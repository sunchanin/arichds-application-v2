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
from fakes import FakeMeterDriver, FakeMeterState, FakeSmw110Driver
from sqlalchemy import func, select

from arichds.acquisition.drivers.base import BillingReading, IntervalReading
from arichds.acquisition.load_profile import LoadProfileReadResult, read_and_store_load_profile
from arichds.acquisition.locks import EndpointLocks
from arichds.config import Settings
from arichds.constants import LOAD_PROFILE_BACKFILL_DAYS, LOAD_PROFILE_CHUNK_HOURS, SOURCE_DLMS
from arichds.db.app_settings import CAPTURE_DIR_KEY, set_setting
from arichds.db.models import BillingReading as BillingReadingRow
from arichds.db.models import Device, DeviceEvent, LoadProfileReading
from arichds.db.session import session_scope
from arichds.licensing.current import set_current_license_service
from arichds.licensing.service import LicenseState

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


def stored_billing_closed_count(device_id: int) -> int:
    with session_scope() as session:
        return len(
            session.scalars(
                select(BillingReadingRow).where(
                    BillingReadingRow.device_id == device_id, BillingReadingRow.record_status.is_(None)
                )
            ).all()
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


class TestHistoryRemains:
    """D9, issue #44 — `history_remains` is `budget_exhausted and advanced`,
    where `advanced` means the watermark itself moved — **not**
    `budget_exhausted and stored > 0`.

    Review round 1 found the `stored > 0` version does not actually close the
    hazard: the driver's window is inclusive on both bounds (module
    docstring), so the boundary row is re-read and re-upserted on every call.
    A meter whose entire remaining buffer is that one boundary row (a
    recording gap starting at our watermark — powered down or relocated for
    months while keeping its buffer) reports `stored=1` on every call
    forever, with the watermark never moving. `stored > 0` cannot see that;
    `advanced` — computed by comparing the per-logger watermark before the
    call to after it — can.
    """

    @pytest.mark.parametrize(
        ("budget_exhausted", "advanced", "expected"),
        [
            (True, True, True),
            (True, False, False),
            (False, True, False),
            (False, False, False),
        ],
    )
    def test_it_is_budget_exhausted_and_advanced(self, budget_exhausted: bool, advanced: bool, expected: bool) -> None:
        result = LoadProfileReadResult(
            supported=True,
            stored=1,
            through=None,
            budget_exhausted=budget_exhausted,
            error=None,
            advanced=advanced,
        )
        assert result.history_remains is expected

    def test_stored_plays_no_part_in_the_formula(self) -> None:
        """The boundary-row hazard itself: a call can report a large
        ``stored`` count (something was written — the boundary row, possibly
        several times over several loggers) while ``advanced=False`` (every
        watermark is exactly where it was before). ``stored`` must not leak
        back into the answer through any path."""
        result = LoadProfileReadResult(
            supported=True, stored=5, through=None, budget_exhausted=True, error=None, advanced=False
        )
        assert result.history_remains is False


class TestHistoryRemainsTerminatesOnABoundaryOnlyBuffer:
    """The blocker, review round 1 — the reviewer's own reproduction.

    A meter with a recording gap starting exactly at our watermark answers
    every chunk request with only the boundary row (inclusive-both-bounds
    filtering, ``FakeSmw110Driver.read_load_profile``'s own docstring mirrors
    ``smw110.py``). Before the fix, four consecutive calls each reported
    ``(stored=1, budget_exhausted=True, history_remains=True)`` with the
    watermark never advancing — a Manual Read that would press itself forever,
    each one outranking background work on that Transport Endpoint (ADR 0006).
    """

    def test_history_remains_is_false_when_only_the_boundary_row_comes_back(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        watermark = NOW - timedelta(hours=60)
        store(device_id, synthesized_rows(watermark))
        # The buffer holds exactly the boundary row and nothing newer.
        fake_meter.load_profile_rows = synthesized_rows(watermark)

        for attempt in range(4):
            result = read_and_store_load_profile(device_id, now=NOW, budget_sec=0.0)
            assert result.stored == 1, f"attempt {attempt}: the boundary row was not re-read"
            assert result.budget_exhausted is True, f"attempt {attempt}: expected the budget to be exhausted"
            assert result.history_remains is False, (
                f"attempt {attempt}: history_remains stayed true on a call that re-stored the same boundary "
                "row without the watermark moving — pressing again cannot make progress"
            )

        assert max_read_at(device_id) == watermark, "the watermark moved even though nothing new was ever stored"


class TestHistoryRemainsAdvancesFromNoWatermark:
    """Round 2 review — the never-read-logger branch of ``_advanced``.

    ``_advanced``'s ``before.get(logger_id) is None`` clause is what lets a
    logger with **no** watermark at all count as advanced the moment it
    gains any row. Nothing had pinned it: the blocker's own reproduction
    (``TestHistoryRemainsTerminatesOnABoundaryOnlyBuffer``, above) starts
    from an *existing* watermark, so it only ever exercises the
    ``mark_after > before[logger_id]`` half of the ``or``.

    This is the branch the feature exists for — ``create_device`` queues
    ``_read_initial_load_profile`` for a device with no watermark at all
    (issue #44's own D1/D4/D5), and an operator's first press on the Load
    Profile page for any device that has never been read hits the same
    path. A device with no stored rows backfills from
    ``NOW - LOAD_PROFILE_BACKFILL_DAYS`` (``_backfill_start``, since
    ``FakeSmw110Driver.load_profile_oldest_reading`` answers ``None``, the
    base-class "cannot say" default) — the first row seeded here sits inside
    that floor's own first chunk, so budget exhaustion after chunk one still
    genuinely advances the watermark from ``None``.
    """

    def test_a_first_ever_read_with_budget_left_over_reports_it_can_continue(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        floor = NOW - timedelta(days=LOAD_PROFILE_BACKFILL_DAYS)
        fake_meter.load_profile_rows = synthesized_rows(
            floor + timedelta(hours=1), floor + timedelta(hours=2), NOW - timedelta(days=10)
        )

        result = read_and_store_load_profile(device_id, now=NOW, budget_sec=0.0)

        assert result.stored == 2
        assert result.budget_exhausted is True
        assert result.advanced is True
        assert result.history_remains is True


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


class TestAMeterWhoseBufferIsShallowerThanTheBackfillWindow:
    """The customer-machine failure of 2026-08-11, and the reason
    :func:`~arichds.acquisition.load_profile._backfill_start` exists.

    A SMART TCC on serial 9600 held ~22 h of load profile. The walk starts at
    ``now - LOAD_PROFILE_BACKFILL_DAYS`` and steps ``LOAD_PROFILE_CHUNK_HOURS``
    at a time, and on that link an empty chunk cost ~3.3 s, so the 60 s budget
    bought 18 of the 90 chunks needed to reach the first row. Nothing was
    stored, so the watermark stayed ``None``, so the next cycle re-walked the
    same empty ninety days — nine times in the log, every one of them stopping
    within two days of the last:

        14:06:47 stopped on the shared budget at 2026-05-31T07:05:44
        15:43:02 stopped on the shared budget at 2026-05-31T08:42:00

    The first test below is the regression: it fails on the code that shipped.
    """

    def test_a_second_cycle_makes_progress_where_the_first_ran_out_of_budget(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """Two budget-limited cycles must not be the same cycle twice.

        The budget is set so a cycle cannot cross ninety days of empty window,
        which is the shipped behaviour on the real link. Without the clamp both
        cycles ask for the identical first chunk and store nothing forever.
        """
        oldest = NOW - timedelta(hours=22)
        fake_meter.load_profile_oldest = oldest
        fake_meter.load_profile_rows = synthesized_rows(NOW - timedelta(hours=2), NOW - timedelta(hours=1))

        first = read_and_store_load_profile(device_id, now=NOW, budget_sec=0.0)

        assert first.stored == 2, "the walk never reached the meter's data"
        assert fake_meter.load_profile_windows[0][1] >= oldest - timedelta(hours=LOAD_PROFILE_CHUNK_HOURS)

        second = read_and_store_load_profile(device_id, now=NOW, budget_sec=0.0)
        assert second.stored >= 1  # the boundary row is deliberately re-read and upserted
        assert fake_meter.load_profile_windows[-1][1] > oldest, "the second cycle restarted from the beginning"

    def test_the_oldest_entry_is_asked_for_only_while_backfilling(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """It costs a meter read, so a device with a watermark must not pay it
        every cycle."""
        fake_meter.load_profile_oldest = NOW - timedelta(hours=22)
        store(device_id, synthesized_rows(NOW - timedelta(hours=3)))
        fake_meter.oldest_reads = 0

        read_and_store_load_profile(device_id, now=NOW)

        assert fake_meter.oldest_reads == 0

    def test_a_driver_that_cannot_say_keeps_the_full_backfill_window(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """The base-class default is ``None``; every model that shipped before
        this change must walk exactly as it did."""
        fake_meter.load_profile_oldest = None

        read_and_store_load_profile(device_id, now=NOW, budget_sec=0.0)

        first_window_start = fake_meter.load_profile_windows[0][1]
        assert first_window_start == NOW - timedelta(days=LOAD_PROFILE_BACKFILL_DAYS)

    def test_a_refusal_falls_back_to_the_full_window_rather_than_failing_the_read(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """An optional hint must never break the read it exists to speed up."""
        fake_meter.load_profile_oldest_error = TimeoutError("the meter would not serve entry 1")

        result = read_and_store_load_profile(device_id, now=NOW, budget_sec=0.0)

        assert result.error is None
        assert fake_meter.load_profile_windows[0][1] == NOW - timedelta(days=LOAD_PROFILE_BACKFILL_DAYS)

    def test_a_meter_clock_in_the_future_cannot_narrow_the_walk_to_nothing(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """A nonsense answer must be ignored, not trusted into skipping data."""
        fake_meter.load_profile_oldest = NOW + timedelta(days=3)
        fake_meter.load_profile_rows = synthesized_rows(NOW - timedelta(hours=1))

        result = read_and_store_load_profile(device_id, now=NOW, budget_sec=0.0)

        assert fake_meter.load_profile_windows[0][1] == NOW - timedelta(days=LOAD_PROFILE_BACKFILL_DAYS)
        assert result.stored == 0  # the full walk is budget-bound, exactly as before


#: A closed period the Billing Change Check's own whole-buffer read (D6)
#: stores. Deliberately carrying no open row — the store path does not need
#: one to write a closed period.
_CLOSED_BILLING_ROW = BillingReading(
    bill_date=datetime(2026, 7, 31, 17, 0, 0, tzinfo=UTC),
    source=SOURCE_DLMS,
    is_open=False,
    meter_serial="1232002893",
    import_active_kwh_total=198685.030,
)


class TestBillingChangeCheckWiring:
    """D5-D9, issue #43, ADR 0018 — the Billing Change Check rides the Load
    Profile cycle's own connection, and when it fires, the whole-buffer
    billing read runs strictly after the Transport Endpoint lock is
    released."""

    def test_a_background_read_with_a_differing_signal_stores_billing_rows(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """D5/D6, mutation row 7 — a REAL EndpointLocks. If the whole-buffer
        read ran *inside* the Load Profile lock, `read_and_store_billing`'s
        own `background=True` acquisition would see the endpoint already
        held and silently return `skipped=True` — nothing would be stored.
        Asserting "it was called" would not catch that; asserting rows
        landed does."""
        locks = EndpointLocks()
        fake_meter.billing_newest_closed = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
        fake_meter.billing_rows = [_CLOSED_BILLING_ROW]

        read_and_store_load_profile(device_id, locks=locks, background=True, now=NOW)

        assert stored_billing_closed_count(device_id) == 1

    def test_an_unchanged_signal_never_calls_the_whole_buffer_read(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.billing_newest_closed = None  # base-class "cannot say" — never triggers
        fake_meter.billing_rows = [_CLOSED_BILLING_ROW]

        read_and_store_load_profile(device_id, background=True, now=NOW)

        assert fake_meter.billing_reads == 0
        assert stored_billing_closed_count(device_id) == 0

    def test_a_manual_read_never_runs_the_billing_read(self, device_id: int, fake_meter: FakeMeterState) -> None:
        """D7, mutation row 9 — the check is gated on the background path. A
        person pressing Read now must not silently grow a whole billing read
        plus capture-file writes on a path they are waiting on."""
        fake_meter.billing_newest_closed = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
        fake_meter.billing_rows = [_CLOSED_BILLING_ROW]

        read_and_store_load_profile(device_id, now=NOW)  # background=False — Read now

        assert fake_meter.billing_newest_closed_reads == 0
        assert stored_billing_closed_count(device_id) == 0

    def test_the_check_is_not_attempted_on_a_model_without_billing(
        self, device_id: int, fake_meter: FakeMeterState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A driver with a load profile but no billing profile must never
        even be asked — mirrors the real catalog (a driver's
        ``supports_billing()`` is what gates this, never a hardcoded model
        list, CLAUDE.md's "no if/elif on model" invariant)."""

        class _NoBillingDriver(FakeSmw110Driver):
            def supports_billing(self) -> bool:
                return False

        monkeypatch.setattr(
            "arichds.acquisition.drivers.factory._registry",
            lambda: {"prometer100": FakeMeterDriver, "smw110": _NoBillingDriver},
        )
        fake_meter.billing_newest_closed = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)

        read_and_store_load_profile(device_id, background=True, now=NOW)

        assert fake_meter.billing_newest_closed_reads == 0

    def test_the_check_is_not_attempted_when_the_endpoint_was_busy(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """A background tick that could not even take the endpoint (ADR 0006
        — skipped, never queued) must never reach the check."""
        locks = EndpointLocks()
        assert locks.get(ENDPOINT).acquire_manual(timeout=0) is True
        fake_meter.billing_newest_closed = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)

        result = read_and_store_load_profile(device_id, locks=locks, background=True, now=NOW)

        assert result.skipped is True
        assert fake_meter.billing_newest_closed_reads == 0

    def test_the_check_runs_after_the_walk_and_before_disconnect(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """D8, mutation row 10 — recorded call order, not just "it happened
        somewhere during the visit"."""
        fake_meter.billing_newest_closed = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)

        read_and_store_load_profile(device_id, background=True, now=NOW)

        order = fake_meter.call_order
        assert order[0] == "connect"
        assert order[-1] == "disconnect"
        last_walk_index = max(i for i, event in enumerate(order) if event == "read_load_profile")
        billing_check_index = order.index("billing_check")
        assert billing_check_index > last_walk_index
        assert billing_check_index < order.index("disconnect")

    def test_a_raising_check_does_not_break_the_walks_own_result(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """D9, mutation row 11 — an optional trigger must never break the
        Load Profile walk it rides on."""
        fake_meter.billing_newest_closed_error = RuntimeError("meter refused the billing profile")
        fake_meter.load_profile_rows = [ANCHOR_ROW]

        result = read_and_store_load_profile(device_id, background=True, now=NOW)

        assert result.error is None
        assert result.stored == 1
        assert fake_meter.billing_newest_closed_reads == 1  # the check WAS attempted, and it failed safely

    def test_the_whole_buffer_read_stores_rows_and_reaches_the_eager_capture_path(
        self, device_id: int, fake_meter: FakeMeterState, tmp_path
    ) -> None:
        """D6, mutation row 8 — proves it is genuinely
        ``read_and_store_billing`` that runs, not a bare
        ``driver.read_billing()`` bolted onto the Load Profile connection: a
        direct driver call would store nothing (no ``_store``/``_upsert_*``)
        and reach no eager capture (``_capture_new_closed_periods`` lives
        inside ``read_and_store_billing`` alone)."""

        class _StubLicenseService:
            def current_state(self) -> LicenseState:
                return LicenseState(state="active", reason=None, features=["billing", "auto_capture"])

        capture_dir = tmp_path / "captures"
        capture_dir.mkdir()
        with session_scope() as session:
            set_setting(session, CAPTURE_DIR_KEY, str(capture_dir))
        set_current_license_service(_StubLicenseService())
        try:
            fake_meter.billing_newest_closed = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
            fake_meter.billing_rows = [_CLOSED_BILLING_ROW]

            read_and_store_load_profile(device_id, background=True, now=NOW)
        finally:
            set_current_license_service(None)

        assert stored_billing_closed_count(device_id) == 1
        assert any(f.suffix == ".pdf" for f in capture_dir.rglob("*") if f.is_file())
