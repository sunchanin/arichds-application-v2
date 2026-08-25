"""The Database Destination's schema, derived from the ORM (issue #46).

Pure — nothing here connects to anything. The half that needs a real MariaDB
(``reconcile``, ``SHOW CREATE TABLE``, ``ALTER TABLE … ADD COLUMN``) lives in
``test_dataout_mysql.py``.

**A file the delegation prompt did not name.** It predicted
``test_dataout_sync.py`` for every pure function, but the schema is derived at
import time from the ORM and has nothing to do with the cycle's window
arithmetic, so it gets its own file rather than a class inside that one.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from arichds.dataout.schema import BILLING_TABLE, LOAD_PROFILE_TABLE
from arichds.db.models import BillingReading, LoadProfileReading


class TestDerivedFromTheOrm:
    """Derived at import time, never hand-listed.

    ``billing_readings`` went from 40 columns to 60 at M4c (issue #24); a
    hand-written list would have gone stale exactly there, and the first
    ``INSERT`` after that upgrade would have failed on the customer's machine
    with an unknown column.
    """

    def test_load_profile_carries_every_source_column_but_the_two_ids(self) -> None:
        source = {c.name for c in LoadProfileReading.__table__.columns} - {"id", "device_id"}

        assert {c.name for c in LOAD_PROFILE_TABLE.columns} == source | {"meter_serial"}

    def test_billing_carries_every_source_column_but_the_two_ids(self) -> None:
        source = {c.name for c in BillingReading.__table__.columns} - {"id", "device_id"}

        assert {c.name for c in BILLING_TABLE.columns} == source

    def test_billing_really_does_have_the_sixty_seven_columns_m4c_left(self) -> None:
        """69 model columns minus `id` and `device_id`. A number, so a silent
        loss of a column shows up as a number rather than as a set."""
        assert len(BillingReading.__table__.columns) == 69
        assert len(BILLING_TABLE.columns) == 67

    def test_device_id_appears_nowhere(self) -> None:
        """`devices.id` is a SQLite rowid alias and is **reused** after the
        highest row is deleted, so the destination would never learn of the
        delete and two meters' data would merge under one number (SPEC §3.10).
        """
        for table in (LOAD_PROFILE_TABLE, BILLING_TABLE):
            assert "device_id" not in table.columns
            assert "id" not in table.columns
            ddl = str(sa.schema.CreateTable(table).compile(dialect=mysql.dialect()))
            assert "device_id" not in ddl

    def test_meter_serial_leads_the_load_profile_table_and_is_not_nullable(self) -> None:
        column = LOAD_PROFILE_TABLE.columns[0]

        assert column.name == "meter_serial"
        assert column.nullable is False
        assert column.type.length == 64

    def test_billing_meter_serial_is_not_nullable_here_even_though_it_is_in_the_orm(self) -> None:
        """Rows are keyed on Meter Serial (SPEC §3.10). The ORM column is
        nullable because a serial-register read can fail after the buffer was
        read (ADR 0018); the sync falls back to `devices.meter_serial` and
        skips a row that has neither, so a NULL can never be written — and
        declaring NOT NULL is what makes that structural instead of a promise.
        """
        assert BillingReading.__table__.columns["meter_serial"].nullable is True
        assert BILLING_TABLE.columns["meter_serial"].nullable is False


class TestTypes:
    def test_every_string_column_is_at_least_as_wide_as_its_sqlite_counterpart(self) -> None:
        """What makes truncation structurally impossible rather than merely
        detected by `STRICT_TRANS_TABLES` (issue #46, decision 7b)."""
        for model, table in ((LoadProfileReading, LOAD_PROFILE_TABLE), (BillingReading, BILLING_TABLE)):
            for source in model.__table__.columns:
                if source.name in {"id", "device_id"} or not isinstance(source.type, sa.String):
                    continue
                destination = table.columns[source.name]
                assert destination.type.length >= source.type.length, source.name

    def test_datetimes_are_datetime_columns_and_never_timestamp(self) -> None:
        """ADR 0021: `TIMESTAMP` converts using the session's `time_zone`,
        which would put correctness in the customer's `my.ini`."""
        ddl = str(sa.schema.CreateTable(BILLING_TABLE).compile(dialect=mysql.dialect()))

        assert "TIMESTAMP" not in ddl.upper()
        assert ddl.upper().count(" DATETIME") == 14  # bill_date, read_at, created_at, updated_at + ten Demand Times

    def test_floats_are_double_precision(self) -> None:
        ddl = str(sa.schema.CreateTable(BILLING_TABLE).compile(dialect=mysql.dialect()))

        assert "DOUBLE" in ddl.upper()
        assert "FLOAT" not in ddl.upper()

    def test_both_tables_declare_innodb_and_utf8mb4_rather_than_inheriting_them(self) -> None:
        """The reference `my.ini` happens to set utf8mb4 server-wide — another
        customer's does not, and stock MariaDB defaults to latin1."""
        for table in (LOAD_PROFILE_TABLE, BILLING_TABLE):
            ddl = str(sa.schema.CreateTable(table).compile(dialect=mysql.dialect()))
            assert "ENGINE=InnoDB" in ddl
            assert "CHARSET=utf8mb4" in ddl
            assert "utf8mb4_general_ci" in ddl


class TestKeys:
    def test_load_profile_has_the_unique_key_odku_needs(self) -> None:
        """`ON DUPLICATE KEY UPDATE` collapses a re-sent row onto the existing
        one only because this key exists (ADR 0021)."""
        unique = [c for c in LOAD_PROFILE_TABLE.constraints if isinstance(c, sa.UniqueConstraint)]

        assert len(unique) == 1
        assert [c.name for c in unique[0].columns] == ["meter_serial", "logger_id", "read_at"]

    def test_billing_has_no_unique_key_at_all(self) -> None:
        """ADR 0009's two **partial** unique indexes cannot be expressed in
        MySQL or MariaDB — the finding ADR 0016 rests on. The whole-table
        replace is what keeps the destination correct instead."""
        assert [c for c in BILLING_TABLE.constraints if isinstance(c, sa.UniqueConstraint)] == []
        assert all(not index.unique for index in BILLING_TABLE.indexes)

    def test_neither_table_has_a_surrogate_primary_key(self) -> None:
        assert list(LOAD_PROFILE_TABLE.primary_key.columns) == []
        assert list(BILLING_TABLE.primary_key.columns) == []

    def test_the_read_side_indexes_exist(self) -> None:
        assert {tuple(i.columns.keys()) for i in LOAD_PROFILE_TABLE.indexes} == {("meter_serial", "read_at")}
        assert {tuple(i.columns.keys()) for i in BILLING_TABLE.indexes} == {("meter_serial", "bill_date")}
