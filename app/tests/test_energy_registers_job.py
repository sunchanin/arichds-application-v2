"""``read_and_store_energy_registers()`` — the Energy Registers read job
(M7-1, issue #28).

Everything runs against ``FakeSmw110Driver``; nothing here touches a meter.
Shaped on ``test_billing_job.py`` for the fixture pattern, but the write rule
is simpler than billing's: one snapshot, upserted on ``(device_id, read_at)``
where ``read_at`` is the writer's own clock, truncated to whole seconds
(decision 10) — never a period, never a closed/open split.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fakes import FakeMeterState
from sqlalchemy import select

from arichds.acquisition.drivers.base import EnergyRegisterReading
from arichds.acquisition.energy_registers import read_and_store_energy_registers
from arichds.config import Settings
from arichds.constants import SOURCE_DLMS
from arichds.db.models import Device
from arichds.db.models import EnergyRegisterReading as EnergyRegisterReadingRow
from arichds.db.session import session_scope

pytestmark = pytest.mark.usefixtures("fake_meter")

NOW = datetime(2026, 8, 11, 4, 0, 0, tzinfo=UTC)


def make_device(model: str = "smw110") -> int:
    with session_scope() as session:
        device = Device(
            name="Main Incomer",
            brand="mitsu",
            model=model,
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="hunter2",
        )
        session.add(device)
        session.flush()
        return device.id


def make_unsupported_device() -> int:
    with session_scope() as session:
        device = Device(
            name="No Energy Registers",
            brand="cewe",
            model="prometer100",
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="hunter2",
        )
        session.add(device)
        session.flush()
        return device.id


@pytest.fixture
def device_id(migrated_db: Settings) -> int:
    return make_device()


def stored_rows(device_id: int) -> list[EnergyRegisterReadingRow]:
    with session_scope() as session:
        return list(
            session.scalars(select(EnergyRegisterReadingRow).where(EnergyRegisterReadingRow.device_id == device_id))
        )


SNAPSHOT = EnergyRegisterReading(
    source=SOURCE_DLMS,
    meter_serial="1232002893",
    import_active_kwh_total=1066.62,
    export_active_kwh_total=0.0,
)


class TestUnsupportedDriver:
    def test_a_model_with_no_energy_registers_is_reported_unsupported(self, migrated_db: Settings) -> None:
        device_id = make_unsupported_device()

        result = read_and_store_energy_registers(device_id, now=NOW)

        assert result.supported is False
        assert result.row_id is None
        assert stored_rows(device_id) == []


class TestStoringASnapshot:
    def test_a_supported_read_stores_one_row(self, device_id: int, fake_meter: FakeMeterState) -> None:
        fake_meter.energy_registers_reading = SNAPSHOT

        result = read_and_store_energy_registers(device_id, now=NOW)

        assert result.supported is True
        assert result.error is None
        assert result.row_id is not None
        rows = stored_rows(device_id)
        assert len(rows) == 1
        assert rows[0].import_active_kwh_total == pytest.approx(1066.62)
        assert rows[0].meter_serial == "1232002893"


class TestSameSecondUpsert:
    def test_two_reads_within_one_second_upsert_to_one_row_with_the_second_values(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """The upsert criterion (decision 10) — must fail if the unique
        constraint or the microsecond truncation is removed."""
        first = EnergyRegisterReading(source=SOURCE_DLMS, meter_serial="SN-1", import_active_kwh_total=100.0)
        second = EnergyRegisterReading(source=SOURCE_DLMS, meter_serial="SN-1", import_active_kwh_total=200.0)

        now_a = datetime(2026, 8, 11, 4, 0, 0, 100000, tzinfo=UTC)
        now_b = datetime(2026, 8, 11, 4, 0, 0, 900000, tzinfo=UTC)  # same second, different microsecond

        fake_meter.energy_registers_reading = first
        read_and_store_energy_registers(device_id, now=now_a)
        fake_meter.energy_registers_reading = second
        read_and_store_energy_registers(device_id, now=now_b)

        rows = stored_rows(device_id)
        assert len(rows) == 1
        assert rows[0].import_active_kwh_total == pytest.approx(200.0)


class TestMeterFailure:
    def test_a_connect_failure_is_reported_as_an_error_sentence_not_an_exception(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.connect_error = ConnectionError("boom")

        result = read_and_store_energy_registers(device_id, now=NOW)

        assert result.supported is True
        assert result.row_id is None
        assert result.error is not None
        assert stored_rows(device_id) == []
