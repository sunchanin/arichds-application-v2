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
implement it.

**The load-profile read path moved onto this base class at M5a-1 (issue #15).**
It landed on the leaf :class:`~arichds.acquisition.drivers.smw110.Smw110Driver`
at M4a-2 (issue #10, D1) on the "no caller, no contract" principle above — and
that reasoning has now expired rather than been overruled: the load-profile job
is the caller, it must ask *every* driver whether it can read one, and
``SPEC.md`` §3.5 names :meth:`MeterDriver.supports_load_profile` as the way it
asks. The pairing is deliberate — a non-abstract
:meth:`MeterDriver.supports_load_profile` answering ``False`` plus a
:meth:`MeterDriver.read_load_profile` that *raises*, so that ``hasattr`` is never
the question. ``hasattr`` would make a driver that **forgot** the method
indistinguishable from one that deliberately lacks it, and only one of those two
is a bug.

**Billing (M6a, issue #21) landed the same pairing** —
:meth:`MeterDriver.supports_billing` / :meth:`MeterDriver.read_billing` — on this
base class from the start, since the billing job needed to ask every driver the
same question on day one. It was the last read path still behind in v1; it no
longer is.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class IntervalReading:
    """One normalized Interval Reading, produced by a driver's load-profile read.

    Field names match ``load_profile_readings`` columns exactly, and the units
    match the names — that is the normalization contract, not a coincidence
    (CONTEXT.md — Interval Reading).

    Attributes:
        read_at: When the interval was recorded by the meter —
            **timezone-aware UTC, always**.
        source: Which acquisition path produced it (``dlms`` / ``modbus``).
        logger_id: Which load profile the row came from, derived from that
            profile's OBIS (:func:`~arichds.acquisition.obis.logger_id_for_profile`).
            Required, because it is part of the row's identity.
        interval_sec: The meter's own capture period for that logger, in seconds
            exactly as it reports them — no label conversion (M5a-1, D4).
        volt_l1/volt_l2/volt_l3: Phase-to-neutral voltage (V).
        current_l1/current_l2/current_l3: Line current (A).
        freq: Frequency (Hz).
        import_active_kwh: Active energy import for the interval (**kWh**).

    The four measurement columns ``load_profile_readings`` gained at M5a-1
    (``import_reactive_kvarh``, ``export_active_kwh``, ``export_reactive_kvarh``,
    ``avg_geo_pf``) are deliberately **not** fields here: no driver produces one
    until M4c, and a field nothing sets is speculative.
    """

    read_at: datetime
    source: str
    logger_id: int
    interval_sec: int
    volt_l1: float | None = None
    volt_l2: float | None = None
    volt_l3: float | None = None
    current_l1: float | None = None
    current_l2: float | None = None
    current_l3: float | None = None
    freq: float | None = None
    import_active_kwh: float | None = None

    def as_columns(self) -> dict[str, Any]:
        """Return the **measurement** fields as ``load_profile_readings`` column values.

        Measurements only — ``read_at``, ``source``, ``logger_id`` and
        ``interval_sec`` are the row's identity, not values it measured, and the
        writer composes them alongside this dict.
        """
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


@dataclass(frozen=True)
class BillingReading:
    """One normalized Billing Reading, produced by a driver's billing read
    (M6a, issue #21).

    Field names match ``billing_readings`` columns exactly, mirroring
    :class:`IntervalReading`'s contract: UTC, kWh/kvarh/kW/kvar, normalized at
    write time in the driver (CONTEXT.md — Billing Reading).

    Attributes:
        bill_date: The meter's own Clock cell for this period —
            **timezone-aware UTC, always** (CONTEXT.md — Bill Date).
        source: Which acquisition path produced it (``dlms`` / ``modbus``).
        is_open: Whether this is the device's Open Period — the running
            period the meter is still accumulating into, at most one per
            device. The driver reports what it saw on the wire; the
            ``NULL``/``"open"`` storage encoding is the writer's concern, not
            the driver's (CONTEXT.md — Open Period).
        meter_serial: Snapshot per row, or None if the driver could not read
            one.
        import_active_kwh_total/rate_a/rate_b/rate_c/rate_d: Imported active
            energy, from OBIS ``1.0.1.8.{0..4}.255``.
        export_active_kwh_total/rate_a/rate_b/rate_c/rate_d: Exported active
            energy, from OBIS ``1.0.2.8.{0..4}.255``.
        import_reactive_kvarh_total/rate_a/rate_b/rate_c/rate_d: Imported
            reactive energy, from OBIS ``1.0.3.8.{0..4}.255``.
        export_reactive_kvarh_total/rate_a/rate_b/rate_c/rate_d: Exported
            reactive energy, from OBIS ``1.0.4.8.{0..4}.255``.
        max_demand_import_active_kw_total/rate_a/rate_b/rate_c/rate_d: Maximum
            demand, imported active power, from OBIS ``1.0.1.6.{0..4}.255``.
        max_demand_export_active_kw_total/rate_a/rate_b/rate_c/rate_d: Maximum
            demand, exported active power, from OBIS ``1.0.2.6.{0..4}.255``.
        max_demand_import_reactive_kvar_total/rate_a/rate_b/rate_c/rate_d:
            Maximum demand, imported reactive power, from OBIS
            ``1.0.3.6.{0..4}.255``.
        max_demand_export_reactive_kvar_total/rate_a/rate_b/rate_c/rate_d:
            Maximum demand, exported reactive power, from OBIS
            ``1.0.4.6.{0..4}.255``.

    ``C=5`` (reactive Q1) has no fields here — no screen has ever shown it
    (SPEC §3.6), and a field nothing sets is speculative.
    """

    bill_date: datetime
    source: str
    is_open: bool
    meter_serial: str | None = None

    import_active_kwh_total: float | None = None
    import_active_kwh_rate_a: float | None = None
    import_active_kwh_rate_b: float | None = None
    import_active_kwh_rate_c: float | None = None
    import_active_kwh_rate_d: float | None = None

    export_active_kwh_total: float | None = None
    export_active_kwh_rate_a: float | None = None
    export_active_kwh_rate_b: float | None = None
    export_active_kwh_rate_c: float | None = None
    export_active_kwh_rate_d: float | None = None

    import_reactive_kvarh_total: float | None = None
    import_reactive_kvarh_rate_a: float | None = None
    import_reactive_kvarh_rate_b: float | None = None
    import_reactive_kvarh_rate_c: float | None = None
    import_reactive_kvarh_rate_d: float | None = None

    export_reactive_kvarh_total: float | None = None
    export_reactive_kvarh_rate_a: float | None = None
    export_reactive_kvarh_rate_b: float | None = None
    export_reactive_kvarh_rate_c: float | None = None
    export_reactive_kvarh_rate_d: float | None = None

    max_demand_import_active_kw_total: float | None = None
    max_demand_import_active_kw_rate_a: float | None = None
    max_demand_import_active_kw_rate_b: float | None = None
    max_demand_import_active_kw_rate_c: float | None = None
    max_demand_import_active_kw_rate_d: float | None = None

    max_demand_export_active_kw_total: float | None = None
    max_demand_export_active_kw_rate_a: float | None = None
    max_demand_export_active_kw_rate_b: float | None = None
    max_demand_export_active_kw_rate_c: float | None = None
    max_demand_export_active_kw_rate_d: float | None = None

    max_demand_import_reactive_kvar_total: float | None = None
    max_demand_import_reactive_kvar_rate_a: float | None = None
    max_demand_import_reactive_kvar_rate_b: float | None = None
    max_demand_import_reactive_kvar_rate_c: float | None = None
    max_demand_import_reactive_kvar_rate_d: float | None = None

    max_demand_export_reactive_kvar_total: float | None = None
    max_demand_export_reactive_kvar_rate_a: float | None = None
    max_demand_export_reactive_kvar_rate_b: float | None = None
    max_demand_export_reactive_kvar_rate_c: float | None = None
    max_demand_export_reactive_kvar_rate_d: float | None = None

    def as_columns(self) -> dict[str, Any]:
        """Return the **forty measurement** fields as ``billing_readings`` column values.

        Measurements only — ``bill_date``, ``source``, ``is_open`` and
        ``meter_serial`` are the row's identity, not values it measured, and
        the writer composes them alongside this dict (mirrors
        :meth:`IntervalReading.as_columns`).
        """
        return {
            "import_active_kwh_total": self.import_active_kwh_total,
            "import_active_kwh_rate_a": self.import_active_kwh_rate_a,
            "import_active_kwh_rate_b": self.import_active_kwh_rate_b,
            "import_active_kwh_rate_c": self.import_active_kwh_rate_c,
            "import_active_kwh_rate_d": self.import_active_kwh_rate_d,
            "export_active_kwh_total": self.export_active_kwh_total,
            "export_active_kwh_rate_a": self.export_active_kwh_rate_a,
            "export_active_kwh_rate_b": self.export_active_kwh_rate_b,
            "export_active_kwh_rate_c": self.export_active_kwh_rate_c,
            "export_active_kwh_rate_d": self.export_active_kwh_rate_d,
            "import_reactive_kvarh_total": self.import_reactive_kvarh_total,
            "import_reactive_kvarh_rate_a": self.import_reactive_kvarh_rate_a,
            "import_reactive_kvarh_rate_b": self.import_reactive_kvarh_rate_b,
            "import_reactive_kvarh_rate_c": self.import_reactive_kvarh_rate_c,
            "import_reactive_kvarh_rate_d": self.import_reactive_kvarh_rate_d,
            "export_reactive_kvarh_total": self.export_reactive_kvarh_total,
            "export_reactive_kvarh_rate_a": self.export_reactive_kvarh_rate_a,
            "export_reactive_kvarh_rate_b": self.export_reactive_kvarh_rate_b,
            "export_reactive_kvarh_rate_c": self.export_reactive_kvarh_rate_c,
            "export_reactive_kvarh_rate_d": self.export_reactive_kvarh_rate_d,
            "max_demand_import_active_kw_total": self.max_demand_import_active_kw_total,
            "max_demand_import_active_kw_rate_a": self.max_demand_import_active_kw_rate_a,
            "max_demand_import_active_kw_rate_b": self.max_demand_import_active_kw_rate_b,
            "max_demand_import_active_kw_rate_c": self.max_demand_import_active_kw_rate_c,
            "max_demand_import_active_kw_rate_d": self.max_demand_import_active_kw_rate_d,
            "max_demand_export_active_kw_total": self.max_demand_export_active_kw_total,
            "max_demand_export_active_kw_rate_a": self.max_demand_export_active_kw_rate_a,
            "max_demand_export_active_kw_rate_b": self.max_demand_export_active_kw_rate_b,
            "max_demand_export_active_kw_rate_c": self.max_demand_export_active_kw_rate_c,
            "max_demand_export_active_kw_rate_d": self.max_demand_export_active_kw_rate_d,
            "max_demand_import_reactive_kvar_total": self.max_demand_import_reactive_kvar_total,
            "max_demand_import_reactive_kvar_rate_a": self.max_demand_import_reactive_kvar_rate_a,
            "max_demand_import_reactive_kvar_rate_b": self.max_demand_import_reactive_kvar_rate_b,
            "max_demand_import_reactive_kvar_rate_c": self.max_demand_import_reactive_kvar_rate_c,
            "max_demand_import_reactive_kvar_rate_d": self.max_demand_import_reactive_kvar_rate_d,
            "max_demand_export_reactive_kvar_total": self.max_demand_export_reactive_kvar_total,
            "max_demand_export_reactive_kvar_rate_a": self.max_demand_export_reactive_kvar_rate_a,
            "max_demand_export_reactive_kvar_rate_b": self.max_demand_export_reactive_kvar_rate_b,
            "max_demand_export_reactive_kvar_rate_c": self.max_demand_export_reactive_kvar_rate_c,
            "max_demand_export_reactive_kvar_rate_d": self.max_demand_export_reactive_kvar_rate_d,
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

    def supports_load_profile(self) -> bool:
        """Whether this driver can read a load profile (M5a-1, SPEC §3.5).

        Non-abstract and ``False`` by default: most models have no scanned
        capture list yet, and the load-profile job must be able to ask every
        driver the same question. A model that can read one overrides this to
        ``True`` **and** implements :meth:`read_load_profile`.

        Returns:
            False, unless a concrete driver says otherwise.
        """
        return False

    def read_load_profile(self, start_utc: datetime, end_utc: datetime) -> list[IntervalReading]:
        """Read the meter's load profile over ``[start_utc, end_utc]``, inclusive.

        Callable only when :meth:`supports_load_profile` returns ``True``.
        Assumes :meth:`connect` succeeded.

        Non-abstract and raising, rather than absent, so the job never has to ask
        ``hasattr``: a driver that *forgot* this method must not look like one
        that deliberately lacks it. Not abstract either — that would force every
        model M4 adds to write a stub for a profile nobody has scanned.

        Args:
            start_utc: Inclusive lower bound, timezone-aware UTC.
            end_utc: Inclusive upper bound, timezone-aware UTC.

        Returns:
            Rows already normalized to UTC timestamps and kWh energy, oldest
            first, each stamped with its ``logger_id`` and ``interval_sec``.

        Raises:
            NotImplementedError: Always, on a driver that has no load profile.
        """
        raise NotImplementedError(f"{type(self).__name__} has no load profile — check supports_load_profile() first")

    def supports_billing(self) -> bool:
        """Whether this driver can read a billing profile (M6a, issue #21).

        Non-abstract and ``False`` by default, for the same reason as
        :meth:`supports_load_profile`: most models have no scanned billing
        profile yet, and the billing job must be able to ask every driver the
        same question. A model that can read one overrides this to ``True``
        **and** implements :meth:`read_billing`.

        Returns:
            False, unless a concrete driver says otherwise.
        """
        return False

    def read_billing(self) -> list[BillingReading]:
        """Read the meter's whole billing buffer (ADR 0009 — every read is a
        full-buffer read; there is no window argument).

        Callable only when :meth:`supports_billing` returns ``True``. Assumes
        :meth:`connect` succeeded.

        Non-abstract and raising, rather than absent, so the job never has to
        ask ``hasattr`` — the same pairing and the same reason as
        :meth:`read_load_profile`: a driver that *forgot* this method must not
        look like one that deliberately lacks it.

        Returns:
            Every row the meter holds, already normalized to UTC timestamps
            and kWh/kvarh/kW/kvar, in whatever order the meter returns them —
            entry ordering is a property of the *profile*, not assumed here.

        Raises:
            NotImplementedError: Always, on a driver that has no billing profile.
        """
        raise NotImplementedError(f"{type(self).__name__} has no billing profile — check supports_billing() first")


class MeterConnectionError(RuntimeError):
    """Raised when a meter connection cannot be established or is lost."""
