"""Opt-in integration tests — a **real** MariaDB/MySQL (issue #46, SPEC §3.10).

**Skipped by default**, the shape ``test_capture_screenshot_integration.py``
established. Run them explicitly::

    ARICHDS_TEST_MYSQL_URL=mysql+pymysql://root:@127.0.0.1:3306/arichds_dest \\
        app/.venv/Scripts/python.exe -m pytest tests/test_dataout_mysql.py -v

Everything here is asserted against what the server actually did, never against
a compiled SQL string. That is deliberate: SQLAlchemy's MySQL and MariaDB
dialects are not identical, so a string assertion against ``mysql.dialect()``
can pass while MariaDB receives something different — and the two decisions
this module rests on (``INSERT … ON DUPLICATE KEY UPDATE`` over
``INSERT IGNORE``, and a session ``sql_mode`` we set ourselves) were both
*measured* rather than reasoned into existence.

Each test drops and recreates the two tables in the configured database, so
runs are independent. Those two tables are ARICHDS's own — the module creates
them and is their only writer (CONTEXT.md — Database Destination) — and no
other object in the database is touched. The one exception is
:class:`TestMissingPrivilegeAgainstARealAccount`, which creates one restricted
user and drops it in the same test.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DataError, OperationalError

from arichds.config import Settings
from arichds.constants import (
    DBDEST_SESSION_SQL_MODE,
    DBDEST_WATERMARK_REWIND_SEC,
    METER_LOCAL_UTC_OFFSET_HOURS,
    RETENTION_DAYS,
    SOURCE_DLMS,
)
from arichds.dataout import sync
from arichds.dataout.destination import (
    DestinationConfig,
    check_destination_connection,
    create_destination_engine,
)
from arichds.dataout.schema import BILLING_TABLE, LOAD_PROFILE_TABLE, reconcile
from arichds.dataout.status import last_sync, set_last_sync
from arichds.db.app_settings import (
    DB_DEST_DATABASE_KEY,
    DB_DEST_HOST_KEY,
    DB_DEST_PASSWORD_KEY,
    DB_DEST_PORT_KEY,
    DB_DEST_USER_KEY,
    set_setting,
)
from arichds.db.models import BillingReading, Device, LoadProfileReading
from arichds.db.session import session_scope
from arichds.licensing.current import set_current_license_service
from arichds.licensing.service import LicenseState

_URL_ENV = "ARICHDS_TEST_MYSQL_URL"

pytestmark = pytest.mark.skipif(
    not os.environ.get(_URL_ENV),
    reason=f"set {_URL_ENV} to run the Database Destination integration tests against a real MariaDB/MySQL",
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


class _StubLicenseService:
    def __init__(self, features: list[str] | None) -> None:
        self._features = features

    def current_state(self) -> LicenseState:
        return LicenseState(state="active", reason=None, features=self._features)


@pytest.fixture
def config() -> DestinationConfig:
    """The destination under test, parsed from ``ARICHDS_TEST_MYSQL_URL``."""
    url = sa.make_url(os.environ[_URL_ENV])
    return DestinationConfig(
        host=url.host or "127.0.0.1",
        port=url.port or 3306,
        database=url.database or "",
        user=url.username or "",
        password=url.password or "",
    )


@pytest.fixture
def destination(config: DestinationConfig):
    """A disposed-at-the-end engine, with our two tables dropped either side.

    Dropped **before** as well as after: the design probe left both tables
    behind under exactly these names, so a test that only cleaned up
    afterwards would silently inherit that state on its first run — and
    ``CREATE TABLE IF NOT EXISTS`` against an existing table does nothing at
    all, which is precisely the failure decision 8b exists to fix.
    """
    engine = create_destination_engine(config)
    _drop_our_tables(engine)
    yield engine
    _drop_our_tables(engine)
    engine.dispose()


def _drop_our_tables(engine) -> None:  # noqa: ANN001
    with engine.begin() as connection:
        for table in (LOAD_PROFILE_TABLE.name, BILLING_TABLE.name):
            connection.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))


@pytest.fixture
def licensed():
    """Every sellable key, through the process-wide holder the job reads."""
    set_current_license_service(_StubLicenseService(None))
    set_last_sync(None)
    yield
    set_current_license_service(None)
    set_last_sync(None)


@pytest.fixture
def configured(migrated_db: Settings, config: DestinationConfig) -> DestinationConfig:
    """Our own SQLite migrated, with the five destination settings written."""
    with session_scope() as session:
        set_setting(session, DB_DEST_HOST_KEY, config.host)
        set_setting(session, DB_DEST_PORT_KEY, str(config.port))
        set_setting(session, DB_DEST_DATABASE_KEY, config.database)
        set_setting(session, DB_DEST_USER_KEY, config.user)
        set_setting(session, DB_DEST_PASSWORD_KEY, config.password)
    return config


# ─── Seeding helpers ──────────────────────────────────────────────────────────


def add_device(name: str, serial: str | None) -> int:
    with session_scope() as session:
        device = Device(
            name=name,
            brand="mitsu",
            model="smw110",
            meter_serial=serial,
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="hunter2",
        )
        session.add(device)
        session.flush()
        return device.id


def add_intervals(device_id: int, logger_id: int, read_ats: list[datetime], *, kwh: float = 1.5) -> None:
    with session_scope() as session:
        for read_at in read_ats:
            session.add(
                LoadProfileReading(
                    device_id=device_id,
                    read_at=read_at,
                    source=SOURCE_DLMS,
                    logger_id=logger_id,
                    interval_sec=900,
                    import_active_kwh=kwh,
                )
            )


def add_billing(device_id: int, bill_date: datetime, *, serial: str | None, status: str | None = None) -> None:
    with session_scope() as session:
        session.add(
            BillingReading(
                device_id=device_id,
                bill_date=bill_date,
                read_at=datetime(2026, 8, 24, 6, 0, tzinfo=UTC),
                record_status=status,
                source=SOURCE_DLMS,
                meter_serial=serial,
                import_active_kwh_total=147029.6554881,
            )
        )


def count(engine, table: str) -> int:  # noqa: ANN001
    with engine.connect() as connection:
        return int(connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one())


def rows(engine, statement: str):  # noqa: ANN001
    with engine.connect() as connection:
        return connection.execute(sa.text(statement)).all()


# ─── The engine itself ────────────────────────────────────────────────────────


class TestTheConnection:
    def test_the_server_is_the_one_this_module_was_designed_against(self, destination) -> None:  # noqa: ANN001
        """Our own evidence for what is answering, rather than inherited."""
        with destination.connect() as connection:
            version = connection.execute(sa.text("SELECT VERSION()")).scalar_one()

        assert version
        print(f"\nSELECT VERSION() -> {version}")

    def test_we_set_the_session_sql_mode_rather_than_inheriting_it(self, destination) -> None:  # noqa: ANN001
        """Decision 7b. The reference server runs **without**
        `STRICT_TRANS_TABLES`, which makes over-long and out-of-range values
        truncate or clamp silently. Read back from a real connection, not
        asserted against the constant we sent."""
        with destination.connect() as connection:
            session_mode = connection.execute(sa.text("SELECT @@session.sql_mode")).scalar_one()
            global_mode = connection.execute(sa.text("SELECT @@global.sql_mode")).scalar_one()

        assert set(str(session_mode).split(",")) == set(DBDEST_SESSION_SQL_MODE.split(","))
        assert "STRICT_TRANS_TABLES" in str(session_mode)
        # The point of the exercise: what we set is not what the server would
        # have given us. If a future server already had it, this assertion is
        # the one that would need re-reading, not deleting.
        print(f"\n@@global.sql_mode -> {global_mode}\n@@session.sql_mode -> {session_mode}")

    def test_the_scheme_resolves_to_the_right_engine_family(self, destination) -> None:  # noqa: ANN001
        """`mysql+pymysql://` accepts both; `mariadb+pymysql://` would refuse
        a real MySQL 8."""
        assert destination.dialect.name == "mysql"


class TestTestConnectionAgainstTheRealServer:
    def test_ok_carries_the_version(self, config: DestinationConfig) -> None:
        check = check_destination_connection(config)

        assert check.result == "ok", check.message
        assert check.server_version
        assert config.database in check.message

    def test_a_wrong_password_is_auth_failed(self, config: DestinationConfig) -> None:
        check = check_destination_connection(
            DestinationConfig(config.host, config.port, config.database, config.user, "definitely-not-the-password")
        )

        assert check.result == "auth_failed", check.message
        assert check.server_version is None

    def test_an_unknown_database_is_database_missing(self, config: DestinationConfig) -> None:
        check = check_destination_connection(
            DestinationConfig(config.host, config.port, "arichds_no_such_database", config.user, config.password)
        )

        assert check.result == "database_missing", check.message
        assert "arichds_no_such_database" in check.message

    def test_a_port_with_nothing_listening_is_unreachable(self, config: DestinationConfig) -> None:
        check = check_destination_connection(
            DestinationConfig(config.host, 3307, config.database, config.user, config.password)
        )

        assert check.result == "unreachable", check.message

    def test_no_scratch_object_is_left_behind(self, config: DestinationConfig, destination) -> None:  # noqa: ANN001
        """ "Creates nothing permanent" — no temp table, no scratch row."""
        before = {r[0] for r in rows(destination, "SHOW TABLES")}

        check_destination_connection(config)

        assert {r[0] for r in rows(destination, "SHOW TABLES")} == before


class TestMissingPrivilegeAgainstARealAccount:
    """`root` holds ALL PRIVILEGES, so this branch cannot be reached through
    it. One deliberately restricted user is created and dropped **in this
    test**, and nothing else in the server is touched."""

    def test_an_account_without_alter_reports_missing_privilege(self, config: DestinationConfig, destination) -> None:  # noqa: ANN001
        user, password = "arichds_probe_ro", "probe-only-password"
        with destination.begin() as connection:
            connection.execute(sa.text(f"DROP USER IF EXISTS '{user}'@'%'"))
            connection.execute(sa.text(f"CREATE USER '{user}'@'%' IDENTIFIED BY '{password}'"))
            connection.execute(
                sa.text(f"GRANT SELECT, INSERT, DELETE, CREATE ON `{config.database}`.* TO '{user}'@'%'")
            )
            connection.execute(sa.text("FLUSH PRIVILEGES"))
        try:
            check = check_destination_connection(
                DestinationConfig(config.host, config.port, config.database, user, password)
            )

            assert check.result == "missing_privilege", check.message
            assert "ALTER" in check.message
            assert "could not confirm" in check.message
            assert "SELECT" not in check.message.split("privileges from SHOW GRANTS:")[1].split(".")[0]
        finally:
            with destination.begin() as connection:
                connection.execute(sa.text(f"DROP USER IF EXISTS '{user}'@'%'"))
                connection.execute(sa.text("FLUSH PRIVILEGES"))

    def test_the_restricted_user_is_gone_afterwards(self, config: DestinationConfig, destination) -> None:  # noqa: ANN001
        found = rows(destination, "SELECT user FROM mysql.user WHERE user = 'arichds_probe_ro'")

        assert found == []


# ─── Schema reconciliation ────────────────────────────────────────────────────


class TestReconcile:
    def test_both_tables_are_created_on_a_destination_that_has_none(self, destination) -> None:  # noqa: ANN001
        assert {r[0] for r in rows(destination, "SHOW TABLES")} & {
            LOAD_PROFILE_TABLE.name,
            BILLING_TABLE.name,
        } == set()

        with destination.begin() as connection:
            reconcile(connection)

        present = {r[0] for r in rows(destination, "SHOW TABLES")}
        assert LOAD_PROFILE_TABLE.name in present
        assert BILLING_TABLE.name in present

    def test_a_second_reconcile_creates_nothing_and_errors_on_nothing(self, destination) -> None:  # noqa: ANN001
        with destination.begin() as connection:
            reconcile(connection)
        first = rows(destination, f"SHOW CREATE TABLE {LOAD_PROFILE_TABLE.name}")

        with destination.begin() as connection:
            reconcile(connection)

        assert rows(destination, f"SHOW CREATE TABLE {LOAD_PROFILE_TABLE.name}") == first

    def test_the_created_shape_is_datetime_double_and_utf8mb4(self, destination) -> None:  # noqa: ANN001
        with destination.begin() as connection:
            reconcile(connection)

        ddl = rows(destination, f"SHOW CREATE TABLE {LOAD_PROFILE_TABLE.name}")[0][1]

        assert "`read_at` datetime" in ddl
        assert "timestamp" not in ddl.lower()
        assert "`import_active_kwh` double" in ddl
        assert "`meter_serial` varchar(64) NOT NULL" in ddl
        assert "ENGINE=InnoDB" in ddl
        assert "CHARSET=utf8mb4" in ddl
        print(f"\n{ddl}")

    def test_billing_lands_with_all_sixty_seven_columns_and_no_unique_key(self, destination) -> None:  # noqa: ANN001
        with destination.begin() as connection:
            reconcile(connection)

        ddl = rows(destination, f"SHOW CREATE TABLE {BILLING_TABLE.name}")[0][1]
        columns = rows(
            destination,
            "SELECT COLUMN_NAME FROM information_schema.columns WHERE TABLE_SCHEMA = DATABASE() "
            f"AND TABLE_NAME = '{BILLING_TABLE.name}'",
        )

        assert len(columns) == 67
        assert "UNIQUE KEY" not in ddl
        assert "device_id" not in ddl

    def test_both_secondary_indexes_actually_reach_the_server(self, destination) -> None:  # noqa: ANN001
        """`CreateTable` renders a UniqueConstraint inline but emits a plain
        `Index` as a **separate** statement — measured on 2026-08-25, where a
        first implementation produced tables with no secondary index at all
        while every Python-side assertion still passed."""
        with destination.begin() as connection:
            reconcile(connection)

        names = {
            (str(table), str(index))
            for table, index in rows(
                destination,
                "SELECT TABLE_NAME, INDEX_NAME FROM information_schema.statistics WHERE TABLE_SCHEMA = DATABASE()",
            )
        }

        assert (LOAD_PROFILE_TABLE.name, "ix_load_profile_readings_serial_read_at") in names
        assert (LOAD_PROFILE_TABLE.name, "uq_load_profile_readings_serial_logger_read_at") in names
        assert (BILLING_TABLE.name, "ix_billing_readings_serial_bill_date") in names

    def test_a_missing_column_is_added_by_alter_and_an_unknown_one_is_left_alone(self, destination) -> None:  # noqa: ANN001
        """Decision 8b. `billing_readings` went 40 → 60 columns at M4c, so
        `CREATE TABLE IF NOT EXISTS` alone would have broken every install at
        that upgrade."""
        with destination.begin() as connection:
            reconcile(connection)
        with destination.begin() as connection:
            connection.execute(sa.text(f"ALTER TABLE {LOAD_PROFILE_TABLE.name} DROP COLUMN avg_geo_pf"))
            connection.execute(
                sa.text(f"ALTER TABLE {BILLING_TABLE.name} DROP COLUMN cumul_demand_import_active_kw_rate_d")
            )
            connection.execute(
                sa.text(f"ALTER TABLE {BILLING_TABLE.name} ADD COLUMN the_customers_own VARCHAR(32) NULL")
            )

        with destination.begin() as connection:
            reconcile(connection)

        assert _columns(destination, LOAD_PROFILE_TABLE.name) >= {c.name for c in LOAD_PROFILE_TABLE.columns}
        assert _columns(destination, BILLING_TABLE.name) >= {c.name for c in BILLING_TABLE.columns}
        assert "the_customers_own" in _columns(destination, BILLING_TABLE.name)

    def test_a_load_profile_table_with_no_unique_key_is_refused_rather_than_duplicated_into(self, destination) -> None:  # noqa: ANN001
        """`ON DUPLICATE KEY UPDATE` degenerates into a plain `INSERT` when
        there is no unique key to collide with, so a table without ours would
        gain a duplicate set of rows on **every** cycle, forever, reporting
        success each time.

        `reconcile` refuses rather than adding the key: adding it would fail on
        a table that already holds duplicates, and reshaping a table we did not
        create is not ours to do. A refusal surfaces on the page as the cycle's
        error, which is the outcome that gets a human involved.
        """
        with destination.begin() as connection:
            reconcile(connection)
        with destination.begin() as connection:
            connection.execute(
                sa.text(
                    f"ALTER TABLE {LOAD_PROFILE_TABLE.name} DROP INDEX uq_load_profile_readings_serial_logger_read_at"
                )
            )

        with pytest.raises(RuntimeError, match="no unique key"), destination.begin() as connection:
            reconcile(connection)

    def test_nothing_is_ever_dropped_or_retyped(self, destination) -> None:  # noqa: ANN001
        """A widened column and an extra one both survive untouched: the only
        DDL `reconcile` can emit is CREATE TABLE, ADD COLUMN and CREATE
        INDEX."""
        with destination.begin() as connection:
            reconcile(connection)
        with destination.begin() as connection:
            connection.execute(
                sa.text(f"ALTER TABLE {LOAD_PROFILE_TABLE.name} MODIFY COLUMN source VARCHAR(99) NOT NULL")
            )
            connection.execute(sa.text(f"ALTER TABLE {LOAD_PROFILE_TABLE.name} ADD COLUMN keep_me VARCHAR(8) NULL"))

        with destination.begin() as connection:
            reconcile(connection)

        ddl = rows(destination, f"SHOW CREATE TABLE {LOAD_PROFILE_TABLE.name}")[0][1]
        assert "`source` varchar(99)" in ddl, "reconcile narrowed a column back — it must never retype"
        assert "`keep_me` varchar(8)" in ddl, "reconcile dropped a column it did not recognise"


def _columns(engine, table: str) -> set[str]:  # noqa: ANN001
    return {
        str(r[0])
        for r in rows(
            engine,
            "SELECT COLUMN_NAME FROM information_schema.columns WHERE TABLE_SCHEMA = DATABASE() "
            f"AND TABLE_NAME = '{table}'",
        )
    }


# ─── Strictness (decision 7b + finding 3) ─────────────────────────────────────


class TestAnOverWideValueRaisesRatherThanTruncating:
    def test_odku_raises_error_1406(self, destination) -> None:  # noqa: ANN001
        """Measured on this server 2026-08-24: `INSERT IGNORE` downgrades this
        to a warning **even under `STRICT_TRANS_TABLES`** and stores 64
        silently truncated characters, while ODKU raises. That is the whole
        reason `INSERT IGNORE` is forbidden."""
        with destination.begin() as connection:
            reconcile(connection)

        with pytest.raises((DataError, OperationalError)) as caught:
            sync._insert_load_profile(
                destination,
                [
                    {
                        "meter_serial": "X" * 80,
                        "read_at": datetime(2026, 8, 24, 13, 15, tzinfo=UTC),
                        "source": SOURCE_DLMS,
                        "logger_id": 1,
                        "interval_sec": 900,
                        # Supplied because `created_at` is NOT NULL with no
                        # server default, and under the strict mode we set,
                        # omitting it raises 1364 *before* the width check —
                        # which would make this test pass for the wrong
                        # reason.
                        "created_at": datetime(2026, 8, 24, 20, 15),
                    }
                ],
            )

        assert "1406" in str(caught.value) or "too long" in str(caught.value).lower()
        assert count(destination, LOAD_PROFILE_TABLE.name) == 0

    def test_insert_ignore_would_have_swallowed_it(self, destination) -> None:  # noqa: ANN001
        """The measurement itself, re-run here so the decision is evidenced by
        the suite rather than by a comment. If a future server version made
        `IGNORE` raise, this test tells us the ban could be revisited — it does
        not tell us to lift it."""
        with destination.begin() as connection:
            reconcile(connection)

        with destination.begin() as connection:
            connection.execute(
                sa.text(
                    f"INSERT IGNORE INTO {LOAD_PROFILE_TABLE.name} "
                    "(meter_serial, read_at, source, logger_id, interval_sec) "
                    "VALUES (:s, :r, :src, 1, 900)"
                ),
                {"s": "X" * 80, "r": datetime(2026, 8, 24, 20, 15), "src": SOURCE_DLMS},
            )

        stored = rows(destination, f"SELECT meter_serial FROM {LOAD_PROFILE_TABLE.name}")
        assert len(stored) == 1
        assert len(stored[0][0]) == 64, "INSERT IGNORE no longer truncates silently — re-read SPEC §3.10 before acting"


# ─── The cycle, end to end ────────────────────────────────────────────────────


def run_cycle() -> None:
    sync.database_destination_cycle()
    status = last_sync()
    assert status is not None
    assert status.error is None, status.error


class TestTheCycle:
    def test_a_first_cycle_sends_everything_and_a_second_adds_nothing(self, configured, destination, licensed) -> None:  # noqa: ANN001
        """The behaviour to reproduce (design probe): the first cycle
        backfills, every cycle after it is nearly free. Asserted on the
        **destination row count**, not on a "rows sent" figure."""
        device_id = add_device("Main", "WP079074")
        base = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
        add_intervals(device_id, 1, [base + timedelta(minutes=15 * i) for i in range(40)])
        add_billing(device_id, datetime(2026, 7, 31, 17, 0, tzinfo=UTC), serial="WP079074")

        run_cycle()
        after_first = count(destination, LOAD_PROFILE_TABLE.name)
        billing_first = count(destination, BILLING_TABLE.name)

        run_cycle()

        assert after_first == 40
        assert billing_first == 1
        assert count(destination, LOAD_PROFILE_TABLE.name) == 40, "the second cycle duplicated rows"
        assert count(destination, BILLING_TABLE.name) == 1

    def test_every_datetime_written_is_local_time(self, configured, destination, licensed) -> None:  # noqa: ANN001
        """ADR 0021, and the exact shift the design probe saw live:
        `2026-08-24 13:15:00` UTC arrived as `2026-08-24 20:15:00`, value
        unchanged."""
        device_id = add_device("Main", "WP079074")
        add_intervals(device_id, 1, [datetime(2026, 8, 24, 13, 15, tzinfo=UTC)], kwh=0.0085671)
        add_billing(device_id, datetime(2026, 7, 31, 17, 0, tzinfo=UTC), serial="WP079074")

        run_cycle()

        read_at, kwh = rows(destination, f"SELECT read_at, import_active_kwh FROM {LOAD_PROFILE_TABLE.name}")[0]
        assert read_at == datetime(2026, 8, 24, 20, 15)
        assert kwh == 0.0085671  # value unchanged, only the clock moved

        bill_date = rows(destination, f"SELECT bill_date FROM {BILLING_TABLE.name}")[0][0]
        # A period our UI calls July closes on 1 August there — the meter's own
        # local cut time, and correct (ADR 0021's Consequences).
        assert bill_date == datetime(2026, 8, 1, 0, 0)

    def test_the_shift_is_the_constant_and_not_a_coincidence(self, configured, destination, licensed) -> None:  # noqa: ANN001
        """Pinned against the constant so a mutation to it moves this test —
        which is what makes "drop or double the offset" a real mutation."""
        device_id = add_device("Main", "WP079074")
        # Inside the Mirror Window on purpose — a fixed old date would be
        # purged by the same cycle and this would assert on an empty table.
        source_read_at = (datetime.now(UTC) - timedelta(days=2)).replace(microsecond=0)
        add_intervals(device_id, 1, [source_read_at])

        run_cycle()

        stored = rows(destination, f"SELECT read_at FROM {LOAD_PROFILE_TABLE.name}")[0][0]
        assert stored - source_read_at.replace(tzinfo=None) == timedelta(hours=METER_LOCAL_UTC_OFFSET_HOURS)

    def test_a_destination_behind_by_days_receives_exactly_the_missing_rows(
        self, configured, destination, licensed
    ) -> None:  # noqa: ANN001
        """A simulated multi-day outage. Only what is newer than the
        destination's own watermark (rewound) is sent."""
        device_id = add_device("Main", "WP079074")
        base = datetime(2026, 8, 20, 0, 0, tzinfo=UTC)
        first_batch = [base + timedelta(hours=i) for i in range(24)]
        add_intervals(device_id, 1, first_batch)

        run_cycle()
        assert count(destination, LOAD_PROFILE_TABLE.name) == 24

        # Three days pass with the destination unreachable; we keep reading.
        later = [base + timedelta(days=3, hours=i) for i in range(24)]
        add_intervals(device_id, 1, later)

        run_cycle()

        assert count(destination, LOAD_PROFILE_TABLE.name) == 48
        newest = rows(destination, f"SELECT MAX(read_at) FROM {LOAD_PROFILE_TABLE.name}")[0][0]
        assert newest == datetime(2026, 8, 23, 23, 0) + timedelta(hours=METER_LOCAL_UTC_OFFSET_HOURS)

    def test_the_watermark_is_per_serial_and_logger_not_per_meter(self, configured, destination, licensed) -> None:  # noqa: ANN001
        """The failure ADR 0008 had to fix on our own side at issue #24: a
        `MIN`/`MAX` across loggers stalls the lagging one behind the other."""
        device_id = add_device("Main", "WP079074")
        base = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
        add_intervals(device_id, 1, [base + timedelta(hours=i) for i in range(10)])
        add_intervals(device_id, 2, [base + timedelta(minutes=5 * i) for i in range(3)])

        run_cycle()

        per_logger = dict(
            rows(destination, f"SELECT logger_id, COUNT(*) FROM {LOAD_PROFILE_TABLE.name} GROUP BY logger_id")
        )
        assert per_logger == {1: 10, 2: 3}

        # Logger 2 lags far behind logger 1. A watermark taken across both
        # would mask logger 2's new rows entirely.
        add_intervals(device_id, 2, [base + timedelta(minutes=5 * i) for i in range(3, 8)])

        run_cycle()

        per_logger = dict(
            rows(destination, f"SELECT logger_id, COUNT(*) FROM {LOAD_PROFILE_TABLE.name} GROUP BY logger_id")
        )
        assert per_logger == {1: 10, 2: 8}, "the lagging logger was masked by the other's watermark"

    def test_the_watermark_is_rewound_before_sending(self, configured, destination, licensed) -> None:  # noqa: ANN001
        """The rewind is what turns an off-by-offset into bounded waste rather
        than a silent gap. Proven by observing that a row **inside** the rewind
        window is re-sent — its `source` is re-asserted by the ODKU clause —
        while the row count does not move."""
        device_id = add_device("Main", "WP079074")
        newest = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
        inside = newest - timedelta(seconds=DBDEST_WATERMARK_REWIND_SEC // 2)
        add_intervals(device_id, 1, [inside, newest])

        run_cycle()
        with destination.begin() as connection:
            connection.execute(sa.text(f"UPDATE {LOAD_PROFILE_TABLE.name} SET source = 'tampered'"))

        run_cycle()

        restored = {r[0] for r in rows(destination, f"SELECT source FROM {LOAD_PROFILE_TABLE.name}")}
        assert restored == {SOURCE_DLMS}, "no row inside the rewind window was re-sent"
        assert count(destination, LOAD_PROFILE_TABLE.name) == 2

    def test_rows_with_no_meter_serial_anywhere_are_skipped_and_counted(
        self, configured, destination, licensed
    ) -> None:  # noqa: ANN001
        good = add_device("Main", "WP079074")
        anonymous = add_device("Unidentified", None)
        add_intervals(good, 1, [datetime(2026, 8, 24, 0, 0, tzinfo=UTC)])
        add_intervals(anonymous, 1, [datetime(2026, 8, 24, 0, 0, tzinfo=UTC)] * 1)
        add_billing(anonymous, datetime(2026, 7, 31, 17, 0, tzinfo=UTC), serial=None)

        run_cycle()

        assert count(destination, LOAD_PROFILE_TABLE.name) == 1
        assert count(destination, BILLING_TABLE.name) == 0
        status = last_sync()
        assert status is not None
        assert status.skipped_rows == 2

    def test_billing_falls_back_to_the_devices_meter_serial(self, configured, destination, licensed) -> None:  # noqa: ANN001
        """ADR 0018: both driver read paths store `meter_serial=None` when the
        serial register read fails **after** the buffer was read. Without the
        fallback a closed period written during one such read would never
        reach the destination at all."""
        device_id = add_device("Main", "WP079074")
        add_billing(device_id, datetime(2026, 7, 31, 17, 0, tzinfo=UTC), serial=None)

        run_cycle()

        stored = rows(destination, f"SELECT meter_serial FROM {BILLING_TABLE.name}")
        assert stored == [("WP079074",)]

    def test_the_open_closed_split_survives_the_whole_table_replace(self, configured, destination, licensed) -> None:  # noqa: ANN001
        device_id = add_device("Main", "WP079074")
        add_billing(device_id, datetime(2026, 6, 30, 17, 0, tzinfo=UTC), serial="WP079074")
        add_billing(device_id, datetime(2026, 7, 31, 17, 0, tzinfo=UTC), serial="WP079074", status="open")

        run_cycle()
        run_cycle()

        split = dict(
            rows(
                destination,
                f"SELECT COALESCE(record_status, 'closed'), COUNT(*) FROM {BILLING_TABLE.name} "
                "GROUP BY COALESCE(record_status, 'closed')",
            )
        )
        assert split == {"closed": 1, "open": 1}


class TestBillingIsReplacedAtomically:
    def test_a_failure_mid_replace_leaves_the_previous_contents_intact(
        self, configured, destination, licensed, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # noqa: ANN001
        """`DELETE` inside one transaction, **never `TRUNCATE`** — `TRUNCATE`
        is DDL, cannot be rolled back, and would show a concurrent reader an
        empty table mid-cycle. Rolled back against the real server, not
        asserted."""
        device_id = add_device("Main", "WP079074")
        add_billing(device_id, datetime(2026, 6, 30, 17, 0, tzinfo=UTC), serial="WP079074")
        run_cycle()
        assert count(destination, BILLING_TABLE.name) == 1

        add_billing(device_id, datetime(2026, 7, 31, 17, 0, tzinfo=UTC), serial="WP079074")
        real_insert = sa.insert

        def explode_on_the_billing_insert(table, *args, **kwargs):  # noqa: ANN001, ANN202
            if table is BILLING_TABLE:
                raise RuntimeError("the connection dropped mid-replace")
            return real_insert(table, *args, **kwargs)

        monkeypatch.setattr(sync.sa, "insert", explode_on_the_billing_insert)

        sync.database_destination_cycle()

        status = last_sync()
        assert status is not None
        assert status.error is not None
        assert count(destination, BILLING_TABLE.name) == 1, "the DELETE was not rolled back with the failed insert"
        assert rows(destination, f"SELECT bill_date FROM {BILLING_TABLE.name}") == [(datetime(2026, 7, 1, 0, 0),)]


# ─── The Mirror Window (ADR 0020) ─────────────────────────────────────────────


class TestThePurge:
    def test_rows_past_retention_are_deleted_from_the_customers_database(
        self, configured, destination, licensed
    ) -> None:  # noqa: ANN001
        device_id = add_device("Main", "WP079074")
        now = datetime.now(UTC).replace(microsecond=0)
        fresh = now - timedelta(days=1)
        stale = now - timedelta(days=RETENTION_DAYS + 5)
        add_intervals(device_id, 1, [fresh, stale])

        run_cycle()

        remaining = rows(destination, f"SELECT read_at FROM {LOAD_PROFILE_TABLE.name}")
        assert len(remaining) == 1
        # The survivor is the fresh row, in the destination's own clock.
        assert remaining[0][0] == (fresh + timedelta(hours=METER_LOCAL_UTC_OFFSET_HOURS)).replace(tzinfo=None)
        status = last_sync()
        assert status is not None
        assert status.purged_rows == 1

    def test_the_cutoff_is_local_so_a_row_in_the_seven_hour_seam_survives(
        self, configured, destination, licensed
    ) -> None:  # noqa: ANN001
        """ADR 0020's named silent failure. A row aged just past
        `RETENTION_DAYS` **in UTC terms** but still inside the window once the
        cutoff is expressed in the destination's own clock must survive; a UTC
        cutoff would delete it, and every one like it, on every cycle.
        """
        device_id = add_device("Main", "WP079074")
        now = datetime.now(UTC)
        # Stored local = utc + 7h. A UTC-computed cutoff sits 7h later in the
        # destination's clock than the correct one, so anything in this seam is
        # exactly what a UTC cutoff wrongly deletes.
        in_the_seam = now - timedelta(days=RETENTION_DAYS) + timedelta(hours=3)
        add_intervals(device_id, 1, [in_the_seam])

        run_cycle()

        assert count(destination, LOAD_PROFILE_TABLE.name) == 1, (
            "the purge cutoff was computed in UTC — it deleted seven hours too much (ADR 0020)"
        )

    def test_billing_is_never_purged(self, configured, destination, licensed) -> None:  # noqa: ANN001
        """ADR 0009/0020: a closed period is never rewritten or removed, and
        the destination copy is kept current by the replace rather than by a
        window. On this machine the oldest load-profile row is 90 days old and
        the oldest billing row is 357."""
        device_id = add_device("Main", "WP079074")
        ancient = datetime.now(UTC) - timedelta(days=357)
        add_billing(device_id, ancient, serial="WP079074")

        run_cycle()
        run_cycle()

        assert count(destination, BILLING_TABLE.name) == 1, "a billing row older than RETENTION_DAYS was purged"

    def test_the_purge_runs_even_when_there_is_nothing_to_append(self, configured, destination, licensed) -> None:  # noqa: ANN001
        device_id = add_device("Main", "WP079074")
        add_intervals(device_id, 1, [datetime.now(UTC) - timedelta(days=1)])
        run_cycle()

        # A row the destination holds and we no longer do — exactly the state
        # a destination that ran ahead of our own daily purge would be in.
        with destination.begin() as connection:
            connection.execute(
                sa.text(
                    f"INSERT INTO {LOAD_PROFILE_TABLE.name} "
                    "(meter_serial, read_at, source, logger_id, interval_sec, created_at) "
                    "VALUES (:s, :r, :src, 1, 900, :c)"
                ),
                {
                    "s": "WP079074",
                    "r": datetime(2020, 1, 1, 0, 0),
                    "src": SOURCE_DLMS,
                    "c": datetime(2020, 1, 1, 0, 0),
                },
            )
        assert count(destination, LOAD_PROFILE_TABLE.name) == 2

        run_cycle()

        assert count(destination, LOAD_PROFILE_TABLE.name) == 1


# ─── The budget ───────────────────────────────────────────────────────────────


class TestTheBudget:
    def test_a_zero_budget_stops_the_cycle_cleanly_and_records_it(
        self, configured, destination, licensed, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # noqa: ANN001
        """A cycle out of budget stops cleanly and resumes next tick — which
        works because the watermark lives in the destination rather than in a
        job record (ADR 0008), so a partial cycle is not a lost cycle."""
        device_id = add_device("Main", "WP079074")
        add_intervals(device_id, 1, [datetime(2026, 8, 24, 0, 0, tzinfo=UTC) + timedelta(hours=i) for i in range(5)])
        monkeypatch.setattr(sync, "DBDEST_SYNC_BUDGET_SEC", 0.0)

        sync.database_destination_cycle()

        status = last_sync()
        assert status is not None
        assert status.error is None, "running out of budget is not an error"
        assert status.budget_exhausted is True
        assert count(destination, LOAD_PROFILE_TABLE.name) == 0

    def test_the_next_cycle_resumes_correctly_after_an_exhausted_one(
        self, configured, destination, licensed, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # noqa: ANN001
        device_id = add_device("Main", "WP079074")
        add_intervals(device_id, 1, [datetime(2026, 8, 24, 0, 0, tzinfo=UTC) + timedelta(hours=i) for i in range(5)])
        monkeypatch.setattr(sync, "DBDEST_SYNC_BUDGET_SEC", 0.0)
        sync.database_destination_cycle()
        monkeypatch.undo()

        run_cycle()

        assert count(destination, LOAD_PROFILE_TABLE.name) == 5

    def test_the_purge_still_runs_when_the_append_spent_the_whole_budget(
        self, configured, destination, licensed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ADR 0020: the **Mirror Window must not drift**. A first-run backfill
        takes several cycles, and a purge that yielded to it every time would
        leave rows past retention sitting in the customer's database for as
        long as the backfill lasted.
        """
        device_id = add_device("Main", "WP079074")
        add_intervals(device_id, 1, [datetime.now(UTC) - timedelta(days=1)])
        run_cycle()
        with destination.begin() as connection:
            connection.execute(
                sa.text(
                    f"INSERT INTO {LOAD_PROFILE_TABLE.name} "
                    "(meter_serial, read_at, source, logger_id, interval_sec, created_at) "
                    "VALUES ('WP079074', :r, :src, 9, 900, :r)"
                ),
                {"r": datetime(2019, 1, 1, 0, 0), "src": SOURCE_DLMS},
            )
        assert count(destination, LOAD_PROFILE_TABLE.name) == 2

        # No budget left at all — the append does nothing this cycle.
        monkeypatch.setattr(sync, "DBDEST_SYNC_BUDGET_SEC", 0.0)
        sync.database_destination_cycle()

        status = last_sync()
        assert status is not None
        assert status.budget_exhausted is True
        assert status.purged_rows == 1, "the purge was starved by an exhausted budget — the window drifted"
        assert count(destination, LOAD_PROFILE_TABLE.name) == 1

    def test_the_budget_is_never_checked_inside_the_billing_transaction(
        self, configured, destination, licensed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A budget check mid-replace would leave the destination holding a
        partial set of periods, which is exactly what the single transaction
        exists to prevent. Proven by making the budget expire *during* the
        replace: the replace must still finish whole.
        """
        device_id = add_device("Main", "WP079074")
        for day in range(4):
            add_billing(device_id, datetime(2026, 4 + day, 28, 17, 0, tzinfo=UTC), serial="WP079074")

        real_delete = sync.sa.delete

        def burn_the_budget(table, *args, **kwargs):  # noqa: ANN001, ANN202
            # The DELETE is the first statement inside the transaction; from
            # here on the clock is already past the deadline.
            monkeypatch.setattr(sync.time, "monotonic", lambda: 1e12)
            return real_delete(table, *args, **kwargs)

        monkeypatch.setattr(sync.sa, "delete", burn_the_budget)

        sync.database_destination_cycle()

        assert count(destination, BILLING_TABLE.name) == 4, "the billing replace was cut short by a budget check"


# ─── Scale ────────────────────────────────────────────────────────────────────


class TestItNeverReadsTheWholeTable:
    def test_the_source_query_is_bounded_by_the_chunk_size(
        self, configured, destination, licensed, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # noqa: ANN001
        """The design probe read all 61,023 source rows on every run and
        discarded most of them in a Python loop. No code path here may."""
        device_id = add_device("Main", "WP079074")
        base = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
        add_intervals(device_id, 1, [base + timedelta(minutes=i) for i in range(30)])

        real_chunk = sync._source_chunk
        seen: list[int] = []

        def counting_chunk(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            result = real_chunk(*args, **kwargs)
            seen.append(len(result))
            return result

        chunk_size = 10
        monkeypatch.setattr(sync, "_source_chunk", counting_chunk)
        monkeypatch.setattr(sync, "DBDEST_ROW_CHUNK", chunk_size)

        run_cycle()

        # Asserted against the **patched** size, not the imported constant.
        # `DBDEST_ROW_CHUNK` is 5000, so `30 <= DBDEST_ROW_CHUNK` would hold
        # with the LIMIT removed altogether — a green that proves nothing.
        # Caught by the mutation sweep, which is what it is for.
        assert seen, "the source query was never reached"
        assert max(seen) <= chunk_size, f"one query returned {max(seen)} rows with a chunk size of {chunk_size}"
        assert len(seen) >= 3, "thirty rows came back in fewer pages than a bounded query could return them in"
        assert count(destination, LOAD_PROFILE_TABLE.name) == 30

    def test_a_steady_state_cycle_re_reads_only_the_rewind_window(self, configured, destination, licensed) -> None:  # noqa: ANN001
        """The second cycle re-reads only what is inside the rewind window,
        because the watermark is applied **in SQL** — not the whole table.

        Not zero, deliberately: the rewind is a safety margin ADR 0021 buys on
        purpose, so the rows inside it *are* re-sent and collapse onto
        themselves. What must not happen is re-reading all fifty.
        """
        device_id = add_device("Main", "WP079074")
        old = datetime.now(UTC) - timedelta(days=10)
        add_intervals(device_id, 1, [old + timedelta(hours=i) for i in range(50)])
        run_cycle()

        started = time.monotonic()
        run_cycle()
        second = time.monotonic() - started

        status = last_sync()
        assert status is not None
        # One hour of rewind over an hourly logger reaches at most two rows.
        assert status.load_profile_rows <= 2, f"a steady-state cycle re-sent {status.load_profile_rows} of 50 rows"
        assert count(destination, LOAD_PROFILE_TABLE.name) == 50
        assert second < 10.0
