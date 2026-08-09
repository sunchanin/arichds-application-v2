"""Records — is the stored load-profile data complete? (M5b-2)

One row per ``(meter, logger)``, one column per local calendar date, each cell
carrying that day's Interval Reading count against what the meter's own capture
period says it should be.

It is deliberately **not** in ``load_profile.py``. That module is a paged
single-device row reader; this is a multi-device aggregate over a different
resource, with its own prefix and tag — the neighbour its docstring already
anticipated.

**A complete day is ``86400 // interval_sec``, read off the stored rows.** Never
the constant 96: SPEC §3.5 forbids assuming a 900 s capture period, and names
96 = 86400÷900 as that same assumption in disguise. A Prometer 100's Logger 2
runs at 300 s, so a complete day there is 288.

**Completeness is a per-logger property.** That same Prometer 100 runs Logger 1
at 900 s and Logger 2 at 300 s on one physical meter at the same time, so
grouping by device alone would find two distinct periods on *every* day and
report a period change forever. Grouping per logger makes "the period changed"
mean what it should: one logger's cadence changed mid-day.

**The days are the operator's local days.** ``utc_offset_minutes`` is the number
of minutes to **add to UTC** to get the caller's local time — ICT is ``+420``,
and the browser sends ``-new Date().getTimezoneOffset()``. Every timestamp this
product shows is rendered in local time, so a UTC-bucketed grid would attribute
every reading between local 00:00 and 07:00 to the previous column, and a real
gap would appear on the wrong date — on the one page whose whole job is telling
you which date is missing data. The default of ``0`` keeps a bare ``curl``
deterministic.

**The range is a pair of inclusive local dates**, not the half-open instants
``/api/load-profile`` takes. Half-open bounds exist to settle whether the last
millisecond of a day is in or out; a date axis is discrete, so there is nothing
to round, and "the last column you asked for isn't there" would be a surprise
with no upside. It is bounded at **31 days**: 90 date columns is not a grid a
person reads, a calendar month is the unit completeness is checked in, and Load
Profile is where you go for the detail behind a suspicious cell.

**Nothing is materialised.** The counts are computed live from
``load_profile_readings`` on every request. A page whose only job is to say
whether the data is complete must not read that answer from a copy that can
drift — which is what v1's ``records_96`` was, a table named after the very
constant this endpoint refuses to hardcode.

**Access is any authenticated role**, matching ``load_profile.py``: changing a
device is admin-only, reading a device's data is not.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arichds.api.deps import SessionDep, get_current_user, require_feature
from arichds.api.envelope import ApiResponse
from arichds.db.models import Device, LoadProfileReading

router = APIRouter(
    prefix="/api/records",
    tags=["records"],
    dependencies=[Depends(get_current_user), Depends(require_feature("records"))],
)

#: The most local days one request may span, inclusive of both ends.
MAX_DAYS = 31

#: Seconds in a local day. The assumed 24-hour day is stated here rather than
#: buried in the division: the deployment zone has no DST, so no local day in
#: service is 23 or 25 hours long.
SECONDS_PER_DAY = 86400


def _expected_per_day(interval_sec: int) -> int:
    """How many Interval Readings a whole day at *interval_sec* holds.

    The one place this division is written. 96 at 900 s, **288 at 300 s** — and
    a literal 96 anywhere in this module would be the assumption SPEC §3.5
    forbids.

    Undefended against a non-positive period on purpose: a driver may not write
    one. ``smw110.py``'s ``_entry_window`` refuses ``capture_period_sec <= 0``
    and the read returns no rows at all, so the value cannot reach the table. A
    later driver that broke that contract would surface here as a 500 rather
    than as a silently wrong expectation, which is the right way round.
    """
    return SECONDS_PER_DAY // interval_sec


class RecordsCell(BaseModel):
    """One meter-logger's completeness on one local day.

    Attributes:
        date: The local calendar day.
        count: Interval Readings stored for that logger on that day.
        expected: How many a whole day holds at *interval_sec*.
        interval_sec: The capture period the count is judged against.
        status: ``complete`` / ``short`` / ``missing`` / ``period_changed``.
    """

    date: date
    count: int
    expected: int | None
    interval_sec: int | None
    status: Literal["complete", "short", "missing", "period_changed"]


class RecordsRow(BaseModel):
    """One meter-logger's whole line of the grid.

    Attributes:
        cells: One per entry in :attr:`RecordsGrid.dates`, same order and
            length — the grid is dense, never a sparse map.
    """

    device_id: int
    device_name: str
    site_name: str
    logger_id: int | None
    cells: list[RecordsCell]


class RecordsGrid(BaseModel):
    """The whole grid: the date axis, and a row per meter-logger.

    Attributes:
        dates: Every date in ``[start_date, end_date]``, ascending.
        rows: Ordered by meter name, then logger.
    """

    dates: list[date]
    rows: list[RecordsRow]


def _local_midnight_utc(day: date, utc_offset_minutes: int) -> datetime:
    """The UTC instant at which *day* begins in the caller's zone."""
    return datetime.combine(day, time.min, UTC) - timedelta(minutes=utc_offset_minutes)


def _counts_by_day(
    session: Session,
    start_date: date,
    end_date: date,
    utc_offset_minutes: int,
) -> dict[tuple[int, int], dict[str, dict[int, int]]]:
    """Count stored rows per ``(device, logger, local day, capture period)``.

    One grouped query, folded into
    ``{(device_id, logger_id): {local day: {interval_sec: rows}}}`` so the
    modal-period pick and the state decision stay readable Python.

    **It does not ride the ``(device_id, read_at)`` index, and the date range
    does not bound the work.** There is no ``device_id`` equality predicate and
    ``read_at`` is not that index's leading column, so SQLite cannot seek it.
    Measured on the real schema at M5c volume (30 meters × 90 days × 96 =
    259,200 rows), ``EXPLAIN QUERY PLAN`` returns::

        SCAN load_profile_readings USING INDEX sqlite_autoindex_load_profile_readings_1
        USE TEMP B-TREE FOR GROUP BY

    — a full scan of the unique constraint's implicit index, plus a temp B-tree
    for the grouping, whatever range was asked for. (With ``ANALYZE`` statistics
    present SQLite switches to a skip-scan that does bound ``read_at`` per
    ``(device_id, logger_id)`` prefix, but nothing in this product runs
    ``ANALYZE``, so the scan above is what ships.)

    That is affordable and is why no index was added: the same measurement times
    a 31-day request at **~70 ms** and a one-day request at ~31 ms, on a page
    loaded on demand by one operator. An index covering this query would put
    write cost on the acquisition hot path — every stored Interval Reading — to
    save 70 ms on a page nobody loads in a loop.

    ``func.date(col, '+N minutes')`` is **SQLite's** date function and its
    modifier syntax. That is deliberate, not an oversight: this product ships
    exactly one database, SQLite, so there is nothing to be portable to.
    """
    local_day = func.date(LoadProfileReading.read_at, f"{utc_offset_minutes:+d} minutes")

    rows = session.execute(
        select(
            LoadProfileReading.device_id,
            LoadProfileReading.logger_id,
            local_day.label("local_day"),
            LoadProfileReading.interval_sec,
            func.count().label("stored"),
        )
        .where(
            LoadProfileReading.read_at >= _local_midnight_utc(start_date, utc_offset_minutes),
            LoadProfileReading.read_at < _local_midnight_utc(end_date + timedelta(days=1), utc_offset_minutes),
        )
        .group_by(
            LoadProfileReading.device_id,
            LoadProfileReading.logger_id,
            local_day,
            LoadProfileReading.interval_sec,
        )
    ).all()

    counted: dict[tuple[int, int], dict[str, dict[int, int]]] = {}
    for device_id, logger_id, day, interval_sec, stored in rows:
        counted.setdefault((device_id, logger_id), {}).setdefault(day, {})[interval_sec] = stored
    return counted


def _cell(day: date, periods: dict[int, int]) -> RecordsCell:
    """Judge one day's rows, given ``{interval_sec: rows}`` for that day."""
    if not periods:
        # Not "short by everything": with no rows there is no capture period to
        # compute an expectation from, so `expected` is null rather than a
        # number the endpoint would have had to invent.
        return RecordsCell(date=day, count=0, expected=None, interval_sec=None, status="missing")

    # The modal period — the one on the most rows that day. The tie-break is
    # written out rather than left to whatever order the groups came back in:
    # on equal counts the **smaller** period wins, so the same stored rows
    # always produce the same cell.
    interval_sec = max(periods, key=lambda period: (periods[period], -period))
    expected = _expected_per_day(interval_sec)
    count = sum(periods.values())

    if len(periods) > 1:
        # Wins over `complete` and `short` unconditionally (SPEC §3.5): the data
        # is not missing, it is at a different cadence for part of the day, and
        # reporting a shortfall against either period would accuse the
        # acquisition path of losing rows it never lost. `count` is every row
        # that day, across every period.
        return RecordsCell(date=day, count=count, expected=expected, interval_sec=interval_sec, status="period_changed")

    # `>=` rather than `==`: a surplus cannot arise while every row sits on the
    # period grid — `(device_id, logger_id, read_at)` is unique — and a day is
    # certainly not *short* when it has more than enough.
    return RecordsCell(
        date=day,
        count=count,
        expected=expected,
        interval_sec=interval_sec,
        status="complete" if count >= expected else "short",
    )


@router.get("")
def read_records(
    session: SessionDep,
    start_date: Annotated[date, Query(description="First local calendar day, inclusive")],
    end_date: Annotated[date, Query(description="Last local calendar day, inclusive")],
    utc_offset_minutes: Annotated[
        int,
        Query(ge=-840, le=840, description="Minutes to ADD to UTC to get the caller's local time; ICT is 420"),
    ] = 0,
) -> ApiResponse[RecordsGrid]:
    """Return the completeness grid for a bounded range of local dates.

    Any authenticated role.
    """
    if end_date < start_date:
        # Raised here rather than declared on the Query: a validator sees one
        # parameter and cannot compare two.
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

    dates = [start_date + timedelta(days=offset) for offset in range(span)]
    counted = _counts_by_day(session, start_date, end_date, utc_offset_minutes)
    devices = session.execute(select(Device.id, Device.name, Device.site_name).order_by(Device.name)).all()

    rows: list[RecordsRow] = []
    for device_id, name, site_name in devices:
        # `None` when the meter recorded nothing in the whole range: there is no
        # logger to name, and dropping the row instead would hide the silent
        # meter on the one page that exists to find it. Sorted, so a device's
        # loggers come back 1, 2, … and the `None` row (which is the device's
        # only row when it appears) is unambiguous.
        loggers: list[int | None] = sorted(logger for device, logger in counted if device == device_id)
        for logger_id in loggers or [None]:
            by_day = counted.get((device_id, logger_id), {})
            rows.append(
                RecordsRow(
                    device_id=device_id,
                    device_name=name,
                    site_name=site_name,
                    logger_id=logger_id,
                    cells=[_cell(day, by_day.get(day.isoformat(), {})) for day in dates],
                )
            )

    return ApiResponse.ok(RecordsGrid(dates=dates, rows=rows))
