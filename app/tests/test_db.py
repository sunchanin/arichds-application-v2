"""Database layer — migrations, WAL, and the normalization contract.

Verifies step 2's exit condition: create a device and a reading against a real
SQLite file produced by ``alembic upgrade head``, not by ``create_all``. The
migration is what ships, so the migration is what gets tested.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from arichds.config import Settings
from arichds.constants import SOURCE_DLMS
from arichds.db.models import BillingReading, Device, LoadProfileReading
from arichds.db.session import get_engine, session_scope


def make_device(name: str = "Meter A", model: str = "prometer100") -> Device:
    """Build an unsaved device row."""
    return Device(
        name=name,
        brand="cewe",
        model=model,
        transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
        password="secret",
        enabled=True,
    )


class TestMigration:
    def test_upgrade_head_creates_the_m1_tables(self, migrated_db: Settings) -> None:
        tables = set(inspect(get_engine()).get_table_names())
        assert {"devices", "load_profile_readings"} <= tables

    def test_only_the_shipped_modules_tables_exist(self, migrated_db: Settings) -> None:
        """M1 landed two tables, M2-1 two more and M3-2 one; the other 8 arrive
        with their own modules.

        ``device_events`` is the only table M3 adds. There is deliberately no
        ``device_status`` and no ``device_heartbeats`` beside it (ADR 0004):
        status lives in columns on ``devices``, and a per-tick heartbeat row is
        exactly what v2 refused to carry over.
        """
        tables = set(inspect(get_engine()).get_table_names()) - {"alembic_version"}
        assert tables == {
            "devices",
            "load_profile_readings",
            "users",
            "user_tokens",
            "device_events",
            "billing_readings",
        }

    def test_wal_is_enabled(self, migrated_db: Settings) -> None:
        with get_engine().connect() as connection:
            mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        assert mode.lower() == "wal"

    def test_foreign_keys_are_enforced(self, migrated_db: Settings) -> None:
        with get_engine().connect() as connection:
            enabled = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        assert enabled == 1


class TestDeviceAndReading:
    def test_create_device_and_reading(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            device = make_device()
            session.add(device)
            session.flush()
            device_id = device.id

            session.add(
                LoadProfileReading(
                    device_id=device_id,
                    read_at=datetime.now(UTC),
                    source=SOURCE_DLMS,
                    logger_id=1,
                    interval_sec=900,
                    volt_l1=230.1,
                    volt_l2=229.8,
                    volt_l3=230.4,
                    current_l1=11.2,
                    current_l2=11.4,
                    current_l3=11.1,
                    freq=50.01,
                    import_active_kwh=1234.567,
                )
            )

        with session_scope() as session:
            reading = session.scalars(select(LoadProfileReading)).one()
            assert reading.device_id == device_id
            assert reading.volt_l1 == 230.1
            assert reading.import_active_kwh == 1234.567

    def test_read_at_round_trips_as_utc(self, migrated_db: Settings) -> None:
        """UTC always — the whole normalization contract rests on this."""
        moment = datetime(2026, 8, 4, 12, 30, 45, tzinfo=UTC)
        with session_scope() as session:
            device = make_device()
            session.add(device)
            session.flush()
            session.add(
                LoadProfileReading(
                    device_id=device.id,
                    read_at=moment,
                    source=SOURCE_DLMS,
                    logger_id=1,
                    interval_sec=900,
                )
            )

        with session_scope() as session:
            stored = session.scalars(select(LoadProfileReading)).one()
            # SQLite drops the tzinfo; the stored wall clock must still be UTC.
            assert stored.read_at.replace(tzinfo=UTC) == moment

    def test_device_names_are_unique(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            session.add(make_device("Duplicate"))

        try:
            with session_scope() as session:
                session.add(make_device("Duplicate"))
        except IntegrityError:
            pass
        else:
            raise AssertionError("expected a unique-constraint violation")

    def test_deleting_a_device_deletes_its_readings(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            device = make_device()
            session.add(device)
            session.flush()
            session.add(
                LoadProfileReading(
                    device_id=device.id,
                    read_at=datetime.now(UTC),
                    source=SOURCE_DLMS,
                    logger_id=1,
                    interval_sec=900,
                )
            )

        with session_scope() as session:
            session.delete(session.scalars(select(Device)).one())

        with session_scope() as session:
            assert session.scalars(select(LoadProfileReading)).all() == []

    def test_latest_reading_query_orders_by_read_at(self, migrated_db: Settings) -> None:
        now = datetime.now(UTC)
        with session_scope() as session:
            device = make_device()
            session.add(device)
            session.flush()
            for offset, volts in ((2, 220.0), (1, 225.0), (0, 230.0)):
                session.add(
                    LoadProfileReading(
                        device_id=device.id,
                        read_at=now - timedelta(minutes=offset),
                        source=SOURCE_DLMS,
                        logger_id=1,
                        interval_sec=900,
                        volt_l1=volts,
                    )
                )

        with session_scope() as session:
            latest = session.scalars(
                select(LoadProfileReading).order_by(LoadProfileReading.read_at.desc()).limit(1)
            ).first()
            assert latest is not None
            assert latest.volt_l1 == 230.0


class TestBillingReading:
    """M6a (issue #21) — the ORM shape and ADR 0009's two partial unique indexes."""

    def test_create_a_closed_period(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            device = make_device(model="smw110")
            session.add(device)
            session.flush()
            device_id = device.id

            session.add(
                BillingReading(
                    device_id=device_id,
                    bill_date=datetime(2026, 7, 1, tzinfo=UTC),
                    read_at=datetime(2026, 8, 7, 4, 37, 58, tzinfo=UTC),
                    record_status=None,
                    source=SOURCE_DLMS,
                    meter_serial="1232002893",
                    import_active_kwh_total=189917.399,
                )
            )

        with session_scope() as session:
            row = session.scalars(select(BillingReading)).one()
            assert row.device_id == device_id
            assert row.record_status is None
            assert row.import_active_kwh_total == pytest.approx(189917.399)
            # Untouched columns default to None — the fixed 40-column shape,
            # not a subset the driver happened to fill (SPEC §3.6).
            assert row.max_demand_export_reactive_kvar_rate_d is None

    def test_a_second_closed_row_with_the_same_bill_date_is_rejected(self, migrated_db: Settings) -> None:
        """The natural key — reading the same buffer twice must not duplicate a
        closed period (ADR 0009)."""
        with session_scope() as session:
            device = make_device(model="smw110")
            session.add(device)
            session.flush()
            device_id = device.id
            bill_date = datetime(2026, 7, 1, tzinfo=UTC)
            session.add(
                BillingReading(
                    device_id=device_id, bill_date=bill_date, read_at=bill_date, record_status=None, source=SOURCE_DLMS
                )
            )

        with pytest.raises(IntegrityError), session_scope() as session:
            session.add(
                BillingReading(
                    device_id=device_id,
                    bill_date=bill_date,
                    read_at=bill_date,
                    record_status=None,
                    source=SOURCE_DLMS,
                )
            )

    def test_a_second_open_row_for_one_device_is_rejected(self, migrated_db: Settings) -> None:
        """At most one Open Period slot per device — the invariant the whole
        module rests on (ADR 0009)."""
        with session_scope() as session:
            device = make_device(model="smw110")
            session.add(device)
            session.flush()
            device_id = device.id
            session.add(
                BillingReading(
                    device_id=device_id,
                    bill_date=datetime(2026, 8, 7, tzinfo=UTC),
                    read_at=datetime(2026, 8, 7, tzinfo=UTC),
                    record_status="open",
                    source=SOURCE_DLMS,
                )
            )

        with pytest.raises(IntegrityError), session_scope() as session:
            session.add(
                BillingReading(
                    device_id=device_id,
                    bill_date=datetime(2026, 8, 8, tzinfo=UTC),
                    read_at=datetime(2026, 8, 8, tzinfo=UTC),
                    record_status="open",
                    source=SOURCE_DLMS,
                )
            )

    def test_deleting_a_device_deletes_its_billing_rows(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            device = make_device(model="smw110")
            session.add(device)
            session.flush()
            session.add(
                BillingReading(
                    device_id=device.id,
                    bill_date=datetime(2026, 7, 1, tzinfo=UTC),
                    read_at=datetime(2026, 7, 1, tzinfo=UTC),
                    record_status=None,
                    source=SOURCE_DLMS,
                )
            )

        with session_scope() as session:
            session.delete(session.scalars(select(Device)).one())

        with session_scope() as session:
            assert session.scalars(select(BillingReading)).all() == []


class TestTransportEndpoint:
    def test_net_endpoint_is_host_port(self) -> None:
        assert make_device().transport_endpoint == "127.0.0.1:4059"

    def test_serial_endpoint_is_the_port_name(self) -> None:
        """The lock key for a serial line is the COM port — devices share it."""
        device = Device(
            name="Serial meter",
            brand="Mitsubishi",
            model="smw110",
            transport={"kind": "serial", "serial_port": "COM3"},
        )
        assert device.transport_endpoint == "COM3"
