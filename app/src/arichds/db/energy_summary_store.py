"""The stored Energy Summary — the recompute job that fills
``energy_summary_days``, and the read the API now serves from it (ADR 0022,
supersedes ADR 0012; M14, ticket 01).

**Recomputed, not derived, and stored, not live.** Every scheduler cycle
recomputes every device's whole ``RETENTION_DAYS`` window from
``load_profile_readings`` through the existing, unchanged Time-of-Use
aggregation in :mod:`arichds.db.energy_query`, and upserts the result. A
Holiday change and a late Interval Reading therefore both reach every
affected day within one cycle, by the same mechanism, with no trigger for
either — exactly what ADR 0012's live derivation gave for free, now paid for
once per cycle instead of once per request.

**``updated_at`` moves only when a bucket value actually changes.** A row is
only ever written to (whether inserted fresh or updated in place) when at
least one of its eight buckets differs from what is already stored — a
recompute that finds nothing new writes nothing, and touches no row's
``updated_at``. This is load-bearing for the Central Push (ADR 0024, not
built by this ticket): a row re-stamped every cycle regardless of its values
would look changed to a push that tracks rows by ``updated_at``, and the
whole window would resend every fifteen minutes. ``updated_at`` is stamped
explicitly from the same ``now`` the recompute is called with, rather than
left to the column's own ``onupdate=func.now()`` — SQLite's ``CURRENT_TIMESTAMP``
has only whole-second resolution, and two recomputes inside the same wall-clock
second must still be able to prove a changed day moved and an unchanged one
did not.

**A stored day whose readings are gone is deleted here too, within the
window.** ADR 0022 says this design "invalidates nothing: it recomputes
everything, every time" — a row the live aggregation no longer produces for a
date inside ``[window_start, window_end]`` is removed in the same pass, not
left to linger until Retention. This is what makes **Delete all data**
(``api/devices.py``) and a re-read that reclassifies a day's intervals
all-invalid actually correct the stored table, rather than leaving a wrong
number on the page — and eventually in the Central Push — for up to 90 days.
Only a date *before* ``window_start`` is left to
:func:`arichds.db.retention.purge_expired`, which owns everything outside the
window.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from arichds.constants import RETENTION_DAYS
from arichds.db.energy_query import EnergySummaryDay, energy_summary_rows, local_today
from arichds.db.models import Device
from arichds.db.models import EnergySummaryDay as EnergySummaryDayRow
from arichds.db.session import session_scope

logger = logging.getLogger(__name__)

#: The eight Time-of-Use bucket fields, in the one order the diff, the insert
#: and the read all walk — field names shared verbatim between
#: :class:`~arichds.db.energy_query.EnergySummaryDay` (the pydantic shape the
#: live aggregation returns) and :class:`~arichds.db.models.EnergySummaryDay`
#: (the stored row), so this tuple is the only place either is named.
_BUCKET_FIELDS: tuple[str, ...] = (
    "peak_import_kwh",
    "offpeak_import_kwh",
    "holiday_import_kwh",
    "total_import_kwh",
    "peak_export_kwh",
    "offpeak_export_kwh",
    "holiday_export_kwh",
    "total_export_kwh",
)


def energy_summary_recompute_cycle(*, today: date | None = None, now: datetime | None = None) -> None:
    """Recompute every device's whole ``RETENTION_DAYS`` window and upsert
    ``energy_summary_days`` (ADR 0022).

    The Scheduler's ``energy_summary_recompute`` job — registered
    **immediately** behind ``load_profile``, at the same interval (see
    :func:`arichds.jobs.scheduler.default_jobs`). Takes no arguments in
    production; ``today``/``now`` exist so a test drives the window and the
    ``updated_at`` stamp without a real clock, the same reason
    :func:`arichds.db.retention.purge_expired` takes ``now``.

    Sequential, one device at a time — one device's failure must never strand
    the rest of the site's recompute, mirroring every other cycle job
    (:func:`arichds.acquisition.battery.battery_cycle`,
    :func:`arichds.acquisition.billing.billing_cycle`).

    Args:
        today: The local calendar day the window ends on, inclusive.
            Defaults to :func:`arichds.db.energy_query.local_today`.
        now: What a changed or new row's ``updated_at`` is stamped with.
            Defaults to the real clock, UTC.
    """
    local_today_ = local_today() if today is None else today
    now_utc = datetime.now(UTC) if now is None else now
    window_start = local_today_ - timedelta(days=RETENTION_DAYS - 1)

    with session_scope() as session:
        device_ids = list(session.scalars(select(Device.id).order_by(Device.id)))

    for device_id in device_ids:
        try:
            _recompute_device(device_id, window_start, local_today_, now_utc)
        except Exception:  # noqa: BLE001 — one device must never strand the rest of the site.
            logger.exception("Energy Summary recompute failed for device id %s", device_id)


def _recompute_device(device_id: int, window_start: date, window_end: date, now_utc: datetime) -> None:
    """Recompute one device's window: upsert every day that changed, and
    delete every stored day in the window the live aggregation no longer
    produces."""
    with session_scope() as session:
        computed = {day.date: day for day in energy_summary_rows(session, device_id, window_start, window_end)}
        existing_rows = {
            row.local_date: row
            for row in session.scalars(
                select(EnergySummaryDayRow).where(
                    EnergySummaryDayRow.device_id == device_id,
                    EnergySummaryDayRow.local_date >= window_start,
                    EnergySummaryDayRow.local_date <= window_end,
                )
            )
        }

        for local_date, day in computed.items():
            existing = existing_rows.get(local_date)
            if existing is None:
                session.add(
                    EnergySummaryDayRow(
                        device_id=device_id,
                        local_date=local_date,
                        updated_at=now_utc,
                        **{field: getattr(day, field) for field in _BUCKET_FIELDS},
                    )
                )
                continue
            # Only touched when at least one bucket genuinely differs — this
            # is what keeps `updated_at` from moving on a row nothing changed
            # about (module docstring).
            if any(getattr(existing, field) != getattr(day, field) for field in _BUCKET_FIELDS):
                for field in _BUCKET_FIELDS:
                    setattr(existing, field, getattr(day, field))
                existing.updated_at = now_utc

        # A stored day inside the window that the live aggregation no longer
        # produces (its readings are gone, or a re-read reclassified every
        # interval all-invalid) is deleted here too — ADR 0022 recomputes
        # everything, every time, rather than leaving a wrong number on the
        # page until Retention. Nothing outside `[window_start, window_end]`
        # is touched; that is `purge_expired`'s job, not this one's.
        for stale_date in set(existing_rows) - set(computed):
            session.delete(existing_rows[stale_date])


def stored_energy_summary_rows(
    session: Session, device_id: int, start_date: date, end_date: date
) -> list[EnergySummaryDay]:
    """Read ``energy_summary_days`` for one device over ``[start_date, end_date]``
    (both local, inclusive) — what ``GET /api/energy/summary`` now serves
    (ADR 0022): the recompute job's stored rows, never re-aggregated on the
    request.

    Returns the same pydantic shape :func:`arichds.db.energy_query.energy_summary_rows`
    always has, so the endpoint's response is unchanged.
    """
    rows = session.scalars(
        select(EnergySummaryDayRow)
        .where(
            EnergySummaryDayRow.device_id == device_id,
            EnergySummaryDayRow.local_date >= start_date,
            EnergySummaryDayRow.local_date <= end_date,
        )
        .order_by(EnergySummaryDayRow.local_date)
    ).all()
    return [
        EnergySummaryDay(date=row.local_date, **{field: getattr(row, field) for field in _BUCKET_FIELDS})
        for row in rows
    ]


__all__ = [
    "energy_summary_recompute_cycle",
    "stored_energy_summary_rows",
]
