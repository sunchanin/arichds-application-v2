"""Shared test fixtures.

Every test gets its own data directory and its own SQLite file, so nothing
touches the developer's real ``./data`` and tests never see each other's rows.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from arichds.config import Settings, get_settings
from arichds.db import session as db_session
from arichds.db.migrate import upgrade_to_head

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"


@pytest.fixture(autouse=True)
def _isolate_simulated_state() -> Iterator[None]:
    """Give every test a fresh simulated-meter state.

    ``SimulatedDriver`` keeps its drift and cumulative register at module scope,
    keyed by Transport Endpoint, because the Poller rebuilds the driver on every
    tick. That state would otherwise leak between tests in one process — a test
    asserting "the register advanced" could pass on a previous test's leftovers,
    or an absolute-value assertion could drift depending on execution order.
    """
    from arichds.acquisition.drivers.simulated import reset_simulated_state

    reset_simulated_state()
    yield
    reset_simulated_state()


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point ``ARICHDS_DATA_DIR`` at a temporary directory for one test."""
    target = tmp_path / "data"
    monkeypatch.setenv("ARICHDS_DATA_DIR", str(target))
    # Settings are cached for the life of the process; drop the cache so the
    # patched environment is actually read.
    get_settings.cache_clear()
    settings = get_settings()
    settings.ensure_directories()
    yield target
    get_settings.cache_clear()


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    """The Settings object for the temporary data directory."""
    return get_settings()


@pytest.fixture
def migrated_db(settings: Settings) -> Iterator[Settings]:
    """A migrated, empty database at the temporary location."""
    upgrade_to_head(settings.db_url)
    db_session.init_engine()
    yield settings
    db_session.dispose_engine()


@pytest.fixture
def vendor_cli():
    """Import ``tools/arichds_vendor.py`` — the real issuer, not a stand-in.

    Testing against the actual CLI is the point: the canonical-payload rule is
    duplicated on both sides on purpose, and this is what catches them drifting.
    """
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    import arichds_vendor

    return arichds_vendor
