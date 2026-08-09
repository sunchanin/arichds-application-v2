"""Migration 0007 — the `billing_readings` table (M6a, issue #21).

A brand-new table, unlike 0006's alter of an existing one — so there is no
"surviving pre-migration row" scenario to replay here. What has to be pinned
is the shape (ADR 0009's two partial unique indexes) and the round-trip.

These tests step to 0006, upgrade to head, and assert against the real SQLite
file — the same sequence a customer machine performs at service start.
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
def db_at_0006(settings: Settings) -> Iterator[str]:
    """A database migrated to 0006 — the world as it was before M6a."""
    command.upgrade(build_alembic_config(settings.db_url), "0006")
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
def upgraded(db_at_0006: str) -> tuple[str, int]:
    device_id = seed_device(db_at_0006)
    upgrade_to_head(db_at_0006)
    return db_at_0006, device_id


class TestTheTableExists:
    def test_billing_readings_is_created(self, upgraded: tuple[str, int]) -> None:
        db_url, _device_id = upgraded
        tables = {row["name"] for row in rows(db_url, "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "billing_readings" in tables

    def test_the_forty_measurement_columns_plus_keys_exist(self, upgraded: tuple[str, int]) -> None:
        db_url, _device_id = upgraded
        columns = {row["name"] for row in rows(db_url, "PRAGMA table_info(billing_readings)")}
        expected_keys = {
            "id",
            "device_id",
            "bill_date",
            "read_at",
            "record_status",
            "source",
            "meter_serial",
            "created_at",
            "updated_at",
        }
        assert expected_keys <= columns
        assert len(columns) == len(expected_keys) + 40


class TestThePartialUniqueIndexes:
    """ADR 0009's two reasons — closed-period dedup, and at most one open slot."""

    def insert_closed(self, db_url: str, device_id: int, bill_date: str) -> None:
        execute(
            db_url,
            "INSERT INTO billing_readings (device_id, bill_date, read_at, record_status, source) "
            "VALUES (:device_id, :bill_date, :bill_date, NULL, 'dlms')",
            {"device_id": device_id, "bill_date": bill_date},
        )

    def insert_open(self, db_url: str, device_id: int, bill_date: str) -> None:
        execute(
            db_url,
            "INSERT INTO billing_readings (device_id, bill_date, read_at, record_status, source) "
            "VALUES (:device_id, :bill_date, :bill_date, 'open', 'dlms')",
            {"device_id": device_id, "bill_date": bill_date},
        )

    def test_a_duplicate_closed_bill_date_is_rejected(self, upgraded: tuple[str, int]) -> None:
        """Asserted on the ``IntegrityError`` — a constraint that exists but does
        not fire is exactly the failure this has to catch."""
        db_url, device_id = upgraded
        self.insert_closed(db_url, device_id, "2026-07-01 00:00:00")

        with pytest.raises(IntegrityError):
            self.insert_closed(db_url, device_id, "2026-07-01 00:00:00")

    def test_a_second_open_row_for_one_device_is_rejected(self, upgraded: tuple[str, int]) -> None:
        db_url, device_id = upgraded
        self.insert_open(db_url, device_id, "2026-08-07 11:37:58")

        with pytest.raises(IntegrityError):
            self.insert_open(db_url, device_id, "2026-08-08 09:00:00")

    def test_a_closed_and_an_open_row_with_the_same_bill_date_both_survive(self, upgraded: tuple[str, int]) -> None:
        """The two indexes are independent — a partial index on ``record_status
        IS NULL`` cannot see a row where it is ``'open'``, and vice versa."""
        db_url, device_id = upgraded
        self.insert_closed(db_url, device_id, "2026-08-07 11:37:58")
        self.insert_open(db_url, device_id, "2026-08-07 11:37:58")

        assert len(rows(db_url, "SELECT id FROM billing_readings")) == 2

    def test_two_devices_may_each_hold_an_open_row(self, upgraded: tuple[str, int]) -> None:
        db_url, device_id = upgraded
        other_id = seed_device(db_url, name="Second Meter")
        self.insert_open(db_url, device_id, "2026-08-07 11:37:58")

        self.insert_open(db_url, other_id, "2026-08-07 11:37:58")

        assert len(rows(db_url, "SELECT id FROM billing_readings")) == 2

    def test_a_closed_bill_date_may_repeat_on_another_device(self, upgraded: tuple[str, int]) -> None:
        db_url, device_id = upgraded
        other_id = seed_device(db_url, name="Second Meter")
        self.insert_closed(db_url, device_id, "2026-07-01 00:00:00")

        self.insert_closed(db_url, other_id, "2026-07-01 00:00:00")

        assert len(rows(db_url, "SELECT id FROM billing_readings")) == 2


class TestCascadeDelete:
    def test_deleting_the_device_deletes_its_billing_rows(self, upgraded: tuple[str, int]) -> None:
        db_url, device_id = upgraded
        execute(
            db_url,
            "INSERT INTO billing_readings (device_id, bill_date, read_at, record_status, source) "
            "VALUES (:device_id, '2026-07-01 00:00:00', '2026-07-01 00:00:00', NULL, 'dlms')",
            {"device_id": device_id},
        )

        execute(db_url, "DELETE FROM devices WHERE id = :device_id", {"device_id": device_id})

        assert rows(db_url, "SELECT id FROM billing_readings") == []


class TestDowngrade:
    def test_the_table_is_gone(self, db_at_0006: str) -> None:
        seed_device(db_at_0006)
        upgrade_to_head(db_at_0006)
        command.downgrade(build_alembic_config(db_at_0006), "0006")

        tables = {row["name"] for row in rows(db_at_0006, "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "billing_readings" not in tables
