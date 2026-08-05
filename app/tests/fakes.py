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
from datetime import UTC, datetime
from typing import Any

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.base import InstantaneousReading, MeterDriver
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
        serial_error: Raised by ``read_meter_serial()`` when set.
        read_error: Raised by ``read_instantaneous()`` when set.
        entered_read: Set as soon as a read begins — how a test knows the fake
            is inside the endpoint lock.
        hold_read: When set, a read parks on this event until the test releases
            it. Lets a test hold the endpoint and observe the priority rule.
        connects: How many times ``connect()`` was called.
        disconnects: How many times ``disconnect()`` was called.
        ticks: How many instantaneous reads have happened.
    """

    meter_serial: str | None = DEFAULT_FAKE_SERIAL
    connect_error: Exception | None = None
    serial_error: Exception | None = None
    read_error: Exception | None = None
    entered_read: threading.Event = field(default_factory=threading.Event)
    hold_read: threading.Event | None = None
    connects: int = 0
    disconnects: int = 0
    ticks: int = 0


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
    """

    source = SOURCE_DLMS

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
        return "prometer100"

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

    def read_instantaneous(self) -> InstantaneousReading:
        """Return a plausible normalized sample — UTC and kWh, like any driver."""
        self._park()
        if _STATE.read_error is not None:
            raise _STATE.read_error
        with _GUARD:
            _STATE.ticks += 1
            tick = _STATE.ticks
        return InstantaneousReading(
            read_at=datetime.now(UTC),
            source=self.source,
            volt_l1=230.0 + tick,
            volt_l2=231.0 + tick,
            volt_l3=229.0 + tick,
            current_l1=12.0,
            current_l2=12.5,
            current_l3=11.5,
            freq=50.0,
            import_active_kwh=100.0 + tick,
        )
