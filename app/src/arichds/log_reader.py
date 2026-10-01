"""Read the tail of the rotating application log (M7-4, issue #31).

The counterpart to :mod:`arichds.logging_config` — that module writes
``arichds.log``, this one reads it back. The on-disk format is fixed by
``logging_config._LOG_FORMAT``:
``"%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"``.

A traceback is the single most valuable thing in an ops log, and it is N
lines following one header line with no format of its own — so a line that
does not parse as a header is treated as a **continuation** of the previous
entry's message, joined with ``"\\n"`` (D4). This is what lets an operator
filter to ERROR and still see the traceback body.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: The only filename this module ever reads — never a request-supplied path
#: (D1). Matches ``logging_config.py``'s ``RotatingFileHandler`` filename,
#: the only other place this string exists.
LOG_FILENAME: Final[str] = "arichds.log"

DEFAULT_TAIL_LINES: Final[int] = 500
MAX_TAIL_LINES: Final[int] = 5000

LEVELS: Final[tuple[str, ...]] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

#: Index of a level's minimum-severity rank, e.g. ``_LEVEL_RANK["WARNING"] == 2``.
_LEVEL_RANK: Final[dict[str, int]] = {level: rank for rank, level in enumerate(LEVELS)}


@dataclass(frozen=True)
class LogEntry:
    """One parsed log entry — a header line plus any continuation lines
    joined onto its ``message``.

    Attributes:
        timestamp: The raw string from the file (``%(asctime)s``), never
            parsed into a ``datetime`` — the format is local-time-with-offset,
            unlike every UTC value elsewhere in this API (D9).
        level: One of :data:`LEVELS`, stripped of the ``%(levelname)-8s``
            padding — or ``None`` for a leading continuation line with no
            preceding header (D5).
        logger: ``%(name)s`` — or ``None`` alongside ``level``.
        message: ``%(message)s``, with any continuation lines appended,
            each joined by ``"\\n"``.
    """

    timestamp: str | None
    level: str | None
    logger: str | None
    message: str


def _parse_header(line: str) -> tuple[str, str, str, str] | None:
    """Split *line* into ``(timestamp, level, logger, message)``, or None.

    A header is a line that splits on ``" | "`` (``maxsplit=3``) into exactly
    four parts **and** whose second part, stripped, names a real level — the
    two-part test D4 requires. ``maxsplit=3`` also means a message containing
    ``" | "`` survives intact.
    """
    parts = line.split(" | ", 3)
    if len(parts) != 4:
        return None
    timestamp, level_field, logger, message = parts
    level = level_field.strip()
    if level not in LEVELS:
        return None
    return timestamp, level, logger, message


def read_tail(log_dir: Path, *, lines: int, min_level: str | None) -> list[LogEntry]:
    """Return the tail of ``<log_dir>/arichds.log`` as structured entries.

    Parses the file in file order, joins continuation lines onto the
    preceding entry, filters each *completed* entry against *min_level*
    **before** applying the tail bound (D7 — an operator asking for the last
    N errors wants exactly that, not "the errors among the last N lines"),
    and returns at most *lines* entries, oldest first.

    Args:
        log_dir: The directory holding ``arichds.log`` (``settings.log_dir``).
        lines: Maximum number of entries to return.
        min_level: Keep only entries whose level is at or above this one, in
            :data:`LEVELS` order. ``None`` disables filtering. An entry with
            ``level is None`` always survives (D6) — it cannot be compared to
            a threshold.

    Returns:
        The matching entries, in file order (newest last). Never raises: a
        missing file, missing directory or empty file all return ``[]``
        (D10), and undecodable bytes are replaced rather than propagated.
    """
    path = log_dir / LOG_FILENAME
    if not path.is_file():
        return []

    tail: deque[LogEntry] = deque(maxlen=lines)
    pending: list[str] | None = None
    pending_header: tuple[str, str, str] | None = None  # (timestamp, level, logger)

    def flush() -> None:
        if pending is None:
            return
        timestamp, level, logger = pending_header if pending_header is not None else (None, None, None)
        if min_level is None or level is None or _LEVEL_RANK[level] >= _LEVEL_RANK[min_level]:
            tail.append(LogEntry(timestamp, level, logger, "\n".join(pending)))

    with path.open(encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            header = _parse_header(line)
            if header is not None:
                flush()
                timestamp, level, logger, message = header
                pending = [message]
                pending_header = (timestamp, level, logger)
            elif pending is None:
                # A leading orphan (D5) — the tail can begin mid-entry.
                pending = [line]
                pending_header = None
            else:
                pending.append(line)
        flush()

    return list(tail)
