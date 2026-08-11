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
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select

from arichds.acquisition.special_days import read_special_days
from arichds.api.deps import AdminDep, SessionDep, get_current_user, require_feature
from arichds.api.envelope import ApiResponse
from arichds.db.models import Device, Holiday

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


def _to_out(row: Holiday) -> HolidayOut:
    return HolidayOut(id=row.id, kind=row.kind, name=row.name, date=row.date, month=row.month, day=row.day)


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
def create_holiday(body: HolidayIn, session: SessionDep, _admin: AdminDep) -> ApiResponse[HolidayOut]:
    """Add one Holiday. Admin-only."""
    collision = _find_colliding_holiday(session, body.kind, body.date, body.month, body.day)
    if collision is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="A holiday already exists on that day."
        )

    row = Holiday(kind=body.kind, name=body.name, date=body.date, month=body.month, day=body.day)
    session.add(row)
    session.flush()
    session.commit()
    session.refresh(row)
    return ApiResponse.ok(_to_out(row))


@router.patch("/{holiday_id}")
def update_holiday(holiday_id: int, body: HolidayIn, session: SessionDep, _admin: AdminDep) -> ApiResponse[HolidayOut]:
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
    session.commit()
    session.refresh(row)
    return ApiResponse.ok(_to_out(row))


@router.delete("/{holiday_id}")
def delete_holiday(holiday_id: int, session: SessionDep, _admin: AdminDep) -> ApiResponse[bool]:
    """Remove one Holiday. Admin-only."""
    row = session.get(Holiday, holiday_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such holiday.")
    session.delete(row)
    session.commit()
    return ApiResponse.ok(True)


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


@router.post("/import")
def import_holidays(body: HolidayDocument, session: SessionDep, _admin: AdminDep) -> ApiResponse[list[HolidayOut]]:
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
    session.flush()
    session.commit()
    for row in rows:
        session.refresh(row)
    return ApiResponse.ok([_to_out(row) for row in rows])


@router.post("/import-from-meter")
def import_holidays_from_meter(
    device_id: Annotated[int, Query(ge=1, description="Which device's Special Days Table to import")],
    session: SessionDep,
    _admin: AdminDep,
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
    session.flush()
    session.commit()
    for row in rows:
        session.refresh(row)
    return ApiResponse.ok(HolidayImportFromMeterResult(imported=[_to_out(row) for row in rows], skipped=skipped))
