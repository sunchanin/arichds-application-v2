"""The load-profile read job (M5a-1, issue #15).

One call reads a device's load profile from where the stored data ends up to
now, in chunks, and writes each chunk before fetching the next. Everything it
needs to know about "how far did we get" comes from
``load_profile_readings`` itself — **there is no job table** (ADR 0008), and
adding one, or a ``read_end`` column, or any second place that answers that
question, reverses that decision rather than extending it.

Three rules shape the walk, and each is load-bearing:

* **Oldest first.** Fetching today first would move ``MAX(read_at)`` to today,
  the next cycle would start from today, and the 90 days behind it would never
  be read. That permanent gap is the whole reason ADR 0008 exists.
* **The window starts *at* the watermark, not after it.** The driver's filter is
  inclusive on both bounds, so the boundary row is re-read and upserted. One
  row's worth of work, bought deliberately: a half-written boundary heals
  instead of becoming a hole.
* **The watermark is the MINIMUM of the per-logger maxima** (D6). ADR 0008
  defines it per ``(device, logger)``, but the driver's read is not per-logger —
  ``read_load_profile(start, end)`` returns whatever loggers it reads. A
  device-wide ``MAX`` would start the walk after the *leading* logger and skip
  the lagging one forever. Taking the minimum over-fetches for the leading
  logger, and over-fetching is free because the write is an upsert.

**This job never touches device status** (D11, ADR 0004): status comes from the
Poller and from nothing else. A failed load-profile read is a log line and,
later, a gap on the Records page — never a strike against the meter.

The scheduler thread, the job registry, skipping Offline devices and Limited
Mode behaviour are **not here**: they are M5a-2 (issue #16). Today the one
caller is Read now.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from arichds.acquisition.drivers.base import IntervalReading, MeterDriver
from arichds.acquisition.locks import EndpointLocks, endpoint_locks
from arichds.acquisition.poller import build_driver
from arichds.constants import (
    LOAD_PROFILE_BACKFILL_DAYS,
    LOAD_PROFILE_CHUNK_HOURS,
    LOAD_PROFILE_READ_BUDGET_SEC,
    MANUAL_READ_LOCK_TIMEOUT_SEC,
)
from arichds.db.models import Device, LoadProfileReading
from arichds.db.session import session_scope

logger = logging.getLogger(__name__)

#: The row's identity. Never in the ``ON CONFLICT`` update set — updating a
#: conflict target is meaningless, and ``created_at`` stays out too so a row
#: keeps saying when it first arrived (D10).
_CONFLICT_KEYS = ("device_id", "logger_id", "read_at")


@dataclass(frozen=True)
class LoadProfileReadResult:
    """What one call to :func:`read_and_store_load_profile` did.

    Attributes:
        supported: False when this device's driver has no load profile at all,
            or could not be built. Nothing was read and no lock was taken.
        stored: How many Interval Readings were written — inserts and overwrites
            alike, because from the operator's side both are "the meter's answer
            is now in the table".
        through: The highest ``read_at`` now stored for this device, or None if
            it still has no rows. Read back off the table rather than taken from
            the window that was asked for — that difference is exactly v1's
            seven-hour gap (ADR 0008).
        budget_exhausted: True when the walk stopped with history still to fetch.
            Pressing Read now again continues from the data.
        error: An operator-facing sentence, or None. Never contains a password.
    """

    supported: bool
    stored: int
    through: datetime | None
    budget_exhausted: bool
    error: str | None


def read_and_store_load_profile(
    device_id: int,
    *,
    locks: EndpointLocks | None = None,
    lock_timeout_sec: float = MANUAL_READ_LOCK_TIMEOUT_SEC,
    budget_sec: float = LOAD_PROFILE_READ_BUDGET_SEC,
    now: datetime | None = None,
) -> LoadProfileReadResult:
    """Read one device's load profile from its watermark to *now* and store it.

    Takes the Transport Endpoint lock **once**, as a Manual Read (ADR 0006), and
    holds it for the whole walk with a single connection. Releasing between
    chunks would force a re-association per chunk and buy nothing: a background
    tick that cannot have the endpoint is skipped, never queued.

    Args:
        device_id: The device to read. It must exist — the caller resolved it.
        locks: Lock registry. Defaults to the process-wide one, which is the
            registry the Poller and every other Manual Read use.
        lock_timeout_sec: How long to wait for the Transport Endpoint.
        budget_sec: How long the whole walk may keep going. Checked **before
            starting each chunk except the first**: a DLMS read cannot be
            interrupted mid-flight, and a call that reads nothing at all makes
            no progress against the watermark.
        now: The upper bound of the window, timezone-aware UTC. A parameter so
            a test drives the walk without a clock.

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
            # Not a meter failure — nothing was asked of the meter.
            logger.warning("Load profile skipped for device %s: %s", device_name, exc)
            return LoadProfileReadResult(
                supported=False, stored=0, through=None, budget_exhausted=False, error=str(exc)
            )
        watermark = _watermark(session, device_id)

    if not driver.supports_load_profile():
        logger.debug("Device %s (%s) has no load profile — nothing to read", device_name, driver.model_name)
        return LoadProfileReadResult(
            supported=False, stored=0, through=_through(device_id), budget_exhausted=False, error=None
        )

    start = watermark if watermark is not None else now_utc - timedelta(days=LOAD_PROFILE_BACKFILL_DAYS)
    endpoint = driver.endpoint
    stored = 0
    budget_exhausted = False
    error: str | None = None

    try:
        with registry.get(endpoint).manual(timeout=lock_timeout_sec):
            try:
                driver.connect()
            except Exception as exc:  # noqa: BLE001 — every meter failure becomes a sentence, never a 500.
                logger.exception("Load profile read of %s at %s failed to connect", device_name, endpoint)
                error = f"The read of {endpoint} stopped after a {type(exc).__name__}."
            else:
                # `_walk` returns its own error rather than raising: a failure on
                # chunk three must still report the two chunks already committed,
                # and an exception unwinding past here would lose that count.
                stored, budget_exhausted, error = _walk(
                    driver, device_id, device_name, endpoint, start, now_utc, budget_sec
                )
            finally:
                driver.disconnect()
    except TimeoutError as exc:
        # Only ``manual()`` can raise here — a TimeoutError from the meter is
        # already a sentence above. The line, not the meter (``probe.py`` draws
        # the same distinction).
        logger.warning("Load profile read of %s skipped: %s busy", device_name, endpoint)
        error = f"The line to {endpoint} was still busy after {lock_timeout_sec:g}s — nothing was read."
        _ = exc

    return LoadProfileReadResult(
        supported=True,
        stored=stored,
        through=_through(device_id),
        budget_exhausted=budget_exhausted,
        error=error,
    )


def _walk(
    driver: MeterDriver,
    device_id: int,
    device_name: str,
    endpoint: str,
    start: datetime,
    end: datetime,
    budget_sec: float,
) -> tuple[int, bool, str | None]:
    """Fetch and store ``[start, end]`` in chunks, oldest first.

    A failing chunk **ends the walk and is reported**, never raised: the chunks
    already committed are real rows, and the count of them is what the operator
    is told. The watermark heals the rest on the next call.

    Returns:
        ``(rows stored, whether the budget stopped the walk, an error sentence
        or None)``.
    """
    deadline = time.monotonic() + budget_sec
    chunk = timedelta(hours=LOAD_PROFILE_CHUNK_HOURS)
    chunk_start = start
    stored = 0
    first = True

    while chunk_start < end:
        if not first and time.monotonic() >= deadline:
            logger.info(
                "Load profile walk of %s stopped on its %gs budget at %s — history remains",
                device_name,
                budget_sec,
                chunk_start.isoformat(),
            )
            return stored, True, None

        chunk_end = min(chunk_start + chunk, end)
        try:
            readings = driver.read_load_profile(chunk_start, chunk_end)
            stored += _store(device_id, readings)
        except Exception as exc:  # noqa: BLE001 — every failure becomes a sentence, never a 500.
            logger.exception(
                "Load profile read of %s at %s failed on the chunk starting %s",
                device_name,
                endpoint,
                chunk_start.isoformat(),
            )
            return stored, False, f"The read of {endpoint} stopped after a {type(exc).__name__}."
        chunk_start = chunk_end
        first = False

    return stored, False, None


def _store(device_id: int, readings: list[IntervalReading]) -> int:
    """Upsert one chunk's rows in its own unit of work, and return how many.

    Committed before the caller fetches the next chunk, so a link that drops
    mid-walk keeps everything already fetched (ADR 0008).
    """
    if not readings:
        return 0

    values = [
        {
            "device_id": device_id,
            "read_at": reading.read_at,
            "source": reading.source,
            "logger_id": reading.logger_id,
            "interval_sec": reading.interval_sec,
            **reading.as_columns(),
        }
        for reading in readings
    ]
    statement = sqlite_insert(LoadProfileReading)
    statement = statement.on_conflict_do_update(
        index_elements=list(_CONFLICT_KEYS),
        # Derived from the row the driver actually produced rather than listed
        # by hand, so a column M4c adds to `IntervalReading` is overwritten too
        # without anyone remembering to come back here.
        set_={key: statement.excluded[key] for key in values[0] if key not in _CONFLICT_KEYS},
    )
    with session_scope() as session:
        session.execute(statement, values)
    return len(values)


def _watermark(session, device_id: int) -> datetime | None:  # noqa: ANN001 — a Session, typed by its only caller.
    """Return the MINIMUM of this device's per-logger ``MAX(read_at)``, or None.

    See the module docstring for why the minimum: a device-wide ``MAX`` would
    start the walk after the leading logger and strand the lagging one.

    The grouping is over **stored** rows, so a logger that has never been read
    contributes no group and does not drag the watermark back to ``None``. The
    consequence, accepted with D6 and worth knowing at M4c: if a driver starts
    returning a second logger *after* the first has been read for a while, that
    logger's history behind the shared watermark is not fetched. No model in the
    build today has a second logger, and the fix is a per-logger read interface —
    which must be designed against a model that actually has two, not against
    this one.
    """
    per_logger = (
        select(func.max(LoadProfileReading.read_at).label("logger_max"))
        .where(LoadProfileReading.device_id == device_id)
        .group_by(LoadProfileReading.logger_id)
        .subquery()
    )
    value = session.scalar(select(func.min(per_logger.c.logger_max)))
    # SQLite hands back a naive datetime; the driver requires timezone-aware UTC
    # and everything in this table is UTC by the normalization contract.
    return value.replace(tzinfo=UTC) if value is not None else None


def _through(device_id: int) -> datetime | None:
    """The highest ``read_at`` now stored for this device — read back, not assumed."""
    with session_scope() as session:
        value = session.scalar(
            select(func.max(LoadProfileReading.read_at)).where(LoadProfileReading.device_id == device_id)
        )
    return value.replace(tzinfo=UTC) if value is not None else None
