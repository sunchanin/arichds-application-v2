"""Poller — the acquisition chain, exercised with the test-only fake meter (M3-1).

Step 5's exit condition: a tick writes a row with a UTC ``read_at`` and kWh
energy. Also pins the decisions that matter architecturally — the lock keys on
the Transport Endpoint, polling follows license state (ADR 0001), a Manual Read
outranks a background tick (ADR 0006), and a device whose model has no driver
never gets a worker.

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
from arichds.config import Settings
from arichds.constants import INTERVAL_LABEL_INSTANTANEOUS, SOURCE_DLMS
from arichds.db.models import Device, IntervalReading
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
