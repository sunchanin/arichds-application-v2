"""Migration 0021 — `billing_readings.captured_at` (ui-audit ticket 03).

Step to 0020, seed a closed period, upgrade to head: the column exists,
nullable, and the existing row reads back NULL — no backfill from file
timestamps. Downgrade drops it again.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from arichds.config import Settings
from arichds.db.migrate import build_alembic_config, upgrade_to_head


@pytest.fixture
def db_at_0020(settings: Settings) -> Iterator[str]:
    command.upgrade(build_alembic_config(settings.db_url), "0020")
    yield settings.db_url


def rows(db_url: str, sql: str) -> list[dict]:
    engine = create_engine(db_url)
    with engine.connect() as conn:
        result = [dict(row) for row in conn.execute(text(sql)).mappings()]
    engine.dispose()
    return result


def seed(db_url: str) -> None:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO devices (name, brand, model, transport, password, enabled, site_name) "
                "VALUES ('Main', 'cewe', 'prometer100', '{}', '', 1, 'Plant A')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO billing_readings (device_id, bill_date, read_at, source, meter_serial) "
                "VALUES (1, '2026-07-31 17:00:00', '2026-08-01 02:00:00', 'dlms', 'SN-1')"
            )
        )
    engine.dispose()


class TestTheColumnIsAdded:
    def test_it_exists_nullable_and_existing_rows_read_null(self, db_at_0020: str) -> None:
        seed(db_at_0020)
        upgrade_to_head(db_at_0020)

        columns = {row["name"]: row["notnull"] for row in rows(db_at_0020, "PRAGMA table_info(billing_readings)")}
        assert columns["captured_at"] == 0
        assert rows(db_at_0020, "SELECT captured_at FROM billing_readings")[0]["captured_at"] is None


class TestDowngrade:
    def test_the_column_is_dropped_and_the_row_survives(self, db_at_0020: str) -> None:
        seed(db_at_0020)
        upgrade_to_head(db_at_0020)
        command.downgrade(build_alembic_config(db_at_0020), "0020")

        columns = {row["name"] for row in rows(db_at_0020, "PRAGMA table_info(billing_readings)")}
        assert "captured_at" not in columns
        assert len(rows(db_at_0020, "SELECT id FROM billing_readings")) == 1
