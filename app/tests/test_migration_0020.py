"""Migration 0020 — `devices.brand` is always a catalog key (ui-audit ticket 01).

Step to 0019, seed one row per case, upgrade to head: a brand that differs
from a catalog key only by case reads back as the key; a brand that matches no
key is left alone.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from arichds.config import Settings
from arichds.db.migrate import build_alembic_config, upgrade_to_head


@pytest.fixture
def db_at_0019(settings: Settings) -> Iterator[str]:
    command.upgrade(build_alembic_config(settings.db_url), "0019")
    yield settings.db_url


def seed_device(db_url: str, name: str, brand: str) -> int:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO devices (name, brand, model, transport, password, enabled, site_name) "
                "VALUES (:name, :brand, 'prometer100', '{}', '', 1, 'Plant A')"
            ),
            {"name": name, "brand": brand},
        )
        device_id = int(result.lastrowid)
    engine.dispose()
    return device_id


def brand_of(db_url: str, device_id: int) -> str:
    engine = create_engine(db_url)
    with engine.connect() as conn:
        brand = conn.execute(text("SELECT brand FROM devices WHERE id = :id"), {"id": device_id}).scalar_one()
    engine.dispose()
    return str(brand)


class TestBrandsAreNormalised:
    def test_a_case_variant_of_a_key_becomes_the_key(self, db_at_0019: str) -> None:
        device_id = seed_device(db_at_0019, "Prometer100_4059", "CEWE")
        upgrade_to_head(db_at_0019)
        assert brand_of(db_at_0019, device_id) == "cewe"

    def test_every_brand_key_is_covered(self, db_at_0019: str) -> None:
        ids = {
            "mitsu": seed_device(db_at_0019, "Feeder", "Mitsu"),
            "smart_tcc": seed_device(db_at_0019, "Incomer", "SMART_TCC"),
        }
        upgrade_to_head(db_at_0019)
        assert {brand_of(db_at_0019, device_id) for device_id in ids.values()} == set(ids)

    def test_a_brand_matching_no_key_is_left_alone(self, db_at_0019: str) -> None:
        device_id = seed_device(db_at_0019, "Old Sim", "acme")
        upgrade_to_head(db_at_0019)
        assert brand_of(db_at_0019, device_id) == "acme"

    def test_a_brand_already_a_key_is_untouched(self, db_at_0019: str) -> None:
        device_id = seed_device(db_at_0019, "Main", "cewe")
        upgrade_to_head(db_at_0019)
        assert brand_of(db_at_0019, device_id) == "cewe"
