"""Migration 0003 — the M3-1 `devices` field set, applied non-destructively.

SPEC §3.3: *"migration ไม่ลบอะไร"*. A machine that has been running since M1
holds device rows whose model no longer has a driver (the old ``sim`` row). The
upgrade must keep every one of them, park them (``enabled = 0``), give them the
placeholder site the form now requires, and leave ``meter_serial`` NULL — which
is exactly the "not yet identified" state ADR 0005 describes, and the state the
next Update (which always probes) resolves.

These tests step to 0002, write the pre-M3 world by hand, then upgrade — the
same sequence a real customer machine performs at service start.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from arichds.acquisition.locks import EndpointLocks
from arichds.acquisition.poller import Poller
from arichds.config import Settings
from arichds.db import session as db_session
from arichds.db.migrate import build_alembic_config, upgrade_to_head

TRANSPORT = json.dumps({"kind": "net", "host": "127.0.0.1", "port": 4059})


@pytest.fixture
def db_at_0002(settings: Settings) -> Iterator[str]:
    """A database migrated to 0002 — the world as it was before M3."""
    command.upgrade(build_alembic_config(settings.db_url), "0002")
    yield settings.db_url


def insert_device(db_url: str, name: str, model: str, brand: str = "SIM", enabled: int = 1) -> None:
    """Insert a pre-M3 device row with the 0002 column set only."""
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO devices (name, brand, model, transport, password, enabled) "
                "VALUES (:name, :brand, :model, :transport, '', :enabled)"
            ),
            {"name": name, "brand": brand, "model": model, "transport": TRANSPORT, "enabled": enabled},
        )
    engine.dispose()


def rows(db_url: str, sql: str) -> list[dict]:
    """Run *sql* and return the rows as dicts."""
    engine = create_engine(db_url)
    with engine.connect() as conn:
        result = [dict(row) for row in conn.execute(text(sql)).mappings()]
    engine.dispose()
    return result


class TestOrphanedRowsSurvive:
    """A row whose model lost its driver is parked, never deleted."""

    @pytest.fixture
    def upgraded(self, db_at_0002: str) -> str:
        insert_device(db_at_0002, "Sim Meter", "sim")
        insert_device(db_at_0002, "Main Incomer", "prometer100", brand="cewe")
        upgrade_to_head(db_at_0002)
        return db_at_0002

    def test_the_row_is_still_there(self, upgraded: str) -> None:
        names = [row["name"] for row in rows(upgraded, "SELECT name FROM devices ORDER BY id")]
        assert names == ["Sim Meter", "Main Incomer"]

    def test_the_orphan_is_disabled(self, upgraded: str) -> None:
        row = rows(upgraded, "SELECT enabled FROM devices WHERE name = 'Sim Meter'")[0]
        assert row["enabled"] == 0

    def test_a_drivable_row_beside_it_stays_enabled(self, upgraded: str) -> None:
        row = rows(upgraded, "SELECT enabled FROM devices WHERE name = 'Main Incomer'")[0]
        assert row["enabled"] == 1

    def test_site_name_is_backfilled_by_the_server_default(self, upgraded: str) -> None:
        """A NOT NULL column with a server_default fills existing rows on ADD."""
        for row in rows(upgraded, "SELECT site_name FROM devices"):
            assert row["site_name"] == "Unknown site"

    def test_meter_serial_stays_null(self, upgraded: str) -> None:
        """Not yet identified — until somebody presses Update, which probes."""
        for row in rows(upgraded, "SELECT meter_serial FROM devices"):
            assert row["meter_serial"] is None

    def test_the_record_only_columns_are_null(self, upgraded: str) -> None:
        row = rows(upgraded, "SELECT site_code, customer, meter_number, group_name FROM devices")[0]
        assert row == {"site_code": None, "customer": None, "meter_number": None, "group_name": None}

    def test_the_m4_and_m6_columns_exist_and_are_null(self, upgraded: str) -> None:
        row = rows(
            upgraded,
            "SELECT block_cipher_key, authentication_key, first_bill_date, "
            "bill_day_feb28, bill_day_feb29, bill_day_30, bill_day_31 FROM devices",
        )[0]
        assert set(row.values()) == {None}

    def test_the_disabling_is_case_insensitive_on_model(self, db_at_0002: str) -> None:
        insert_device(db_at_0002, "Shouty", "SIM")
        upgrade_to_head(db_at_0002)
        assert rows(db_at_0002, "SELECT enabled FROM devices WHERE name = 'Shouty'")[0]["enabled"] == 0

    def test_a_prometer100_written_in_capitals_stays_enabled(self, db_at_0002: str) -> None:
        insert_device(db_at_0002, "Loud", "PROMETER100", brand="cewe")
        upgrade_to_head(db_at_0002)
        assert rows(db_at_0002, "SELECT enabled FROM devices WHERE name = 'Loud'")[0]["enabled"] == 1


class TestMeterSerialUniqueIndex:
    """Unique **and** nullable: SQLite allows many NULLs in a unique index."""

    @pytest.fixture
    def upgraded(self, db_at_0002: str) -> str:
        upgrade_to_head(db_at_0002)
        return db_at_0002

    def test_two_rows_may_both_have_no_serial(self, upgraded: str) -> None:
        insert_device(upgraded, "A", "prometer100", brand="cewe")
        insert_device(upgraded, "B", "prometer100", brand="cewe")
        assert len(rows(upgraded, "SELECT id FROM devices")) == 2

    def test_two_rows_may_not_share_a_serial(self, upgraded: str) -> None:
        from sqlalchemy.exc import IntegrityError

        insert_device(upgraded, "A", "prometer100", brand="cewe")
        insert_device(upgraded, "B", "prometer100", brand="cewe")
        engine = create_engine(upgraded)
        try:
            with engine.begin() as conn:
                conn.execute(text("UPDATE devices SET meter_serial = 'SN-1' WHERE name = 'A'"))
            with pytest.raises(IntegrityError), engine.begin() as conn:
                conn.execute(text("UPDATE devices SET meter_serial = 'SN-1' WHERE name = 'B'"))
        finally:
            engine.dispose()

    def test_the_indexes_exist(self, upgraded: str) -> None:
        names = {row["name"] for row in rows(upgraded, "SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "ix_devices_meter_serial" in names
        assert "ix_devices_group_name" in names


class TestDowngrade:
    def test_downgrade_removes_what_0003_added(self, db_at_0002: str) -> None:
        upgrade_to_head(db_at_0002)
        command.downgrade(build_alembic_config(db_at_0002), "0002")

        columns = {row["name"] for row in rows(db_at_0002, "PRAGMA table_info(devices)")}
        assert "meter_serial" not in columns
        assert "site_name" not in columns
        assert "bill_day_31" not in columns
        indexes = {row["name"] for row in rows(db_at_0002, "SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "ix_devices_meter_serial" not in indexes
        assert "ix_devices_group_name" not in indexes


class TestThePollerIgnoresTheParkedRow:
    """D4 ties back here: the parked row must cost neither a thread nor a log flood."""

    def test_no_worker_and_one_log_line(self, db_at_0002: str, fake_meter, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        insert_device(db_at_0002, "Sim Meter", "sim")
        upgrade_to_head(db_at_0002)
        # Re-enable it by hand — the case D4 exists for.
        engine = create_engine(db_at_0002)
        with engine.begin() as conn:
            conn.execute(text("UPDATE devices SET enabled = 1"))
        engine.dispose()

        db_session.init_engine()
        try:
            poller = Poller(interval_sec=0.05, locks=EndpointLocks())
            with caplog.at_level(logging.WARNING, logger="arichds.acquisition.poller"):
                try:
                    poller.start()
                    assert poller._threads == []
                finally:
                    poller.stop()
        finally:
            db_session.dispose_engine()

        flood = [r for r in caplog.records if "has no driver in this build" in r.getMessage()]
        assert len(flood) == 1
        assert not [t for t in threading.enumerate() if t.name == "poller-Sim Meter"]
