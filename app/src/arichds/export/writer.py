"""The one writer every export file goes through (M13, issue 01; ticket 02
rewrites its head-change behaviour under ADR 0023).

An export file **appends for months under a header written once** — ADR 0013
calls that a contract, as opposed to a rendered view which is re-derived on
every request. This module owns the consequence ADR 0013 did not have to face
until now: **what happens when the contract itself changes.**

**The answer, since ADR 0023, is that the file is rewritten in place.** M13's
answer — close the file under a dated name and open a new one beside it — grew
the export folder without bound on a machine whose owner asked for bounded
storage (ADR 0020's constraint). ADR 0023 replaces it: when a file's head no
longer matches what we would write today, the whole file is rewritten under
the current head, atomically, and no dated edition is ever created. **No row
is ever appended under a head that does not describe it** survives unchanged —
that is still the failure this module exists to prevent, and the one nobody
would see: a fourteen-column header with twenty-five-column rows below it
raises no error anywhere, it just puts every number under the wrong name.

**The head is the block plus the column row, and both are compared.** The
block carries the customer, site name and meter serial off the device row,
all three of which an operator can edit at any time. Comparing only the
column row would leave a file claiming a site name that was not in effect
when its rows were written, for as long as the columns happened not to
change — possibly for ever.

Reading the head reads *the head*, not the file: a few lines off the front,
never the whole thing. The Load Profile CSV export deliberately avoids reading
its own output (its watermark is a column, not a line count), and that
reasoning survives here — a fixed number of lines is not a scan.

Two write paths, for two shapes of caller:

* :func:`append_rows` — the cheap, common case: the file's on-disk head
  already matches (or the file is new), and the caller only has a batch of
  *pending* rows to add. Opens in append mode; refuses, rather than
  corrupting the file, if the head has in fact changed underneath it — a
  caller must have checked :func:`head_changed` first and gone to
  :func:`replace_rows` instead.
* :func:`replace_rows` — the whole-file case: the caller has computed the
  file's *entire* current content (a head change, an every-cycle rewrite, or
  an on-demand save) and wants it on disk as one atomic swap. Writes a
  temporary file in the same directory, flushes and ``fsync``s it, then
  ``os.replace``s it over the target in one step, so a reader — Syncthing,
  the customer's own tooling — never sees a half-written file, and a failure
  anywhere in the write leaves the previous file exactly as it was.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from arichds.capture.paths import ensure_within_allowlist

logger = logging.getLogger(__name__)

#: Written once at the top of a fresh file (v1 parity — Excel on Windows needs
#: the BOM to render non-ASCII text correctly).
UTF8_BOM = "﻿"


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


def head_changed(path: Path, header_block: Sequence[Sequence[str]], header_row: Sequence[str]) -> bool:
    """Whether *path* already exists, with content, under a head that differs
    from what :func:`render_head` would produce for *header_block* /
    *header_row* today.

    ``False`` covers two different normal states a caller must **not**
    distinguish: the file is absent or empty (the ordinary
    :func:`append_rows` path creates it), or it already carries the current
    head. Only ``True`` means a caller should compute this file's whole
    current content and write it through :func:`replace_rows` instead of
    appending.
    """
    head_lines = len(header_block) + 1
    existing = _existing_head(path, head_lines)
    if existing is None:
        return False
    return existing != render_head(header_block, header_row)


def append_rows(
    path: Path,
    *,
    header_block: Sequence[Sequence[str]],
    header_row: Sequence[str],
    rows: Sequence[Sequence[str]],
    allowlist: Sequence[Path],
    label: str,
) -> bool:
    """Append *rows* to *path*, writing the BOM and head first if the file is
    new or empty.

    **Callers are responsible for having checked :func:`head_changed` first.**
    When the file exists with content whose head no longer matches, this
    refuses to append — under the old head that would put rows under a
    header that does not describe them, and there is no cheap way to fix that
    from inside an append; the caller must recompute the whole file and call
    :func:`replace_rows`. Reaching that branch here means a caller skipped
    the check, so it is logged and treated the same as a write failure.

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
        a write error, an allowlist rejection, or a head that has changed
        underneath the caller. The caller must not advance its watermark on
        False, so the same rows retry on the next cycle.
    """
    head = render_head(header_block, header_row)
    head_lines = len(header_block) + 1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ensure_within_allowlist(path, allowlist)

        existing = _existing_head(path, head_lines)
        if existing is not None and existing != head:
            logger.warning(
                "%s: the head of %s no longer matches what we would write today — "
                "a caller must replace the whole file, not append to it — skipping",
                label,
                path.name,
            )
            return False

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


def replace_rows(
    path: Path,
    *,
    header_block: Sequence[Sequence[str]],
    header_row: Sequence[str],
    rows: Sequence[Sequence[str]],
    allowlist: Sequence[Path],
    label: str,
) -> bool:
    """Atomically replace *path* with the complete file: BOM, header block,
    header row, then *rows* — exactly the content a fresh file would open
    with (ADR 0023).

    Writes a temporary file in *path*'s own directory (so the final swap is a
    same-filesystem rename, never a cross-filesystem copy), flushes and
    ``fsync``s it, then ``os.replace``s it over *path* in one step. The
    target is never opened for writing directly: on any failure — mid-write,
    at ``fsync``, or at the replace itself — *path* is left byte-for-byte as
    it was, and the temporary file is removed.

    Used for a head-change rewrite, an every-cycle whole-file rewrite (Energy,
    Billing — ADR 0023) and an on-demand save that is always the *whole*
    answer for its own range.

    Args:
        path: The target file.
        header_block: The file header block, one ``[label, value]`` pair per
            line.
        header_row: The column header row.
        rows: Every row the file should hold, already formatted as strings —
            the file's whole current content, not a pending batch.
        allowlist: Roots *path* must resolve inside — checked before the
            temporary file is created.
        label: What to call this export in a log line.

    Returns:
        True once the swap has completed. False on an allowlist rejection or
        any write/replace failure, logged. The caller must not advance a
        watermark on False.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ensure_within_allowlist(path, allowlist)
    except ValueError:
        logger.warning("%s: target path outside allowlist (%s) — skipping", label, path.name)
        return False
    except OSError:
        logger.warning("%s: could not prepare %s for replacement — skipping", label, path.name, exc_info=True)
        return False

    try:
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    except OSError:
        logger.warning(
            "%s: could not create a temporary file beside %s — the previous file is untouched",
            label,
            path.name,
            exc_info=True,
        )
        return False

    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as file_obj:
            file_obj.write(UTF8_BOM)
            file_obj.write(render_head(header_block, header_row))
            writer = csv.writer(file_obj, lineterminator="\n")
            writer.writerows(rows)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(tmp_path, path)
        return True
    except OSError:
        logger.warning(
            "%s: atomic replace failed for %s — the previous file is untouched", label, path.name, exc_info=True
        )
        return False
    finally:
        # A success has already renamed the temporary file away, so this is a
        # no-op on the happy path — and the one thing that guarantees a
        # failure at any point above never leaves a stray `.tmp` file behind.
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


__all__ = ["UTF8_BOM", "append_rows", "head_changed", "render_head", "replace_rows"]
