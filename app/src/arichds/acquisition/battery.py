"""The battery read job (M7-2, issue #29) — the hourly scheduler job that
fills ``battery_readings``.

**Background only. There is no Manual Read path** (D5) — SPEC §3.7 makes
battery a registry job because the value is the trend, not the minute.
:func:`read_and_store_battery` therefore takes the endpoint with
``.background()`` and has no ``background`` parameter: one caller, one
priority (mirrors :mod:`arichds.acquisition.energy_registers`'s inverse —
that job is Manual-Read-only).

**The interval is one hour, and the reason lives at the lock**
(``locks.py::PriorityEndpointLock.try_acquire_background`` — read its
docstring). A background tick that cannot have the Transport Endpoint is
*skipped, never queued* (ADR 0006): a daily job that collides once with the
load-profile cycle or a person pressing Read now on a shared line loses the
whole day, with no second attempt. Hourly, combined with the day-guard in
:func:`battery_cycle` below, gives 24 chances at **exactly the same number of
meter reads** as a daily job — no retry logic, no scheduler state. Do not
"simplify" this back to daily; that would silently delete the retry.

**A failed read writes no row; a successful read that yields ``None`` does**
(D4) — the single most important interaction in this module. If a failed
read wrote a row, the day-guard below would suppress the remaining 23
retries and destroy the entire reason for the hourly cadence. So: connect or
read raised -> log, no row, retried next hour. Read returned ``None`` (the
meter answered with nothing) -> store a row with ``status = NULL``, which
counts as today's row and is **not** retried — parity with v1
(``storage_service.py:281`` / ``battery_reader.py:122-125``).

**The day-guard lives in the cycle, not in the per-device function** (D3),
mirroring :func:`~arichds.acquisition.billing.billing_cycle`'s own split:
``battery_cycle()`` decides *which devices to read*; ``read_and_store_battery``
means "read this device now". "Today" is the UTC calendar day, judged
against ``read_at`` (D2) — plumbing, not a reported figure, so no
``METER_LOCAL_UTC_OFFSET_HOURS`` shift applies here.

**Never touches device status** (ADR 0004) — a skipped, failed, or
unsupported battery read is a log line, exactly like the load-profile and
billing jobs.

**A meter that keeps failing is one WARNING per device per day, not an ERROR
with a traceback per cycle** (ui-audit ticket 04). The first real install
logged a full traceback every hour for two meters whose firmware simply lacks
the register — noise that would bury a real fault. The last failure per device
is kept in memory (:func:`last_battery_failure`) so the Battery page can say
why a meter has no rows; nothing is persisted (ADR 0008) and it resets on
restart, which is the same shape ``dataout/status.py`` chose.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select

from arichds.acquisition.drivers.base import MeterDriver
from arichds.acquisition.locks import EndpointLocks, endpoint_locks
from arichds.acquisition.poller import build_driver
from arichds.acquisition.status import DeviceStatus
from arichds.db.models import BatteryReading as BatteryReadingRow
from arichds.db.models import Device
from arichds.db.session import session_scope

logger = logging.getLogger(__name__)

#: v1 parity — the column width ``battery_readings.status`` is truncated to
#: (D8). A module constant here, not read off the ORM column, because the
#: writer needs it before it ever touches a Session.
_STATUS_MAX_LEN = 20


@dataclass(frozen=True)
class BatteryFailure:
    """The last failed battery read of one device — in memory only.

    Attributes:
        at: When the read failed (UTC).
        reason: The failure's class and text — the meter's own sentence,
            never a password (the exception text comes from Gurux, not from
            our connection parameters).
        warned_on: The UTC calendar day a WARNING was last emitted for this
            device — the same day the cycle's day-guard uses (D2).
    """

    at: datetime
    reason: str
    warned_on: date


_failures: dict[int, BatteryFailure] = {}


def last_battery_failure(device_id: int) -> BatteryFailure | None:
    """The last failed read of *device_id* since the service started, or None
    when its last read succeeded (or none has run). Read by
    ``GET /api/battery`` so the page can name the reason a meter has no rows."""
    return _failures.get(device_id)


def reset_battery_failures() -> None:
    """Forget every remembered failure — for tests, which share one process."""
    _failures.clear()


def _record_failure(device_id: int, device_name: str, endpoint: str, exc: BaseException, now_utc: datetime) -> None:
    """Remember the failure and log it **once per device per UTC day** as a
    WARNING with the reason and no traceback; every further failure that day
    is a DEBUG line. The next hourly retry is the day-guard's business."""
    reason = f"{type(exc).__name__}: {exc}"
    previous = _failures.get(device_id)
    today = now_utc.date()
    if previous is None or previous.warned_on != today:
        logger.warning(
            "Battery read of %s at %s failed: %s — retried hourly; one warning per device per day",
            device_name,
            endpoint,
            reason,
        )
        warned_on = today
    else:
        logger.debug("Battery read of %s at %s failed again: %s", device_name, endpoint, reason)
        warned_on = previous.warned_on
    _failures[device_id] = BatteryFailure(at=now_utc, reason=reason, warned_on=warned_on)


@dataclass(frozen=True)
class BatteryReadResult:
    """What one call to :func:`read_and_store_battery` did.

    Attributes:
        supported: False when this device's driver has no battery status
            register at all, or could not be built. Nothing was read and no
            lock was taken.
        row_id: The stored row's id, or None when nothing was written
            (unsupported, skipped, or the read failed).
        error: An operator-facing sentence, or None. Never contains a
            password.
        skipped: True when the Transport Endpoint was busy and this
            background tick gave it up rather than queue for it (ADR 0006).
            Not a failure and never an ``error``.
    """

    supported: bool
    row_id: int | None
    error: str | None
    skipped: bool = False


def read_and_store_battery(
    device_id: int,
    *,
    locks: EndpointLocks | None = None,
    now: datetime | None = None,
) -> BatteryReadResult:
    """Read one device's battery status and store it — background only (D5).

    Args:
        device_id: The device to read. It must exist — the caller resolved
            it.
        locks: Lock registry. Defaults to the process-wide one.
        now: When *we* read it — timezone-aware UTC, stamped on the row
            written this call. A parameter so a test drives the write
            without a clock. The Scheduler's own call never passes this.

    Returns:
        What happened, including a sentence for the operator when it failed.

    Raises:
        ValueError: If *device_id* does not exist.
    """
    now_utc = datetime.now(UTC) if now is None else now
    registry = endpoint_locks() if locks is None else locks

    with session_scope() as session:
        device = session.get(Device, device_id)
        if device is None:
            raise ValueError(f"No device with id {device_id}")
        device_name = device.name
        try:
            driver = build_driver(device)
        except ValueError as exc:
            logger.debug("Battery read skipped for device %s: %s", device_name, exc)
            return BatteryReadResult(supported=False, row_id=None, error=str(exc))

    if not driver.supports_battery():
        logger.debug("Device %s (%s) has no battery status register — nothing to read", device_name, driver.model_name)
        return BatteryReadResult(supported=False, row_id=None, error=None)

    endpoint = driver.endpoint
    with registry.get(endpoint).background() as acquired:
        if not acquired:
            logger.info("Skipping battery read of %s — %s is busy", device_name, endpoint)
            return BatteryReadResult(supported=True, row_id=None, error=None, skipped=True)
        row_id, error = _read_while_holding(driver, device_id, device_name, endpoint, now_utc)

    return BatteryReadResult(supported=True, row_id=row_id, error=error)


def _read_while_holding(
    driver: MeterDriver,
    device_id: int,
    device_name: str,
    endpoint: str,
    read_at: datetime,
) -> tuple[int | None, str | None]:
    """Connect, read the status, disconnect — with the endpoint already held.

    Returns:
        ``(the stored row's id, or None if the read failed; an error
        sentence, or None on success)``.
    """
    try:
        driver.connect()
    except Exception as exc:  # noqa: BLE001 — every meter failure becomes a sentence, never a 500.
        _record_failure(device_id, device_name, endpoint, exc, read_at)
        return None, f"The read of {endpoint} stopped after a {type(exc).__name__}."

    try:
        # A raised exception here must NOT reach `_store` — a failed read
        # writes no row at all (D4), so the write only happens once the read
        # has actually returned a value (including None).
        status = driver.read_battery_status()
        row_id = _store(device_id, status, read_at, device_name)
    except Exception as exc:  # noqa: BLE001
        _record_failure(device_id, device_name, endpoint, exc, read_at)
        return None, f"The read of {endpoint} stopped after a {type(exc).__name__}."
    finally:
        driver.disconnect()

    _failures.pop(device_id, None)
    return row_id, None


def _store(device_id: int, status: str | None, read_at: datetime, device_name: str) -> int:
    """Insert one battery reading row. ``status`` is truncated to the column
    width and warned about, rather than truncated silently (D8)."""
    if status is not None and len(status) > _STATUS_MAX_LEN:
        logger.warning(
            "Battery status for device %s truncated from %d to %d chars: %r",
            device_name,
            len(status),
            _STATUS_MAX_LEN,
            status,
        )
        status = status[:_STATUS_MAX_LEN]

    with session_scope() as session:
        row = BatteryReadingRow(device_id=device_id, read_at=read_at, status=status)
        session.add(row)
        session.flush()
        return row.id


def battery_cycle() -> None:
    """Read the battery status of every device that should be read, once
    this hour (M7-2, issue #29).

    The Scheduler's ``battery`` job — see
    :func:`arichds.jobs.scheduler.default_jobs`. Takes no arguments: the
    registry entry is one line.

    **Same two device filters as the load-profile and billing cycles, and
    no others** (D3): ``Device.enabled`` is the operator pausing a device,
    ``status != OFFLINE`` avoids burning a read on a meter already known
    dead, and ``unknown`` is deliberately **not** skipped.

    **The day-guard**: a device that already has a ``battery_readings`` row
    stamped today (UTC calendar day, D2) is skipped — that row, successful
    or a stored ``NULL``, is this hour's answer already. A device whose only
    row is *not* from today is read again, which is what lets a failed read
    retry on the very next hourly pass (D4).

    Sequential, one device's failure never stops the next — mirrors
    :func:`arichds.acquisition.billing.billing_cycle` exactly.
    """
    now_utc = datetime.now(UTC)
    today_start = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=UTC)

    with session_scope() as session:
        device_ids = list(
            session.scalars(
                select(Device.id)
                .where(Device.enabled.is_(True), Device.status != DeviceStatus.OFFLINE)
                .order_by(Device.id)
            )
        )
        already_read_today = set(
            session.scalars(select(BatteryReadingRow.device_id).where(BatteryReadingRow.read_at >= today_start))
        )

    for device_id in device_ids:
        if device_id in already_read_today:
            continue
        try:
            read_and_store_battery(device_id)
        except Exception:  # noqa: BLE001 — one device must never strand the rest of the site.
            logger.exception("Battery cycle failed for device id %s", device_id)
