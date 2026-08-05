"""Migration 0004 — `device_events` plus the device status columns (M3-2).

ADR 0004: status is derived from the Poller's ticks, so the columns that hold it
live on ``devices`` — including the strike counter, which must survive both
``poller.restart()`` and a Windows service restart (D1). ``device_events``
records transitions and operator actions only, never a per-tick heartbeat.

These tests step to 0003, write the pre-0004 world by hand, then upgrade — the
same sequence a real customer machine performs at service start.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from arichds.config import Settings
from arichds.db.migrate import build_alembic_config, upgrade_to_head

TRANSPORT = json.dumps({"kind": "net", "host": "127.0.0.1", "port": 4059})


@pytest.fixture
def db_at_0003(settings: Settings) -> Iterator[str]:
    """A database migrated to 0003 — the world as it was before M3-2."""
    command.upgrade(build_alembic_config(settings.db_url), "0003")
    yield settings.db_url


def insert_device(db_url: str, name: str = "Main Incomer", model: str = "prometer100") -> int:
    """Insert a pre-0004 device row with the 0003 column set only."""
    engine = create_engine(db_url)
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO devices (name, brand, model, transport, password, enabled, site_name) "
                "VALUES (:name, 'cewe', :model, :transport, '', 1, 'Plant A')"
            ),
            {"name": name, "model": model, "transport": TRANSPORT},
        )
        device_id = int(result.lastrowid)
    engine.dispose()
    return device_id


def rows(db_url: str, sql: str) -> list[dict]:
    """Run *sql* and return the rows as dicts."""
    engine = create_engine(db_url)
    with engine.connect() as conn:
        result = [dict(row) for row in conn.execute(text(sql)).mappings()]
    engine.dispose()
    return result


class TestDeviceEventsTable:
    @pytest.fixture
    def upgraded(self, db_at_0003: str) -> str:
        upgrade_to_head(db_at_0003)
        return db_at_0003

    def test_the_table_exists(self, upgraded: str) -> None:
        tables = {row["name"] for row in rows(upgraded, "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "device_events" in tables

    def test_it_has_the_columns_the_drawer_needs(self, upgraded: str) -> None:
        columns = {row["name"] for row in rows(upgraded, "PRAGMA table_info(device_events)")}
        assert columns == {"id", "device_id", "kind", "detail", "actor", "created_at"}

    def test_detail_and_actor_are_nullable(self, upgraded: str) -> None:
        """An automatic transition carries no actor (D11)."""
        nullable = {row["name"]: row["notnull"] for row in rows(upgraded, "PRAGMA table_info(device_events)")}
        assert nullable["detail"] == 0
        assert nullable["actor"] == 0

    def test_both_indexes_exist(self, upgraded: str) -> None:
        """Mirrors what ``interval_readings`` already does, for consistency."""
        names = {row["name"] for row in rows(upgraded, "SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "ix_device_events_device_id" in names
        assert "ix_device_events_device_created_at" in names

    def test_deleting_a_device_removes_its_events(self, upgraded: str) -> None:
        """The FK cascades — ``PRAGMA foreign_keys=ON`` is set per connection."""
        device_id = insert_device(upgraded)
        engine = create_engine(upgraded)
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(
                text("INSERT INTO device_events (device_id, kind) VALUES (:id, 'created')"),
                {"id": device_id},
            )
            conn.execute(text("DELETE FROM devices WHERE id = :id"), {"id": device_id})
            remaining = conn.execute(text("SELECT COUNT(*) FROM device_events")).scalar_one()
        engine.dispose()
        assert remaining == 0


class TestExistingDeviceRowsSurvive:
    @pytest.fixture
    def upgraded(self, db_at_0003: str) -> str:
        insert_device(db_at_0003, "Main Incomer")
        upgrade_to_head(db_at_0003)
        return db_at_0003

    def test_the_row_is_still_there(self, upgraded: str) -> None:
        assert [row["name"] for row in rows(upgraded, "SELECT name FROM devices")] == ["Main Incomer"]

    def test_status_is_backfilled_to_unknown(self, upgraded: str) -> None:
        """A NOT NULL column with a server_default fills existing rows on ADD."""
        assert rows(upgraded, "SELECT status FROM devices")[0]["status"] == "unknown"

    def test_the_strike_counter_starts_at_zero(self, upgraded: str) -> None:
        assert rows(upgraded, "SELECT consecutive_failures FROM devices")[0]["consecutive_failures"] == 0

    def test_the_nullable_status_columns_are_null(self, upgraded: str) -> None:
        row = rows(upgraded, "SELECT status_detail, status_checked_at FROM devices")[0]
        assert row == {"status_detail": None, "status_checked_at": None}


class TestDowngrade:
    def test_downgrade_removes_what_0004_added(self, db_at_0003: str) -> None:
        upgrade_to_head(db_at_0003)
        command.downgrade(build_alembic_config(db_at_0003), "0003")

        columns = {row["name"] for row in rows(db_at_0003, "PRAGMA table_info(devices)")}
        assert "status" not in columns
        assert "status_detail" not in columns
        assert "status_checked_at" not in columns
        assert "consecutive_failures" not in columns

        tables = {row["name"] for row in rows(db_at_0003, "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "device_events" not in tables

    def test_it_leaves_0003_intact(self, db_at_0003: str) -> None:
        """A downgrade must remove exactly what its upgrade added, and no more."""
        upgrade_to_head(db_at_0003)
        command.downgrade(build_alembic_config(db_at_0003), "0003")

        columns = {row["name"] for row in rows(db_at_0003, "PRAGMA table_info(devices)")}
        assert {"meter_serial", "site_name", "bill_day_31"} <= columns
        indexes = {row["name"] for row in rows(db_at_0003, "SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "ix_devices_meter_serial" in indexes
