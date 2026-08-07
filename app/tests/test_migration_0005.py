"""Migration 0005 — drop the 60 s rows, rename the table to what it holds (M3-4).

ADR 0007 stopped the Poller storing anything: the tick proves liveness and
writes no row. That leaves two jobs on disk, and the order between them matters
— delete first, rename second, so the DELETE names the table it was written
against.

1. **The ``interval='60s'`` rows go.** They are real values the meter reported,
   but nothing will ever read them, and leaving them means one table holds two
   kinds of row forever with every future reader having to know which is which.
2. **``interval_readings`` becomes ``load_profile_readings``.** After the
   deletion the table holds load profile and nothing else, and it is empty
   today — the cheapest moment there will ever be to rename it (M5 lands the
   real load-profile writer, M8 the push payload).

These tests step to 0004, write the pre-0005 world by hand, then upgrade — the
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
def db_at_0004(settings: Settings) -> Iterator[str]:
    """A database migrated to 0004 — the world as it was before M3-4."""
    command.upgrade(build_alembic_config(settings.db_url), "0004")
    yield settings.db_url


def rows(db_url: str, sql: str) -> list[dict]:
    """Run *sql* and return the rows as dicts."""
    engine = create_engine(db_url)
    with engine.connect() as conn:
        result = [dict(row) for row in conn.execute(text(sql)).mappings()]
    engine.dispose()
    return result


def names_of(db_url: str, kind: str) -> set[str]:
    """Every ``table`` or ``index`` name SQLite knows about."""
    return {row["name"] for row in rows(db_url, f"SELECT name FROM sqlite_master WHERE type = '{kind}'")}


def seed_pre_0005(db_url: str) -> int:
    """Write a device and one reading per interval label, as 0004 shaped them.

    Raw SQL on purpose: the ORM model has already been renamed, so going through
    it would describe the world *after* this migration rather than before it.
    """
    engine = create_engine(db_url)
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO devices (name, brand, model, transport, password, enabled, site_name) "
                "VALUES ('Main Incomer', 'cewe', 'prometer100', :transport, '', 1, 'Plant A')"
            ),
            {"transport": TRANSPORT},
        )
        device_id = int(result.lastrowid)
        for interval, volts in (("60s", 230.0), ("60s", 231.0), ("60s", 229.0), ("15m", 240.0)):
            conn.execute(
                text(
                    "INSERT INTO interval_readings (device_id, read_at, source, interval, volt_l1) "
                    "VALUES (:device_id, '2026-08-05 10:00:00', 'dlms', :interval, :volts)"
                ),
                {"device_id": device_id, "interval": interval, "volts": volts},
            )
    engine.dispose()
    return device_id


class TestTheSixtySecondRowsGo:
    @pytest.fixture
    def upgraded(self, db_at_0004: str) -> str:
        seed_pre_0005(db_at_0004)
        upgrade_to_head(db_at_0004)
        return db_at_0004

    def test_no_60s_row_survives(self, upgraded: str) -> None:
        surviving = rows(upgraded, "SELECT interval FROM load_profile_readings WHERE interval = '60s'")
        assert surviving == []

    def test_a_non_60s_row_is_left_alone(self, upgraded: str) -> None:
        """The DELETE is scoped to ``'60s'`` — M4b's Modbus cadences share this table.

        Without this, an unscoped ``DELETE FROM interval_readings`` would pass
        every other assertion in this file.
        """
        kept = rows(upgraded, "SELECT interval, volt_l1 FROM load_profile_readings")
        assert kept == [{"interval": "15m", "volt_l1": 240.0}]


class TestTheTableIsRenamed:
    @pytest.fixture
    def upgraded(self, db_at_0004: str) -> str:
        seed_pre_0005(db_at_0004)
        upgrade_to_head(db_at_0004)
        return db_at_0004

    def test_the_new_name_exists(self, upgraded: str) -> None:
        assert "load_profile_readings" in names_of(upgraded, "table")

    def test_the_old_name_is_gone(self, upgraded: str) -> None:
        assert "interval_readings" not in names_of(upgraded, "table")

    def test_the_columns_are_unchanged(self, upgraded: str) -> None:
        """A rename, not a reshape: ``interval`` and the V/I/freq columns stay."""
        columns = {row["name"] for row in rows(upgraded, "PRAGMA table_info(load_profile_readings)")}
        assert columns == {
            "id",
            "device_id",
            "read_at",
            "source",
            "interval",
            "volt_l1",
            "volt_l2",
            "volt_l3",
            "current_l1",
            "current_l2",
            "current_l3",
            "freq",
            "import_active_kwh",
            "created_at",
        }

    def test_both_indexes_carry_the_new_prefix(self, upgraded: str) -> None:
        """Both, not just the composite one.

        ``device_id`` is ``index=True`` on the model, so SQLAlchemy's implicit
        name is ``ix_<table>_device_id``. Renaming only the composite index
        would leave a migrated customer database silently disagreeing with the
        model's own metadata forever.
        """
        indexes = names_of(upgraded, "index")
        assert "ix_load_profile_readings_device_id" in indexes
        assert "ix_load_profile_readings_device_read_at" in indexes

    def test_neither_old_index_name_survives(self, upgraded: str) -> None:
        indexes = names_of(upgraded, "index")
        assert "ix_interval_readings_device_id" not in indexes
        assert "ix_interval_readings_device_read_at" not in indexes


class TestDowngrade:
    @pytest.fixture
    def downgraded(self, db_at_0004: str) -> str:
        seed_pre_0005(db_at_0004)
        upgrade_to_head(db_at_0004)
        command.downgrade(build_alembic_config(db_at_0004), "0004")
        return db_at_0004

    def test_the_old_table_name_is_back(self, downgraded: str) -> None:
        tables = names_of(downgraded, "table")
        assert "interval_readings" in tables
        assert "load_profile_readings" not in tables

    def test_both_old_index_names_are_back(self, downgraded: str) -> None:
        indexes = names_of(downgraded, "index")
        assert "ix_interval_readings_device_id" in indexes
        assert "ix_interval_readings_device_read_at" in indexes

    def test_the_deleted_rows_do_not_come_back(self, downgraded: str) -> None:
        # Deliberately one-way: 0005 reverses the *shape*, never the data. A
        # downgrade that resurrected the 60 s rows would have to have kept them
        # somewhere, which is exactly the "two kinds of row in one table" that
        # ADR 0007 removed.
        assert rows(downgraded, "SELECT interval FROM interval_readings") == [{"interval": "15m"}]
