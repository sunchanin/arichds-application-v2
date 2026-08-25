"""The Database Destination cycle (issue #46, SPEC §3.10, ADR 0020/0021).

Every fifteen minutes, on the scheduler's one existing thread: replace
``billing_readings`` wholesale, append the ``load_profile_readings`` the
destination does not have, and delete rows past the **Mirror Window**
(CONTEXT.md) from the destination's copy.

**Nothing is persisted on our side.** ADR 0008 forbids job state of any kind,
and this module honours it structurally rather than by discipline: the
watermark *is* the destination's own ``MAX(read_at)``, so there is no record to
keep and a partial cycle is not a lost cycle. The status the page shows is one
frozen dataclass in memory (:mod:`.status`).

**Local time on the way out** (ADR 0021). :func:`_to_local` and
:func:`_from_local` are the single pair the row write, the watermark read and
the purge cutoff all go through, because *"a missing or doubled conversion is
seven hours of silently duplicated or skipped rows, with no error on either
side"*. The same arithmetic is written out at
``acquisition/drivers/_dlms_profile.py:887`` for a different purpose and at
``export/format.py:159-162`` for the CSV; ADR 0021's Consequences forbid
sharing a helper with either — *"they agree today by coincidence of the same
constant, not by contract"* — so this module imports from neither.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.dialects.mysql import insert as mysql_insert

from arichds.config import get_settings
from arichds.constants import (
    DBDEST_ROW_CHUNK,
    DBDEST_SYNC_BUDGET_SEC,
    DBDEST_WATERMARK_REWIND_SEC,
    METER_LOCAL_UTC_OFFSET_HOURS,
    RETENTION_DAYS,
)
from arichds.dataout.destination import create_destination_engine, load_config
from arichds.dataout.schema import BILLING_TABLE, LOAD_PROFILE_TABLE, reconcile
from arichds.dataout.status import SyncStatus, set_last_sync
from arichds.db.models import BillingReading, Device, LoadProfileReading
from arichds.db.session import session_scope
from arichds.licensing.current import current_license_service
from arichds.licensing.features import feature_enabled

logger = logging.getLogger(__name__)

_OFFSET = timedelta(hours=METER_LOCAL_UTC_OFFSET_HOURS)


# ─── The one conversion pair (ADR 0021) ───────────────────────────────────────


def _to_local(value: datetime) -> datetime:
    """Our UTC → the destination's naive local time.

    A naive input is treated as UTC, which is correct rather than lenient:
    SQLite hands datetimes back naive even from a ``DateTime(timezone=True)``
    column, and every one of them is UTC by CLAUDE.md's write-time
    normalization invariant.

    The result is **naive** because the destination's columns are ``DATETIME``,
    which carries no zone at all (ADR 0021: that is the price the owner
    accepted for not depending on the customer's ``my.ini``).
    """
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return (aware.astimezone(UTC) + _OFFSET).replace(tzinfo=None)


def _from_local(value: datetime) -> datetime:
    """The destination's naive local time → our timezone-aware UTC.

    The inverse of :func:`_to_local`, and the one used on the watermark. Any
    zone on the input is discarded rather than honoured: the value came out of
    a ``DATETIME`` column, so a zone on it would be the driver's invention.
    """
    naive = value.replace(tzinfo=None) if value.tzinfo is not None else value
    return (naive - _OFFSET).replace(tzinfo=UTC)


def _purge_cutoff(now_utc: datetime) -> datetime:
    """The Mirror Window's oldest surviving instant, in the destination's clock.

    **Computed in local time, deliberately** (ADR 0020): the rows it is
    compared against are local, and computing it in UTC silently deletes seven
    hours too much on every cycle with nothing to notice it.
    """
    return _to_local(now_utc - timedelta(days=RETENTION_DAYS))


def _watermark_start(destination_max_local: datetime | None) -> datetime | None:
    """Where to resume sending from, in our UTC, given the destination's newest row.

    Two things happen here and both matter. The destination's value is
    converted **back** to UTC before it can be compared with ours, and it is
    then rewound by :data:`~arichds.constants.DBDEST_WATERMARK_REWIND_SEC`. The
    rewind is what turns an off-by-offset from silent corruption into bounded
    waste: the re-sent rows collapse onto the existing ones through
    ``ON DUPLICATE KEY UPDATE`` against the unique key.

    ``None`` in means ``None`` out — a destination that has never seen this
    ``(meter_serial, logger_id)`` gets everything we hold, which is the first
    cycle's backfill.
    """
    if destination_max_local is None:
        return None
    return _from_local(destination_max_local) - timedelta(seconds=DBDEST_WATERMARK_REWIND_SEC)


def _local_row(row: dict[str, Any]) -> dict[str, Any]:
    """Copy *row* with every datetime value shifted to the destination's clock.

    Type-driven rather than name-driven: billing carries fourteen datetime
    columns, ten of them the Demand Time columns M4c added, and a list of names
    would have gone stale at that upgrade the same way a hand-written schema
    would. ``None`` passes through — thirteen of billing's columns are NULL on
    a real row.

    Returns a new dict; the caller may still hold the original, and an in-place
    shift would double on any retry.
    """
    return {key: _to_local(value) if isinstance(value, datetime) else value for key, value in row.items()}


# ─── The cycle ────────────────────────────────────────────────────────────────


def database_destination_cycle() -> None:
    """Write our two tables into the customer's database, once.

    The Scheduler's ``dbdest_sync`` job — see
    :func:`arichds.jobs.scheduler.default_jobs`, registered **last** because it
    is the only network job that can legitimately consume its whole budget, and
    everything ahead of it is a meter read or a local disk job that should not
    queue behind it within a pass.

    **Order within a cycle: billing replace → load-profile append → purge.**
    Billing first because it is small (28 rows today), bounded and
    all-or-nothing, and a large first-run load-profile backfill must not starve
    it for cycles. The purge runs even when the append hit its budget — the
    Mirror Window must not drift — but not when the connection itself failed.

    Nothing propagates: a failure is recorded on the in-memory status and the
    job runs again in fifteen minutes. The scheduler's own guard would log it
    too, but then the page would have nothing to show, and *"without that the
    operator cannot tell a working sync from a silent one"*.
    """
    settings = get_settings()
    license_service = current_license_service()
    if not feature_enabled("database_destination", license_service=license_service, settings=settings):
        return

    with session_scope() as session:
        config = load_config(session)

    if not config.configured:
        logger.debug("Database Destination: not configured — nothing to do")
        return

    send_load_profile = feature_enabled("load_profile", license_service=license_service, settings=settings)
    send_billing = feature_enabled("billing", license_service=license_service, settings=settings)

    started = time.monotonic()
    deadline = started + DBDEST_SYNC_BUDGET_SEC
    counts = _Counts()
    error: str | None = None
    engine: Engine | None = None
    try:
        engine = create_destination_engine(config)
        _run_cycle(engine, deadline=deadline, counts=counts, billing=send_billing, load_profile=send_load_profile)
    except Exception as exc:  # noqa: BLE001 — a customer's database being down must never strand the scheduler.
        error = f"{type(exc).__name__}: {exc}"
        logger.exception("Database Destination cycle failed")
    finally:
        if engine is not None:
            # One engine per cycle, disposed here: the settings can change
            # through the PUT at any moment and a 15-minute cadence makes a
            # pool worthless.
            engine.dispose()

    set_last_sync(
        SyncStatus(
            ran_at=datetime.now(UTC),
            load_profile_rows=counts.load_profile,
            billing_rows=counts.billing,
            purged_rows=counts.purged,
            skipped_rows=counts.skipped,
            duration_sec=round(time.monotonic() - started, 3),
            error=error,
            budget_exhausted=counts.budget_exhausted,
        )
    )
    logger.info(
        "Database Destination cycle: %d Interval Reading(s) sent, %d Billing Reading(s) replaced, "
        "%d purged past the Mirror Window, %d skipped for a missing Meter Serial, in %.2fs%s",
        counts.load_profile,
        counts.billing,
        counts.purged,
        counts.skipped,
        time.monotonic() - started,
        " (budget exhausted — resuming next tick)" if counts.budget_exhausted else "",
    )


class _Counts:
    """One cycle's running totals, so a partial cycle still reports honestly."""

    __slots__ = ("billing", "budget_exhausted", "load_profile", "purged", "skipped")

    def __init__(self) -> None:
        self.load_profile = 0
        self.billing = 0
        self.purged = 0
        self.skipped = 0
        self.budget_exhausted = False


def _run_cycle(engine: Engine, *, deadline: float, counts: _Counts, billing: bool, load_profile: bool) -> None:
    """Reconcile the schema, then do the three pieces of work in order."""
    with engine.begin() as connection:
        reconcile(connection)

    # Checked **before** the transaction opens and never inside it: a budget
    # check mid-replace would leave the destination holding a partial set of
    # periods, which is exactly what the single transaction exists to prevent.
    #
    # It skips *billing*, and deliberately does not return from the cycle: the
    # purge below must still get its turn, or an exhausted budget would let the
    # Mirror Window drift (ADR 0020).
    if billing and not _out_of_budget(deadline, counts):
        _replace_billing(engine, counts)

    # The purge sits **inside** the `load_profile` gate, deliberately. A licence
    # that keeps `database_destination` but loses `load_profile` therefore stops
    # appending *and* stops purging, so the destination holds rows past
    # RETENTION_DAYS that our own (un-gated) retention job has already deleted
    # here — briefly an archive, which ADR 0020 refuses. The other reading was
    # available: purge regardless, so the Mirror Window keeps shrinking on a
    # table we may no longer write. "Do not touch a table you are not licensed
    # for" won, because a lapsed entitlement should freeze a destination rather
    # than quietly drain the customer's copy, and the state needs a mid-life
    # licence change to reach at all (Limited Mode returns at the top of
    # `database_destination_cycle`). Recorded so the next reader knows this was
    # chosen rather than missed.
    if load_profile:
        _append_load_profile(engine, deadline=deadline, counts=counts)
        # The purge runs even when the append ran out of budget — the Mirror
        # Window must not drift while a first-run backfill takes several
        # cycles to finish (ADR 0020). `_purge_destination` runs one batch
        # before it consults the budget at all, for the same reason.
        _purge_destination(engine, deadline=deadline, counts=counts)


def _out_of_budget(deadline: float, counts: _Counts) -> bool:
    """Whether the cycle's wall clock is spent, recording it if so."""
    if time.monotonic() < deadline:
        return False
    counts.budget_exhausted = True
    return True


# ─── Billing — whole-table replace, one transaction (ADR 0009/0016) ────────────


def _replace_billing(engine: Engine, counts: _Counts) -> None:
    """Delete every destination billing row and write ours, atomically.

    Required rather than chosen: the Open Period row is upserted **in place**
    on every read, and the table's identity is two *partial* unique indexes
    that neither MySQL nor MariaDB can express (ADR 0016). A whole-table
    replace is what keeps the destination correct without them.

    ``DELETE``, **never ``TRUNCATE``** — ``TRUNCATE`` is DDL, cannot be rolled
    back, and would show a concurrent reader an empty table mid-cycle. Inside
    one ``engine.begin()``, so a failure anywhere leaves the destination's
    previous contents intact.

    **``billing_readings`` is never purged**, here or on our side (ADR
    0009/0020): a closed period is never rewritten or removed, and the
    destination copy is kept current by this replace rather than by a window.
    On this machine the oldest load-profile row is 90 days old and the oldest
    billing row is 357.
    """
    rows, skipped = _billing_rows()
    counts.skipped += skipped

    with engine.begin() as connection:
        connection.execute(sa.delete(BILLING_TABLE))
        for chunk in _chunks(rows, DBDEST_ROW_CHUNK):
            connection.execute(sa.insert(BILLING_TABLE), chunk)
            counts.billing += len(chunk)


def _billing_rows() -> tuple[list[dict[str, Any]], int]:
    """Every Billing Reading we hold, shaped for the destination.

    ``billing_readings.meter_serial`` is nullable, and ADR 0018 records that
    **both** driver read paths store ``meter_serial=None`` when the serial
    register read fails after the buffer was read. So the row's own snapshot is
    tried first and ``devices.meter_serial`` is the fallback; a row with
    neither is skipped and counted, because it is unattributable at a
    destination keyed on Meter Serial. Without the fallback a closed period
    written during one failed serial read would never reach the destination at
    all.

    Returns:
        The rows to insert, and how many were skipped.
    """
    source = BillingReading.__table__
    device = Device.__table__
    columns = [column for column in source.columns if column.name in BILLING_TABLE.columns]
    statement = sa.select(*columns, device.c.meter_serial.label("_device_serial")).select_from(
        source.join(device, device.c.id == source.c.device_id)
    )

    rows: list[dict[str, Any]] = []
    skipped = 0
    with session_scope() as session:
        for mapping in session.execute(statement).mappings():
            row = dict(mapping)
            serial = row.pop("_device_serial")
            row["meter_serial"] = row.get("meter_serial") or serial
            if not row["meter_serial"]:
                skipped += 1
                continue
            rows.append(_local_row(row))

    if skipped:
        logger.warning(
            "Database Destination: %d Billing Reading(s) have no Meter Serial on the row or its device — not sent",
            skipped,
        )
    return rows, skipped


# ─── Load profile — append from the destination's own watermark ───────────────


def _append_load_profile(engine: Engine, *, deadline: float, counts: _Counts) -> None:
    """Send every Interval Reading the destination does not already have.

    The watermark is **per ``(meter_serial, logger_id)``, never per meter**: a
    logger that lags behind another must keep its own and catch up without
    being masked. That is the same failure ADR 0008 had to fix on our own side
    at issue #24, where the watermark was taking ``MIN`` across loggers and
    stalling one behind the other.

    **The source query filters on the watermark in SQL.** The design probe read
    all 61,023 rows on every run and discarded most of them in a Python loop;
    that cost 0.4 s at three meters and does not scale to twenty. No code path
    here reads the whole table into memory.
    """
    watermarks = _destination_watermarks(engine)

    for device_id, logger_id, serial in _source_pairs():
        if serial is None:
            # Counted only on the miss — see `_source_pairs`.
            missing_rows = _unattributable_row_count(device_id, logger_id)
            counts.skipped += missing_rows
            logger.warning(
                "Database Destination: device id %s has no Meter Serial — its %d Interval Reading(s) on logger %s "
                "cannot be attributed at the destination and were not sent",
                device_id,
                missing_rows,
                logger_id,
            )
            continue
        if _out_of_budget(deadline, counts):
            return
        _send_pair(engine, device_id, logger_id, serial, watermarks, deadline=deadline, counts=counts)


def _destination_watermarks(engine: Engine) -> dict[tuple[str, int], datetime]:
    """The destination's newest ``read_at`` per ``(meter_serial, logger_id)``.

    Values are **local**, straight out of a ``DATETIME`` column;
    :func:`_watermark_start` is what converts them back.
    """
    statement = sa.select(
        LOAD_PROFILE_TABLE.c.meter_serial,
        LOAD_PROFILE_TABLE.c.logger_id,
        sa.func.max(LOAD_PROFILE_TABLE.c.read_at),
    ).group_by(LOAD_PROFILE_TABLE.c.meter_serial, LOAD_PROFILE_TABLE.c.logger_id)

    with engine.connect() as connection:
        return {(str(serial), int(logger_id)): newest for serial, logger_id, newest in connection.execute(statement)}


def _source_pairs() -> list[tuple[int, int, str | None]]:
    """Every ``(device_id, logger_id)`` we hold rows for, with its Meter Serial.

    ``DISTINCT`` rather than ``GROUP BY … COUNT(*)``. An earlier version
    aggregated a count here so the "no Meter Serial" warning could name a
    number, which meant every cycle paid a full aggregate over
    ``load_profile_readings`` — ``logger_id`` is not in
    ``ix_load_profile_readings_device_read_at``, so at 60k+ rows that is a scan
    plus a temp b-tree — to populate a log line that normally never fires (the
    design probe measured 0 such rows). :func:`_unattributable_row_count` now
    issues that count only on the miss.
    """
    source = LoadProfileReading.__table__
    device = Device.__table__
    statement = (
        sa.select(source.c.device_id, source.c.logger_id, device.c.meter_serial)
        .select_from(source.join(device, device.c.id == source.c.device_id))
        .distinct()
        .order_by(source.c.device_id, source.c.logger_id)
    )

    with session_scope() as session:
        return [(int(device_id), int(logger_id), serial) for device_id, logger_id, serial in session.execute(statement)]


def _unattributable_row_count(device_id: int, logger_id: int) -> int:
    """How many rows one serial-less ``(device, logger)`` holds.

    Exact rather than approximate: a device with no Meter Serial has nothing at
    the destination, so every row it holds is a row not sent. Issued only when
    a device actually lacks a serial, which on a healthy site is never.
    """
    source = LoadProfileReading.__table__
    statement = sa.select(sa.func.count()).where(source.c.device_id == device_id, source.c.logger_id == logger_id)
    with session_scope() as session:
        return int(session.execute(statement).scalar_one())


def _send_pair(
    engine: Engine,
    device_id: int,
    logger_id: int,
    serial: str,
    watermarks: dict[tuple[str, int], datetime],
    *,
    deadline: float,
    counts: _Counts,
) -> None:
    """Send one ``(meter_serial, logger_id)``'s pending rows, chunk by chunk."""
    start = _watermark_start(watermarks.get((serial, logger_id)))

    while True:
        rows = _source_chunk(device_id, logger_id, serial, start)
        if not rows:
            return
        _insert_load_profile(engine, rows)
        counts.load_profile += len(rows)
        # `read_at` is still UTC on the source rows; `_local_row` is applied
        # inside `_insert_load_profile`, so paging stays in our own clock and
        # the conversion happens exactly once.
        start = rows[-1]["read_at"]
        if len(rows) < DBDEST_ROW_CHUNK or _out_of_budget(deadline, counts):
            return


def _source_chunk(device_id: int, logger_id: int, serial: str, start: datetime | None) -> list[dict[str, Any]]:
    """One page of source rows newer than *start*, in ``read_at`` order.

    The watermark is applied **in SQL**, which is the whole point: the
    destination's own newest row decides what SQLite is asked for, so a
    steady-state cycle reads about 28 rows rather than 61,023.
    """
    source = LoadProfileReading.__table__
    columns = [column for column in source.columns if column.name in LOAD_PROFILE_TABLE.columns]
    statement = sa.select(*columns).where(source.c.device_id == device_id, source.c.logger_id == logger_id)
    if start is not None:
        statement = statement.where(source.c.read_at > start)
    statement = statement.order_by(source.c.read_at).limit(DBDEST_ROW_CHUNK)

    with session_scope() as session:
        return [{**dict(mapping), "meter_serial": serial} for mapping in session.execute(statement).mappings()]


def _insert_load_profile(engine: Engine, rows: Sequence[dict[str, Any]]) -> None:
    """Write one chunk with ``INSERT … ON DUPLICATE KEY UPDATE``.

    **Never ``INSERT IGNORE``.** Measured against MariaDB 10.4.32 on
    2026-08-24: ``IGNORE`` downgrades data errors to warnings *even under*
    ``STRICT_TRANS_TABLES``, so ``REPEAT('X',80)`` into a ``VARCHAR(64)``
    stored 64 characters and raised nothing, while both plain ``INSERT`` and
    ``ON DUPLICATE KEY UPDATE`` raised ``ERROR 1406 Data too long``. ODKU
    deduplicates identically, so the dedup was never worth buying with a
    swallowed error.

    The update clause re-asserts ``source``, one non-key column, because MySQL
    requires a non-empty update list and these rows **never change value** once
    written — the assignment is therefore a no-op by construction rather than
    by coincidence.
    """
    statement = mysql_insert(LOAD_PROFILE_TABLE)
    statement = statement.on_duplicate_key_update(source=statement.inserted.source)
    with engine.begin() as connection:
        connection.execute(statement, [_local_row(row) for row in rows])


# ─── Purge — the Mirror Window (ADR 0020) ─────────────────────────────────────


def _purge_destination(engine: Engine, *, deadline: float, counts: _Counts) -> None:
    """Delete destination rows past the Mirror Window, in batches.

    ``load_profile_readings`` **only** — see :func:`_replace_billing` for why
    billing has no window at all.

    ``DELETE … LIMIT`` is available here, unlike on our own side: CPython's
    bundled SQLite is not built with ``SQLITE_ENABLE_UPDATE_DELETE_LIMIT``
    (``db/retention.py:86-98``), MySQL and MariaDB both support it.

    Appending and purging cannot collide, and that is structural rather than
    lucky: the append works from the newest end and this from the oldest.

    **At least one batch always runs, even when the append already spent the
    whole budget.** The budget is checked *after* a batch rather than before
    one, deliberately: a first-run backfill takes several cycles (61,023 rows
    on the design probe), and a purge that yielded to it every time would let
    the **Mirror Window drift** for as long as the backfill lasted — which is
    precisely what ADR 0020 says must not happen. The overrun that buys this is
    bounded by exactly one ``DELETE … LIMIT`` statement.
    """
    cutoff = _purge_cutoff(datetime.now(UTC))

    while True:
        removed = _purge_batch(engine, cutoff)
        counts.purged += removed
        if removed < DBDEST_ROW_CHUNK or _out_of_budget(deadline, counts):
            return


def _purge_batch(engine: Engine, cutoff: datetime) -> int:
    """One ``DELETE … LIMIT`` batch, its own transaction."""
    # The limit is interpolated rather than bound: it is our own `Final[int]`
    # constant, never operator input, and MySQL will not accept a placeholder
    # there through a server-side prepared statement.
    statement = sa.text(f"DELETE FROM {LOAD_PROFILE_TABLE.name} WHERE read_at < :cutoff LIMIT {int(DBDEST_ROW_CHUNK)}")
    with engine.begin() as connection:
        return int(connection.execute(statement, {"cutoff": cutoff}).rowcount)


def _chunks(rows: Sequence[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    """Slice *rows* into lists of at most *size*."""
    for start in range(0, len(rows), size):
        yield list(rows[start : start + size])


__all__ = ["database_destination_cycle"]
