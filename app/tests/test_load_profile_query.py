"""``db.load_profile_query`` — the shared Logger 1/2 merge (D-2, issue #30).

The full behavioural coverage of the merge (exact-match join, COALESCE
precedence, device isolation, no time window) already lives in
``test_api_load_profile.py::TestLoggerMerge`` and the CSV export tests,
exercised through both of this module's two callers. This file is the
direct, no-HTTP proof that :func:`merged_rows_select` itself carries the
rule, independent of either caller.
"""

from __future__ import annotations

from datetime import UTC, datetime

from arichds.config import Settings
from arichds.db.load_profile_query import MERGED_COLUMNS, merged_rows_select
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
    def test_it_is_the_twelve_measurement_columns_in_the_pages_order(self) -> None:
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
