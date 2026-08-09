"""The hardened capture write (decision 3c, ADR 0010, issue #22).

Ported from v1 ``billing/service.py:1089-1291`` (``_atomic_write`` and
``capture_pdf``'s ordering), collapsed into one function shared by both
callers: the eager write in :mod:`arichds.acquisition.billing` and the
render-on-miss download in :mod:`arichds.api.billing`.

**Ordering is the whole point.** Nothing touches the filesystem before the
bytes exist in memory — a render failure must leave nothing on disk, and a
write that fails partway must leave nothing either (the orphan-prevention
invariant):

1. :func:`~arichds.capture.paths.ensure_within_allowlist` on the
   fully-constructed path (cheap, no I/O).
2. Render the bytes.
3. Stepwise ``os.mkdir(..., 0o700)`` for each missing ancestor.
4. ``lstat`` the parent and reject a symlink or non-directory.
5. Atomic write: ``O_EXCL|O_NOFOLLOW|O_BINARY``, mode ``0o600``, ``fsync``;
   unlink-the-partial on ``OSError``.

Unlike v1's ``_atomic_write`` this has no ``replace_existing`` — v2 has no
regenerate endpoint (ADR 0010), so a capture is written exactly once, ever,
per ``(meter_serial, bill_date, format)``. A second attempt at the same path
raises ``FileExistsError``; callers that consider that a race rather than a
failure (the download endpoint) catch it themselves.
"""

from __future__ import annotations

import contextlib
import os
import stat
from collections.abc import Callable
from pathlib import Path

from arichds.capture.paths import ensure_within_allowlist
from arichds.constants import O_BINARY, O_NOFOLLOW


def write_capture(target: Path, render: Callable[[], bytes], allowlist: list[Path]) -> None:
    """Render then hardened-write one capture file.

    Args:
        target: The fully-constructed ``<capture_dir>/<serial>/<file>`` path.
        render: Called with no arguments, exactly once, to produce the bytes.
            Not called at all if *target* fails the allowlist check.
        allowlist: Passed straight to
            :func:`~arichds.capture.paths.ensure_within_allowlist` — in
            practice always ``[resolved capture_dir]`` (decision 17).

    Raises:
        ValueError: *target* is outside *allowlist*, or its parent directory
            is a symlink or not a directory.
        OSError: The write itself failed (disk full, permissions, ...) — the
            partial file is unlinked before this propagates.
        FileExistsError: *target* already exists (``O_EXCL``).
    """
    ensure_within_allowlist(target, allowlist)

    data = render()

    parent = target.parent
    to_create: list[Path] = []
    directory = parent
    while not directory.exists():
        to_create.append(directory)
        next_up = directory.parent
        if next_up == directory:
            break  # filesystem root
        directory = next_up
    for directory in reversed(to_create):
        with contextlib.suppress(FileExistsError):  # a concurrent writer beat us to this ancestor
            os.mkdir(str(directory), 0o700)

    try:
        parent_stat = os.lstat(str(parent))
    except OSError as exc:
        raise ValueError(f"capture directory is a symlink or missing: cannot lstat {parent}: {exc}") from exc
    if not stat.S_ISDIR(parent_stat.st_mode) or stat.S_ISLNK(parent_stat.st_mode):
        raise ValueError(f"capture directory is a symlink or missing: {parent}")

    _atomic_write(target, data)


def _atomic_write(target: Path, data: bytes) -> None:
    """Write *data* to *target* with ``O_EXCL`` — never overwrite, never leave
    a partial file on failure."""
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | O_BINARY, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=True) as file_obj:
            file_obj.write(data)
            file_obj.flush()
            os.fsync(file_obj.fileno())
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(str(target))
        raise
