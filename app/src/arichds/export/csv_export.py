"""The Load Profile CSV auto-export (M7 slice 3, issue #30) — the file an
operator's downstream tooling appends to for months, one per meter.

Two entry points:

* :func:`export_device` — read one device's pending rows and append them.
  Both "Save CSV now" (``POST /api/load-profile/export``) and the scheduler
  job call this; the ``require_auto_save`` parameter is the one thing that
  differs between them (D-11).
* :func:`csv_export_cycle` — the Scheduler's ``csv_export`` job (D-10),
  walking every device once and writing **every** export file for that device
  before moving to the next (M13, issue 01): the Load Profile CSV here and the
  billing CSV in :mod:`arichds.export.billing_csv` and the Energy Summary file
  in :mod:`arichds.export.energy_csv`, each inside its own error boundary.

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

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arichds.acquisition.poller import build_driver
from arichds.capture.paths import sanitize_meter_serial, validate_directory_setting
from arichds.config import get_settings
from arichds.constants import RETENTION_DAYS
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
from arichds.export.billing_csv import export_device_billing
from arichds.export.energy_csv import export_device_energy
from arichds.export.format import _EXPORT_HEADERS, file_header_block, format_rows, render_filename
from arichds.export.writer import append_rows, head_changed, replace_rows

logger = logging.getLogger(__name__)

#: The label this file's header block carries, matching the customer's samples
#: (M13, issue 07), and what to call this export in a log line.
_FILE_LABEL = "Load Profile"
_LOG_LABEL = "CSV export"

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

        try:
            resolved_output_dir = validate_directory_setting(
                output_dir_str, get_settings().capture_allowlist_roots(), setting_name="output_dir"
            )
        except ValueError:
            logger.warning("CSV export: export_output_dir invalid for device_id=%d — skipping", device_id)
            return CsvExportResult(rows_written=0, path=None)

        device_label = f"{device.name} ({meter_token})"
        final_path = resolved_output_dir / render_filename(filename_tmpl, meter_token)
        header_block = file_header_block(
            customer=device.customer, site_name=device.site_name, meter_serial=meter_token, file_label=_FILE_LABEL
        )

        # ADR 0023 (ticket 02) — a head that no longer matches what is on disk
        # is rewritten in place under the whole 90-day window, atomically,
        # instead of M13's roll to a dated edition. This bypasses the
        # watermark entirely: a rewrite must reproduce the *whole* window a
        # fresh file would hold today, including rows an old watermark had
        # already marked exported under the head that is being replaced.
        if head_changed(final_path, header_block, _EXPORT_HEADERS):
            full_rows, full_watermark = _full_window_rows(
                session, device_id, cap=cap, device_label=device_label, date_format=date_format
            )
            written = replace_rows(
                final_path,
                header_block=header_block,
                header_row=_EXPORT_HEADERS,
                rows=full_rows,
                allowlist=[resolved_output_dir],
                label=_LOG_LABEL,
            )
            if not written:
                return CsvExportResult(rows_written=0, path=final_path)
            if full_watermark is not None:
                device.csv_exported_through = full_watermark
                session.commit()
            return CsvExportResult(rows_written=len(full_rows), path=final_path)

        watermark = device.csv_exported_through
        watermark = _as_utc(watermark) if watermark is not None else None

        stmt = merged_rows_select(device_id)
        if watermark is not None:
            stmt = stmt.where(LoadProfileReading.read_at > watermark)
        stmt = stmt.where(LoadProfileReading.read_at <= cap).order_by(LoadProfileReading.read_at.asc())

        # The newest row **in the window**, counted without the all-invalid
        # filter `merged_rows_select` applies (v1's INV-LP-06). The watermark
        # has to advance past a row that filter dropped, or the window grows by
        # one interval every cycle and the same rejected rows are re-queried for
        # ever — the shape of the self-healing-watermark trap, which needs no
        # bug to trigger it, only a meter that flagged one interval.
        #
        # This is the same value `rows[-1]` carried before the filter existed,
        # so the watermark's meaning is unchanged: "every row up to here has
        # been dealt with", where dealt with includes deliberately excluded.
        # It does **not** cover a write failure — those still return early
        # below, leaving the watermark untouched so the rows retry.
        window_max = session.scalar(
            select(func.max(LoadProfileReading.read_at)).where(
                LoadProfileReading.device_id == device_id,
                LoadProfileReading.logger_id == 1,
                LoadProfileReading.read_at <= cap,
                *([LoadProfileReading.read_at > watermark] if watermark is not None else []),
            )
        )
        if window_max is None:
            return CsvExportResult(rows_written=0, path=None)
        window_max = _as_utc(window_max)

        rows = session.execute(stmt).all()
        if not rows:
            # Rows exist in the window but the meter disowned every one of
            # them. Nothing to write, and nothing pending either.
            device.csv_exported_through = window_max
            session.commit()
            return CsvExportResult(rows_written=0, path=None)

        formatted = format_rows(
            [row._mapping for row in rows],  # noqa: SLF001 — Row._mapping is the documented public accessor.
            device_label=device_label,
            date_format=date_format,
        )

        # The head has already been confirmed to match (or the file is new) —
        # see the `head_changed` branch above, which is what makes a plain
        # append here safe (ticket 02, ADR 0023).
        written = append_rows(
            final_path,
            header_block=header_block,
            header_row=_EXPORT_HEADERS,
            rows=formatted,
            allowlist=[resolved_output_dir],
            label=_LOG_LABEL,
        )
        if not written:
            return CsvExportResult(rows_written=0, path=final_path)

        # `window_max`, not `rows[-1]` — see its own comment above. They are the
        # same instant unless the newest rows in the window were all-invalid,
        # and in that case `rows[-1]` would leave them pending for ever.
        device.csv_exported_through = window_max
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


def _full_window_rows(
    session: Session, device_id: int, *, cap: datetime, device_label: str, date_format: str
) -> tuple[list[list[str]], datetime | None]:
    """Every stored row inside the 90-day retention window, through the same
    merged Logger 1/Logger 2 query and skew cap (*cap*) the incremental
    append above uses — what a head-change rewrite writes instead of the rows
    a stale watermark would have picked up (ticket 02, ADR 0023).

    **Deliberately bypasses the watermark.** A rewrite has to reproduce the
    whole window a fresh file would hold today, including rows an earlier
    cycle already exported under the head that is now being replaced —
    filtering by the watermark here would drop exactly the rows the old file
    already carried.

    The lower bound mirrors :func:`arichds.db.retention.purge_expired`'s own
    cutoff (``now - RETENTION_DAYS``, real clock, UTC) rather than *cap*, so
    the file's window matches what the database still holds, not what one
    device's own newest reading happens to be.

    Returns:
        The formatted rows, oldest first, and the newest ``read_at`` among
        them (what the caller sets as the watermark) — or ``([], None)`` when
        the window holds nothing for this device.
    """
    window_start = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)

    window_max = session.scalar(
        select(func.max(LoadProfileReading.read_at)).where(
            LoadProfileReading.device_id == device_id,
            LoadProfileReading.logger_id == 1,
            LoadProfileReading.read_at >= window_start,
            LoadProfileReading.read_at <= cap,
        )
    )
    if window_max is None:
        return [], None
    window_max = _as_utc(window_max)

    stmt = (
        merged_rows_select(device_id)
        .where(LoadProfileReading.read_at >= window_start, LoadProfileReading.read_at <= cap)
        .order_by(LoadProfileReading.read_at.asc())
    )
    rows = session.execute(stmt).all()
    formatted = format_rows(
        [row._mapping for row in rows],  # noqa: SLF001 — Row._mapping is the documented public accessor.
        device_label=device_label,
        date_format=date_format,
    )
    return formatted, window_max


#: What :func:`csv_export_cycle` writes for each device, in order, each inside
#: its own error boundary (M13, issue 01). A tuple rather than two calls in the
#: loop body so adding the next export file is one line here and not another
#: try/except nested in a loop.
_PER_DEVICE_EXPORTS: tuple[tuple[str, Callable[..., object]], ...] = (
    ("Load Profile CSV export", export_device),
    ("Billing export", export_device_billing),
    ("Energy export", export_device_energy),
)


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

    **It writes every export file for one device before moving on** (M13,
    issue 01) — the Load Profile CSV and the billing CSV today. One job, one
    interval, one output folder, one switch: a second interval for the billing
    file would be a value somebody has to keep in step with this one by hand,
    which is the reasoning D-10 already used to tie this job's cadence to the
    load-profile cycle rather than give it its own.

    **Each file sits in its own error boundary.** A billing file that cannot
    be written — a locked file, a full disk, a file that cannot be replaced —
    must not cost that same device its Load Profile rows.
    """
    with session_scope() as session:
        device_ids = list(session.scalars(select(Device.id).where(Device.enabled.is_(True)).order_by(Device.id)))

    for device_id in device_ids:
        for label, export in _PER_DEVICE_EXPORTS:
            try:
                export(device_id, require_auto_save=True)
            except Exception:  # noqa: BLE001 — one file, one device must never strand the rest.
                logger.exception("%s cycle failed for device id %s", label, device_id)
