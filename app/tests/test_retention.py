"""The daily retention job (M5c, issue #19).

Two tables, one rule: 90 days, cut on ``read_at`` for Interval Readings and on
``created_at`` for Device Events. The tests drive :func:`purge_expired` through
its public interface and assert against the rows that survive, because the rows
are the whole product of the job — there is no job record to inspect (ADR 0008).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from fakes import fake_meter_state
from sqlalchemy import event, select

from arichds.acquisition.load_profile import read_and_store_load_profile
from arichds.config import Settings
from arichds.constants import LOAD_PROFILE_BACKFILL_DAYS, RETENTION_DAYS, SOURCE_DLMS
from arichds.db.models import Device, DeviceEvent, LoadProfileReading
from arichds.db.retention import purge_expired
from arichds.db.session import get_engine, session_scope

#: A fixed anchor so every cutoff in these tests is arithmetic, not a clock race.
NOW = datetime(2026, 8, 7, 6, 0, tzinfo=UTC)


def make_device(name: str = "Main Incomer") -> int:
    """Insert one device to hang readings and events off, and return its id."""
    with session_scope() as session:
        device = Device(
            name=name,
            brand="mitsu",
            model="smw110",
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="hunter2",
        )
        session.add(device)
        session.flush()
        return device.id


def seed_readings(device_id: int, *moments: datetime) -> None:
    """Store one Interval Reading per moment (one per logger slot, so all survive)."""
    with session_scope() as session:
        session.add_all(
            LoadProfileReading(
                device_id=device_id,
                read_at=moment,
                source=SOURCE_DLMS,
                logger_id=1,
                interval_sec=900,
                import_active_kwh=1.0,
            )
            for moment in moments
        )


def stored_read_ats(device_id: int) -> list[datetime]:
    """Every ``read_at`` still stored for *device_id*, oldest first."""
    with session_scope() as session:
        return [
            value.replace(tzinfo=UTC)
            for value in session.scalars(
                select(LoadProfileReading.read_at)
                .where(LoadProfileReading.device_id == device_id)
                .order_by(LoadProfileReading.read_at)
            )
        ]


def seed_events(device_id: int, *moments: datetime, actor: str | None = None) -> None:
    """Record one Device Event per moment."""
    with session_scope() as session:
        session.add_all(
            DeviceEvent(device_id=device_id, kind="status_changed", detail="offline", actor=actor, created_at=moment)
            for moment in moments
        )


def stored_event_times(device_id: int) -> list[datetime]:
    """Every Device Event ``created_at`` still stored, oldest first."""
    with session_scope() as session:
        return [
            value.replace(tzinfo=UTC)
            for value in session.scalars(
                select(DeviceEvent.created_at)
                .where(DeviceEvent.device_id == device_id)
                .order_by(DeviceEvent.created_at)
            )
        ]


@contextmanager
def sql_timeline(table: str) -> Iterator[list[str]]:
    """Record, in order, every ``DELETE`` against *table* and every commit.

    Real SQL rather than rows, for both halves of the batching rule, because a
    test that only asserts the rows are gone passes identically without either:

    * the ``DELETE`` markers count the statements, which the batch loop produces
      and a single unbounded delete does not;
    * the ``COMMIT`` markers between them are the reason batching exists at all —
      each batch is its own unit of work, so SQLite's write lock is released and
      the Poller and the load-profile job are never held off for the length of a
      purge. Collapsing the loop into one ``session_scope()`` leaves the
      statement count untouched and changes only these.
    """
    timeline: list[str] = []

    def record_delete(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        if statement.lstrip().upper().startswith("DELETE") and table in statement:
            timeline.append("DELETE")

    def record_commit(conn) -> None:  # noqa: ANN001 — a Connection, typed by the event.
        timeline.append("COMMIT")

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", record_delete)
    event.listen(engine, "commit", record_commit)
    try:
        yield timeline
    finally:
        event.remove(engine, "before_cursor_execute", record_delete)
        event.remove(engine, "commit", record_commit)


class TestTheCutoff:
    """90 days, strictly older. A row exactly on the cutoff instant is kept."""

    def test_interval_readings_older_than_the_cutoff_go_and_the_rest_stay(self, migrated_db: Settings) -> None:
        device_id = make_device()
        expired = NOW - timedelta(days=RETENTION_DAYS + 1)
        kept = NOW - timedelta(days=RETENTION_DAYS - 1)
        seed_readings(device_id, expired, kept)

        purge_expired(now=NOW)

        assert stored_read_ats(device_id) == [kept]

    def test_device_events_older_than_the_cutoff_go_and_the_rest_stay(self, migrated_db: Settings) -> None:
        """Cut on ``created_at``, the column that says when the event happened."""
        device_id = make_device()
        expired = NOW - timedelta(days=RETENTION_DAYS + 1)
        kept = NOW - timedelta(days=RETENTION_DAYS - 1)
        seed_events(device_id, expired, kept)

        purge_expired(now=NOW)

        assert stored_event_times(device_id) == [kept]

    def test_an_operator_action_expires_like_any_other_row(self, migrated_db: Settings) -> None:
        """SPEC §5 — Device Events go **uniformly**, ``actor`` and all.

        The owner took that decision knowing the cost, in as many words: after 90
        days there is no record of who paused a meter or cleared its data either.
        This test exists because the softer rule is the tempting one — a future
        reader meets the uniform delete, reads it as an oversight, and adds
        ``actor IS NULL`` to spare operator actions. Every other test in this file
        seeds ``actor=None``, so without this one that change goes unnoticed.
        """
        device_id = make_device()
        expired = NOW - timedelta(days=RETENTION_DAYS + 1)
        seed_events(device_id, expired)  # a status transition the machine wrote
        seed_events(device_id, expired + timedelta(seconds=1), actor="admin")  # a person paused the meter

        purge_expired(now=NOW)

        assert stored_event_times(device_id) == [], (
            "an operator action outlived the retention window — device_events is deleted uniformly (SPEC §5), "
            "and sparing rows that carry an actor is the softer rule the owner rejected"
        )

    def test_a_row_exactly_on_the_cutoff_instant_is_kept(self, migrated_db: Settings) -> None:
        """Strictly ``<``. The boundary microsecond decides which side a row is on.

        Asserted a microsecond either side of the instant, on both tables,
        because the whole of the rule is in that comparison operator.
        """
        device_id = make_device()
        cutoff = NOW - timedelta(days=RETENTION_DAYS)
        one_microsecond = timedelta(microseconds=1)
        seed_readings(device_id, cutoff - one_microsecond, cutoff, cutoff + one_microsecond)
        seed_events(device_id, cutoff - one_microsecond, cutoff, cutoff + one_microsecond)

        purge_expired(now=NOW)

        assert stored_read_ats(device_id) == [cutoff, cutoff + one_microsecond]
        assert stored_event_times(device_id) == [cutoff, cutoff + one_microsecond]


class TestThePurgeIsBatched:
    """One `session_scope()` per batch, so the write lock is released between them.

    The Poller and the load-profile job write to this database while retention
    runs. A single 2.6 M-row DELETE would hold SQLite's write lock for the whole
    purge and stall both of them; `_store` in `acquisition/load_profile.py`
    commits per chunk for the same reason.
    """

    def test_a_large_purge_takes_several_statements(self, migrated_db: Settings) -> None:
        device_id = make_device()
        expired = [NOW - timedelta(days=RETENTION_DAYS + 1, minutes=minute) for minute in range(25)]
        seed_readings(device_id, *expired)

        with sql_timeline("load_profile_readings") as timeline:
            purge_expired(now=NOW, batch_size=10)

        # 10 + 10 + 5, then the statement that finds nothing left and ends the
        # loop: the stop condition is a batch that deletes zero rows.
        deletes = timeline.count("DELETE")
        assert deletes == 4, f"25 expired rows went in {deletes} statement(s), not in batches of 10"
        assert stored_read_ats(device_id) == []

    def test_each_batch_commits_before_the_next_one_starts(self, migrated_db: Settings) -> None:
        """The statement count alone does not pin this: collapsing the loop into
        one ``session_scope()`` leaves four DELETEs and holds the write lock for
        the whole purge — ~1.6 s at the measured worst case, with the Poller and
        the load-profile job queued behind ``busy_timeout=5000``.
        """
        device_id = make_device()
        seed_readings(device_id, *[NOW - timedelta(days=RETENTION_DAYS + 1, minutes=m) for m in range(25)])

        with sql_timeline("load_profile_readings") as timeline:
            purge_expired(now=NOW, batch_size=10)

        # The readings purge runs first and entirely: four batches, each its own
        # committed unit of work. (What follows is the events table's own batch.)
        assert timeline[:8] == ["DELETE", "COMMIT"] * 4, (
            f"the batches did not commit one at a time — {timeline[:8]} — so the write lock is held across them"
        )


class TestRetentionCannotMoveTheWatermark:
    """ADR 0008 — the watermark is the data, and retention deletes the other end of it.

    The watermark is ``MIN`` over the per-logger ``MAX(read_at)``: the newest
    rows. Retention deletes the oldest. The one case where they meet is a device
    offline past the cutoff, which loses every row it had — and the correct
    answer there is a fresh 90-day backfill, not a gap and not an error.
    """

    def test_a_device_purged_empty_backfills_instead_of_failing(self, migrated_db: Settings) -> None:
        device_id = make_device("Long gone")
        seed_readings(device_id, NOW - timedelta(days=RETENTION_DAYS + 2), NOW - timedelta(days=RETENTION_DAYS + 1))

        purge_expired(now=NOW)
        assert stored_read_ats(device_id) == [], "the seeded rows were not all past the cutoff"

        # The real read path, not a private helper: what matters is the window
        # the meter is actually asked for on the next cycle.
        fake_meter_state().load_profile_windows.clear()
        read_and_store_load_profile(device_id, now=NOW)

        first_window_start = fake_meter_state().load_profile_windows[0][0]
        assert first_window_start == NOW - timedelta(days=LOAD_PROFILE_BACKFILL_DAYS), (
            f"the walk restarted from {first_window_start.isoformat()} — a device purged empty must backfill "
            f"from {LOAD_PROFILE_BACKFILL_DAYS} days back, which is what a NULL watermark means"
        )


class TestAnEmptyDatabase:
    """Day one of an install: the Scheduler runs every job on its first pass."""

    def test_purging_an_empty_database_removes_nothing_and_raises_nothing(self, migrated_db: Settings) -> None:
        device_id = make_device()

        with sql_timeline("load_profile_readings") as timeline:
            purge_expired(now=NOW)

        assert timeline.count("DELETE") == 1, "an empty table cost more than the one statement that found nothing"
        assert stored_read_ats(device_id) == []
        assert stored_event_times(device_id) == []
