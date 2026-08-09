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

import os
import stat
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arichds.api.deps import (
    AdminDep,
    FeatureDisabledError,
    LicenseServiceDep,
    SessionDep,
    get_current_user,
    require_feature,
)
from arichds.api.envelope import ApiResponse
from arichds.capture.paths import validate_capture_dir_setting
from arichds.capture.service import capture_target_paths, write_pdf_capture, write_xlsx_capture
from arichds.config import get_settings
from arichds.constants import O_BINARY, O_NOFOLLOW
from arichds.db.app_settings import CAPTURE_DIR_DEFAULT, CAPTURE_DIR_KEY, get_setting, set_setting
from arichds.db.models import BillingReading, Device
from arichds.licensing.features import feature_enabled

router = APIRouter(
    prefix="/api/billing",
    tags=["billing"],
    dependencies=[Depends(get_current_user), Depends(require_feature("billing"))],
)


#: Every measurement column's field name, grouped like ``db/models.py`` and
#: ``drivers/base.py`` spell them out — the whole sixty (D19, M4c issue #24):
#: the response now carries every measurement, not just the eight totals, so
#: the Billing page's grouped-header table (D20) has the tariff columns to
#: show. Spelled out rather than generated, matching the same field set as
#: ``BillingReading.as_columns()`` and ``capture/_render_shared.py``.
_RATE_SUFFIXES = ("total", "rate_a", "rate_b", "rate_c", "rate_d")


def _rated(prefix: str) -> tuple[str, ...]:
    return tuple(f"{prefix}_{suffix}" for suffix in _RATE_SUFFIXES)


#: The ten Demand Time field names — datetimes, never scaled (D11) — kept
#: separate from the other measurement fields because they need the same
#: UTC re-attachment ``bill_date``/``read_at`` get, not the float typing.
_DEMAND_TIME_FIELDS: tuple[str, ...] = (
    *_rated("max_demand_import_active_time"),
    *_rated("max_demand_import_reactive_time"),
)


class BillingRowOut(BaseModel):
    """One Billing Reading as the Billing page renders it — either tab.

    Attributes:
        id: The row's own id — needed by the History tab's download-capture
            link (M6b, issue #22: ``GET /api/billing/captures/{id}``), which
            has no other way to name a specific closed period.
        device_id: Which device this period belongs to.
        device_name: Joined from ``devices.name`` — the page lists rows across
            devices, so the id alone is not enough to render a row.
        bill_date: The meter's own Clock cell for this period — UTC (CONTEXT.md
            — Bill Date).
        read_at: When *we* read it — UTC.
        meter_serial: Snapshot per row, or None.

    **Every one of the sixty measurement columns is a field here** (D19) —
    grown from the original eight totals so the grouped-header Billing page
    (D20) can show every tariff. Ten of them (the Demand Time columns) are
    ``datetime | None``, not ``float | None`` — see :data:`_DEMAND_TIME_FIELDS`.
    """

    id: int
    device_id: int
    device_name: str
    bill_date: datetime
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

    max_demand_import_active_kw_total: float | None
    max_demand_import_active_kw_rate_a: float | None
    max_demand_import_active_kw_rate_b: float | None
    max_demand_import_active_kw_rate_c: float | None
    max_demand_import_active_kw_rate_d: float | None

    max_demand_export_active_kw_total: float | None
    max_demand_export_active_kw_rate_a: float | None
    max_demand_export_active_kw_rate_b: float | None
    max_demand_export_active_kw_rate_c: float | None
    max_demand_export_active_kw_rate_d: float | None

    max_demand_import_reactive_kvar_total: float | None
    max_demand_import_reactive_kvar_rate_a: float | None
    max_demand_import_reactive_kvar_rate_b: float | None
    max_demand_import_reactive_kvar_rate_c: float | None
    max_demand_import_reactive_kvar_rate_d: float | None

    max_demand_export_reactive_kvar_total: float | None
    max_demand_export_reactive_kvar_rate_a: float | None
    max_demand_export_reactive_kvar_rate_b: float | None
    max_demand_export_reactive_kvar_rate_c: float | None
    max_demand_export_reactive_kvar_rate_d: float | None

    # ── M4c, issue #24 — the twenty columns v1's screen has always shown ──
    max_demand_import_active_time_total: datetime | None
    max_demand_import_active_time_rate_a: datetime | None
    max_demand_import_active_time_rate_b: datetime | None
    max_demand_import_active_time_rate_c: datetime | None
    max_demand_import_active_time_rate_d: datetime | None

    max_demand_import_reactive_time_total: datetime | None
    max_demand_import_reactive_time_rate_a: datetime | None
    max_demand_import_reactive_time_rate_b: datetime | None
    max_demand_import_reactive_time_rate_c: datetime | None
    max_demand_import_reactive_time_rate_d: datetime | None

    cumul_demand_import_active_kw_total: float | None
    cumul_demand_import_active_kw_rate_a: float | None
    cumul_demand_import_active_kw_rate_b: float | None
    cumul_demand_import_active_kw_rate_c: float | None
    cumul_demand_import_active_kw_rate_d: float | None

    cumul_demand_import_reactive_kvar_total: float | None
    cumul_demand_import_reactive_kvar_rate_a: float | None
    cumul_demand_import_reactive_kvar_rate_b: float | None
    cumul_demand_import_reactive_kvar_rate_c: float | None
    cumul_demand_import_reactive_kvar_rate_d: float | None

    @field_validator("bill_date", "read_at")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        """Re-attach UTC to the naive datetime SQLite hands back.

        Same rule as ``LoadProfileRowOut._ensure_utc`` — SQLite has no
        timezone type, so a column declared ``DateTime(timezone=True)`` comes
        back naive and would otherwise be read by the browser as local time.
        """
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @field_validator(*_DEMAND_TIME_FIELDS)
    @classmethod
    def _ensure_utc_or_none(cls, value: datetime | None) -> datetime | None:
        """The same re-attachment as :meth:`_ensure_utc`, but ``None``-safe
        (D19) — unlike ``bill_date``/``read_at``, every one of these ten
        fields is optional: most billing rows have never captured a max
        demand at all, let alone the instant it happened.
        """
        if value is None:
            return None
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

    items = [_to_row_out(reading, device_name) for reading, device_name in rows]

    return ApiResponse.ok(BillingPage(items=items, total=total, limit=limit, offset=offset))


#: Every ``billing_readings`` column that is not part of a row's identity —
#: the sixty measurement columns (D19), read off the ORM model itself so a
#: column migration 0009 (or a future one) adds is picked up here without
#: anyone hand-updating a sixty-line kwargs list (mirrors
#: ``capture/_render_shared.py``'s own column-derived approach).
_IDENTITY_COLUMNS = frozenset(
    {"id", "device_id", "bill_date", "read_at", "record_status", "source", "meter_serial", "created_at", "updated_at"}
)
_MEASUREMENT_COLUMN_NAMES: tuple[str, ...] = tuple(
    column.name for column in BillingReading.__table__.columns if column.name not in _IDENTITY_COLUMNS
)


def _to_row_out(reading: BillingReading, device_name: str) -> BillingRowOut:
    """Build the response row for one ``BillingReading`` (D19)."""
    return BillingRowOut(
        id=reading.id,
        device_id=reading.device_id,
        device_name=device_name,
        bill_date=reading.bill_date,
        read_at=reading.read_at,
        meter_serial=reading.meter_serial,
        **{name: getattr(reading, name) for name in _MEASUREMENT_COLUMN_NAMES},
    )


class BillingSettingsOut(BaseModel):
    """The Billing settings, as the Billing page's admin form renders them.

    Attributes:
        capture_dir: The current value — ``""`` means "not configured"
            (decision 16, issue #22).
        capture_count: How many **closed** billing rows exist right now — the
            rows a capture could exist for. Drives the frontend's "changing
            this orphans N existing captures" warning; the backend never
            blocks on it (decision 2d, ADR 0010).
    """

    capture_dir: str
    capture_count: int


class BillingSettingsIn(BaseModel):
    """The body ``PUT /api/billing/settings`` takes."""

    capture_dir: str


def _closed_billing_count(session: Session) -> int:
    """How many closed Billing Readings exist — the rows a capture could exist
    for (decision 2d). Computed from the database, never by walking the
    capture folder: a directory walk over a possible network share costs real
    time for a number that only feeds a warning."""
    return (
        session.scalar(select(func.count()).select_from(BillingReading).where(BillingReading.record_status.is_(None)))
        or 0
    )


@router.get("/settings")
def get_billing_settings(session: SessionDep) -> ApiResponse[BillingSettingsOut]:
    """Return the current ``capture_dir`` and how many closed rows exist.

    Any authenticated caller — reading a setting is not admin-only, matching
    the rest of this router (``list_billing_readings`` above).
    """
    capture_dir = get_setting(session, CAPTURE_DIR_KEY, CAPTURE_DIR_DEFAULT)
    return ApiResponse.ok(BillingSettingsOut(capture_dir=capture_dir, capture_count=_closed_billing_count(session)))


@router.put("/settings")
def put_billing_settings(
    body: BillingSettingsIn, session: SessionDep, _admin: AdminDep
) -> ApiResponse[BillingSettingsOut]:
    """Save ``capture_dir`` — admin-only, validated before it is stored (ADR 0010).

    An empty string is accepted without path validation — it means "disable
    capture" (decision 16), not a path to reject. A non-empty value is
    validated by :func:`~arichds.capture.paths.validate_capture_dir_setting`;
    a rejection becomes 422 with the sentence an operator can act on.

    **Never blocks on existing captures** (decision 2d, ADR 0010) — changing
    the value orphans old files by design; the frontend is where the warning
    about that lives, before this endpoint is even called.
    """
    if body.capture_dir.strip():
        try:
            resolved = validate_capture_dir_setting(body.capture_dir, get_settings().capture_allowlist_roots())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
        value = str(resolved)
    else:
        value = ""

    set_setting(session, CAPTURE_DIR_KEY, value)
    session.commit()

    return ApiResponse.ok(BillingSettingsOut(capture_dir=value, capture_count=_closed_billing_count(session)))


#: Media type per download format — the only two the capture package renders.
_MEDIA_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
#: The feature key gating each format, on top of the router's own `billing`
#: gate (decision 14, issue #22).
_FORMAT_FEATURE: dict[str, str] = {"pdf": "auto_capture", "xlsx": "billing_excel_export"}


def _is_regular_file(path: Path) -> bool:
    """``lstat`` + ``S_ISREG`` — never follows a symlink (v1 ``router.py:170-177``)."""
    try:
        file_stat = os.lstat(str(path))
    except OSError:
        return False
    return stat.S_ISREG(file_stat.st_mode)


def _stream_file(path: Path) -> Iterator[bytes]:
    """Yield *path* in chunks through an ``O_NOFOLLOW`` open (v1 ``router.py:179-193``).

    The fd is opened lazily, inside the generator, so a client that
    disconnects before Starlette starts iterating never leaks one. Guards
    ``fdopen`` itself (v1 ``router.py:184-188``): if it raises, the raw fd
    must still be closed directly — nothing else owns it yet.
    """
    fd = os.open(str(path), os.O_RDONLY | O_NOFOLLOW | O_BINARY)
    try:
        file_obj = os.fdopen(fd, "rb")
    except OSError:
        os.close(fd)
        raise
    try:
        while chunk := file_obj.read(65536):
            yield chunk
    finally:
        file_obj.close()


@router.get("/captures/{reading_id}")
def download_billing_capture(
    reading_id: int,
    session: SessionDep,
    license_service: LicenseServiceDep,
    document_format: Annotated[
        Literal["pdf", "xlsx"], Query(alias="format", description="Which document to download")
    ] = "pdf",
) -> StreamingResponse:
    """Download the capture for one closed Billing Reading — render-on-miss
    (decision 14, ADR 0010, issue #22).

    Existing file -> streamed as-is. Missing -> rendered, hardened-written,
    then streamed — this is what replaces v1's regenerate endpoint, its
    permanently-failed-capture state, and its two-second frontend retry
    entirely (ADR 0010 §"What we do not carry over from v1").

    Gated per-format on top of the router's own ``billing`` gate: ``pdf``
    needs ``auto_capture``, ``xlsx`` needs ``billing_excel_export`` — because
    this endpoint is also a renderer, it carries the same entitlement the
    writer does.

    Raises:
        HTTPException: 404 for an unknown id, the Open Period (which has no
            capture — SPEC §3.6), an unconfigured ``capture_dir``, or a
            capture that still could not be produced. 422 for a row whose
            ``meter_serial`` fails path validation.
    """
    required_feature = _FORMAT_FEATURE[document_format]
    if not feature_enabled(required_feature, license_service=license_service, settings=get_settings()):
        raise FeatureDisabledError(required_feature)

    row = session.get(BillingReading, reading_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such Billing Reading.")
    if row.record_status == "open":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The Open Period has no capture.")

    capture_dir_str = get_setting(session, CAPTURE_DIR_KEY, CAPTURE_DIR_DEFAULT)
    if not capture_dir_str.strip():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="capture_dir is not configured — nothing to download."
        )
    capture_dir = Path(capture_dir_str)

    device = session.get(Device, row.device_id)
    device_name = device.name if device is not None else str(row.device_id)

    try:
        pdf_target, xlsx_target = capture_target_paths(capture_dir, row.meter_serial or "", row.bill_date)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    target = pdf_target if document_format == "pdf" else xlsx_target

    if not _is_regular_file(target):
        try:
            if document_format == "pdf":
                write_pdf_capture(row, device_name, target, capture_dir)
            else:
                write_xlsx_capture(row, device_name, target, capture_dir)
        except FileExistsError:
            pass  # a concurrent request just wrote it — fall through and serve it
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
        except OSError as exc:
            # A real possibility on a network-share capture_dir: disk full,
            # permission denied, the share unreachable. Structured 500 rather
            # than an unhandled exception with no detail (v1's
            # BILLING_CAPTURE_IO_ERROR — router.py:147 — makes the same call).
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Could not write the capture: {exc}"
            ) from exc

    if not _is_regular_file(target):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The capture could not be created.")

    return StreamingResponse(
        _stream_file(target),
        media_type=_MEDIA_TYPES[document_format],
        headers={"Content-Disposition": f'attachment; filename="{target.name}"'},
    )
