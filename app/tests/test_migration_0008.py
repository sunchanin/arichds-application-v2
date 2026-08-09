"""Migration 0008 — the `settings` table (M6b, issue #22).

A brand-new key/value table — SPEC §4's eleven-table list, ADR 0010. Mirrors
``test_migration_0007.py``'s shape: step to 0007, upgrade to head, assert
against the real SQLite file.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from arichds.config import Settings
from arichds.db.migrate import build_alembic_config, upgrade_to_head


@pytest.fixture
def db_at_0007(settings: Settings) -> Iterator[str]:
    command.upgrade(build_alembic_config(settings.db_url), "0007")
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


class TestTheTableExists:
    def test_settings_is_created(self, db_at_0007: str) -> None:
        upgrade_to_head(db_at_0007)

        tables = {row["name"] for row in rows(db_at_0007, "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "settings" in tables

    def test_the_key_value_updated_at_columns_exist(self, db_at_0007: str) -> None:
        upgrade_to_head(db_at_0007)

        columns = {row["name"] for row in rows(db_at_0007, "PRAGMA table_info(settings)")}
        assert columns == {"key", "value", "updated_at"}


class TestKeyIsThePrimaryKey:
    def test_a_duplicate_key_is_rejected(self, db_at_0007: str) -> None:
        upgrade_to_head(db_at_0007)
        execute(db_at_0007, "INSERT INTO settings (key, value) VALUES ('capture_dir', '/a')")

        with pytest.raises(Exception, match="UNIQUE|PRIMARY KEY"):
            execute(db_at_0007, "INSERT INTO settings (key, value) VALUES ('capture_dir', '/b')")


class TestDowngrade:
    def test_the_table_is_gone(self, db_at_0007: str) -> None:
        upgrade_to_head(db_at_0007)
        command.downgrade(build_alembic_config(db_at_0007), "0007")

        tables = {row["name"] for row in rows(db_at_0007, "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "settings" not in tables
