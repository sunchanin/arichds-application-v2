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

from arichds.acquisition.drivers.base import BillingReading, MeterDriver


class _MinimalDriver(MeterDriver):
    """The bare minimum concrete subclass — implements only what
    :class:`MeterDriver` demands, nothing else. Used to test the *base
    class's own* defaults in isolation, so this contract cannot drift the
    way piggybacking on a real production driver just did (M4c, issue #24:
    ``Prometer100Driver`` used to be "the driver with no billing profile" —
    then it grew one)."""

    @property
    def model_name(self) -> str:
        return "minimal"

    @property
    def endpoint(self) -> str:
        return "198.51.100.9:4059"

    def get_obis_map(self) -> dict[str, tuple[str, int]]:
        return {}

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def read_meter_serial(self) -> str | None:
        return None


class TestTheCapabilityContract:
    def test_the_base_class_answers_no(self) -> None:
        driver = _MinimalDriver()
        assert driver.supports_billing() is False

    def test_calling_the_base_read_raises_rather_than_being_absent(self) -> None:
        driver = _MinimalDriver()
        with pytest.raises(NotImplementedError):
            driver.read_billing()


class TestTheBillingChangeCheckBaseContract:
    """D10/D11, issue #43 — the Billing Change Check's per-driver seam. Same
    pairing shape as :meth:`MeterDriver.load_profile_oldest_reading`: a
    non-abstract method that answers ``None`` ("cannot say") by default, so a
    driver with no scanned billing profile yet degrades to "never trigger",
    never a crash."""

    def test_the_base_default_cannot_answer(self) -> None:
        driver = _MinimalDriver()
        assert driver.billing_newest_closed_bill_date() is None

    def test_entry_ordering_defaults_to_newest_first(self) -> None:
        """Every billing implementation shipped today reads newest-first
        (finding 4) — the base default matches that, and a driver whose
        profile is actually oldest-first must override it explicitly."""
        driver = _MinimalDriver()
        assert driver.BILLING_NEWEST_ENTRY_FIRST is True


class TestBillingReadingShape:
    """The dataclass fields are spelled out, not generated — a generated field
    set would defeat type checking."""

    def test_as_columns_returns_only_the_sixty_measurement_fields(self) -> None:
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
        assert len(columns) == 60

    def test_the_sixty_measurement_fields_default_to_none(self) -> None:
        reading = BillingReading(bill_date=datetime(2026, 8, 7, tzinfo=UTC), source="dlms", is_open=False)

        assert all(value is None for value in reading.as_columns().values())

    def test_the_field_set_is_exactly_sixty_four(self) -> None:
        """4 identity fields + 60 measurement fields, no more, no fewer."""
        assert len({f.name for f in fields(BillingReading)}) == 64

    def test_the_twenty_new_columns_are_present(self) -> None:
        """D10 — Demand Time (x2 groups) + Cumulative Demand (x2 groups), each
        total + rate_a..d = 20 new columns on top of the existing forty."""
        reading = BillingReading(bill_date=datetime(2026, 8, 7, tzinfo=UTC), source="dlms", is_open=False)
        columns = reading.as_columns()

        for prefix in (
            "max_demand_import_active_time",
            "max_demand_import_reactive_time",
            "cumul_demand_import_active_kw",
            "cumul_demand_import_reactive_kvar",
        ):
            for suffix in ("total", "rate_a", "rate_b", "rate_c", "rate_d"):
                assert f"{prefix}_{suffix}" in columns

    def test_demand_time_fields_accept_a_datetime(self) -> None:
        """D11 — Demand Time is a timestamp, not a number."""
        moment = datetime(2026, 8, 7, 4, 37, 58, tzinfo=UTC)
        reading = BillingReading(
            bill_date=datetime(2026, 8, 7, tzinfo=UTC),
            source="dlms",
            is_open=False,
            max_demand_import_active_time_total=moment,
        )

        assert reading.as_columns()["max_demand_import_active_time_total"] == moment
