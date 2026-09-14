"""The Energy Summary export file (M13, issue 02) — the Time-of-Use daily split
written to disk, in two forms that share one layout.

**Why a file at all, when ADR 0012 said the summary was derived on every
request and deliberately not reproducible?** Because Retention deletes the
Interval Readings it is derived from after ninety days. Past that point this
file is the only record of the split that survives — including now that ADR
0022 (M14, ticket 01) supersedes 0012 and stores the summary in
``energy_summary_days``: that table is itself subject to Retention (same
window, same reason), so the file remains the one place a day's split outlives
ninety days. **This module still calls**
:func:`arichds.db.energy_query.energy_summary_rows` directly, live, on every
call — never the stored table — but that is a sequencing fact, not a design
one: ADR 0023 (decided alongside 0022, not yet implemented) is what moves the
Energy Export File onto ``energy_summary_days``, rewritten whole every export
cycle; the ticket that lands ADR 0023 is what retires this module's own live
aggregation. Nothing here is persisted in the database and nothing reads it
back: a file is a snapshot somebody chose to take, not a cache.

Two forms:

* **The daily file** — the scheduler appends one row per device per local day,
  exactly as before ticket 02. It mirrors the 90-day window (ADR 0023) only
  when its head changes: a head-change rewrite (:func:`arichds.export.writer.replace_rows`)
  recomputes the whole 90-day window live and drops anything older, in one
  atomic swap. Between head changes it still only grows by appends — **ticket
  04** is what makes it rewrite that same window every cycle regardless of the
  head, which retires this distinction.
* **The on-demand file** — an operator presses a button and gets a snapshot of
  the range they are looking at, in a file whose name carries that range so it
  can never collide with the daily one.

**The watermark advances whether or not a row was written.** A local day with
no Interval Readings produces no row and is never revisited. Holding the
watermark until a day produces a row would turn a genuine data gap into a
window the job re-queries for ever with nothing to report it — a shape this
codebase has already shipped once.

**The consequence, stated rather than hidden**: Interval Readings that arrive
late, through the ninety-day load-profile backfill, are not picked up by the
daily file's own append cadence — nothing schedules a head change to catch
them. Together with a Holiday entered after the fact (issue 03), that is
exactly two reasons the daily file can lag behind the Energy Summary page, and
**the on-demand save is today's reliable corrective for both**, until ticket
04's every-cycle rewrite makes the daily file self-heal the same way
automatically.
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
from arichds.db.energy_query import EnergySummaryDay, energy_summary_rows, local_today
from arichds.db.models import Device
from arichds.db.session import session_scope
from arichds.export.format import (
    ENERGY_EXPORT_HEADERS,
    file_header_block,
    format_energy_rows,
    render_filename,
)
from arichds.export.writer import append_rows, head_changed, replace_rows

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


def _append(target: _Target, path: Path, days: list[EnergySummaryDay]) -> bool:
    """The cheap incremental path — the head has already been confirmed to
    match (or the file is new); see the ``head_changed`` branch in
    :func:`_export_daily_locked` (ticket 02, ADR 0023)."""
    return append_rows(
        path,
        header_block=_header_block(target),
        header_row=ENERGY_EXPORT_HEADERS,
        rows=format_energy_rows(days, date_format=target.date_format),
        allowlist=[target.output_dir],
        label=_LOG_LABEL,
    )


def _replace_whole(target: _Target, path: Path, days: list[EnergySummaryDay]) -> bool:
    """The whole-file path (ticket 02, ADR 0023): *days* is this file's
    entire current content, written as one atomic swap — used for a
    head-change rewrite and for the on-demand save, which is always the
    complete answer for its own range rather than a pending batch."""
    return replace_rows(
        path,
        header_block=_header_block(target),
        header_row=ENERGY_EXPORT_HEADERS,
        rows=format_energy_rows(days, date_format=target.date_format),
        allowlist=[target.output_dir],
        label=_LOG_LABEL,
    )


def _full_window_days(session: Session, device_id: int) -> tuple[list[EnergySummaryDay], date]:
    """Every finished local day inside the 90-day retention window, from the
    live Time-of-Use aggregation — what a head-change rewrite writes instead
    of the days a stale watermark would still call pending (ticket 02).

    **This module still calls** :func:`arichds.db.energy_query.energy_summary_rows`
    directly — moving onto the stored ``energy_summary_days`` table is ADR
    0023's ticket 04, not this one (see the module docstring).

    Returns:
        The days (possibly empty) and ``last_finished`` — the watermark the
        caller sets regardless of whether the window produced any rows,
        mirroring the daily incremental path's own reasoning.
    """
    last_finished = local_today() - timedelta(days=1)
    start = last_finished - timedelta(days=_FIRST_RUN_DAYS - 1)
    return energy_summary_rows(session, device_id, start, last_finished), last_finished


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

        path = target.output_dir / render_filename(target.filename_tmpl, target.meter_token)

        # ADR 0023 (ticket 02) — a head that no longer matches what is on disk
        # is rewritten in place with the whole 90-day window, atomically,
        # instead of M13's roll to a dated edition. Bypasses the watermark
        # deliberately: a rewrite must reproduce the file's whole current
        # content, not just the days a stale watermark still calls pending.
        if head_changed(path, _header_block(target), ENERGY_EXPORT_HEADERS):
            full_days, last_finished = _full_window_days(session, device_id)
            # Written unconditionally, even when the window is empty: the
            # file already carries an old head on disk (that is what
            # `head_changed` just found), so leaving it there would strand a
            # stale file under a header nothing describes any more.
            if not _replace_whole(target, path, full_days):
                return EnergyExportResult(rows_written=0, path=path)
            target.device.energy_exported_through = last_finished
            session.commit()
            return EnergyExportResult(rows_written=len(full_days), path=path)

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

        # A window with no readings at all still advances the watermark: the
        # days are genuinely empty, and re-querying them for ever would be the
        # self-healing-watermark trap rather than patience.
        if days and not _append(target, path, days):
            return EnergyExportResult(rows_written=0, path=path)

        target.device.energy_exported_through = last_finished
        session.commit()
        return EnergyExportResult(rows_written=len(days), path=path if days else None)


def export_energy_range(device_id: int, start: date, end: date) -> EnergyExportResult:
    """Write *device_id*'s summary for ``[start, end]`` to its own file.

    **The watermark is not touched.** This is a snapshot of the chosen range an
    operator asked for, not the daily file — and it is today's reliable
    corrective for every reason the daily file can lag behind the Energy
    Summary page: a Holiday entered after the fact, or Interval Readings that
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
