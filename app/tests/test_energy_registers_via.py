"""``read_energy_registers_via()`` (M7-1, issue #28, review finding 3) — the
shared OBIS→field mapping every opting-in driver's ``read_energy_registers()``
calls through.

**Nothing else exercises this mapping.** ``FakeSmw110Driver.read_energy_registers()``
overrides the method wholesale and replays a prebuilt :class:`EnergyRegisterReading`
(``tests/fakes.py``), so every test that goes through the fake — the job tests,
the API tests — proves the *job*/*router* wiring but never runs the OBIS→field
loop, the ``/ WH_TO_KWH_DIVISOR`` division, the per-address failure isolation,
or the meter-serial fallback in ``_dlms.py`` itself. This module is the one
place that loop actually runs.

A stub exposing just ``_reader``/``_client``/``read_register()``/``read_meter_serial()``
stands in for a real ``DlmsDriver`` — the function only ever touches those four
things (plus ``.source``/``.model_name``), so nothing else needs faking.
"""

from __future__ import annotations

from typing import Any

from arichds.acquisition.drivers._dlms import read_energy_registers_via
from arichds.constants import SOURCE_DLMS, WH_TO_KWH_DIVISOR

#: One raw value per OBIS, each a distinct multiple of ``WH_TO_KWH_DIVISOR`` so
#: a swapped quantity (``C=1``/``C=2``), a swapped tariff (``E=0``/``E=1``), or a
#: missing division all produce a value nothing else in this dict could produce.
_RAW_BY_OBIS: dict[str, float] = {
    f"1.0.{c}.8.{e}.255": float((c * 10 + e) * WH_TO_KWH_DIVISOR) for c in (1, 2, 3, 4) for e in (0, 1, 2, 3, 4)
}

#: The field each OBIS must land on, and the value it must carry — computed
#: independently of ``_dlms.py``'s own ``_ENERGY_REGISTER_PREFIX_BY_C`` /
#: ``_ENERGY_REGISTER_RATE_SUFFIX`` dicts, so this test cannot pass merely
#: because it shares a typo with the code it is checking.
_EXPECTED_FIELDS: dict[str, float] = {
    "import_active_kwh_total": 10.0,
    "import_active_kwh_rate_a": 11.0,
    "import_active_kwh_rate_b": 12.0,
    "import_active_kwh_rate_c": 13.0,
    "import_active_kwh_rate_d": 14.0,
    "export_active_kwh_total": 20.0,
    "export_active_kwh_rate_a": 21.0,
    "export_active_kwh_rate_b": 22.0,
    "export_active_kwh_rate_c": 23.0,
    "export_active_kwh_rate_d": 24.0,
    "import_reactive_kvarh_total": 30.0,
    "import_reactive_kvarh_rate_a": 31.0,
    "import_reactive_kvarh_rate_b": 32.0,
    "import_reactive_kvarh_rate_c": 33.0,
    "import_reactive_kvarh_rate_d": 34.0,
    "export_reactive_kvarh_total": 40.0,
    "export_reactive_kvarh_rate_a": 41.0,
    "export_reactive_kvarh_rate_b": 42.0,
    "export_reactive_kvarh_rate_c": 43.0,
    "export_reactive_kvarh_rate_d": 44.0,
}


class _StubDriver:
    """A bare stand-in for a connected ``DlmsDriver`` — only what
    :func:`read_energy_registers_via` actually touches."""

    source = SOURCE_DLMS
    model_name = "stub"

    def __init__(
        self, values: dict[str, float], *, fail_obis: str | None = None, serial: str | None = "SN-STUB"
    ) -> None:
        self._reader = object()  # non-None is all the function checks for
        self._client = object()
        self._values = values
        self._fail_obis = fail_obis
        self._serial = serial

    def read_register(self, obis: str, attr: int = 2) -> Any:
        if obis == self._fail_obis:
            raise TimeoutError("meter refused this address")
        return self._values[obis]

    def read_meter_serial(self) -> str | None:
        return self._serial


class TestEveryFieldLandsOnTheRightName:
    def test_all_twenty_fields_are_mapped_and_divided_by_1000(self) -> None:
        driver = _StubDriver(dict(_RAW_BY_OBIS))

        reading = read_energy_registers_via(driver)

        actual = reading.as_columns()
        assert actual == _EXPECTED_FIELDS
        assert reading.source == SOURCE_DLMS
        assert reading.meter_serial == "SN-STUB"


class TestOneFailedAddressDoesNotAbortTheOthers:
    def test_a_refused_address_leaves_only_its_own_field_none(self) -> None:
        failing_obis = "1.0.1.8.2.255"  # import_active_kwh_rate_b
        driver = _StubDriver(dict(_RAW_BY_OBIS), fail_obis=failing_obis)

        reading = read_energy_registers_via(driver)

        actual = reading.as_columns()
        expected = dict(_EXPECTED_FIELDS)
        expected["import_active_kwh_rate_b"] = None
        assert actual == expected


class TestDisconnectedDriver:
    def test_returns_an_all_none_reading_when_reader_is_absent(self) -> None:
        driver = _StubDriver(dict(_RAW_BY_OBIS))
        driver._reader = None

        reading = read_energy_registers_via(driver)

        assert all(value is None for value in reading.as_columns().values())
        assert reading.meter_serial is None
