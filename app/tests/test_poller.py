"""Poller — the acquisition chain, exercised with the simulated driver.

Step 5's exit condition: a tick writes a row with a UTC ``read_at`` and kWh
energy. Also pins the two decisions that matter architecturally — the lock keys
on the Transport Endpoint, and polling follows license state (ADR 0001).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.factory import create_driver, supported_models
from arichds.acquisition.drivers.simulated import SimulatedDriver
from arichds.acquisition.poller import EndpointLocks, Poller, build_driver, poll_once, store_reading
from arichds.config import Settings
from arichds.constants import INTERVAL_LABEL_INSTANTANEOUS, SOURCE_SIMULATED
from arichds.db.models import Device, IntervalReading
from arichds.db.session import session_scope
from arichds.licensing.service import STATE_ACTIVE, STATE_LIMITED, LicenseState


@pytest.fixture
def sim_device(migrated_db: Settings) -> Device:
    """A saved, enabled simulated device."""
    with session_scope() as session:
        device = Device(
            name="Sim Meter",
            brand="SIM",
            model="sim",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            enabled=True,
        )
        session.add(device)
        session.flush()
        session.expunge(device)
        return device


class TestFactory:
    def test_sim_is_registered(self) -> None:
        assert "sim" in supported_models()

    def test_prometer100_is_registered(self) -> None:
        assert "prometer100" in supported_models()

    def test_model_lookup_is_case_insensitive(self) -> None:
        driver = create_driver("SIM", ConnectionParams.net("127.0.0.1", 4059))
        assert isinstance(driver, SimulatedDriver)

    def test_unknown_model_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown meter model"):
            create_driver("no-such-meter", ConnectionParams.net("127.0.0.1", 4059))


class TestSimulatedDriver:
    def test_reading_is_utc_aware(self) -> None:
        driver = SimulatedDriver(ConnectionParams.net("127.0.0.1", 4059))
        reading = driver.read_instantaneous()
        assert reading.read_at.tzinfo is not None
        assert reading.read_at.utcoffset() == datetime.now(UTC).utcoffset()

    def test_values_are_plausible(self) -> None:
        driver = SimulatedDriver(ConnectionParams.net("127.0.0.1", 4059))
        reading = driver.read_instantaneous()
        assert 200 < reading.volt_l1 < 260
        assert 200 < reading.volt_l2 < 260
        assert 200 < reading.volt_l3 < 260
        assert 45 < reading.freq < 55
        assert reading.current_l1 is not None

    def test_energy_register_advances(self) -> None:
        """A cumulative import register must never go backwards."""
        driver = SimulatedDriver(ConnectionParams.net("127.0.0.1", 4059))
        first = driver.read_instantaneous().import_active_kwh
        second = driver.read_instantaneous().import_active_kwh
        assert second > first

    def test_state_survives_a_fresh_driver_for_the_same_endpoint(self) -> None:
        """The Poller builds a NEW driver every tick — state cannot live on the instance.

        This is the gap the instance-reuse test above cannot see: on the real
        poll path each tick constructs a fresh ``SimulatedDriver``, so per-instance
        counters reset and the simulation freezes.
        """
        conn = ConnectionParams.net("10.9.9.9", 4059)
        first = SimulatedDriver(conn).read_instantaneous().import_active_kwh
        second = SimulatedDriver(conn).read_instantaneous().import_active_kwh
        assert second > first

    def test_separate_endpoints_keep_separate_state(self) -> None:
        one = SimulatedDriver(ConnectionParams.net("10.9.9.1", 4059)).read_instantaneous()
        two = SimulatedDriver(ConnectionParams.net("10.9.9.2", 4059)).read_instantaneous()
        assert one.import_active_kwh != two.import_active_kwh

    def test_source_is_sim_not_dlms(self) -> None:
        driver = SimulatedDriver(ConnectionParams.net("127.0.0.1", 4059))
        assert driver.read_instantaneous().source == SOURCE_SIMULATED

    def test_values_drift_between_ticks(self) -> None:
        driver = SimulatedDriver(ConnectionParams.net("127.0.0.1", 4059))
        readings = [driver.read_instantaneous().volt_l1 for _ in range(5)]
        assert len(set(readings)) > 1


class TestEndpointLocks:
    def test_same_endpoint_shares_one_lock(self) -> None:
        """Devices on one line queue behind a single lock (REMAKE-PLAN §3.2)."""
        locks = EndpointLocks()
        assert locks.get("10.0.0.1:4059") is locks.get("10.0.0.1:4059")

    def test_different_endpoints_get_different_locks(self) -> None:
        locks = EndpointLocks()
        assert locks.get("10.0.0.1:4059") is not locks.get("10.0.0.2:4059")


class TestBuildDriver:
    def test_builds_from_the_stored_transport(self, sim_device: Device) -> None:
        driver = build_driver(sim_device)
        assert driver.endpoint == "127.0.0.1:4059"

    def test_missing_transport_is_an_error(self) -> None:
        device = Device(name="Broken", brand="SIM", model="sim", transport={})
        with pytest.raises(ValueError, match="no usable transport"):
            build_driver(device)


class TestPollOnce:
    def test_tick_writes_one_row(self, sim_device: Device) -> None:
        row_id = poll_once(sim_device, EndpointLocks(), threading.Event())
        assert row_id is not None

        with session_scope() as session:
            rows = session.scalars(select(IntervalReading)).all()
            assert len(rows) == 1

    def test_stored_row_is_utc_and_kwh(self, sim_device: Device) -> None:
        poll_once(sim_device, EndpointLocks(), threading.Event())

        with session_scope() as session:
            row = session.scalars(select(IntervalReading)).one()
            # UTC: SQLite drops tzinfo, so compare the wall clock against now.
            stored = row.read_at.replace(tzinfo=UTC)
            assert abs((datetime.now(UTC) - stored).total_seconds()) < 60
            # kWh: the column name promises kWh and the value is plausible.
            assert row.import_active_kwh is not None
            assert row.import_active_kwh > 0
            assert row.interval == INTERVAL_LABEL_INSTANTANEOUS
            assert row.source == SOURCE_SIMULATED

    def test_two_ticks_write_two_rows(self, sim_device: Device) -> None:
        locks = EndpointLocks()
        poll_once(sim_device, locks, threading.Event())
        poll_once(sim_device, locks, threading.Event())

        with session_scope() as session:
            assert len(session.scalars(select(IntervalReading)).all()) == 2

    def test_simulated_values_move_across_ticks_on_the_real_path(self, sim_device: Device) -> None:
        """SIM is user-visible (the Monitor model dropdown), so it must look live.

        Driven through ``poll_once`` — the path the Poller actually takes, which
        builds a fresh driver every tick — rather than one reused instance.
        """
        locks = EndpointLocks()
        for _ in range(3):
            poll_once(sim_device, locks, threading.Event())

        with session_scope() as session:
            rows = session.scalars(select(IntervalReading).order_by(IntervalReading.id)).all()
            energies = [row.import_active_kwh for row in rows]
            volts = [row.volt_l1 for row in rows]

        assert len(energies) == 3
        assert energies[0] < energies[1] < energies[2], "the cumulative register never advanced"
        assert len(set(volts)) > 1, "voltage was frozen at a single sine phase"

    def test_a_failing_meter_does_not_raise(self, migrated_db: Settings, monkeypatch) -> None:
        """One unreachable meter must not take the Poller down."""
        with session_scope() as session:
            device = Device(
                name="Unreachable",
                brand="SIM",
                model="sim",
                transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            )
            session.add(device)
            session.flush()
            session.expunge(device)

        def boom(self) -> None:
            raise ConnectionError("meter is down")

        monkeypatch.setattr(SimulatedDriver, "connect", boom)

        assert poll_once(device, EndpointLocks(), threading.Event()) is None
        with session_scope() as session:
            assert session.scalars(select(IntervalReading)).all() == []


class TestStoreReading:
    def test_persists_every_column(self, sim_device: Device) -> None:
        driver = SimulatedDriver(ConnectionParams.net("127.0.0.1", 4059))
        reading = driver.read_instantaneous()
        store_reading(sim_device.id, reading)

        with session_scope() as session:
            row = session.scalars(select(IntervalReading)).one()
            assert row.volt_l1 == reading.volt_l1
            assert row.current_l3 == reading.current_l3
            assert row.freq == reading.freq
            assert row.import_active_kwh == reading.import_active_kwh


class TestPollerLifecycle:
    def test_starts_a_worker_per_enabled_device(self, sim_device: Device) -> None:
        poller = Poller(interval_sec=0.05)
        try:
            poller.start()
            assert poller.running
        finally:
            poller.stop()
        assert not poller.running

    def test_start_is_idempotent(self, sim_device: Device) -> None:
        poller = Poller(interval_sec=0.05)
        try:
            poller.start()
            poller.start()
            assert poller.running
        finally:
            poller.stop()

    def test_stop_is_idempotent(self, sim_device: Device) -> None:
        poller = Poller(interval_sec=0.05)
        poller.start()
        poller.stop()
        poller.stop()
        assert not poller.running

    def test_worker_ticks_and_writes(self, sim_device: Device) -> None:
        ticked = threading.Event()

        def fake_poll(device, locks, shutdown):  # noqa: ANN001
            row_id = poll_once(device, locks, shutdown)
            ticked.set()
            return row_id

        poller = Poller(interval_sec=0.05, poll_fn=fake_poll)
        try:
            poller.start()
            assert ticked.wait(timeout=5), "poller never ticked"
        finally:
            poller.stop()

        with session_scope() as session:
            assert len(session.scalars(select(IntervalReading)).all()) >= 1

    def test_disabled_devices_get_no_worker(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            session.add(
                Device(
                    name="Paused",
                    brand="SIM",
                    model="sim",
                    transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
                    enabled=False,
                )
            )

        poller = Poller(interval_sec=0.05)
        try:
            poller.start()
            assert poller._threads == []
        finally:
            poller.stop()


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

    def test_restart_mid_tick_leaves_exactly_one_worker(self, sim_device: Device) -> None:
        in_tick = threading.Event()
        release = threading.Event()

        def slow_poll(device, locks, shutdown):  # noqa: ANN001
            in_tick.set()
            release.wait(timeout=10)
            return None

        # stop_timeout shorter than the tick, so the join times out exactly the
        # way a 60 s meter read makes it time out in production.
        poller = Poller(interval_sec=0.05, stop_timeout=0.1, poll_fn=slow_poll)
        try:
            poller.start()
            assert in_tick.wait(timeout=5), "worker never entered its tick"

            poller.restart()  # abandons a worker that is still inside poll_fn
            release.set()  # let the abandoned tick run to completion

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if len(live_workers_for(sim_device.name)) <= 1:
                    break
                time.sleep(0.05)

            assert len(live_workers_for(sim_device.name)) == 1, (
                "the worker abandoned by restart() kept polling alongside its replacement"
            )
        finally:
            release.set()
            poller.stop()

    def test_abandoned_worker_stops_even_though_start_rebound_the_event(self, sim_device: Device) -> None:
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
            return None

        poller = Poller(interval_sec=0.05, stop_timeout=0.1, poll_fn=slow_poll)
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
                if len(live_workers_for(sim_device.name)) <= 1:
                    break
                time.sleep(0.05)
            assert len(live_workers_for(sim_device.name)) == 1
        finally:
            release.set()
            poller.stop()

    def test_stop_logs_when_a_join_times_out(self, sim_device: Device, caplog: pytest.LogCaptureFixture) -> None:
        """A worker that outlives its join must be visible, not silent."""
        release = threading.Event()
        in_tick = threading.Event()

        def slow_poll(device, locks, shutdown):  # noqa: ANN001
            in_tick.set()
            release.wait(timeout=10)
            return None

        poller = Poller(interval_sec=0.05, stop_timeout=0.1, poll_fn=slow_poll)
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

    def test_disabled_poller_does_not_start(self, sim_device: Device) -> None:
        poller = Poller(interval_sec=0.05, enabled=False)
        poller.start()
        assert not poller.running

    def test_disabled_poller_ignores_a_valid_license(self, sim_device: Device) -> None:
        poller = Poller(interval_sec=0.05, enabled=False)
        poller.on_license_state(LicenseState(state=STATE_ACTIVE, reason=None))
        assert not poller.running


class TestPollerFollowsLicenseState:
    """SPEC §3.9 — polling stops in Limited Mode, starts on activation."""

    def test_valid_license_starts_polling(self, sim_device: Device) -> None:
        poller = Poller(interval_sec=0.05)
        try:
            poller.on_license_state(LicenseState(state=STATE_ACTIVE, reason=None))
            assert poller.running
        finally:
            poller.stop()

    def test_limited_mode_stops_polling(self, sim_device: Device) -> None:
        poller = Poller(interval_sec=0.05)
        poller.on_license_state(LicenseState(state=STATE_ACTIVE, reason=None))
        poller.on_license_state(LicenseState(state=STATE_LIMITED, reason="NO_LICENSE"))
        assert not poller.running
