"""The billing driver capability pair — ``supports_billing`` / ``read_billing``
(M6a, issue #21).

Mirrors ``TestTheCapabilityContract`` in ``test_smw110_load_profile.py``: a
non-abstract ``supports_billing()`` answering ``False`` by default, paired with
a non-abstract ``read_billing()`` that *raises* rather than being absent — so
``hasattr`` is never the question a caller has to ask (CLAUDE.md: no model
branch in generic code).
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

import pytest

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.base import BillingReading
from arichds.acquisition.drivers.prometer100 import Prometer100Driver


class TestTheCapabilityContract:
    def test_the_base_class_answers_no(self) -> None:
        driver = Prometer100Driver(ConnectionParams.net("198.51.100.9", 4059), password="secret")
        assert driver.supports_billing() is False

    def test_calling_the_base_read_raises_rather_than_being_absent(self) -> None:
        driver = Prometer100Driver(ConnectionParams.net("198.51.100.9", 4059), password="secret")
        with pytest.raises(NotImplementedError):
            driver.read_billing()


class TestBillingReadingShape:
    """The dataclass fields are spelled out, not generated — a generated field
    set would defeat type checking."""

    def test_as_columns_returns_only_the_forty_measurement_fields(self) -> None:
        reading = BillingReading(
            bill_date=datetime(2026, 8, 7, tzinfo=UTC),
            source="dlms",
            is_open=True,
            import_active_kwh_total=200464.501,
        )

        columns = reading.as_columns()

        assert "bill_date" not in columns
        assert "source" not in columns
        assert "is_open" not in columns
        assert "meter_serial" not in columns
        assert columns["import_active_kwh_total"] == pytest.approx(200464.501)
        assert len(columns) == 40

    def test_the_forty_measurement_fields_default_to_none(self) -> None:
        reading = BillingReading(bill_date=datetime(2026, 8, 7, tzinfo=UTC), source="dlms", is_open=False)

        assert all(value is None for value in reading.as_columns().values())

    def test_the_field_set_is_exactly_forty_four(self) -> None:
        """4 identity fields + 40 measurement fields, no more, no fewer."""
        assert len({f.name for f in fields(BillingReading)}) == 44
