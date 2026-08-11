"""Migration 0010 — `holidays` and `energy_register_readings` (M7-1, issue #28).

Mirrors `test_migration_0009.py`'s shape: step to 0009, upgrade to head,
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

ENERGY_COLUMNS = [
    f"{prefix}_{suffix}"
    for prefix in (
        "import_active_kwh",
        "export_active_kwh",
        "import_reactive_kvarh",
        "export_reactive_kvarh",
    )
    for suffix in ("total", "rate_a", "rate_b", "rate_c", "rate_d")
]


@pytest.fixture
def db_at_0009(settings: Settings) -> Iterator[str]:
    command.upgrade(build_alembic_config(settings.db_url), "0009")
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
                "VALUES (:name, 'mitsu', 'smw110', '{}', '', 1, 'Plant A')"
            ),
            {"name": name},
        )
        device_id = int(result.lastrowid)
    engine.dispose()
    return device_id


class TestHolidaysTable:
    def test_the_columns_exist(self, db_at_0009: str) -> None:
        upgrade_to_head(db_at_0009)
        columns = {row["name"] for row in rows(db_at_0009, "PRAGMA table_info(holidays)")}
        assert columns == {"id", "kind", "name", "date", "month", "day"}

    def test_two_public_holidays_on_the_same_date_are_refused(self, db_at_0009: str) -> None:
        upgrade_to_head(db_at_0009)
        execute(
            db_at_0009,
            "INSERT INTO holidays (kind, name, date) VALUES ('public', 'Makha Bucha', '2026-02-12')",
        )
        with pytest.raises(IntegrityError):
            execute(
                db_at_0009,
                "INSERT INTO holidays (kind, name, date) VALUES ('public', 'Duplicate', '2026-02-12')",
            )

    def test_two_annual_holidays_on_the_same_month_day_are_refused(self, db_at_0009: str) -> None:
        upgrade_to_head(db_at_0009)
        execute(
            db_at_0009,
            "INSERT INTO holidays (kind, name, month, day) VALUES ('annual', 'New Year', 1, 1)",
        )
        with pytest.raises(IntegrityError):
            execute(
                db_at_0009,
                "INSERT INTO holidays (kind, name, month, day) VALUES ('annual', 'Duplicate', 1, 1)",
            )

    def test_an_annual_and_a_public_row_may_share_a_calendar_day(self, db_at_0009: str) -> None:
        """The two partial indexes are independent — an annual `1/1` and a
        public `2026-01-01` do not collide, because the unique constraint on
        each is scoped to its own `kind` by the partial WHERE clause."""
        upgrade_to_head(db_at_0009)
        execute(
            db_at_0009,
            "INSERT INTO holidays (kind, name, month, day) VALUES ('annual', 'New Year', 1, 1)",
        )
        execute(
            db_at_0009,
            "INSERT INTO holidays (kind, name, date) VALUES ('public', 'New Year 2026', '2026-01-01')",
        )
        assert len(rows(db_at_0009, "SELECT * FROM holidays")) == 2


class TestEnergyRegisterReadingsTable:
    def test_the_twenty_measurement_columns_exist(self, db_at_0009: str) -> None:
        upgrade_to_head(db_at_0009)
        columns = {row["name"] for row in rows(db_at_0009, "PRAGMA table_info(energy_register_readings)")}
        assert set(ENERGY_COLUMNS) <= columns

    def test_the_table_has_exactly_the_expected_columns(self, db_at_0009: str) -> None:
        upgrade_to_head(db_at_0009)
        columns = {row["name"] for row in rows(db_at_0009, "PRAGMA table_info(energy_register_readings)")}
        expected_keys = {"id", "device_id", "read_at", "source", "meter_serial", "created_at", "updated_at"}
        assert columns == expected_keys | set(ENERGY_COLUMNS)

    def test_a_row_can_be_inserted_and_read_back(self, db_at_0009: str) -> None:
        upgrade_to_head(db_at_0009)
        device_id = seed_device(db_at_0009)
        execute(
            db_at_0009,
            "INSERT INTO energy_register_readings (device_id, read_at, source, import_active_kwh_total) "
            "VALUES (:device_id, '2026-08-11 04:00:00', 'dlms', 1066.62)",
            {"device_id": device_id},
        )
        row = rows(db_at_0009, "SELECT * FROM energy_register_readings")[0]
        assert row["import_active_kwh_total"] == pytest.approx(1066.62)

    def test_two_reads_at_the_same_device_and_read_at_collide(self, db_at_0009: str) -> None:
        """The unique constraint the upsert relies on (decision 10) — this is
        the database-level half of "two clicks in one second are one row"."""
        upgrade_to_head(db_at_0009)
        device_id = seed_device(db_at_0009)
        execute(
            db_at_0009,
            "INSERT INTO energy_register_readings (device_id, read_at, source) "
            "VALUES (:device_id, '2026-08-11 04:00:00', 'dlms')",
            {"device_id": device_id},
        )
        with pytest.raises(IntegrityError):
            execute(
                db_at_0009,
                "INSERT INTO energy_register_readings (device_id, read_at, source) "
                "VALUES (:device_id, '2026-08-11 04:00:00', 'dlms')",
                {"device_id": device_id},
            )


class TestDowngrade:
    def test_both_tables_are_gone(self, db_at_0009: str) -> None:
        upgrade_to_head(db_at_0009)
        command.downgrade(build_alembic_config(db_at_0009), "0009")

        tables = {row["name"] for row in rows(db_at_0009, "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "holidays" not in tables
        assert "energy_register_readings" not in tables
