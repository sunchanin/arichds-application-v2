"""Migration 0023 — the `export_billing_output_dir` row is removed (owner
decision ก, 2026-09-23: the Billing page has one folder).

Step to 0022, seed the row a 0.8.2 install could hold beside its neighbours,
upgrade to head: that one row is gone and every other setting is untouched —
read back from SQLite itself, never through the settings module.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from arichds.config import Settings
from arichds.db.migrate import build_alembic_config, upgrade_to_head


@pytest.fixture
def db_at_0022(settings: Settings) -> Iterator[str]:
    command.upgrade(build_alembic_config(settings.db_url), "0022")
    yield settings.db_url


def settings_rows(db_url: str) -> dict[str, str | None]:
    engine = create_engine(db_url)
    with engine.connect() as conn:
        result = {row["key"]: row["value"] for row in conn.execute(text("SELECT key, value FROM settings")).mappings()}
    engine.dispose()
    return result


def seed(db_url: str) -> None:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO settings (key, value) VALUES "
                "('capture_dir', 'C:/Billing'), "
                "('export_billing_output_dir', 'C:/BillingExports'), "
                "('export_energy_output_dir', 'C:/Energy'), "
                "('export_output_dir', 'C:/LoadProfile')"
            )
        )
    engine.dispose()


class TestTheOrphanRowIsRemoved:
    def test_only_the_billing_file_folder_row_goes(self, db_at_0022: str) -> None:
        seed(db_at_0022)

        upgrade_to_head(db_at_0022)

        assert settings_rows(db_at_0022) == {
            "capture_dir": "C:/Billing",
            "export_energy_output_dir": "C:/Energy",
            "export_output_dir": "C:/LoadProfile",
        }

    def test_a_database_without_the_row_upgrades_cleanly(self, db_at_0022: str) -> None:
        upgrade_to_head(db_at_0022)

        assert "export_billing_output_dir" not in settings_rows(db_at_0022)
