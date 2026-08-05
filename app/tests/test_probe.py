"""Probe — reading a meter's identity before anything is written (M3-1).

CONTEXT.md: *"Talking to a meter to read its identity before committing
anything. Creating or updating a device probes first: no serial, no row. A probe
is not a reading — it writes no Interval Reading."*

ADR 0005 is what these tests protect, and ADR 0006 decides how the probe takes
the endpoint: as a **Manual Read**, ahead of any background tick.

The four failure reasons exist because the operator's next action differs for
each — a wrong password and no route to host are not the same problem — so each
one gets its own test rather than a single "it failed" assertion.

Nothing here touches a real meter.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest
from fakes import FakeMeterState
from gurux_dlms import GXDLMSException
from sqlalchemy import select

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.base import MeterConnectionError
from arichds.acquisition.drivers.prometer100 import Prometer100Driver
from arichds.acquisition.locks import EndpointLocks
from arichds.acquisition.probe import ProbeError, ProbeFailure, probe_meter
from arichds.config import Settings
from arichds.constants import METER_SERIAL_OBIS_ATTR, METER_SERIAL_OBIS_CODE
from arichds.db.models import IntervalReading
from arichds.db.session import session_scope

PROBE_ARGS = {"model": "prometer100", "host": "127.0.0.1", "port": 4059, "password": "ABCD0001"}


def probe(**overrides: object):
    """Run a probe against the fake meter with an isolated lock registry."""
    return probe_meter(**{**PROBE_ARGS, "locks": EndpointLocks(), **overrides})  # type: ignore[arg-type]


class TestSuccess:
    def test_returns_the_serial(self, fake_meter: FakeMeterState) -> None:
        fake_meter.meter_serial = "SN-12345"
        assert probe().meter_serial == "SN-12345"

    def test_reports_a_latency(self, fake_meter: FakeMeterState) -> None:
        result = probe()
        assert result.latency_ms is not None
        assert result.latency_ms >= 0

    def test_disconnects_exactly_once(self, fake_meter: FakeMeterState) -> None:
        probe()
        assert fake_meter.connects == 1
        assert fake_meter.disconnects == 1


class TestFailureReasons:
    def test_rejected_credentials_are_auth_failed(self, fake_meter: FakeMeterState) -> None:
        fake_meter.connect_error = GXDLMSException(1)
        with pytest.raises(ProbeError) as caught:
            probe()
        assert caught.value.reason is ProbeFailure.AUTH_FAILED

    def test_timeout_is_timeout(self, fake_meter: FakeMeterState) -> None:
        fake_meter.connect_error = TimeoutError("timed out")
        with pytest.raises(ProbeError) as caught:
            probe()
        assert caught.value.reason is ProbeFailure.TIMEOUT

    def test_socket_timeout_is_timeout(self, fake_meter: FakeMeterState) -> None:
        """``socket.timeout`` is an alias of ``TimeoutError``; pin it anyway."""
        fake_meter.connect_error = TimeoutError("timed out")
        with pytest.raises(ProbeError) as caught:
            probe()
        assert caught.value.reason is ProbeFailure.TIMEOUT

    @pytest.mark.parametrize(
        "error",
        [
            ConnectionRefusedError("refused"),
            ConnectionResetError("reset"),
            ConnectionAbortedError("aborted"),
            socket.gaierror("no such host"),
            OSError("no route to host"),
        ],
        ids=["refused", "reset", "aborted", "gaierror", "oserror"],
    )
    def test_transport_errors_are_unreachable(self, fake_meter: FakeMeterState, error: Exception) -> None:
        fake_meter.connect_error = error
        with pytest.raises(ProbeError) as caught:
            probe()
        assert caught.value.reason is ProbeFailure.UNREACHABLE

    def test_meter_connection_error_is_unreachable(self, fake_meter: FakeMeterState) -> None:
        fake_meter.connect_error = MeterConnectionError("GXSettings parameter error")
        with pytest.raises(ProbeError) as caught:
            probe()
        assert caught.value.reason is ProbeFailure.UNREACHABLE

    def test_an_unexpected_error_is_unreachable(self, fake_meter: FakeMeterState) -> None:
        fake_meter.connect_error = RuntimeError("something nobody predicted")
        with pytest.raises(ProbeError) as caught:
            probe()
        assert caught.value.reason is ProbeFailure.UNREACHABLE

    def test_no_serial_when_the_meter_answers_with_nothing(self, fake_meter: FakeMeterState) -> None:
        fake_meter.meter_serial = None
        with pytest.raises(ProbeError) as caught:
            probe()
        assert caught.value.reason is ProbeFailure.NO_SERIAL

    def test_the_message_never_carries_the_password(self, fake_meter: FakeMeterState) -> None:
        fake_meter.connect_error = GXDLMSException(1)
        with pytest.raises(ProbeError) as caught:
            probe(password="hunter2")
        assert "hunter2" not in str(caught.value)

    def test_the_message_names_the_endpoint(self, fake_meter: FakeMeterState) -> None:
        fake_meter.connect_error = TimeoutError("timed out")
        with pytest.raises(ProbeError) as caught:
            probe()
        assert "127.0.0.1:4059" in str(caught.value)


class TestCleanup:
    def test_disconnect_runs_even_when_the_serial_read_raises(self, fake_meter: FakeMeterState) -> None:
        fake_meter.serial_error = TimeoutError("timed out")
        with pytest.raises(ProbeError):
            probe()
        assert fake_meter.disconnects == 1

    def test_disconnect_runs_even_when_connect_raises(self, fake_meter: FakeMeterState) -> None:
        fake_meter.connect_error = ConnectionRefusedError("refused")
        with pytest.raises(ProbeError):
            probe()
        assert fake_meter.disconnects == 1


class TestUnknownModel:
    def test_raises_before_anything_is_connected(self, fake_meter: FakeMeterState) -> None:
        with pytest.raises(ValueError, match="Unknown meter model"):
            probe(model="no-such-meter")
        assert fake_meter.connects == 0


class TestTheProbeIsAManualRead:
    """ADR 0006 — a Manual Read holds the endpoint ahead of a background tick."""

    def test_a_background_tick_cannot_have_the_endpoint_during_a_probe(self, fake_meter: FakeMeterState) -> None:
        locks = EndpointLocks()
        fake_meter.hold_read = threading.Event()
        result: list[object] = []

        def run_probe() -> None:
            result.append(probe_meter(**PROBE_ARGS, locks=locks))  # type: ignore[arg-type]

        worker = threading.Thread(target=run_probe, daemon=True)
        worker.start()
        try:
            assert fake_meter.entered_read.wait(timeout=5), "the probe never reached the meter"
            assert locks.get("127.0.0.1:4059").try_acquire_background() is False
        finally:
            fake_meter.hold_read.set()
            worker.join(timeout=5)

        assert locks.get("127.0.0.1:4059").try_acquire_background() is True
        locks.get("127.0.0.1:4059").release()
        assert len(result) == 1

    def test_the_endpoint_is_released_after_a_failed_probe(self, fake_meter: FakeMeterState) -> None:
        locks = EndpointLocks()
        fake_meter.connect_error = ConnectionRefusedError("refused")
        with pytest.raises(ProbeError):
            probe_meter(**PROBE_ARGS, locks=locks)  # type: ignore[arg-type]

        assert locks.get("127.0.0.1:4059").try_acquire_background() is True
        locks.get("127.0.0.1:4059").release()


class TestTheWaitForTheEndpointIsBounded:
    """A probe runs inside an HTTP handler, so it must never wait forever.

    A background tick holds the endpoint across a connect plus every register
    read; on a dying meter that is minutes, and an unbounded wait would leave
    ``POST /api/devices`` answering nothing at all.
    """

    def test_a_busy_endpoint_times_out(self, fake_meter: FakeMeterState) -> None:
        locks = EndpointLocks()
        assert locks.get("127.0.0.1:4059").try_acquire_background() is True
        try:
            with pytest.raises(ProbeError) as caught:
                probe_meter(**PROBE_ARGS, locks=locks, lock_timeout_sec=0.05)  # type: ignore[arg-type]
        finally:
            locks.get("127.0.0.1:4059").release()

        assert caught.value.reason is ProbeFailure.TIMEOUT

    def test_it_never_opens_a_connection(self, fake_meter: FakeMeterState) -> None:
        """Giving up on the lock must not touch the meter at all."""
        locks = EndpointLocks()
        assert locks.get("127.0.0.1:4059").try_acquire_background() is True
        try:
            with pytest.raises(ProbeError):
                probe_meter(**PROBE_ARGS, locks=locks, lock_timeout_sec=0.05)  # type: ignore[arg-type]
        finally:
            locks.get("127.0.0.1:4059").release()

        assert fake_meter.connects == 0
        assert fake_meter.disconnects == 0

    def test_the_message_names_the_endpoint_and_does_not_say_retry(self, fake_meter: FakeMeterState) -> None:
        """ADR 0006 — the operator is never told 'busy, try again'."""
        locks = EndpointLocks()
        assert locks.get("127.0.0.1:4059").try_acquire_background() is True
        try:
            with pytest.raises(ProbeError) as caught:
                probe_meter(**PROBE_ARGS, locks=locks, lock_timeout_sec=0.05)  # type: ignore[arg-type]
        finally:
            locks.get("127.0.0.1:4059").release()

        message = str(caught.value)
        assert "127.0.0.1:4059" in message
        assert "try again" not in message.lower()

    def test_the_endpoint_is_not_left_held(self, fake_meter: FakeMeterState) -> None:
        locks = EndpointLocks()
        lock = locks.get("127.0.0.1:4059")
        assert lock.try_acquire_background() is True
        with pytest.raises(ProbeError):
            probe_meter(**PROBE_ARGS, locks=locks, lock_timeout_sec=0.05)  # type: ignore[arg-type]
        lock.release()

        assert lock.try_acquire_background() is True
        lock.release()

    def test_a_probe_that_waits_but_gets_in_still_succeeds(self, fake_meter: FakeMeterState) -> None:
        """A slow-but-alive line must not cost the operator their read."""
        locks = EndpointLocks()
        lock = locks.get("127.0.0.1:4059")
        fake_meter.meter_serial = "SN-WAITED"
        assert lock.try_acquire_background() is True

        released = threading.Event()

        def release_shortly() -> None:
            time.sleep(0.05)
            lock.release()
            released.set()

        holder = threading.Thread(target=release_shortly, daemon=True)
        holder.start()
        try:
            result = probe_meter(**PROBE_ARGS, locks=locks, lock_timeout_sec=10)  # type: ignore[arg-type]
        finally:
            holder.join(timeout=5)

        assert released.is_set()
        assert result.meter_serial == "SN-WAITED"
        assert fake_meter.connects == 1


class TestAProbeIsNotAReading:
    def test_it_writes_no_interval_reading(self, migrated_db: Settings, fake_meter: FakeMeterState) -> None:
        with session_scope() as session:
            before = len(session.scalars(select(IntervalReading)).all())

        probe()

        with session_scope() as session:
            after = len(session.scalars(select(IntervalReading)).all())
        assert before == after == 0


class TestTcpDlmsSerialRead:
    """D5 — the one concrete implementation, shared by every DLMS/TCP model.

    On :class:`TcpDlmsDriver`, not on the leaf: all eight remaining DLMS models
    in M4 need the identical read, and only SMW110 needs a different register —
    which the ``METER_SERIAL_OBIS`` class attribute already covers.
    """

    def driver(self) -> Prometer100Driver:
        return Prometer100Driver(ConnectionParams.net("127.0.0.1", 4059), password="ABCD0001")

    def test_the_default_register_is_the_dlms_standard_one(self) -> None:
        assert Prometer100Driver.METER_SERIAL_OBIS == (METER_SERIAL_OBIS_CODE, METER_SERIAL_OBIS_ATTR)

    def test_it_is_a_class_attribute_readable_without_instantiating(self) -> None:
        """A capability flag, not an if/elif model chain (v1 base_driver.py)."""
        assert isinstance(Prometer100Driver.METER_SERIAL_OBIS, tuple)

    def test_it_reads_the_serial_register(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[tuple[str, int]] = []
        driver = self.driver()
        monkeypatch.setattr(
            type(driver),
            "read_register",
            lambda self, obis, attr=2: (seen.append((obis, attr)), "SN-1")[1],
        )
        assert driver.read_meter_serial() == "SN-1"
        assert seen == [(METER_SERIAL_OBIS_CODE, METER_SERIAL_OBIS_ATTR)]

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (b"SN-12345", "SN-12345"),
            (bytearray(b"  SN-99  "), "SN-99"),
            ("  SN-7 ", "SN-7"),
            (12345, "12345"),
            (b"SN-\xff", "SN-�"),
        ],
        ids=["bytes", "bytearray-padded", "str-padded", "int", "undecodable-byte"],
    )
    def test_it_decodes_and_strips(self, monkeypatch: pytest.MonkeyPatch, raw: object, expected: str) -> None:
        driver = self.driver()
        monkeypatch.setattr(type(driver), "read_register", lambda self, obis, attr=2: raw)
        assert driver.read_meter_serial() == expected

    @pytest.mark.parametrize(
        "raw", [None, "", "   ", b"", b"   "], ids=["none", "empty", "spaces", "b-empty", "b-spaces"]
    )
    def test_nothing_and_blank_both_mean_none(self, monkeypatch: pytest.MonkeyPatch, raw: object) -> None:
        """A blank serial is indistinguishable from a failed probe (v1)."""
        driver = self.driver()
        monkeypatch.setattr(type(driver), "read_register", lambda self, obis, attr=2: raw)
        assert driver.read_meter_serial() is None

    def test_a_blank_serial_probes_as_no_serial(self, fake_meter: FakeMeterState) -> None:
        """End to end: the driver returns None, the probe names it NO_SERIAL."""
        fake_meter.meter_serial = None
        with pytest.raises(ProbeError) as caught:
            probe()
        assert caught.value.reason is ProbeFailure.NO_SERIAL
