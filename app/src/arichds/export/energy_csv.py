"""The Energy Summary export file (M13, issue 02) — the Time-of-Use daily split
written to disk, in two forms that share one layout.

**Why a file at all, when ADR 0012 says the summary is derived on every request
and deliberately not reproducible?** Because Retention deletes the Interval
Readings it is derived from after ninety days. Past that point this file is the
only record of the split that survives. Nothing here is persisted in the
database and nothing reads it back: a file is a snapshot somebody chose to take,
not a cache. **ADR 0012 is untouched.**

Two forms:

* **The daily file** — the scheduler appends one row per device per local day.
  This is the archive.
* **The on-demand file** — an operator presses a button and gets the range they
  are looking at, in a file whose name carries that range so it can never
  collide with the archive.

**The watermark advances whether or not a row was written.** A local day with
no Interval Readings produces no row and is never revisited. Holding the
watermark until a day produces a row would turn a genuine data gap into a
window the job re-queries for ever with nothing to report it — a shape this
codebase has already shipped once.

**The consequence, stated rather than hidden**: Interval Readings that arrive
late, through the ninety-day load-profile backfill, never reach the daily file.
Together with a Holiday entered after the fact (issue 03), that is exactly two
reasons the archive can be stale, and **the on-demand save is the single
corrective for both**. One mechanism, not two.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from arichds.capture.paths import sanitize_meter_serial, validate_directory_setting
from arichds.config import get_settings
from arichds.constants import METER_LOCAL_UTC_OFFSET_HOURS
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
from arichds.db.energy_query import EnergySummaryDay, energy_summary_rows
from arichds.db.models import Device
from arichds.db.session import session_scope
from arichds.export.format import (
    ENERGY_EXPORT_HEADERS,
    file_header_block,
    format_energy_rows,
    render_filename,
)
from arichds.export.writer import append_rows

logger = logging.getLogger(__name__)

_FILE_LABEL = "Energy"
_LOG_LABEL = "Energy export"

#: How far back a device with no watermark starts. Matches Retention, because
#: there is nothing older to summarise: a day whose Interval Readings have been
#: purged can never produce a row again.
_FIRST_RUN_DAYS = 90

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


@dataclass(frozen=True)
class EnergyExportResult:
    """What one call did.

    Attributes:
        rows_written: How many local days were appended. Zero is a normal
            answer for the daily file — a day with no Interval Readings
            produces no row, and the watermark still moves past it.
        path: The resolved target file, or ``None`` when the call held or
            failed before a path existed.
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


def local_today() -> date:
    """Today's date in the meter's fixed local zone.

    The summary's rows are local calendar days, so "which day is finished" has
    to be asked in that zone rather than in UTC — near midnight the two
    disagree, and asking in UTC would either skip a day or write one twice.
    """
    return (datetime.now(UTC) + timedelta(hours=METER_LOCAL_UTC_OFFSET_HOURS)).date()


def _range_filename(template: str, meter_token: str, start: date, end: date) -> str:
    """The on-demand file's name: the daily file's name with the range inserted
    before the extension.

    One filename setting rather than two — the archive and a snapshot of it are
    the same file for the same meter, and a second template would be a value
    somebody has to keep in step with the first by hand. The range in the name
    is what makes the two unable to collide.
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


def _write(target: _Target, path: Path, days: list[EnergySummaryDay]) -> bool:
    return append_rows(
        path,
        header_block=file_header_block(
            customer=target.device.customer,
            site_name=target.device.site_name,
            meter_serial=target.meter_token,
            file_label=_FILE_LABEL,
        ),
        header_row=ENERGY_EXPORT_HEADERS,
        rows=format_energy_rows(days, date_format=target.date_format),
        allowlist=[target.output_dir],
        label=_LOG_LABEL,
    )


def export_device_energy(device_id: int, *, require_auto_save: bool) -> EnergyExportResult:
    """Append every finished local day *device_id* has not yet exported.

    "Finished" means strictly before today in the meter's local zone — today is
    still accumulating, and a partial day appended to a file that cannot be
    revised would be wrong for ever.

    Returns:
        How many days were appended and the target file. Never raises: a hold,
        a write failure or an allowlist rejection is zero rows written, logged,
        with the watermark left where it was.
    """
    with _device_lock(device_id):
        return _export_daily_locked(device_id, require_auto_save=require_auto_save)


def _export_daily_locked(device_id: int, *, require_auto_save: bool) -> EnergyExportResult:
    with session_scope() as session:
        target = _resolve_target(session, device_id, require_auto_save=require_auto_save)
        if target is None:
            return EnergyExportResult(rows_written=0, path=None)

        last_finished = local_today() - timedelta(days=1)
        watermark = target.device.energy_exported_through
        start = (
            watermark + timedelta(days=1)
            if watermark is not None
            else last_finished - timedelta(days=_FIRST_RUN_DAYS - 1)
        )
        if start > last_finished:
            return EnergyExportResult(rows_written=0, path=None)

        days = energy_summary_rows(session, device_id, start, last_finished)

        path = target.output_dir / render_filename(target.filename_tmpl, target.meter_token)
        # A window with no readings at all still advances the watermark: the
        # days are genuinely empty, and re-querying them for ever would be the
        # self-healing-watermark trap rather than patience.
        if days and not _write(target, path, days):
            return EnergyExportResult(rows_written=0, path=path)

        target.device.energy_exported_through = last_finished
        session.commit()
        return EnergyExportResult(rows_written=len(days), path=path if days else None)


def export_energy_range(device_id: int, start: date, end: date) -> EnergyExportResult:
    """Write *device_id*'s summary for ``[start, end]`` to its own file.

    **The watermark is not touched.** This is a snapshot an operator asked for,
    not the archive — and it is the corrective for every reason the archive can
    be stale: a Holiday entered after the fact, or Interval Readings that
    arrived through a backfill after the day had already been written.

    Returns:
        How many days were written and the target file.
    """
    with _device_lock(device_id), session_scope() as session:
        target = _resolve_target(session, device_id, require_auto_save=False)
        if target is None:
            return EnergyExportResult(rows_written=0, path=None)

        days = energy_summary_rows(session, device_id, start, end)
        if not days:
            return EnergyExportResult(rows_written=0, path=None)

        path = target.output_dir / _range_filename(target.filename_tmpl, target.meter_token, start, end)
        if not _write(target, path, days):
            return EnergyExportResult(rows_written=0, path=path)
        return EnergyExportResult(rows_written=len(days), path=path)


__all__ = [
    "EnergyExportResult",
    "export_device_energy",
    "export_energy_range",
    "local_today",
]
