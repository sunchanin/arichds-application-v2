"""The daily database backup job (M5c, issue #19).

``VACUUM INTO`` rather than a file copy: in WAL mode the database is
``.db`` + ``-wal`` + ``-shm``, so a raw copy taken while the process runs is not
a database (REMAKE-PLAN §269). The tests assert against the produced *file* —
that it opens as a database and holds the rows — because that is the only thing
a backup is for.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from arichds.config import Settings
from arichds.db.backup import backup_database
from arichds.db.models import Device
from arichds.db.session import session_scope


def make_device(name: str = "Main Incomer") -> None:
    """Put one row in the source database, so a backup has something to contain."""
    with session_scope() as session:
        session.add(
            Device(
                name=name,
                brand="mitsu",
                model="smw110",
                site_name="Plant A",
                transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
                password="hunter2",
            )
        )


def device_names_in(backup: Path) -> list[str]:
    """Open *backup* as a plain SQLite database and read its device names."""
    connection = sqlite3.connect(backup)
    try:
        return [row[0] for row in connection.execute("SELECT name FROM devices ORDER BY name")]
    finally:
        connection.close()


class TestWhereBackupsLive:
    """One place decides where data lives — :class:`Settings`, like every other path."""

    def test_the_backup_directory_is_created_with_the_rest_of_the_data_tree(self, settings: Settings) -> None:
        assert settings.backup_dir == settings.data_dir.resolve() / "backup"
        assert settings.backup_dir.is_dir(), "ensure_directories() did not create the backup directory"


class TestTheBackupIsARealDatabase:
    """A backup file that looks valid and is not is worse than no backup (SPEC §5)."""

    def test_it_writes_one_file_that_opens_and_holds_the_source_rows(self, migrated_db: Settings) -> None:
        make_device("Main Incomer")

        backup_database()

        backups = list(migrated_db.backup_dir.glob("arichds-*.db"))
        assert len(backups) == 1, f"expected one backup file, found {[p.name for p in backups]}"
        assert device_names_in(backups[0]) == ["Main Incomer"]


class TestAFailedBackupLeavesNothingBehind:
    """SPEC §5 — ``VACUUM INTO`` needs the whole database's worth of space, so a
    full disk mid-write is the foreseen failure. The half-written file must never
    appear under a name that looks like a finished backup.
    """

    def test_a_failure_part_way_through_leaves_no_file_at_all(
        self, migrated_db: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def write_some_bytes_then_die(source: Path, destination: Path) -> None:
            destination.write_bytes(b"SQLite format 3\x00 half a database")
            raise OSError("There is not enough space on the disk")

        monkeypatch.setattr("arichds.db.backup._vacuum_into", write_some_bytes_then_die)

        backup_database()

        assert list(migrated_db.backup_dir.glob("arichds-*.db")) == [], "a partial write was named as a real backup"
        assert list(migrated_db.backup_dir.glob("*.tmp")) == [], "the temp file was left behind to accumulate"


class TestAnUnwritableDestinationIsALogLine:
    """The real failure path, with nothing patched out.

    ``backup_database`` catches its own failures rather than letting the
    Scheduler's guard log an anonymous "Job backup failed": a full or unwritable
    disk is a *foreseen* condition, and the sentence has to name the path a
    person would go and look at.
    """

    def test_it_returns_normally_and_names_the_destination_at_error(
        self, migrated_db: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        blocked = tmp_path / "not-a-directory"
        blocked.write_text("a regular file where a directory would have to go")
        destination = blocked / "backup"

        with caplog.at_level(logging.ERROR, logger="arichds.db.backup"):
            backup_database(destination=destination)  # must not raise

        assert "Database backup to" in caplog.text
        assert str(destination) in caplog.text, "the log does not say which destination failed"
        assert not destination.exists()


class TestRotation:
    """Seven kept (SPEC §5), sorted by **filename** — the timestamp is in the name.

    Not by modification time: mtime is a filesystem property that copying a
    backup off the machine, or restoring one, silently changes.
    """

    def test_the_oldest_backup_goes_once_there_are_more_than_seven(self, migrated_db: Settings) -> None:
        for day in range(1, 8):
            (migrated_db.backup_dir / f"arichds-2020010{day}-000000.db").write_bytes(b"an older backup")

        backup_database()

        names = sorted(path.name for path in migrated_db.backup_dir.glob("arichds-*.db"))
        assert len(names) == 7, f"rotation kept {len(names)} backups: {names}"
        assert "arichds-20200101-000000.db" not in names, "the oldest backup survived rotation"
        assert "arichds-20200102-000000.db" in names, "rotation removed more than the oldest"
        fresh = [name for name in names if not name.startswith("arichds-2020")]
        assert len(fresh) == 1, f"the backup just taken was rotated away instead of the oldest: {names}"


class TestALeftoverTempFileHeals:
    """A process killed mid-backup never runs its ``finally``, so the temp file
    survives. ``VACUUM INTO`` refuses a destination that already exists, so the
    next run unlinks it *before* writing rather than only after a failure —
    otherwise one crash would break every backup from then on.
    """

    def test_a_stale_temp_file_does_not_block_the_next_backup(self, migrated_db: Settings) -> None:
        (migrated_db.backup_dir / "arichds-backup.tmp").write_bytes(b"left by a killed process")
        make_device("Main Incomer")

        backup_database()

        backups = list(migrated_db.backup_dir.glob("arichds-*.db"))
        assert len(backups) == 1, "a stale temp file blocked the backup"
        assert device_names_in(backups[0]) == ["Main Incomer"]
        assert list(migrated_db.backup_dir.glob("*.tmp")) == []


class TestOneUndeletableFileDoesNotStopTheRest:
    """A lock on one stale backup must cost one file, not the whole rotation.

    The stale slice is walked newest-first, so a lock on a *newer* stale file
    sits in front of every older one. Without a per-file catch that lock blocks
    them all — and a lock that never lifts (a handle an operator left open, an
    antivirus quarantine) stops rotation permanently: one file a day, forever,
    in the job whose purpose is keeping the machine from filling up. With it, the
    same permanent lock stabilises one file over the limit.
    """

    def test_the_file_behind_a_locked_one_is_still_removed(
        self, migrated_db: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for day in range(1, 9):  # eight stale files; with the ninth taken below, two must go
            (migrated_db.backup_dir / f"arichds-2020010{day}-000000.db").write_bytes(b"an older backup")

        # `20200102` is the NEWER of the two doomed files, so rotation reaches it
        # first — the position that distinguishes a per-file catch from one at the
        # call site. `20200101` is behind it and must still go.
        locked = migrated_db.backup_dir / "arichds-20200102-000000.db"
        real_unlink = Path.unlink

        def refuse_the_locked_file(self: Path, *args: object, **kwargs: object) -> None:
            if self == locked:
                raise PermissionError(32, "The process cannot access the file because it is being used by another")
            real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", refuse_the_locked_file)

        backup_database()

        names = sorted(path.name for path in migrated_db.backup_dir.glob("arichds-*.db"))
        assert "arichds-20200101-000000.db" not in names, (
            "the file behind the locked one was never reached — one undeletable file stopped the whole rotation, "
            "so a lock that never lifts would grow this directory without bound"
        )
        assert locked.name in names, "the locked file was somehow deleted, so this test proves nothing"
        assert len(names) == 8, f"rotation kept {len(names)} files: {names}"
