"""Poller — the acquisition chain, exercised with the test-only fake meter (M3-1).

Step 5's exit condition: a tick writes a row with a UTC ``read_at`` and kWh
energy. Also pins the decisions that matter architecturally — the lock keys on
the Transport Endpoint, polling follows license state (ADR 0001), a Manual Read
outranks a background tick (ADR 0006), and a device whose model has no driver
never gets a worker.

M3-2 adds the other half: what a tick's outcome does to the device's status
(ADR 0004). The state machine itself is tested in ``test_device_status.py``;
what belongs here is the *wiring* — that ``STORED`` and ``FAILED`` reach the
recorder, that ``SKIPPED`` reaches nothing at all, and that the strike counter
survives ``restart()`` respawning every worker.

Nothing here touches a real meter: ``fake_meter`` swaps the driver registry.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime

import pytest
from fakes import FakeMeterDriver, FakeMeterState
from sqlalchemy import select

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.factory import create_driver, supported_models
from arichds.acquisition.locks import EndpointLocks, endpoint_locks
from arichds.acquisition.poller import Poller, TickOutcome, build_driver, poll_once, store_reading
from arichds.acquisition.status import DeviceEventKind, DeviceStatus, record_failure
from arichds.config import Settings
from arichds.constants import INTERVAL_LABEL_INSTANTANEOUS, OFFLINE_AFTER_CONSECUTIVE_FAILURES, SOURCE_DLMS
from arichds.db.models import Device, DeviceEvent, IntervalReading
from arichds.db.session import session_scope
from arichds.licensing.service import STATE_ACTIVE, STATE_LIMITED, LicenseState


@pytest.fixture
def meter_device(migrated_db: Settings, fake_meter: FakeMeterState) -> Device:
    """A saved, enabled device whose model resolves to the fake driver."""
    with session_scope() as session:
        device = Device(
            name="Main Incomer",
            brand="cewe",
            model="prometer100",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            enabled=True,
        )
        session.add(device)
        session.flush()
        session.expunge(device)
        return device


class TestFactory:
    def test_prometer100_is_registered(self) -> None:
        assert "prometer100" in supported_models()

    def test_sim_is_gone(self) -> None:
        """ADR 0005 removed the simulated driver from the product."""
        assert "sim" not in supported_models()

    def test_model_lookup_is_case_insensitive(self, fake_meter: FakeMeterState) -> None:
        driver = create_driver("PROMETER100", ConnectionParams.net("127.0.0.1", 4059))
        assert isinstance(driver, FakeMeterDriver)

    def test_unknown_model_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown meter model"):
            create_driver("no-such-meter", ConnectionParams.net("127.0.0.1", 4059))


class TestBuildDriver:
    def test_builds_from_the_stored_transport(self, meter_device: Device) -> None:
        driver = build_driver(meter_device)
        assert driver.endpoint == "127.0.0.1:4059"

    def test_missing_transport_is_an_error(self) -> None:
        device = Device(name="Broken", brand="cewe", model="prometer100", transport={})
        with pytest.raises(ValueError, match="no usable transport"):
            build_driver(device)


class TestPollOnce:
    def test_tick_writes_one_row(self, meter_device: Device) -> None:
        assert poll_once(meter_device, EndpointLocks(), threading.Event()) is TickOutcome.STORED

        with session_scope() as session:
            assert len(session.scalars(select(IntervalReading)).all()) == 1

    def test_stored_row_is_utc_and_kwh(self, meter_device: Device) -> None:
        poll_once(meter_device, EndpointLocks(), threading.Event())

        with session_scope() as session:
            row = session.scalars(select(IntervalReading)).one()
            # UTC: SQLite drops tzinfo, so compare the wall clock against now.
            stored = row.read_at.replace(tzinfo=UTC)
            assert abs((datetime.now(UTC) - stored).total_seconds()) < 60
            # kWh: the column name promises kWh and the value is plausible.
            assert row.import_active_kwh is not None
            assert row.import_active_kwh > 0
            assert row.interval == INTERVAL_LABEL_INSTANTANEOUS
            assert row.source == SOURCE_DLMS

    def test_two_ticks_write_two_rows(self, meter_device: Device) -> None:
        locks = EndpointLocks()
        poll_once(meter_device, locks, threading.Event())
        poll_once(meter_device, locks, threading.Event())

        with session_scope() as session:
            assert len(session.scalars(select(IntervalReading)).all()) == 2

    def test_a_failing_meter_does_not_raise(self, meter_device: Device, fake_meter: FakeMeterState) -> None:
        """One unreachable meter must not take the Poller down."""
        fake_meter.connect_error = ConnectionError("meter is down")

        assert poll_once(meter_device, EndpointLocks(), threading.Event()) is TickOutcome.FAILED
        with session_scope() as session:
            assert session.scalars(select(IntervalReading)).all() == []

    def test_a_failing_meter_is_still_disconnected(self, meter_device: Device, fake_meter: FakeMeterState) -> None:
        fake_meter.connect_error = ConnectionError("meter is down")
        poll_once(meter_device, EndpointLocks(), threading.Event())
        assert fake_meter.disconnects == 1

    def test_an_undrivable_model_fails_without_shouting(
        self, migrated_db: Settings, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The backstop path: FAILED and one WARNING, never a stack trace."""
        device = Device(
            name="Old Sim",
            brand="SIM",
            model="sim",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
        )
        with caplog.at_level(logging.WARNING, logger="arichds.acquisition.poller"):
            outcome = poll_once(device, EndpointLocks(), threading.Event())

        assert outcome is TickOutcome.FAILED
        assert "Cannot build a driver" in caplog.text
        assert "Traceback" not in caplog.text


class TestManualReadsOutrankTicks:
    """ADR 0006 — the four properties, proved through ``poll_once``."""

    def test_a_tick_is_skipped_while_a_manual_read_holds_the_endpoint(self, meter_device: Device) -> None:
        locks = EndpointLocks()
        with locks.get("127.0.0.1:4059").manual():
            outcome = poll_once(meter_device, locks, threading.Event())

        assert outcome is TickOutcome.SKIPPED
        with session_scope() as session:
            assert session.scalars(select(IntervalReading)).all() == []

    def test_skipped_is_not_failed(self, meter_device: Device) -> None:
        """Issue #5's 3-consecutive-failures rule depends on exactly this."""
        locks = EndpointLocks()
        with locks.get("127.0.0.1:4059").manual():
            skipped = poll_once(meter_device, locks, threading.Event())

        assert skipped is TickOutcome.SKIPPED
        assert skipped is not TickOutcome.FAILED
        assert TickOutcome.SKIPPED != TickOutcome.FAILED

    def test_background_polling_starves_under_sustained_manual_load(self, meter_device: Device) -> None:
        """A documented consequence of ADR 0006, asserted rather than assumed."""
        locks = EndpointLocks()
        lock = locks.get("127.0.0.1:4059")
        outcomes = []
        for _ in range(5):
            with lock.manual():
                outcomes.append(poll_once(meter_device, locks, threading.Event()))

        assert outcomes == [TickOutcome.SKIPPED] * 5
        with session_scope() as session:
            assert session.scalars(select(IntervalReading)).all() == []

    def test_a_tick_runs_again_once_the_manual_read_lets_go(self, meter_device: Device) -> None:
        locks = EndpointLocks()
        with locks.get("127.0.0.1:4059").manual():
            assert poll_once(meter_device, locks, threading.Event()) is TickOutcome.SKIPPED
        assert poll_once(meter_device, locks, threading.Event()) is TickOutcome.STORED

    def test_a_tick_in_flight_is_never_interrupted(self, meter_device: Device, fake_meter: FakeMeterState) -> None:
        """The Manual Read waits its turn; the tick still stores its row."""
        locks = EndpointLocks()
        fake_meter.hold_read = threading.Event()
        outcome: list[TickOutcome] = []

        def tick() -> None:
            outcome.append(poll_once(meter_device, locks, threading.Event()))

        worker = threading.Thread(target=tick, daemon=True)
        worker.start()
        assert fake_meter.entered_read.wait(timeout=5), "the tick never started reading"

        manual_in = threading.Event()

        def manual() -> None:
            with locks.get("127.0.0.1:4059").manual(timeout=10):
                manual_in.set()

        reader = threading.Thread(target=manual, daemon=True)
        reader.start()

        # The Manual Read cannot be inside while the tick holds the endpoint.
        assert not manual_in.wait(timeout=0.2)
        fake_meter.hold_read.set()
        worker.join(timeout=5)
        assert manual_in.wait(timeout=5)
        reader.join(timeout=5)

        assert outcome == [TickOutcome.STORED]


class TestStoreReading:
    def test_persists_every_column(self, meter_device: Device, fake_meter: FakeMeterState) -> None:
        driver = FakeMeterDriver(ConnectionParams.net("127.0.0.1", 4059))
        reading = driver.read_instantaneous()
        store_reading(meter_device.id, reading)

        with session_scope() as session:
            row = session.scalars(select(IntervalReading)).one()
            assert row.volt_l1 == reading.volt_l1
            assert row.current_l3 == reading.current_l3
            assert row.freq == reading.freq
            assert row.import_active_kwh == reading.import_active_kwh


class TestPollerLifecycle:
    def test_starts_a_worker_per_enabled_device(self, meter_device: Device) -> None:
        poller = Poller(interval_sec=0.05, locks=EndpointLocks())
        try:
            poller.start()
            assert poller.running
        finally:
            poller.stop()
        assert not poller.running

    def test_start_is_idempotent(self, meter_device: Device) -> None:
        poller = Poller(interval_sec=0.05, locks=EndpointLocks())
        try:
            poller.start()
            poller.start()
            assert poller.running
        finally:
            poller.stop()

    def test_stop_is_idempotent(self, meter_device: Device) -> None:
        poller = Poller(interval_sec=0.05, locks=EndpointLocks())
        poller.start()
        poller.stop()
        poller.stop()
        assert not poller.running

    def test_worker_ticks_and_writes(self, meter_device: Device) -> None:
        ticked = threading.Event()

        def fake_poll(device, locks, shutdown):  # noqa: ANN001
            outcome = poll_once(device, locks, shutdown)
            ticked.set()
            return outcome

        poller = Poller(interval_sec=0.05, poll_fn=fake_poll, locks=EndpointLocks())
        try:
            poller.start()
            assert ticked.wait(timeout=5), "poller never ticked"
        finally:
            poller.stop()

        with session_scope() as session:
            assert len(session.scalars(select(IntervalReading)).all()) >= 1

    def test_disabled_devices_get_no_worker(self, migrated_db: Settings, fake_meter: FakeMeterState) -> None:
        with session_scope() as session:
            session.add(
                Device(
                    name="Paused",
                    brand="cewe",
                    model="prometer100",
                    transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
                    enabled=False,
                )
            )

        poller = Poller(interval_sec=0.05, locks=EndpointLocks())
        try:
            poller.start()
            assert poller._threads == []
        finally:
            poller.stop()


class TestUndrivableModelsGetNoWorker:
    """A pre-M3 row whose model has no driver must cost nothing (D4)."""

    @pytest.fixture
    def orphan(self, migrated_db: Settings, fake_meter: FakeMeterState) -> None:
        with session_scope() as session:
            session.add(
                Device(
                    name="Old Sim",
                    brand="SIM",
                    model="sim",
                    transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
                    enabled=True,
                )
            )

    def test_no_worker_is_created(self, orphan: None) -> None:
        poller = Poller(interval_sec=0.05, locks=EndpointLocks())
        try:
            poller.start()
            assert poller._threads == []
            assert live_workers_for("Old Sim") == []
        finally:
            poller.stop()

    def test_it_is_logged_once_per_start(self, orphan: None, caplog: pytest.LogCaptureFixture) -> None:
        """Not a flood: one line per start, naming the device and the model."""
        poller = Poller(interval_sec=0.05, locks=EndpointLocks())
        with caplog.at_level(logging.WARNING, logger="arichds.acquisition.poller"):
            try:
                poller.start()
            finally:
                poller.stop()

        lines = [record for record in caplog.records if "has no driver in this build" in record.getMessage()]
        assert len(lines) == 1
        assert "Old Sim" in lines[0].getMessage()
        assert "sim" in lines[0].getMessage()

    def test_a_drivable_device_beside_it_still_polls(self, orphan: None, meter_device: Device) -> None:
        poller = Poller(interval_sec=0.05, locks=EndpointLocks())
        try:
            poller.start()
            assert [t.name for t in poller._threads] == [f"poller-{meter_device.name}"]
        finally:
            poller.stop()


class TestTheLockRegistryIsProcessWide:
    """D1 — a probe must find the same lock the Poller uses, always."""

    def test_the_default_registry_is_the_process_one(self) -> None:
        assert Poller(enabled=False)._locks is endpoint_locks()

    def test_the_registry_survives_a_restart(self, meter_device: Device) -> None:
        """``create_device`` and ``delete_device`` both call ``restart()``."""
        poller = Poller(interval_sec=0.05)
        try:
            poller.start()
            before = poller._locks.get("127.0.0.1:4059")
            poller.restart()
            after = poller._locks.get("127.0.0.1:4059")
        finally:
            poller.stop()

        assert before is after
        assert after is endpoint_locks().get("127.0.0.1:4059")


def live_workers_for(device_name: str) -> list[threading.Thread]:
    """Every live Poller worker thread for *device_name*.

    The Poller names its threads ``poller-<device name>``, so counting them is
    how "exactly one worker per device" gets asserted.
    """
    return [t for t in threading.enumerate() if t.is_alive() and t.name == f"poller-{device_name}"]


class TestRestartDoesNotLeakWorkers:
    """SPEC §4 budgets 2 + n threads. A restart must not smuggle in extras.

    ``create_device`` and ``delete_device`` both call ``restart()``, and a real
    DLMS tick takes seconds (up to the 60 s read timeout on an unreachable
    meter). So a restart landing mid-tick is the normal case on a live site,
    not a corner case.
    """

    def test_restart_mid_tick_leaves_exactly_one_worker(self, meter_device: Device) -> None:
        in_tick = threading.Event()
        release = threading.Event()

        def slow_poll(device, locks, shutdown):  # noqa: ANN001
            in_tick.set()
            release.wait(timeout=10)
            return TickOutcome.FAILED

        # stop_timeout shorter than the tick, so the join times out exactly the
        # way a 60 s meter read makes it time out in production.
        poller = Poller(interval_sec=0.05, stop_timeout=0.1, poll_fn=slow_poll, locks=EndpointLocks())
        try:
            poller.start()
            assert in_tick.wait(timeout=5), "worker never entered its tick"

            poller.restart()  # abandons a worker that is still inside poll_fn
            release.set()  # let the abandoned tick run to completion

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if len(live_workers_for(meter_device.name)) <= 1:
                    break
                time.sleep(0.05)

            assert len(live_workers_for(meter_device.name)) == 1, (
                "the worker abandoned by restart() kept polling alongside its replacement"
            )
        finally:
            release.set()
            poller.stop()

    def test_abandoned_worker_stops_even_though_start_rebound_the_event(self, meter_device: Device) -> None:
        """The event a worker watches must be the one its own start() set.

        Binding at thread creation is the fix: ``stop()`` sets event A, then
        ``start()`` rebinds the attribute to a fresh unset event B. A worker
        that re-reads the attribute would see B and poll forever.
        """
        ticks: list[float] = []
        release = threading.Event()

        def slow_poll(device, locks, shutdown):  # noqa: ANN001
            ticks.append(time.monotonic())
            release.wait(timeout=10)
            return TickOutcome.FAILED

        poller = Poller(interval_sec=0.05, stop_timeout=0.1, poll_fn=slow_poll, locks=EndpointLocks())
        poller.start()
        try:
            deadline = time.monotonic() + 5
            while not ticks and time.monotonic() < deadline:
                time.sleep(0.02)
            poller.stop()  # join times out; worker is parked inside poll_fn
            poller.start()  # rebinds self._shutdown to a fresh, unset event
            release.set()

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if len(live_workers_for(meter_device.name)) <= 1:
                    break
                time.sleep(0.05)
            assert len(live_workers_for(meter_device.name)) == 1
        finally:
            release.set()
            poller.stop()

    def test_stop_logs_when_a_join_times_out(self, meter_device: Device, caplog: pytest.LogCaptureFixture) -> None:
        """A worker that outlives its join must be visible, not silent."""
        release = threading.Event()
        in_tick = threading.Event()

        def slow_poll(device, locks, shutdown):  # noqa: ANN001
            in_tick.set()
            release.wait(timeout=10)
            return TickOutcome.FAILED

        poller = Poller(interval_sec=0.05, stop_timeout=0.1, poll_fn=slow_poll, locks=EndpointLocks())
        poller.start()
        try:
            assert in_tick.wait(timeout=5)
            with caplog.at_level(logging.WARNING, logger="arichds.acquisition.poller"):
                poller.stop()
            assert "did not stop within" in caplog.text
        finally:
            release.set()
            poller.stop()


def device_row(device_id: int) -> Device:
    """A detached snapshot of one device row."""
    with session_scope() as session:
        device = session.get(Device, device_id)
        session.expunge(device)
        return device


def event_kinds(device_id: int) -> list[str]:
    """Every Device Event kind recorded for *device_id*, oldest first."""
    with session_scope() as session:
        return list(
            session.scalars(select(DeviceEvent.kind).where(DeviceEvent.device_id == device_id).order_by(DeviceEvent.id))
        )


def wait_until(predicate, *, timeout: float = 5.0) -> bool:  # noqa: ANN001
    """Poll *predicate* until it is true or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class TestTheWorkerRecordsWhatItsTickProved:
    """ADR 0004 — the tick's outcome is the status signal, mapped in ``_worker``."""

    def test_a_stored_tick_reports_online(self, meter_device: Device) -> None:
        poller = Poller(interval_sec=0.05, poll_fn=lambda d, locks, s: TickOutcome.STORED, locks=EndpointLocks())
        try:
            poller.start()
            assert wait_until(lambda: device_row(meter_device.id).status == DeviceStatus.ONLINE)
        finally:
            poller.stop()

    def test_a_failed_tick_is_a_strike(self, meter_device: Device) -> None:
        poller = Poller(interval_sec=0.05, poll_fn=lambda d, locks, s: TickOutcome.FAILED, locks=EndpointLocks())
        try:
            poller.start()
            assert wait_until(lambda: device_row(meter_device.id).status == DeviceStatus.OFFLINE)
        finally:
            poller.stop()

    def test_a_driver_that_raises_can_still_reach_offline(self, meter_device: Device) -> None:
        """D6 — an unhandled exception is a failure, not a hole in the rule."""

        def exploding_poll(device, locks, shutdown):  # noqa: ANN001
            raise RuntimeError("the driver blew up")

        poller = Poller(interval_sec=0.05, poll_fn=exploding_poll, locks=EndpointLocks())
        try:
            poller.start()
            assert wait_until(lambda: device_row(meter_device.id).status == DeviceStatus.OFFLINE)
        finally:
            poller.stop()
        assert event_kinds(meter_device.id) == [DeviceEventKind.OFFLINE]


class TestASkippedTickIsInert:
    """ADR 0006 — a tick that never ran must report nothing at all (D3)."""

    def test_it_touches_no_status_column(self, meter_device: Device) -> None:
        locks = EndpointLocks()
        outcomes: list[TickOutcome] = []

        def counting_poll(device, locks_, shutdown):  # noqa: ANN001
            outcome = poll_once(device, locks_, shutdown)
            outcomes.append(outcome)
            return outcome

        poller = Poller(interval_sec=0.02, poll_fn=counting_poll, locks=locks)
        # A Manual Read holds the endpoint for the whole run, so every tick skips.
        with locks.get("127.0.0.1:4059").manual():
            try:
                poller.start()
                assert wait_until(lambda: len(outcomes) >= 3), "the poller never ticked"
            finally:
                poller.stop()

        assert set(outcomes) == {TickOutcome.SKIPPED}
        device = device_row(meter_device.id)
        assert device.status == DeviceStatus.UNKNOWN
        assert device.status_checked_at is None
        assert device.consecutive_failures == 0
        assert event_kinds(meter_device.id) == []

    def test_a_skip_does_not_reset_the_streak(self, meter_device: Device) -> None:
        """FAILED, FAILED, SKIPPED, FAILED still reaches Offline."""
        script = [TickOutcome.FAILED, TickOutcome.FAILED, TickOutcome.SKIPPED, TickOutcome.FAILED]
        remaining = list(script)
        finished = threading.Event()

        def scripted_poll(device, locks, shutdown):  # noqa: ANN001
            if not remaining:
                finished.set()
                return TickOutcome.SKIPPED
            return remaining.pop(0)

        poller = Poller(interval_sec=0.02, poll_fn=scripted_poll, locks=EndpointLocks())
        try:
            poller.start()
            assert finished.wait(timeout=5), "the poller never ran the script"
        finally:
            poller.stop()

        device = device_row(meter_device.id)
        assert device.status == DeviceStatus.OFFLINE
        assert device.consecutive_failures == OFFLINE_AFTER_CONSECUTIVE_FAILURES
        assert event_kinds(meter_device.id) == [DeviceEventKind.OFFLINE]


class TestTheStrikeCounterSurvivesARestart:
    """Trap 2 — ``restart()`` builds brand-new threads (D1).

    If the counter lived in a worker's local variable, adding one device would
    reset the streak of every device on the site and a genuinely dead meter would
    never reach three.
    """

    def test_deterministically(self, meter_device: Device) -> None:
        # An inert poll_fn: the Poller must be genuinely running for restart()
        # to respawn anything, but its ticks must not disturb the counter.
        poller = Poller(interval_sec=0.02, poll_fn=lambda d, locks, s: TickOutcome.SKIPPED, locks=EndpointLocks())
        try:
            poller.start()
            record_failure(meter_device.id)
            record_failure(meter_device.id)
            assert device_row(meter_device.id).status != DeviceStatus.OFFLINE

            poller.restart()

            record_failure(meter_device.id)
        finally:
            poller.stop()

        assert device_row(meter_device.id).status == DeviceStatus.OFFLINE
        assert event_kinds(meter_device.id) == [DeviceEventKind.OFFLINE]

    def test_through_a_running_poller(self, meter_device: Device) -> None:
        # One permit per tick, so the number of recorded failures is exactly the
        # number the test released — whichever worker happens to take it.
        permits = threading.Semaphore(0)

        def gated_poll(device, locks, shutdown):  # noqa: ANN001
            if not permits.acquire(timeout=2):
                return TickOutcome.SKIPPED  # inert — never a strike
            return TickOutcome.FAILED

        poller = Poller(interval_sec=0.02, stop_timeout=0.2, poll_fn=gated_poll, locks=EndpointLocks())
        try:
            poller.start()
            permits.release()
            permits.release()
            assert wait_until(lambda: device_row(meter_device.id).consecutive_failures == 2)
            assert device_row(meter_device.id).status != DeviceStatus.OFFLINE

            poller.restart()

            permits.release()
            assert wait_until(lambda: device_row(meter_device.id).status == DeviceStatus.OFFLINE)
        finally:
            poller.stop()

        assert event_kinds(meter_device.id) == [DeviceEventKind.OFFLINE]


class TestADeviceWithNoDriverSaysWhy:
    """An operator who resumes a parked pre-M3 row must see a reason, not silence."""

    @pytest.fixture
    def orphan_id(self, migrated_db: Settings, fake_meter: FakeMeterState) -> int:
        with session_scope() as session:
            device = Device(
                name="Old Sim",
                brand="SIM",
                model="sim",
                site_name="Plant A",
                transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
                enabled=True,
            )
            session.add(device)
            session.flush()
            return device.id

    def test_it_ends_at_unknown_with_a_reason(self, orphan_id: int) -> None:
        poller = Poller(interval_sec=0.05, locks=EndpointLocks())
        try:
            poller.start()
        finally:
            poller.stop()

        device = device_row(orphan_id)
        assert device.status == DeviceStatus.UNKNOWN
        assert device.status_detail is not None
        assert "sim" in device.status_detail

    def test_it_never_drifts_to_offline(self, orphan_id: int) -> None:
        """No worker ever runs for it, so no tick can ever strike it out."""
        poller = Poller(interval_sec=0.05, locks=EndpointLocks())
        try:
            poller.start()
            time.sleep(0.2)
        finally:
            poller.stop()

        device = device_row(orphan_id)
        assert device.status != DeviceStatus.OFFLINE
        assert device.consecutive_failures == 0
        assert event_kinds(orphan_id) == []


class TestPollerMasterSwitch:
    """``ARICHDS_POLL_ENABLED=false`` must hold even with a valid license."""

    def test_disabled_poller_does_not_start(self, meter_device: Device) -> None:
        poller = Poller(interval_sec=0.05, enabled=False, locks=EndpointLocks())
        poller.start()
        assert not poller.running

    def test_disabled_poller_ignores_a_valid_license(self, meter_device: Device) -> None:
        poller = Poller(interval_sec=0.05, enabled=False, locks=EndpointLocks())
        poller.on_license_state(LicenseState(state=STATE_ACTIVE, reason=None))
        assert not poller.running


class TestPollerFollowsLicenseState:
    """SPEC §3.9 — polling stops in Limited Mode, starts on activation."""

    def test_valid_license_starts_polling(self, meter_device: Device) -> None:
        poller = Poller(interval_sec=0.05, locks=EndpointLocks())
        try:
            poller.on_license_state(LicenseState(state=STATE_ACTIVE, reason=None))
            assert poller.running
        finally:
            poller.stop()

    def test_limited_mode_stops_polling(self, meter_device: Device) -> None:
        poller = Poller(interval_sec=0.05, locks=EndpointLocks())
        poller.on_license_state(LicenseState(state=STATE_ACTIVE, reason=None))
        poller.on_license_state(LicenseState(state=STATE_LIMITED, reason="NO_LICENSE"))
        assert not poller.running
