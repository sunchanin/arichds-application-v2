"""The daily retention job — 90 days of rows, and nothing older (M5c, issue #19).

SPEC §5: ``load_profile_readings`` is cut on ``read_at`` and ``device_events`` on
``created_at``, both at :data:`~arichds.constants.RETENTION_DAYS`. Nothing else
expires here — ``billing_readings`` (M6a, issue #21) is deliberately excluded:
ADR 0009 says a closed period is never rewritten once stored, and the only way
to remove one is ``Delete all data`` on the Devices page, not a daily purge.
``user_tokens`` needs no job either, because :mod:`arichds.auth.service` purges
expired tokens on every login.

It lives under ``db/`` rather than ``acquisition/`` because it reads no meter,
builds no driver and takes no Transport Endpoint lock: its domain is the rows.

**Nothing here records that it ran.** ADR 0008 forbids persisted job state of any
kind, so the one INFO line below is the entire history of a purge — which is why
it names both counts rather than saying "done".

**Retention cannot move the load-profile watermark**, and that is arithmetic
rather than luck: this deletes the *oldest* rows, while the watermark is ``MIN``
over the per-logger ``MAX(read_at)`` (``acquisition/load_profile.py``) — the
*newest*. When a device has been offline past the cutoff and loses every row, the
``GROUP BY`` produces no groups, the watermark is ``None``, and the next read
backfills from :data:`~arichds.constants.LOAD_PROFILE_BACKFILL_DAYS` back. That
is the correct outcome, not a gap.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import InstrumentedAttribute

from arichds.constants import RETENTION_DAYS, RETENTION_DELETE_BATCH_SIZE
from arichds.db.models import DeviceEvent, LoadProfileReading
from arichds.db.session import session_scope

logger = logging.getLogger(__name__)


def purge_expired(*, now: datetime | None = None, batch_size: int = RETENTION_DELETE_BATCH_SIZE) -> None:
    """Delete every row past its retention window, in batches.

    The Scheduler's ``retention`` job — see
    :func:`arichds.jobs.scheduler.default_jobs`. It takes no arguments in
    production: both keyword parameters exist so a test drives it without a clock
    and without seeding millions of rows, the same reason ``now`` exists on
    :func:`arichds.acquisition.load_profile.read_and_store_load_profile`.

    **Device Events go uniformly** — a status transition the machine wrote and an
    operator action carrying a username are both just rows past the cutoff. The
    owner chose that simplicity knowing the cost (SPEC §5): after 90 days there is
    no record of who paused a meter or cleared its data either.

    Nothing is caught here. A failure belongs to the Scheduler's guard, which logs
    it and runs the job again tomorrow; a bare ``except`` at this level would turn
    a real schema bug into a log line nobody acts on.

    Args:
        now: The instant the cutoff is measured back from, timezone-aware UTC.
            Defaults to the real clock. The comparison is strictly ``<``, so a row
            landing exactly on the cutoff instant is kept.
        batch_size: How many rows one DELETE statement removes. Each batch is its
            own unit of work, so SQLite's write lock is released between them and
            the Poller and the load-profile job are never held off by a purge.
    """
    cutoff = (datetime.now(UTC) if now is None else now) - timedelta(days=RETENTION_DAYS)
    readings = _purge(LoadProfileReading, LoadProfileReading.read_at, cutoff, batch_size)
    events = _purge(DeviceEvent, DeviceEvent.created_at, cutoff, batch_size)
    logger.info(
        "Retention removed %d Interval Reading(s) and %d Device Event(s) older than %s",
        readings,
        events,
        cutoff.isoformat(),
    )


def _purge(
    model: type[LoadProfileReading] | type[DeviceEvent],
    column: InstrumentedAttribute[datetime],
    cutoff: datetime,
    batch_size: int,
) -> int:
    """Delete rows of *model* whose *column* is before *cutoff*, and count them.

    ``DELETE ... LIMIT`` is not available: CPython's bundled SQLite is not built
    with ``SQLITE_ENABLE_UPDATE_DELETE_LIMIT`` and raises a syntax error on it
    (REMAKE-PLAN §280 recorded the same finding against v1's four uses). The
    subquery form below is the working equivalent, and on the measured worst case
    it plans as a covering-index scan of the existing ``(device_id, read_at)``
    index — which is why this job ships no index and no migration.

    Loops until a batch deletes **zero** rows, so the last, partly-full batch is
    followed by one statement that finds nothing. That costs one cheap statement
    per table per day and needs no assumption about how a short delete reports
    itself.
    """
    expired = select(model.id).where(column < cutoff).limit(batch_size).scalar_subquery()
    statement = delete(model).where(model.id.in_(expired))

    deleted = 0
    while True:
        # One unit of work per batch, committed before the next starts — the
        # write lock is what is being released, and `_store` in
        # `acquisition/load_profile.py` commits per chunk for the same reason.
        with session_scope() as session:
            removed = session.execute(statement).rowcount
        if not removed:
            return deleted
        deleted += removed
