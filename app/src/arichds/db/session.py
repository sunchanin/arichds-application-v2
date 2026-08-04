"""Engine and Session factory for the one SQLite database.

SQLite in **WAL** mode (SPEC §4) so the Poller threads can write while the API
reads. WAL and foreign-key enforcement are applied on every connection, not once
at startup, because SQLite settings are per-connection.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from arichds.config import get_settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _apply_sqlite_pragmas(engine: Engine) -> None:
    """Set WAL + foreign keys on every new DBAPI connection.

    WAL lets one writer and many readers coexist, which is exactly the M1 shape:
    n poller threads writing Interval Readings while the API serves the monitor
    page. ``foreign_keys=ON`` is off by default in SQLite — without it the
    ``ON DELETE CASCADE`` on ``interval_readings`` would silently not fire.
    """

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        # Wait rather than fail immediately when another connection holds the
        # write lock — poller threads and the API do overlap.
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def create_db_engine(db_path: Path) -> Engine:
    """Build an Engine for *db_path*, with WAL/FK pragmas attached.

    Args:
        db_path: Absolute path to the SQLite file. Its parent must already exist
            (SQLite will not create it).

    Returns:
        A configured, not-yet-connected Engine.
    """
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        # Poller threads hand connections around; SQLAlchemy's pool is what
        # actually serialises access, so the per-thread check is redundant.
        connect_args={"check_same_thread": False},
        future=True,
    )
    _apply_sqlite_pragmas(engine)
    return engine


def init_engine(db_path: Path | None = None) -> Engine:
    """Create (or replace) the process-wide engine and session factory.

    Called once from the app lifespan, and again per test with a tmp path.

    Args:
        db_path: Override the configured database location (tests).

    Returns:
        The active Engine.
    """
    global _engine, _session_factory
    settings = get_settings()
    target = db_path if db_path is not None else settings.db_path
    target.parent.mkdir(parents=True, exist_ok=True)

    if _engine is not None:
        _engine.dispose()

    _engine = create_db_engine(target)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    logger.info("Database engine ready at %s", target)
    return _engine


def get_engine() -> Engine:
    """Return the active Engine, creating it on first use."""
    if _engine is None:
        return init_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the active session factory, creating the engine on first use."""
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a Session that commits on success and rolls back on error.

    The unit of work for background threads (the Poller) and for anything
    outside a request. Request handlers use the ``SessionDep`` dependency.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    """Close all pooled connections and drop the engine (shutdown / tests)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
