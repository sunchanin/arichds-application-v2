"""``MeterDriver`` — the one abstraction every meter goes behind.

Ported from ``cewe-worker/src/drivers/base_driver.py`` and trimmed to what M1
needs. The governing rule survives intact (SPEC §3.4): **no ``if/elif`` on brand
or model in generic code**. Model-specific behaviour lives in a concrete driver
or on a class-level capability flag; the Poller, the API and the DB layer never
learn which meter they are talking to.

The driver is also where **normalization happens** (REMAKE-PLAN §6.1): whatever
the wire says, a driver hands back UTC timestamps and kWh energy. Nothing
downstream converts anything.

There is deliberately **no read method for live values here, and no reachability
probe** (ADR 0007). Both left with issue #8: v2 displays no live value and stores
nothing instantaneous, so the Poller's tick reads
:meth:`MeterDriver.read_meter_serial` — one register, the same seam the Probe
uses — and discards the answer. An abstract method with no caller is not a
contract, it is a leftover, and every base class M4 adds would have had to
implement it. The remaining read paths are the load profile (M5) and billing
(M6), both of which read intervals the *meter* recorded.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class InstantaneousReading:
    """One normalized sample, ready to persist.

    Field names match ``load_profile_readings`` columns exactly, and the units
    match the names — that is the normalization contract, not a coincidence.

    **Nothing produces one of these today.** ADR 0007 removed the read method
    that did, and issue #8 kept the dataclass on purpose: M5 may well use the
    same shape for a load-profile row, so the decision belongs to M5 rather than
    to the change that stopped storing instantaneous values.

    Attributes:
        read_at: When the value was taken — **timezone-aware UTC, always**.
        source: Which acquisition path produced it (``dlms`` / ``modbus``).
        volt_l1/volt_l2/volt_l3: Phase-to-neutral voltage (V).
        current_l1/current_l2/current_l3: Line current (A).
        freq: Frequency (Hz).
        import_active_kwh: Cumulative active energy import (**kWh**).
    """

    read_at: datetime
    source: str
    volt_l1: float | None = None
    volt_l2: float | None = None
    volt_l3: float | None = None
    current_l1: float | None = None
    current_l2: float | None = None
    current_l3: float | None = None
    freq: float | None = None
    import_active_kwh: float | None = None

    def as_columns(self) -> dict[str, Any]:
        """Return the measurement fields as ``load_profile_readings`` column values."""
        return {
            "volt_l1": self.volt_l1,
            "volt_l2": self.volt_l2,
            "volt_l3": self.volt_l3,
            "current_l1": self.current_l1,
            "current_l2": self.current_l2,
            "current_l3": self.current_l3,
            "freq": self.freq,
            "import_active_kwh": self.import_active_kwh,
        }


class MeterDriver(ABC):
    """Abstract base for every meter protocol driver.

    A driver instance represents a single physical meter connection — it owns
    the socket/serial resource and MUST release it in :meth:`disconnect`.
    """

    #: Which Source rows written by this driver carry. A class attribute rather
    #: than a branch at the write site (CONTEXT.md — Source is a property of the
    #: reading, never a branch in read-path code).
    source: str = "dlms"

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Human-readable model identifier, e.g. ``"prometer100"``."""

    @property
    @abstractmethod
    def endpoint(self) -> str:
        """The Transport Endpoint this driver talks over — the Poller's lock key."""

    @abstractmethod
    def get_obis_map(self) -> dict[str, tuple[str, int]]:
        """Return this model's OBIS map for the instantaneous set.

        Returns:
            ``{column_name: (obis_code, attribute_index)}``.
        """

    @abstractmethod
    def connect(self) -> None:
        """Open the connection and complete any protocol handshake.

        Raises:
            MeterConnectionError: If the connection cannot be established.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """Close the connection and release all resources.

        MUST be called from a ``finally`` block and MUST NOT raise — swallow and
        log any error so the caller's ``finally`` always completes.
        """

    @abstractmethod
    def read_meter_serial(self) -> str | None:
        """Read the Meter Serial off the meter. Assumes connect() succeeded.

        Abstract on purpose: ADR 0005 says a device's identity comes from the
        meter, so a driver that cannot supply one is a driver that must not
        compile — not one that fails at 3am on a customer machine.

        Returns:
            The trimmed serial, or None when the meter answered with nothing or
            a blank — which is indistinguishable from a failed probe for the
            caller.
        """


class MeterConnectionError(RuntimeError):
    """Raised when a meter connection cannot be established or is lost."""
