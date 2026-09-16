"""What the last File Upload Destination cycle did — **in memory only**
(ADR 0008), the same shape :mod:`arichds.centralpush.status` and
:mod:`arichds.dataout.status` use, and for the same reason: ADR 0025 gives
this Destination no persisted job state either — the server-side **Upload
Manifest** is what remembers, never this process.

It resets on restart, and that is correct rather than a gap: the page's
status card answers *"is the upload working right now"*, and a service that
just came up has no answer to that yet.

**Ticket 01 (this) never calls** :func:`set_last_cycle` — there is no cycle
yet, so :func:`last_cycle` always answers ``None`` until ticket 02 lands the
scheduler job that populates it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

#: What a cycle ended as — the same two-outcome shape
#: :data:`arichds.centralpush.status.CycleOutcome` uses, for the same reason:
#: every failure (unreachable, refused, a bad certificate, a rejected host
#: key) is one fact from the status card's point of view — nothing new
#: reached the server this pass — and *why* lives in
#: :attr:`CycleStatus.error`.
CycleOutcome = Literal["success", "skipped"]


@dataclass(frozen=True, slots=True)
class CycleStatus:
    """One completed File Upload Destination cycle.

    Attributes:
        ran_at: When the cycle finished, **UTC and timezone-aware**.
        protocol: Which protocol was active for this cycle (``"sftp"`` /
            ``"ftps"`` / ``"https"``).
        outcome: Which of :data:`CycleOutcome` this cycle ended as.
        files_sent: Files the manifest compare found new or changed and the
            transport actually put.
        bytes_sent: Total bytes across *files_sent*.
        files_skipped: Files the cycle's time budget left unreached this
            pass — not a failure, since the manifest already records what did
            arrive and the next cycle resumes from there (ADR 0025).
        duration_sec: Wall clock for the whole cycle.
        error: The failure's class name (never a credential) when *outcome*
            is `"skipped"`, else ``None``.
    """

    ran_at: datetime
    protocol: str
    outcome: CycleOutcome
    files_sent: int = 0
    bytes_sent: int = 0
    files_skipped: int = 0
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
