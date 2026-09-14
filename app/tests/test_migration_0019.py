"""Migration 0019 — the `holiday_changes` table (ADR 0022, M14 ticket 06).

Mirrors `test_migration_0017.py`'s shape: step to 0018, upgrade to head,
assert against the real SQLite file. No device foreign key and no cascade
here — the calendar, and its change log, are machine-wide (no `device_id`,
same as `holidays` itself).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from arichds.config import Settings
from arichds.db.migrate import build_alembic_config, upgrade_to_head


@pytest.fixture
def db_at_0018(settings: Settings) -> Iterator[str]:
    """A database migrated to 0018 — the world as it was before M14 ticket 06."""
    command.upgrade(build_alembic_config(settings.db_url), "0018")
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


@pytest.fixture
def upgraded(db_at_0018: str) -> str:
    """A head-migrated database, ready to insert `holiday_changes` rows against."""
    upgrade_to_head(db_at_0018)
    return db_at_0018


class TestHolidayChangesTable:
    def test_the_columns_exist(self, upgraded: str) -> None:
        columns = {row["name"] for row in rows(upgraded, "PRAGMA table_info(holiday_changes)")}
        assert columns == {
            "id",
            "created_at",
            "username",
            "action",
            "holiday_kind",
            "holiday_name",
            "holiday_date",
            "holiday_month",
            "holiday_day",
            "count",
        }

    def test_a_single_holiday_row_can_be_inserted_and_read_back(self, upgraded: str) -> None:
        execute(
            upgraded,
            "INSERT INTO holiday_changes (created_at, username, action, holiday_kind, holiday_name, "
            "holiday_date, holiday_month, holiday_day, count) "
            "VALUES ('2026-09-14 00:00:00', 'admin', 'add', 'public', 'Test', '2026-09-14', NULL, NULL, NULL)",
        )

        row = rows(upgraded, "SELECT * FROM holiday_changes")[0]
        assert row["action"] == "add"
        assert row["holiday_date"] == "2026-09-14"
        assert row["count"] is None

    def test_an_import_row_carries_a_count_and_no_single_holiday_fields(self, upgraded: str) -> None:
        execute(
            upgraded,
            "INSERT INTO holiday_changes (created_at, username, action, count) "
            "VALUES ('2026-09-14 00:00:00', 'admin', 'import_csv', 3)",
        )

        row = rows(upgraded, "SELECT * FROM holiday_changes")[0]
        assert row["action"] == "import_csv"
        assert row["count"] == 3
        assert row["holiday_name"] is None


class TestDowngrade:
    def test_the_table_is_gone(self, db_at_0018: str) -> None:
        upgrade_to_head(db_at_0018)
        command.downgrade(build_alembic_config(db_at_0018), "0018")

        tables = {row["name"] for row in rows(db_at_0018, "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "holiday_changes" not in tables
