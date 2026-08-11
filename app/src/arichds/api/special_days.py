"""Special Days — the read-only, read-through view of a meter's own COSEM
class-11 table (M7-1, issue #28; CONTEXT.md).

**Stores nothing.** Every call re-reads the meter. Populating the Holiday
calendar from this same data is a **separate**, explicit action on the
Holidays page (``POST /api/holidays/import-from-meter``) — this router only
shows what the meter currently holds.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from arichds.acquisition.special_days import read_special_days
from arichds.api.deps import SessionDep, get_current_user, require_feature
from arichds.api.envelope import ApiResponse
from arichds.db.models import Device

router = APIRouter(
    prefix="/api/special-days",
    tags=["special-days"],
    dependencies=[Depends(get_current_user), Depends(require_feature("special_days"))],
)


class SpecialDayOut(BaseModel):
    """One entry off the meter's own Special Days Table, as the page
    renders it — index / date / day ID, with the annual/public split
    already resolved by the driver (CONTEXT.md — Holiday)."""

    index: int
    day_id: int
    kind: Literal["annual", "public"]
    year: int | None
    month: int
    day: int


class SpecialDaysReadOut(BaseModel):
    """What ``GET /api/special-days`` returned.

    Attributes:
        entries: The meter's own table — empty both when it genuinely holds
            nothing and when :attr:`error` is set (never a stale value).
        error: An operator-facing sentence, or ``None`` on success — a
            live-read failure is a verdict carried on the payload, never an
            HTTP error status (mirrors Test Connection / Read Now).
    """

    entries: list[SpecialDayOut]
    error: str | None


def _require_device_exists(session: SessionDep, device_id: int) -> None:
    """Refuse with 404 unless *device_id* names a device — same rule
    ``api/records.py``/``api/billing.py``/``api/energy.py`` give."""
    if session.get(Device, device_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such device.")


@router.get("")
def read_device_special_days(
    device_id: Annotated[int, Query(ge=1, description="Which device's Special Days Table to read")],
    session: SessionDep,
) -> ApiResponse[SpecialDaysReadOut]:
    """Read *device_id*'s Special Days Table now, through the Manual Read
    lock. Any authenticated role.

    Raises:
        HTTPException: 404 for an unknown device, or one whose driver has
            no Special Days Table at all (``supported=False``) — a
            structural fact about the device, not a live-read failure. A
            live-read failure (connection dropped, endpoint busy) is
            **not** an HTTPException — see :class:`SpecialDaysReadOut`.
    """
    _require_device_exists(session, device_id)

    result = read_special_days(device_id)
    if not result.supported:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=result.error or "This device has no Special Days Table."
        )

    entries = [
        SpecialDayOut(
            index=entry.index, day_id=entry.day_id, kind=entry.kind, year=entry.year, month=entry.month, day=entry.day
        )
        for entry in result.entries
    ]
    return ApiResponse.ok(SpecialDaysReadOut(entries=entries, error=result.error))
