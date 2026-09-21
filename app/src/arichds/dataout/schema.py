"""The two tables we create in the customer's database (issue #46, SPEC §3.10).

We own their shape and we are the only writer (CONTEXT.md — Database
Destination). **Nothing else is ever sent**: not ``energy_register_readings``,
not the device list, and never ``devices``, which holds meter passwords in the
clear plus ``block_cipher_key`` / ``authentication_key`` the API itself is
forbidden to return. Three operator-entered labels are the one thing that
crosses from that table, by name and one column at a time
(:data:`DEVICE_LABEL_COLUMNS`) — never the row.

**The column set is derived from the ORM models at import time, never hand
listed.** That is what makes SPEC §3.10's decision 8b structural rather than a
promise: ``billing_readings`` went from 40 columns to 60 at M4c (issue #24),
and a hand-written list would have gone stale exactly there — the customer's
first ``INSERT`` after that upgrade would have failed on an unknown column,
repairable only by a person editing their database by hand. It is also what
lets ``test_dataout_schema.py`` *prove* every destination column is at least as
wide as its SQLite counterpart rather than assert it.

SQLAlchemy Core, never the ORM: these tables are ours but they are not our
store, and no model in :mod:`arichds.db.models` may grow a second bind.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy import Connection, Table
from sqlalchemy.dialects import mysql

from arichds.db.load_profile_query import MERGED_COLUMNS
from arichds.db.models import BillingReading, Device, LoadProfileReading

logger = logging.getLogger(__name__)

#: Our own MetaData — deliberately not ``Base.metadata``. Binding these tables
#: to the ORM's registry would put the destination one ``create_all`` away from
#: being created inside our own SQLite, and one ``drop_all`` away from worse.
METADATA = sa.MetaData()

#: The columns that exist only to serve SQLite and must never leave.
#:
#: ``id`` is a surrogate key with no meaning outside our database. ``device_id``
#: is worse than meaningless: ``devices.id`` is a SQLite rowid alias, so it is
#: **reused** once the highest row is deleted (verified on the live database —
#: ``max id = 3`` with ``count = 3``). The destination would never learn of the
#: delete, and two meters' data would silently merge under one number. Rows are
#: keyed on **Meter Serial** instead, which is globally unique per meter and is
#: why two installs may safely share one destination database (ADR 0020).
# `captured_at` is bookkeeping about *our* capture folder (ui-audit ticket
# 03), not a meter measurement — a customer's database mirrors what the meter
# said (ADR 0016/0020), never where a document landed on this machine.
_EXCLUDED_COLUMNS = frozenset({"id", "device_id", "captured_at"})

#: Dropped from ``load_profile_readings`` only, since ADR 0027: the destination
#: holds **one merged row per interval** — Logger 1 the spine, Logger 2 joined
#: on an exact ``read_at``, ``COALESCE`` per column — the row the Load Profile
#: page and the Load Profile CSV already show, so a logger discriminator has
#: nothing left to discriminate.
_LOGGER_COLUMN = "logger_id"

#: Meter Serial's width, taken from ``devices.meter_serial`` /
#: ``billing_readings.meter_serial`` (``String(64)``) rather than chosen here,
#: so the two can never disagree.
_METER_SERIAL_WIDTH = 64

#: The device labels every destination row carries, destination column ->
#: ``devices`` column (owner, 2026-09-20 — the customer's reports name a meter
#: by these, not by its serial). ``meter`` is the customer's own word for
#: ``meter_number``; ``device_name`` is ours for ``name``, which alone would
#: say nothing in a table of readings.
#:
#: **A label is a snapshot, not a reference.** A load-profile row keeps the
#: labels its device had when the row was written — a sent row never changes
#: (ADR 0020/0021), so renaming a device reaches new rows only. Billing is
#: replaced wholesale every cycle and therefore always carries the current
#: ones. Rows sent before these columns existed stay ``NULL``.
DEVICE_LABEL_COLUMNS: dict[str, str] = {"device_name": "name", "meter": "meter_number", "site_name": "site_name"}


def _destination_type(source: sa.types.TypeEngine) -> sa.types.TypeEngine:
    """Map one SQLite column type onto its MariaDB/MySQL counterpart.

    Declared explicitly through this one mapping rather than left to the
    dialect to compile the source type "the way we want". The two that matter:

    * ``DateTime(timezone=True)`` becomes a **naive ``DATETIME``**, never
      ``TIMESTAMP`` (ADR 0021). ``TIMESTAMP`` converts on the way in and out
      using the session's ``time_zone``, which would make the correctness of
      the customer's data depend on their ``my.ini``, their connection's
      session settings, and whether their reporting tool sets either. The
      timezone-awareness is stripped at the write, in :mod:`.sync`.
    * ``Float`` becomes ``DOUBLE``, not ``FLOAT``. Measured on the design
      probe: 40 numeric columns on one billing row round-tripped exactly
      through ``DOUBLE`` — ``147029.6554881``, ``127.570966``,
      ``1136.5020832``. ``FLOAT`` is single precision and would not have.

    Raises:
        TypeError: On a source type this has never seen. Deliberately loud:
            a new column type added to a model must be considered here, not
            silently guessed at against someone else's database.
    """
    if isinstance(source, sa.DateTime):
        return mysql.DATETIME()
    if isinstance(source, sa.String):
        return mysql.VARCHAR(source.length)
    if isinstance(source, sa.Integer):
        return mysql.INTEGER()
    if isinstance(source, sa.Float):
        return mysql.DOUBLE(asdecimal=False)
    raise TypeError(f"No Database Destination type mapping for {source!r} — add one to dataout/schema.py")


def _derive_columns(model: type[LoadProfileReading] | type[BillingReading]) -> list[sa.Column]:
    """Every column of *model* that belongs in the destination.

    Nullability is carried over from the source, so a column that can be NULL
    here can be NULL there. The two exceptions are the identity columns, and
    both are handled by the callers below rather than here.
    """
    return [
        sa.Column(source.name, _destination_type(source.type), nullable=source.nullable)
        for source in model.__table__.columns
        if source.name not in _EXCLUDED_COLUMNS
    ]


def _device_label_columns() -> list[sa.Column]:
    """The :data:`DEVICE_LABEL_COLUMNS`, typed from ``devices`` itself.

    **Always nullable**, whatever ``devices`` says: :func:`reconcile` adds them
    to tables that already hold rows, and a ``NOT NULL`` there would fail on
    the customer's server.
    """
    return [
        sa.Column(name, _destination_type(Device.__table__.columns[source].type), nullable=True)
        for name, source in DEVICE_LABEL_COLUMNS.items()
    ]


def _labelled(columns: list[sa.Column]) -> list[sa.Column]:
    """*columns* with the device labels placed directly after ``meter_serial``.

    Owner, 2026-09-20: whoever opens the table reads which meter a row belongs
    to in one place — serial, name, meter number, site — before any
    measurement. :func:`reconcile` adds a missing column ``AFTER`` its
    neighbour here, so an upgraded destination ends up in this same order.
    """
    position = next(index for index, column in enumerate(columns) if column.name == "meter_serial") + 1
    return [*columns[:position], *_device_label_columns(), *columns[position:]]


#: Declared, never inherited. The reference server's ``my.ini`` happens to set
#: ``utf8mb4`` server-wide (``C:\\xampp\\mysql\\bin\\my.ini:160-161``), so the
#: stock MariaDB ``latin1`` default does not bite there — but another
#: customer's ``my.ini`` is not that one, and a destination that silently
#: became latin1 would mangle any non-ASCII value the moment one appeared.
_TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_general_ci",
    "mariadb_engine": "InnoDB",
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_general_ci",
}

#: ``load_profile_readings`` at the destination.
#:
#: **``meter_serial`` is added by us, at the front** — ``LoadProfileReading``
#: has no such column, so it is joined from ``devices`` at write time. It is
#: ``NOT NULL``: a row nobody can attribute to a meter is unattributable at the
#: destination too, so the sync skips and counts it rather than writing it.
#:
#: **One merged row per interval, no ``logger_id``** (ADR 0027) — see
#: :data:`_LOGGER_COLUMN`. Every measurement column is one of
#: :data:`~arichds.db.load_profile_query.MERGED_COLUMNS`; what is left
#: (``source``, ``interval_sec``, ``created_at``) is taken from the Logger 1 row.
#: ``test_dataout_schema.py`` pins that split, so a measurement column added to
#: the model cannot reach this table without joining the merge.
#:
#: The unique key on ``(meter_serial, read_at)`` is what makes
#: ``INSERT … ON DUPLICATE KEY UPDATE`` collapse a re-sent row onto the
#: existing one instead of duplicating it — the safety the watermark rewind
#: rests on (ADR 0021). The watermark's ``MAX(read_at)`` per serial rides it
#: too, so the ``(meter_serial, read_at)`` secondary index the per-logger shape
#: carried would now be an exact duplicate and is gone.
#:
#: **The purge needs its own index.** ``DELETE … WHERE read_at < :cutoff`` names
#: no ``meter_serial``, so no index that leads with the serial can serve it —
#: true of the old secondary index as well, which left every cycle's purge a
#: full scan (code review, 2026-09-20). ``ix_load_profile_readings_read_at`` is
#: for that statement alone.
#:
#: There is no surrogate primary key: nothing at the destination refers to a
#: row by number.
LOAD_PROFILE_TABLE: Table = sa.Table(
    "load_profile_readings",
    METADATA,
    *_labelled(
        [
            sa.Column("meter_serial", mysql.VARCHAR(_METER_SERIAL_WIDTH), nullable=False),
            *[column for column in _derive_columns(LoadProfileReading) if column.name != _LOGGER_COLUMN],
        ]
    ),
    sa.UniqueConstraint("meter_serial", "read_at", name="uq_load_profile_readings_serial_read_at"),
    sa.Index("ix_load_profile_readings_read_at", "read_at"),
    **_TABLE_OPTIONS,
)

#: The destination columns that are **not** merged — copied from the Logger 1
#: row as they stand. Derived, so :mod:`.sync` selects exactly what the table
#: holds and nothing is listed twice.
LOAD_PROFILE_SPINE_COLUMNS: tuple[str, ...] = tuple(
    column.name
    for column in LOAD_PROFILE_TABLE.columns
    if column.name not in {"meter_serial", "read_at", *DEVICE_LABEL_COLUMNS, *MERGED_COLUMNS}
)

#: ``billing_readings`` at the destination.
#:
#: **No unique key of any kind.** ADR 0009's identity for this table is two
#: *partial* unique indexes — one over closed periods, one allowing at most a
#: single Open Period per device — and neither MySQL nor MariaDB can express a
#: partial index. That is the finding ADR 0016 rests on. What keeps the
#: destination correct instead is the whole-table replace inside one
#: transaction, every cycle.
#:
#: ``meter_serial`` is ``NOT NULL`` here even though the ORM column is
#: nullable. The ORM allows NULL because a serial-register read can fail
#: *after* the buffer was read (ADR 0018), and the sync's fallback to
#: ``devices.meter_serial`` plus its skip-and-count is what guarantees a NULL
#: never reaches here — declaring it turns a regression into ``ERROR 1048``
#: instead of a silently unattributable row.
#:
#: **That backstop reaches only tables we created.** Against a destination
#: table that already exists with the column nullable, :func:`reconcile`
#: correctly never retypes it (add-only, never drop, never retype), so the
#: constraint is simply absent there and the guarantee rests on the sync's own
#: skip alone. Correct behaviour, narrower reach than "NOT NULL" suggests.
BILLING_TABLE: Table = sa.Table(
    "billing_readings",
    METADATA,
    *_labelled(_derive_columns(BillingReading)),
    sa.Index("ix_billing_readings_serial_bill_date", "meter_serial", "bill_date"),
    **_TABLE_OPTIONS,
)
BILLING_TABLE.columns["meter_serial"].nullable = False

#: Both tables, in the order a cycle touches them.
TABLES: tuple[Table, ...] = (BILLING_TABLE, LOAD_PROFILE_TABLE)


def reconcile(connection: Connection) -> bool:
    """Create what is missing and add what is new — **never drop, never retype**.

    Four steps, and the last three exist because the first is not enough:

    1. ``CREATE TABLE IF NOT EXISTS`` for each table.
    2. Compare ``information_schema.columns`` against the derived set and
       ``ALTER TABLE … ADD COLUMN`` whatever is missing — ``AFTER`` the column
       that precedes it in our own definition, so an upgraded table has the
       order a fresh one has. Measured on MariaDB 10.4.32, 200,000 rows: 3–5 ms
       (instant), 570 ms when forced to copy the table as an older server
       would. A column that is already there is **never moved**.
    3. Create any of our secondary indexes the server does not have.
    4. Refuse to go on if ``load_profile_readings`` has no unique key.

    **A per-logger ``load_profile_readings`` is left exactly as it is.** A table
    that still has a ``logger_id`` column is the one an ARICHDS before ADR 0027
    created: nothing is added to it, no index is created on it and its key is
    not judged, because nothing will be written to it either — this function
    **returns ``True``** for it, and the load-profile step raises
    :func:`per_logger_load_profile_error` on that answer before it would write.
    The raise is kept out of here so that a site with no ``load_profile``
    licence, or an upgrade nobody has finished yet, still gets its billing.

    **Step 1 alone is not enough**, and this is not hypothetical. Against a
    table that already exists, ``CREATE TABLE IF NOT EXISTS`` does *nothing at
    all* whatever the shape, and the next ``INSERT`` then fails on an unknown
    column. ``billing_readings`` grew from 40 columns to 60 at M4c (issue #24),
    so a sync shipped before that upgrade would have broken on every install
    the day it landed. Owner decision, 2026-08-24; it is why the account needs
    ``ALTER`` on top of ``CREATE``/``SELECT``/``INSERT``/``DELETE``.

    **Step 3 exists because ``CreateTable`` does not emit them.** SQLAlchemy
    renders a ``UniqueConstraint`` inline in ``CREATE TABLE`` but emits a plain
    ``Index`` as a separate ``CREATE INDEX`` statement, so a ``CreateTable``
    alone silently produces tables with no secondary index at all — measured
    against the real server on 2026-08-25, where the first ``SHOW CREATE
    TABLE`` came back without either of ours. Their absence costs nothing in
    correctness and a full scan per watermark query in speed. Existence is
    checked through ``information_schema.statistics`` rather than
    ``CREATE INDEX IF NOT EXISTS``, which MariaDB supports and **MySQL 8 does
    not**.

    **Step 4 closes a silent-corruption path.** ``INSERT … ON DUPLICATE KEY
    UPDATE`` degenerates into a plain ``INSERT`` when there is no unique key to
    collide with, so a ``load_profile_readings`` that somehow exists without
    ours would gain a duplicate set of rows on every cycle, forever, reporting
    success each time. Nothing here tries to *add* the key — that would fail on
    a table already holding duplicates, and it is not our place to reshape a
    table we did not create. It raises instead, which surfaces on the page as
    the cycle's error.

    **A column we do not recognise is left alone** — it may be one the customer
    added, and this is their database. Nothing here drops a column, changes a
    type, changes a width, or renames anything: the only DDL it can emit is
    ``CREATE TABLE``, ``ADD COLUMN`` and ``CREATE INDEX``.

    Args:
        connection: An open connection to the destination. The caller owns the
            transaction — the DDL below is not rolled back by MySQL or MariaDB
            in any case, which is one more reason nothing destructive belongs
            in it.

    Returns:
        Whether ``load_profile_readings`` is a per-logger table that was left
        alone. Returned rather than asked again by the caller: the columns are
        already in hand here, and a second ``information_schema`` query every
        fifteen minutes, for ever, is a lot to pay for a one-time upgrade.

    Raises:
        RuntimeError: When a merged-shape ``load_profile_readings`` has no
            unique key over ``(meter_serial, read_at)``.
    """
    for table in TABLES:
        connection.execute(sa.schema.CreateTable(table, if_not_exists=True))

    existing = _existing_columns(connection)
    per_logger = _LOGGER_COLUMN in existing.get(LOAD_PROFILE_TABLE.name, set())
    ours = [table for table in TABLES if not (per_logger and table is LOAD_PROFILE_TABLE)]
    for table in ours:
        present = existing.get(table.name, set())
        if not present:
            # Freshly created above, or reported empty by information_schema —
            # either way there is nothing an ALTER could add.
            continue
        previous: str | None = None
        for column in table.columns:
            if column.name in present:
                previous = column.name
                continue
            logger.info(
                "Database Destination: adding missing column %s.%s — the destination's schema follows ours",
                table.name,
                column.name,
            )
            connection.execute(sa.text(_add_column_sql(connection, table, column, after=previous)))
            previous = column.name

    index_names = _existing_index_names(connection)
    for table in ours:
        for index in table.indexes:
            if index.name in index_names.get(table.name, set()):
                continue
            logger.info("Database Destination: creating missing index %s on %s", index.name, table.name)
            connection.execute(sa.schema.CreateIndex(index))

    if per_logger:
        return True
    if not _load_profile_unique_key_names().intersection(index_names.get(LOAD_PROFILE_TABLE.name, set())):
        raise RuntimeError(
            f"The destination's {LOAD_PROFILE_TABLE.name} has no unique key over "
            "(meter_serial, read_at). ARICHDS relies on it to collapse a re-sent row onto the "
            "existing one; without it every cycle would add duplicates. Drop or repair that table and let "
            "ARICHDS create it."
        )
    return False


def per_logger_load_profile_error() -> RuntimeError:
    """What the load-profile step raises when :func:`reconcile` answered ``True``.

    The per-logger table's unique key includes ``logger_id`` and that column is
    ``NOT NULL``, so a merged row (ADR 0027) cannot be written into it, and
    reshaping a key on a table that holds rows is not ours to do in someone
    else's database. The message names the way out — drop the table;
    :func:`reconcile` recreates it and the next cycle re-sends the whole window.

    Raised by the load-profile step only, **after** billing has been replaced:
    the refusal is about this one table, and the cycle's error on the Database
    page is loud enough without freezing a table it has nothing to do with.
    """
    return RuntimeError(
        f"The destination's {LOAD_PROFILE_TABLE.name} is the per-logger table an earlier ARICHDS created "
        f"(it has a {_LOGGER_COLUMN} column). ARICHDS now writes one merged row per interval, keyed on "
        f"(meter_serial, read_at). Run DROP TABLE {LOAD_PROFILE_TABLE.name}; on the destination — ARICHDS "
        "recreates it and re-sends its whole window on the next cycle."
    )


def _load_profile_unique_key_names() -> set[str]:
    """Index names that would satisfy the load-profile unique key.

    Ours by name, plus MySQL's own habit of naming a unique key after its
    leading column when one is declared without a name.
    """
    constraint = next(c for c in LOAD_PROFILE_TABLE.constraints if isinstance(c, sa.UniqueConstraint))
    return {str(constraint.name), "meter_serial"}


def _add_column_sql(connection: Connection, table: Table, column: sa.Column, *, after: str | None = None) -> str:
    """``ALTER TABLE … ADD COLUMN`` for one column, quoted for this server.

    Built by hand because SQLAlchemy Core has no ``ADD COLUMN`` DDL construct —
    Alembic owns that job for our own database, and pulling Alembic in to point
    at someone else's would be far more machinery than one statement is worth.
    The type text comes from the dialect's own type compiler, so it is exactly
    what ``CREATE TABLE`` would have emitted for the same column.

    A ``NOT NULL`` column added to a table that already holds rows is left to
    fail on the server rather than being quietly relaxed to nullable: every
    column this product has *added* since M6a has been nullable, so reaching
    that case means the destination table is not one of ours, and a loud
    failure is the honest answer.
    """
    preparer = connection.dialect.identifier_preparer
    type_text = connection.dialect.type_compiler_instance.process(column.type)
    null_text = "NULL" if column.nullable else "NOT NULL"
    # *after* is the nearest preceding column of ours the destination has. With
    # none — our first column is the missing one — the server's default (last)
    # stands: that column is NOT NULL in both tables, so the table is not ours.
    position_text = f" AFTER {preparer.quote(after)}" if after is not None else ""
    return (
        f"ALTER TABLE {preparer.quote(table.name)} ADD COLUMN {preparer.quote(column.name)} "
        f"{type_text} {null_text}{position_text}"
    )


def _existing_columns(connection: Connection) -> dict[str, set[str]]:
    """The columns each of our two tables currently has, per the server.

    Scoped to ``DATABASE()`` rather than to a name we pass in, so it can only
    ever describe the database this connection is actually attached to.
    """
    rows = connection.execute(
        sa.text(
            "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.columns "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN :names"
        ).bindparams(sa.bindparam("names", expanding=True)),
        {"names": [table.name for table in TABLES]},
    )
    found: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        found.setdefault(str(table_name), set()).add(str(column_name))
    return found


def _existing_index_names(connection: Connection) -> dict[str, set[str]]:
    """The index names each of our two tables currently has, per the server."""
    rows = connection.execute(
        sa.text(
            "SELECT TABLE_NAME, INDEX_NAME FROM information_schema.statistics "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN :names"
        ).bindparams(sa.bindparam("names", expanding=True)),
        {"names": [table.name for table in TABLES]},
    )
    found: dict[str, set[str]] = {}
    for table_name, index_name in rows:
        found.setdefault(str(table_name), set()).add(str(index_name))
    return found
