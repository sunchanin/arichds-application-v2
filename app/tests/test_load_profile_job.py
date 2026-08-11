"""The load-profile job (M5a-1) — watermark, windowing, upsert, budget.

Everything runs against ``FakeSmw110Driver``; nothing here touches a meter. The
driver's own read path was already validated against both live SMW110W4 units on
2026-08-07 (``docs/meter-notes/smw110w4-scan.md:162-202``) and is not re-litigated
here — this module is about the storage and the walk built on top of it.

**A correction about the recorded buffers, so nobody re-acquires the belief:**
they do **not** contain a full 24-hour window from either unit. The largest
recorded contiguous set is 24 rows over six hours per unit
(``raw/smw110w4-lp-readpath-{tcp,serial}-2026-08-07.txt``), printed elided, and
the one attempt at a 24-hour read *failed* — the meter answers
``Read-Write denied`` to ``readRowsByRange`` and takes entry access only
(``raw/smw110w4-tcp-probe-2026-08-07.txt:186-188``). So :data:`ANCHOR_ROW` below
is the one row that really was recorded, verbatim and pinned twice
(``raw/smw110w4-tcp-probe-2026-08-07.txt:179`` raw, ``smw110w4-scan.md:183-188``
engineering), and every longer span a windowing test needs is **synthesized** by
:func:`synthesized_rows` and labelled as such.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeMeterState
from sqlalchemy import func, select

from arichds.acquisition.drivers.base import IntervalReading
from arichds.acquisition.load_profile import read_and_store_load_profile
from arichds.acquisition.locks import EndpointLocks
from arichds.config import Settings
from arichds.constants import LOAD_PROFILE_BACKFILL_DAYS, SOURCE_DLMS
from arichds.db.models import Device, DeviceEvent, LoadProfileReading
from arichds.db.session import session_scope

pytestmark = pytest.mark.usefixtures("fake_meter")

#: A fixed "now" so every window in this module is arithmetic, not a clock race.
NOW = datetime(2026, 8, 7, 6, 0, tzinfo=UTC)

ENDPOINT = "127.0.0.1:4059"

#: The one row that was really recorded off the TCP unit — meter-local
#: ``2026-08-07 11:00`` = ``04:00`` UTC. Verbatim; do not "tidy" these numbers.
ANCHOR_ROW = IntervalReading(
    read_at=datetime(2026, 8, 7, 4, 0, tzinfo=UTC),
    source=SOURCE_DLMS,
    logger_id=1,
    interval_sec=900,
    volt_l1=228.188,
    volt_l2=225.989,
    volt_l3=228.127,
    current_l1=76.833,
    current_l2=76.993,
    current_l3=76.552,
    freq=None,
    import_active_kwh=13.130,
)


def synthesized_rows(*moments: datetime, logger_id: int = 1, kwh: float = 1.0) -> list[IntervalReading]:
    """Rows at *moments*. **Synthesized** — no meter ever produced these.

    The recorded buffers cover six hours; the walk has to be exercised over
    days, so the timestamps a multi-chunk test needs are invented here rather
    than attributed to a probe that never took them.
    """
    return [
        IntervalReading(
            read_at=moment,
            source=SOURCE_DLMS,
            logger_id=logger_id,
            interval_sec=900,
            import_active_kwh=kwh,
        )
        for moment in moments
    ]


def make_device(model: str = "smw110") -> int:
    """Insert one device on :data:`ENDPOINT` and return its id."""
    with session_scope() as session:
        device = Device(
            name="Main Incomer",
            brand="mitsu",
            model=model,
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="hunter2",
        )
        session.add(device)
        session.flush()
        return device.id


def store(device_id: int, rows: list[IntervalReading]) -> None:
    """Put rows in the table directly — the "already ingested" starting state."""
    with session_scope() as session:
        for row in rows:
            session.add(
                LoadProfileReading(
                    device_id=device_id,
                    read_at=row.read_at,
                    source=row.source,
                    logger_id=row.logger_id,
                    interval_sec=row.interval_sec,
                    **row.as_columns(),
                )
            )


def stored_rows(device_id: int) -> list[LoadProfileReading]:
    with session_scope() as session:
        return list(
            session.scalars(
                select(LoadProfileReading)
                .where(LoadProfileReading.device_id == device_id)
                .order_by(LoadProfileReading.read_at)
            )
        )


def max_read_at(device_id: int) -> datetime | None:
    with session_scope() as session:
        value = session.scalar(
            select(func.max(LoadProfileReading.read_at)).where(LoadProfileReading.device_id == device_id)
        )
    return value.replace(tzinfo=UTC) if value is not None else None


@pytest.fixture
def device_id(migrated_db: Settings) -> int:
    return make_device()


class TestTheUpsert:
    """D10 — the meter's latest answer wins, as in v1 (``INV-LP-01``)."""

    def test_reading_the_same_window_twice_stores_one_row(self, device_id: int, fake_meter: FakeMeterState) -> None:
        store(device_id, [ANCHOR_ROW])
        fake_meter.load_profile_rows = [ANCHOR_ROW]

        read_and_store_load_profile(device_id, now=NOW)
        read_and_store_load_profile(device_id, now=NOW)

        assert len(stored_rows(device_id)) == 1

    def test_a_changed_value_overwrites_the_stored_one(self, device_id: int, fake_meter: FakeMeterState) -> None:
        stale = IntervalReading(
            read_at=ANCHOR_ROW.read_at,
            source=SOURCE_DLMS,
            logger_id=1,
            interval_sec=900,
            volt_l1=1.0,
            import_active_kwh=0.0,
        )
        store(device_id, [stale])
        fake_meter.load_profile_rows = [ANCHOR_ROW]

        read_and_store_load_profile(device_id, now=NOW)

        rows = stored_rows(device_id)
        assert len(rows) == 1
        assert rows[0].volt_l1 == pytest.approx(228.188)
        assert rows[0].import_active_kwh == pytest.approx(13.130)

    def test_the_row_carries_the_drivers_logger_and_period(self, device_id: int, fake_meter: FakeMeterState) -> None:
        store(device_id, synthesized_rows(NOW - timedelta(hours=2)))
        fake_meter.load_profile_rows = [ANCHOR_ROW]

        read_and_store_load_profile(device_id, now=NOW)

        row = [r for r in stored_rows(device_id) if r.read_at.replace(tzinfo=UTC) == ANCHOR_ROW.read_at]
        assert len(row) == 1
        assert (row[0].logger_id, row[0].interval_sec) == (1, 900)


class TestTheWalkIsOldestFirst:
    """ADR 0008 — newest-first moves ``MAX(read_at)`` to today and the 90 days
    behind it are never read. Not negotiable while the watermark is the data."""

    def test_the_windows_ascend_and_start_at_the_watermark(self, device_id: int, fake_meter: FakeMeterState) -> None:
        watermark = NOW - timedelta(hours=60)
        store(device_id, synthesized_rows(watermark))

        read_and_store_load_profile(device_id, now=NOW)

        assert fake_meter.load_profile_windows == [
            (1, watermark, watermark + timedelta(hours=24)),
            (1, watermark + timedelta(hours=24), watermark + timedelta(hours=48)),
            (1, watermark + timedelta(hours=48), NOW),
        ]

    def test_each_chunk_is_stored_before_the_next_is_fetched(self, device_id: int, fake_meter: FakeMeterState) -> None:
        """The payoff for deriving the watermark from rows: a link that drops
        mid-walk keeps everything already fetched (ADR 0008)."""
        watermark = NOW - timedelta(hours=60)
        store(device_id, synthesized_rows(watermark))
        fake_meter.load_profile_rows = synthesized_rows(NOW - timedelta(hours=50), NOW - timedelta(hours=20))
        fake_meter.load_profile_fail_after = 1

        result = read_and_store_load_profile(device_id, now=NOW)

        assert result.error is not None
        assert result.stored == 1
        assert max_read_at(device_id) == NOW - timedelta(hours=50)

    def test_the_watermark_is_the_row_stored_not_the_window_asked_for(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """v1's seven-hour gap came from a job that recorded its nominal window."""
        watermark = NOW - timedelta(hours=60)
        store(device_id, synthesized_rows(watermark))
        fake_meter.load_profile_rows = synthesized_rows(NOW - timedelta(hours=50))
        fake_meter.load_profile_fail_after = 1

        result = read_and_store_load_profile(device_id, now=NOW)

        # The first chunk ASKED for [watermark, watermark + 24h].
        assert fake_meter.load_profile_windows[0][2] == watermark + timedelta(hours=24)
        assert result.through == NOW - timedelta(hours=50)


class TestWhereTheWalkStarts:
    def test_a_device_with_no_rows_starts_ninety_days_back(self, device_id: int, fake_meter: FakeMeterState) -> None:
        read_and_store_load_profile(device_id, now=NOW)

        _logger_id, first_start, _first_end = fake_meter.load_profile_windows[0]
        assert first_start == NOW - timedelta(days=LOAD_PROFILE_BACKFILL_DAYS)

    def test_a_device_with_rows_starts_at_its_watermark(self, device_id: int, fake_meter: FakeMeterState) -> None:
        store(device_id, synthesized_rows(NOW - timedelta(hours=10)))

        read_and_store_load_profile(device_id, now=NOW)

        assert fake_meter.load_profile_windows[0][1] == NOW - timedelta(hours=10)


class TestPerLoggerWatermarkAndWalk:
    """D2/D3/D4, M4c issue #24 — the per-logger read interface. Each logger's
    watermark, and therefore its own start, is independent of every other
    logger's. This is the fix for the gap load_profile.py's own docstring
    used to warn about: a device-wide/minimum watermark starves whichever
    logger is behind, or denies a fresh logger its own 90-day backfill."""

    def test_a_stalled_logger_does_not_hold_the_other_loggers_window_open(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """Logger 1 is far behind (a stall); Logger 2 is nearly caught up. Each
        must walk from its own watermark, not the minimum of the two."""
        fake_meter.load_profile_loggers = (1, 2)
        store(device_id, synthesized_rows(NOW - timedelta(hours=200), logger_id=1))
        store(device_id, synthesized_rows(NOW - timedelta(hours=2), logger_id=2))

        read_and_store_load_profile(device_id, now=NOW)

        logger_1_starts = [start for logger_id, start, _end in fake_meter.load_profile_windows if logger_id == 1]
        logger_2_starts = [start for logger_id, start, _end in fake_meter.load_profile_windows if logger_id == 2]
        assert logger_1_starts[0] == NOW - timedelta(hours=200)
        assert logger_2_starts[0] == NOW - timedelta(hours=2)
        # Mutation-tested: if the walk used min() across loggers (the old
        # device-wide rule), Logger 2 would start at Logger 1's watermark
        # (NOW - 200h) instead of its own (NOW - 2h) - this assertion would
        # then compare NOW - timedelta(hours=200) == NOW - timedelta(hours=2)
        # and fail, proving the assertion discriminates.

    def test_a_logger_with_no_rows_backfills_ninety_days_while_its_sibling_resumes(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """The fix for load_profile.py's own former warning: a logger seen
        for the first time after its sibling has been read for a while must
        still get its own full 90-day backfill, not be starved by the
        sibling's watermark."""
        fake_meter.load_profile_loggers = (1, 2)
        store(device_id, synthesized_rows(NOW - timedelta(hours=5), logger_id=1))
        # Logger 2 has never been read - no rows stored for it at all.

        read_and_store_load_profile(device_id, now=NOW)

        logger_1_starts = [start for logger_id, start, _end in fake_meter.load_profile_windows if logger_id == 1]
        logger_2_starts = [start for logger_id, start, _end in fake_meter.load_profile_windows if logger_id == 2]
        assert logger_1_starts[0] == NOW - timedelta(hours=5)
        assert logger_2_starts[0] == NOW - timedelta(days=LOAD_PROFILE_BACKFILL_DAYS)

    def test_through_reports_the_minimum_across_loggers(self, device_id: int, fake_meter: FakeMeterState) -> None:
        """D4 - a device-wide MAX would say "up to <leader's time>" while a
        stalled logger sat far behind; that over-reports coverage, which is
        exactly what ADR 0008 exists to prevent."""
        fake_meter.load_profile_loggers = (1, 2)
        fake_meter.load_profile_rows = [
            *synthesized_rows(NOW - timedelta(hours=48), NOW - timedelta(hours=24), logger_id=1),
            *synthesized_rows(NOW - timedelta(hours=6), logger_id=2),
        ]

        result = read_and_store_load_profile(device_id, now=NOW)

        assert result.through == NOW - timedelta(hours=24)

    def test_both_loggers_are_read_within_one_connect_disconnect_pair(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.load_profile_loggers = (1, 2)

        read_and_store_load_profile(device_id, now=NOW)

        assert fake_meter.connects == 1
        assert fake_meter.disconnects == 1
        logger_ids_seen = {logger_id for logger_id, _start, _end in fake_meter.load_profile_windows}
        assert logger_ids_seen == {1, 2}

    def test_the_first_chunk_of_every_logger_gets_through_even_with_no_budget(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """D3 - one shared budget for the whole call, not one per logger, but
        the first chunk of each logger is let through regardless, so a
        logger can always make progress against its own watermark."""
        fake_meter.load_profile_loggers = (1, 2)
        store(device_id, synthesized_rows(NOW - timedelta(hours=10), logger_id=1))
        store(device_id, synthesized_rows(NOW - timedelta(hours=10), logger_id=2))

        read_and_store_load_profile(device_id, now=NOW, budget_sec=0.0)

        logger_ids_seen = [logger_id for logger_id, _start, _end in fake_meter.load_profile_windows]
        assert logger_ids_seen == [1, 2]


class TestTheBudget:
    """D8 — a time budget, not a chunk count: nobody has measured how long one
    chunk takes on this hardware."""

    def test_it_stops_the_walk_but_never_before_the_first_chunk(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """A DLMS read cannot be interrupted mid-flight, and a call that reads
        nothing at all makes no progress — so chunk one always runs."""
        watermark = NOW - timedelta(hours=60)
        store(device_id, synthesized_rows(watermark))
        fake_meter.load_profile_rows = synthesized_rows(NOW - timedelta(hours=50), NOW - timedelta(hours=20))

        result = read_and_store_load_profile(device_id, now=NOW, budget_sec=0.0)

        assert len(fake_meter.load_profile_windows) == 1
        assert result.budget_exhausted is True
        assert result.error is None

    def test_a_second_call_picks_up_where_the_first_stopped(self, device_id: int, fake_meter: FakeMeterState) -> None:
        watermark = NOW - timedelta(hours=60)
        store(device_id, synthesized_rows(watermark))
        fake_meter.load_profile_rows = synthesized_rows(NOW - timedelta(hours=50), NOW - timedelta(hours=20))

        read_and_store_load_profile(device_id, now=NOW, budget_sec=0.0)
        fake_meter.load_profile_windows.clear()
        second = read_and_store_load_profile(device_id, now=NOW)

        assert fake_meter.load_profile_windows[0][1] == NOW - timedelta(hours=50)
        assert second.budget_exhausted is False
        assert max_read_at(device_id) == NOW - timedelta(hours=20)


class TestADriverWithoutALoadProfile:
    def test_it_reports_unsupported_and_touches_nothing(
        self, migrated_db: Settings, fake_meter: FakeMeterState
    ) -> None:
        """No lock taken and no connection opened: the endpoint is held by
        someone else here, so a job that reached for it would come back with a
        lock timeout instead of a clean answer."""
        prometer_id = make_device("prometer100")
        locks = EndpointLocks()
        assert locks.get(ENDPOINT).acquire_manual(timeout=0) is True

        result = read_and_store_load_profile(prometer_id, locks=locks, lock_timeout_sec=0.01, now=NOW)

        assert result.supported is False
        assert result.stored == 0
        assert result.error is None
        assert fake_meter.connects == 0
        assert fake_meter.load_profile_windows == []


class TestItNeverTouchesDeviceStatus:
    """D11 / ADR 0004 — status comes from the Poller and from nothing else. A
    failed load-profile read is a log line and, later, a gap on the Records
    page."""

    def test_a_successful_read_writes_no_device_event_and_moves_no_status(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        store(device_id, synthesized_rows(NOW - timedelta(hours=2)))
        fake_meter.load_profile_rows = [ANCHOR_ROW]

        read_and_store_load_profile(device_id, now=NOW)

        with session_scope() as session:
            device = session.get(Device, device_id)
            assert device is not None
            assert device.status == "unknown"
            assert device.status_checked_at is None
            assert device.consecutive_failures == 0
            assert session.scalars(select(DeviceEvent)).all() == []

    def test_a_failed_read_writes_no_device_event_and_moves_no_status(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.load_profile_error = TimeoutError("the meter went away")

        result = read_and_store_load_profile(device_id, now=NOW)

        assert result.error is not None
        with session_scope() as session:
            device = session.get(Device, device_id)
            assert device is not None
            assert device.status == "unknown"
            assert device.status_checked_at is None
            assert device.consecutive_failures == 0
            assert session.scalars(select(DeviceEvent)).all() == []


class TestFailuresBecomeSentences:
    def test_a_meter_failure_names_the_endpoint_and_never_escapes(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.load_profile_error = TimeoutError("the meter went away")

        result = read_and_store_load_profile(device_id, now=NOW)

        assert result.supported is True
        assert result.error is not None
        assert ENDPOINT in result.error
        assert "TimeoutError" in result.error

    def test_a_busy_endpoint_is_reported_as_the_line_not_the_meter(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """``probe.py`` draws the same distinction: a ``TimeoutError`` from
        ``manual()`` is the line, not the meter."""
        locks = EndpointLocks()
        assert locks.get(ENDPOINT).acquire_manual(timeout=0) is True

        result = read_and_store_load_profile(device_id, locks=locks, lock_timeout_sec=0.01, now=NOW)

        assert result.error is not None
        assert "busy" in result.error
        assert fake_meter.connects == 0

    def test_a_meter_that_refuses_the_association_is_a_sentence_too(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """``connect()`` fails outside the chunk loop, so it is a second error
        path rather than the same one."""
        fake_meter.connect_error = ConnectionRefusedError("refused")

        result = read_and_store_load_profile(device_id, now=NOW)

        assert result.supported is True
        assert result.stored == 0
        assert result.error is not None
        assert ENDPOINT in result.error
        assert "ConnectionRefusedError" in result.error
        assert fake_meter.load_profile_windows == []

    def test_an_unusable_transport_is_unsupported_not_a_crash(self, migrated_db: Settings) -> None:
        """The scheduler (#16) calls this without a probe in front of it, so
        an unbuildable driver has to come back as an answer rather than an
        exception."""
        with session_scope() as session:
            device = Device(
                name="Malformed", brand="mitsu", model="smw110", site_name="Plant A", transport={"kind": "net"}
            )
            session.add(device)
            session.flush()
            broken_id = device.id

        result = read_and_store_load_profile(broken_id, now=NOW)

        assert result.supported is False
        assert result.stored == 0
        assert result.error is not None

    def test_an_unknown_device_is_a_value_error(self, migrated_db: Settings) -> None:
        with pytest.raises(ValueError):
            read_and_store_load_profile(9999, now=NOW)


class TestAWatermarkAheadOfNow:
    def test_a_meter_clock_that_runs_ahead_reads_nothing_rather_than_backwards(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """``chunk_start >= end`` on the first iteration. The walk must produce
        no window at all — a negative-width chunk would ask the meter for a
        window running backwards."""
        store(device_id, synthesized_rows(NOW + timedelta(hours=3)))

        result = read_and_store_load_profile(device_id, now=NOW)

        assert fake_meter.load_profile_windows == []
        assert result.stored == 0
        assert result.error is None
        assert result.budget_exhausted is False
