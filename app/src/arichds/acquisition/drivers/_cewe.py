"""Shared read logic for the three CEWE models — Prometer 100, Saral 305,
Premier 550 (M4c, issue #24).

All three share one billing-profile shape (F4): OBIS ``1.0.98.2.0.255``,
entry 1 = newest, full width, no span — genuinely simpler than the SMW110W4's
hand-driven 43-column span (:mod:`~arichds.acquisition.drivers.smw110`, which
stays on its own leaf implementation because its *transport* is genuinely
different — D6). What is identical across all three CEWE models lives here
once: the billing column map (with the twenty new Demand Time / Cumulative
Demand columns, D10-D12), the bill-date candidate list (D8), the open/closed
classification from the meter's own reset-reason cell (D9), and the
full-buffer entry-access read itself.

A concrete CEWE driver supplies only what genuinely differs: its connection
parameters (F9), its per-logger load-profile column map (F7 + the omissions
each model's field scan requires, D16), and which loggers it has (D15).

**No ``if/elif`` on model anywhere in this file** — every per-model difference
is a class attribute or an OBIS map a subclass declares, never a branch here.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from gurux_dlms.enums import Unit
from gurux_dlms.objects import GXDLMSExtendedRegister, GXDLMSProfileGeneric, GXDLMSRegister

from arichds.acquisition.drivers._dlms import DlmsDriver
from arichds.acquisition.drivers._profile import (
    build_fields,
    coerce_clock_cell,
    meter_local_to_utc,
    positions_by_obis_attr,
)
from arichds.acquisition.drivers.base import BillingReading, IntervalReading
from arichds.constants import METER_LOCAL_UTC_OFFSET_HOURS, WH_TO_KWH_DIVISOR

logger = logging.getLogger(__name__)

#: The billing ProfileGeneric every CEWE model shares (F4).
BILLING_PROFILE_OBIS = "1.0.98.2.0.255"

#: Ordered bill-date candidates, first present in the live capture list wins
#: (D8). CEWE's own bill-date column, then the DLMS-standard Clock as a
#: fallback — a concrete driver may override this tuple, but no CEWE model
#: needs to.
CEWE_BILL_DATE_CANDIDATES: tuple[tuple[str, int], ...] = (("0.0.0.1.2.255", 2), ("0.0.1.0.0.255", 2))

#: The reset-reason cell (F5): ``255`` = not reset = the Open Period; any
#: other integer = a closed cut. Present on all three CEWE models' billing
#: capture list (confirmed 2026-07-21 per v1's field notes).
_RESET_REASON_KEY: tuple[str, int] = ("0.0.0.1.12.255", 2)
_RESET_REASON_NOT_RESET = 255

_RATE_SUFFIX: dict[int, str] = {0: "total", 1: "rate_a", 2: "rate_b", 3: "rate_c", 4: "rate_d"}

#: `C` -> (field prefix, required Unit) for energy (D=8, class 3 Register).
_ENERGY_BY_C: dict[int, tuple[str, Unit]] = {
    1: ("import_active_kwh", Unit.ACTIVE_ENERGY),
    2: ("export_active_kwh", Unit.ACTIVE_ENERGY),
    3: ("import_reactive_kvarh", Unit.REACTIVE_ENERGY),
    4: ("export_reactive_kvarh", Unit.REACTIVE_ENERGY),
}

#: `C` -> (field prefix, required Unit) for max demand (D=6, class 4
#: ExtendedRegister, attribute 2 — the value).
_DEMAND_BY_C: dict[int, tuple[str, Unit]] = {
    1: ("max_demand_import_active_kw", Unit.ACTIVE_POWER),
    2: ("max_demand_export_active_kw", Unit.ACTIVE_POWER),
    3: ("max_demand_import_reactive_kvar", Unit.REACTIVE_POWER),
    4: ("max_demand_export_reactive_kvar", Unit.REACTIVE_POWER),
}

#: `C` -> field prefix for Demand Time (D=6, class 4 ExtendedRegister,
#: attribute **5** — when the max-demand value was captured). Import side
#: only (D10, F2) — no screen shows the export side.
_DEMAND_TIME_BY_C: dict[int, str] = {1: "max_demand_import_active_time", 3: "max_demand_import_reactive_time"}

#: `C` -> (field prefix, required Unit) for Cumulative Demand (D=2, class 4
#: ExtendedRegister, attribute 2). Import side only (D10).
_CUMUL_DEMAND_BY_C: dict[int, tuple[str, Unit]] = {
    1: ("cumul_demand_import_active_kw", Unit.ACTIVE_POWER),
    3: ("cumul_demand_import_reactive_kvar", Unit.REACTIVE_POWER),
}

#: Every mapped billing capture column that carries a **scaled number**, keyed
#: on ``(OBIS, attribute)`` — identical scheme to
#: :mod:`~arichds.acquisition.drivers.smw110`'s billing map, extended with the
#: twenty M4c columns (D10). Demand Time is deliberately absent here — it is a
#: timestamp, mapped separately in :data:`CEWE_DEMAND_TIME_COLUMNS` below.
CEWE_MAPPED_BILLING_COLUMNS: dict[tuple[str, int], tuple[str, type, Unit]] = {
    **{
        (f"1.0.{c}.8.{e}.255", 2): (f"{prefix}_{suffix}", GXDLMSRegister, unit)
        for c, (prefix, unit) in _ENERGY_BY_C.items()
        for e, suffix in _RATE_SUFFIX.items()
    },
    **{
        (f"1.0.{c}.6.{e}.255", 2): (f"{prefix}_{suffix}", GXDLMSExtendedRegister, unit)
        for c, (prefix, unit) in _DEMAND_BY_C.items()
        for e, suffix in _RATE_SUFFIX.items()
    },
    **{
        (f"1.0.{c}.2.{e}.255", 2): (f"{prefix}_{suffix}", GXDLMSExtendedRegister, unit)
        for c, (prefix, unit) in _CUMUL_DEMAND_BY_C.items()
        for e, suffix in _RATE_SUFFIX.items()
    },
}

#: Every mapped Demand Time column, keyed on ``(OBIS, attribute)`` — attribute
#: **5** on the same OBIS the value's own attribute-2 cell uses (F2's
#: collision, why the position map must key on the pair). Never scaled, never
#: divided (D11) — converted meter-local -> UTC like a bill date.
CEWE_DEMAND_TIME_COLUMNS: dict[tuple[str, int], str] = {
    (f"1.0.{c}.6.{e}.255", 5): f"{prefix}_{suffix}"
    for c, prefix in _DEMAND_TIME_BY_C.items()
    for e, suffix in _RATE_SUFFIX.items()
}


def _read_scaler_unit(
    reader: Any,
    client: Any,
    cache: dict[tuple[str, type, Unit], float | None],
    obis: str,
    cosem_class: type,
    required_unit: Unit,
) -> float | None:
    """Read *obis*'s own ``scaler_unit`` (attr 3), memoized per *cache*.

    Shared with the billing sibling-fallback below and with a load-profile
    column's own-address attempt (D6) — the read-and-check shape is identical
    everywhere a multiplier is resolved.

    *required_unit* is deliberately part of the cache key, alongside *obis*
    and *cosem_class* — not an oversight to simplify later. Nothing in this
    module queries the same ``(obis, cosem_class)`` pair under two different
    required units today, so dropping it from the key would change nothing
    observable right now, but the key still names it: a future caller doing
    exactly that (the same physical register asked about for two different
    expected quantities) must get two independent cache entries, not one
    resolution silently reused for a unit it was never checked against.
    """
    key = (obis, cosem_class, required_unit)
    if key in cache:
        return cache[key]

    obj = cosem_class(obis)
    client.objects.append(obj)
    try:
        reader.read(obj, 3)
    except Exception:  # noqa: BLE001 — an unreadable object degrades to None below, never guessed.
        multiplier = None
    else:
        multiplier = obj.scaler if obj.unit == required_unit else None

    cache[key] = multiplier
    return multiplier


def resolve_scaler_candidates(
    reader: Any,
    client: Any,
    cache: dict[tuple[str, type, Unit], float | None],
    candidates: list[str],
    cosem_class: type,
    required_unit: Unit,
    field: str,
    model_name: str,
) -> float | None:
    """Try each OBIS in *candidates*, in order, and return the first
    multiplier that resolves — the one place every scaler-resolution attempt
    in this module goes through (billing's own-address/E=0/D=6 chain, and
    load profile's own-address/sibling pair), so the "unresolvable -> NULL,
    never guess" rule (D12) is enforced exactly once.

    Args:
        candidates: OBIS codes to try, most-preferred first. Duplicates are
            skipped so a column whose sibling happens to equal itself (the
            ``E=0`` total column, say) does not read its own address twice.
            Belt-and-braces on top of *cache*: ``_read_scaler_unit`` already
            memoizes by ``(obis, cosem_class, required_unit)``, so a repeated
            candidate would hit the cache and cost nothing measurable even
            without this guard — kept anyway because it makes "no duplicate
            attempts" true by construction, not by relying on every caller
            passing the same cache.

    Returns:
        The multiplier, or ``None`` if every candidate failed — a WARNING
        names *field* and the first (primary) candidate.
    """
    tried: list[str] = []
    for obis in candidates:
        if obis in tried:
            continue
        tried.append(obis)
        multiplier = _read_scaler_unit(reader, client, cache, obis, cosem_class, required_unit)
        if multiplier is not None:
            return multiplier

    logger.warning(
        "%s: could not resolve a scaler for %s (%s) — %s stays unscaled (None) on every row",
        model_name,
        candidates[0],
        field,
        field,
    )
    return None


def resolve_billing_multiplier(
    reader: Any,
    client: Any,
    cache: dict[tuple[str, type, Unit], float | None],
    capture_obis: str,
    cosem_class: type,
    required_unit: Unit,
    field: str,
    model_name: str,
) -> float | None:
    """Resolve *capture_obis*'s multiplier: its own ``scaler_unit`` first,
    then the ``E=0`` (total) sibling of the same ``C.D`` group, then — for
    ``D=2`` (Cumulative Demand) only — two ``D=6`` (max demand) fallbacks for
    the same ``C``: the same-tariff sibling, then the ``D=6`` group's own
    ``E=0`` total (review finding 2, v1's proven route:
    ``cewe-worker/_tcp_driver_base.py:861-873`` — *"D=2 cumulative demand:
    E=0 is not standalone-readable on Premier 550. Borrow the D=6 (max-demand)
    scaler — same physical quantity, same unit."*).

    **Both ``D=6`` candidates are needed, confirmed by the 2026-08-09 live
    re-read after the first version of this fallback (same-tariff ``D=6``
    only) still left every Cumulative Demand ``rate_a``..``rate_d`` column
    ``None``.** The meter denies ``scaler_unit`` on every ``D=6`` tariff
    column (``E=1``..``E=4``) exactly the way it denies every ``D=2`` one —
    only the ``D=6`` group's own total (``E=0``) answers directly, the same
    "E=0 total is known-readable" pattern
    :meth:`~arichds.acquisition.drivers.smw110.Smw110Driver._billing_multiplier`
    already relies on for energy. The ``E=0`` sibling of a ``D=2`` column
    *is* its own total, so that attempt is a no-op for the total column
    itself — the ``D=6`` E=0 fallback is what actually resolves every
    Cumulative Demand column, total and every tariff alike.

    Identical shape to :class:`~arichds.acquisition.drivers.smw110.Smw110Driver`'s
    proven billing approach (D6), now generalised to a candidate chain
    (:func:`resolve_scaler_candidates`) so further quantity-preserving
    fallbacks can be added without duplicating the read-and-check logic.

    Returns:
        The multiplier, or ``None`` if every attempt fails — the column is
        left ``None`` on every row rather than storing an unscaled number
        that looks like data.
    """
    parts = capture_obis.split(".")
    candidates = [capture_obis]

    e0_sibling = ".".join([*parts[:4], "0", parts[5]])
    candidates.append(e0_sibling)

    if parts[3] == "2":  # Cumulative Demand — borrow a D=6 max-demand scaler for the same C.
        d6_same_tariff = ".".join([*parts[:3], "6", *parts[4:]])
        candidates.append(d6_same_tariff)
        d6_total = ".".join([*parts[:3], "6", "0", parts[5]])
        candidates.append(d6_total)

    return resolve_scaler_candidates(reader, client, cache, candidates, cosem_class, required_unit, field, model_name)


def resolve_load_profile_multiplier(
    reader: Any,
    client: Any,
    cache: dict[tuple[str, type, Unit], float | None],
    capture_obis: str,
    sibling_obis: str | None,
    required_unit: Unit,
    field: str,
    model_name: str,
) -> float | None:
    """Resolve a load-profile column's multiplier: its own ``scaler_unit``
    (attr 3, class 3 Register) first, then *sibling_obis* if that fails
    (review finding 1) — the same denial pattern the SMW110W4 already has a
    proven fix for (:meth:`~arichds.acquisition.drivers.smw110.Smw110Driver._resolve_multiplier`),
    confirmed live on all three CEWE models by ``docs/meter-notes/cewe-billing-capture-objects.md``'s
    2026-08-09 scan: every measurement column's own-address read was refused.

    *cache* is threaded through from the caller so a chunked walk — which
    calls :meth:`CeweDriver.read_load_profile` once per 24 h chunk, up to 90
    times for a full backfill — resolves each column's multiplier once per
    connection, not once per chunk (review finding 3).
    """
    candidates = [capture_obis]
    if sibling_obis is not None:
        candidates.append(sibling_obis)
    return resolve_scaler_candidates(
        reader, client, cache, candidates, GXDLMSRegister, required_unit, field, model_name
    )


class CeweDriver(DlmsDriver):
    """Shared billing + load-profile read logic for the three CEWE models.

    Subclasses declare :attr:`LOAD_PROFILE_COLUMN_MAP` (``{logger_id:
    {(obis, attr): (IntervalReading field, sibling OBIS to borrow scaler_unit
    from or None, required Unit)}}``) and the connection hooks
    (:meth:`~arichds.acquisition.drivers._dlms.DlmsDriver._protocol_args`,
    :meth:`~arichds.acquisition.drivers._dlms.DlmsDriver._read_timeout_ms`).
    Everything else — billing, the bill-date/open-closed logic, the
    load-profile transport (range read, meter-local conversion) — lives here.
    """

    #: ``{logger_id: {(obis, attr): (field, sibling OBIS or None, required
    #: Unit)}}``. Empty on the base — every concrete CEWE driver overrides it
    #: (D15). The sibling is what :func:`resolve_load_profile_multiplier`
    #: falls back to when the column's own address denies ``scaler_unit``
    #: (review finding 1) — ``None`` for a column with no known working
    #: sibling.
    LOAD_PROFILE_COLUMN_MAP: dict[int, dict[tuple[str, int], tuple[str, str | None, Unit]]] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Add the per-connection load-profile scaler cache (review finding
        3) to whatever :class:`~arichds.acquisition.drivers._dlms.DlmsDriver`
        already sets up. A fresh dict per driver instance is correct here:
        the product builds a new driver per read call
        (``acquisition/poller.build_driver`` / ``load_profile.py``'s
        ``build_driver(device)``), so this cache's lifetime already matches
        "once per connection" without needing a reset hook on ``connect()``.
        """
        super().__init__(*args, **kwargs)
        self._lp_scaler_cache: dict[tuple[str, type, Unit], float | None] = {}

    @abstractmethod
    def get_obis_map(self) -> dict[str, tuple[str, int]]:
        """No instantaneous set for these models in v2 (ADR 0007) — no
        production caller since that ADR removed the instantaneous read.
        Kept only to satisfy the abstract interface; each concrete CEWE
        driver returns ``dict(INSTANTANEOUS_OBIS)`` (the same shared,
        field-proven map ``scripts/probe_meter.py`` walks), unlike
        :class:`~arichds.acquisition.drivers.smw110.Smw110Driver`, which
        returns ``{}`` because its instantaneous set differs from this one."""

    # ── Load profile ─────────────────────────────────────────────────────────

    def supports_load_profile(self) -> bool:
        """Yes, for every CEWE model — each declares at least one logger."""
        return bool(self.LOAD_PROFILE_COLUMN_MAP)

    def load_profile_loggers(self) -> tuple[int, ...]:
        """The logger ids this model's :attr:`LOAD_PROFILE_COLUMN_MAP` declares,
        ascending (D2/D15)."""
        return tuple(sorted(self.LOAD_PROFILE_COLUMN_MAP))

    def read_load_profile(self, logger_id: int, start_utc: datetime, end_utc: datetime) -> list[IntervalReading]:
        """Read one logger's profile (``1.0.99.{logger_id}.0.255``) over
        ``[start_utc, end_utc]`` by range (D14, F6) — v1-proven for CEWE, the
        opposite of the SMW110W4's entry-only access.

        Capture objects and capture period are read live on every call (D7,
        SPEC §3.5) — never cached, never assumed to be 900 s.

        Raises:
            ValueError: If either bound is a naive datetime, or *logger_id* is
                not one of :meth:`load_profile_loggers`.
        """
        if start_utc.tzinfo is None or end_utc.tzinfo is None:
            raise ValueError("read_load_profile() requires timezone-aware UTC datetimes")
        column_map = self.LOAD_PROFILE_COLUMN_MAP.get(logger_id)
        if column_map is None:
            raise ValueError(f"{self.model_name} has no logger {logger_id} — check load_profile_loggers() first")

        if self._reader is None or self._client is None:
            logger.warning("read_load_profile(%d) called on a disconnected driver %s", logger_id, self)
            return []

        profile_obis = f"1.0.99.{logger_id}.0.255"
        clock_key = ("0.0.1.0.0.255", 2)

        pg = GXDLMSProfileGeneric(profile_obis)
        self._client.objects.append(pg)

        self._reader.read(pg, 3)  # populates pg.captureObjects — live, never cached (D7)
        capture_period_sec = int(self._reader.read(pg, 4))

        positions = positions_by_obis_attr(pg.captureObjects)
        expected_cell_count = len(pg.captureObjects)
        clock_pos = positions.get(clock_key)

        # *self._lp_scaler_cache* is threaded through so a multi-chunk walk
        # (up to 90 calls for a full backfill) resolves each column once per
        # connection, not once per chunk (review finding 3).
        multipliers = {
            key: resolve_load_profile_multiplier(
                self._reader, self._client, self._lp_scaler_cache, key[0], sibling_obis, unit, field, self.model_name
            )
            for key, (field, sibling_obis, unit) in column_map.items()
            if key in positions
        }
        row_column_map = {key: field for key, (field, _sibling_obis, _unit) in column_map.items()}

        start_local = meter_local_to_utc_inverse(start_utc)
        end_local = meter_local_to_utc_inverse(end_utc)
        raw_rows = self._reader.readRowsByRange(pg, start_local, end_local) or []

        readings: list[IntervalReading] = []
        for row in raw_rows:
            if len(row) != expected_cell_count:
                logger.warning(
                    "%s: logger %d row has %d cells, live capture-object count is %d — skipping",
                    self.model_name,
                    logger_id,
                    len(row),
                    expected_cell_count,
                )
                continue

            local_dt = coerce_clock_cell(row[clock_pos]) if clock_pos is not None else None
            if local_dt is None:
                logger.warning("%s: logger %d row has no usable timestamp — skipping", self.model_name, logger_id)
                continue
            read_at = meter_local_to_utc(local_dt)
            # Firmware may return rows up to one capture period beyond the
            # requested end — filter to the requested window ourselves
            # (gurux-dlms skill, "ProfileGeneric by range").
            if read_at < start_utc or read_at > end_utc:
                continue

            fields = build_fields(row, positions, row_column_map, multipliers, scale=self._normalize)

            readings.append(
                IntervalReading(
                    read_at=read_at,
                    source=self.source,
                    logger_id=logger_id,
                    interval_sec=capture_period_sec,
                    volt_l1=fields.get("volt_l1"),
                    volt_l2=fields.get("volt_l2"),
                    volt_l3=fields.get("volt_l3"),
                    current_l1=fields.get("current_l1"),
                    current_l2=fields.get("current_l2"),
                    current_l3=fields.get("current_l3"),
                    freq=fields.get("freq"),
                    import_active_kwh=fields.get("import_active_kwh"),
                    import_reactive_kvarh=fields.get("import_reactive_kvarh"),
                    export_active_kwh=fields.get("export_active_kwh"),
                    export_reactive_kvarh=fields.get("export_reactive_kvarh"),
                    avg_geo_pf=fields.get("avg_geo_pf"),
                )
            )
        return readings

    # ── Billing ───────────────────────────────────────────────────────────────

    def supports_billing(self) -> bool:
        """Yes — every CEWE model shares the billing profile (F4)."""
        return True

    def read_billing(self) -> list[BillingReading]:
        """Read the whole billing buffer (``1.0.98.2.0.255``) full width, one
        entry-access call, entry 1 = newest (F4, F6) — no span, unlike the
        SMW110W4.

        Returns:
            Every row the meter holds, newest first — the meter's own
            reset-reason cell decides which row (if any) is the Open Period
            (D9), never entry position alone unless that column is absent.
        """
        if self._reader is None or self._client is None:
            logger.warning("read_billing() called on a disconnected driver %s", self)
            return []

        pg = GXDLMSProfileGeneric(BILLING_PROFILE_OBIS)
        self._client.objects.append(pg)

        self._reader.read(pg, 3)  # populates pg.captureObjects — live, never cached (D7)
        entries_in_use = int(self._reader.read(pg, 7))
        if entries_in_use <= 0:
            return []

        positions = positions_by_obis_attr(pg.captureObjects)
        expected_cell_count = len(pg.captureObjects)

        bill_date_key = next((key for key in CEWE_BILL_DATE_CANDIDATES if key in positions), None)
        if bill_date_key is None:
            logger.warning(
                "%s: no bill-date candidate present in the live capture list — nothing was stored", self.model_name
            )
            return []

        reset_reason_key = _RESET_REASON_KEY if _RESET_REASON_KEY in positions else None
        if reset_reason_key is None:
            logger.warning(
                "%s: reset-reason column %s is absent from the live capture list — "
                "falling back to positional open/closed classification (entry 1 = open)",
                self.model_name,
                _RESET_REASON_KEY[0],
            )

        scaler_cache: dict[tuple[str, type, Unit], float | None] = {}
        multipliers = {
            key: resolve_billing_multiplier(
                self._reader, self._client, scaler_cache, key[0], cosem_class, unit, field, self.model_name
            )
            for key, (field, cosem_class, unit) in CEWE_MAPPED_BILLING_COLUMNS.items()
            if key in positions
        }
        column_map = {key: field for key, (field, _cls, _unit) in CEWE_MAPPED_BILLING_COLUMNS.items()}
        demand_time_map = {key: field for key, field in CEWE_DEMAND_TIME_COLUMNS.items() if key in positions}
        column_map.update(demand_time_map)

        rows = self._reader.readRowsByEntry(pg, 1, entries_in_use) or []

        try:
            meter_serial = self.read_meter_serial()
        except Exception:  # noqa: BLE001 — an annotation column must not cost the whole read.
            logger.warning(
                "%s: meter serial read failed after the billing buffer was already read — "
                "rows stored with meter_serial=None",
                self.model_name,
            )
            meter_serial = None

        readings: list[BillingReading] = []
        open_assigned = False
        for position, row in enumerate(rows):
            if len(row) != expected_cell_count:
                logger.warning(
                    "%s: billing row has %d cells, live capture-object count is %d — skipping",
                    self.model_name,
                    len(row),
                    expected_cell_count,
                )
                if position == 0:
                    logger.warning(
                        "%s: entry 1 (the running billing period) was malformed — "
                        "no Open Period will be recorded from this read",
                        self.model_name,
                    )
                continue

            local_dt = coerce_clock_cell(row[positions[bill_date_key]])
            if local_dt is None:
                if position == 0:
                    logger.warning(
                        "%s: the running billing period (entry 1) has no usable bill date — "
                        "no Open Period will be recorded from this read",
                        self.model_name,
                    )
                else:
                    logger.warning("%s: billing row has no usable bill date — skipping", self.model_name)
                continue
            bill_date = meter_local_to_utc(local_dt)

            is_open, open_assigned = self._classify_open(row, positions, reset_reason_key, position, open_assigned)

            # `build_fields` computes every numeric field (Demand Time columns
            # included, since they are in `column_map`) — but a Demand Time
            # column has no entry in `multipliers`, so `build_fields` leaves it
            # `None`; the loop below overwrites those specific fields with the
            # coerced, meter-local -> UTC value instead (D11: never scaled).
            # There is deliberately no `passthrough_keys` here (review finding
            # 6) — that parameter's output would only be overwritten again by
            # this loop, so passing it was a guard that guarded nothing.
            fields = build_fields(
                row, positions, column_map, multipliers, scale=lambda _field, value: value / WH_TO_KWH_DIVISOR
            )
            for key, field in demand_time_map.items():
                raw_cell = row[positions[key]]
                local_time = coerce_clock_cell(raw_cell)
                fields[field] = meter_local_to_utc(local_time) if local_time is not None else None

            readings.append(
                BillingReading(
                    bill_date=bill_date,
                    source=self.source,
                    is_open=is_open,
                    meter_serial=meter_serial,
                    **fields,
                )
            )
        return readings

    def _classify_open(
        self,
        row: list[Any],
        positions: dict[tuple[str, int], int],
        reset_reason_key: tuple[str, int] | None,
        position: int,
        already_assigned: bool,
    ) -> tuple[bool, bool]:
        """Decide whether *row* is the Open Period (D9).

        Ask the meter first: the reset-reason cell, ``255`` = not reset = open.
        Fall back to entry position only when the column itself is absent from
        the live capture list. A non-integer/absent cell on a present column
        classifies closed and WARNs — asymmetric on purpose (D9): a wrongly
        "open" row collides with the one-open-slot unique index and fails the
        write for every row, while a wrongly "closed" row costs one history row.

        Returns:
            ``(is_open, already_assigned-after-this-row)`` — at most one
            ``True`` per call (D9): a later row that would also classify open
            is kept closed and WARNs instead.
        """
        if reset_reason_key is not None:
            raw = row[positions[reset_reason_key]]
            if raw is None or not isinstance(raw, (int, float, Decimal)):
                logger.warning(
                    "%s: reset-reason cell on row %d is not a usable integer — classifying closed",
                    self.model_name,
                    position,
                )
                candidate = False
            else:
                candidate = int(raw) == _RESET_REASON_NOT_RESET
        else:
            candidate = position == 0

        if candidate and already_assigned:
            logger.warning(
                "%s: row %d also classifies as the Open Period — a read returns at most one; "
                "keeping the first and treating this row as closed",
                self.model_name,
                position,
            )
            return False, already_assigned

        return candidate, already_assigned or candidate


def meter_local_to_utc_inverse(utc_dt: datetime) -> datetime:
    """Convert a UTC instant to meter-local time for a ``readRowsByRange`` bound.

    The inverse of :func:`~arichds.acquisition.drivers._profile.meter_local_to_utc`
    (D14, gurux-dlms skill "Meter-local time in selective access") — the meter
    stores buffer timestamps in local time and expects the selective-access
    filter in the same local time, naive (no tzinfo), the way v1 sends it.
    """
    return (utc_dt + timedelta(hours=METER_LOCAL_UTC_OFFSET_HOURS)).replace(tzinfo=None)
