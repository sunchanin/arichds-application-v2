"""Migration 0022 — `billing_readings.sequence` (ADR 0029).

Step to 0021, seed one closed period and one Open Period, upgrade to head:
the column exists, `NOT NULL DEFAULT 0`, the existing rows read back `0`,
and the closed-period unique index is rebuilt over the three columns with
its `WHERE record_status IS NULL` intact — read back from SQLite itself,
never from the Python-side model (the memory *schema assertions must read
back from the server*). The Open Period index is untouched. Downgrade drops
the column and restores the two-column index.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from arichds.config import Settings
from arichds.db.migrate import build_alembic_config, upgrade_to_head


@pytest.fixture
def db_at_0021(settings: Settings) -> Iterator[str]:
    command.upgrade(build_alembic_config(settings.db_url), "0021")
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
                "INSERT INTO billing_readings (device_id, bill_date, read_at, source, meter_serial, record_status) "
                "VALUES (1, '2026-07-31 17:00:00', '2026-08-01 02:00:00', 'dlms', 'SN-1', NULL), "
                "       (1, '2026-08-01 02:00:00', '2026-08-01 02:00:00', 'dlms', 'SN-1', 'open')"
            )
        )
    engine.dispose()


def index_columns(db_url: str, name: str) -> list[str]:
    return [row["name"] for row in rows(db_url, f"PRAGMA index_info({name})")]


def index_sql(db_url: str, name: str) -> str:
    return rows(db_url, f"SELECT sql FROM sqlite_master WHERE type = 'index' AND name = '{name}'")[0]["sql"]


class TestTheColumnIsAdded:
    def test_it_is_not_null_default_zero_and_existing_rows_read_zero(self, db_at_0021: str) -> None:
        seed(db_at_0021)
        upgrade_to_head(db_at_0021)

        info = {row["name"]: row for row in rows(db_at_0021, "PRAGMA table_info(billing_readings)")}
        assert info["sequence"]["notnull"] == 1
        assert info["sequence"]["dflt_value"] == "0"
        assert [r["sequence"] for r in rows(db_at_0021, "SELECT sequence FROM billing_readings ORDER BY id")] == [0, 0]


class TestTheClosedIndexIsRebuilt:
    def test_it_spans_the_three_columns_and_keeps_its_partial_where(self, db_at_0021: str) -> None:
        upgrade_to_head(db_at_0021)

        assert index_columns(db_at_0021, "uq_billing_readings_closed") == ["device_id", "bill_date", "sequence"]
        sql = index_sql(db_at_0021, "uq_billing_readings_closed")
        assert sql.startswith("CREATE UNIQUE INDEX")
        assert "record_status IS NULL" in sql

    def test_a_same_second_pair_is_two_rows_and_a_third_with_the_same_sequence_is_refused(
        self, db_at_0021: str
    ) -> None:
        seed(db_at_0021)
        upgrade_to_head(db_at_0021)

        engine = create_engine(db_at_0021)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO billing_readings (device_id, bill_date, read_at, source, sequence) "
                    "VALUES (1, '2026-07-31 17:00:00', '2026-08-01 02:00:00', 'dlms', 1)"
                )
            )
        with pytest.raises(Exception, match="UNIQUE"), engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO billing_readings (device_id, bill_date, read_at, source, sequence) "
                    "VALUES (1, '2026-07-31 17:00:00', '2026-08-01 02:00:00', 'dlms', 1)"
                )
            )
        engine.dispose()

    def test_the_open_period_index_is_untouched(self, db_at_0021: str) -> None:
        before = index_sql(db_at_0021, "uq_billing_readings_open")
        upgrade_to_head(db_at_0021)
        assert index_sql(db_at_0021, "uq_billing_readings_open") == before


class TestDowngrade:
    def test_it_restores_the_two_column_index_and_drops_the_column(self, db_at_0021: str) -> None:
        upgrade_to_head(db_at_0021)
        command.downgrade(build_alembic_config(db_at_0021), "0021")

        assert index_columns(db_at_0021, "uq_billing_readings_closed") == ["device_id", "bill_date"]
        assert "sequence" not in {row["name"] for row in rows(db_at_0021, "PRAGMA table_info(billing_readings)")}
