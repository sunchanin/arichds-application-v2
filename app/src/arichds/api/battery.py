"""Battery — reading a device's stored Battery Readings (M7-2, issue #29).

The counterpart to the writer: :mod:`arichds.acquisition.battery` fills
``battery_readings`` from the Scheduler's hourly ``battery`` job. This module
is the only thing that *reads* those rows back out — mirrors
:mod:`arichds.api.billing` in shape (``_as_utc``, ``_require_device_exists``,
the shared ``matching`` filter tuple, the paged response model).

**Bounded from the first commit.** ``docs/issues/002-energy-registers-endpoint-is-unbounded.md``
is the open ticket for the one endpoint in this codebase that is not — this
must not become the second, so ``limit``/``offset`` are required parameters
with bounds from the start.

**No Read-now endpoint here** (D5) — there is no Manual Read path for
battery; the only writer is the Scheduler's background job.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from arichds.api.deps import SessionDep, get_current_user, require_feature
from arichds.api.envelope import ApiResponse
from arichds.db.models import BatteryReading, Device

router = APIRouter(
    prefix="/api/battery",
    tags=["battery"],
    dependencies=[Depends(get_current_user), Depends(require_feature("battery"))],
)


class BatteryRowOut(BaseModel):
    """One stored Battery Reading, as the Battery page renders it.

    Attributes:
        id: The row's own id.
        device_id: Which device this reading belongs to.
        device_name: Joined from ``devices.name`` — the page lists rows
            across devices, so the id alone is not enough to render a row.
        meter_serial: Joined from ``devices.meter_serial``, or None.
        read_at: **Our** clock, UTC — not the meter's.
        status: The raw value the meter reported, verbatim — never scaled,
            never thresholded, never coloured (D8). ``None`` when the meter
            answered with nothing.
    """

    id: int
    device_id: int
    device_name: str
    meter_serial: str | None
    read_at: datetime
    status: str | None


class BatteryPage(BaseModel):
    """One page of Battery Readings.

    Attributes:
        items: The rows, newest ``read_at`` first.
        total: How many rows match the filters, ignoring paging.
        limit: The page size that was applied.
        offset: How many rows were skipped.
    """

    items: list[BatteryRowOut]
    total: int
    limit: int
    offset: int


def _as_utc(moment: datetime) -> datetime:
    """Read a naive query parameter as UTC rather than refusing it — same
    reasoning as ``api/billing.py``'s helper of the same name."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _require_device_exists(session: SessionDep, device_id: int) -> None:
    """Refuse with 404 unless *device_id* names a device — same rule
    ``api/billing.py``/``api/special_days.py`` give."""
    if session.get(Device, device_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such device.")


@router.get("")
def list_battery_readings(
    session: SessionDep,
    device_id: Annotated[int | None, Query(ge=1, description="Restrict to one device; omitted = every device")] = None,
    start: Annotated[datetime | None, Query(description="Inclusive lower bound on read_at, UTC")] = None,
    end: Annotated[datetime | None, Query(description="**Exclusive** upper bound on read_at, UTC")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Page size")] = 100,
    offset: Annotated[int, Query(ge=0, description="Rows to skip")] = 0,
) -> ApiResponse[BatteryPage]:
    """Return one page of Battery Readings, newest ``read_at`` first.

    Any authenticated role — reading a device's data is not admin-only
    (``devices.py``'s own rule, and Billing's/Load Profile's).
    """
    if device_id is not None:
        _require_device_exists(session, device_id)

    lower = _as_utc(start) if start is not None else None
    upper = _as_utc(end) if end is not None else None
    if lower is not None and upper is not None and upper <= lower:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="`end` must be later than `start` — the range is half-open, [start, end).",
        )

    filters = []
    if device_id is not None:
        filters.append(BatteryReading.device_id == device_id)
    if lower is not None:
        filters.append(BatteryReading.read_at >= lower)
    if upper is not None:
        filters.append(BatteryReading.read_at < upper)
    # Built once and used by both queries below, for the reason
    # api/billing.py:296-298 gives: `total` is only meaningful as the unpaged
    # count of *the same* filter.
    matching = tuple(filters)

    rows = session.execute(
        select(BatteryReading, Device.name, Device.meter_serial)
        .join(Device, BatteryReading.device_id == Device.id)
        .where(*matching)
        .order_by(BatteryReading.read_at.desc(), BatteryReading.device_id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    total = session.scalar(select(func.count()).select_from(BatteryReading).where(*matching)) or 0

    items = [
        BatteryRowOut(
            id=reading.id,
            device_id=reading.device_id,
            device_name=device_name,
            meter_serial=meter_serial,
            read_at=_as_utc(reading.read_at),
            status=reading.status,
        )
        for reading, device_name, meter_serial in rows
    ]

    return ApiResponse.ok(BatteryPage(items=items, total=total, limit=limit, offset=offset))
