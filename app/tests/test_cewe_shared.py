"""``acquisition.drivers._dlms_profile`` — the shared billing/load-profile
logic every CEWE model uses (D6/D8/D9/D10, M4c issue #24). Renamed from
``_cewe``/``CeweDriver`` at issue #25, when the SMART TCC family became a
second driver family on this base — see the module's own docstring.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from gurux_dlms.enums import Unit
from gurux_dlms.objects import GXDLMSProfileGeneric

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms_profile import (
    CEWE_BILL_DATE_CANDIDATES,
    CEWE_DEMAND_TIME_COLUMNS,
    CEWE_MAPPED_BILLING_COLUMNS,
    DlmsProfileDriver,
    meter_local_to_utc_inverse,
    resolve_billing_multiplier,
    resolve_load_profile_multiplier,
)
from arichds.acquisition.drivers._profile import meter_local_to_utc
from arichds.acquisition.drivers.prometer100 import Prometer100Driver

CLOCK_OBIS = "0.0.1.0.0.255"
CEWE_BILL_DATE_OBIS = "0.0.0.1.2.255"
RESET_REASON_OBIS = "0.0.0.1.12.255"
DEMAND_C1_E0 = "1.0.1.6.0.255"  # max_demand_import_active_kw_total AND its capture time


class TestCeweBillDateCandidates:
    def test_cewe_own_bill_date_column_is_tried_first(self) -> None:
        assert CEWE_BILL_DATE_CANDIDATES[0] == (CEWE_BILL_DATE_OBIS, 2)

    def test_the_clock_is_the_fallback(self) -> None:
        assert CEWE_BILL_DATE_CANDIDATES[1] == (CLOCK_OBIS, 2)


class TestTheObisAttributeCollision:
    """F2 — a max-demand value (attr 2) and its own capture time (attr 5)
    share one OBIS code. The two must be distinct mapped columns."""

    def test_the_value_and_the_capture_time_are_different_keys(self) -> None:
        assert (DEMAND_C1_E0, 2) in CEWE_MAPPED_BILLING_COLUMNS
        assert (DEMAND_C1_E0, 5) in CEWE_DEMAND_TIME_COLUMNS
        assert (DEMAND_C1_E0, 2) != (DEMAND_C1_E0, 5)

    def test_the_value_maps_to_the_kw_field_and_the_time_to_the_time_field(self) -> None:
        field, _cls, _unit = CEWE_MAPPED_BILLING_COLUMNS[(DEMAND_C1_E0, 2)]
        assert field == "max_demand_import_active_kw_total"
        assert CEWE_DEMAND_TIME_COLUMNS[(DEMAND_C1_E0, 5)] == "max_demand_import_active_time_total"


class FakeCeweBillingReader:
    """Reproduces the subset of ``GXDLMSReader`` the CEWE billing path calls —
    a full-width, no-span entry-access read (F4/F6), unlike SMW110W4's."""

    def __init__(
        self,
        capture_objects: list[tuple[str, int]],
        entries_in_use: int,
        buffer: list[list[Any]],
        sibling_scalers: dict[str, tuple[float, Unit]] | None = None,
        unreadable: set[str] | None = None,
        meter_serial: str | None = "SN-CEWE-1",
    ) -> None:
        self._capture_objects = capture_objects
        self._entries_in_use = entries_in_use
        self._buffer = buffer
        self._sibling_scalers = sibling_scalers or {}
        self._unreadable = unreadable or set()
        self._meter_serial = meter_serial
        self.calls: list[tuple[str, int]] = []

    def read(self, obj: Any, attr: int) -> Any:
        if isinstance(obj, GXDLMSProfileGeneric):
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
            if obis in self._unreadable:
                raise RuntimeError("meter refused scaler_unit")
            multiplier, unit = self._sibling_scalers.get(obis, (1.0, Unit.NONE))
            obj.scaler = multiplier
            obj.unit = unit
            return None
        if attr == 2 and obis == Prometer100Driver.METER_SERIAL_OBIS[0]:
            return self._meter_serial
        raise AssertionError(f"unexpected attr {attr} for {obis}")

    def readRowsByEntry(self, pg: Any, index: int, count: int) -> list[list[Any]]:  # noqa: N802
        self.calls.append(("__rows__", index))
        return self._buffer[index - 1 : index - 1 + count]


def _build_driver(reader: FakeCeweBillingReader) -> DlmsProfileDriver:
    driver = Prometer100Driver(ConnectionParams.net("198.51.100.9", 4059), password="secret")
    driver._reader = reader  # noqa: SLF001
    driver._client = SimpleNamespace(objects=[])  # noqa: SLF001
    return driver


def _capture_list_with_reset_reason() -> list[tuple[str, int]]:
    columns = [(CLOCK_OBIS, 2), (CEWE_BILL_DATE_OBIS, 2), (RESET_REASON_OBIS, 2)]
    columns += [(DEMAND_C1_E0, 2), (DEMAND_C1_E0, 5)]
    return columns


SCALERS = {DEMAND_C1_E0: (1.0, Unit.ACTIVE_POWER)}


def _row(
    bill_date_local: datetime | None, reset_reason: int | None, demand_value: float, demand_time_local: datetime | None
) -> list[Any]:
    return [None, bill_date_local, reset_reason, demand_value, demand_time_local]


class TestOpenClosedFromResetReason:
    def test_reset_reason_255_is_open(self) -> None:
        reader = FakeCeweBillingReader(
            _capture_list_with_reset_reason(),
            entries_in_use=1,
            buffer=[_row(datetime(2026, 8, 7, 11, 0), 255, 10.0, None)],
            sibling_scalers=SCALERS,
        )
        driver = _build_driver(reader)

        readings = driver.read_billing()

        assert len(readings) == 1
        assert readings[0].is_open is True

    def test_reset_reason_other_than_255_is_closed(self) -> None:
        reader = FakeCeweBillingReader(
            _capture_list_with_reset_reason(),
            entries_in_use=1,
            buffer=[_row(datetime(2026, 7, 1, 0, 0), 2, 10.0, None)],
            sibling_scalers=SCALERS,
        )
        driver = _build_driver(reader)

        readings = driver.read_billing()

        assert readings[0].is_open is False

    def test_only_one_row_is_ever_open(self) -> None:
        """D9 — a driver returns at most one open row; a second candidate is
        kept closed and warned about rather than producing two open rows."""
        reader = FakeCeweBillingReader(
            _capture_list_with_reset_reason(),
            entries_in_use=2,
            buffer=[
                _row(datetime(2026, 8, 7, 11, 0), 255, 10.0, None),
                _row(datetime(2026, 7, 1, 0, 0), 255, 9.0, None),  # also 255 - must not also be open
            ],
            sibling_scalers=SCALERS,
        )
        driver = _build_driver(reader)

        readings = driver.read_billing()

        assert [r.is_open for r in readings] == [True, False]

    def test_a_non_integer_reset_reason_cell_classifies_closed(self) -> None:
        reader = FakeCeweBillingReader(
            _capture_list_with_reset_reason(),
            entries_in_use=1,
            buffer=[_row(datetime(2026, 8, 7, 11, 0), None, 10.0, None)],
            sibling_scalers=SCALERS,
        )
        driver = _build_driver(reader)

        readings = driver.read_billing()

        assert readings[0].is_open is False


class TestOpenClosedFallsBackToPositionalWhenColumnAbsent:
    def test_no_reset_reason_column_falls_back_to_entry_one_is_open(self, caplog: pytest.LogCaptureFixture) -> None:
        columns = [(CLOCK_OBIS, 2), (CEWE_BILL_DATE_OBIS, 2), (DEMAND_C1_E0, 2)]
        reader = FakeCeweBillingReader(
            columns,
            entries_in_use=2,
            buffer=[
                [None, datetime(2026, 8, 7, 11, 0), 10.0],
                [None, datetime(2026, 7, 1, 0, 0), 9.0],
            ],
            sibling_scalers=SCALERS,
        )
        driver = _build_driver(reader)

        with caplog.at_level("WARNING"):
            readings = driver.read_billing()

        assert [r.is_open for r in readings] == [True, False]
        assert any("reset-reason" in record.message.lower() for record in caplog.records)


class TestDemandTimeIsNeverScaled:
    def test_the_capture_time_cell_is_converted_to_utc_not_multiplied(self) -> None:
        reader = FakeCeweBillingReader(
            _capture_list_with_reset_reason(),
            entries_in_use=1,
            buffer=[_row(datetime(2026, 8, 7, 11, 0), 255, 123.0, datetime(2026, 8, 5, 9, 12, 0))],
            sibling_scalers=SCALERS,
        )
        driver = _build_driver(reader)

        readings = driver.read_billing()

        assert readings[0].max_demand_import_active_time_total == datetime(2026, 8, 5, 2, 12, 0, tzinfo=UTC)
        # The value column scales like every other billing number — divided
        # by WH_TO_KWH_DIVISOR (D12) — while the time column above did not.
        assert readings[0].max_demand_import_active_kw_total == pytest.approx(0.123)

    def test_a_missing_capture_time_cell_is_none(self) -> None:
        reader = FakeCeweBillingReader(
            _capture_list_with_reset_reason(),
            entries_in_use=1,
            buffer=[_row(datetime(2026, 8, 7, 11, 0), 255, 123.0, None)],
            sibling_scalers=SCALERS,
        )
        driver = _build_driver(reader)

        readings = driver.read_billing()

        assert readings[0].max_demand_import_active_time_total is None


class TestMeterLocalToUtcInverse:
    """D14 — the inverse conversion used to build ``readRowsByRange``'s
    selective-access bounds. Review finding 4: unpinned, a flipped sign
    silently empties every load-profile window rather than raising."""

    def test_a_known_utc_instant_converts_to_the_expected_naive_local_bound(self) -> None:
        utc_instant = datetime(2026, 8, 7, 4, 0, tzinfo=UTC)

        local = meter_local_to_utc_inverse(utc_instant)

        assert local == datetime(2026, 8, 7, 11, 0)
        assert local.tzinfo is None

    def test_round_trips_through_meter_local_to_utc(self) -> None:
        original = datetime(2026, 8, 7, 4, 0, tzinfo=UTC)

        round_tripped = meter_local_to_utc(meter_local_to_utc_inverse(original))

        assert round_tripped == original

    def test_mutation_flipping_the_sign_breaks_the_expected_bound(self) -> None:
        """Proves the assertion above discriminates: a flipped sign (-7h
        instead of +7h) would produce 2026-08-06 21:00, not 11:00."""
        utc_instant = datetime(2026, 8, 7, 4, 0, tzinfo=UTC)
        wrong = (utc_instant - timedelta(hours=7)).replace(tzinfo=None)
        right = meter_local_to_utc_inverse(utc_instant)
        assert wrong != right
        assert right == datetime(2026, 8, 7, 11, 0)


class _FakeScalerReader:
    """A minimal fake for the scaler-resolution functions directly — no
    ProfileGeneric, just ``reader.read(obj, 3)`` on standalone registers."""

    def __init__(
        self, scalers: dict[str, tuple[float, Unit]] | None = None, unreadable: set[str] | None = None
    ) -> None:
        self._scalers = scalers or {}
        self._unreadable = unreadable or set()
        self.calls: list[str] = []

    def read(self, obj: Any, attr: int) -> None:
        assert attr == 3
        obis = str(obj.logicalName)
        self.calls.append(obis)
        if obis in self._unreadable:
            raise RuntimeError("meter refused scaler_unit")
        multiplier, unit = self._scalers.get(obis, (1.0, Unit.NONE))
        obj.scaler = multiplier
        obj.unit = unit


class _FakeScalerClient:
    def __init__(self) -> None:
        self.objects: list[Any] = []


class TestBillingE0SiblingFallback:
    """Review finding 5 — the E=0 sibling fallback that ``resolve_billing_multiplier``
    already had, pinned directly for the first time."""

    def test_when_the_own_address_is_denied_the_e0_sibling_resolves(self) -> None:
        from gurux_dlms.objects import GXDLMSExtendedRegister

        reader = _FakeScalerReader(scalers={"1.0.1.6.0.255": (1.0, Unit.ACTIVE_POWER)}, unreadable={"1.0.1.6.1.255"})
        client = _FakeScalerClient()

        multiplier = resolve_billing_multiplier(
            reader,
            client,
            {},
            "1.0.1.6.1.255",
            GXDLMSExtendedRegister,
            Unit.ACTIVE_POWER,
            "max_demand_import_active_kw_rate_a",
            "prometer100",
        )

        assert multiplier == pytest.approx(1.0)
        assert "1.0.1.6.0.255" in reader.calls


class TestCumulativeDemandFallsBackToD6MaxDemand:
    """Review finding 2 — v1's proven route for D=2 (Cumulative Demand): when
    both the own address and the E=0 sibling fail, borrow the D=6 (max
    demand) scaler for the same C/E — same physical quantity, same unit
    (cewe-worker/_tcp_driver_base.py:861-873)."""

    def test_when_own_and_e0_both_fail_the_d6_sibling_resolves(self) -> None:
        from gurux_dlms.objects import GXDLMSExtendedRegister

        reader = _FakeScalerReader(
            scalers={"1.0.1.6.1.255": (2.0, Unit.ACTIVE_POWER)},
            unreadable={"1.0.1.2.1.255", "1.0.1.2.0.255"},
        )
        client = _FakeScalerClient()

        multiplier = resolve_billing_multiplier(
            reader,
            client,
            {},
            "1.0.1.2.1.255",
            GXDLMSExtendedRegister,
            Unit.ACTIVE_POWER,
            "cumul_demand_import_active_kw_rate_a",
            "premier550",
        )

        assert multiplier == pytest.approx(2.0)

    def test_the_reactive_group_falls_back_to_its_own_d6_sibling(self) -> None:
        from gurux_dlms.objects import GXDLMSExtendedRegister

        reader = _FakeScalerReader(scalers={"1.0.3.6.0.255": (3.0, Unit.REACTIVE_POWER)}, unreadable={"1.0.3.2.0.255"})
        client = _FakeScalerClient()

        multiplier = resolve_billing_multiplier(
            reader,
            client,
            {},
            "1.0.3.2.0.255",
            GXDLMSExtendedRegister,
            Unit.REACTIVE_POWER,
            "cumul_demand_import_reactive_kvar_total",
            "premier550",
        )

        assert multiplier == pytest.approx(3.0)

    def test_when_the_same_tariff_d6_sibling_also_fails_the_d6_total_resolves(self) -> None:
        """The real-meter finding: the meter denies ``scaler_unit`` on every
        ``D=6`` tariff column too (``E=1``..``E=4``) — only the ``D=6``
        group's own total (``E=0``) answers directly. A rate_a Cumulative
        Demand column must still resolve via that total."""
        from gurux_dlms.objects import GXDLMSExtendedRegister

        reader = _FakeScalerReader(
            scalers={"1.0.1.6.0.255": (4.0, Unit.ACTIVE_POWER)},
            unreadable={"1.0.1.2.1.255", "1.0.1.2.0.255", "1.0.1.6.1.255"},
        )
        client = _FakeScalerClient()

        multiplier = resolve_billing_multiplier(
            reader,
            client,
            {},
            "1.0.1.2.1.255",
            GXDLMSExtendedRegister,
            Unit.ACTIVE_POWER,
            "cumul_demand_import_active_kw_rate_a",
            "premier550",
        )

        assert multiplier == pytest.approx(4.0)

    def test_energy_columns_get_no_d6_fallback(self) -> None:
        """D=8 energy is not Cumulative Demand — must not pick up the D=6
        fallback meant only for D=2, or a wrong-quantity scaler could be
        borrowed by accident."""
        from gurux_dlms.objects import GXDLMSRegister

        reader = _FakeScalerReader(unreadable={"1.0.1.8.0.255"})
        client = _FakeScalerClient()

        multiplier = resolve_billing_multiplier(
            reader,
            client,
            {},
            "1.0.1.8.0.255",
            GXDLMSRegister,
            Unit.ACTIVE_ENERGY,
            "import_active_kwh_total",
            "premier550",
        )

        assert multiplier is None
        assert "1.0.1.6.0.255" not in reader.calls


class TestLoadProfileSiblingFallback:
    """Review finding 1 — every CEWE load-profile measurement column was
    NULL on all three real meters because the own-address-only resolver had
    no sibling to fall back to, unlike SMW110W4's proven
    ``_resolve_multiplier``."""

    def test_when_the_own_address_is_denied_the_sibling_resolves(self) -> None:
        reader = _FakeScalerReader(scalers={"1.0.1.8.0.255": (1.0, Unit.ACTIVE_ENERGY)}, unreadable={"1.0.1.29.0.255"})
        client = _FakeScalerClient()

        multiplier = resolve_load_profile_multiplier(
            reader, client, {}, "1.0.1.29.0.255", "1.0.1.8.0.255", Unit.ACTIVE_ENERGY, "import_active_kwh", "saral305"
        )

        assert multiplier == pytest.approx(1.0)

    def test_a_denied_own_address_with_no_working_sibling_is_none(self) -> None:
        reader = _FakeScalerReader(unreadable={"1.0.1.29.0.255", "1.0.1.8.0.255"})
        client = _FakeScalerClient()

        multiplier = resolve_load_profile_multiplier(
            reader, client, {}, "1.0.1.29.0.255", "1.0.1.8.0.255", Unit.ACTIVE_ENERGY, "import_active_kwh", "saral305"
        )

        assert multiplier is None

    def test_no_sibling_declared_means_own_address_only(self) -> None:
        """A column with no sibling declared (``sibling_obis=None``) must not
        crash and must not try a bogus second address."""
        reader = _FakeScalerReader(scalers={"1.0.14.27.0.255": (1.0, Unit.FREQUENCY)})
        client = _FakeScalerClient()

        multiplier = resolve_load_profile_multiplier(
            reader, client, {}, "1.0.14.27.0.255", None, Unit.FREQUENCY, "freq", "prometer100"
        )

        assert multiplier == pytest.approx(1.0)
        assert reader.calls == ["1.0.14.27.0.255"]


class TestLoadProfileScalerCaching:
    """Review finding 3 — a chunked walk calls ``read_load_profile()`` once
    per 24h chunk (up to 90 for a full backfill); an uncached resolver
    re-issues every column's DLMS round trip on every chunk."""

    def test_the_sibling_is_read_only_once_across_repeated_resolutions(self) -> None:
        reader = _FakeScalerReader(scalers={"1.0.1.8.0.255": (1.0, Unit.ACTIVE_ENERGY)})
        client = _FakeScalerClient()
        cache: dict[tuple[str, type, Unit], float | None] = {}

        for _ in range(3):
            resolve_load_profile_multiplier(
                reader,
                client,
                cache,
                "1.0.1.29.0.255",
                "1.0.1.8.0.255",
                Unit.ACTIVE_ENERGY,
                "import_active_kwh",
                "saral305",
            )

        assert reader.calls.count("1.0.1.29.0.255") == 1
        assert reader.calls.count("1.0.1.8.0.255") == 1
