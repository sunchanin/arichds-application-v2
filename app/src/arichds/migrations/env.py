"""Alembic environment — one migration set for the one SQLite database.

``render_as_batch=True`` is set from migration 0001 and is not negotiable
(SPEC §4 / REMAKE-PLAN §3.4): SQLite cannot ``ALTER TABLE`` to drop or alter a
column, so without batch mode every future column change would mean rebuilding
the table by hand.

The URL is normally injected by the caller (``arichds.db.migrate``) via
``config.set_main_option("sqlalchemy.url", ...)``; when Alembic is driven from
the CLI it falls back to the app's configured database.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from arichds.config import get_settings
from arichds.db.models import Base

config = context.config

# Only configure logging when Alembic was started from a real .ini (the CLI).
# The app builds a Config() in memory and owns its own logging — reconfiguring
# it here would clobber the credential redaction filter.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_url() -> str:
    """Return the database URL: caller-supplied, else the configured one."""
    return config.get_main_option("sqlalchemy.url") or get_settings().db_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (``alembic upgrade --sql``)."""
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and run migrations against the live database."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
