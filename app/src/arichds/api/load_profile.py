"""Load Profile — reading a device's stored Interval Readings (M5b-1).

The counterpart to the writer: #15 taught Read now to store a load profile and
#16 gave the Scheduler a job that does the same on a cadence. This module is the
only thing that *reads* those rows back out.

It is deliberately not in ``devices.py``. That module's docstring states that no
handler in it reports a measured value (ADR 0007), and every row here is exactly
that — but a *recorded interval*, not a live one, which is the distinction
ADR 0007 draws and the thing it left standing. Records (M5b-2) has its own home
next to this one, in ``records.py``.

**The range is half-open** — ``read_at >= start AND read_at < end``, v1's own
bounds (``cewe-worker/src/load_profile/repository.py:237-238``). A closed upper
bound forces every caller to decide whether the last millisecond of the day is
in or out; a half-open one lets "the whole of the 3rd" be written as
``[3rd 00:00, 4th 00:00)`` with nothing to round.

**Nothing is merged.** v1 folded Logger 2 into Logger 1 with a ``LEFT JOIN`` and
``COALESCE``; SPEC §3.5 records why that is wrong — on a Premier 550 the two
loggers map different registers onto the same column, so the merge silently
overwrites values. Both loggers come back as their own rows, each carrying its
``logger_id``, exactly as CONTEXT.md defines an Interval Reading.

**Access is any authenticated role.** Changing a device is admin-only; *reading*
a device's data is not (``devices.py`` — ``list_device_events`` carries no
admin dependency), and stored readings are device data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arichds.api.deps import SessionDep, get_current_user, require_feature
from arichds.api.envelope import ApiResponse
from arichds.db.models import Device, LoadProfileReading

router = APIRouter(
    prefix="/api/load-profile",
    tags=["load-profile"],
    dependencies=[Depends(get_current_user), Depends(require_feature("load_profile"))],
)


class LoadProfileRowOut(BaseModel):
    """One Interval Reading as the Load Profile page renders it.

    The twelve measurement columns keep their **exact model attribute names**,
    so nothing between the driver that normalized them and the table that shows
    them has to translate. All twelve are nullable and stay so: the only model
    in service (SMW110W4) captures seven of them, and the page's contract is
    that an absent column renders as an em dash, never as ``0``.

    ``source``, ``interval_sec`` and ``id`` are deliberately absent — no column
    on the page reads them.

    Attributes:
        read_at: When the meter recorded the interval — **UTC, timezone-aware**.
        logger_id: Which of the meter's load profiles the row came from. Part of
            the row's identity, never a merge key.
    """

    model_config = ConfigDict(from_attributes=True)

    read_at: datetime
    logger_id: int

    import_active_kwh: float | None
    import_reactive_kvarh: float | None
    export_active_kwh: float | None
    export_reactive_kvarh: float | None
    avg_geo_pf: float | None
    volt_l1: float | None
    volt_l2: float | None
    volt_l3: float | None
    current_l1: float | None
    current_l2: float | None
    current_l3: float | None
    freq: float | None

    @field_validator("read_at")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        """Re-attach UTC to the naive datetime SQLite hands back.

        Same rule as ``DeviceEventOut._ensure_utc`` — SQLite has no timezone
        type, so a column declared ``DateTime(timezone=True)`` comes back naive
        and would otherwise be read by the browser as local time.
        """
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class LoadProfilePage(BaseModel):
    """One page of a device's Interval Readings.

    Mirrors ``DeviceEventPage``: ``total`` is the **unpaged** count under the
    same filters, which is what lets the table show "1-100 of 2,880" and know
    another page exists.

    Attributes:
        items: The readings, newest first.
        total: How many rows match the device and range, ignoring paging.
        limit: The page size that was applied.
        offset: How many rows were skipped.
    """

    items: list[LoadProfileRowOut]
    total: int
    limit: int
    offset: int


def _as_utc(moment: datetime) -> datetime:
    """Read a naive query parameter as UTC rather than refusing it.

    The page always sends an offset (``dayjs().toISOString()``), but a naive
    instant from a curl or a script is unambiguous in a product whose every
    stored timestamp is UTC — coercing beats a 422 nobody can act on.
    """
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _require_device_exists(session: Session, device_id: int) -> None:
    """Refuse with 404 unless *device_id* names a device.

    Written here rather than imported from ``devices.py``: that module's
    ``_require_device`` is private and returns a row this handler has no use
    for — the readings are queried by ``device_id``, never through the device.
    An unknown id must not be answered with an empty page, or a typo in a
    dropdown looks exactly like a meter that has never been read.
    """
    if session.get(Device, device_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such device.")


@router.get("")
def list_interval_readings(
    session: SessionDep,
    device_id: Annotated[int, Query(ge=1, description="Which device's readings to return")],
    start: Annotated[datetime, Query(description="Inclusive lower bound, UTC")],
    end: Annotated[datetime, Query(description="**Exclusive** upper bound, UTC")],
    limit: Annotated[int, Query(ge=1, le=500, description="Page size")] = 100,
    offset: Annotated[int, Query(ge=0, description="Rows to skip")] = 0,
) -> ApiResponse[LoadProfilePage]:
    """Return one page of a device's Interval Readings, newest first.

    Any authenticated role. The ordering is ``read_at DESC, logger_id ASC``, and
    it is *total*: ``(device_id, logger_id, read_at)`` is unique, so no two rows
    of one device tie on both keys and paging cannot repeat or skip a row.
    """
    _require_device_exists(session, device_id)
    lower, upper = _as_utc(start), _as_utc(end)
    if upper <= lower:
        # Raised here rather than declared on the Query: a validator sees one
        # parameter and cannot compare two. Both halves of an inverted or empty
        # range select nothing, and answering 200 with an empty page would let a
        # picker bug read as "this meter has no data".
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="`end` must be later than `start` — the range is half-open, [start, end).",
        )

    # Written once and used by both queries on purpose: ``total`` is only
    # meaningful as the unpaged count of *the same* filter, and two hand-copied
    # WHERE clauses are free to drift into a page whose rows and whose total
    # disagree.
    matching = (
        LoadProfileReading.device_id == device_id,
        LoadProfileReading.read_at >= lower,
        LoadProfileReading.read_at < upper,
    )

    rows = session.scalars(
        select(LoadProfileReading)
        .where(*matching)
        .order_by(LoadProfileReading.read_at.desc(), LoadProfileReading.logger_id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    total = session.scalar(select(func.count()).select_from(LoadProfileReading).where(*matching)) or 0

    return ApiResponse.ok(
        LoadProfilePage(
            items=[LoadProfileRowOut.model_validate(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )
    )
