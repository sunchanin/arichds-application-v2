"""``Saral305Driver.read_billing()`` — the measured NULL set (F10, D16, M4c
issue #24).

**This is a measured fact about the fleet, not a bug.** v1 recorded this
model at 19/25 ``BILLING_FIELDS`` populated: six fields the firmware simply
does not track. Source: v1 ``cewe-worker/src/drivers/saral305.py:63-67`` —
*"19/25 BILLING_FIELDS populate; the following 6 are NOT captured by this
fleet and remain None by design (hardware/firmware does not track them):
cumul_kw_demand_rate_a/b/c, kvar_demand_total, kvar_demand_time,
cumul_kvar_demand_total."* Corroborated by v1
``adr/0004-driver-abstraction-obis-map.md:232-239``.

Nothing in :class:`Saral305Driver` or :mod:`~arichds.acquisition.drivers._cewe`
special-cases these six columns — the shared billing read simply finds no
position for their OBIS codes in this model's live capture list and leaves
the field ``None``, exactly as it would for any absent column. This test
pins that outcome so a future reader does not "fix" it by inventing values
the meter never reports.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from gurux_dlms.enums import Unit
from gurux_dlms.objects import GXDLMSProfileGeneric

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.saral305 import Saral305Driver

CLOCK_OBIS = "0.0.1.0.0.255"
BILL_DATE_OBIS = "0.0.0.1.2.255"
RESET_REASON_OBIS = "0.0.0.1.12.255"

#: The v1-measured capture list on this fleet: bill date, reset reason, the
#: energy totals (import/export active/reactive, rate A only — the field
#: fleet has one active tariff), max demand import active (total + rate A
#: only — no rate B/C on this fleet either). The six fields F10 names have
#: NO capture column here — that absence is the whole point of this test.
_MEASURED_CAPTURE_LIST: list[tuple[str, int]] = [
    (CLOCK_OBIS, 2),
    (BILL_DATE_OBIS, 2),
    (RESET_REASON_OBIS, 2),
    ("1.0.1.8.0.255", 2),  # import_active_kwh_total
    ("1.0.1.8.1.255", 2),  # import_active_kwh_rate_a
    ("1.0.2.8.0.255", 2),  # export_active_kwh_total
    ("1.0.3.8.0.255", 2),  # import_reactive_kvarh_total
    ("1.0.4.8.0.255", 2),  # export_reactive_kvarh_total
    ("1.0.1.6.0.255", 2),  # max_demand_import_active_kw_total
    ("1.0.1.6.1.255", 2),  # max_demand_import_active_kw_rate_a
]

_ROW = [None, datetime(2026, 8, 7, 11, 0), 255, 100.0, 40.0, 50.0, 20.0, 10.0, 5.5, 5.0]

_SCALERS = {
    "1.0.1.8.0.255": (1.0, Unit.ACTIVE_ENERGY),
    "1.0.1.8.1.255": (1.0, Unit.ACTIVE_ENERGY),
    "1.0.2.8.0.255": (1.0, Unit.ACTIVE_ENERGY),
    "1.0.3.8.0.255": (1.0, Unit.REACTIVE_ENERGY),
    "1.0.4.8.0.255": (1.0, Unit.REACTIVE_ENERGY),
    "1.0.1.6.0.255": (1.0, Unit.ACTIVE_POWER),
    "1.0.1.6.1.255": (1.0, Unit.ACTIVE_POWER),
}


class FakeSaral305BillingReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def read(self, obj: Any, attr: int) -> Any:
        if isinstance(obj, GXDLMSProfileGeneric):
            self.calls.append(("__profile__", attr))
            if attr == 3:
                obj.captureObjects = [
                    (SimpleNamespace(logicalName=obis), SimpleNamespace(attributeIndex=a))
                    for obis, a in _MEASURED_CAPTURE_LIST
                ]
                return obj.captureObjects
            if attr == 7:
                return 1
            raise AssertionError(f"unexpected ProfileGeneric attr {attr}")

        obis = str(obj.logicalName)
        self.calls.append((obis, attr))
        if attr == 3:
            multiplier, unit = _SCALERS.get(obis, (1.0, Unit.NONE))
            obj.scaler = multiplier
            obj.unit = unit
            return None
        if attr == 2 and obis == Saral305Driver.METER_SERIAL_OBIS[0]:
            return "SN-SARAL-1"
        raise AssertionError(f"unexpected attr {attr} for {obis}")

    def readRowsByEntry(self, pg: Any, index: int, count: int) -> list[list[Any]]:  # noqa: N802
        self.calls.append(("__rows__", index))
        return [_ROW][index - 1 : index - 1 + count]


def _build_driver() -> Saral305Driver:
    driver = Saral305Driver(ConnectionParams.net("203.170.151.217", 4059), password="secret")
    driver._reader = FakeSaral305BillingReader()  # noqa: SLF001
    driver._client = SimpleNamespace(objects=[])  # noqa: SLF001
    return driver


class TestTheMeasuredNullSet:
    """F10 — six fields this fleet's firmware never populates."""

    def test_the_six_untracked_fields_are_none(self) -> None:
        driver = _build_driver()

        readings = driver.read_billing()

        assert len(readings) == 1
        row = readings[0]
        assert row.max_demand_import_active_kw_rate_b is None
        assert row.max_demand_import_active_kw_rate_c is None
        assert row.max_demand_import_reactive_kvar_total is None
        assert row.max_demand_import_reactive_time_total is None
        assert row.cumul_demand_import_reactive_kvar_total is None

    def test_the_populated_fields_are_not_none(self) -> None:
        """The pin above must not be vacuous — proves this fixture's capture
        list actually resolves values for the columns it does carry."""
        driver = _build_driver()

        readings = driver.read_billing()

        row = readings[0]
        assert row.import_active_kwh_total is not None
        assert row.import_active_kwh_rate_a is not None
        assert row.max_demand_import_active_kw_total is not None
        assert row.max_demand_import_active_kw_rate_a is not None
        assert row.is_open is True

    def test_bill_date_is_meter_local_minus_seven_hours(self) -> None:
        driver = _build_driver()

        readings = driver.read_billing()

        assert readings[0].bill_date == datetime(2026, 8, 7, 4, 0, tzinfo=UTC)
