"""The Load Profile CSV auto-export (M7 slice 3, issue #30) — the file an
operator's downstream tooling appends to for months, one per meter.

Two entry points:

* :func:`export_device` — read one device's pending rows and append them.
  Both "Save CSV now" (``POST /api/load-profile/export``) and the scheduler
  job call this; the ``require_auto_save`` parameter is the one thing that
  differs between them (D-11).
* :func:`csv_export_cycle` — the Scheduler's ``csv_export`` job (D-10),
  walking every device once.

**The watermark is ``devices.csv_exported_through``, a column, not a table**
(D-8) — ``None`` means nothing has been exported yet, so everything stored
exports, up to the skew cap (D-9): there is no separate first-enable/backfill
mechanism the way v1 needed two for.

**The skew cap (F5)** holds Logger 1 rows back until Logger 2 catches up, on
models that have a second logger, with a staleness escape so a dead Logger 2
cannot hold rows forever. Anchored in meter-domain time relative to
``MAX(read_at)`` on Logger 1, never wall-clock, so the release is
deterministic with no clock.

**Ordering, always**: query the pending rows -> format them -> append to disk
(``flush()`` + ``os.fsync()``) -> **only then** advance and commit the
watermark. A write ``OSError`` or an allowlist rejection is logged and
returns 0 rows written; the watermark stays untouched and the pending rows
retry on the next call.

**A per-device lock**, mirroring v1's own ``LpCsvExporter`` (module
docstring, `cewe-worker/src/worker/lp_csv_exporter.py`), so the scheduler
job and a concurrent "Save CSV now" for the same device serialise instead of
racing the same file and the same watermark. Two different devices never
contend — each gets its own lock.
"""

from __future__ import annotations

import csv
import logging
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arichds.acquisition.poller import build_driver
from arichds.capture.paths import ensure_within_allowlist, sanitize_meter_serial, validate_directory_setting
from arichds.config import get_settings
from arichds.db.app_settings import (
    EXPORT_AUTO_SAVE_ENABLED_DEFAULT,
    EXPORT_AUTO_SAVE_ENABLED_KEY,
    EXPORT_CSV_FILENAME_TMPL_DEFAULT,
    EXPORT_CSV_FILENAME_TMPL_KEY,
    EXPORT_DATE_FORMAT_DEFAULT,
    EXPORT_DATE_FORMAT_KEY,
    EXPORT_OUTPUT_DIR_DEFAULT,
    EXPORT_OUTPUT_DIR_KEY,
    get_setting,
)
from arichds.db.load_profile_query import merged_rows_select
from arichds.db.models import Device, LoadProfileReading
from arichds.db.session import session_scope
from arichds.export.format import _EXPORT_HEADERS, format_rows, render_filename

logger = logging.getLogger(__name__)

#: Written once, when the target file is absent or empty (v1 parity — Excel
#: on Windows needs the BOM to render non-ASCII text correctly).
_UTF8_BOM = "﻿"

#: F5 — how far Logger 2 may lag Logger 1 before the staleness escape
#: releases held rows anyway (v1's `LP_L2_SKEW_MAX_HOURS`).
_SKEW_CAP = timedelta(hours=24)

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


@dataclass(frozen=True)
class CsvExportResult:
    """What one call to :func:`export_device` did.

    Attributes:
        rows_written: How many rows were appended this call. Zero for every
            hold/skip/failure case (D-11, D-12, D-15) — never an exception.
        path: The resolved target file path, or ``None`` when nothing was
            resolved (the call held or failed before a path existed).
    """

    rows_written: int
    path: Path | None


def _device_lock(device_id: int) -> threading.Lock:
    """Return the one lock guarding *device_id*'s export, creating it on
    first use. Never removed — a lock outlives the device that first needed
    it (mirrors `acquisition/locks.py::EndpointLocks`)."""
    with _locks_guard:
        lock = _locks.get(device_id)
        if lock is None:
            lock = threading.Lock()
            _locks[device_id] = lock
        return lock


def export_device(device_id: int, *, require_auto_save: bool) -> CsvExportResult:
    """Append *device_id*'s pending Interval Readings to its CSV file.

    Serialised per device by :func:`_device_lock`, so the scheduler job and a
    concurrent "Save CSV now" for the same device never race the same file
    or the same watermark; a different device's export is never blocked by
    this one (D-14/T13).

    Args:
        device_id: The device to export.
        require_auto_save: When True (the scheduler job), a device whose
            ``export_auto_save_enabled`` setting is off is held with zero
            rows written (D-11). When False ("Save CSV now"), the switch is
            ignored — pressing a button already expresses intent.

    Returns:
        How many rows were appended and the resolved target path (D-11).
        Never raises for a business hold, a write failure, or an allowlist
        rejection — every one of those is zero rows written, logged, and the
        watermark left untouched so the pending rows retry next call.
    """
    with _device_lock(device_id):
        return _export_device_locked(device_id, require_auto_save=require_auto_save)


def _export_device_locked(device_id: int, *, require_auto_save: bool) -> CsvExportResult:
    with session_scope() as session:
        if require_auto_save:
            enabled = get_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, EXPORT_AUTO_SAVE_ENABLED_DEFAULT) == "true"
            if not enabled:
                return CsvExportResult(rows_written=0, path=None)

        output_dir_str = get_setting(session, EXPORT_OUTPUT_DIR_KEY, EXPORT_OUTPUT_DIR_DEFAULT).strip()
        if not output_dir_str:
            return CsvExportResult(rows_written=0, path=None)

        date_format = get_setting(session, EXPORT_DATE_FORMAT_KEY, EXPORT_DATE_FORMAT_DEFAULT)
        filename_tmpl = get_setting(session, EXPORT_CSV_FILENAME_TMPL_KEY, EXPORT_CSV_FILENAME_TMPL_DEFAULT)

        device = session.get(Device, device_id)
        if device is None:
            logger.warning("CSV export: device_id=%d not found — skipping", device_id)
            return CsvExportResult(rows_written=0, path=None)

        # D-15 — the file is named by the sanitized serial; an undiscovered
        # serial is the normal early state (ADR 0005), so this holds quietly.
        if not device.meter_serial:
            return CsvExportResult(rows_written=0, path=None)
        try:
            meter_token = sanitize_meter_serial(device.meter_serial)
        except ValueError:
            logger.warning("CSV export: unsafe meter token for device_id=%d — skipping", device_id)
            return CsvExportResult(rows_written=0, path=None)

        # D-12 — whether this device has a second logger comes from the
        # driver, never from the data. Built but never connected; no
        # Transport Endpoint lock is taken (nothing here talks to a meter).
        try:
            driver = build_driver(device)
        except ValueError as exc:
            logger.warning("CSV export skipped for device_id=%d: %s", device_id, exc)
            return CsvExportResult(rows_written=0, path=None)
        has_secondary_logger = 2 in driver.load_profile_loggers()

        l1_max = session.scalar(
            select(func.max(LoadProfileReading.read_at)).where(
                LoadProfileReading.device_id == device_id, LoadProfileReading.logger_id == 1
            )
        )
        if l1_max is None:
            return CsvExportResult(rows_written=0, path=None)
        l1_max = _as_utc(l1_max)

        cap = _compute_cap(session, device_id, l1_max, has_secondary_logger)

        watermark = device.csv_exported_through
        watermark = _as_utc(watermark) if watermark is not None else None

        stmt = merged_rows_select(device_id)
        if watermark is not None:
            stmt = stmt.where(LoadProfileReading.read_at > watermark)
        stmt = stmt.where(LoadProfileReading.read_at <= cap).order_by(LoadProfileReading.read_at.asc())

        rows = session.execute(stmt).all()
        if not rows:
            return CsvExportResult(rows_written=0, path=None)

        device_label = f"{device.name} ({meter_token})"
        formatted = format_rows(
            [row._mapping for row in rows],  # noqa: SLF001 — Row._mapping is the documented public accessor.
            device_label=device_label,
            date_format=date_format,
        )

        try:
            resolved_output_dir = validate_directory_setting(
                output_dir_str, get_settings().capture_allowlist_roots(), setting_name="output_dir"
            )
        except ValueError:
            logger.warning("CSV export: export_output_dir invalid for device_id=%d — skipping", device_id)
            return CsvExportResult(rows_written=0, path=None)

        filename = render_filename(filename_tmpl, meter_token)
        final_path = resolved_output_dir / filename

        if not _append_rows(final_path, formatted, [resolved_output_dir], device_id):
            return CsvExportResult(rows_written=0, path=final_path)

        max_read_at = _as_utc(rows[-1]._mapping["read_at"])  # noqa: SLF001
        device.csv_exported_through = max_read_at
        session.commit()
        return CsvExportResult(rows_written=len(formatted), path=final_path)


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; every stored ``read_at`` is UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _compute_cap(session: Session, device_id: int, l1_max: datetime, has_secondary_logger: bool) -> datetime:
    """F5 — the inclusive upper bound of the export window.

    Args:
        session: Active DB session.
        device_id: The device being exported.
        l1_max: This device's ``MAX(read_at)`` on Logger 1 — never ``None``
            (the caller has already returned before this is called for a
            device with no Logger 1 rows).
        has_secondary_logger: Whether the driver reports a Logger 2 (D-12).

    Returns:
        The inclusive upper-bound ``read_at`` for the export window.
    """
    if not has_secondary_logger:
        return l1_max

    l2_max = session.scalar(
        select(func.max(LoadProfileReading.read_at)).where(
            LoadProfileReading.device_id == device_id, LoadProfileReading.logger_id == 2
        )
    )
    if l2_max is None:
        # Logger 2 never seen — hold everything within the skew window.
        return l1_max - _SKEW_CAP
    l2_max = _as_utc(l2_max)
    if l2_max >= l1_max - _SKEW_CAP:
        # Logger 2 present and within the window — hold rows past its frontier.
        return min(l1_max, l2_max)
    # Logger 2 stale beyond the window — staleness escape, release everything.
    return l1_max


def _append_rows(final_path: Path, rows: list[list[str]], allowlist: list[Path], device_id: int) -> bool:
    """Append *rows* to *final_path* (BOM + header when the file is absent
    or empty), ``flush()`` + ``os.fsync()``.

    Returns:
        True on success, False on a write ``OSError`` or an allowlist
        rejection — logged WARNING either way; the caller must not advance
        the watermark on False.
    """
    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        # Defence-in-depth TOCTOU guard immediately before opening the file
        # (mirrors capture/write.py's own ordering).
        ensure_within_allowlist(final_path, allowlist)
        need_header = not final_path.exists() or final_path.stat().st_size == 0
        with open(final_path, "a", encoding="utf-8", newline="") as file_obj:
            writer = csv.writer(file_obj, lineterminator="\n")
            if need_header:
                file_obj.write(_UTF8_BOM)
                writer.writerow(_EXPORT_HEADERS)
            writer.writerows(rows)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        return True
    except ValueError:
        logger.warning("CSV export: target path outside allowlist for device_id=%d — skipping", device_id)
        return False
    except OSError:
        logger.warning(
            "CSV export: write failed for device_id=%d (path unavailable) — will retry next cycle",
            device_id,
            exc_info=True,
        )
        return False


def csv_export_cycle() -> None:
    """Export every device that should be exported, once (D-10, issue #30).

    The Scheduler's ``csv_export`` job — see
    :func:`arichds.jobs.scheduler.default_jobs`, registered immediately
    after ``load_profile`` so it runs behind the load-profile cycle in the
    same pass (D-10).

    **Only ``enabled`` filters — deliberately not ``status != offline``
    too**, unlike the sibling read cycles. CONTEXT.md's Pause is exactly
    this job's shape: *"Stopping every background read of one device while
    leaving it fully visible… Manual Reads still work on a paused device"*
    — the background job skips a paused device, "Save CSV now" still works
    on it, and its rows wait for export until it resumes rather than being
    lost. ``status != offline`` is a different rule and does not carry over:
    :func:`arichds.acquisition.load_profile.load_profile_cycle` excludes an
    Offline device because reading one would burn a full timeout against a
    meter that is not answering — a cost of *talking to the meter*. This
    job never talks to a meter (D-10), so that cost does not exist here,
    and the filter's only effect would be to silently withhold rows
    **already sitting in the database** from the customer's CSV for as long
    as the meter stays Offline — indefinitely, for a meter that never comes
    back. Rows are not lost either way (``POST /export`` can always force
    them through), but a live meter's history the customer's own tooling
    reads should not stall on a filter that buys this job nothing.

    Sequential, one device's failure never stops the next.
    """
    with session_scope() as session:
        device_ids = list(session.scalars(select(Device.id).where(Device.enabled.is_(True)).order_by(Device.id)))

    for device_id in device_ids:
        try:
            export_device(device_id, require_auto_save=True)
        except Exception:  # noqa: BLE001 — one device must never strand the rest of the site.
            logger.exception("CSV export cycle failed for device id %s", device_id)
