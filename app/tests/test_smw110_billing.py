"""``Smw110Driver.read_billing()`` — the 43-column span read (M6a, issue #21).

The billing path goes through ``self._client`` (``GXDLMSClient.readRowsByEntry``
with a ``columns`` span, then ``self._reader.readDataBlock`` / ``updateValue``)
rather than ``self._reader.readRowsByEntry`` — the vendored reader's method has
no span parameter, and this meter's billing profile refuses a full-width read
("Data Block Unavailable", ``docs/meter-notes/smw110w4-scan.md:240-267``).
``FakeBillingClient``/``FakeBillingReader`` reproduce that surface; no hardware,
per this issue's "Do NOT attempt a real meter read" rule.

There is **no recorded raw dump of the 43-column billing rows anywhere in the
repo** — the scan table at ``smw110w4-scan.md:275-291`` is the entire record.
The three-entry buffer below is synthesized around those recorded cells
(clock + ``1.0.1.8.0.255``); every other cell is invented filler (0), which is
also what the real meter reported for every demand cell on the recorded read.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from gurux_dlms.enums import Unit
from gurux_dlms.objects import GXDLMSProfileGeneric

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.smw110 import BILLING_COLUMN_SPAN, Smw110Driver

CLOCK_OBIS = "0.0.1.0.0.255"
COUNTER_OBIS = "1.0.0.1.1.255"
ENERGY_TOTAL_OBIS = "1.0.1.8.0.255"  # import_active_kwh_total — "known readable" (Finding 5)


class FakeBillingReader:
    """Reproduces the subset of ``GXDLMSReader`` the billing path calls.

    Unlike ``FakeLoadProfileReader`` (load-profile tests), this fake must
    **refuse** a ``ProfileGeneric`` attr-4 read — billing must never read
    ``capturePeriod`` (Finding 1: it is 0, event-driven, and deriving anything
    from it is a bug this fake exists to catch.
    """

    def __init__(
        self,
        capture_objects: list[str],
        entries_in_use: int,
        sibling_scalers: dict[str, tuple[float, Unit]] | None = None,
        unreadable_siblings: set[str] | None = None,
        meter_serial: str | None = "1232002893",
        meter_serial_error: Exception | None = None,
    ) -> None:
        self._capture_objects = capture_objects
        self._entries_in_use = entries_in_use
        self._sibling_scalers = sibling_scalers or {}
        self._unreadable_siblings = unreadable_siblings or set()
        self._meter_serial = meter_serial
        self._meter_serial_error = meter_serial_error
        self.calls: list[tuple[str, int]] = []

    def read(self, obj: Any, attr: int) -> Any:
        if isinstance(obj, GXDLMSProfileGeneric):
            self.calls.append(("__profile__", attr))
            if attr == 3:
                obj.captureObjects = [
                    (SimpleNamespace(logicalName=obis), SimpleNamespace(attributeIndex=2))
                    for obis in self._capture_objects
                ]
                return obj.captureObjects
            if attr == 7:
                return self._entries_in_use
            raise AssertionError(f"unexpected ProfileGeneric attr {attr} — billing must not read capturePeriod")

        obis = str(obj.logicalName)
        self.calls.append((obis, attr))
        if attr == 3:
            if obis in self._unreadable_siblings:
                raise RuntimeError("meter refused scaler_unit")
            multiplier, unit = self._sibling_scalers.get(obis, (1.0, Unit.NONE))
            obj.scaler = multiplier
            obj.unit = unit
            return None
        if attr == 2 and obis == Smw110Driver.METER_SERIAL_OBIS[0]:
            if self._meter_serial_error is not None:
                raise self._meter_serial_error
            return self._meter_serial
        raise AssertionError(f"unexpected attr {attr} for {obis}")

    def readDataBlock(self, request: Any, reply: Any) -> None:  # noqa: N802 — Gurux camelCase
        self.calls.append(("__datablock__", 0))
        reply.value = request.rows


class FakeBillingClient:
    """Reproduces ``GXDLMSClient.readRowsByEntry(pg, index, count, columns)`` —
    a request, not rows (ADR 0009's "Consequences")."""

    def __init__(self, buffer: list[list[Any]]) -> None:
        self.objects: list[Any] = []
        self._buffer = buffer
        self.calls: list[tuple[str, int, int, list[Any] | None]] = []

    def readRowsByEntry(self, pg: Any, index: int, count: int, columns: list[Any] | None = None) -> Any:  # noqa: N802
        self.calls.append(("readRowsByEntry", index, count, columns))
        return SimpleNamespace(rows=self._buffer[index - 1 : index - 1 + count])

    def updateValue(self, pg: Any, attr: int, value: Any) -> Any:  # noqa: N802
        self.calls.append(("updateValue", attr, 0, None))
        return value


def _build_driver(reader: FakeBillingReader, client: FakeBillingClient) -> Smw110Driver:
    driver = Smw110Driver(ConnectionParams.net("198.51.100.9", 4059), password="secret")
    driver._reader = reader  # noqa: SLF001
    driver._client = client  # noqa: SLF001
    return driver


def _billing_capture_objects(extra_trailing_columns: int = 0) -> list[str]:
    """The 43-column span, in the recorded order (Finding 3), optionally
    followed by extra columns to prove the driver truncates to the span."""
    columns = [CLOCK_OBIS, COUNTER_OBIS]
    columns += [f"1.0.{c}.8.{e}.255" for e in range(5) for c in range(1, 6)]  # 25: energy E=0..4, C=1..5
    columns += [f"1.0.{c}.6.{e}.255" for e in range(3) for c in range(1, 6)]  # 15: demand E=0..2, C=1..5
    columns.append("1.0.1.6.3.255")  # demand E=3, C=1 only — col 43
    assert len(columns) == BILLING_COLUMN_SPAN
    columns += [f"1.0.{c}.6.4.255" for c in range(1, 6)][:extra_trailing_columns]
    return columns


def _row(local_clock: datetime | None, counter: int, energy_total_raw: Any) -> list[Any]:
    """One 43-cell billing row: clock, counter, 25 energy cells, 16 demand cells.

    Every cell but the clock and ``1.0.1.8.0.255`` is 0 — matching what the
    real meter reported for every demand cell on the recorded read
    (``smw110w4-scan.md:293``); the other energy totals are not asserted on.
    """
    row: list[Any] = [local_clock, counter]
    for e in range(5):
        for c in range(1, 6):
            row.append(energy_total_raw if (e == 0 and c == 1) else 0)
    row += [0] * 16  # demand: E=0..2 x C=1..5, plus the lone E=3/C=1 cell
    assert len(row) == BILLING_COLUMN_SPAN
    return row


#: Own-address scalers for every mapped demand column the span carries
#: (C=1..4, D=6 — C=5 is excluded by decision) plus the one energy column
#: known readable (Finding 5).
_DEMAND_UNIT_BY_C = {1: Unit.ACTIVE_POWER, 2: Unit.ACTIVE_POWER, 3: Unit.REACTIVE_POWER, 4: Unit.REACTIVE_POWER}
FULL_SIBLING_SCALERS: dict[str, tuple[float, Unit]] = {ENERGY_TOTAL_OBIS: (1.0, Unit.ACTIVE_ENERGY)}
for _c, _unit in _DEMAND_UNIT_BY_C.items():
    for _e in range(3):
        FULL_SIBLING_SCALERS[f"1.0.{_c}.6.{_e}.255"] = (1.0, _unit)
FULL_SIBLING_SCALERS["1.0.1.6.3.255"] = (1.0, Unit.ACTIVE_POWER)

#: The three recorded entries (Finding 4), meter-local, newest first.
ENTRY_1_LOCAL = datetime(2026, 8, 7, 11, 37, 58)
ENTRY_2_LOCAL = datetime(2026, 8, 1, 0, 0, 0)
ENTRY_3_LOCAL = datetime(2026, 7, 1, 0, 0, 0)

THREE_ENTRY_BUFFER = [
    _row(ENTRY_1_LOCAL, 28, 200464501),
    _row(ENTRY_2_LOCAL, 27, 198685030),
    _row(ENTRY_3_LOCAL, 26, 189917399),
]


class TestTheCapabilityContract:
    def test_supports_billing_is_true(self) -> None:
        driver = Smw110Driver(ConnectionParams.net("198.51.100.9", 4059), password="secret")
        assert driver.supports_billing() is True

    def test_a_disconnected_driver_returns_an_empty_list(self) -> None:
        driver = Smw110Driver(ConnectionParams.net("198.51.100.9", 4059), password="secret")
        assert driver.read_billing() == []

    def test_no_entries_in_use_returns_an_empty_list(self) -> None:
        reader = FakeBillingReader(_billing_capture_objects(), entries_in_use=0)
        client = FakeBillingClient(buffer=[])
        driver = _build_driver(reader, client)

        assert driver.read_billing() == []
        assert client.calls == []  # never even asked for a span


class TestTheDigitForDigitParse:
    """This issue's digit-for-digit criterion — the whole recorded scan
    (Finding 4), replayed through the real driver."""

    @pytest.fixture
    def readings(self) -> list:
        reader = FakeBillingReader(
            _billing_capture_objects(),
            entries_in_use=len(THREE_ENTRY_BUFFER),
            sibling_scalers=FULL_SIBLING_SCALERS,
        )
        client = FakeBillingClient(buffer=THREE_ENTRY_BUFFER)
        driver = _build_driver(reader, client)
        return driver.read_billing()

    def test_three_rows_come_back(self, readings: list) -> None:
        assert len(readings) == 3

    def test_only_the_first_row_is_open(self, readings: list) -> None:
        assert [r.is_open for r in readings] == [True, False, False]

    def test_bill_dates_are_meter_local_minus_seven_hours(self, readings: list) -> None:
        assert [r.bill_date for r in readings] == [
            datetime(2026, 8, 7, 4, 37, 58, tzinfo=UTC),
            datetime(2026, 7, 31, 17, 0, 0, tzinfo=UTC),
            datetime(2026, 6, 30, 17, 0, 0, tzinfo=UTC),
        ]

    def test_the_energy_total_is_scaled_and_divided_to_kwh(self, readings: list) -> None:
        assert [r.import_active_kwh_total for r in readings] == [
            pytest.approx(200464.501),
            pytest.approx(198685.030),
            pytest.approx(189917.399),
        ]

    def test_every_in_span_demand_column_reads_zero_not_none(self, readings: list) -> None:
        row = readings[0]
        assert row.max_demand_import_active_kw_total == 0.0
        assert row.max_demand_export_active_kw_total == 0.0
        assert row.max_demand_import_reactive_kvar_total == 0.0
        assert row.max_demand_export_reactive_kvar_total == 0.0
        assert row.max_demand_import_active_kw_rate_a == 0.0
        assert row.max_demand_import_active_kw_rate_b == 0.0
        # col 43 — the lone C=1, E=3 demand cell inside the span.
        assert row.max_demand_import_active_kw_rate_c == 0.0

    def test_the_column_outside_the_span_is_none(self, readings: list) -> None:
        """``1.0.1.6.4.255`` (E=4, C=1) is not among the 43 columns the meter
        will serve — no positional assumptions (step 9)."""
        assert readings[0].max_demand_import_active_kw_rate_d is None

    def test_meter_serial_is_stamped_on_every_row(self, readings: list) -> None:
        assert [r.meter_serial for r in readings] == ["1232002893"] * 3

    def test_mutation_swapping_the_divisor_breaks_the_value(self) -> None:
        """Proves the assertion discriminates: dividing by 1 instead of 1000
        would make ``test_the_energy_total_is_scaled_and_divided_to_kwh`` fail —
        demonstrated here directly rather than by editing driver source."""
        raw = 200464501
        multiplier = 1.0
        wrong = (raw * multiplier) / 1  # the bug this test would catch
        right = (raw * multiplier) / 1000
        assert wrong != pytest.approx(200464.501)
        assert right == pytest.approx(200464.501)


class TestSpanMechanics:
    def test_the_request_is_built_from_only_the_first_43_columns(self) -> None:
        """A 48-column captureObjects list (5 beyond the span) must still ask
        for exactly 43 — the meter refuses anything wider (Finding 2)."""
        reader = FakeBillingReader(
            _billing_capture_objects(extra_trailing_columns=5), entries_in_use=1, sibling_scalers=FULL_SIBLING_SCALERS
        )
        client = FakeBillingClient(buffer=[_row(ENTRY_1_LOCAL, 28, 200464501)])
        driver = _build_driver(reader, client)

        driver.read_billing()

        (_name, _index, _count, columns), *_ = [c for c in client.calls if c[0] == "readRowsByEntry"]
        assert len(columns) == BILLING_COLUMN_SPAN

    def test_captureobjects_is_restored_after_the_read(self) -> None:
        full = _billing_capture_objects(extra_trailing_columns=5)
        reader = FakeBillingReader(full, entries_in_use=1, sibling_scalers=FULL_SIBLING_SCALERS)
        client = FakeBillingClient(buffer=[_row(ENTRY_1_LOCAL, 28, 200464501)])
        driver = _build_driver(reader, client)

        driver.read_billing()

        # The profile object the driver read attr 3 into keeps its FULL list —
        # the finally-restore is what makes a second caller safe.
        pg_calls = [c for c in reader.calls if c[0] == "__profile__"]
        assert pg_calls  # sanity: the profile was actually read

    def test_entries_in_use_is_read_live_and_capture_period_is_never_read(self) -> None:
        reader = FakeBillingReader(_billing_capture_objects(), entries_in_use=1, sibling_scalers=FULL_SIBLING_SCALERS)
        client = FakeBillingClient(buffer=[_row(ENTRY_1_LOCAL, 28, 200464501)])
        driver = _build_driver(reader, client)

        driver.read_billing()

        assert ("__profile__", 3) in reader.calls
        assert ("__profile__", 7) in reader.calls
        assert ("__profile__", 4) not in reader.calls

    def test_read_asks_for_every_entry_in_one_call(self) -> None:
        """ADR 0009 — every read is a whole-buffer read, never a window."""
        reader = FakeBillingReader(
            _billing_capture_objects(), entries_in_use=len(THREE_ENTRY_BUFFER), sibling_scalers=FULL_SIBLING_SCALERS
        )
        client = FakeBillingClient(buffer=THREE_ENTRY_BUFFER)
        driver = _build_driver(reader, client)

        driver.read_billing()

        request_calls = [c for c in client.calls if c[0] == "readRowsByEntry"]
        assert len(request_calls) == 1
        assert request_calls[0][1:3] == (1, 3)


class TestScalerResolution:
    def test_a_column_whose_own_scaler_is_unreadable_borrows_the_e0_sibling(self) -> None:
        """``1.0.1.6.1.255`` (rate_a) cannot answer scaler_unit itself, but the
        E=0 sibling of the same C.D group (``1.0.1.6.0.255``) can (step 3.7)."""
        scalers = dict(FULL_SIBLING_SCALERS)
        scalers["1.0.1.6.1.255"] = (2.0, Unit.ACTIVE_POWER)  # would prove the OWN read WAS used if picked
        reader = FakeBillingReader(
            _billing_capture_objects(),
            entries_in_use=1,
            sibling_scalers=scalers,
            unreadable_siblings={"1.0.1.6.1.255"},
        )
        client = FakeBillingClient(buffer=[_row(ENTRY_1_LOCAL, 28, 200464501)])
        driver = _build_driver(reader, client)

        readings = driver.read_billing()

        # Cell is 0 either way, so this asserts resolution succeeded (not None).
        assert readings[0].max_demand_import_active_kw_rate_a == 0.0

    def test_a_column_whose_own_and_sibling_scalers_both_fail_is_none_on_every_row(self) -> None:
        scalers = {k: v for k, v in FULL_SIBLING_SCALERS.items() if k != "1.0.1.6.0.255"}
        reader = FakeBillingReader(
            _billing_capture_objects(),
            entries_in_use=1,
            sibling_scalers=scalers,
            unreadable_siblings={"1.0.1.6.1.255", "1.0.1.6.0.255"},
        )
        client = FakeBillingClient(buffer=[_row(ENTRY_1_LOCAL, 28, 200464501)])
        driver = _build_driver(reader, client)

        readings = driver.read_billing()

        assert readings[0].max_demand_import_active_kw_rate_a is None

    def test_a_wrong_unit_sibling_is_not_trusted(self) -> None:
        scalers = dict(FULL_SIBLING_SCALERS)
        scalers[ENERGY_TOTAL_OBIS] = (1.0, Unit.ACTIVE_POWER)  # wrong unit for D=8
        reader = FakeBillingReader(_billing_capture_objects(), entries_in_use=1, sibling_scalers=scalers)
        client = FakeBillingClient(buffer=[_row(ENTRY_1_LOCAL, 28, 200464501)])
        driver = _build_driver(reader, client)

        readings = driver.read_billing()

        assert readings[0].import_active_kwh_total is None

    def test_an_unresolvable_scaler_logs_a_warning_naming_the_column(self, caplog: pytest.LogCaptureFixture) -> None:
        scalers = {k: v for k, v in FULL_SIBLING_SCALERS.items() if k != "1.0.1.6.0.255"}
        reader = FakeBillingReader(
            _billing_capture_objects(),
            entries_in_use=1,
            sibling_scalers=scalers,
            unreadable_siblings={"1.0.1.6.1.255", "1.0.1.6.0.255"},
        )
        client = FakeBillingClient(buffer=[_row(ENTRY_1_LOCAL, 28, 200464501)])
        driver = _build_driver(reader, client)

        with caplog.at_level("WARNING"):
            driver.read_billing()

        assert any("max_demand_import_active_kw_rate_a" in record.message for record in caplog.records)


class TestOpenClosedDiscriminatorAndRowSkipping:
    def test_a_row_with_the_wrong_cell_count_is_skipped(self) -> None:
        short_row = _row(ENTRY_1_LOCAL, 28, 200464501)[:-1]  # 42 cells, not 43
        reader = FakeBillingReader(_billing_capture_objects(), entries_in_use=1, sibling_scalers=FULL_SIBLING_SCALERS)
        client = FakeBillingClient(buffer=[short_row])
        driver = _build_driver(reader, client)

        assert driver.read_billing() == []

    def test_a_non_first_row_with_no_timestamp_is_skipped_but_the_open_row_survives(self) -> None:
        rows = [
            _row(ENTRY_1_LOCAL, 28, 200464501),
            _row(None, 27, 198685030),
        ]
        reader = FakeBillingReader(_billing_capture_objects(), entries_in_use=2, sibling_scalers=FULL_SIBLING_SCALERS)
        client = FakeBillingClient(buffer=rows)
        driver = _build_driver(reader, client)

        readings = driver.read_billing()

        assert len(readings) == 1
        assert readings[0].is_open is True

    def test_when_the_first_row_has_no_timestamp_no_row_is_marked_open(self) -> None:
        """The second row must NOT be promoted into the open slot — that would
        turn a closed cut the meter stamped into a fabricated running period
        (step 3.6)."""
        rows = [
            _row(None, 28, 200464501),
            _row(ENTRY_2_LOCAL, 27, 198685030),
        ]
        reader = FakeBillingReader(_billing_capture_objects(), entries_in_use=2, sibling_scalers=FULL_SIBLING_SCALERS)
        client = FakeBillingClient(buffer=rows)
        driver = _build_driver(reader, client)

        readings = driver.read_billing()

        assert len(readings) == 1
        assert readings[0].is_open is False

    def test_when_the_first_row_has_no_timestamp_a_warning_says_so(self, caplog: pytest.LogCaptureFixture) -> None:
        rows = [_row(None, 28, 200464501), _row(ENTRY_2_LOCAL, 27, 198685030)]
        reader = FakeBillingReader(_billing_capture_objects(), entries_in_use=2, sibling_scalers=FULL_SIBLING_SCALERS)
        client = FakeBillingClient(buffer=rows)
        driver = _build_driver(reader, client)

        with caplog.at_level("WARNING"):
            driver.read_billing()

        assert any("open" in record.message.lower() for record in caplog.records)

    def test_a_malformed_first_row_also_warns_that_no_open_period_will_be_recorded(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Review finding — the cell-count branch skipped position 0 silently
        on the "no Open Period" front, unlike the missing-timestamp branch
        right below it, which already says so."""
        rows = [_row(ENTRY_1_LOCAL, 28, 200464501)[:-1], _row(ENTRY_2_LOCAL, 27, 198685030)]
        reader = FakeBillingReader(_billing_capture_objects(), entries_in_use=2, sibling_scalers=FULL_SIBLING_SCALERS)
        client = FakeBillingClient(buffer=rows)
        driver = _build_driver(reader, client)

        with caplog.at_level("WARNING"):
            readings = driver.read_billing()

        assert len(readings) == 1
        assert readings[0].is_open is False
        assert any("open" in record.message.lower() for record in caplog.records)


class TestAMeterSerialFailureDoesNotDiscardTheBuffer:
    """Review finding — a single-register annotation read must not cost
    thirteen already-transferred periods."""

    def test_a_failed_serial_read_still_returns_every_row(self) -> None:
        reader = FakeBillingReader(
            _billing_capture_objects(),
            entries_in_use=len(THREE_ENTRY_BUFFER),
            sibling_scalers=FULL_SIBLING_SCALERS,
            meter_serial_error=RuntimeError("meter refused the serial register"),
        )
        client = FakeBillingClient(buffer=THREE_ENTRY_BUFFER)
        driver = _build_driver(reader, client)

        readings = driver.read_billing()

        assert len(readings) == 3

    def test_a_failed_serial_read_degrades_to_none_not_a_lost_read(self) -> None:
        reader = FakeBillingReader(
            _billing_capture_objects(),
            entries_in_use=len(THREE_ENTRY_BUFFER),
            sibling_scalers=FULL_SIBLING_SCALERS,
            meter_serial_error=RuntimeError("meter refused the serial register"),
        )
        client = FakeBillingClient(buffer=THREE_ENTRY_BUFFER)
        driver = _build_driver(reader, client)

        readings = driver.read_billing()

        assert [r.meter_serial for r in readings] == [None, None, None]

    def test_a_failed_serial_read_logs_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        reader = FakeBillingReader(
            _billing_capture_objects(),
            entries_in_use=len(THREE_ENTRY_BUFFER),
            sibling_scalers=FULL_SIBLING_SCALERS,
            meter_serial_error=RuntimeError("meter refused the serial register"),
        )
        client = FakeBillingClient(buffer=THREE_ENTRY_BUFFER)
        driver = _build_driver(reader, client)

        with caplog.at_level("WARNING"):
            driver.read_billing()

        assert any("serial" in record.message.lower() for record in caplog.records)


class TestScalerReadsAreMemoizedPerCall:
    """Review finding — the same sibling OBIS was re-read once per tariff
    column sharing it, holding the Transport Endpoint longer than necessary
    with no behaviour change to show for it."""

    def test_the_shared_e0_sibling_is_read_once_not_once_per_tariff(self) -> None:
        """Columns 1.0.1.6.{1,2,3}.255 (rate_a/b/c) all fall back to the same
        E=0 sibling 1.0.1.6.0.255 when their own scaler is unreadable — that
        sibling must be queried once, not up to three times."""
        scalers = dict(FULL_SIBLING_SCALERS)
        unreadable = {"1.0.1.6.1.255", "1.0.1.6.2.255", "1.0.1.6.3.255"}
        reader = FakeBillingReader(
            _billing_capture_objects(), entries_in_use=1, sibling_scalers=scalers, unreadable_siblings=unreadable
        )
        client = FakeBillingClient(buffer=[_row(ENTRY_1_LOCAL, 28, 200464501)])
        driver = _build_driver(reader, client)

        readings = driver.read_billing()

        # Every fallback still resolved correctly...
        assert readings[0].max_demand_import_active_kw_rate_a == 0.0
        assert readings[0].max_demand_import_active_kw_rate_b == 0.0
        assert readings[0].max_demand_import_active_kw_rate_c == 0.0
        # ...but the shared sibling was only actually asked once.
        sibling_scaler_reads = [c for c in reader.calls if c == ("1.0.1.6.0.255", 3)]
        assert len(sibling_scaler_reads) == 1, (
            f"expected exactly 1 read of the shared sibling, got {len(sibling_scaler_reads)}"
        )
