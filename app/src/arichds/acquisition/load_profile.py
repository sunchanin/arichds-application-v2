"""The load-profile read job (M5a-1, issue #15) and its cycle (M5a-2, issue #16).

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
* **The watermark is per ``(device, logger)``** (ADR 0008's own Decision,
  implemented rather than reversed at M4c, issue #24). The read is now genuinely
  per-logger — :meth:`~arichds.acquisition.drivers.base.MeterDriver.read_load_profile`
  takes a ``logger_id`` and returns one profile's rows — so each logger walks
  from its own watermark inside one connection, ascending
  (:meth:`~arichds.acquisition.drivers.base.MeterDriver.load_profile_loggers`
  order). A logger with no stored rows backfills its own 90 days rather than
  inheriting a sibling's watermark; a stalled logger no longer holds another
  logger's window open. This replaces the earlier "minimum of the per-logger
  maxima" compromise, which the driver interface at the time could not do
  better than.

**This job never touches device status** (D11, ADR 0004): status comes from the
Poller and from nothing else. A failed load-profile read is a log line and,
later, a gap on the Records page — never a strike against the meter.

**Two callers, one read path, two priorities.** :func:`read_and_store_load_profile`
is what Read now presses, and :func:`load_profile_cycle` is the same call in a
loop over every device that should be read — the ``load_profile`` entry in
:func:`arichds.jobs.scheduler.default_jobs`. Which devices those are (enabled,
not Offline) is decided in the cycle, because it is a property of *the sweep*,
not of a read: pressing Read now on an Offline device must still read it.

The one thing that differs between the two is **how the Transport Endpoint is
taken**. Read now is a Manual Read: it waits, and it outranks background work.
The cycle passes ``background=True`` and gives the line up at once when anything
else holds it — a walk can hold an endpoint for a full budget, and a person whose
Read now blocks behind an invisible background sweep is the exact cost ADR 0006
priced and refused. A skip loses nothing: the watermark makes the next cycle
resume from the same place (ADR 0008).

The scheduler thread itself and Limited Mode are **not here**: they are
:mod:`arichds.jobs.scheduler`, which stops the thread when the license lapses,
so this module needs no license check of its own.
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
from arichds.acquisition.status import DeviceStatus
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
        skipped: True when a **background** read gave the Transport Endpoint up
            rather than queue for it (ADR 0006). Not a failure and never an
            ``error``: nothing was asked of the meter, nothing was lost, and the
            next cycle reads it from the same watermark. Only the background
            path can set it, so Read now never sees it.
    """

    supported: bool
    stored: int
    through: datetime | None
    budget_exhausted: bool
    error: str | None
    # Defaulted so every existing construction — and `api/devices.py`, which
    # renders the Read now modal — needs no change.
    skipped: bool = False


def read_and_store_load_profile(
    device_id: int,
    *,
    locks: EndpointLocks | None = None,
    lock_timeout_sec: float = MANUAL_READ_LOCK_TIMEOUT_SEC,
    budget_sec: float = LOAD_PROFILE_READ_BUDGET_SEC,
    now: datetime | None = None,
    background: bool = False,
) -> LoadProfileReadResult:
    """Read one device's load profile from its watermark to *now* and store it.

    Takes the Transport Endpoint lock **once** and holds it for the whole walk
    with a single connection. Releasing between chunks would force a
    re-association per chunk and buy nothing.

    **Which lock, and why it is the caller's business.** A person pressing Read
    now is a Manual Read: it waits for the endpoint and is granted it ahead of
    background work (ADR 0006). The Scheduler's cycle is background work and
    takes the other path — it gives the endpoint up at once rather than queue,
    because a walk can hold a line for a full :data:`LOAD_PROFILE_READ_BUDGET_SEC`
    and a person waiting behind invisible background work is precisely the cost
    ADR 0006 refuses to pay. Priority is a property of *the request*, which is
    why it is a parameter here and not a branch inside the lock.

    Args:
        device_id: The device to read. It must exist — the caller resolved it.
        locks: Lock registry. Defaults to the process-wide one, which is the
            registry the Poller and every other Manual Read use.
        lock_timeout_sec: How long to wait for the Transport Endpoint. Ignored
            when *background* is set — that path never waits.
        budget_sec: How long the whole walk may keep going. Checked **before
            starting each chunk except the first**: a DLMS read cannot be
            interrupted mid-flight, and a call that reads nothing at all makes
            no progress against the watermark.
        now: The upper bound of the window, timezone-aware UTC. A parameter so
            a test drives the walk without a clock.
        background: Take the endpoint on the background path — never blocking,
            skipping the device when the line is busy. The default is False so
            Read now keeps exactly the behaviour it has always had.

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
            #
            # DEBUG on the background path: such a row sits at `unknown`, which
            # the cycle deliberately does not skip, so a WARNING here would be
            # ~96 identical lines a day forever. The Poller met the same case and
            # made the same call — one line per start, not one per tick. A person
            # pressing Read now still gets the WARNING *and* the sentence below.
            logger.log(
                logging.DEBUG if background else logging.WARNING,
                "Load profile skipped for device %s: %s",
                device_name,
                exc,
            )
            return LoadProfileReadResult(
                supported=False, stored=0, through=None, budget_exhausted=False, error=str(exc)
            )

    if not driver.supports_load_profile():
        logger.debug("Device %s (%s) has no load profile — nothing to read", device_name, driver.model_name)
        return LoadProfileReadResult(
            supported=False, stored=0, through=_through(device_id), budget_exhausted=False, error=None
        )

    # Every logger's own start, computed once up front (D3) — each backfills
    # its own 90 days if it has never been read, rather than inheriting a
    # sibling logger's watermark.
    # DB only — the meter is not touched here. A logger with no watermark maps
    # to None ("backfill"), and where that backfill starts is decided under the
    # Transport Endpoint lock in `_walk_every_logger`, because deciding it costs
    # a read.
    with session_scope() as session:
        per_logger_start = {
            logger_id: _watermark(session, device_id, logger_id) for logger_id in driver.load_profile_loggers()
        }

    endpoint = driver.endpoint
    stored = 0
    budget_exhausted = False
    error: str | None = None

    if background:
        # Never blocks, and never preempts what is in flight. A tick that cannot
        # have the endpoint is *skipped*, and the watermark means the skip costs
        # one cycle rather than any data (ADR 0006 + ADR 0008).
        with registry.get(endpoint).background() as acquired:
            if not acquired:
                logger.info("Skipping the load profile of %s — %s is busy", device_name, endpoint)
                return LoadProfileReadResult(
                    supported=True,
                    stored=0,
                    through=_through(device_id),
                    budget_exhausted=False,
                    # NOT an error: nothing was asked of the meter. Reporting a
                    # skip as a failure is how a busy line would come to look
                    # like a broken one (poller.py's SKIPPED-is-not-FAILED).
                    error=None,
                    skipped=True,
                )
            stored, budget_exhausted, error = _read_while_holding(
                driver, device_id, device_name, endpoint, per_logger_start, now_utc, budget_sec
            )
    else:
        try:
            with registry.get(endpoint).manual(timeout=lock_timeout_sec):
                stored, budget_exhausted, error = _read_while_holding(
                    driver, device_id, device_name, endpoint, per_logger_start, now_utc, budget_sec
                )
        except TimeoutError as exc:
            # Reachable from the manual path only — ``background()`` yields False
            # instead of raising. A TimeoutError from the meter is already a
            # sentence below. The line, not the meter (``probe.py`` draws the
            # same distinction).
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


def _read_while_holding(
    driver: MeterDriver,
    device_id: int,
    device_name: str,
    endpoint: str,
    per_logger_start: dict[int, datetime | None],
    now_utc: datetime,
    budget_sec: float,
) -> tuple[int, bool, str | None]:
    """Connect once, walk every logger's window, disconnect — the endpoint
    already held for the whole visit (D3, M4c issue #24).

    Extracted so the two acquisition paths differ **only** in how they take the
    lock: the read itself must not depend on who asked for it, or the priority
    rule would quietly become a second code path through the meter.

    Returns:
        ``(rows stored across every logger, whether any logger's walk hit the
        shared budget, the first error sentence encountered or None)``.
    """
    try:
        driver.connect()
    except Exception as exc:  # noqa: BLE001 — every meter failure becomes a sentence, never a 500.
        logger.exception("Load profile read of %s at %s failed to connect", device_name, endpoint)
        return 0, False, f"The read of {endpoint} stopped after a {type(exc).__name__}."
    else:
        # `_walk` returns its own error rather than raising: a failure on chunk
        # three must still report the two chunks already committed, and an
        # exception unwinding past here would lose that count.
        return _walk_every_logger(driver, device_id, device_name, endpoint, per_logger_start, now_utc, budget_sec)
    finally:
        driver.disconnect()


def _walk_every_logger(
    driver: MeterDriver,
    device_id: int,
    device_name: str,
    endpoint: str,
    per_logger_start: dict[int, datetime | None],
    now_utc: datetime,
    budget_sec: float,
) -> tuple[int, bool, str | None]:
    """Walk every logger in :meth:`~arichds.acquisition.drivers.base.MeterDriver.load_profile_loggers`
    order, ascending, all inside one Transport Endpoint acquisition.

    **One budget for the whole visit, not one per logger** (D3) — the budget
    exists to bound how long the endpoint is held, which is a property of the
    visit, not of any one profile. Each logger's own first chunk is still let
    through regardless of the deadline (the same "checked before starting each
    chunk except the first" rule :func:`_walk` already applies within a
    logger), so a logger can always make progress against its own watermark
    even if an earlier logger already spent the whole budget.

    Returns:
        ``(rows stored across every logger, whether any logger's walk hit the
        budget, the first error sentence encountered or None)``.
    """
    deadline = time.monotonic() + budget_sec
    total_stored = 0
    budget_exhausted = False
    error: str | None = None

    for logger_id in driver.load_profile_loggers():
        watermark = per_logger_start[logger_id]
        start = watermark if watermark is not None else _backfill_start(driver, logger_id, device_name, now_utc)
        stored, exhausted, logger_error = _walk(
            driver, device_id, device_name, endpoint, logger_id, start, now_utc, deadline
        )
        total_stored += stored
        budget_exhausted = budget_exhausted or exhausted
        if error is None:
            error = logger_error

    return total_stored, budget_exhausted, error


def load_profile_cycle() -> None:
    """Read the load profile of every device that should be read, once (issue #16).

    The Scheduler's ``load_profile`` job — see
    :func:`arichds.jobs.scheduler.default_jobs`. It takes no arguments on
    purpose: the registry entry is one line, and everything this needs
    (the process-wide locks, the real clock, the standard budget) is
    :func:`read_and_store_load_profile`'s own default.

    **Two filters, and no others** (D5). ``enabled`` is the operator pausing a
    device. ``status != offline`` is narrower than it looks: a dead meter would
    otherwise burn a full read timeout every single cycle for nothing
    (SPEC §3.5). ``unknown`` is deliberately **not** skipped — a device is
    unknown until its first Poller tick, and stranding its 90-day backfill behind
    the Poller's cadence would buy nothing. A device that recovers needs no code
    here at all: the Poller keeps ticking it (ADR 0004), ``record_success``
    writes ``online``, the next cycle's query includes it again, and the
    watermark pulls in everything missed during the outage (ADR 0008).

    **It never writes device status** — not on success, not on failure, not even
    ``status_checked_at``. Status has exactly one source (ADR 0004) and a failed
    load-profile read is a log line here and, at M5b, a gap on the Records page.

    The walk is sequential: the Transport Endpoint lock already serialises
    anything sharing a line, so reading devices concurrently would buy
    contention rather than throughput. One device's failure never stops the
    next — :func:`read_and_store_load_profile` returns meter failures as a
    sentence rather than raising, and the guard below catches the rest.

    **Every read here is background work** (``background=True``): a device whose
    line is busy is skipped and read next cycle, never queued behind a person
    (ADR 0006, and CLAUDE.md's invariant in as many words).
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
            # background=True: this is a sweep, not a person. A busy endpoint
            # means skip this device and read it next cycle (ADR 0006).
            read_and_store_load_profile(device_id, background=True)
        except Exception:  # noqa: BLE001 — one device must never strand the rest of the site.
            # Meter failures do not arrive here at all: they come back as a
            # sentence in the result. What does arrive is the ValueError from a
            # device deleted between the query above and its turn in the walk —
            # and anything unforeseen, which on a site nobody can log into must
            # cost one device rather than the whole cycle.
            logger.exception("Load profile cycle failed for device id %s", device_id)


def _backfill_start(driver: MeterDriver, logger_id: int, device_name: str, now_utc: datetime) -> datetime:
    """Where a logger with no watermark should start — never earlier than the
    meter's own buffer.

    **Called with the Transport Endpoint held and the driver connected**, because
    it asks the meter a question (`_walk_every_logger`, not
    `read_and_store_load_profile`).

    The bug this closes: `_walk` steps `LOAD_PROFILE_CHUNK_HOURS` at a time from
    `now - LOAD_PROFILE_BACKFILL_DAYS`, stops on `LOAD_PROFILE_READ_BUDGET_SEC`,
    and **keeps no memory of where it stopped** — by design, because the
    watermark is the data (ADR 0008). That is self-healing only while the walk
    reaches a row before the budget runs out. A SMART TCC on serial 9600 holding
    ~22 h of buffer needs 90 chunks to reach its first row and gets through
    fewer, so nothing is stored, so the watermark stays None, so the next cycle
    re-walks the same empty ninety days. It sat at zero rows for three hours
    that way, one identical re-walk per cycle, and Read now reported `0 rows`
    for the same reason.

    Clamping to the meter's oldest entry turns that into a single chunk. A meter
    that really holds the whole window answers with a time about 90 days old and
    nothing changes. A driver that cannot answer returns None (the base default)
    and keeps today's behaviour exactly.

    Never returns a time in the future or beyond the full window — a meter
    reporting a nonsense clock must not be able to *narrow* the walk to nothing.
    """
    floor = now_utc - timedelta(days=LOAD_PROFILE_BACKFILL_DAYS)
    try:
        oldest = driver.load_profile_oldest_reading(logger_id)
    except Exception:  # noqa: BLE001 — an optional hint must never break the read it optimises.
        logger.exception(
            "Could not read %s logger %d's oldest entry — backfilling the full window", device_name, logger_id
        )
        return floor

    if oldest is None or not (floor < oldest < now_utc):
        return floor

    logger.info(
        "Backfill of %s logger %d starts at %s, not %s — the meter's buffer begins there",
        device_name,
        logger_id,
        oldest.isoformat(),
        floor.isoformat(),
    )
    return oldest


def _walk(
    driver: MeterDriver,
    device_id: int,
    device_name: str,
    endpoint: str,
    logger_id: int,
    start: datetime,
    end: datetime,
    deadline: float,
) -> tuple[int, bool, str | None]:
    """Fetch and store one logger's ``[start, end]`` in chunks, oldest first.

    *deadline* is a shared ``time.monotonic()`` instant, not a per-logger
    budget (D3, M4c issue #24) — the caller computes it once for the whole
    visit. Checked before starting each chunk **except this logger's first**:
    a DLMS read cannot be interrupted mid-flight, a call that reads nothing at
    all makes no progress against this logger's own watermark, and letting
    every logger's first chunk through is what stops an earlier logger from
    starving a later one even when the shared budget is already spent.

    A failing chunk **ends this logger's walk and is reported**, never
    raised: the chunks already committed are real rows, and the count of them
    is what the operator is told. The watermark heals the rest on the next
    call.

    Returns:
        ``(rows stored, whether the deadline stopped this logger's walk, an
        error sentence or None)``.
    """
    chunk = timedelta(hours=LOAD_PROFILE_CHUNK_HOURS)
    chunk_start = start
    stored = 0
    first = True

    while chunk_start < end:
        if not first and time.monotonic() >= deadline:
            logger.info(
                "Load profile walk of %s logger %d stopped on the shared budget at %s — history remains",
                device_name,
                logger_id,
                chunk_start.isoformat(),
            )
            return stored, True, None

        chunk_end = min(chunk_start + chunk, end)
        try:
            readings = driver.read_load_profile(logger_id, chunk_start, chunk_end)
            stored += _store(device_id, readings)
        except Exception as exc:  # noqa: BLE001 — every failure becomes a sentence, never a 500.
            logger.exception(
                "Load profile read of %s logger %d at %s failed on the chunk starting %s",
                device_name,
                logger_id,
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


def _per_logger_watermarks(session, device_id: int) -> dict[int, datetime]:  # noqa: ANN001 — a Session, typed by its only caller.
    """``{logger_id: MAX(read_at)}`` for every logger this device has stored
    rows for (D3/D4, M4c issue #24) — the one source :func:`_watermark` and
    :func:`_through` both derive from, so the two can never disagree.

    The grouping is over **stored** rows, so a logger that has never been read
    is simply absent from the result rather than dragging anything to
    ``None`` — that absence is exactly what lets that logger's own 90-day
    backfill happen (the fix this issue's D3 makes).
    """
    rows = session.execute(
        select(LoadProfileReading.logger_id, func.max(LoadProfileReading.read_at))
        .where(LoadProfileReading.device_id == device_id)
        .group_by(LoadProfileReading.logger_id)
    ).all()
    # SQLite hands back naive datetimes; the driver requires timezone-aware UTC
    # and everything in this table is UTC by the normalization contract.
    return {logger_id: read_at.replace(tzinfo=UTC) for logger_id, read_at in rows}


def _watermark(session, device_id: int, logger_id: int) -> datetime | None:  # noqa: ANN001 — a Session, typed by its only caller.
    """Return this logger's own ``MAX(read_at)``, or ``None`` when it has never
    been read (D3) — the fix for the gap this module's docstring used to warn
    about: a logger seen for the first time gets its own full backfill rather
    than inheriting a sibling logger's watermark.
    """
    return _per_logger_watermarks(session, device_id).get(logger_id)


def _through(device_id: int) -> datetime | None:
    """The MINIMUM of this device's per-logger ``MAX(read_at)`` (D4).

    Shown to a person as "Stored N Interval Readings up to X UTC"
    (``api/devices.py``). A device-wide ``MAX`` would over-report coverage
    while a stalled logger sat behind — the exact failure mode ADR 0008 exists
    to prevent — so this reports the laggard's own progress, not the leader's.
    On every single-logger model this equals the device-wide MAX, so nothing
    observable changes for those models; it only becomes visible on a
    multi-logger model (M4c).
    """
    with session_scope() as session:
        per_logger = _per_logger_watermarks(session, device_id)
    return min(per_logger.values()) if per_logger else None
