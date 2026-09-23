"""The **Capture Sweep** (CONTEXT.md) — what **Save all** runs (capture-sweep
ticket 04, grill 2026-09-23).

Every closed Billing Reading whose PDF is not in the current Billing Folder
gets its Capture — every device in id order, Paused ones included, periods
newest first, every format the licence allows — and every device's Billing
Export File is rewritten first. It runs on the Scheduler's one-shot lane in
**slices** of at most :data:`~arichds.constants.CAPTURE_SWEEP_SLICE_SEC`: after
the capture that crosses the budget the slice re-queues itself, so the regular
jobs (the fifteen-minute load-profile pass above all) run between slices and a
meter read is never delayed by a folder being filled.

**The folder is the state** (ADR 0008). Nothing persists which periods were
swept: each slice rebuilds its work list by asking the folder, exactly as the
download path's render-on-miss does, so a restart mid-sweep leaves nothing to
clean up and the next Save all simply writes what is still missing. What the
process does remember, in memory only and only for the sweep in flight, is
the periods that failed this sweep — so a period that cannot be written is
logged and counted once rather than retried every slice — and whether the
billing files were already written. A file that exists is never rewritten
(the ``O_EXCL`` write in :mod:`arichds.capture.write` stays); "missing" is the
PDF's absence, so a period whose PDF exists but whose xlsx or PNG does not is
done here and left to the download path, one document at a time, as today.

The progress a person sees — :class:`SweepStatus` — is one in-memory slot in
the shape :mod:`arichds.fileupload.status` uses, ``None`` until the first
Save all since start.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from sqlalchemy import select

from arichds.capture.service import capture_reading, capture_target_paths
from arichds.config import get_settings
from arichds.constants import CAPTURE_SWEEP_SLICE_SEC
from arichds.db.app_settings import (
    CAPTURE_DIR_DEFAULT,
    CAPTURE_DIR_KEY,
    DISPLAY_UNIT_SCALE_DEFAULT,
    DISPLAY_UNIT_SCALE_KEY,
    get_setting,
)
from arichds.db.models import BillingReading as BillingReadingRow
from arichds.db.models import Device
from arichds.db.session import session_scope
from arichds.export.billing_csv import export_device_billing
from arichds.licensing.current import current_license_service
from arichds.licensing.features import feature_enabled

logger = logging.getLogger(__name__)

#: What the one-shot is called in the Scheduler's logs.
SWEEP_JOB_NAME = "capture_sweep"


class RunSoon(Protocol):
    """The one method of the Scheduler a sweep needs — its one-shot lane."""

    def run_soon(self, name: str, fn: Callable[[], None]) -> None: ...


@dataclass(frozen=True, slots=True)
class SweepStatus:
    """The sweep in flight, or the last one since start.

    Attributes:
        running: Whether a slice is queued or executing.
        started_at: When Save all was pressed, UTC.
        finished_at: When the last slice found nothing left, UTC; ``None``
            while running.
        billing_files_written: Devices whose Billing Export File was
            rewritten with at least one closed period.
        captures_written: Captures written by this sweep so far.
        captures_left: Periods still without a PDF when the last slice
            ended — the next slice's work.
        captures_failed: Periods whose capture raised this sweep; logged,
            skipped for the rest of the sweep, retried by the next Save all.
    """

    running: bool
    started_at: datetime
    finished_at: datetime | None = None
    billing_files_written: int = 0
    captures_written: int = 0
    captures_left: int = 0
    captures_failed: int = 0


_lock = threading.Lock()
_status: SweepStatus | None = None
#: Working memory for the sweep in flight only — never status, never persisted.
_billing_done = False
_failed_ids: set[int] = set()


def sweep_status() -> SweepStatus | None:
    """The sweep in flight or the last one since start — ``None`` before the first."""
    with _lock:
        return _status


def reset_sweep_status() -> None:
    """Forget everything — what a restart does; for tests."""
    global _status, _billing_done  # noqa: PLW0603 — one process-wide slot, same shape as fileupload/status.py
    with _lock:
        _status = None
        _billing_done = False
        _failed_ids.clear()


def _publish(**changes: object) -> SweepStatus:
    global _status  # noqa: PLW0603
    with _lock:
        assert _status is not None
        _status = replace(_status, **changes)  # type: ignore[arg-type]
        return _status


def start_capture_sweep(scheduler: RunSoon) -> Literal["started", "already_running"]:
    """Queue the first slice, unless a sweep is already in flight.

    Pressed while running it says so and queues nothing (grill Q7) — the
    page's button is loading whenever the status says running, so a second
    press is a race, not an intent.
    """
    global _status, _billing_done  # noqa: PLW0603
    with _lock:
        if _status is not None and _status.running:
            return "already_running"
        _status = SweepStatus(running=True, started_at=datetime.now(UTC))
        _billing_done = False
        _failed_ids.clear()
    scheduler.run_soon(SWEEP_JOB_NAME, lambda: run_sweep_slice(scheduler))
    return "started"


@dataclass(frozen=True, slots=True)
class _Target:
    device_id: int
    device_name: str
    reading_id: int


def _missing_targets(session: object, capture_dir: Path) -> list[_Target]:
    """Every closed period with no PDF in *capture_dir* — devices in id
    order, periods newest first (bill date descending, sequence ascending,
    the PNG window's own order) — minus the periods that already failed this
    sweep. A period with no stored Meter Serial, or one the serial cannot name
    a folder for, has no document to be missing (the eager path skips it the
    same way)."""
    rows = session.execute(  # type: ignore[attr-defined]
        select(BillingReadingRow, Device.name)
        .join(Device, BillingReadingRow.device_id == Device.id)
        .where(BillingReadingRow.record_status.is_(None))
        .order_by(Device.id, BillingReadingRow.bill_date.desc(), BillingReadingRow.sequence.asc())
    ).all()
    targets: list[_Target] = []
    for row, device_name in rows:
        if row.id in _failed_ids or row.meter_serial is None:
            continue
        try:
            pdf_target, _xlsx, _png = capture_target_paths(
                capture_dir, row.meter_serial, row.bill_date, sequence=row.sequence
            )
        except ValueError:
            continue
        if pdf_target.exists():
            continue
        targets.append(_Target(device_id=row.device_id, device_name=device_name, reading_id=row.id))
    return targets


def run_sweep_slice(
    scheduler: RunSoon,
    *,
    budget_sec: float = CAPTURE_SWEEP_SLICE_SEC,
    clock: Callable[[], float] = time.monotonic,
) -> SweepStatus:
    """One slice: the billing files (first slice only), then captures until
    the budget is crossed or nothing is missing. Re-queues itself on
    *scheduler* when work remains; publishes progress after every capture.

    *budget_sec* and *clock* are seams for tests — the product always calls
    this with the defaults, through :func:`start_capture_sweep`.
    """
    global _billing_done  # noqa: PLW0603
    deadline = clock() + budget_sec
    settings = get_settings()
    license_service = current_license_service()

    with session_scope() as session:
        capture_dir_str = get_setting(session, CAPTURE_DIR_KEY, CAPTURE_DIR_DEFAULT).strip()
        scale = get_setting(session, DISPLAY_UNIT_SCALE_KEY, DISPLAY_UNIT_SCALE_DEFAULT)
        device_ids = list(session.scalars(select(Device.id).order_by(Device.id)))
    if not capture_dir_str:
        # The endpoint refuses before queueing; an admin who emptied the folder
        # between slices simply ends the sweep — there is no folder to fill.
        return _finish()
    capture_dir = Path(capture_dir_str)

    if not _billing_done:
        written = 0
        for device_id in device_ids:
            try:
                result = export_device_billing(device_id, require_auto_save=False)
            except Exception:  # noqa: BLE001 — one device's file must not end the sweep for the others.
                logger.exception("Save all: billing file for device_id=%d failed", device_id)
                continue
            if result.path is not None and result.rows_written:
                written += 1
        _billing_done = True
        _publish(billing_files_written=written)

    if not feature_enabled("auto_capture", license_service=license_service, settings=settings):
        return _finish()  # no capture may be written on this licence — the billing files were the whole job
    write_excel = feature_enabled("billing_excel_export", license_service=license_service, settings=settings)
    write_image = feature_enabled("billing_image_export", license_service=license_service, settings=settings)

    with session_scope() as session:
        targets = _missing_targets(session, capture_dir)

    for index, target in enumerate(targets):
        left = len(targets) - index - 1
        try:
            with session_scope() as session:
                row = session.get(BillingReadingRow, target.reading_id)
                if row is None:
                    continue
                capture_reading(
                    row, target.device_name, capture_dir, write_excel=write_excel, write_image=write_image, scale=scale
                )
                # Stamped only once the document exists — the same rule the
                # eager path keeps (ui-audit ticket 03).
                row.captured_at = datetime.now(UTC)
            status = _bump("captures_written", left)
        except Exception:  # noqa: BLE001 — one period must never end the sweep; logged, counted, skipped for this sweep.
            logger.exception("Save all: capture failed for %s reading id %s", target.device_name, target.reading_id)
            _failed_ids.add(target.reading_id)
            status = _bump("captures_failed", left)
        if left and clock() >= deadline:
            scheduler.run_soon(SWEEP_JOB_NAME, lambda: run_sweep_slice(scheduler))
            return status
    return _finish()


def _bump(field: str, left: int) -> SweepStatus:
    with _lock:
        assert _status is not None
        current = getattr(_status, field)
    return _publish(**{field: current + 1, "captures_left": left})


def _finish() -> SweepStatus:
    status = _publish(running=False, finished_at=datetime.now(UTC), captures_left=0)
    logger.info(
        "Save all finished: %d billing file(s), %d capture(s) written, %d failed",
        status.billing_files_written,
        status.captures_written,
        status.captures_failed,
    )
    return status


__all__ = [
    "SWEEP_JOB_NAME",
    "RunSoon",
    "SweepStatus",
    "reset_sweep_status",
    "run_sweep_slice",
    "start_capture_sweep",
    "sweep_status",
]
