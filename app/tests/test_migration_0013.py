"""Migration 0013 — `devices.meter_activation_code` (ADR 0019, issue #42).

Mirrors `test_migration_0012.py`'s shape: step to 0012, upgrade to head,
assert against the real SQLite file, then downgrade back.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from arichds.config import Settings
from arichds.db.migrate import build_alembic_config, upgrade_to_head


@pytest.fixture
def db_at_0012(settings: Settings) -> Iterator[str]:
    command.upgrade(build_alembic_config(settings.db_url), "0012")
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


class TestMeterActivationCodeColumn:
    def test_the_column_exists_and_is_nullable(self, db_at_0012: str) -> None:
        upgrade_to_head(db_at_0012)
        columns = {row["name"]: row["notnull"] for row in rows(db_at_0012, "PRAGMA table_info(devices)")}
        assert "meter_activation_code" in columns
        assert columns["meter_activation_code"] == 0

    def test_an_existing_row_survives_the_upgrade_with_a_null_code(self, db_at_0012: str) -> None:
        device_id = seed_device(db_at_0012)
        upgrade_to_head(db_at_0012)

        row = rows(db_at_0012, f"SELECT * FROM devices WHERE id = {device_id}")[0]
        assert row["meter_activation_code"] is None

    def test_a_value_can_be_written_and_read_back(self, db_at_0012: str) -> None:
        upgrade_to_head(db_at_0012)
        device_id = seed_device(db_at_0012)
        execute(
            db_at_0012,
            "UPDATE devices SET meter_activation_code = :code WHERE id = :id",
            {"code": "eyJhIjoxfQ.c2ln", "id": device_id},
        )
        row = rows(db_at_0012, f"SELECT meter_activation_code FROM devices WHERE id = {device_id}")[0]
        assert row["meter_activation_code"] == "eyJhIjoxfQ.c2ln"


class TestDowngrade:
    def test_the_column_is_gone(self, db_at_0012: str) -> None:
        upgrade_to_head(db_at_0012)
        command.downgrade(build_alembic_config(db_at_0012), "0012")

        columns = {row["name"] for row in rows(db_at_0012, "PRAGMA table_info(devices)")}
        assert "meter_activation_code" not in columns

    def test_existing_rows_survive_the_round_trip(self, db_at_0012: str) -> None:
        device_id = seed_device(db_at_0012)
        upgrade_to_head(db_at_0012)
        command.downgrade(build_alembic_config(db_at_0012), "0012")

        names = [row["name"] for row in rows(db_at_0012, "SELECT name FROM devices")]
        assert names == ["Main Incomer"]
        _ = device_id
