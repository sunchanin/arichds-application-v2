"""App Log — reading the tail of the rotating application log (M7-4, issue #31).

The read-only counterpart to :mod:`arichds.log_reader`, exposed over HTTP.
Admin-only (D11): the log's content is machine-internal — usernames,
``host:port`` Transport Endpoints, file paths, tracebacks — unlike the meter
data every other read page shows.

**No filename parameter** (D1): the endpoint always reads exactly
``settings.log_dir / "arichds.log"``. There is nothing to sanitise because no
user input ever reaches a path.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from arichds.api.deps import get_current_user, require_admin, require_feature
from arichds.api.envelope import ApiResponse
from arichds.config import get_settings
from arichds.log_reader import DEFAULT_TAIL_LINES, MAX_TAIL_LINES, read_tail

router = APIRouter(
    prefix="/api/logs",
    tags=["logs"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_feature("app_log")),
        Depends(require_admin),
    ],
)


class LogEntryOut(BaseModel):
    """One parsed log entry, as the App Log page renders it.

    Attributes:
        timestamp: The raw string from the file — never parsed into a
            ``datetime`` (D9). ``None`` for a leading continuation line with
            no preceding header.
        level: One of DEBUG/INFO/WARNING/ERROR/CRITICAL, or ``None`` alongside
            ``timestamp``.
        logger: The logger name that emitted the entry, or ``None``.
        message: The log message, with any continuation lines (e.g. a
            traceback) joined onto it by newlines.
    """

    timestamp: str | None
    level: str | None
    logger: str | None
    message: str


class LogTail(BaseModel):
    """The tail of the application log. Not a page — no ``total``, no echoed
    ``limit``/``offset``: the client already knows what it asked for."""

    items: list[LogEntryOut]


@router.get("")
def get_log_tail(
    lines: Annotated[int, Query(ge=1, le=MAX_TAIL_LINES, description="How many entries to return, at most")] = (
        DEFAULT_TAIL_LINES
    ),
    min_level: Annotated[
        Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None,
        Query(description="Keep only entries at or above this level; omitted = no filtering"),
    ] = None,
) -> ApiResponse[LogTail]:
    """Return the tail of the application log, newest last.

    Resolves ``log_dir`` from :func:`~arichds.config.get_settings` on every
    call — never a module-level capture (ADR 0001's habit) — so a re-licensed
    or re-pointed machine, and a test pointing at ``tmp_path``, both see the
    current value. A missing file, missing directory, or empty file all
    answer 200 with ``items: []`` (D10).
    """
    settings = get_settings()
    entries = read_tail(settings.log_dir, lines=lines, min_level=min_level)
    items = [LogEntryOut(timestamp=e.timestamp, level=e.level, logger=e.logger, message=e.message) for e in entries]
    return ApiResponse.ok(LogTail(items=items))
