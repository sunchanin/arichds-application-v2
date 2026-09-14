"""The Energy Summary export file (M13, issue 02) — rewritten whole from the
stored Energy Summary on every export cycle, since ADR 0022/0023 (M14,
ticket 04).

**Why a file at all, when ADR 0012 said the summary was derived on every
request and deliberately not reproducible?** Because Retention deletes the
Interval Readings it was derived from after ninety days, and now also deletes
`energy_summary_days` rows on the same schedule (ADR 0022). Past that point
this file is the only record of the split that survives.

**This module now reads only `energy_summary_days`** through
:func:`arichds.db.energy_summary_store.stored_energy_summary_rows` — never
:func:`arichds.db.energy_query.energy_summary_rows`, the live aggregation.
That live call is what :mod:`arichds.db.energy_summary_store`'s own recompute
job runs, on the scheduler's `energy_summary_recompute` job, registered
immediately ahead of `csv_export` (`jobs/scheduler.py::default_jobs`) — so by
the time this module runs on the same pass, the table already holds this
cycle's freshest numbers.

Two forms, both reading the same table:

* **The daily file** — the scheduler rewrites the whole file every cycle
  (:func:`export_device_energy`), from exactly the same
  `[local_today − (RETENTION_DAYS − 1), local_today]` window the recompute
  job stores — including today's own row, partial or not: unlike the old
  append-only file, a wrong number here is corrected on the very next cycle
  rather than being wrong forever, so there is no reason left to hold it
  back. There is no watermark any more (`devices.energy_exported_through`
  is dropped, migration 0018) and no head-change special case — every cycle
  already reproduces the file's whole current content, so a head change is
  just what a normal cycle does.
* **The on-demand file** — an operator presses a button and gets a snapshot
  of the range they are looking at, in a file whose name carries that range
  so it can never collide with the daily one. Also reads the stored table
  now, so it always agrees with the Energy Summary page and the daily file
  for the same days.

**A resolved target with nothing to write still holds quietly** — mirroring
`export/billing_csv.py` and `export/csv_export.py`: a device with no stored
day in its window (a brand-new device, or one whose data has aged out of the
retention window entirely) is left with no file rather than an empty one, the
same choice already made for a device with no meter serial or no configured
output folder. The one difference from the Load Profile CSV / Billing files:
those can only ever *gain* rows (readings keep arriving; billing periods are
never purged, ADR 0009), so "hold when there is nothing yet" can never leave
a stale file behind. The Energy file's window can shrink to nothing for a
device that stops reporting for the whole retention window — at that point
this module leaves whatever was last written in place rather than replacing
it with an empty file. No acceptance criterion in ticket 04 names that case,
and it is the same choice the sibling exporters already make, but it is
worth stating plainly rather than leaving it to be discovered.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from arichds.capture.paths import sanitize_meter_serial, validate_directory_setting
from arichds.config import get_settings
from arichds.constants import RETENTION_DAYS
from arichds.db.app_settings import (
    EXPORT_AUTO_SAVE_ENABLED_DEFAULT,
    EXPORT_AUTO_SAVE_ENABLED_KEY,
    EXPORT_DATE_FORMAT_DEFAULT,
    EXPORT_DATE_FORMAT_KEY,
    EXPORT_ENERGY_FILENAME_TMPL_DEFAULT,
    EXPORT_ENERGY_FILENAME_TMPL_KEY,
    EXPORT_OUTPUT_DIR_DEFAULT,
    EXPORT_OUTPUT_DIR_KEY,
    get_setting,
)
from arichds.db.energy_query import EnergySummaryDay, local_today
from arichds.db.energy_summary_store import stored_energy_summary_rows
from arichds.db.models import Device
from arichds.db.session import session_scope
from arichds.export.format import (
    ENERGY_EXPORT_HEADERS,
    file_header_block,
    format_energy_rows,
    render_filename,
)
from arichds.export.writer import replace_rows

logger = logging.getLogger(__name__)

_FILE_LABEL = "Energy"
_LOG_LABEL = "Energy export"

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


@dataclass(frozen=True)
class EnergyExportResult:
    """What one call did.

    Attributes:
        rows_written: How many local days the file now holds. Zero is a
            normal answer — a device with no stored day in its window holds
            quietly (module docstring).
        path: The resolved target file, or ``None`` when the call held, wrote
            nothing, or failed before/while writing.
    """

    rows_written: int
    path: Path | None


def _device_lock(device_id: int) -> threading.Lock:
    """The one lock guarding *device_id*'s energy exports, created on first
    use — so the scheduler job and a button press cannot race the same file."""
    with _locks_guard:
        lock = _locks.get(device_id)
        if lock is None:
            lock = threading.Lock()
            _locks[device_id] = lock
        return lock


def _range_filename(template: str, meter_token: str, start: date, end: date) -> str:
    """The on-demand file's name: the daily file's name with the range inserted
    before the extension.

    One filename setting rather than two — the daily file and a snapshot of a
    chosen range share the same template for the same meter, and a second
    template would be a value somebody has to keep in step with the first by
    hand. The range in the name is what makes the two unable to collide.
    """
    rendered = Path(render_filename(template, meter_token))
    return f"{rendered.stem}-{start.isoformat()}-to-{end.isoformat()}{rendered.suffix}"


@dataclass(frozen=True)
class _Target:
    """Everything an export needs that comes out of settings and the device row."""

    device: Device
    meter_token: str
    output_dir: Path
    filename_tmpl: str
    date_format: str


def _resolve_target(session: Session, device_id: int, *, require_auto_save: bool) -> _Target | None:
    """Read the settings and the device row, or ``None`` when this export must
    hold. Every hold is quiet — an unset folder, an undiscovered Meter Serial
    (ADR 0005) and a disabled auto-save are normal states, not failures."""
    if require_auto_save:
        enabled = get_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, EXPORT_AUTO_SAVE_ENABLED_DEFAULT) == "true"
        if not enabled:
            return None

    output_dir_str = get_setting(session, EXPORT_OUTPUT_DIR_KEY, EXPORT_OUTPUT_DIR_DEFAULT).strip()
    if not output_dir_str:
        return None

    device = session.get(Device, device_id)
    if device is None:
        logger.warning("%s: device_id=%d not found — skipping", _LOG_LABEL, device_id)
        return None
    if not device.meter_serial:
        return None
    try:
        meter_token = sanitize_meter_serial(device.meter_serial)
    except ValueError:
        logger.warning("%s: unsafe meter token for device_id=%d — skipping", _LOG_LABEL, device_id)
        return None

    try:
        output_dir = validate_directory_setting(
            output_dir_str, get_settings().capture_allowlist_roots(), setting_name="output_dir"
        )
    except ValueError:
        logger.warning("%s: export_output_dir invalid for device_id=%d — skipping", _LOG_LABEL, device_id)
        return None

    return _Target(
        device=device,
        meter_token=meter_token,
        output_dir=output_dir,
        filename_tmpl=get_setting(session, EXPORT_ENERGY_FILENAME_TMPL_KEY, EXPORT_ENERGY_FILENAME_TMPL_DEFAULT),
        date_format=get_setting(session, EXPORT_DATE_FORMAT_KEY, EXPORT_DATE_FORMAT_DEFAULT),
    )


def _header_block(target: _Target) -> list[list[str]]:
    return file_header_block(
        customer=target.device.customer,
        site_name=target.device.site_name,
        meter_serial=target.meter_token,
        file_label=_FILE_LABEL,
    )


def _replace_whole(target: _Target, path: Path, days: list[EnergySummaryDay]) -> bool:
    """Write *days* as the file's whole current content, one atomic swap
    (ADR 0023) — every call to :func:`export_device_energy` and
    :func:`export_energy_range` goes through this; there is no cheaper
    incremental path left (module docstring)."""
    return replace_rows(
        path,
        header_block=_header_block(target),
        header_row=ENERGY_EXPORT_HEADERS,
        rows=format_energy_rows(days, date_format=target.date_format),
        allowlist=[target.output_dir],
        label=_LOG_LABEL,
    )


def export_device_energy(device_id: int, *, require_auto_save: bool) -> EnergyExportResult:
    """Rewrite *device_id*'s whole Energy Export File from `energy_summary_days`
    (ADR 0023, ticket 04): the `[local_today − (RETENTION_DAYS − 1), local_today]`
    window, the same one the recompute job stores.

    Returns:
        How many days the file now holds and the target file. Never raises: a
        hold, a write failure or an allowlist rejection is zero rows written,
        logged, with the previous file (if any) left untouched.
    """
    with _device_lock(device_id):
        return _export_daily_locked(device_id, require_auto_save=require_auto_save)


def _export_daily_locked(device_id: int, *, require_auto_save: bool) -> EnergyExportResult:
    with session_scope() as session:
        target = _resolve_target(session, device_id, require_auto_save=require_auto_save)
        if target is None:
            return EnergyExportResult(rows_written=0, path=None)

        window_end = local_today()
        window_start = window_end - timedelta(days=RETENTION_DAYS - 1)
        days = stored_energy_summary_rows(session, device_id, window_start, window_end)
        if not days:
            # Nothing stored in the window yet — hold quietly rather than
            # write an empty file (module docstring: the same choice the
            # Load Profile CSV and Billing exports already make).
            return EnergyExportResult(rows_written=0, path=None)

        path = target.output_dir / render_filename(target.filename_tmpl, target.meter_token)
        if not _replace_whole(target, path, days):
            return EnergyExportResult(rows_written=0, path=path)
        return EnergyExportResult(rows_written=len(days), path=path)


def export_energy_range(device_id: int, start: date, end: date) -> EnergyExportResult:
    """Write *device_id*'s stored summary for ``[start, end]`` to its own file.

    Reads `energy_summary_days` (ADR 0023, ticket 04) rather than aggregating
    live — the same table the Energy Summary page and the daily file read, so
    this can never disagree with either.

    Returns:
        How many days were written and the target file.
    """
    with _device_lock(device_id), session_scope() as session:
        target = _resolve_target(session, device_id, require_auto_save=False)
        if target is None:
            return EnergyExportResult(rows_written=0, path=None)

        days = stored_energy_summary_rows(session, device_id, start, end)
        if not days:
            return EnergyExportResult(rows_written=0, path=None)

        path = target.output_dir / _range_filename(target.filename_tmpl, target.meter_token, start, end)
        # Always the whole answer for its own uniquely-named range, so this
        # goes through the atomic replace path rather than an append — a
        # second save for the exact same range must not duplicate rows.
        if not _replace_whole(target, path, days):
            return EnergyExportResult(rows_written=0, path=path)
        return EnergyExportResult(rows_written=len(days), path=path)


__all__ = [
    "EnergyExportResult",
    "export_device_energy",
    "export_energy_range",
]
