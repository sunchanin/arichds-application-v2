"""The one writer every export file goes through (M13, issue 01).

An export file **appends for months under a header written once** — ADR 0013
calls that a contract, as opposed to a rendered view which is re-derived on
every request. This module owns the consequence ADR 0013 did not have to face
until now: **what happens when the contract itself changes.**

The answer is that it does not change. The file is closed and a new one opens
beside it::

    <name>.csv          the edition being appended to now
    <name>.2026-09-15.csv   the edition that was closed on that date

Nothing is ever rewritten in place, and **no row is ever appended under a head
that does not describe it** — which is the failure this exists to prevent, and
the one nobody would see: a fourteen-column header with twenty-five-column rows
below it raises no error anywhere, it just puts every number under the wrong
name.

**The head is the block plus the column row, and both are compared.** The block
carries the customer, site name and meter serial off the device row, all three
of which an operator can edit at any time. Comparing only the column row would
leave a file claiming a site name that was not in effect when its rows were
written, for as long as the columns happened not to change — possibly for ever.

Reading the head reads *the head*, not the file: a few lines off the front,
never the whole thing. The Load Profile CSV export deliberately avoids reading
its own output (its watermark is a column, not a line count), and that reasoning
survives here — a fixed number of lines is not a scan.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from arichds.capture.paths import ensure_within_allowlist

logger = logging.getLogger(__name__)

#: Written once at the top of a fresh file (v1 parity — Excel on Windows needs
#: the BOM to render non-ASCII text correctly).
UTF8_BOM = "﻿"

#: How many rolled editions of one file may share a date before we give up.
#: Reaching this means something is rewriting the head in a loop, which is a
#: defect to see rather than a case to keep renaming around.
_MAX_ROLL_SUFFIX = 99


def render_head(header_block: Sequence[Sequence[str]], header_row: Sequence[str]) -> str:
    """Render the block and the column row as the exact text a fresh file opens
    with — the same string that is compared against an existing file's front.

    Built through :mod:`csv` rather than by joining commas, so a site name
    containing a comma is quoted here exactly as it is when written.

    Args:
        header_block: The file header block, one ``[label, value]`` pair per
            line.
        header_row: The column header row.

    Returns:
        The head text, newline-terminated, without the BOM.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(header_block)
    writer.writerow(header_row)
    return buffer.getvalue()


def _existing_head(path: Path, line_count: int) -> str | None:
    """Read the first *line_count* lines of *path*, or ``None`` when the file
    is absent, empty or unreadable.

    The BOM is stripped before returning, so a caller compares content rather
    than encoding.
    """
    try:
        if not path.exists() or path.stat().st_size == 0:
            return None
        with open(path, encoding="utf-8-sig", newline="") as file_obj:
            lines = [file_obj.readline() for _ in range(line_count)]
    except OSError:
        return None
    if not lines[0]:
        return None
    return "".join(lines)


def _roll(path: Path) -> Path | None:
    """Close *path* by renaming it with today's date before its extension.

    A name already taken takes a numeric suffix, so two column changes on one
    day do not silently destroy the first edition.

    Returns:
        The name the old file now has, or ``None`` when the rename failed —
        in which case the caller must not write, because writing would append
        under the wrong head.
    """
    today = date.today().isoformat()
    for suffix in range(1, _MAX_ROLL_SUFFIX + 1):
        stem = f"{path.stem}.{today}" if suffix == 1 else f"{path.stem}.{today}-{suffix}"
        candidate = path.with_name(stem + path.suffix)
        if candidate.exists():
            continue
        try:
            path.rename(candidate)
        except OSError:
            logger.warning("Export: could not close %s for a head change — not writing", path.name, exc_info=True)
            return None
        return candidate
    logger.warning("Export: %s has been rolled %d times today — not writing", path.name, _MAX_ROLL_SUFFIX)
    return None


def append_rows(
    path: Path,
    *,
    header_block: Sequence[Sequence[str]],
    header_row: Sequence[str],
    rows: Sequence[Sequence[str]],
    allowlist: Sequence[Path],
    label: str,
) -> bool:
    """Append *rows* to *path*, opening a new edition first if its head changed.

    Args:
        path: The target file.
        header_block: The file header block, one ``[label, value]`` pair per
            line.
        header_row: The column header row.
        rows: The rows to append, already formatted as strings.
        allowlist: Roots *path* must resolve inside — checked immediately
            before the file is opened, mirroring ``capture/write.py``'s own
            ordering.
        label: What to call this export in a log line.

    Returns:
        True when the rows reached disk. **False on every failure**, logged —
        a write error, an allowlist rejection, or a roll that could not
        complete. The caller must not advance its watermark on False, so the
        same rows retry on the next cycle.
    """
    head = render_head(header_block, header_row)
    head_lines = len(header_block) + 1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ensure_within_allowlist(path, allowlist)

        existing = _existing_head(path, head_lines)
        if existing is not None and existing != head:
            closed_as = _roll(path)
            if closed_as is None:
                return False
            logger.info(
                "%s: the head of %s changed — closed it as %s and started a new file",
                label,
                path.name,
                closed_as.name,
            )
            existing = None

        with open(path, "a", encoding="utf-8", newline="") as file_obj:
            if existing is None:
                file_obj.write(UTF8_BOM)
                file_obj.write(head)
            writer = csv.writer(file_obj, lineterminator="\n")
            writer.writerows(rows)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        return True
    except ValueError:
        logger.warning("%s: target path outside allowlist (%s) — skipping", label, path.name)
        return False
    except OSError:
        logger.warning("%s: write failed for %s — will retry next cycle", label, path.name, exc_info=True)
        return False


__all__ = ["UTF8_BOM", "append_rows", "render_head"]
