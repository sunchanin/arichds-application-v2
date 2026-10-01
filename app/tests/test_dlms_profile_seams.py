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
        #: ``(index, count)`` for every ``readRowsByEntry`` call — kept
        #: separate from ``calls`` (which only ever recorded the index) so
        #: existing assertions on ``calls`` stay meaningful while a test can
        #: still verify the requested row *count*, not just its start.
        self.entry_access_calls: list[tuple[int, int]] = []

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
        self.entry_access_calls.append((index, count))
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


class TestBillingNewestClosedBillDate:
    """The Billing Change Check's driver-side read (ADR 0018, D1/D2/D11/D13,
    issue #43)."""

    def test_the_signal_is_the_newest_closed_period_not_the_open_row(self) -> None:
        """D1 — entry 1 is the Open Period on this profile (F4); its bill
        date must never be what this method answers. Mutation: answering
        with the open row's bill date instead would return the 2026-08-07
        date below rather than the 2026-07-31 one."""
        reader = _FakeBillingReader(
            [(CLOCK_OBIS, 2)],
            entries_in_use=2,
            buffer=[
                [datetime(2026, 8, 7, 11, 0)],  # entry 1 — open, newest clock
                [datetime(2026, 7, 31, 17, 0)],  # entry 2 — closed
            ],
        )
        driver = _build_driver(reader)

        result = driver.billing_newest_closed_bill_date()

        assert result == datetime(2026, 7, 31, 10, 0, tzinfo=UTC)

    def test_two_entries_are_read_in_one_call(self) -> None:
        """D1 — the check reads count=2, never a single entry access call."""
        reader = _FakeBillingReader(
            [(CLOCK_OBIS, 2)],
            entries_in_use=2,
            buffer=[[datetime(2026, 8, 7, 11, 0)], [datetime(2026, 7, 31, 17, 0)]],
        )
        driver = _build_driver(reader)

        driver.billing_newest_closed_bill_date()

        assert reader.entry_access_calls == [(1, 2)]

    def test_a_disconnected_driver_returns_none(self) -> None:
        driver = _FakeSeamDriver(ConnectionParams.net("198.51.100.9", 4059), password="secret")
        assert driver.billing_newest_closed_bill_date() is None

    def test_an_empty_buffer_returns_none(self) -> None:
        reader = _FakeBillingReader([(CLOCK_OBIS, 2)], entries_in_use=0, buffer=[])
        driver = _build_driver(reader)

        assert driver.billing_newest_closed_bill_date() is None

    def test_ordering_comes_from_the_declaration_not_a_hardcoded_index(self) -> None:
        """D11(a) — a driver declaring oldest-first must ask for the entries
        near the END of the buffer, not index 1. Mutation (a) — hardcoding
        index 1 regardless of the declaration — stays green on a
        newest-first driver but goes red here, where the declared driver is
        oldest-first and the buffer's last two entries are what must be
        read."""

        class _OldestFirstSeamDriver(_FakeSeamDriver):
            BILLING_NEWEST_ENTRY_FIRST = False

        reader = _FakeBillingReader(
            [(CLOCK_OBIS, 2)],
            entries_in_use=3,
            buffer=[
                [datetime(2026, 6, 1, 0, 0)],  # entry 1 — oldest
                [datetime(2026, 7, 1, 0, 0)],  # entry 2 — closed, newest closed
                [datetime(2026, 8, 7, 11, 0)],  # entry 3 — open, newest
            ],
        )
        driver = _OldestFirstSeamDriver(ConnectionParams.net("198.51.100.9", 4059), password="secret")
        driver._reader = reader  # noqa: SLF001
        driver._client = SimpleNamespace(objects=[])  # noqa: SLF001

        result = driver.billing_newest_closed_bill_date()

        rows_calls = [c for c in reader.calls if c[0] == "__rows__"]
        assert rows_calls == [("__rows__", 2)]  # index = entries_in_use - 1 = 2, not 1
        assert result == datetime(2026, 6, 30, 17, 0, tzinfo=UTC)  # entry 2's date, meter-local -> UTC

    def test_flipping_the_declaration_changes_the_requested_index(self) -> None:
        """D11(b) — the same buffer, read through both declarations, must ask
        for different entry-access windows. Proves the ordering flag actually
        reaches the request rather than being read and ignored."""
        buffer = [
            [datetime(2026, 6, 1, 0, 0)],
            [datetime(2026, 7, 1, 0, 0)],
            [datetime(2026, 8, 7, 11, 0)],
        ]

        newest_first_reader = _FakeBillingReader([(CLOCK_OBIS, 2)], entries_in_use=3, buffer=buffer)
        newest_first = _build_driver(newest_first_reader)
        newest_first.billing_newest_closed_bill_date()

        class _OldestFirstSeamDriver(_FakeSeamDriver):
            BILLING_NEWEST_ENTRY_FIRST = False

        oldest_first_reader = _FakeBillingReader([(CLOCK_OBIS, 2)], entries_in_use=3, buffer=buffer)
        oldest_first = _OldestFirstSeamDriver(ConnectionParams.net("198.51.100.9", 4059), password="secret")
        oldest_first._reader = oldest_first_reader  # noqa: SLF001
        oldest_first._client = SimpleNamespace(objects=[])  # noqa: SLF001
        oldest_first.billing_newest_closed_bill_date()

        newest_first_index = [c for c in newest_first_reader.calls if c[0] == "__rows__"][0][1]
        oldest_first_index = [c for c in oldest_first_reader.calls if c[0] == "__rows__"][0][1]
        assert newest_first_index != oldest_first_index

    def test_entries_in_use_moving_alone_does_not_change_the_answer(self) -> None:
        """D13 — entriesInUse only tells the read where the buffer's newest
        end is (needed for an oldest-first profile's index math); it is never
        the change signal itself. Two reads whose first two (newest-first)
        entries are identical must answer identically even though the ring
        counter grew — proving nothing about *this* method depends on the
        counter beyond locating the window."""
        smaller_buffer = _FakeBillingReader(
            [(CLOCK_OBIS, 2)],
            entries_in_use=3,
            buffer=[[datetime(2026, 8, 7, 11, 0)], [datetime(2026, 7, 31, 17, 0)], [datetime(2026, 6, 30, 17, 0)]],
        )
        larger_buffer = _FakeBillingReader(
            [(CLOCK_OBIS, 2)],
            entries_in_use=13,
            buffer=[[datetime(2026, 8, 7, 11, 0)], [datetime(2026, 7, 31, 17, 0)], [datetime(2026, 6, 30, 17, 0)]],
        )

        first = _build_driver(smaller_buffer).billing_newest_closed_bill_date()
        second = _build_driver(larger_buffer).billing_newest_closed_bill_date()

        assert first == second == datetime(2026, 7, 31, 10, 0, tzinfo=UTC)

    def test_reads_use_the_classifier_not_a_fresh_guess(self) -> None:
        """D1 — the reset-reason cell decides open/closed exactly as
        :meth:`read_billing` decides it, via ``_classify_open``. A row whose
        reset-reason cell is NOT the not-reset sentinel is closed even at
        position 0."""

        class _ClockAndResetReason(_FakeSeamDriver):
            pass

        capture = [(CLOCK_OBIS, 2), ("0.0.0.1.12.255", 2)]
        reader = _FakeBillingReader(
            capture,
            entries_in_use=1,
            buffer=[[datetime(2026, 7, 31, 17, 0), 3]],  # reset-reason 3 != 255 -> closed, even at position 0
        )
        driver = _ClockAndResetReason(ConnectionParams.net("198.51.100.9", 4059), password="secret")
        driver._reader = reader  # noqa: SLF001
        driver._client = SimpleNamespace(objects=[])  # noqa: SLF001

        result = driver.billing_newest_closed_bill_date()

        assert result == datetime(2026, 7, 31, 10, 0, tzinfo=UTC)


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
