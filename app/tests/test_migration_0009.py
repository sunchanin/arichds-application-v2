"""Migration 0009 — twenty new `billing_readings` columns (M4c, issue #24).

Demand Time (x2 groups) and Cumulative Demand (x2 groups), each
total + rate_a..d — the columns v1's screen has always shown but v2's schema
didn't carry until this issue (D10). Mirrors ``test_migration_0007.py``'s
shape: step to 0008, upgrade to head, assert against the real SQLite file.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from arichds.config import Settings
from arichds.db.migrate import build_alembic_config, upgrade_to_head

NEW_COLUMNS = [
    f"{prefix}_{suffix}"
    for prefix in (
        "max_demand_import_active_time",
        "max_demand_import_reactive_time",
        "cumul_demand_import_active_kw",
        "cumul_demand_import_reactive_kvar",
    )
    for suffix in ("total", "rate_a", "rate_b", "rate_c", "rate_d")
]


@pytest.fixture
def db_at_0008(settings: Settings) -> Iterator[str]:
    command.upgrade(build_alembic_config(settings.db_url), "0008")
    yield settings.db_url


def rows(db_url: str, sql: str) -> list[dict]:
    engine = create_engine(db_url)
    with engine.connect() as conn:
        result = [dict(row) for row in conn.execute(text(sql)).mappings()]
    engine.dispose()
    return result


def execute(db_url: str, sql: str, params: dict | None = None) -> None:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})
    engine.dispose()


def seed_device(db_url: str, name: str = "Main Incomer") -> int:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO devices (name, brand, model, transport, password, enabled, site_name) "
                "VALUES (:name, 'cewe', 'prometer100', '{}', '', 1, 'Plant A')"
            ),
            {"name": name},
        )
        device_id = int(result.lastrowid)
    engine.dispose()
    return device_id


class TestTheColumnsExist:
    def test_the_twenty_new_columns_are_added(self, db_at_0008: str) -> None:
        upgrade_to_head(db_at_0008)

        columns = {row["name"] for row in rows(db_at_0008, "PRAGMA table_info(billing_readings)")}
        assert set(NEW_COLUMNS) <= columns

    def test_the_table_now_has_sixty_measurement_columns_plus_keys(self, db_at_0008: str) -> None:
        upgrade_to_head(db_at_0008)

        columns = {row["name"] for row in rows(db_at_0008, "PRAGMA table_info(billing_readings)")}
        expected_keys = {
            "id",
            "device_id",
            "bill_date",
            "read_at",
            "record_status",
            "source",
            "meter_serial",
            "created_at",
            "updated_at",
        }
        assert len(columns) == len(expected_keys) + 60

    def test_existing_rows_survive_with_null_new_columns(self, db_at_0008: str) -> None:
        device_id = seed_device(db_at_0008)
        execute(
            db_at_0008,
            "INSERT INTO billing_readings (device_id, bill_date, read_at, record_status, source, "
            "import_active_kwh_total) VALUES (:device_id, '2026-07-01 00:00:00', '2026-07-01 00:00:00', "
            "NULL, 'dlms', 12345.6)",
            {"device_id": device_id},
        )

        upgrade_to_head(db_at_0008)

        row = rows(db_at_0008, "SELECT * FROM billing_readings")[0]
        assert row["import_active_kwh_total"] == pytest.approx(12345.6)
        for column in NEW_COLUMNS:
            assert row[column] is None


class TestTheDemandTimeColumnsAreDatetime:
    def test_a_datetime_string_round_trips(self, db_at_0008: str) -> None:
        upgrade_to_head(db_at_0008)
        device_id = seed_device(db_at_0008)
        execute(
            db_at_0008,
            "INSERT INTO billing_readings (device_id, bill_date, read_at, record_status, source, "
            "max_demand_import_active_time_total) VALUES "
            "(:device_id, '2026-08-07 04:37:58', '2026-08-07 04:37:58', NULL, 'dlms', '2026-08-05 09:12:00')",
            {"device_id": device_id},
        )

        row = rows(db_at_0008, "SELECT max_demand_import_active_time_total FROM billing_readings")[0]
        assert row["max_demand_import_active_time_total"] == "2026-08-05 09:12:00"


class TestDowngrade:
    def test_the_columns_are_gone(self, db_at_0008: str) -> None:
        seed_device(db_at_0008)
        upgrade_to_head(db_at_0008)
        command.downgrade(build_alembic_config(db_at_0008), "0008")

        columns = {row["name"] for row in rows(db_at_0008, "PRAGMA table_info(billing_readings)")}
        assert not (set(NEW_COLUMNS) & columns)
