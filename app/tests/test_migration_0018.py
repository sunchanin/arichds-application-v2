"""Migration 0018 — dropping `devices.billing_exported_through` and
`devices.energy_exported_through` (M14 ticket 04, ADR 0023).

Mirrors `test_migration_0012.py`'s shape in reverse: step to 0017, seed a
device with both watermarks set, upgrade to head, assert the columns are gone
and the row survived, then downgrade back and assert the columns return
(nullable, since a downgrade cannot recover values a drop already discarded).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from arichds.config import Settings
from arichds.db.migrate import build_alembic_config, upgrade_to_head


@pytest.fixture
def db_at_0017(settings: Settings) -> Iterator[str]:
    command.upgrade(build_alembic_config(settings.db_url), "0017")
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
                "INSERT INTO devices (name, brand, model, transport, password, enabled, site_name, "
                "billing_exported_through, energy_exported_through) "
                "VALUES (:name, 'mitsu', 'smw110', '{}', '', 1, 'Plant A', "
                "'2026-08-01 00:00:00', '2026-08-01')"
            ),
            {"name": name},
        )
        device_id = int(result.lastrowid)
    engine.dispose()
    return device_id


class TestTheColumnsAreDropped:
    def test_the_columns_are_gone_after_upgrade(self, db_at_0017: str) -> None:
        device_id = seed_device(db_at_0017)
        upgrade_to_head(db_at_0017)

        columns = {row["name"] for row in rows(db_at_0017, "PRAGMA table_info(devices)")}
        assert "billing_exported_through" not in columns
        assert "energy_exported_through" not in columns
        _ = device_id

    def test_the_row_survives_the_upgrade(self, db_at_0017: str) -> None:
        device_id = seed_device(db_at_0017)
        upgrade_to_head(db_at_0017)

        row = rows(db_at_0017, f"SELECT name FROM devices WHERE id = {device_id}")[0]
        assert row["name"] == "Main Incomer"


class TestDowngrade:
    def test_the_columns_come_back_nullable(self, db_at_0017: str) -> None:
        seed_device(db_at_0017)
        upgrade_to_head(db_at_0017)
        command.downgrade(build_alembic_config(db_at_0017), "0017")

        columns = {row["name"]: row["notnull"] for row in rows(db_at_0017, "PRAGMA table_info(devices)")}
        assert columns["billing_exported_through"] == 0
        assert columns["energy_exported_through"] == 0

    def test_existing_rows_survive_the_round_trip(self, db_at_0017: str) -> None:
        device_id = seed_device(db_at_0017)
        upgrade_to_head(db_at_0017)
        command.downgrade(build_alembic_config(db_at_0017), "0017")

        names = [row["name"] for row in rows(db_at_0017, "SELECT name FROM devices")]
        assert names == ["Main Incomer"]
        _ = device_id
