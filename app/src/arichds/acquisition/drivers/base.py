"""``MeterDriver`` — the one abstraction every meter goes behind.

Ported from ``cewe-worker/src/drivers/base_driver.py`` and trimmed to what M1
needs. The governing rule survives intact (SPEC §3.4): **no ``if/elif`` on brand
or model in generic code**. Model-specific behaviour lives in a concrete driver
or on a class-level capability flag; the Poller, the API and the DB layer never
learn which meter they are talking to.

The driver is also where **normalization happens** (REMAKE-PLAN §6.1): whatever
the wire says, :meth:`MeterDriver.read_instantaneous` returns UTC timestamps and
kWh energy. Nothing downstream converts anything.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class InstantaneousReading:
    """One normalized instantaneous sample, ready to persist.

    Field names match ``interval_readings`` columns exactly, and the units match
    the names — that is the normalization contract, not a coincidence.

    Attributes:
        read_at: When the value was taken — **timezone-aware UTC, always**.
        source: Which acquisition path produced it (``dlms`` / ``modbus`` / ``sim``).
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
        """Return the measurement fields as ``interval_readings`` column values."""
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
    def read_instantaneous(self) -> InstantaneousReading:
        """Read the instantaneous set and return it **already normalized**.

        Assumes :meth:`connect` succeeded. UTC and kWh are this method's
        responsibility, not the caller's.

        Returns:
            The normalized sample.
        """

    def health_check(self) -> bool:
        """Cheap reachability probe: connect, read something small, disconnect.

        Default implementation reads the instantaneous set, which every model
        supports. Models with a cheaper probe override this.

        Returns:
            True if the meter answered, False on any error.
        """
        try:
            self.connect()
            self.read_instantaneous()
            return True
        except Exception:  # noqa: BLE001 — a probe reports False, never raises.
            return False
        finally:
            self.disconnect()


class MeterConnectionError(RuntimeError):
    """Raised when a meter connection cannot be established or is lost."""
