"""``db.load_profile_query`` — the shared Logger 1/2 merge (D-2, issue #30).

The full behavioural coverage of the merge (exact-match join, COALESCE
precedence, device isolation, no time window) already lives in
``test_api_load_profile.py::TestLoggerMerge`` and the CSV export tests,
exercised through both of this module's two callers. This file is the
direct, no-HTTP proof that :func:`merged_rows_select` itself carries the
rule, independent of either caller.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from arichds.config import Settings
from arichds.db.load_profile_query import (
    MERGED_COLUMNS,
    SKEW_CAP,
    merged_rows_cap,
    merged_rows_l1_max,
    merged_rows_select,
)
from arichds.db.models import Device, LoadProfileReading
from arichds.db.session import session_scope

BASE = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def make_device(name: str = "Main Incomer") -> int:
    with session_scope() as session:
        device = Device(
            name=name,
            brand="cewe",
            model="prometer100",
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="",
        )
        session.add(device)
        session.flush()
        return device.id


def seed(device_id: int, read_at: datetime, *, logger_id: int = 1, **columns: float) -> None:
    with session_scope() as session:
        session.add(
            LoadProfileReading(
                device_id=device_id,
                read_at=read_at,
                source="dlms",
                logger_id=logger_id,
                interval_sec=900,
                **columns,
            )
        )


class TestMergedColumnsOrder:
    def test_it_is_the_twenty_three_measurement_columns_in_the_pages_order(self) -> None:
        assert MERGED_COLUMNS == (
            "import_active_kwh",
            "import_reactive_kvarh",
            "export_active_kwh",
            "export_reactive_kvarh",
            "avg_geo_pf",
            "volt_l1",
            "volt_l2",
            "volt_l3",
            "current_l1",
            "current_l2",
            "current_l3",
            "freq",
            # M13, issue 06/07 — the eleven. `interval_status_flag` sits among
            # them and is the one non-measurement value here: a raw bitmap the
            # COALESCE treats like any other column, decoded only at render
            # time.
            "phase_angle_a",
            "phase_angle_b",
            "phase_angle_c",
            "interval_status_flag",
            "import_active_kw",
            "import_reactive_kvar",
            "export_active_kw",
            "export_reactive_kvar",
            "volt_l1_l2",
            "volt_l2_l3",
            "volt_l3_l1",
        )


class TestMergedRowsSelect:
    def test_logger_2_fills_a_column_logger_1_left_null(self, migrated_db: Settings) -> None:
        device_id = make_device()
        seed(device_id, BASE, logger_id=1, import_active_kwh=11.0)
        seed(device_id, BASE, logger_id=2, volt_l1=230.5)

        with session_scope() as session:
            rows = session.execute(merged_rows_select(device_id)).all()

        assert len(rows) == 1
        assert rows[0]._mapping["import_active_kwh"] == 11.0
        assert rows[0]._mapping["volt_l1"] == 230.5

    def test_logger_1_wins_the_collision(self, migrated_db: Settings) -> None:
        device_id = make_device()
        seed(device_id, BASE, logger_id=1, import_active_kwh=11.0)
        seed(device_id, BASE, logger_id=2, import_active_kwh=22.0)

        with session_scope() as session:
            rows = session.execute(merged_rows_select(device_id)).all()

        assert rows[0]._mapping["import_active_kwh"] == 11.0

    def test_a_logger_2_row_with_no_exact_read_at_match_is_dropped(self, migrated_db: Settings) -> None:
        from datetime import timedelta

        device_id = make_device()
        seed(device_id, BASE, logger_id=1, import_active_kwh=11.0)
        seed(device_id, BASE + timedelta(minutes=5), logger_id=2, import_active_kwh=99.0)

        with session_scope() as session:
            rows = session.execute(merged_rows_select(device_id)).all()

        assert len(rows) == 1
        assert rows[0]._mapping["import_active_kwh"] == 11.0

    def test_another_devices_rows_never_appear(self, migrated_db: Settings) -> None:
        mine = make_device("Mine")
        theirs = make_device("Theirs")
        seed(mine, BASE, import_active_kwh=1.0)
        seed(theirs, BASE, import_active_kwh=2.0)

        with session_scope() as session:
            rows = session.execute(merged_rows_select(mine)).all()

        assert len(rows) == 1
        assert rows[0]._mapping["import_active_kwh"] == 1.0

    def test_a_logger_2_only_instant_shows_nothing(self, migrated_db: Settings) -> None:
        device_id = make_device()
        seed(device_id, BASE, logger_id=2, import_active_kwh=99.0)

        with session_scope() as session:
            rows = session.execute(merged_rows_select(device_id)).all()

        assert rows == []


class TestTheSpinesFrontier:
    def test_a_device_with_no_logger_1_row_has_none(self, migrated_db: Settings) -> None:
        device_id = make_device()
        seed(device_id, BASE, logger_id=2, volt_l1_l2=400.0)

        with session_scope() as session:
            assert merged_rows_l1_max(session, device_id) is None

    def test_it_is_logger_1s_newest_read_at_as_aware_utc(self, migrated_db: Settings) -> None:
        device_id = make_device()
        seed(device_id, BASE)
        seed(device_id, BASE + timedelta(hours=1))
        seed(device_id, BASE + timedelta(hours=5), logger_id=2)

        with session_scope() as session:
            assert merged_rows_l1_max(session, device_id) == BASE + timedelta(hours=1)


class TestTheCapForAWriterThatNeverRewrites:
    """The load-profile walk reads Logger 1 to the present before Logger 2 gets
    more than a chunk per visit, so after a long backfill Logger 2 is days
    behind **while still arriving**. The CSV's daily rewrite repairs the rows
    the plain 24 h escape then releases half-empty; the Database Destination
    never rewrites a row, so for it the escape waits for a Logger 2 that has
    actually gone quiet (code review of ADR 0027, 2026-09-20)."""

    NOW = BASE + timedelta(days=5)
    L1_MAX = BASE + timedelta(days=5) - timedelta(minutes=15)
    L2_MAX = BASE + timedelta(days=1)

    def _seed(self, device_id: int, *, l2_stored_at: datetime) -> None:
        seed(device_id, self.L1_MAX, created_at=self.NOW)
        seed(device_id, self.L2_MAX, logger_id=2, created_at=l2_stored_at)

    def test_a_logger_2_that_is_days_behind_but_still_arriving_holds_the_rows(self, migrated_db: Settings) -> None:
        device_id = make_device()
        self._seed(device_id, l2_stored_at=self.NOW - timedelta(minutes=20))

        with session_scope() as session:
            cap = merged_rows_cap(session, device_id, self.L1_MAX, True, never_rewritten=True, now_utc=self.NOW)

        assert cap == self.L2_MAX

    def test_a_logger_2_that_has_stored_nothing_for_a_day_is_given_up_on(self, migrated_db: Settings) -> None:
        device_id = make_device()
        self._seed(device_id, l2_stored_at=self.NOW - SKEW_CAP - timedelta(minutes=1))

        with session_scope() as session:
            cap = merged_rows_cap(session, device_id, self.L1_MAX, True, never_rewritten=True, now_utc=self.NOW)

        assert cap == self.L1_MAX

    def test_the_csv_keeps_its_plain_escape(self, migrated_db: Settings) -> None:
        """Unchanged for the writer that heals itself: same rows, no flag."""
        device_id = make_device()
        self._seed(device_id, l2_stored_at=self.NOW - timedelta(minutes=20))

        with session_scope() as session:
            cap = merged_rows_cap(session, device_id, self.L1_MAX, True, now_utc=self.NOW)

        assert cap == self.L1_MAX

    def test_within_the_window_the_flag_changes_nothing(self, migrated_db: Settings) -> None:
        device_id = make_device()
        seed(device_id, self.L1_MAX, created_at=self.NOW)
        l2_max = self.L1_MAX - timedelta(hours=2)
        seed(device_id, l2_max, logger_id=2, created_at=self.NOW - timedelta(days=3))

        with session_scope() as session:
            cap = merged_rows_cap(session, device_id, self.L1_MAX, True, never_rewritten=True, now_utc=self.NOW)

        assert cap == l2_max
