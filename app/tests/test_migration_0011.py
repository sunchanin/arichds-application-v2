"""Migration 0011 — `battery_readings` (M7-2, issue #29).

Mirrors `test_migration_0010.py`'s shape: step to 0010, upgrade to head,
assert against the real SQLite file.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from arichds.config import Settings
from arichds.db.migrate import build_alembic_config, upgrade_to_head


@pytest.fixture
def db_at_0010(settings: Settings) -> Iterator[str]:
    command.upgrade(build_alembic_config(settings.db_url), "0010")
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


class TestBatteryReadingsTable:
    def test_the_columns_exist(self, db_at_0010: str) -> None:
        upgrade_to_head(db_at_0010)
        columns = {row["name"] for row in rows(db_at_0010, "PRAGMA table_info(battery_readings)")}
        assert columns == {"id", "device_id", "read_at", "status", "created_at"}

    def test_a_row_can_be_inserted_and_read_back(self, db_at_0010: str) -> None:
        upgrade_to_head(db_at_0010)
        device_id = seed_device(db_at_0010)
        execute(
            db_at_0010,
            "INSERT INTO battery_readings (device_id, read_at, status) VALUES (:device_id, '2026-08-11 04:00:00', '4321')",
            {"device_id": device_id},
        )
        row = rows(db_at_0010, "SELECT * FROM battery_readings")[0]
        assert row["status"] == "4321"

    def test_a_row_with_a_null_status_can_be_inserted(self, db_at_0010: str) -> None:
        """D4 — a successful read that yielded nothing still stores a row,
        with `status IS NULL`."""
        upgrade_to_head(db_at_0010)
        device_id = seed_device(db_at_0010)
        execute(
            db_at_0010,
            "INSERT INTO battery_readings (device_id, read_at) VALUES (:device_id, '2026-08-11 04:00:00')",
            {"device_id": device_id},
        )
        row = rows(db_at_0010, "SELECT * FROM battery_readings")[0]
        assert row["status"] is None

    def test_two_reads_at_the_same_device_and_read_at_collide(self, db_at_0010: str) -> None:
        """The unique constraint the day-guard upsert relies on."""
        upgrade_to_head(db_at_0010)
        device_id = seed_device(db_at_0010)
        execute(
            db_at_0010,
            "INSERT INTO battery_readings (device_id, read_at) VALUES (:device_id, '2026-08-11 04:00:00')",
            {"device_id": device_id},
        )
        with pytest.raises(IntegrityError):
            execute(
                db_at_0010,
                "INSERT INTO battery_readings (device_id, read_at) VALUES (:device_id, '2026-08-11 04:00:00')",
                {"device_id": device_id},
            )


class TestDowngrade:
    def test_the_table_is_gone(self, db_at_0010: str) -> None:
        upgrade_to_head(db_at_0010)
        command.downgrade(build_alembic_config(db_at_0010), "0010")

        tables = {row["name"] for row in rows(db_at_0010, "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "battery_readings" not in tables
