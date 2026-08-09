"""The D5 per-driver billing declarations on
``acquisition.drivers._dlms_profile.DlmsProfileDriver`` (M4c issue #25).

Before issue #25, ``BILLING_PROFILE_OBIS``, the bill-date candidate list, the
reset-reason key and the Cumulative Demand COSEM class were module constants
that :meth:`DlmsProfileDriver.read_billing` read directly — a concrete driver
had no way to replace any of them, even though the base's own docstring
already claimed "a concrete driver may override this tuple" (a claim that was
false until this issue). These tests exercise the seam mechanism itself,
against a minimal fake subclass that is not any real meter family — the real
family (:class:`~arichds.acquisition.drivers.smart_tcc.SmartTccDriver`) has
its own tests that prove the *values* it declares are the field-recorded
ones; these prove the *mechanism* actually reaches ``self``, not a constant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from gurux_dlms.enums import Unit
from gurux_dlms.objects import GXDLMSExtendedRegister, GXDLMSProfileGeneric, GXDLMSRegister

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms_profile import DlmsProfileDriver
from arichds.acquisition.obis import INSTANTANEOUS_OBIS

CLOCK_OBIS = "0.0.1.0.0.255"
CEWE_BILL_DATE_OBIS = "0.0.0.1.2.255"


class _FakeSeamDriver(DlmsProfileDriver):
    """A minimal concrete driver — not a real meter family — used only to
    prove the D5 seam mechanism reads ``self``, never a module constant."""

    def _protocol_args(self) -> list[str]:
        return []

    def _read_timeout_ms(self) -> int:
        return 1000

    @property
    def model_name(self) -> str:
        return "fake_seam"

    def get_obis_map(self) -> dict[str, tuple[str, int]]:
        return dict(INSTANTANEOUS_OBIS)


class _FakeBillingReader:
    """Reproduces the ``GXDLMSReader`` subset ``read_billing()`` calls."""

    def __init__(self, capture_objects: list[tuple[str, int]], entries_in_use: int, buffer: list[list[Any]]) -> None:
        self._capture_objects = capture_objects
        self._entries_in_use = entries_in_use
        self._buffer = buffer
        self.opened_profile_obis: str | None = None
        self.calls: list[tuple[str, int]] = []

    def read(self, obj: Any, attr: int) -> Any:
        if isinstance(obj, GXDLMSProfileGeneric):
            self.opened_profile_obis = str(obj.logicalName)
            self.calls.append(("__profile__", attr))
            if attr == 3:
                obj.captureObjects = [
                    (SimpleNamespace(logicalName=obis), SimpleNamespace(attributeIndex=a))
                    for obis, a in self._capture_objects
                ]
                return obj.captureObjects
            if attr == 7:
                return self._entries_in_use
            raise AssertionError(f"unexpected ProfileGeneric attr {attr}")

        obis = str(obj.logicalName)
        self.calls.append((obis, attr))
        if attr == 3:
            obj.scaler = 1.0
            obj.unit = Unit.NONE
            return None
        if attr == 2 and obis == _FakeSeamDriver.METER_SERIAL_OBIS[0]:
            return "SN-FAKE-1"
        raise AssertionError(f"unexpected attr {attr} for {obis}")

    def readRowsByEntry(self, pg: Any, index: int, count: int) -> list[list[Any]]:  # noqa: N802
        self.calls.append(("__rows__", index))
        return self._buffer[index - 1 : index - 1 + count]


def _build_driver(reader: _FakeBillingReader) -> _FakeSeamDriver:
    driver = _FakeSeamDriver(ConnectionParams.net("198.51.100.9", 4059), password="secret")
    driver._reader = reader  # noqa: SLF001
    driver._client = SimpleNamespace(objects=[])  # noqa: SLF001
    return driver


class TestBillingProfileObisIsDeclaredPerDriver:
    def test_the_base_default_opens_cewes_own_profile(self) -> None:
        reader = _FakeBillingReader([(CLOCK_OBIS, 2)], entries_in_use=0, buffer=[])
        driver = _build_driver(reader)

        driver.read_billing()

        assert reader.opened_profile_obis == "1.0.98.2.0.255"

    def test_a_subclass_override_opens_its_own_declared_profile(self) -> None:
        class _OverriddenObis(_FakeSeamDriver):
            BILLING_PROFILE_OBIS = "0.0.98.1.0.255"

        reader = _FakeBillingReader([(CLOCK_OBIS, 2)], entries_in_use=0, buffer=[])
        driver = _OverriddenObis(ConnectionParams.net("198.51.100.9", 4059), password="secret")
        driver._reader = reader  # noqa: SLF001
        driver._client = SimpleNamespace(objects=[])  # noqa: SLF001

        driver.read_billing()

        assert reader.opened_profile_obis == "0.0.98.1.0.255"


class TestBillDateCandidatesIsDeclaredPerDriver:
    def test_a_subclass_declaring_clock_only_ignores_cewes_own_bill_date_column(self) -> None:
        """The base default tries CEWE's own bill-date column first — if the
        seam did not reach ``self``, this row's date would resolve from
        ``CEWE_BILL_DATE_OBIS`` (2026-01-01) instead of the declared-only
        Clock column (2026-08-07), which is the mutation this test would miss
        if it only checked "a date came back"."""

        class _ClockOnlyBillDate(_FakeSeamDriver):
            BILL_DATE_CANDIDATES = ((CLOCK_OBIS, 2),)

        reader = _FakeBillingReader(
            [(CLOCK_OBIS, 2), (CEWE_BILL_DATE_OBIS, 2)],
            entries_in_use=1,
            buffer=[[datetime(2026, 8, 7, 11, 0), datetime(2026, 1, 1, 0, 0)]],
        )
        driver = _ClockOnlyBillDate(ConnectionParams.net("198.51.100.9", 4059), password="secret")
        driver._reader = reader  # noqa: SLF001
        driver._client = SimpleNamespace(objects=[])  # noqa: SLF001

        readings = driver.read_billing()

        assert readings[0].bill_date == datetime(2026, 8, 7, 4, 0, tzinfo=UTC)


class TestResetReasonKeyDeclaredAbsentSkipsTheWarning:
    def test_declared_none_reaches_positional_fallback_without_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        class _NoResetReason(_FakeSeamDriver):
            RESET_REASON_KEY = None

        reader = _FakeBillingReader(
            [(CLOCK_OBIS, 2)],
            entries_in_use=1,
            buffer=[[datetime(2026, 8, 7, 11, 0)]],
        )
        driver = _NoResetReason(ConnectionParams.net("198.51.100.9", 4059), password="secret")
        driver._reader = reader  # noqa: SLF001
        driver._client = SimpleNamespace(objects=[])  # noqa: SLF001

        with caplog.at_level("WARNING"):
            readings = driver.read_billing()

        assert readings[0].is_open is True  # positional fallback: entry 0 = open
        assert not any("reset-reason" in record.message.lower() for record in caplog.records)

    def test_declared_but_missing_from_the_capture_list_still_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """The base default (declared, CEWE's own key) is absent from this
        fake capture list — must still WARN, unlike the declared-``None``
        case above."""
        reader = _FakeBillingReader(
            [(CLOCK_OBIS, 2)],
            entries_in_use=1,
            buffer=[[datetime(2026, 8, 7, 11, 0)]],
        )
        driver = _build_driver(reader)

        with caplog.at_level("WARNING"):
            readings = driver.read_billing()

        assert readings[0].is_open is True
        assert any("reset-reason" in record.message.lower() for record in caplog.records)


class TestCumulDemandCosemClassIsDeclaredPerDriver:
    def test_the_base_default_is_extended_register(self) -> None:
        mapped = _FakeSeamDriver._mapped_billing_columns()
        _field, cosem_class, _unit = mapped[("1.0.1.2.0.255", 2)]
        assert cosem_class is GXDLMSExtendedRegister

    def test_a_subclass_override_changes_the_cumulative_demand_class_only(self) -> None:
        class _RegisterCumulDemand(_FakeSeamDriver):
            CUMUL_DEMAND_COSEM_CLASS = GXDLMSRegister

        mapped = _RegisterCumulDemand._mapped_billing_columns()
        _field, cumul_class, _unit = mapped[("1.0.1.2.0.255", 2)]
        _field, demand_class, _unit = mapped[("1.0.1.6.0.255", 2)]
        _field, energy_class, _unit = mapped[("1.0.1.8.0.255", 2)]

        assert cumul_class is GXDLMSRegister  # overridden
        assert demand_class is GXDLMSExtendedRegister  # untouched — D=6 group
        assert energy_class is GXDLMSRegister  # untouched — D=8 group was already Register
