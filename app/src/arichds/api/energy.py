"""Energy — the Time-of-Use aggregation (Summary Report tab), the stored
Energy Registers (Meter Registers tab), and its Read now trigger (M7-1,
issue #28; CONTEXT.md — Energy Summary / Energy Registers).

**The Summary Report is stored, and recomputed over the whole retention
window every scheduler cycle** (ADR 0022, supersedes ADR 0012; M14, ticket
01): ``GET /api/energy/summary`` below reads ``energy_summary_days`` through
:func:`arichds.db.energy_summary_store.stored_energy_summary_rows`, never
re-aggregating ``load_profile_readings`` on the request. The response shape
and the 31-day bound are unchanged. The Peak / Off-Peak / Holiday
classification itself is untouched — it still lives in
:mod:`arichds.db.energy_query`, which the recompute job calls — ported from
v1 ``cewe-worker/src/load_profile/repository.py`` (``_IS_HOLIDAY_PREDICATE``,
``_ENERGY_SUMMARY_SQL``), translated MySQL -> SQLite:

* weekend: MySQL ``DAYOFWEEK(...) IN (1, 7)`` (1 = Sunday) becomes SQLite
  ``strftime('%w', ...) IN ('0', '6')`` (0 = Sunday).
* local day: MySQL ``ADDTIME(read_at, tz_shift)`` becomes SQLite's own
  ``date(col, '+N hours')`` modifier, as ``api/records.py`` already uses it.
* peak hour: **UTC, unshifted**, on both sides — the peak constants
  (:data:`~arichds.constants.TOU_PEAK_START_UTC` /
  :data:`~arichds.constants.TOU_PEAK_END_UTC`) are pre-shifted for ICT, so
  applying the local-day shift to the hour too would double-shift it. v1's own
  ADR 0016 document omits the ``ADDTIME`` on the hour term; the code is
  followed here, not the document.

**The day/month/day-of-week shift is always** :data:`~arichds.constants.METER_LOCAL_UTC_OFFSET_HOURS`
**— never a request parameter.** Unlike ``api/records.py``'s
``utc_offset_minutes``, a browser-supplied offset here would classify the
*day* in one zone while the pre-shifted peak-hour constants stay fixed to
ICT, so the two could disagree.

**Logger 1 only** (decision 6) — it carries the energy columns on every
model (``drivers/base.py``); aggregating across loggers would double-count on
the first model that captures energy in more than one profile.

**Energy Registers are a different half of this page** (CONTEXT.md): a
button-triggered snapshot of the meter's cumulative counters, stored in
``energy_register_readings`` and read back here, sharing nothing with the
Summary Report but the license key.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from arichds.acquisition.energy_registers import read_and_store_energy_registers
from arichds.api.deps import SessionDep, get_current_user, require_feature
from arichds.api.envelope import ApiResponse
from arichds.constants import (
    MANUAL_READ_LOCK_TIMEOUT_SEC,
)
from arichds.db.app_settings import EXPORT_OUTPUT_DIR_DEFAULT, EXPORT_OUTPUT_DIR_KEY, get_setting
from arichds.db.energy_query import EnergySummaryReport
from arichds.db.energy_summary_store import stored_energy_summary_rows
from arichds.db.models import Device, EnergyRegisterReading
from arichds.db.session import session_scope
from arichds.export.energy_csv import export_energy_range

router = APIRouter(
    prefix="/api/energy",
    tags=["energy"],
    dependencies=[Depends(get_current_user), Depends(require_feature("energy_summary"))],
)

#: The most local days one Summary Report request may span, inclusive of both
#: ends — same bound and same reasoning as ``api/records.py`` (decision 22).
MAX_DAYS = 31


def _require_device_exists(session: Session, device_id: int) -> None:
    """Refuse with 404 unless *device_id* names a device — same rule
    ``api/records.py``/``api/billing.py`` give: an unknown id must not be
    answered with an empty report."""
    if session.get(Device, device_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such device.")


@router.get("/summary")
def read_energy_summary(
    session: SessionDep,
    device_id: Annotated[int, Query(ge=1, description="Which device's Logger 1 to aggregate")],
    start_date: Annotated[date, Query(description="First local calendar day, inclusive")],
    end_date: Annotated[date, Query(description="Last local calendar day, inclusive")],
) -> ApiResponse[EnergySummaryReport]:
    """Return the Time-of-Use daily totals for one device over a bounded
    range of local dates. Any authenticated role — reading a device's data is
    not admin-only (matches ``api/records.py``/``api/billing.py``).

    **Stored, not live** (ADR 0022): this reads ``energy_summary_days``, the
    recompute job's own table — never ``load_profile_readings`` directly.
    """
    _require_device_exists(session, device_id)

    if end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="`end_date` must not be earlier than `start_date` — the range is inclusive of both ends.",
        )
    span = (end_date - start_date).days + 1
    if span > MAX_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"The range spans {span} days; at most {MAX_DAYS} may be asked for at once.",
        )

    return ApiResponse.ok(
        EnergySummaryReport(days=stored_energy_summary_rows(session, device_id, start_date, end_date))
    )


class EnergyExportOut(BaseModel):
    """What the Energy Summary save button did (M13, issue 02).

    Attributes:
        rows_written: How many local days were written. Zero means the range
            holds no stored Interval Readings at all — a normal answer, not an
            error.
        path: The file written, or ``None`` when nothing was.
    """

    rows_written: int
    path: str | None


@router.post("/export")
def export_energy_summary(
    session: SessionDep,
    device_id: Annotated[int, Query(ge=1)],
    start_date: Annotated[date, Query(description="First local calendar day, inclusive")],
    end_date: Annotated[date, Query(description="Last local calendar day, inclusive")],
) -> ApiResponse[EnergyExportOut]:
    """Write the Time-of-Use split for one device and range to its own file.

    Any authenticated role, matching the Summary Report this saves.

    **This is the corrective for a stale daily file**, and the only one. The
    daily file records what was true the night it was written; a Holiday
    entered later, or Interval Readings that arrived through a backfill, change
    what the same days should say. Pressing this produces a file that agrees
    with the screen right now.

    The same range bound the Summary Report carries applies here, for the same
    reason — and so that a press can never turn into an unbounded scan.

    **``export_output_dir`` is required**: a person pressing a button must be
    told the destination was never set, not handed a silent zero.
    """
    _require_device_exists(session, device_id)

    if end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="`end_date` must not be earlier than `start_date` — the range is inclusive of both ends.",
        )
    span = (end_date - start_date).days + 1
    if span > MAX_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"The range spans {span} days; at most {MAX_DAYS} may be asked for at once.",
        )

    output_dir = get_setting(session, EXPORT_OUTPUT_DIR_KEY, EXPORT_OUTPUT_DIR_DEFAULT).strip()
    if not output_dir:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="export_output_dir is not configured — nothing to export to. Set it on the Load Profile page.",
        )

    result = export_energy_range(device_id, start_date, end_date)
    return ApiResponse.ok(
        EnergyExportOut(rows_written=result.rows_written, path=str(result.path) if result.path else None)
    )


# ─── Energy Registers (Meter Registers tab) ────────────────────────────────


class EnergyRegisterRowOut(BaseModel):
    """One stored ``energy_register_readings`` row, as the Meter Registers
    tab renders it (decision 11: divided by ``WH_TO_KWH_DIVISOR``
    unconditionally, already done by the driver at write time)."""

    id: int
    device_id: int
    read_at: datetime
    meter_serial: str | None

    import_active_kwh_total: float | None
    import_active_kwh_rate_a: float | None
    import_active_kwh_rate_b: float | None
    import_active_kwh_rate_c: float | None
    import_active_kwh_rate_d: float | None

    export_active_kwh_total: float | None
    export_active_kwh_rate_a: float | None
    export_active_kwh_rate_b: float | None
    export_active_kwh_rate_c: float | None
    export_active_kwh_rate_d: float | None

    import_reactive_kvarh_total: float | None
    import_reactive_kvarh_rate_a: float | None
    import_reactive_kvarh_rate_b: float | None
    import_reactive_kvarh_rate_c: float | None
    import_reactive_kvarh_rate_d: float | None

    export_reactive_kvarh_total: float | None
    export_reactive_kvarh_rate_a: float | None
    export_reactive_kvarh_rate_b: float | None
    export_reactive_kvarh_rate_c: float | None
    export_reactive_kvarh_rate_d: float | None

    @field_validator("read_at")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        """Re-attach UTC to the naive datetime SQLite hands back — same rule
        as ``api/billing.py``'s ``BillingRowOut._ensure_utc``."""
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class EnergyRegisterReadOut(BaseModel):
    """What ``POST /api/energy/registers/read`` did.

    Attributes:
        row: The stored snapshot, or ``None`` when the read itself failed
            (a connection error, a busy Transport Endpoint).
        error: An operator-facing sentence, or ``None`` on success — a
            meter failure is a verdict carried in the payload, never an
            HTTP error status (mirrors Test Connection / Read Now
            elsewhere in this product: "always arrives on a 200 — the
            verdict is in here").
    """

    row: EnergyRegisterRowOut | None
    error: str | None


#: Every ``energy_register_readings`` measurement column, read off the ORM
#: model itself (mirrors ``api/billing.py``'s own ``_MEASUREMENT_COLUMN_NAMES``)
#: so a future column migration is picked up automatically.
_IDENTITY_COLUMNS = frozenset({"id", "device_id", "read_at", "source", "meter_serial", "created_at", "updated_at"})
_MEASUREMENT_COLUMN_NAMES: tuple[str, ...] = tuple(
    column.name for column in EnergyRegisterReading.__table__.columns if column.name not in _IDENTITY_COLUMNS
)


def _to_register_row_out(row: EnergyRegisterReading) -> EnergyRegisterRowOut:
    return EnergyRegisterRowOut(
        id=row.id,
        device_id=row.device_id,
        read_at=row.read_at,
        meter_serial=row.meter_serial,
        **{name: getattr(row, name) for name in _MEASUREMENT_COLUMN_NAMES},
    )


@router.get("/registers")
def list_energy_registers(
    session: SessionDep,
    device_id: Annotated[int, Query(ge=1, description="Which device's stored Energy Registers to return")],
) -> ApiResponse[list[EnergyRegisterRowOut]]:
    """Return every stored Energy Registers snapshot for one device, newest
    first. Any authenticated role."""
    _require_device_exists(session, device_id)
    rows = session.scalars(
        select(EnergyRegisterReading)
        .where(EnergyRegisterReading.device_id == device_id)
        .order_by(EnergyRegisterReading.read_at.desc())
    ).all()
    return ApiResponse.ok([_to_register_row_out(row) for row in rows])


@router.post("/registers/read")
def trigger_energy_register_read(
    device_id: Annotated[int, Query(ge=1)],
    session: SessionDep,
) -> ApiResponse[EnergyRegisterReadOut]:
    """Read the meter's Energy Registers now, through the Manual Read lock
    (decision — button-triggered only, no scheduler job). Any authenticated
    role — matches every other Read now surface in this product.

    Raises:
        HTTPException: 404 for an unknown device, or one whose driver has
            no Energy Registers at all (``supported=False``) — a structural
            fact about the device, not a live-read failure. A live-read
            failure (connection dropped, endpoint busy) is **not** an
            HTTPException — it comes back on the payload's ``error`` field,
            same as Test Connection.
    """
    _require_device_exists(session, device_id)

    result = read_and_store_energy_registers(device_id, lock_timeout_sec=MANUAL_READ_LOCK_TIMEOUT_SEC)
    if not result.supported:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=result.error or "This device has no Energy Registers."
        )
    if result.row_id is None:
        return ApiResponse.ok(EnergyRegisterReadOut(row=None, error=result.error))

    with session_scope() as inner_session:
        row = inner_session.get(EnergyRegisterReading, result.row_id)
        return ApiResponse.ok(
            EnergyRegisterReadOut(row=_to_register_row_out(row) if row is not None else None, error=None)
        )
