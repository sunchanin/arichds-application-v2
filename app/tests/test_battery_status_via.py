"""``read_battery_status_via()`` (M7-2, issue #29) — the shared CEWE battery
read every opting-in driver's ``read_battery_status()`` calls through.

**Nothing else exercises this read.** ``FakeSmw110Driver.read_battery_status()``
(``tests/fakes.py``) overrides the method wholesale and replays a prebuilt
string, so every test that goes through the fake — the job tests, the API
tests — proves the *job*/*router* wiring but never runs the actual
``(obis, attr)`` pair or the ``str(raw).strip()`` conversion. This module is
the one place that read actually runs.

A stub exposing just ``_reader``/``_client``/``read_register()`` stands in for
a real ``DlmsDriver`` — the function only ever touches those three things, so
nothing else needs faking (mirrors ``test_energy_registers_via.py``'s
``_StubDriver``).
"""

from __future__ import annotations

from typing import Any

import pytest

from arichds.acquisition.drivers._dlms import CEWE_BATTERY_STATUS_OBIS, read_battery_status_via


class _StubDriver:
    """A bare stand-in for a connected ``DlmsDriver`` — only what
    :func:`read_battery_status_via` actually touches."""

    def __init__(self, value: Any, *, raise_on_read: Exception | None = None) -> None:
        self._reader = object()  # non-None is all the function checks for
        self._client = object()
        self._value = value
        self._raise_on_read = raise_on_read
        self.calls: list[tuple[str, int]] = []

    def read_register(self, obis: str, attr: int = 2) -> Any:
        self.calls.append((obis, attr))
        if self._raise_on_read is not None:
            raise self._raise_on_read
        return self._value


class TestTheExactRegisterIsRead:
    def test_reads_the_pinned_obis_and_attribute(self) -> None:
        driver = _StubDriver(1234)

        read_battery_status_via(driver)

        assert driver.calls == [(CEWE_BATTERY_STATUS_OBIS, 2)]

    def test_the_obis_constant_is_the_v1_pinned_value(self) -> None:
        assert CEWE_BATTERY_STATUS_OBIS == "0.0.96.6.1.255"


class TestValueConversion:
    def test_an_int_value_becomes_its_decimal_string(self) -> None:
        driver = _StubDriver(1234)

        result = read_battery_status_via(driver)

        assert result == "1234"

    def test_none_stays_none(self) -> None:
        driver = _StubDriver(None)

        result = read_battery_status_via(driver)

        assert result is None

    def test_a_string_value_is_stripped(self) -> None:
        driver = _StubDriver("  OK  ")

        result = read_battery_status_via(driver)

        assert result == "OK"


class TestDisconnectedDriver:
    def test_returns_none_without_calling_read_register_when_reader_is_absent(self) -> None:
        driver = _StubDriver(1234)
        driver._reader = None

        result = read_battery_status_via(driver)

        assert result is None
        assert driver.calls == []

    def test_returns_none_without_calling_read_register_when_client_is_absent(self) -> None:
        driver = _StubDriver(1234)
        driver._client = None

        result = read_battery_status_via(driver)

        assert result is None
        assert driver.calls == []


class TestARaisingReadPropagates:
    def test_the_function_does_not_catch_read_register_exceptions(self) -> None:
        """D4 (in the job's own module) relies on this: the job — not this
        function — is what turns a failed read into 'no row, retry next
        hour', so this shared function must let the exception through
        exactly like read_energy_registers_via's own per-address try/except
        deliberately does NOT live here."""
        driver = _StubDriver(None, raise_on_read=TimeoutError("meter refused"))

        with pytest.raises(TimeoutError):
            read_battery_status_via(driver)
