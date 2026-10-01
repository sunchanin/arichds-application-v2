"""Holidays — the machine-wide calendar the Energy Summary's Holiday bucket
is judged against (M7-1, issue #28; CONTEXT.md — Holiday).

**No ``device_id``** — holidays are machine-wide, and the whole set travels
between machines as one JSON file (decision 12/14). **Import replaces the
whole set**, from either source — a merge needs a collision rule nobody has
asked for (decision 13); the confirmation naming how many rows will be lost
is the frontend's job, this endpoint just replaces.

**Duplicate handling differs by source, on purpose** (decision 15): a JSON
import with an internal collision is refused whole with 422 — our own
export cannot produce one, so a duplicate means a hand-edited file whose
intent is unknown. A meter import de-duplicates on the key, keeps the
first, and reports how many were skipped — two meter rows on one calendar
day are one holiday to us.

**29 February as ``annual`` is refused everywhere** (decision 16) — the
create form, the JSON import (structurally, by :class:`HolidayIn`'s own
validator) and the meter import (explicitly, before anything is written) —
and refusing it fails the **whole** import, since a partial import of a
replace-the-whole-set operation is a set nobody chose.

**Reading is any authenticated role; every mutation is admin-only**
(decision 19) — create, update, delete, both imports.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, select

from arichds.acquisition.special_days import read_special_days
from arichds.api.deps import AdminDep, SessionDep, get_current_user, require_feature
from arichds.api.envelope import ApiResponse
from arichds.db.models import Device, Holiday, HolidayChange

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/holidays",
    tags=["holidays"],
    dependencies=[Depends(get_current_user), Depends(require_feature("energy_summary"))],
)


def _validate_holiday_shape(kind: str, date_: dt.date | None, month: int | None, day: int | None) -> None:
    """Enforce the mutually-exclusive column pair per kind, and refuse 29
    February as ``annual`` (decision 16) — shared by every entry point that
    can create a Holiday row: the create form, JSON import, and (called
    explicitly, since a driver-sourced entry never passes through this
    Pydantic model) the meter import.

    Raises:
        ValueError: On any shape violation — turned into a 422 by whichever
            caller invoked this (a Pydantic validator for the two JSON
            paths, an explicit ``HTTPException`` for the meter path).
    """
    if kind == "annual":
        if month is None or day is None:
            raise ValueError("An annual holiday needs both `month` and `day`.")
        if date_ is not None:
            raise ValueError("An annual holiday must not carry an exact `date`.")
        if month == 2 and day == 29:
            raise ValueError(
                "29 February cannot be an annual holiday — it would match nothing in a non-leap year. "
                "Use a public holiday with an exact date instead."
            )
    else:
        if date_ is None:
            raise ValueError("A public holiday needs an exact `date`.")
        if month is not None or day is not None:
            raise ValueError("A public holiday must not carry `month`/`day`.")


class HolidayOut(BaseModel):
    """One stored Holiday row, as the Holidays page renders it."""

    id: int
    kind: Literal["annual", "public"]
    name: str
    date: dt.date | None
    month: int | None
    day: int | None


class HolidayIn(BaseModel):
    """The body ``POST``/``PATCH /api/holidays`` and each entry of a JSON
    import document take — validated at construction, so a shape violation
    is a 422 before the handler runs."""

    kind: Literal["annual", "public"]
    name: str
    date: dt.date | None = None
    month: Annotated[int | None, Field(ge=1, le=12)] = None
    day: Annotated[int | None, Field(ge=1, le=31)] = None

    @model_validator(mode="after")
    def _check_shape(self) -> HolidayIn:
        _validate_holiday_shape(self.kind, self.date, self.month, self.day)
        return self


class HolidayDocument(BaseModel):
    """The JSON export/import document shape (decision 14)."""

    version: int = 1
    holidays: list[HolidayIn]


class HolidayImportFromMeterResult(BaseModel):
    """What ``POST /api/holidays/import-from-meter`` did.

    Attributes:
        imported: The rows now stored, replacing whatever was there before.
        skipped: How many of the meter's own entries collided with another
            of the meter's entries and were dropped, keeping the first
            (decision 15) — never the rows that replaced the *previous*
            stored set, which is not a "skip" at all.
    """

    imported: list[HolidayOut]
    skipped: int


class HolidayMutationOut(BaseModel):
    """The answer to any change that may move the Energy Summary (ADR 0022,
    M14 ticket 04).

    **Drops `affected_date` and `energy_files_written_past`** (M13, issue 03):
    those existed because the daily Energy Export File was a snapshot that
    could fall behind a Holiday entered after the fact, so the API told the
    operator which files needed a manual re-save. Since ADR 0022/0023 the
    Energy Summary is a stored table recomputed over the whole window every
    scheduler cycle and the Energy file is rewritten from it every cycle too
    (ticket 04), so neither can be stale by more than one cycle — there is
    nothing left to compute or report here, and the page shows a fixed notice
    instead (`web/src/pages/Holidays.tsx`).

    Attributes:
        holiday: The row as it now stands, or ``None`` for a delete.
    """

    holiday: HolidayOut | None


def _mutation_out(row: Holiday | None) -> HolidayMutationOut:
    return HolidayMutationOut(holiday=_to_out(row) if row is not None else None)


def _to_out(row: Holiday) -> HolidayOut:
    return HolidayOut(id=row.id, kind=row.kind, name=row.name, date=row.date, month=row.month, day=row.day)


class HolidayChangeOut(BaseModel):
    """One recorded Holiday Change (ADR 0022, M14 ticket 06; CONTEXT.md —
    Holiday Change), as ``GET /api/holidays/changes`` renders it."""

    id: int
    created_at: dt.datetime
    username: str
    action: Literal["add", "edit", "delete", "import_csv", "import_meter"]
    holiday_kind: Literal["annual", "public"] | None
    holiday_name: str | None
    holiday_date: dt.date | None
    holiday_month: int | None
    holiday_day: int | None
    count: int | None

    @field_validator("created_at")
    @classmethod
    def _ensure_utc(cls, value: dt.datetime) -> dt.datetime:
        """Re-attach UTC to the naive datetime SQLite hands back.

        The house pattern (``BillingRowOut._ensure_utc``, `docs/issues/006`):
        SQLite has no timezone type, so a ``DateTime(timezone=True)`` column
        comes back naive and the drawer would otherwise print 04:10 for a
        change made at 11:10 (+07:00) — ui-audit ticket 02.
        """
        return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


class HolidayChangePage(BaseModel):
    """One page of the Holiday Change record (antd-ui: a list that can grow
    pages server-side — mirrors :class:`~arichds.api.devices.DeviceEventPage`).

    Attributes:
        items: The changes, newest first.
        total: How many changes exist in total (unpaged).
        limit: The page size that was applied.
        offset: How many rows were skipped.
    """

    items: list[HolidayChangeOut]
    total: int
    limit: int
    offset: int


def _change_to_out(row: HolidayChange) -> HolidayChangeOut:
    return HolidayChangeOut(
        id=row.id,
        created_at=row.created_at,
        username=row.username,
        action=row.action,  # type: ignore[arg-type]
        holiday_kind=row.holiday_kind,  # type: ignore[arg-type]
        holiday_name=row.holiday_name,
        holiday_date=row.holiday_date,
        holiday_month=row.holiday_month,
        holiday_day=row.holiday_day,
        count=row.count,
    )


def _day_description(holiday: Holiday) -> str:
    """The Holiday's day, however it is stored — an exact date or a
    recurring month/day (used for the one App Log line each change writes)."""
    return holiday.date.isoformat() if holiday.kind == "public" else f"{holiday.month}/{holiday.day}"


def _record_holiday_change(session: SessionDep, *, action: str, username: str, holiday: Holiday) -> None:
    """Add one Holiday Change row for a single-Holiday action — add, edit or
    delete — to *session*. The caller commits it in the **same transaction**
    as the mutation itself (ADR 0022, M14 ticket 06): a mutation the API
    refuses never reaches here, so it records nothing.
    """
    session.add(
        HolidayChange(
            username=username,
            action=action,
            holiday_kind=holiday.kind,
            holiday_name=holiday.name,
            holiday_date=holiday.date,
            holiday_month=holiday.month,
            holiday_day=holiday.day,
        )
    )


def _record_import_change(session: SessionDep, *, action: str, username: str, count: int) -> None:
    """Add **one** Holiday Change row for a whole-set-replace import — never
    one row per imported Holiday. Same transaction as the import itself."""
    session.add(HolidayChange(username=username, action=action, count=count))


def _log_holiday_change(*, action: str, username: str, name: str, day: str) -> None:
    """The one App Log line ADR 0022 asks every single-Holiday change to
    leave, naming the action, the user and the day."""
    logger.info("Holiday %s: %r (%s) by %s", action, name, day, username)


def _log_import_change(*, action: str, username: str, count: int) -> None:
    """The one App Log line ADR 0022 asks every import to leave, naming the
    action, the user and how many Holidays it brought in."""
    logger.info("Holiday %s: %d holiday(s) by %s", action, count, username)


def _find_colliding_holiday(
    session: SessionDep,
    kind: str,
    date_: dt.date | None,
    month: int | None,
    day: int | None,
    *,
    exclude_id: int | None = None,
) -> Holiday | None:
    """The row (if any) that already occupies *kind*'s unique key —
    ``date`` for ``public``, ``(month, day)`` for ``annual`` — checked
    proactively so a collision answers 422, never a 500 from the database's
    own partial unique index."""
    if kind == "public":
        query = select(Holiday).where(Holiday.kind == "public", Holiday.date == date_)
    else:
        query = select(Holiday).where(Holiday.kind == "annual", Holiday.month == month, Holiday.day == day)
    if exclude_id is not None:
        query = query.where(Holiday.id != exclude_id)
    return session.scalar(query)


@router.get("")
def list_holidays(session: SessionDep) -> ApiResponse[list[HolidayOut]]:
    """Return every stored Holiday, annual first then public, each ordered
    by calendar position. Any authenticated role."""
    rows = session.scalars(select(Holiday).order_by(Holiday.kind, Holiday.month, Holiday.day, Holiday.date)).all()
    return ApiResponse.ok([_to_out(row) for row in rows])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_holiday(body: HolidayIn, session: SessionDep, admin: AdminDep) -> ApiResponse[HolidayMutationOut]:
    """Add one Holiday. Admin-only."""
    collision = _find_colliding_holiday(session, body.kind, body.date, body.month, body.day)
    if collision is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="A holiday already exists on that day."
        )

    row = Holiday(kind=body.kind, name=body.name, date=body.date, month=body.month, day=body.day)
    session.add(row)
    session.flush()
    _record_holiday_change(session, action="add", username=admin.username, holiday=row)
    name, day = row.name, _day_description(row)
    session.commit()
    session.refresh(row)
    _log_holiday_change(action="add", username=admin.username, name=name, day=day)
    return ApiResponse.ok(_mutation_out(row))


@router.patch("/{holiday_id}")
def update_holiday(
    holiday_id: int, body: HolidayIn, session: SessionDep, admin: AdminDep
) -> ApiResponse[HolidayMutationOut]:
    """Replace one Holiday's fields in place. Admin-only."""
    row = session.get(Holiday, holiday_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such holiday.")

    collision = _find_colliding_holiday(session, body.kind, body.date, body.month, body.day, exclude_id=holiday_id)
    if collision is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Another holiday already exists on that day."
        )

    row.kind = body.kind
    row.name = body.name
    row.date = body.date
    row.month = body.month
    row.day = body.day
    _record_holiday_change(session, action="edit", username=admin.username, holiday=row)
    name, day = row.name, _day_description(row)
    session.commit()
    session.refresh(row)
    _log_holiday_change(action="edit", username=admin.username, name=name, day=day)
    return ApiResponse.ok(_mutation_out(row))


@router.delete("/{holiday_id}")
def delete_holiday(holiday_id: int, session: SessionDep, admin: AdminDep) -> ApiResponse[HolidayMutationOut]:
    """Remove one Holiday. Admin-only."""
    row = session.get(Holiday, holiday_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such holiday.")
    name, day = row.name, _day_description(row)
    _record_holiday_change(session, action="delete", username=admin.username, holiday=row)
    session.delete(row)
    session.commit()
    _log_holiday_change(action="delete", username=admin.username, name=name, day=day)
    return ApiResponse.ok(_mutation_out(None))


@router.get("/export")
def export_holidays(session: SessionDep) -> ApiResponse[HolidayDocument]:
    """Return the whole calendar as the JSON document (decision 14). Any
    authenticated role — the frontend saves this as a Blob download."""
    rows = session.scalars(select(Holiday).order_by(Holiday.kind, Holiday.month, Holiday.day, Holiday.date)).all()
    return ApiResponse.ok(
        HolidayDocument(
            version=1,
            holidays=[
                HolidayIn(kind=row.kind, name=row.name, date=row.date, month=row.month, day=row.day) for row in rows
            ],
        )
    )


@router.get("/changes")
def list_holiday_changes(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200, description="Page size")] = 50,
    offset: Annotated[int, Query(ge=0, description="Rows to skip")] = 0,
) -> ApiResponse[HolidayChangePage]:
    """Return one page of the Holiday Change record, newest first (ADR 0022,
    M14 ticket 06; CONTEXT.md — Holiday Change). Any authenticated role —
    same licence gate as the rest of this router, no extra admin requirement.

    Paginated server-side like ``GET /api/devices/{id}/events`` — the record
    grows by one row per mutation and is kept for
    :data:`~arichds.constants.RETENTION_DAYS`, so it is exactly the kind of
    list that must not be dumped whole into a client-side table.

    The ``id`` tiebreak in the ordering matches
    :func:`arichds.api.devices.list_device_events`: SQLite's
    ``CURRENT_TIMESTAMP`` has one-second resolution, so two changes made
    within the same second — two quick edits, or an edit that collides right
    after a create — would otherwise sort arbitrarily between pages.
    """
    total = session.scalar(select(func.count()).select_from(HolidayChange)) or 0
    rows = session.scalars(
        select(HolidayChange)
        .order_by(HolidayChange.created_at.desc(), HolidayChange.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return ApiResponse.ok(
        HolidayChangePage(items=[_change_to_out(row) for row in rows], total=total, limit=limit, offset=offset)
    )


@router.post("/import")
def import_holidays(body: HolidayDocument, session: SessionDep, admin: AdminDep) -> ApiResponse[list[HolidayOut]]:
    """Replace the whole calendar with *body* (decision 13). Admin-only.

    Each entry's own shape (kind/date/month/day, 29-Feb refusal) was already
    validated by :class:`HolidayIn` while parsing the request body — this
    handler only checks for a duplicate **key** across entries, which is a
    document-wide property Pydantic's per-item validation cannot see. A
    duplicate refuses the whole import (decision 15) — our own export
    cannot produce one, so a duplicate means a hand-edited file.
    """
    seen_public: set[dt.date] = set()
    seen_annual: set[tuple[int, int]] = set()
    for entry in body.holidays:
        if entry.kind == "public":
            if entry.date in seen_public:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Duplicate public holiday on {entry.date} — refusing the whole import.",
                )
            seen_public.add(entry.date)  # type: ignore[arg-type]
        else:
            key = (entry.month, entry.day)
            if key in seen_annual:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Duplicate annual holiday on {entry.month}/{entry.day} — refusing the whole import.",
                )
            seen_annual.add(key)  # type: ignore[arg-type]

    session.execute(delete(Holiday))
    rows = [
        Holiday(kind=entry.kind, name=entry.name, date=entry.date, month=entry.month, day=entry.day)
        for entry in body.holidays
    ]
    session.add_all(rows)
    _record_import_change(session, action="import_csv", username=admin.username, count=len(rows))
    session.flush()
    session.commit()
    for row in rows:
        session.refresh(row)
    _log_import_change(action="import_csv", username=admin.username, count=len(rows))
    return ApiResponse.ok([_to_out(row) for row in rows])


@router.post("/import-from-meter")
def import_holidays_from_meter(
    device_id: Annotated[int, Query(ge=1, description="Which device's Special Days Table to import")],
    session: SessionDep,
    admin: AdminDep,
) -> ApiResponse[HolidayImportFromMeterResult]:
    """Read *device_id*'s Special Days Table and replace the whole calendar
    with it (decision 18). Admin-only.

    Populating the TOU calendar is this endpoint's product purpose — the
    read-only Special Days page (``api/special_days.py``) shows the same
    table without ever writing it anywhere.
    """
    if session.get(Device, device_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such device.")

    result = read_special_days(device_id)
    if not result.supported:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.error or "No such device.")
    if result.error is not None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=result.error)

    for entry in result.entries:
        if entry.kind == "annual" and entry.month == 2 and entry.day == 29:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "The meter's Special Days Table has a 29 February annual entry, which cannot be stored — "
                    "refusing the whole import."
                ),
            )

    seen_public: set[dt.date] = set()
    seen_annual: set[tuple[int, int]] = set()
    skipped = 0
    rows: list[Holiday] = []
    for entry in result.entries:
        name = f"Meter day ID {entry.day_id}"
        if entry.kind == "public":
            entry_date = dt.date(entry.year, entry.month, entry.day)  # type: ignore[arg-type]
            if entry_date in seen_public:
                skipped += 1
                continue
            seen_public.add(entry_date)
            rows.append(Holiday(kind="public", name=name, date=entry_date, month=None, day=None))
        else:
            key = (entry.month, entry.day)
            if key in seen_annual:
                skipped += 1
                continue
            seen_annual.add(key)
            rows.append(Holiday(kind="annual", name=name, date=None, month=entry.month, day=entry.day))

    session.execute(delete(Holiday))
    session.add_all(rows)
    _record_import_change(session, action="import_meter", username=admin.username, count=len(rows))
    session.flush()
    session.commit()
    for row in rows:
        session.refresh(row)
    _log_import_change(action="import_meter", username=admin.username, count=len(rows))
    return ApiResponse.ok(HolidayImportFromMeterResult(imported=[_to_out(row) for row in rows], skipped=skipped))
