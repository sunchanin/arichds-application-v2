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

**Logger 1 and Logger 2 merge into one row here — read side only** (owner
ruling, 2026-08-11, reversing the "never merged" decision this module shipped
with). v1's own rule is reproduced exactly
(``cewe-worker/src/load_profile/repository.py:275-291``): Logger 1 is the
spine (``WHERE logger_id = 1``), Logger 2 is ``LEFT JOIN``ed on the same
``device_id`` and an **exact** ``read_at`` match, and every measurement column
becomes ``COALESCE(logger1_col, logger2_col)`` — Logger 1 wins.

**Storage is untouched.** Rows still land one per
``(device_id, logger_id, read_at)`` in ``load_profile_readings`` (ADR 0008) —
this module only changes how the list endpoint *projects* what is already
there, never what a read writes. Two consequences follow directly from
``docs/meter-notes/load-profile-capture-objects.md:35-53``:

1. On **Prometer 100** Logger 2 captures every 300 s against Logger 1's 900 s,
   so only the one-in-three Logger 2 rows whose timestamp lands exactly on a
   Logger 1 boundary contribute anything here — the other two thirds stay in
   the database and still reach CSV export.
2. On **Premier 550** Logger 1's ``1.0.1.29.0.255`` (interval) and Logger 2's
   ``1.0.1.8.0.255`` (cumulative) map to the same column — same collision at
   C=2, 3 and 4 — so ``COALESCE`` makes Logger 1 win deterministically and
   Logger 2's value is not displayed, though it is still on disk.

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

from arichds.acquisition.load_profile import read_and_store_load_profile
from arichds.api.deps import SessionDep, get_current_user, require_feature
from arichds.api.envelope import ApiResponse
from arichds.db.app_settings import EXPORT_OUTPUT_DIR_DEFAULT, EXPORT_OUTPUT_DIR_KEY, get_setting
from arichds.db.load_profile_query import merged_rows_select
from arichds.db.models import Device, LoadProfileReading
from arichds.export.csv_export import export_device

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
    on the page reads them. ``logger_id`` is absent too, as of the read-side
    Logger 1/2 merge (owner ruling, 2026-08-11, module docstring): a row here
    is no longer one logger's own data, so labelling it with either logger's
    id would be misleading.

    Attributes:
        read_at: When the meter recorded the interval — **UTC, timezone-aware**.
            Always a Logger 1 timestamp — Logger 1 is the merge's spine.
    """

    model_config = ConfigDict(from_attributes=True)

    read_at: datetime

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
    """Return one page of a device's merged Interval Readings, newest first.

    Any authenticated role. Logger 1 is the spine and the sole driver of
    paging and ``total`` — see the module docstring for the merge rule and its
    two known consequences. The ordering is ``read_at DESC``, and it is
    *total*: for a fixed ``logger_id = 1``, ``(device_id, read_at)`` is unique
    (ADR 0008's ``(device_id, logger_id, read_at)`` key), so no two rows tie
    and paging cannot repeat or skip a row.
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

    # Built once and used by both queries on purpose: ``total`` is only
    # meaningful as the unpaged count of *the same* filter, and two hand-copied
    # WHERE clauses are free to drift into a page whose rows and whose total
    # disagree. ``merged_rows_select`` already carries the ``logger_id == 1``
    # spine filter (D-2, issue #30) — Logger 1 is the spine this whole merge
    # is keyed on (module docstring), so a device with only a Logger 2 (none
    # exist today) would correctly show nothing here.
    base = merged_rows_select(device_id).where(
        LoadProfileReading.read_at >= lower,
        LoadProfileReading.read_at < upper,
    )
    rows = session.execute(base.order_by(LoadProfileReading.read_at.desc()).limit(limit).offset(offset)).all()
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0

    return ApiResponse.ok(
        LoadProfilePage(
            items=[LoadProfileRowOut.model_validate(row, from_attributes=True) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )
    )


class LoadProfileExportResult(BaseModel):
    """What ``POST /api/load-profile/export`` did.

    Attributes:
        rows_written: How many rows were appended this call.
        path: The resolved target CSV file path, or ``None`` when nothing
            was written (an undiscovered Meter Serial, an unbuildable
            driver, no pending rows, or a write failure — see
            :func:`arichds.export.csv_export.export_device`).
    """

    rows_written: int
    path: str | None


@router.post("/export")
def export_load_profile_now(
    session: SessionDep, device_id: Annotated[int, Query(ge=1)]
) -> ApiResponse[LoadProfileExportResult]:
    """ "Save CSV now" — export *device_id*'s pending Interval Readings at once.

    Any authenticated role, mirroring ``list_interval_readings`` above
    (D-17) — reading and exporting stored device data are both open to every
    role, the same as the rest of this router.

    **Ignores ``export_auto_save_enabled``** (D-11): an operator pressing
    this button has already expressed intent, and making them flip a
    *background* switch first would be a trap. It runs the same function
    under the same per-device lock and advances the same watermark as the
    scheduler job — two writers to one file that did not share a watermark
    would duplicate rows.

    **``export_output_dir`` is still required** — unlike the scheduler job,
    which no-ops silently when it is empty (v1 parity), this is a person
    pressing a button, so an unconfigured destination is a 422 with an
    actionable sentence rather than a silent "0 rows written" 200.
    """
    _require_device_exists(session, device_id)
    output_dir = get_setting(session, EXPORT_OUTPUT_DIR_KEY, EXPORT_OUTPUT_DIR_DEFAULT).strip()
    if not output_dir:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="export_output_dir is not configured — nothing to export to. Set it on the Export Format page.",
        )

    result = export_device(device_id, require_auto_save=False)
    return ApiResponse.ok(
        LoadProfileExportResult(rows_written=result.rows_written, path=str(result.path) if result.path else None)
    )


class LoadProfileReadOut(BaseModel):
    """What ``POST /api/load-profile/read`` did (issue #44).

    Shaped on ``api/energy.py``'s ``EnergyRegisterReadOut``: a live-read
    failure is a verdict carried on ``error``, never an HTTP error status.

    Attributes:
        stored: How many Interval Readings this call wrote — mirrors
            ``LoadProfileReadResult.stored``.
        through: The highest ``read_at`` now stored for this device, or
            ``None`` if it still has no rows.
        history_remains: Whether another press would make progress — see
            :attr:`~arichds.acquisition.load_profile.LoadProfileReadResult.history_remains`.
            The Load Profile page's button loops on this field (D11).
        error: An operator-facing sentence, or ``None`` on success.
    """

    stored: int
    through: datetime | None
    history_remains: bool
    error: str | None

    @field_validator("through")
    @classmethod
    def _ensure_utc_or_none(cls, value: datetime | None) -> datetime | None:
        """Same re-attachment as :meth:`LoadProfileRowOut._ensure_utc`, but
        ``None``-safe: a device with no stored rows yet has no ``through``."""
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@router.post("/read")
def trigger_load_profile_read(
    device_id: Annotated[int, Query(ge=1)],
    session: SessionDep,
) -> ApiResponse[LoadProfileReadOut]:
    """Read the meter's load profile now, through the Manual Read lock
    (issue #44, D7) — button-triggered, mirroring ``api/energy.py``'s
    ``trigger_energy_register_read``.

    Any authenticated role — matches every other Read now surface in this
    product and the rest of this router.

    **No liveness probe, and this never touches device status** (D7): Read
    now on the Devices page probes first because liveness is the one job
    that writes device status (ADR 0004); a page-scoped read that probed
    would buy a second DLMS association per press for a status column this
    page does not show. Mirrors ``api/devices.py``'s own
    ``_read_load_profile_job``, minus the liveness probe in front of it.

    **Runs only this job** — never billing (D1/D7): a device with no stored
    closed period already gets billing from inside the ordinary Load Profile
    cycle's Billing Change Check (#43, ADR 0018).

    Raises:
        HTTPException: 404 for an unknown device, or one whose driver has no
            load profile at all (``supported=False``) — a structural fact
            about the device, not a live-read failure. A live-read failure
            (connection dropped, endpoint busy, budget exhausted) is **not**
            an HTTPException — it comes back on the payload's ``error``
            field, same as Test Connection.
    """
    _require_device_exists(session, device_id)

    result = read_and_store_load_profile(device_id)
    if not result.supported:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=result.error or "This device has no load profile."
        )
    return ApiResponse.ok(
        LoadProfileReadOut(
            stored=result.stored,
            through=result.through,
            history_remains=result.history_remains,
            error=result.error,
        )
    )
