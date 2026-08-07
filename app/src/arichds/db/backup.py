"""The daily database backup job (M5c, issue #19).

``VACUUM INTO`` rather than copying the file: in WAL mode the database on disk is
``.db`` + ``-wal`` + ``-shm``, so a raw copy taken while the process is running is
not a database (REMAKE-PLAN §269). It lives under ``db/`` because its domain is
the database *as a file* — it reads no meter and takes no Transport Endpoint
lock.

**Same disk as the original.** SPEC §5 is explicit about what that does and does
not buy: it protects against a wrong delete or a corrupted database, and it does
**not** protect against the disk failing.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from arichds.config import get_settings
from arichds.constants import BACKUP_KEEP_COUNT
from arichds.db.session import create_db_engine

logger = logging.getLogger(__name__)

#: Written under a **fixed** name and renamed on success. Fixed rather than
#: unique so that repeated failures overwrite one file instead of accumulating
#: partial ones, and it is unlinked before the write because ``VACUUM INTO``
#: refuses a destination that already exists.
_TEMP_NAME = "arichds-backup.tmp"


def backup_database(*, destination: Path | None = None, keep: int = BACKUP_KEEP_COUNT) -> None:
    """Write a consistent copy of the database, then rotate the old ones.

    The Scheduler's ``backup`` job — see
    :func:`arichds.jobs.scheduler.default_jobs`. It takes no arguments in
    production; both keyword parameters exist so a test can drive it, the same
    reason ``now`` exists on
    :func:`arichds.acquisition.load_profile.read_and_store_load_profile`.

    The source is ``get_settings().db_path``, which is the same path
    :func:`arichds.db.session.init_engine` resolves, so the backup and the
    running application cannot disagree about which database is being served.

    **Written to a temp name and renamed on success.** ``VACUUM INTO`` needs the
    whole database's worth of free space, so a full disk mid-write is a foreseen
    failure; :func:`os.replace` within one directory is atomic, so the backup
    directory never holds a half-written file under a name that looks finished. A
    backup that looks valid and is not is worse than no backup (SPEC §5).

    **Failures are caught here, not raised.** A full or unwritable disk deserves a
    log line naming the path rather than the Scheduler's anonymous "Job backup
    failed", and the temp-file cleanup has to live where the ``finally`` is. Next
    run tries again — there is no retry, no backoff and no disk-space pre-check.

    **Every job runs on the Scheduler's first pass**, so a service restart takes a
    backup immediately. That is what "24 h measured from service start" means
    (SPEC §5), and it is why frequent restarts can rotate the seven kept files
    down to a single day's worth. There is deliberately no "skip if a recent
    backup exists" guard: deciding that needs persisted state, which ADR 0008
    forbids.

    Args:
        destination: The directory to write into. Defaults to
            ``Settings.backup_dir``. Created if missing, so a deleted folder heals
            instead of failing forever.
        keep: How many backup files survive. The rest are unlinked oldest-first.
    """
    settings = get_settings()
    target_dir = settings.backup_dir if destination is None else destination
    temp_path = target_dir / _TEMP_NAME
    final_path = target_dir / f"arichds-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.db"

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        # Unlinked *before* the write, not only after a failure: ``VACUUM INTO``
        # raises "output file already exists" rather than overwriting.
        temp_path.unlink(missing_ok=True)
        _vacuum_into(settings.db_path, temp_path)
        os.replace(temp_path, final_path)
        logger.info("Database backed up to %s", final_path)
        try:
            _rotate(target_dir, keep)
        except OSError:
            # Caught here and not below: by this point the backup is written, and
            # "Database backup to X failed" next to the line saying X was written
            # is the one message an operator must be able to trust. This is the
            # catch for a failure a per-file one cannot reach — a directory that
            # vanished under the glob. An undeletable *file* is handled inside
            # `_rotate`, which is what keeps one lock from stopping the rest.
            logger.exception("Rotating old backups in %s failed — %s was written", target_dir, final_path.name)
    except Exception:  # noqa: BLE001 — a full disk must cost today's backup, not the job.
        logger.exception("Database backup to %s failed", final_path)
    finally:
        # Whatever went wrong, the partial file does not survive to be mistaken
        # for a backup or to fill the disk it already exhausted.
        temp_path.unlink(missing_ok=True)


def _vacuum_into(source: Path, destination: Path) -> None:
    """``VACUUM INTO`` *source* to *destination*, which must not already exist.

    A module-level function so a test can replace it and drive the failure path
    that matters — a write that dies part way through, leaving bytes behind.
    """
    engine = create_db_engine(source)
    try:
        with engine.begin() as connection:
            connection.execute(text("VACUUM INTO :destination"), {"destination": str(destination)})
    finally:
        engine.dispose()


def _rotate(target_dir: Path, keep: int) -> None:
    """Keep the *keep* newest backups in *target_dir* and unlink the rest.

    Sorted **by filename**, not by modification time: the timestamp is in the
    name, and mtime is a filesystem property that copying or restoring a file
    silently changes.

    **Two failures, two catches, and they are not redundant.** A file that will
    not delete — held open by a viewer or an antivirus scan, the ordinary Windows
    case — is logged and skipped *here*, so the older files behind it are still
    rotated. The slice is walked newest-first, so without this a lock on one file
    would block every older one behind it, and a lock that never lifts would stop
    rotation permanently: the directory would then grow by one file a day,
    forever, in the job whose whole purpose is keeping the disk from filling.
    With this, the same permanent lock costs exactly one extra file.

    What is left to raise is a failure no per-file catch can reach — a directory
    that vanished under the glob. Its **caller** handles that, because by then the
    backup is already written and a rotation failure must never be reported as a
    failed backup.
    """
    backups = sorted(target_dir.glob("arichds-*.db"), key=lambda path: path.name, reverse=True)
    for stale in backups[keep:]:
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove the expired backup %s — the rest are still rotated", stale)
        else:
            logger.info("Removed the expired backup %s", stale.name)
