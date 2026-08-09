"""The test-only fake meter (M3-1).

ADR 0005 removed the simulated (``SIM``) driver from the product: a fake meter
cannot supply a real identity, and keeping it would mean an ``if this is SIM,
skip the probe`` branch in the create path — precisely the model-shaped ``if``
the driver abstraction exists to prevent. It survives here instead, registered
by ``conftest``'s ``fake_meter`` fixture through a monkeypatch of the driver
registry, so the whole suite runs green **without touching a real meter**.

It is registered under the real model string ``prometer100`` rather than a
made-up one, so the catalog endpoint, the driver registry and the API tests all
stay coherent with the product's own vocabulary.

Its knobs live at MODULE scope, keyed by nothing, because the Poller and the
probe both build a brand-new driver for every read — per-instance knobs would
be reset before a test could observe them.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.base import IntervalReading, MeterDriver
from arichds.constants import SOURCE_DLMS

#: The serial the fake meter reports unless a test says otherwise.
DEFAULT_FAKE_SERIAL = "FAKE-SN-0001"


@dataclass
class FakeMeterState:
    """What every :class:`FakeMeterDriver` built in this test will do.

    Attributes:
        meter_serial: What :meth:`FakeMeterDriver.read_meter_serial` returns —
            already decoded and trimmed, as the contract requires. ``None``
            means "the meter answered with nothing".
        connect_error: Raised by ``connect()`` when set.
        serial_error: Raised by ``read_meter_serial()`` when set — the meter
            that accepts an association but cannot serve a register.
        entered_read: Set as soon as a read begins — how a test knows the fake
            is inside the endpoint lock.
        hold_read: When set, a read parks on this event until the test releases
            it. Lets a test hold the endpoint and observe the priority rule.
        connects: How many times ``connect()`` was called.
        disconnects: How many times ``disconnect()`` was called.
        load_profile_rows: The whole buffer :class:`FakeSmw110Driver` replays
            from — a read returns the subset falling inside the asked-for
            window, inclusive on both bounds, like the real driver's filter.
        load_profile_windows: Every window asked for, in call order. The walk's
            *direction* is only observable here; row counts alone would pass
            just as happily with the chunks reversed.
        load_profile_error: What a failing load-profile read raises.
        load_profile_fail_after: Succeed for this many reads, then raise. The
            mid-walk failure a chunked backfill has to survive.
    """

    meter_serial: str | None = DEFAULT_FAKE_SERIAL
    connect_error: Exception | None = None
    serial_error: Exception | None = None
    entered_read: threading.Event = field(default_factory=threading.Event)
    hold_read: threading.Event | None = None
    connects: int = 0
    disconnects: int = 0
    load_profile_rows: list[IntervalReading] = field(default_factory=list)
    load_profile_windows: list[tuple[datetime, datetime]] = field(default_factory=list)
    load_profile_error: Exception | None = None
    load_profile_fail_after: int | None = None


_STATE = FakeMeterState()
_GUARD = threading.Lock()


def fake_meter_state() -> FakeMeterState:
    """Return the knobs every fake driver instance reads."""
    return _STATE


def reset_fake_meter() -> None:
    """Restore the fake meter to its default, always-answers behaviour."""
    global _STATE  # noqa: PLW0603 — one shared knob-set per test, by design.
    with _GUARD:
        _STATE = FakeMeterState()


class FakeMeterDriver(MeterDriver):
    """A meter that answers exactly how the current :class:`FakeMeterState` says.

    Implements the full :class:`~arichds.acquisition.drivers.base.MeterDriver`
    contract, so registering it proves the contract is satisfiable rather than
    papering over it.

    Registered under **both** ``prometer100`` and ``smw110`` (issue #9) — see
    :class:`FakeSmw110Driver` below, which only overrides :attr:`_MODEL_NAME`,
    so ``model_name`` stays truthful for whichever key the registry used.
    """

    source = SOURCE_DLMS

    #: Overridden by :class:`FakeSmw110Driver`. A class attribute rather than a
    #: constructor argument because the driver factory calls
    #: ``registry[key](conn=conn, password=password, **kwargs)`` — it never
    #: passes the registry key itself, so the only way for two registrations of
    #: "the same fake" to report a different, truthful ``model_name`` is one
    #: class each.
    _MODEL_NAME: str = "prometer100"

    def __init__(self, conn: ConnectionParams, password: str = "", **kwargs: Any) -> None:
        """Initialise the fake.

        Args:
            conn: Transport identity, used only for the endpoint label.
            password: Ignored — kept so the factory signature is uniform.
            **kwargs: Absorbed for forward compatibility.
        """
        self._conn = conn
        self._password = password

    @property
    def model_name(self) -> str:
        """Human-readable model identifier."""
        return self._MODEL_NAME

    @property
    def endpoint(self) -> str:
        """The Transport Endpoint this fake meter claims to live at."""
        return self._conn.endpoint

    def get_obis_map(self) -> dict[str, tuple[str, int]]:
        """No wire protocol — the fake has no OBIS codes."""
        return {}

    def connect(self) -> None:
        """Record the connect, or raise whatever the test asked for."""
        with _GUARD:
            _STATE.connects += 1
            error = _STATE.connect_error
        if error is not None:
            raise error

    def disconnect(self) -> None:
        """Record the disconnect. Never raises, like every real driver."""
        with _GUARD:
            _STATE.disconnects += 1

    def _park(self) -> None:
        """Announce that a read has begun and hold there if the test asked."""
        _STATE.entered_read.set()
        hold = _STATE.hold_read
        if hold is not None:
            hold.wait(timeout=10)

    def read_meter_serial(self) -> str | None:
        """Return the configured Meter Serial, already trimmed."""
        self._park()
        if _STATE.serial_error is not None:
            raise _STATE.serial_error
        return _STATE.meter_serial


class FakeSmw110Driver(FakeMeterDriver):
    """The same fake, registered under ``smw110`` (issue #9) with a truthful name.

    It is also the **only** fake that can read a load profile (M5a-1), mirroring
    the product: :class:`FakeMeterDriver` inherits ``MeterDriver``'s ``False``,
    so ``prometer100`` keeps proving the unsupported path.
    """

    _MODEL_NAME = "smw110"

    def supports_load_profile(self) -> bool:
        """Yes — like the real ``Smw110Driver``."""
        return True

    def read_load_profile(self, start_utc: datetime, end_utc: datetime) -> list[IntervalReading]:
        """Record the window, honour the failure knobs, replay the seeded rows.

        Filtering inclusively on both bounds is the real driver's behaviour
        (``smw110.py``), and it is what makes the job's deliberate re-read of the
        watermark row come back rather than vanish.
        """
        with _GUARD:
            _STATE.load_profile_windows.append((start_utc, end_utc))
            reads = len(_STATE.load_profile_windows)
            error = _STATE.load_profile_error
            fail_after = _STATE.load_profile_fail_after
            rows = list(_STATE.load_profile_rows)

        if fail_after is not None:
            if reads > fail_after:
                raise error or TimeoutError("the meter stopped answering mid-walk")
        elif error is not None:
            raise error

        return [row for row in rows if start_utc <= row.read_at <= end_utc]
