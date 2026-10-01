"""What the last Central Push cycle did — **in memory only** (ADR 0008).

The same shape :mod:`arichds.dataout.status` uses for the Database
Destination, and for the same reason: ADR 0008 forbids persisted job state
of any kind, and ADR 0024 says the same about the push itself — "no
`sync_state`" — so there is nothing to write to disk here either. One
frozen dataclass in one process-wide slot is the entire history of a cycle.

It resets on restart, and that is correct rather than a gap: the API page's
status card answers *"is the push working right now"*, and a service that
just came up has no answer to that yet.

**Ticket 08** is what calls :func:`set_last_cycle` — `centralpush/cycle.py`'s
scheduler job.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

#: What a cycle ended as (SPEC story 12). ``"skipped"`` covers every failure
#: the ticket names as one word — unreachable, refused, timed out on
#: connect or read, or a non-2xx response — because from the API page's
#: point of view they are the same fact: nothing new reached the server this
#: pass, and *why* lives in :attr:`CycleStatus.error`, not in a second
#: outcome value.
CycleOutcome = Literal["success", "skipped"]


@dataclass(frozen=True, slots=True)
class CycleStatus:
    """One completed Central Push cycle.

    Attributes:
        ran_at: When the cycle finished, **UTC and timezone-aware**.
        outcome: Which of :data:`CycleOutcome` this cycle ended as.
        meters_rows: Meter roster rows sent — always a full snapshot
            (ADR 0024).
        billing_rows: Billing rows sent (new, or re-sent because
            `updated_at` advanced).
        energy_summary_rows: Energy Summary rows sent, same rule.
        load_profile_rows: Interval Reading rows sent.
        skipped_rows: Rows whose device has no known Meter Serial, and were
            therefore not sent (SPEC story 14).
        duration_sec: Wall clock for the whole cycle.
        error: The failure's class name (never the URL or the token) when
            *outcome* is `"skipped"`, else ``None``. A cycle that stopped on
            its own time budget is *not* an error — it stopped cleanly with
            *outcome* `"success"` and resumes next tick from wherever it got
            to.
    """

    ran_at: datetime
    outcome: CycleOutcome
    meters_rows: int = 0
    billing_rows: int = 0
    energy_summary_rows: int = 0
    load_profile_rows: int = 0
    skipped_rows: int = 0
    duration_sec: float = 0.0
    error: str | None = None


_lock = threading.Lock()
_last: CycleStatus | None = None


def set_last_cycle(status: CycleStatus | None) -> None:
    """Publish (or, with ``None``, clear) the last cycle's status."""
    global _last  # noqa: PLW0603
    with _lock:
        _last = status


def last_cycle() -> CycleStatus | None:
    """Return the last cycle's status, or ``None`` if none has run."""
    with _lock:
        return _last
