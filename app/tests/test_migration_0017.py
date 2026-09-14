"""Migration 0017 — the `energy_summary_days` table (ADR 0022, M14 ticket 01).

Mirrors `test_migration_0011.py`'s shape (`battery_readings`, the closest
structural precedent: a brand-new table, a device foreign key, one unique
constraint) — step to 0016, upgrade to head, assert against the real SQLite
file. What this pins that no other test in the suite does: the schema-level
unique constraint on (device_id, local_date) and the cascade delete — the
ticket's own words, "unique on device plus local date; rows go when their
device goes".
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from arichds.config import Settings
from arichds.db.migrate import build_alembic_config, upgrade_to_head


@pytest.fixture
def db_at_0016(settings: Settings) -> Iterator[str]:
    """A database migrated to 0016 — the world as it was before M14 ticket 01."""
    command.upgrade(build_alembic_config(settings.db_url), "0016")
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
        # SQLite disables foreign-key enforcement per connection by default —
        # the production engine (``db/session.py``) turns it on, but a fresh
        # raw connection here does not inherit that, and the cascade test
        # below needs it explicitly.
        conn.execute(text("PRAGMA foreign_keys = ON"))
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


@pytest.fixture
def upgraded(db_at_0016: str) -> tuple[str, int]:
    """A head-migrated database with one device seeded, ready to insert
    `energy_summary_days` rows against."""
    upgrade_to_head(db_at_0016)
    device_id = seed_device(db_at_0016)
    return db_at_0016, device_id


def _insert_row(db_url: str, device_id: int, local_date: str, **overrides: float) -> None:
    values = {
        "peak_import_kwh": 0.0,
        "offpeak_import_kwh": 0.0,
        "holiday_import_kwh": 0.0,
        "total_import_kwh": 0.0,
        "peak_export_kwh": 0.0,
        "offpeak_export_kwh": 0.0,
        "holiday_export_kwh": 0.0,
        "total_export_kwh": 0.0,
        **overrides,
    }
    execute(
        db_url,
        "INSERT INTO energy_summary_days "
        "(device_id, local_date, peak_import_kwh, offpeak_import_kwh, holiday_import_kwh, total_import_kwh, "
        "peak_export_kwh, offpeak_export_kwh, holiday_export_kwh, total_export_kwh) "
        "VALUES (:device_id, :local_date, :peak_import_kwh, :offpeak_import_kwh, :holiday_import_kwh, "
        ":total_import_kwh, :peak_export_kwh, :offpeak_export_kwh, :holiday_export_kwh, :total_export_kwh)",
        {"device_id": device_id, "local_date": local_date, **values},
    )


class TestEnergySummaryDaysTable:
    def test_the_columns_exist(self, upgraded: tuple[str, int]) -> None:
        db_url, _device_id = upgraded
        columns = {row["name"] for row in rows(db_url, "PRAGMA table_info(energy_summary_days)")}
        assert columns == {
            "id",
            "device_id",
            "local_date",
            "peak_import_kwh",
            "offpeak_import_kwh",
            "holiday_import_kwh",
            "total_import_kwh",
            "peak_export_kwh",
            "offpeak_export_kwh",
            "holiday_export_kwh",
            "total_export_kwh",
            "updated_at",
        }

    def test_a_row_can_be_inserted_and_read_back(self, upgraded: tuple[str, int]) -> None:
        db_url, device_id = upgraded
        _insert_row(db_url, device_id, "2026-08-06", total_import_kwh=4.0)

        row = rows(db_url, "SELECT * FROM energy_summary_days")[0]
        assert row["local_date"] == "2026-08-06"
        assert row["total_import_kwh"] == 4.0


class TestTheUniqueConstraint:
    """ "Unique on device plus local date" — the ticket's own words."""

    def test_two_rows_for_the_same_device_and_local_date_collide(self, upgraded: tuple[str, int]) -> None:
        db_url, device_id = upgraded
        _insert_row(db_url, device_id, "2026-08-06")

        with pytest.raises(IntegrityError):
            _insert_row(db_url, device_id, "2026-08-06")

    def test_the_same_local_date_may_repeat_on_another_device(self, upgraded: tuple[str, int]) -> None:
        db_url, first_device_id = upgraded
        second_device_id = seed_device(db_url, name="Second")
        _insert_row(db_url, first_device_id, "2026-08-06")

        _insert_row(db_url, second_device_id, "2026-08-06")  # must not raise

        assert len(rows(db_url, "SELECT id FROM energy_summary_days")) == 2


class TestCascadeDelete:
    """ "Rows go when their device goes" — the ticket's own words."""

    def test_deleting_the_device_deletes_its_energy_summary_rows(self, upgraded: tuple[str, int]) -> None:
        db_url, device_id = upgraded
        _insert_row(db_url, device_id, "2026-08-06")

        execute(db_url, "DELETE FROM devices WHERE id = :device_id", {"device_id": device_id})

        assert rows(db_url, "SELECT id FROM energy_summary_days") == []


class TestDowngrade:
    def test_the_table_is_gone(self, db_at_0016: str) -> None:
        upgrade_to_head(db_at_0016)
        command.downgrade(build_alembic_config(db_at_0016), "0016")

        tables = {row["name"] for row in rows(db_at_0016, "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "energy_summary_days" not in tables
