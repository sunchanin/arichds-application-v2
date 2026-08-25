"""Configuration → engine, and the Test connection check (issue #46).

The **Database Destination** (CONTEXT.md) is the customer's own MariaDB or
MySQL. This module owns everything about *reaching* it; :mod:`.schema` owns
what its tables look like and :mod:`.sync` owns what goes into them.

**MariaDB is the real target.** XAMPP's Control Panel button says "MySQL" and
starts MariaDB — the reference server answers ``10.4.32-MariaDB``. The URL
scheme is ``mysql+pymysql://``, which SQLAlchemy resolves to either engine (it
reads ``dialect.is_mariadb`` off the version string); ``mariadb+pymysql://``
would refuse a real MySQL 8 and is deliberately not used.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

import sqlalchemy as sa
from sqlalchemy import URL, Engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arichds.constants import (
    DBDEST_CONNECT_TIMEOUT_SEC,
    DBDEST_READ_TIMEOUT_SEC,
    DBDEST_SESSION_SQL_MODE,
    DBDEST_TEST_CONNECT_TIMEOUT_SEC,
)
from arichds.db.app_settings import (
    DB_DEST_DATABASE_DEFAULT,
    DB_DEST_DATABASE_KEY,
    DB_DEST_HOST_DEFAULT,
    DB_DEST_HOST_KEY,
    DB_DEST_PASSWORD_DEFAULT,
    DB_DEST_PASSWORD_KEY,
    DB_DEST_PORT_DEFAULT,
    DB_DEST_PORT_KEY,
    DB_DEST_USER_DEFAULT,
    DB_DEST_USER_KEY,
    get_setting,
)

logger = logging.getLogger(__name__)

#: What ``POST /api/settings/database-destination/test`` can answer.
#:
#: ``not_configured`` is a **sixth** outcome the first draft of this module did
#: not have, and its absence was a live defect rather than a gap in taste.
#: PyMySQL silently defaults a blank host to ``localhost`` and a blank database
#: to "no default schema", so an unconfigured destination does not fail to
#: connect — it connects to *something else*. Measured on the reference server
#: (2026-08-25): all three of ``host=""``, ``database=""`` and both-empty came
#: back ``ok`` with ``Server: 10.4.32-MariaDB``. On this product that is the
#: **expected** configuration to hit it, not an exotic one: the customer runs
#: XAMPP on the same machine as ARICHDS, as ``root`` with an empty password,
#: which is exactly what makes a blank host resolve and succeed.
ConnectionResult = Literal[
    "ok", "not_configured", "unreachable", "auth_failed", "database_missing", "missing_privilege"
]

#: The privileges the sync needs. ``CREATE`` and ``ALTER`` because we own the
#: tables' shape and grow it when a column is added (SPEC §3.10, decision 8b);
#: ``DELETE`` because the destination mirrors our window rather than archiving
#: (ADR 0020), which is the one privilege least privilege cannot narrow past.
REQUIRED_PRIVILEGES: tuple[str, ...] = ("SELECT", "INSERT", "DELETE", "CREATE", "ALTER")

#: Server error codes, **measured** against MariaDB 10.4.32 through PyMySQL
#: 1.2.0 on 2026-08-25 rather than taken from a datasheet. Note that a refused
#: TCP connection and an unresolvable hostname both come back as 2003 — the C
#: client's 2002/2005 do not appear from this driver, so nothing keys on them.
_ERR_ACCESS_DENIED = 1045
_ERR_UNKNOWN_DATABASE = 1049


@dataclass(frozen=True, slots=True)
class DestinationConfig:
    """The five stored settings, read once per cycle.

    Frozen because a cycle must not have the settings change underneath it —
    the ``PUT`` can land at any moment, and the engine is built from this
    snapshot.
    """

    host: str
    port: int
    database: str
    user: str
    password: str

    @property
    def configured(self) -> bool:
        """Whether there is anything to connect to.

        An empty *host* **or** *database* means "not configured" — the
        convention ``capture_dir`` and ``export_output_dir`` already set. The
        sync then returns immediately with one DEBUG line and no error: a
        machine whose operator has not filled the form in is not a machine
        with a fault.
        """
        return bool(self.host.strip() and self.database.strip())


@dataclass(frozen=True, slots=True)
class ConnectionCheck:
    """One Test connection outcome.

    Attributes:
        result: Which of the six.
        message: One operator-actionable English sentence. Never
            "Connection failed" — telling the operator *which* thing is wrong
            is the entire point of this endpoint.
        server_version: ``SELECT VERSION()`` on success, ``None`` otherwise.
    """

    result: ConnectionResult
    message: str
    server_version: str | None


def load_config(session: Session) -> DestinationConfig:
    """Read the five ``settings`` rows into a :class:`DestinationConfig`.

    A ``db_dest_port`` that will not parse falls back to the default rather
    than raising — the value can only get there by hand-editing the database,
    and a background job must not die on it.
    """
    try:
        port = int(get_setting(session, DB_DEST_PORT_KEY, DB_DEST_PORT_DEFAULT))
    except ValueError:
        port = int(DB_DEST_PORT_DEFAULT)
    return DestinationConfig(
        host=get_setting(session, DB_DEST_HOST_KEY, DB_DEST_HOST_DEFAULT),
        port=port,
        database=get_setting(session, DB_DEST_DATABASE_KEY, DB_DEST_DATABASE_DEFAULT),
        user=get_setting(session, DB_DEST_USER_KEY, DB_DEST_USER_DEFAULT),
        password=get_setting(session, DB_DEST_PASSWORD_KEY, DB_DEST_PASSWORD_DEFAULT),
    )


def destination_url(config: DestinationConfig) -> URL:
    """Build the SQLAlchemy URL for *config*.

    **Never build this by concatenating a string.** :meth:`URL.create`
    escapes a password containing ``@``, ``/`` or ``:`` correctly, and the
    resulting object hides the password in both ``repr()`` and
    ``render_as_string()`` unless ``hide_password=False`` is passed — which
    nothing in this codebase does, and which
    ``test_dataout_config_api.py`` pins. A hand-built f-string would have
    neither property.
    """
    return URL.create(
        "mysql+pymysql",
        username=config.user,
        password=config.password,
        host=config.host,
        port=config.port,
        database=config.database,
        query={"charset": "utf8mb4"},
    )


def create_destination_engine(
    config: DestinationConfig, *, connect_timeout: int = DBDEST_CONNECT_TIMEOUT_SEC
) -> Engine:
    """Build an engine for *config* — **one per cycle, disposed at the end**.

    Not a cached process-wide engine, deliberately. The settings can change
    through the ``PUT`` at any moment, and a fifteen-minute cadence makes a
    connection pool worthless: every connection in it would be stale by the
    time the next cycle wanted it. There is no ``pool_pre_ping`` for the same
    reason — nothing is being kept alive.

    The session ``sql_mode`` is set **by us** on every connection rather than
    inherited (SPEC §3.10, decision 7b). The reference server runs without
    ``STRICT_TRANS_TABLES``, which makes an over-long or out-of-range value
    truncate or clamp silently; correctness must not live in the customer's
    ``my.ini``, the same argument ADR 0021 makes for ``DATETIME`` over
    ``TIMESTAMP``. It is done through a ``connect`` event rather than
    ``connect_args`` because PyMySQL has no ``sql_mode`` connect argument —
    ``init_command`` exists but takes a single statement and would silently
    lose the setting if anything else ever needed to run at connect time.

    Args:
        config: The destination to reach.
        connect_timeout: Seconds to wait for the TCP connection and handshake.
            The Test connection path passes the shorter
            :data:`~arichds.constants.DBDEST_TEST_CONNECT_TIMEOUT_SEC`
            because a person is waiting on a button.
    """
    engine = sa.create_engine(
        destination_url(config),
        poolclass=sa.pool.NullPool,
        connect_args={
            "connect_timeout": connect_timeout,
            "read_timeout": DBDEST_READ_TIMEOUT_SEC,
            "write_timeout": DBDEST_READ_TIMEOUT_SEC,
        },
    )

    @event.listens_for(engine, "connect")
    def _set_session_sql_mode(dbapi_connection, _record) -> None:  # noqa: ANN001
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET SESSION sql_mode = %s", (DBDEST_SESSION_SQL_MODE,))

    return engine


def classify_connect_error(exc: BaseException, *, database: str) -> tuple[ConnectionResult, str]:
    """Turn a failed connection into an outcome and a sentence.

    Only ever returns one of the three *connection-failure* outcomes —
    ``unreachable``, ``auth_failed``, ``database_missing``. ``ok`` and
    ``missing_privilege`` are decided by the caller once a connection
    exists, and ``not_configured`` short-circuits before one is attempted.

    Keyed on the server error codes **measured** against MariaDB 10.4.32
    through PyMySQL 1.2.0 on 2026-08-25, not on the C client's codes: a
    refused TCP connection and an unresolvable hostname both arrive as
    ``2003`` from this driver, so neither ``2002`` nor ``2005`` is keyed on.
    Anything with no recognised code — a socket timeout, a DNS failure that
    never reached the driver — is "unreachable" too, because from the
    operator's chair it is the same problem and the same fix.

    Args:
        exc: The exception raised by the connection attempt.
        database: The configured database name, so the 1049 message can name
            the one that is missing.

    Returns:
        The outcome and its operator-actionable sentence. Never raises.
    """
    orig = getattr(exc, "orig", exc)
    args = getattr(orig, "args", ())
    code = args[0] if args and isinstance(args[0], int) else None
    detail = str(args[1]) if len(args) > 1 else str(orig)

    if code == _ERR_ACCESS_DENIED:
        return (
            "auth_failed",
            f"The server refused the user name or password. Check the user and password fields. Server said: {detail}",
        )
    if code == _ERR_UNKNOWN_DATABASE:
        return (
            "database_missing",
            f"Connected to the server, but the database {database!r} does not exist. "
            "Ask the customer's database administrator to create it — ARICHDS creates its own tables inside it, "
            "but never the database itself.",
        )
    return (
        "unreachable",
        f"Could not reach the server. Check the host, the port, and that the database server is running and "
        f"accepting connections from this machine. Details: {detail}",
    )


def missing_privileges(grants: list[str], *, database: str) -> list[str]:
    """Which of :data:`REQUIRED_PRIVILEGES` *grants* does not confirm.

    Parses ``SHOW GRANTS FOR CURRENT_USER()`` output. **Only recognised grant
    syntax counts; anything this cannot parse grants nothing** — which can
    produce a false "missing" on an exotic setup, and is exactly why the
    endpoint's message says *could not confirm* rather than *you lack*, and
    names which ones. **The sync job never consults this**: it attempts the
    work and reports the real server error, so a false negative here costs an
    operator a confusing sentence, never a skipped sync.

    Handles both grant scopes that can cover us — ``*.*`` and
    ```db`.*`` — and MySQL's ``\\_`` escaping of an underscore in a
    database name inside a grant.

    Args:
        grants: The rows ``SHOW GRANTS`` returned, one string each.
        database: The configured database name, unescaped.

    Returns:
        The unconfirmed privileges, in :data:`REQUIRED_PRIVILEGES` order.
    """
    confirmed: set[str] = set()
    for row in grants:
        match = re.match(r"^\s*GRANT\s+(.+?)\s+ON\s+(\S+)\s+TO\s", row, re.IGNORECASE | re.DOTALL)
        if match is None:
            continue
        privileges_text, scope = match.group(1), match.group(2)
        if not _scope_covers(scope, database):
            continue
        granted = {part.strip().upper() for part in privileges_text.split(",")}
        if any(privilege.startswith("ALL PRIVILEGES") or privilege == "ALL" for privilege in granted):
            confirmed.update(REQUIRED_PRIVILEGES)
            continue
        confirmed.update(privilege for privilege in REQUIRED_PRIVILEGES if privilege in granted)

    return [privilege for privilege in REQUIRED_PRIVILEGES if privilege not in confirmed]


def _scope_covers(scope: str, database: str) -> bool:
    """Whether a grant's ``ON <scope>`` reaches *database*.

    ``*.*`` covers everything. ```db`.*`` (or ``db.*``) covers only that one
    database, with MySQL's ``\\_`` escaping undone before comparing. A
    table-level grant is not recognised: we create tables that do not exist
    yet, so a grant naming today's tables would not cover tomorrow's.
    """
    scope = scope.strip()
    if scope in {"*.*", "*"}:
        return True
    db_part, _, table_part = scope.rpartition(".")
    if table_part != "*":
        return False
    return db_part.strip("`").replace("\\_", "_").replace("\\%", "%") == database


def check_destination_connection(
    config: DestinationConfig, *, connect_timeout: int = DBDEST_TEST_CONNECT_TIMEOUT_SEC
) -> ConnectionCheck:
    """Connect to *config* and report which of the six outcomes it is.

    **An unconfigured destination short-circuits before any connection is
    attempted.** That guard is load-bearing, not tidiness: a blank host is not
    a connection failure, because PyMySQL defaults it to ``localhost`` — so
    without this, a fresh install reports "Connected" against whatever database
    server happens to be on the operator's own machine, while the sync
    (:func:`~arichds.dataout.sync.database_destination_cycle`) correctly does
    nothing. A silently dead feature behind a green tick is worse than a red
    one.

    **Creates nothing.** No temp table, no scratch row — two reads,
    ``SELECT VERSION()`` and ``SHOW GRANTS FOR CURRENT_USER()``, and the
    engine is disposed in a ``finally``.

    The privilege half is best-effort by construction: see
    :func:`missing_privileges`. A ``SHOW GRANTS`` that itself fails is not
    treated as a missing privilege — every account can run it, so a failure
    there means something about the connection is wrong in a way the earlier
    ``SELECT VERSION()`` should already have caught, and reporting "ok" with
    the version we did read is more honest than inventing a privilege
    complaint.
    """
    if not config.configured:
        missing = " and ".join(
            name for name, value in (("host", config.host), ("database", config.database)) if not value.strip()
        )
        return ConnectionCheck(
            "not_configured",
            f"No {missing} is saved yet, so there is nothing to test. Fill the form in and press Save first — "
            "Test connection always checks the settings that are **saved**, which is what the sync will use.",
            None,
        )

    engine = create_destination_engine(config, connect_timeout=connect_timeout)
    try:
        with engine.connect() as connection:
            version = str(connection.execute(sa.text("SELECT VERSION()")).scalar_one())
            try:
                grants = [str(row[0]) for row in connection.execute(sa.text("SHOW GRANTS FOR CURRENT_USER()"))]
            except SQLAlchemyError:
                logger.warning("Database Destination: SHOW GRANTS failed — reporting the connection as ok")
                grants = None
    except Exception as exc:  # noqa: BLE001 — every failure becomes a reported outcome, never a 500.
        result, message = classify_connect_error(exc, database=config.database)
        return ConnectionCheck(result, message, None)
    finally:
        engine.dispose()

    if grants is not None:
        unconfirmed = missing_privileges(grants, database=config.database)
        if unconfirmed:
            return ConnectionCheck(
                "missing_privilege",
                f"Connected to {config.database!r}, but could not confirm these privileges from SHOW GRANTS: "
                f"{', '.join(unconfirmed)}. ARICHDS needs {', '.join(REQUIRED_PRIVILEGES)} on that database — "
                "CREATE and ALTER because it owns the shape of its two tables, and DELETE because the "
                "destination holds the same 90 days ARICHDS holds. If the grant was made in a form this check "
                "does not recognise, the sync may still work.",
                version,
            )

    return ConnectionCheck(
        "ok",
        f"Connected to {config.database!r} on {config.host}:{config.port} as {config.user!r}. Server: {version}.",
        version,
    )
