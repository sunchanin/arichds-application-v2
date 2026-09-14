"""The billing export file (M13, issue 01) — one growing CSV per meter, a row
per closed billing period.

**Neither v1 nor v2 has ever produced this file.** v1's billing output is the
per-period PDF/xlsx capture, which v2 also ships (ADR 0010/0015); the file the
customer sends us as a sample comes from a third Windows-Forms program we are
replacing. So there is no parity obligation here and no installed base — the
customer's own sample is the whole contract.

:func:`export_device_billing` appends one device's unexported closed periods.
Both the scheduler job and "Save now" call it, mirroring the Load Profile CSV
export (:mod:`arichds.export.csv_export`); ``require_auto_save`` is the one
thing that differs between them.

The walk over every enabled device lives in
:func:`arichds.export.csv_export.csv_export_cycle`, which writes every export
file for one device before moving to the next — **one job, one interval, one
output folder, one switch**, with each file inside its own error boundary so a
billing file that cannot be written never stops that device's Load Profile
file.

**Only closed periods.** The Open Period's Bill Date advances on every read
(ADR 0018, CONTEXT.md — Open Period), so a file that appends cannot hold it:
the same period would be written again on every cycle under a date that had
moved. :func:`~arichds.db.billing_query.closed_periods_with_record_no` is where
that exclusion lives, shared with the All-Meters View.

**Ordering, always**: query the pending periods -> format them -> append to
disk -> **only then** advance and commit the watermark. A write failure leaves
the watermark untouched and the periods retry next call — the same discipline
the Load Profile CSV export follows, and the reason neither writer can lose a
row to a full disk.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from arichds.capture.paths import sanitize_meter_serial, validate_directory_setting
from arichds.config import get_settings
from arichds.db.app_settings import (
    EXPORT_AUTO_SAVE_ENABLED_DEFAULT,
    EXPORT_AUTO_SAVE_ENABLED_KEY,
    EXPORT_BILLING_FILENAME_TMPL_DEFAULT,
    EXPORT_BILLING_FILENAME_TMPL_KEY,
    EXPORT_DATE_FORMAT_DEFAULT,
    EXPORT_DATE_FORMAT_KEY,
    EXPORT_OUTPUT_DIR_DEFAULT,
    EXPORT_OUTPUT_DIR_KEY,
    get_setting,
)
from arichds.db.billing_query import closed_periods_with_record_no
from arichds.db.models import BillingReading, Device
from arichds.db.session import session_scope
from arichds.export.format import (
    BILLING_EXPORT_HEADERS,
    BILLING_FIELDS,
    file_header_block,
    format_billing_rows,
    render_filename,
)
from arichds.export.writer import append_rows, head_changed, replace_rows

logger = logging.getLogger(__name__)

#: The label this file's header block carries, matching the customer's samples.
_FILE_LABEL = "Billing"

_LOG_LABEL = "Billing export"

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


@dataclass(frozen=True)
class BillingExportResult:
    """What one call to :func:`export_device_billing` did.

    Attributes:
        rows_written: How many periods were appended. Zero for every
            hold/skip/failure case — never an exception.
        path: The resolved target file, or ``None`` when the call held or
            failed before a path existed.
    """

    rows_written: int
    path: Path | None


def _device_lock(device_id: int) -> threading.Lock:
    """The one lock guarding *device_id*'s billing export, created on first use.

    Its own registry rather than the Load Profile export's: the two write
    different files, so serialising them against each other would make a slow
    Load Profile export delay a billing one for no reason. A device's billing
    export still cannot race itself — the scheduler job and "Save now" queue
    here.
    """
    with _locks_guard:
        lock = _locks.get(device_id)
        if lock is None:
            lock = threading.Lock()
            _locks[device_id] = lock
        return lock


def export_device_billing(device_id: int, *, require_auto_save: bool) -> BillingExportResult:
    """Append *device_id*'s unexported closed billing periods to its file.

    Args:
        device_id: The device to export.
        require_auto_save: When True (the scheduler job), a machine whose
            ``export_auto_save_enabled`` setting is off is held with zero rows
            written. When False ("Save now"), the switch is ignored — pressing
            a button already expresses intent.

    Returns:
        How many periods were appended and the resolved target path. Never
        raises for a hold, a write failure or an allowlist rejection: each is
        zero rows written, logged, with the watermark left alone so the periods
        retry on the next call.
    """
    with _device_lock(device_id):
        return _export_locked(device_id, require_auto_save=require_auto_save)


def _export_locked(device_id: int, *, require_auto_save: bool) -> BillingExportResult:
    with session_scope() as session:
        if require_auto_save:
            enabled = get_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, EXPORT_AUTO_SAVE_ENABLED_DEFAULT) == "true"
            if not enabled:
                return BillingExportResult(rows_written=0, path=None)

        output_dir_str = get_setting(session, EXPORT_OUTPUT_DIR_KEY, EXPORT_OUTPUT_DIR_DEFAULT).strip()
        if not output_dir_str:
            return BillingExportResult(rows_written=0, path=None)

        date_format = get_setting(session, EXPORT_DATE_FORMAT_KEY, EXPORT_DATE_FORMAT_DEFAULT)
        filename_tmpl = get_setting(session, EXPORT_BILLING_FILENAME_TMPL_KEY, EXPORT_BILLING_FILENAME_TMPL_DEFAULT)

        device = session.get(Device, device_id)
        if device is None:
            logger.warning("%s: device_id=%d not found — skipping", _LOG_LABEL, device_id)
            return BillingExportResult(rows_written=0, path=None)

        # The file is named by the sanitized serial; an undiscovered serial is
        # the normal early state (ADR 0005), so this holds quietly.
        if not device.meter_serial:
            return BillingExportResult(rows_written=0, path=None)
        try:
            meter_token = sanitize_meter_serial(device.meter_serial)
        except ValueError:
            logger.warning("%s: unsafe meter token for device_id=%d — skipping", _LOG_LABEL, device_id)
            return BillingExportResult(rows_written=0, path=None)

        try:
            resolved_output_dir = validate_directory_setting(
                output_dir_str, get_settings().capture_allowlist_roots(), setting_name="output_dir"
            )
        except ValueError:
            logger.warning("%s: export_output_dir invalid for device_id=%d — skipping", _LOG_LABEL, device_id)
            return BillingExportResult(rows_written=0, path=None)

        final_path = resolved_output_dir / render_filename(filename_tmpl, meter_token)
        header_block = file_header_block(
            customer=device.customer, site_name=device.site_name, meter_serial=meter_token, file_label=_FILE_LABEL
        )

        # ADR 0023 (ticket 02) — a head that no longer matches what is on disk
        # is rewritten in place with **every** closed period, atomically,
        # instead of M13's roll to a dated edition. Bypasses the watermark
        # deliberately: a rewrite must reproduce the file's whole current
        # content, not just the periods a stale watermark still calls
        # pending — `closed_periods_with_record_no` already numbers every
        # period from the whole series, so `record_no` is unaffected by
        # whether a period was already exported once before.
        if head_changed(final_path, header_block, BILLING_EXPORT_HEADERS):
            full_rows, full_watermark = _full_window_rows(session, device_id, date_format=date_format)
            written = replace_rows(
                final_path,
                header_block=header_block,
                header_row=BILLING_EXPORT_HEADERS,
                rows=full_rows,
                allowlist=[resolved_output_dir],
                label=_LOG_LABEL,
            )
            if not written:
                return BillingExportResult(rows_written=0, path=final_path)
            device.billing_exported_through = full_watermark
            session.commit()
            return BillingExportResult(rows_written=len(full_rows), path=final_path)

        watermark = device.billing_exported_through
        watermark = _as_utc(watermark) if watermark is not None else None

        stmt = closed_periods_with_record_no(device_id)
        if watermark is not None:
            stmt = stmt.where(BillingReading.bill_date > watermark)

        results = session.execute(stmt).all()
        if not results:
            return BillingExportResult(rows_written=0, path=None)

        rows = [
            {**{field: getattr(reading, field) for field in BILLING_FIELDS}, "record_no": record_no}
            for reading, record_no in results
        ]
        formatted = format_billing_rows(rows, date_format=date_format)

        # The head has already been confirmed to match (or the file is new) —
        # see the `head_changed` branch above (ticket 02, ADR 0023).
        written = append_rows(
            final_path,
            header_block=header_block,
            header_row=BILLING_EXPORT_HEADERS,
            rows=formatted,
            allowlist=[resolved_output_dir],
            label=_LOG_LABEL,
        )
        if not written:
            return BillingExportResult(rows_written=0, path=final_path)

        device.billing_exported_through = _as_utc(results[-1][0].bill_date)
        session.commit()
        return BillingExportResult(rows_written=len(formatted), path=final_path)


def _full_window_rows(session: Session, device_id: int, *, date_format: str) -> tuple[list[list[str]], datetime | None]:
    """Every closed period this device has — the whole series
    :func:`~arichds.db.billing_query.closed_periods_with_record_no` returns,
    with no watermark filter — what a head-change rewrite writes (ticket 02,
    ADR 0023). Billing is never purged from our store (ADR 0009), so this is
    the file's whole window, not a 90-day slice.

    Returns:
        The formatted rows, oldest first, and the newest ``bill_date`` among
        them (what the caller sets as the watermark), or ``([], None)`` when
        the device has no closed period at all.
    """
    results = session.execute(closed_periods_with_record_no(device_id)).all()
    if not results:
        return [], None
    rows = [
        {**{field: getattr(reading, field) for field in BILLING_FIELDS}, "record_no": record_no}
        for reading, record_no in results
    ]
    formatted = format_billing_rows(rows, date_format=date_format)
    return formatted, _as_utc(results[-1][0].bill_date)


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; every stored ``bill_date`` is UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = ["BillingExportResult", "export_device_billing"]
