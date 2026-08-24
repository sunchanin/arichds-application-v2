"""The billing read job (M6a, issue #21) — ADR 0009's one read path.

**One function, one caller shape, two priorities** — :func:`read_and_store_billing`
is what Read now presses and what :func:`billing_cycle` (the Scheduler's
``billing`` entry in :func:`arichds.jobs.scheduler.default_jobs`) calls once
per device on a fixed daily interval. Shaped on
:mod:`arichds.acquisition.load_profile` — same signature idea, same lock
discipline, same two callers — but the read *mechanism* is different, and so
is the write:

* **Every read is the whole buffer** (ADR 0009). There is no window, no
  watermark, and therefore no "Backfill" left as a concept: a device with no
  stored rows and a device read yesterday are read identically.
* **Closed periods dedupe on ``(device_id, bill_date)`` and are never
  rewritten.** A ``bill_date`` seen before with a *different* value is skipped
  and logged, never overwritten — stored history is not something a later read
  gets to correct (ADR 0009's "Consequences": ``Delete all data`` is the only
  way to repair a wrong value, and it is a repair tool for values that were
  wrong on *our* side, not the meter's).
* **The Open Period is one row per device, found by ``record_status``, never
  by ``bill_date``** — its Bill Date advances on every read, which is the
  entire reason the slot exists (CONTEXT.md — Open Period).
* **Closed periods land before the open slot moves**, so a month rollover
  reads correctly in a single pass: the just-closed period exists as its own
  row before the slot is repointed at the new running period.

**This job never touches device status, never a strike** (ADR 0004) — a
failed billing read is a log line, exactly as the load-profile job is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from arichds.acquisition.drivers.base import BillingReading, MeterDriver
from arichds.acquisition.locks import EndpointLocks, endpoint_locks
from arichds.acquisition.poller import build_driver
from arichds.acquisition.status import DeviceStatus
from arichds.capture.service import capture_reading
from arichds.config import get_settings
from arichds.constants import MANUAL_READ_LOCK_TIMEOUT_SEC
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
from arichds.licensing.current import current_license_service
from arichds.licensing.features import feature_enabled

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BillingReadResult:
    """What one call to :func:`read_and_store_billing` did.

    Attributes:
        supported: False when this device's driver has no billing profile at
            all, or could not be built. Nothing was read and no lock was taken.
        stored: How many **closed** periods were newly inserted. Re-reading an
            already-stored period, or the Open Period slot moving, does not
            count here.
        open_updated: Whether the device's Open Period slot was inserted or
            changed by this read.
        error: An operator-facing sentence, or None. Never contains a password.
        skipped: True when a **background** read gave the Transport Endpoint
            up rather than queue for it (ADR 0006). Not a failure and never an
            ``error``. Only the background path can set it.
    """

    supported: bool
    stored: int
    open_updated: bool
    error: str | None
    skipped: bool = False


def read_and_store_billing(
    device_id: int,
    *,
    locks: EndpointLocks | None = None,
    lock_timeout_sec: float = MANUAL_READ_LOCK_TIMEOUT_SEC,
    now: datetime | None = None,
    background: bool = False,
) -> BillingReadResult:
    """Read one device's whole billing buffer and store it (ADR 0009).

    Takes the Transport Endpoint lock **once** for the single round trip a
    billing read is — thirteen rows is one read, not a walk, so there is no
    budget parameter here the way :func:`~arichds.acquisition.load_profile.read_and_store_load_profile`
    has one.

    **Which lock, and why it is the caller's business.** Same rule as the
    load-profile job: a person pressing Read now is a Manual Read and waits
    for the endpoint (ADR 0006); the Scheduler's cycle is background work and
    gives the endpoint up at once when it is busy, never queuing.

    Args:
        device_id: The device to read. It must exist — the caller resolved it.
        locks: Lock registry. Defaults to the process-wide one.
        lock_timeout_sec: How long a Manual Read waits for the Transport
            Endpoint. Ignored when *background* is set.
        now: When *we* read it — timezone-aware UTC, stamped on every row
            written this call. A parameter so a test drives the write without
            a clock.
        background: Take the endpoint on the background path — never
            blocking, skipping the device when the line is busy.

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
            # A model with no driver, or a stored transport nothing can parse.
            # Not a meter failure — nothing was asked of the meter. Same log
            # split as the load-profile job: DEBUG on the background sweep
            # (one line per start, not one per device per day forever),
            # WARNING for a person pressing Read now.
            logger.log(
                logging.DEBUG if background else logging.WARNING,
                "Billing skipped for device %s: %s",
                device_name,
                exc,
            )
            return BillingReadResult(supported=False, stored=0, open_updated=False, error=str(exc))

    if not driver.supports_billing():
        logger.debug("Device %s (%s) has no billing profile — nothing to read", device_name, driver.model_name)
        return BillingReadResult(supported=False, stored=0, open_updated=False, error=None)

    endpoint = driver.endpoint
    stored = 0
    open_updated = False
    error: str | None = None
    new_closed_ids: list[int] = []

    if background:
        # Never blocks, and never preempts what is in flight (ADR 0006).
        with registry.get(endpoint).background() as acquired:
            if not acquired:
                logger.info("Skipping billing of %s — %s is busy", device_name, endpoint)
                return BillingReadResult(supported=True, stored=0, open_updated=False, error=None, skipped=True)
            stored, open_updated, new_closed_ids, error = _read_while_holding(
                driver, device_id, device_name, endpoint, now_utc
            )
    else:
        try:
            with registry.get(endpoint).manual(timeout=lock_timeout_sec):
                stored, open_updated, new_closed_ids, error = _read_while_holding(
                    driver, device_id, device_name, endpoint, now_utc
                )
        except TimeoutError as exc:
            logger.warning("Billing read of %s skipped: %s busy", device_name, endpoint)
            error = f"The line to {endpoint} was still busy after {lock_timeout_sec:g}s — nothing was read."
            _ = exc

    # Outside the Transport Endpoint lock and after the rows committed (SPEC
    # §3.6, decision 11) — capture is eager but must never make a meter read
    # wait on a network share, and must never hold the endpoint a moment
    # longer than the read itself needs it.
    if new_closed_ids:
        _capture_new_closed_periods(new_closed_ids, device_name)

    return BillingReadResult(supported=True, stored=stored, open_updated=open_updated, error=error)


def _read_while_holding(
    driver: MeterDriver,
    device_id: int,
    device_name: str,
    endpoint: str,
    read_at: datetime,
) -> tuple[int, bool, list[int], str | None]:
    """Connect, read the whole buffer, disconnect — with the endpoint already held.

    Returns:
        ``(closed periods inserted, whether the open slot changed, the ids of
        newly-inserted closed rows, an error sentence or None)``.
    """
    try:
        driver.connect()
    except Exception as exc:  # noqa: BLE001 — every meter failure becomes a sentence, never a 500.
        logger.exception("Billing read of %s at %s failed to connect", device_name, endpoint)
        return 0, False, [], f"The read of {endpoint} stopped after a {type(exc).__name__}."

    try:
        # The store runs in the same try as the read (unlike load_profile.py's
        # chunked `_walk`, which has a separate reason to split them — a
        # failing chunk there must still report the chunks already committed).
        # A billing read is one round trip with nothing partial to preserve,
        # so a write-side failure is exactly as much "the read stopped" as a
        # meter failure is, and must become the same kind of sentence rather
        # than an unhandled exception reaching the API or `billing_cycle`'s
        # per-device guard.
        readings = driver.read_billing()
        stored, open_updated, new_closed_ids = _store(device_id, device_name, readings, read_at)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Billing read of %s at %s failed", device_name, endpoint)
        return 0, False, [], f"The read of {endpoint} stopped after a {type(exc).__name__}."
    finally:
        driver.disconnect()

    return stored, open_updated, new_closed_ids, None


def _capture_new_closed_periods(reading_ids: list[int], device_name: str) -> None:
    """Render and write captures for newly-inserted closed periods (decision
    11, SPEC §3.6, issue #22).

    Called after the Transport Endpoint lock is released and after the rows
    committed — capture never holds the endpoint and never blocks a meter
    read. Gated on ``auto_capture`` (PDF) — the outer gate on the whole eager
    path, so with it off nothing is written regardless of the other two
    flags — with ``billing_excel_export`` (xlsx) and ``billing_image_export``
    (PNG, M7 slice 4, issue #35, D3) checked alongside it, all fresh through
    the process-wide LicenseService holder (:mod:`arichds.licensing.current`)
    — this path has no ``Request``, unlike
    :func:`~arichds.api.deps.require_feature`.

    A capture failure is logged and never propagates: a meter read that
    succeeded must not be reported as failed because a network share was
    unavailable or a row went missing between commit and this call.
    """
    settings = get_settings()
    license_service = current_license_service()
    if not feature_enabled("auto_capture", license_service=license_service, settings=settings):
        return

    with session_scope() as session:
        capture_dir_str = get_setting(session, CAPTURE_DIR_KEY, CAPTURE_DIR_DEFAULT)
        display_unit_scale = get_setting(session, DISPLAY_UNIT_SCALE_KEY, DISPLAY_UNIT_SCALE_DEFAULT)
    if not capture_dir_str.strip():
        logger.debug("Capture skipped for %s — capture_dir is not configured", device_name)
        return

    capture_dir = Path(capture_dir_str)
    write_excel = feature_enabled("billing_excel_export", license_service=license_service, settings=settings)
    write_image = feature_enabled("billing_image_export", license_service=license_service, settings=settings)

    for reading_id in reading_ids:
        try:
            with session_scope() as session:
                row = session.get(BillingReadingRow, reading_id)
                if row is None:
                    continue
                capture_reading(
                    row,
                    device_name,
                    capture_dir,
                    write_excel=write_excel,
                    write_image=write_image,
                    scale=display_unit_scale,
                )
        except Exception:  # noqa: BLE001 — capture must never fail the read that produced the row.
            logger.exception("Capture failed for %s reading id %s", device_name, reading_id)


def billing_change_check(driver: MeterDriver, device_id: int) -> bool:
    """The Billing Change Check (ADR 0018, corrected by issue #43's D1/D2) —
    decides whether the whole-buffer billing read should run this Load
    Profile tick.

    Called only from inside :func:`~arichds.acquisition.load_profile._read_while_holding`,
    on an already-connected driver, on the **background** path only (D7) —
    never a second association, and never from a Manual Read.

    **The signal is the newest CLOSED period's bill date, not the newest
    entry's** (D1): the newest entry is the Open Period on every model this
    product reads today, and its Bill Date advances on every single read
    (CONTEXT.md — Open Period) — comparing against it would trigger the
    whole-buffer read on every tick, exactly the cost this check exists to
    avoid.

    **Compared on `device_id` alone, never `(device, meter_serial)`** (D2):
    both driver read paths store ``meter_serial=None`` when the serial
    register read fails after the buffer was already read
    (`_dlms_profile.py`, `smw110.py`), so a serial filter would exclude
    legitimately stored rows, `MAX` would come back `NULL` forever, and this
    check would fire a full read every cycle.

    **`entriesInUse` is read by the driver but is never this function's
    signal** (D13) — it saturates once a ring is full
    (`docs/meter-notes/smw110w4-scan.md:71`, a billing ring reaches its own
    ceiling after roughly a year on this fleet); the newest closed
    `bill_date` cannot saturate the same way, and this function has no
    visibility into `entriesInUse` at all — it only ever asks the driver for
    a `bill_date`.

    Returns:
        True when the whole-buffer read should run: nothing is stored for
        this device yet (D4 — a freshly added device gets its billing inside
        one cycle rather than waiting up to a day), or the newest closed
        period the meter reports differs from the newest closed period
        already stored (D3 — exact inequality, never ``>``: a buffer that
        moved *backwards* is still worth re-reading, and the whole-buffer
        write path is idempotent). Any failure — an unsupported driver, an
        unreadable buffer, a DB error — is logged and swallowed, returning
        False: the daily full read stays the backstop (D9).
    """
    try:
        newest_closed = driver.billing_newest_closed_bill_date()
    except Exception:  # noqa: BLE001 — D9: an optional trigger must never break the walk it rides on.
        logger.exception(
            "Billing change check failed for device id %s — the daily read stays the only signal", device_id
        )
        return False

    if newest_closed is None:
        return False

    try:
        with session_scope() as session:
            stored_newest = session.scalar(
                select(func.max(BillingReadingRow.bill_date)).where(
                    BillingReadingRow.device_id == device_id,
                    # D2 — device_id alone, and D1's "closed only": the Open
                    # Period slot's bill_date advances on every read and must
                    # never win this MAX.
                    BillingReadingRow.record_status.is_(None),
                )
            )
    except Exception:  # noqa: BLE001 — same rule, the DB side of the check.
        logger.exception("Billing change check's stored lookup failed for device id %s", device_id)
        return False

    if stored_newest is None:
        # D4 — nothing stored yet: trigger, so a freshly added device gets
        # its billing inside one Load Profile cycle rather than waiting up
        # to a day. Accepted degenerate case: if the whole-buffer read this
        # triggers persistently stores nothing (a driver bug, a malformed
        # buffer), this branch re-triggers every single LP cycle — bounded
        # at one full read per cycle, no worse than a naive fifteen-minute
        # billing job would cost, and now attributable in the log line
        # below rather than a silent repeat.
        logger.info(
            "Billing change check: device id %s has no stored closed period yet "
            "(meter's newest closed: %s) — triggering the whole-buffer read",
            device_id,
            newest_closed.isoformat(),
        )
        return True

    # SQLite hands back naive datetimes; every row in this table is UTC by
    # the normalization contract (module docstring).
    stored_newest = stored_newest.replace(tzinfo=UTC)
    changed = newest_closed != stored_newest  # D3 — != not >.
    if changed:
        # The only line that says the feature is doing anything at all on an
        # ordinary tick — without it an operator has no way to tell a
        # triggered read from a coincidentally-scheduled daily one.
        logger.info(
            "Billing change check: device id %s's newest closed period changed "
            "(meter: %s, stored: %s) — triggering the whole-buffer read",
            device_id,
            newest_closed.isoformat(),
            stored_newest.isoformat(),
        )
    return changed


def billing_cycle() -> None:
    """Read the billing buffer of every device that should be read, once (M6a).

    The Scheduler's ``billing`` job — see
    :func:`arichds.jobs.scheduler.default_jobs`. Takes no arguments: the
    registry entry is one line, and everything this needs (the process-wide
    locks, the real clock) is :func:`read_and_store_billing`'s own default.

    **Same two filters as the load-profile cycle, and no others** (D5 /
    ADR 0009's own "one read path" reasoning applied to the sweep): ``enabled``
    is the operator pausing a device, ``status != offline`` avoids burning a
    full read timeout on a meter already known dead, and ``unknown`` is
    deliberately **not** skipped.

    **It never writes device status.** A failed billing read is a log line
    here, never a strike (ADR 0004) — only ``liveness`` touches status.

    Sequential, one device's failure never stops the next — mirrors
    :func:`arichds.acquisition.load_profile.load_profile_cycle` exactly.
    """
    with session_scope() as session:
        device_ids = list(
            session.scalars(
                select(Device.id)
                .where(Device.enabled.is_(True), Device.status != DeviceStatus.OFFLINE)
                .order_by(Device.id)
            )
        )

    for device_id in device_ids:
        try:
            read_and_store_billing(device_id, background=True)
        except Exception:  # noqa: BLE001 — one device must never strand the rest of the site.
            logger.exception("Billing cycle failed for device id %s", device_id)


def _store(
    device_id: int, device_name: str, readings: list[BillingReading], read_at: datetime
) -> tuple[int, bool, list[int]]:
    """Write the whole buffer in one unit of work: closed periods first, then
    the Open Period slot — the newly closed period must exist before the slot
    moves off it (ADR 0009).

    Returns:
        ``(closed periods inserted, whether the open slot changed, the ids of
        newly-inserted closed rows — plain ints, not ORM objects, since
        ``session_scope()`` closes below and the eager capture path re-reads
        them fresh (decision 11, issue #22))``.
    """
    if not readings:
        return 0, False, []

    closed = [reading for reading in readings if not reading.is_open]
    open_reading = next((reading for reading in readings if reading.is_open), None)

    stored = 0
    new_closed_ids: list[int] = []
    with session_scope() as session:
        for reading in closed:
            new_id = _upsert_closed(session, device_id, device_name, reading, read_at)
            if new_id is not None:
                stored += 1
                new_closed_ids.append(new_id)

        open_updated = False
        if open_reading is not None:
            open_updated = _upsert_open(session, device_id, open_reading, read_at)

    return stored, open_updated, new_closed_ids


def _upsert_closed(
    session,  # noqa: ANN001 — a Session, typed by its only caller.
    device_id: int,
    device_name: str,
    reading: BillingReading,
    read_at: datetime,
) -> int | None:
    """Insert a closed period if absent; skip and WARN if it exists with a
    different value; silent no-op if it exists and matches exactly.

    Returns:
        The new row's id if one was inserted, else None.
    """
    existing = session.scalar(
        select(BillingReadingRow).where(
            BillingReadingRow.device_id == device_id,
            BillingReadingRow.bill_date == reading.bill_date,
            BillingReadingRow.record_status.is_(None),
        )
    )
    incoming = reading.as_columns()

    if existing is None:
        row = BillingReadingRow(
            device_id=device_id,
            bill_date=reading.bill_date,
            read_at=read_at,
            record_status=None,
            source=reading.source,
            meter_serial=reading.meter_serial,
            **incoming,
        )
        session.add(row)
        # Flushed (not committed) so `row.id` is populated before
        # `session_scope()` closes — the caller hands the id, not the row
        # itself, up to the eager capture path.
        session.flush()
        return row.id

    # Exact comparison, no tolerance: both sides are round-tripped SQLite REALs
    # of the same computation, and None == None must count as equal.
    if any(getattr(existing, key) != value for key, value in incoming.items()):
        logger.warning(
            "Billing period for device %s at bill_date %s is already stored with a different value — "
            "skipping (stored history is never rewritten)",
            device_name,
            reading.bill_date.isoformat(),
        )
    return None


def _upsert_open(
    session,  # noqa: ANN001 — a Session, typed by its only caller.
    device_id: int,
    reading: BillingReading,
    read_at: datetime,
) -> bool:
    """Update the device's Open Period slot in place, or insert it if absent.

    Found by ``(device_id, record_status='open')`` — never by ``bill_date``,
    which advances on every read (CONTEXT.md — Open Period).

    Returns:
        True — the slot always changes when the driver reported an open row.
    """
    slot = session.scalar(
        select(BillingReadingRow).where(
            BillingReadingRow.device_id == device_id, BillingReadingRow.record_status == "open"
        )
    )
    incoming = reading.as_columns()

    if slot is None:
        session.add(
            BillingReadingRow(
                device_id=device_id,
                bill_date=reading.bill_date,
                read_at=read_at,
                record_status="open",
                source=reading.source,
                meter_serial=reading.meter_serial,
                **incoming,
            )
        )
    else:
        slot.bill_date = reading.bill_date
        slot.read_at = read_at
        slot.meter_serial = reading.meter_serial
        for key, value in incoming.items():
            setattr(slot, key, value)
    return True
