"""What the last Database Destination cycle did — **in memory only** (#46).

ADR 0008 forbids persisted job state of any kind: no job table, no
``last_sync`` row, no watermark column. The load-profile watermark is the
destination's own ``MAX(read_at)``, and *this* is the entire history of a
cycle — one frozen dataclass in one process-wide slot, the same shape
:mod:`arichds.licensing.current` uses for the LicenseService.

It resets on restart, and that is correct rather than a gap: the page's
status card answers *"is the sync working right now"*, and a service that
just came up has no answer to that yet. A record of what it did last week
would be exactly the job history ADR 0008 refuses.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SyncStatus:
    """One completed Database Destination cycle.

    Attributes:
        ran_at: When the cycle finished, **UTC and timezone-aware**. The
            store's convention — ADR 0021's local-time boundary is the
            *destination*, and this never leaves our side.
        load_profile_rows: Interval Readings sent (attempted inserts, not a
            count of rows the destination gained — a re-sent row inside the
            watermark rewind collapses onto itself through ON DUPLICATE KEY
            UPDATE and is counted here all the same).
        billing_rows: Billing Readings written by the whole-table replace.
        purged_rows: Rows deleted from the destination's
            ``load_profile_readings`` past the Mirror Window (ADR 0020).
        skipped_rows: Rows that could not be attributed to a Meter Serial and
            were therefore not sent.
        duration_sec: Wall clock for the whole cycle.
        error: The failure that ended the cycle, or ``None``. A cycle that
            ran out of budget is **not** an error — it stopped cleanly and
            resumes next tick.
        budget_exhausted: Whether the cycle stopped early on
            :data:`~arichds.constants.DBDEST_SYNC_BUDGET_SEC`.
    """

    ran_at: datetime
    load_profile_rows: int = 0
    billing_rows: int = 0
    purged_rows: int = 0
    skipped_rows: int = 0
    duration_sec: float = 0.0
    error: str | None = None
    budget_exhausted: bool = False


_lock = threading.Lock()
_last: SyncStatus | None = None


def set_last_sync(status: SyncStatus | None) -> None:
    """Publish (or, with ``None``, clear) the last cycle's status."""
    global _last  # noqa: PLW0603
    with _lock:
        _last = status


def last_sync() -> SyncStatus | None:
    """Return the last cycle's status, or ``None`` if none has run."""
    with _lock:
        return _last
