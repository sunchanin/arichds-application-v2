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
        import_reactive_kvarh/export_active_kwh/export_reactive_kvarh/avg_geo_pf:
            The rest of the twelve-column set the v1 Load Profile page shows
            (SPEC §3.5). The columns existed on ``load_profile_readings``
            since M5a-1 (migration 0006) but stayed off this dataclass until
            M4c, issue #24 — a field nothing sets is speculative, and the
            three CEWE drivers are the first to produce them (F7).
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
    # ── M4c, issue #24 — produced by all three CEWE drivers (F7); the columns
    # already existed on `load_profile_readings` since migration 0006, but a
    # field nothing set was speculative until a driver actually produces one.
    import_reactive_kvarh: float | None = None
    export_active_kwh: float | None = None
    export_reactive_kvarh: float | None = None
    avg_geo_pf: float | None = None

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
            "import_reactive_kvarh": self.import_reactive_kvarh,
            "export_active_kwh": self.export_active_kwh,
            "export_reactive_kvarh": self.export_reactive_kvarh,
            "avg_geo_pf": self.avg_geo_pf,
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
        max_demand_import_active_time_total/rate_a/rate_b/rate_c/rate_d: When
            the corresponding import active max-demand value was captured —
            **timezone-aware UTC, never scaled** (D11) — from OBIS
            ``1.0.1.6.{0..4}.255`` attribute 5 (M4c, issue #24).
        max_demand_import_reactive_time_total/rate_a/rate_b/rate_c/rate_d: When
            the corresponding import reactive max-demand value was captured,
            from OBIS ``1.0.3.6.{0..4}.255`` attribute 5.
        cumul_demand_import_active_kw_total/rate_a/rate_b/rate_c/rate_d:
            Cumulative demand, imported active power, from OBIS
            ``1.0.1.2.{0..4}.255``. Scales like every other billing number
            (D12) — resolved ``scaler_unit``, then divided to kW.
        cumul_demand_import_reactive_kvar_total/rate_a/rate_b/rate_c/rate_d:
            Cumulative demand, imported reactive power, from OBIS
            ``1.0.3.2.{0..4}.255``.

    ``C=5`` (reactive Q1) has no fields here — no screen has ever shown it
    (SPEC §3.6), and a field nothing sets is speculative. The **export** side
    of Demand Time and Cumulative Demand is deliberately absent too (D10,
    F2) — no screen shows it and no meter known to this build carries it.
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

    # ── M4c, issue #24 — the twenty columns v1's screen has always shown ──────
    # Demand Time: WHEN the max-demand value was captured (Extended Register
    # attr 5, D11) — a timestamp, never scaled, never divided. Cumulative
    # Demand: a running total (D=2, class 4 ExtendedRegister) that scales like
    # every other billing number (D12). Import side only — no screen shows the
    # export side (D10/F2).
    max_demand_import_active_time_total: datetime | None = None
    max_demand_import_active_time_rate_a: datetime | None = None
    max_demand_import_active_time_rate_b: datetime | None = None
    max_demand_import_active_time_rate_c: datetime | None = None
    max_demand_import_active_time_rate_d: datetime | None = None

    max_demand_import_reactive_time_total: datetime | None = None
    max_demand_import_reactive_time_rate_a: datetime | None = None
    max_demand_import_reactive_time_rate_b: datetime | None = None
    max_demand_import_reactive_time_rate_c: datetime | None = None
    max_demand_import_reactive_time_rate_d: datetime | None = None

    cumul_demand_import_active_kw_total: float | None = None
    cumul_demand_import_active_kw_rate_a: float | None = None
    cumul_demand_import_active_kw_rate_b: float | None = None
    cumul_demand_import_active_kw_rate_c: float | None = None
    cumul_demand_import_active_kw_rate_d: float | None = None

    cumul_demand_import_reactive_kvar_total: float | None = None
    cumul_demand_import_reactive_kvar_rate_a: float | None = None
    cumul_demand_import_reactive_kvar_rate_b: float | None = None
    cumul_demand_import_reactive_kvar_rate_c: float | None = None
    cumul_demand_import_reactive_kvar_rate_d: float | None = None

    def as_columns(self) -> dict[str, Any]:
        """Return the **sixty measurement** fields as ``billing_readings`` column values.

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
            "max_demand_import_active_time_total": self.max_demand_import_active_time_total,
            "max_demand_import_active_time_rate_a": self.max_demand_import_active_time_rate_a,
            "max_demand_import_active_time_rate_b": self.max_demand_import_active_time_rate_b,
            "max_demand_import_active_time_rate_c": self.max_demand_import_active_time_rate_c,
            "max_demand_import_active_time_rate_d": self.max_demand_import_active_time_rate_d,
            "max_demand_import_reactive_time_total": self.max_demand_import_reactive_time_total,
            "max_demand_import_reactive_time_rate_a": self.max_demand_import_reactive_time_rate_a,
            "max_demand_import_reactive_time_rate_b": self.max_demand_import_reactive_time_rate_b,
            "max_demand_import_reactive_time_rate_c": self.max_demand_import_reactive_time_rate_c,
            "max_demand_import_reactive_time_rate_d": self.max_demand_import_reactive_time_rate_d,
            "cumul_demand_import_active_kw_total": self.cumul_demand_import_active_kw_total,
            "cumul_demand_import_active_kw_rate_a": self.cumul_demand_import_active_kw_rate_a,
            "cumul_demand_import_active_kw_rate_b": self.cumul_demand_import_active_kw_rate_b,
            "cumul_demand_import_active_kw_rate_c": self.cumul_demand_import_active_kw_rate_c,
            "cumul_demand_import_active_kw_rate_d": self.cumul_demand_import_active_kw_rate_d,
            "cumul_demand_import_reactive_kvar_total": self.cumul_demand_import_reactive_kvar_total,
            "cumul_demand_import_reactive_kvar_rate_a": self.cumul_demand_import_reactive_kvar_rate_a,
            "cumul_demand_import_reactive_kvar_rate_b": self.cumul_demand_import_reactive_kvar_rate_b,
            "cumul_demand_import_reactive_kvar_rate_c": self.cumul_demand_import_reactive_kvar_rate_c,
            "cumul_demand_import_reactive_kvar_rate_d": self.cumul_demand_import_reactive_kvar_rate_d,
        }


@dataclass(frozen=True)
class EnergyRegisterReading:
    """One snapshot of a meter's cumulative Energy Registers (M7-1, issue #28;
    CONTEXT.md — Energy Registers).

    Field names match ``energy_register_readings`` columns exactly, mirroring
    :class:`BillingReading`'s naming convention — a total plus four tariffs
    for each of the four quantities. Unlike a Billing Reading there is no
    ``bill_date``/``is_open``: this is a plain dated snapshot, never a period.

    Attributes:
        source: Which acquisition path produced it (``dlms``).
        meter_serial: Snapshot per row, or None if the driver could not read
            one.
        import_active_kwh_total/rate_a/rate_b/rate_c/rate_d: OBIS
            ``1.0.1.8.{0..4}.255``.
        export_active_kwh_total/rate_a/rate_b/rate_c/rate_d: OBIS
            ``1.0.2.8.{0..4}.255``.
        import_reactive_kvarh_total/rate_a/rate_b/rate_c/rate_d: OBIS
            ``1.0.3.8.{0..4}.255``.
        export_reactive_kvarh_total/rate_a/rate_b/rate_c/rate_d: OBIS
            ``1.0.4.8.{0..4}.255``.
    """

    source: str
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

    def as_columns(self) -> dict[str, Any]:
        """Return the **twenty measurement** fields as ``energy_register_readings``
        column values. ``source``/``meter_serial`` are the row's identity, not
        values it measured — mirrors :meth:`BillingReading.as_columns`."""
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
        }


@dataclass(frozen=True)
class SpecialDayEntry:
    """One row of a meter's COSEM class-11 Special Days Table (M7-1, issue
    #28; CONTEXT.md — Holiday), already classified — the wire's wildcard-year
    detail (a bare ``GXDate`` whose year field was skipped, decoded by Gurux
    as a ``2000`` placeholder) is a wire fact and must not leak past the
    driver, the same write-time-normalization invariant applied to a
    calendar instead of a unit.

    **One representation, mapping 1:1 onto the ``holidays`` columns** — a
    driver never returns a raw ``GXDate``, only this.

    Attributes:
        index: The entry's own index on the meter's table.
        day_id: The meter's own tariff-table code for this day — the only
            distinguishing datum the meter carries (decision 17; there is no
            name field on the wire).
        year: The entry's year, or ``None`` when the wire's year field was a
            wildcard (annual, recurring every year). **Never the ``2000``
            placeholder Gurux substitutes for a skipped year** — that value
            must never reach this field.
        month: The month, always present.
        day: The day of month, always present.
    """

    index: int
    day_id: int
    year: int | None
    month: int
    day: int

    @property
    def kind(self) -> str:
        """``"annual"`` when :attr:`year` is ``None``, else ``"public"`` —
        the same two kinds :class:`~arichds.db.models.Holiday` stores."""
        return "annual" if self.year is None else "public"


class MeterDriver(ABC):
    """Abstract base for every meter protocol driver.

    A driver instance represents a single physical meter connection — it owns
    the socket/serial resource and MUST release it in :meth:`disconnect`.
    """

    #: Which Source rows written by this driver carry. A class attribute rather
    #: than a branch at the write site (CONTEXT.md — Source is a property of the
    #: reading, never a branch in read-path code).
    source: str = "dlms"

    #: The widest column span a billing ``readRowsByEntry`` may ask for in one
    #: request, or ``None`` when the model has no such ceiling and reads full
    #: width (D7, M4c issue #24). SMW110W4 is the one model that needs a span
    #: today — its billing profile answers "Data Block Unavailable" past 43
    #: columns; the three CEWE models read whole-buffer, full-width, no span
    #: (F4). A class attribute, not a module constant, because M4c is the
    #: first slice with a model that does not need one.
    BILLING_COLUMN_SPAN: int | None = None

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

    def load_profile_loggers(self) -> tuple[int, ...]:
        """Which ``logger_id``\\ s this driver can read, ascending (D2, M4c issue #24).

        Non-abstract and empty by default, mirroring :meth:`supports_load_profile`:
        most models have no scanned capture list yet. A model that can read a
        load profile overrides this with the logger ids it actually captures —
        derived from its own profile OBIS declarations through
        :func:`~arichds.acquisition.obis.logger_id_for_profile`, never from
        discovery order or arithmetic (ADR 0005's principle). The load-profile
        job walks these ascending so Logger 1 — which carries the energy
        columns on every model — is never starved by Logger 2.

        A driver-contract test asserts this is non-empty exactly when
        :meth:`supports_load_profile` is ``True``, so the two capability
        signals cannot drift apart.

        Returns:
            The logger ids this driver reads, ascending. Empty unless a
            concrete driver says otherwise.
        """
        return ()

    def read_load_profile(self, logger_id: int, start_utc: datetime, end_utc: datetime) -> list[IntervalReading]:
        """Read one logger's profile over ``[start_utc, end_utc]``, inclusive.

        Callable only when :meth:`supports_load_profile` returns ``True`` and
        *logger_id* is one of :meth:`load_profile_loggers`. Assumes
        :meth:`connect` succeeded.

        Non-abstract and raising, rather than absent, so the job never has to ask
        ``hasattr``: a driver that *forgot* this method must not look like one
        that deliberately lacks it. Not abstract either — that would force every
        model M4 adds to write a stub for a profile nobody has scanned.

        The logger id comes first, before the window, because it selects
        **which profile** — a property of *what* is being read — before *when*
        (D2, M4c issue #24). A per-logger read interface replaces the earlier
        one-profile-per-driver assumption, which is what let a stalled logger
        hold another logger's watermark open forever (ADR 0008, load_profile.py).

        Args:
            logger_id: Which load profile to read — one of
                :meth:`load_profile_loggers`.
            start_utc: Inclusive lower bound, timezone-aware UTC.
            end_utc: Inclusive upper bound, timezone-aware UTC.

        Returns:
            Rows already normalized to UTC timestamps and kWh energy, oldest
            first, each stamped with its ``logger_id`` and ``interval_sec``.

        Raises:
            NotImplementedError: Always, on a driver that has no load profile.
        """
        raise NotImplementedError(f"{type(self).__name__} has no load profile — check supports_load_profile() first")

    def load_profile_oldest_reading(self, logger_id: int) -> datetime | None:
        """When this logger's buffer actually starts, or ``None`` if unknown.

        The backfill walk begins at ``now - LOAD_PROFILE_BACKFILL_DAYS`` on a
        device with no stored rows, and steps forward one chunk at a time. Every
        chunk older than the meter's own buffer is a round trip whose answer is
        already known to be empty — and on a slow link that is not merely
        wasteful, it is fatal: the walk is bounded by
        ``LOAD_PROFILE_READ_BUDGET_SEC`` and keeps no memory of where it
        stopped, so if the budget runs out before the first row is stored, the
        watermark stays ``None`` and the next cycle repeats the same empty walk
        forever. A SMART TCC on serial 9600 with ~22 hours of buffer sat at zero
        rows for three hours that way, one re-walk per cycle.

        Answering it moves the start to the first chunk that can contain data.
        A meter that genuinely holds the whole window answers with a time ~90
        days old and nothing about the walk changes.

        Non-abstract and returning ``None`` rather than raising: a driver that
        cannot cheaply answer must degrade to today's behaviour, not fail. The
        caller only asks during backfill (no watermark), so a driver paying a
        read for it pays once per device, not once per cycle.

        Args:
            logger_id: Which load profile to ask about — one of
                :meth:`load_profile_loggers`.

        Returns:
            The timestamp of the oldest row the meter still holds for that
            logger, timezone-aware UTC, or ``None`` when it cannot be
            established.
        """
        return None

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

    def supports_energy_registers(self) -> bool:
        """Whether this driver can read the standalone Energy Registers
        (M7-1, issue #28; ADR 0011 — the driver is the authority, the
        catalog's ``supports_energy_summary`` flag only gates the *page*).

        Non-abstract and ``False`` by default, the same pairing as
        :meth:`supports_billing`. A model that can read the twenty
        cumulative-energy registers overrides this to ``True`` **and**
        implements :meth:`read_energy_registers`.

        Returns:
            False, unless a concrete driver says otherwise.
        """
        return False

    def read_energy_registers(self) -> EnergyRegisterReading:
        """Read the meter's twenty standalone cumulative energy registers
        (COSEM ``D=8``) — one dated snapshot, not a period (M7-1, issue #28).

        Callable only when :meth:`supports_energy_registers` returns
        ``True``. Assumes :meth:`connect` succeeded.

        Non-abstract and raising, rather than absent, so the caller never has
        to ask ``hasattr`` — the same pairing and the same reason as
        :meth:`read_billing`.

        Returns:
            The snapshot, already normalized to kWh/kvarh. An address that
            refuses leaves its field ``None``; it must not abort the other
            nineteen.

        Raises:
            NotImplementedError: Always, on a driver that has no Energy
                Registers.
        """
        raise NotImplementedError(
            f"{type(self).__name__} has no Energy Registers — check supports_energy_registers() first"
        )

    def supports_special_days(self) -> bool:
        """Whether this driver can read the COSEM class-11 Special Days
        Table (M7-1, issue #28; ADR 0011).

        Non-abstract and ``False`` by default, the same pairing as
        :meth:`supports_billing`. A model that exposes the table overrides
        this to ``True`` **and** implements :meth:`read_special_days`.

        Returns:
            False, unless a concrete driver says otherwise.
        """
        return False

    def read_special_days(self) -> list[SpecialDayEntry]:
        """Read the meter's whole Special Days Table, read-through — nothing
        is stored from this call (CONTEXT.md — the Special Days page shows
        what the meter holds, and it alone; the Holiday table it can seed is
        a **separate**, explicit import action, never automatic).

        Callable only when :meth:`supports_special_days` returns ``True``.
        Assumes :meth:`connect` succeeded. **Never calls the table's own
        ``insert()``/``delete()`` methods** — the product only ever reads a
        meter (CLAUDE.md).

        Returns:
            Every entry the meter holds, in whatever order the meter returns
            them — an empty table is a valid answer, not a failure.

        Raises:
            NotImplementedError: Always, on a driver that has no Special Days
                Table.
        """
        raise NotImplementedError(
            f"{type(self).__name__} has no Special Days Table — check supports_special_days() first"
        )


class MeterConnectionError(RuntimeError):
    """Raised when a meter connection cannot be established or is lost."""
