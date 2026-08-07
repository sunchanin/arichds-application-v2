"""Migration 0006 — the load-profile schema M5a-1 writes against.

Three changes, and each one has to survive a database that already holds rows:

1. **``logger_id`` and ``interval_sec`` arrive NOT NULL**, with server defaults
   ``1`` and ``900``. The defaults exist so the ``ALTER`` cannot fail on a
   non-empty table — every write supplies both values explicitly, so a default
   never lands on a row the job wrote. ``1`` / ``900`` is the only shape a
   surviving pre-0006 row could have had: one logger, 900 s on every model
   scanned so far.
2. **``interval`` (the String cadence label) goes.** Nothing ever read it, and
   ``interval_sec`` carries the meter's own capture period instead.
3. **``(device_id, logger_id, read_at)`` becomes unique**, which is what makes
   the job's re-read of the watermark row an upsert rather than a duplicate.

These tests step to 0005, write the pre-0006 world by hand, then upgrade — the
same sequence a real customer machine performs at service start.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from arichds.config import Settings
from arichds.db.migrate import build_alembic_config, upgrade_to_head

TRANSPORT = json.dumps({"kind": "net", "host": "127.0.0.1", "port": 4059})

#: Every column ``load_profile_readings`` carries after 0006 — twelve
#: measurement columns plus the five keys and ``created_at`` (SPEC §3.5).
COLUMNS_AT_0006 = {
    "id",
    "device_id",
    "read_at",
    "source",
    "logger_id",
    "interval_sec",
    "volt_l1",
    "volt_l2",
    "volt_l3",
    "current_l1",
    "current_l2",
    "current_l3",
    "freq",
    "import_active_kwh",
    "import_reactive_kvarh",
    "export_active_kwh",
    "export_reactive_kvarh",
    "avg_geo_pf",
    "created_at",
}


@pytest.fixture
def db_at_0005(settings: Settings) -> Iterator[str]:
    """A database migrated to 0005 — the world as it was before M5a-1."""
    command.upgrade(build_alembic_config(settings.db_url), "0005")
    yield settings.db_url


def rows(db_url: str, sql: str) -> list[dict]:
    """Run *sql* and return the rows as dicts."""
    engine = create_engine(db_url)
    with engine.connect() as conn:
        result = [dict(row) for row in conn.execute(text(sql)).mappings()]
    engine.dispose()
    return result


def execute(db_url: str, sql: str, params: dict | None = None) -> None:
    """Run one statement, committing it."""
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})
    engine.dispose()


def seed_pre_0006(db_url: str) -> int:
    """Write a device and one reading, as 0005 shaped them.

    Raw SQL on purpose: the ORM model already describes the world *after* this
    migration, so going through it would prove nothing about the world before.
    """
    engine = create_engine(db_url)
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO devices (name, brand, model, transport, password, enabled, site_name) "
                "VALUES ('Main Incomer', 'mitsu', 'smw110', :transport, '', 1, 'Plant A')"
            ),
            {"transport": TRANSPORT},
        )
        device_id = int(result.lastrowid)
        conn.execute(
            text(
                "INSERT INTO load_profile_readings (device_id, read_at, source, interval, volt_l1) "
                "VALUES (:device_id, '2026-08-07 04:00:00', 'dlms', '15m', 228.188)"
            ),
            {"device_id": device_id},
        )
    engine.dispose()
    return device_id


class TestAnEmptyTable:
    """The case every developer machine and every fresh install is in."""

    @pytest.fixture
    def upgraded(self, db_at_0005: str) -> str:
        upgrade_to_head(db_at_0005)
        return db_at_0005

    def test_the_column_set_is_exactly_the_m5_shape(self, upgraded: str) -> None:
        columns = {row["name"] for row in rows(upgraded, "PRAGMA table_info(load_profile_readings)")}
        assert columns == COLUMNS_AT_0006

    def test_the_interval_label_column_is_gone(self, upgraded: str) -> None:
        columns = {row["name"] for row in rows(upgraded, "PRAGMA table_info(load_profile_readings)")}
        assert "interval" not in columns

    def test_logger_id_and_interval_sec_are_not_null(self, upgraded: str) -> None:
        """``NULL`` is unusable for ``logger_id``: SQLite treats ``NULL != NULL``,
        so a nullable column would make the unique key stop preventing duplicates
        (SPEC §3.5)."""
        info = {row["name"]: row for row in rows(upgraded, "PRAGMA table_info(load_profile_readings)")}
        assert info["logger_id"]["notnull"] == 1
        assert info["interval_sec"]["notnull"] == 1

    def test_both_existing_indexes_survive(self, upgraded: str) -> None:
        names = {row["name"] for row in rows(upgraded, "SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "ix_load_profile_readings_device_id" in names
        assert "ix_load_profile_readings_device_read_at" in names


class TestATableWithRows:
    """The case a customer machine is in — the one that can actually fail."""

    @pytest.fixture
    def upgraded(self, db_at_0005: str) -> tuple[str, int]:
        device_id = seed_pre_0006(db_at_0005)
        upgrade_to_head(db_at_0005)
        return db_at_0005, device_id

    def test_the_row_survives(self, upgraded: tuple[str, int]) -> None:
        db_url, _device_id = upgraded
        assert rows(db_url, "SELECT volt_l1 FROM load_profile_readings") == [{"volt_l1": 228.188}]

    def test_the_server_defaults_fill_the_surviving_row(self, upgraded: tuple[str, int]) -> None:
        """The migration must not invent per-row values it cannot know — the
        defaults are the only shape a pre-0006 row could have had."""
        db_url, _device_id = upgraded
        assert rows(db_url, "SELECT logger_id, interval_sec FROM load_profile_readings") == [
            {"logger_id": 1, "interval_sec": 900}
        ]

    def test_the_new_measurement_columns_are_empty(self, upgraded: tuple[str, int]) -> None:
        db_url, _device_id = upgraded
        assert rows(
            db_url,
            "SELECT import_reactive_kvarh, export_active_kwh, export_reactive_kvarh, avg_geo_pf "
            "FROM load_profile_readings",
        ) == [
            {
                "import_reactive_kvarh": None,
                "export_active_kwh": None,
                "export_reactive_kvarh": None,
                "avg_geo_pf": None,
            }
        ]


class TestTheUniqueKey:
    @pytest.fixture
    def upgraded(self, db_at_0005: str) -> tuple[str, int]:
        device_id = seed_pre_0006(db_at_0005)
        upgrade_to_head(db_at_0005)
        return db_at_0005, device_id

    def test_a_duplicate_device_logger_read_at_is_rejected(self, upgraded: tuple[str, int]) -> None:
        """Asserted on the ``IntegrityError``, not on the DDL text: a constraint
        that exists but does not fire is the failure this has to catch."""
        db_url, device_id = upgraded
        with pytest.raises(IntegrityError):
            execute(
                db_url,
                "INSERT INTO load_profile_readings (device_id, read_at, source, logger_id, interval_sec) "
                "VALUES (:device_id, '2026-08-07 04:00:00', 'dlms', 1, 900)",
                {"device_id": device_id},
            )

    def test_the_same_read_at_on_another_logger_is_allowed(self, upgraded: tuple[str, int]) -> None:
        """SPEC §3.5: Logger 1 and Logger 2 are *separate rows*, not a merge."""
        db_url, device_id = upgraded
        execute(
            db_url,
            "INSERT INTO load_profile_readings (device_id, read_at, source, logger_id, interval_sec) "
            "VALUES (:device_id, '2026-08-07 04:00:00', 'dlms', 2, 300)",
            {"device_id": device_id},
        )
        assert len(rows(db_url, "SELECT id FROM load_profile_readings")) == 2


class TestDowngrade:
    @pytest.fixture
    def downgraded(self, db_at_0005: str) -> str:
        seed_pre_0006(db_at_0005)
        upgrade_to_head(db_at_0005)
        command.downgrade(build_alembic_config(db_at_0005), "0005")
        return db_at_0005

    def test_the_label_column_is_back_and_the_m5_columns_are_gone(self, downgraded: str) -> None:
        columns = {row["name"] for row in rows(downgraded, "PRAGMA table_info(load_profile_readings)")}
        assert "interval" in columns
        assert {"logger_id", "interval_sec", "avg_geo_pf"} & columns == set()

    def test_the_row_survives_the_round_trip(self, downgraded: str) -> None:
        # The shape reverses; the data does not come back. The cadence label is
        # unrecoverable — 0006 dropped it — so ``interval`` returns empty rather
        # than being back-filled with a value this migration cannot know.
        assert rows(downgraded, "SELECT volt_l1, interval FROM load_profile_readings") == [
            {"volt_l1": 228.188, "interval": None}
        ]
