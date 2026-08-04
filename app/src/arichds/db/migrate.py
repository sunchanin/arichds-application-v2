"""Run ``alembic upgrade head`` from inside the process.

SPEC §3.1: "Migration รันอัตโนมัติตอน service start (alembic upgrade head
ก่อนเปิด API)" — the installer and updater have no separate migrate step, so
this runs in the app lifespan before the first request is served.

An in-memory ``alembic.Config`` is used rather than reading ``alembic.ini``: a
frozen ``arichds.exe`` started by NSSM has an unpredictable working directory,
so every path here is resolved absolutely off the package location.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)


def migrations_dir() -> Path:
    """Return the absolute path of the Alembic script directory.

    Resolution order:

    1. **Frozen bundle** — under PyInstaller, ``<_MEIPASS>/arichds/migrations``.
    2. **Normal import** — the ``migrations`` package next to this module.

    Both branches are absolute, so the NSSM service's working directory never
    matters.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen = Path(meipass) / "arichds" / "migrations"
        if frozen.is_dir():
            return frozen
    return Path(__file__).resolve().parent.parent / "migrations"


def build_alembic_config(db_url: str) -> Config:
    """Build an in-memory Alembic config pointed at *db_url*."""
    config = Config()
    config.set_main_option("script_location", str(migrations_dir()))
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def upgrade_to_head(db_url: str) -> None:
    """Bring the database at *db_url* up to the latest revision.

    Blocking and synchronous — intentionally so: it runs before the API accepts
    traffic, and the schema must be current before anything reads it.

    Args:
        db_url: SQLAlchemy URL of the database to migrate. Its parent directory
            must exist (SQLite will not create it).
    """
    logger.info("Running alembic upgrade head")
    command.upgrade(build_alembic_config(db_url), "head")
    logger.info("Database schema is at head")
