"""Billing — reading a device's stored Billing Readings (M6a, issue #21).

The counterpart to the writer: :mod:`arichds.acquisition.billing` fills
``billing_readings`` from Read now and the Scheduler's ``billing`` job. This
module is the only thing that *reads* those rows back out — mirrors
:mod:`arichds.api.load_profile` in shape (``_as_utc``, ``_require_device_exists``,
the shared ``matching`` filter tuple, the paged response model).

**Two differences from Load Profile, both deliberate (SPEC §3.6):**

* ``status`` (``closed``/``open``) is **required** — it is what the two Billing
  page tabs are — and maps to ``record_status IS NULL`` / ``= 'open'``.
* ``device_id`` and the date range are **optional**. Load Profile forces a
  range because one meter can hold 8,640 rows over 90 days; billing is ~13
  rows per device per year, so the same rule would only hide data.

**Eight columns only.** The response carries the ``*_total`` column of each of
the eight measurement groups — the 32 tariff columns are stored but not
returned, mirroring ``LoadProfileRowOut``'s rule that a response carries
exactly what the page renders. Surfacing tariffs is a later slice's job.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arichds.api.deps import SessionDep, get_current_user
from arichds.api.envelope import ApiResponse
from arichds.db.models import BillingReading, Device

router = APIRouter(prefix="/api/billing", tags=["billing"], dependencies=[Depends(get_current_user)])


class BillingRowOut(BaseModel):
    """One Billing Reading as the Billing page renders it — either tab.

    Attributes:
        device_id: Which device this period belongs to.
        device_name: Joined from ``devices.name`` — the page lists rows across
            devices, so the id alone is not enough to render a row.
        bill_date: The meter's own Clock cell for this period — UTC (CONTEXT.md
            — Bill Date).
        read_at: When *we* read it — UTC.
        meter_serial: Snapshot per row, or None.
    """

    device_id: int
    device_name: str
    bill_date: datetime
    read_at: datetime
    meter_serial: str | None

    import_active_kwh_total: float | None
    export_active_kwh_total: float | None
    import_reactive_kvarh_total: float | None
    export_reactive_kvarh_total: float | None
    max_demand_import_active_kw_total: float | None
    max_demand_export_active_kw_total: float | None
    max_demand_import_reactive_kvar_total: float | None
    max_demand_export_reactive_kvar_total: float | None

    @field_validator("bill_date", "read_at")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        """Re-attach UTC to the naive datetime SQLite hands back.

        Same rule as ``LoadProfileRowOut._ensure_utc`` — SQLite has no
        timezone type, so a column declared ``DateTime(timezone=True)`` comes
        back naive and would otherwise be read by the browser as local time.
        """
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class BillingPage(BaseModel):
    """One page of Billing Readings, either tab.

    Attributes:
        items: The rows, newest ``bill_date`` first.
        total: How many rows match the filters, ignoring paging.
        limit: The page size that was applied.
        offset: How many rows were skipped.
    """

    items: list[BillingRowOut]
    total: int
    limit: int
    offset: int


def _as_utc(moment: datetime) -> datetime:
    """Read a naive query parameter as UTC rather than refusing it.

    Same reasoning as ``api/load_profile.py``'s helper of the same name: every
    stored timestamp here is UTC, so coercing a naive instant beats a 422
    nobody can act on.
    """
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _require_device_exists(session: Session, device_id: int) -> None:
    """Refuse with 404 unless *device_id* names a device.

    Written here rather than imported, for the same reason
    ``api/load_profile.py`` gives: an unknown id must not be answered with an
    empty page, or a typo in a dropdown looks exactly like a meter that has
    never been read.
    """
    if session.get(Device, device_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such device.")


@router.get("")
def list_billing_readings(
    session: SessionDep,
    status_: Annotated[
        Literal["closed", "open"], Query(alias="status", description="Which tab: closed periods or the Open Period")
    ],
    device_id: Annotated[int | None, Query(ge=1, description="Restrict to one device; omitted = every device")] = None,
    start: Annotated[datetime | None, Query(description="Inclusive lower bound on bill_date, UTC")] = None,
    end: Annotated[datetime | None, Query(description="**Exclusive** upper bound on bill_date, UTC")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Page size")] = 100,
    offset: Annotated[int, Query(ge=0, description="Rows to skip")] = 0,
) -> ApiResponse[BillingPage]:
    """Return one page of Billing Readings, newest ``bill_date`` first.

    Any authenticated role — reading a device's data is not admin-only
    (``devices.py``'s own rule, and Load Profile's).

    Unlike Load Profile, ``device_id`` and the range are optional: billing's
    row volume (~13/device/year) never justifies forcing one.
    """
    if device_id is not None:
        _require_device_exists(session, device_id)

    lower = _as_utc(start) if start is not None else None
    upper = _as_utc(end) if end is not None else None
    if lower is not None and upper is not None and upper <= lower:
        # Same sentence shape as api/load_profile.py:160-163.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="`end` must be later than `start` — the range is half-open, [start, end).",
        )

    status_filter = (
        BillingReading.record_status.is_(None) if status_ == "closed" else BillingReading.record_status == "open"
    )
    filters = [status_filter]
    if device_id is not None:
        filters.append(BillingReading.device_id == device_id)
    if lower is not None:
        filters.append(BillingReading.bill_date >= lower)
    if upper is not None:
        filters.append(BillingReading.bill_date < upper)
    # Built once and used by both queries below, for the reason
    # api/load_profile.py:165-168 gives: `total` is only meaningful as the
    # unpaged count of *the same* filter.
    matching = tuple(filters)

    rows = session.execute(
        select(BillingReading, Device.name)
        .join(Device, BillingReading.device_id == Device.id)
        .where(*matching)
        .order_by(BillingReading.bill_date.desc(), BillingReading.device_id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    total = session.scalar(select(func.count()).select_from(BillingReading).where(*matching)) or 0

    items = [
        BillingRowOut(
            device_id=reading.device_id,
            device_name=device_name,
            bill_date=reading.bill_date,
            read_at=reading.read_at,
            meter_serial=reading.meter_serial,
            import_active_kwh_total=reading.import_active_kwh_total,
            export_active_kwh_total=reading.export_active_kwh_total,
            import_reactive_kvarh_total=reading.import_reactive_kvarh_total,
            export_reactive_kvarh_total=reading.export_reactive_kvarh_total,
            max_demand_import_active_kw_total=reading.max_demand_import_active_kw_total,
            max_demand_export_active_kw_total=reading.max_demand_export_active_kw_total,
            max_demand_import_reactive_kvar_total=reading.max_demand_import_reactive_kvar_total,
            max_demand_export_reactive_kvar_total=reading.max_demand_export_reactive_kvar_total,
        )
        for reading, device_name in rows
    ]

    return ApiResponse.ok(BillingPage(items=items, total=total, limit=limit, offset=offset))
