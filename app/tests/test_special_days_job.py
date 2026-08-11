"""``read_special_days()`` — the Special Days read-through job (M7-1, issue
#28).

Everything runs against ``FakeSmw110Driver``; nothing here touches a meter.
Stores nothing — the point of this test module is to prove that, not to
check a table.
"""

from __future__ import annotations

import pytest
from fakes import FakeMeterState

from arichds.acquisition.drivers.base import SpecialDayEntry
from arichds.acquisition.special_days import read_special_days
from arichds.config import Settings
from arichds.db.models import Device
from arichds.db.session import session_scope

pytestmark = pytest.mark.usefixtures("fake_meter")


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
            name="No Special Days",
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


class TestUnsupportedDriver:
    def test_a_model_with_no_special_days_table_is_reported_unsupported(self, migrated_db: Settings) -> None:
        result = read_special_days(make_unsupported_device())

        assert result.supported is False
        assert result.entries == []


class TestReadThrough:
    def test_the_meters_entries_are_returned_and_nothing_is_stored(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        entries = [
            SpecialDayEntry(index=1, day_id=7, year=None, month=1, day=1),
            SpecialDayEntry(index=2, day_id=9, year=2026, month=3, day=3),
        ]
        fake_meter.special_days_entries = entries

        result = read_special_days(device_id)

        assert result.supported is True
        assert result.entries == entries

    def test_an_empty_table_is_a_valid_answer_not_a_failure(self, device_id: int, fake_meter: FakeMeterState) -> None:
        fake_meter.special_days_entries = []

        result = read_special_days(device_id)

        assert result.supported is True
        assert result.error is None
        assert result.entries == []


class TestMeterFailure:
    def test_a_connect_failure_is_reported_as_an_error_sentence_not_an_exception(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.connect_error = ConnectionError("boom")

        result = read_special_days(device_id)

        assert result.supported is True
        assert result.entries == []
        assert result.error is not None
