"""``Smw110Driver.read_load_profile()`` — locked vectors + read-path tests (issue #10).

Three numeric vectors are locked here **before the read path exists**
(`docs/meter-notes/smw110w4-scan.md:152-160`, REMAKE-PLAN §5): a raw buffer cell
becomes the correct engineering value only when the scaler-borrowing resolver
picks the sibling by unit (D5) and the driver multiplies rather than raises to a
power (ADR 0002). Everything below runs against a fake reader that reproduces
the recorded buffer rows and scaler probe — no hardware, per the "Do NOT attempt
a real meter read" rule in this issue's delegation prompt.

``FakeLoadProfileReader`` extends the shape of ``test_dlms_scaler.FakeGuruxReader``
/ ``ScalerTestDriver`` to also cover ``GXDLMSProfileGeneric`` (capture objects,
capture period, entries-in-use, ``readRowsByEntry``) and the sibling's ``unit``,
which the scaler test's fake never needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from gurux_dlms.enums import Unit
from gurux_dlms.objects import GXDLMSProfileGeneric

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.base import IntervalReading
from arichds.acquisition.drivers.smw110 import Smw110Driver, _entry_window

CLOCK_OBIS = "0.0.1.0.0.255"
ENERGY_OBIS = "1.0.1.29.0.255"
ENERGY_SIBLING = "1.0.1.8.0.255"
POWER_SIBLING = "1.0.1.7.0.255"  # same C-group as ENERGY_SIBLING — must NOT be picked
VOLT_L1_OBIS = "1.0.32.27.0.255"
VOLT_L1_SIBLING = "1.0.32.7.0.255"
CURRENT_L1_OBIS = "1.0.31.27.0.255"
CURRENT_L1_SIBLING = "1.0.31.7.0.255"


class FakeLoadProfileReader:
    """Reproduces the subset of ``GXDLMSReader`` ``read_load_profile`` calls.

    Attributes:
        calls: Every ``(obis_or_sentinel, attr)`` in call order — ``"__profile__"``
            stands in for the ``GXDLMSProfileGeneric`` object itself (attrs 3/4/7),
            since it has no OBIS code of its own worth asserting on.
    """

    def __init__(
        self,
        capture_objects: list[str],
        buffer: list[list[Any]],
        capture_period_sec: int = 900,
        entries_in_use: int | None = None,
        sibling_scalers: dict[str, tuple[float, Unit]] | None = None,
        unreadable_siblings: set[str] | None = None,
    ) -> None:
        self._capture_objects = capture_objects
        self._buffer = buffer
        self._capture_period_sec = capture_period_sec
        self._entries_in_use = entries_in_use if entries_in_use is not None else len(buffer)
        self._sibling_scalers = sibling_scalers or {}
        self._unreadable_siblings = unreadable_siblings or set()
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
            if attr == 4:
                return self._capture_period_sec
            if attr == 7:
                return self._entries_in_use
            raise AssertionError(f"unexpected ProfileGeneric attr {attr}")

        obis = str(obj.logicalName)
        self.calls.append((obis, attr))
        if attr == 3:
            if obis in self._unreadable_siblings:
                raise RuntimeError("meter refused scaler_unit")
            multiplier, unit = self._sibling_scalers.get(obis, (1.0, Unit.NONE))
            obj.scaler = multiplier
            obj.unit = unit
            return None
        raise AssertionError(f"unexpected attr {attr} for {obis}")

    def readRowsByEntry(self, pg: Any, index: int, count: int) -> list[list[Any]]:  # noqa: N802 — Gurux camelCase
        self.calls.append(("__rows__", index))
        return self._buffer[index - 1 : index - 1 + count]


def _build_driver(reader: FakeLoadProfileReader) -> Smw110Driver:
    """A real ``Smw110Driver`` wired to a fake reader instead of a socket."""
    driver = Smw110Driver(ConnectionParams.net("198.51.100.9", 4059), password="secret")
    driver._reader = reader  # noqa: SLF001 — the whole point of the fake-reader shape
    driver._client = SimpleNamespace(objects=[])  # noqa: SLF001
    return driver


class TestLockedVectors:
    """smw110w4-scan.md:152-160 — locked before the read path exists (issue #10 AC4)."""

    def test_energy_vector_10138_wh_becomes_10_138_kwh(self) -> None:
        """Raw 10138 x multiplier 1 (Wh) / 1000 = 10.138 kWh."""
        row_local = datetime(2026, 8, 7, 11, 0)
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, ENERGY_OBIS],
            buffer=[[row_local, 10138]],
            sibling_scalers={ENERGY_SIBLING: (1.0, Unit.ACTIVE_ENERGY)},
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert len(readings) == 1
        assert readings[0].import_active_kwh == pytest.approx(10.138)

    def test_voltage_vector_225942_becomes_225_942_v(self) -> None:
        """Raw 225942 x multiplier 0.001 = 225.942 V."""
        row_local = datetime(2026, 8, 7, 11, 0)
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, VOLT_L1_OBIS],
            buffer=[[row_local, 225942]],
            sibling_scalers={VOLT_L1_SIBLING: (0.001, Unit.VOLTAGE)},
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert len(readings) == 1
        assert readings[0].volt_l1 == pytest.approx(225.942)

    def test_current_vector_59004_becomes_59_004_a(self) -> None:
        """Raw 59004 x multiplier 0.001 = 59.004 A."""
        row_local = datetime(2026, 8, 7, 11, 0)
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, CURRENT_L1_OBIS],
            buffer=[[row_local, 59004]],
            sibling_scalers={CURRENT_L1_SIBLING: (0.001, Unit.CURRENT)},
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert len(readings) == 1
        assert readings[0].current_l1 == pytest.approx(59.004)


class TestEntryWindow:
    """The module-level pure ``(entries_in_use, capture_period_sec, start, end, now)
    -> (start, count) | None`` window function — ported from v1's ``_entry_window``
    (Output Parity on the margins), adapted to timezone-aware UTC."""

    def test_a_window_at_the_oldest_end_clamps_start_to_one(self) -> None:
        """A small buffer relative to the requested window walks off the start."""
        result = _entry_window(
            entries_in_use=3,
            capture_period_sec=900,
            start_utc=datetime(2026, 8, 7, 0, 0, tzinfo=UTC),
            end_utc=datetime(2026, 8, 7, 1, 0, tzinfo=UTC),
            now_utc=datetime(2026, 8, 7, 1, 0, tzinfo=UTC),
        )

        assert result == (1, 3)

    def test_a_window_at_the_newest_end_clamps_count_to_the_buffer(self) -> None:
        """The window never reaches past the newest entry."""
        now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)

        result = _entry_window(
            entries_in_use=10,
            capture_period_sec=900,
            start_utc=now - timedelta(hours=1),
            end_utc=now,
            now_utc=now,
        )

        assert result is not None
        start, count = result
        assert start + count - 1 == 10

    def test_an_empty_buffer_returns_none(self) -> None:
        result = _entry_window(
            entries_in_use=0,
            capture_period_sec=900,
            start_utc=datetime(2026, 8, 7, 0, 0, tzinfo=UTC),
            end_utc=datetime(2026, 8, 7, 1, 0, tzinfo=UTC),
            now_utc=datetime(2026, 8, 7, 1, 0, tzinfo=UTC),
        )

        assert result is None

    def test_a_mid_buffer_window_pins_the_2_and_4_row_margins(self) -> None:
        """Neither end of the buffer is touched here, so the only thing that can
        make this assertion pass is the exact v1 margins (2 rows on the start
        side, 4 on the count side) — margins 0/0 would give ``(64, 4)`` instead,
        and any other pair would give something else again. This is what
        actually guards Output Parity; the oldest/newest-end tests above pass
        under several different margin values."""
        now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
        start_utc = datetime(2026, 8, 7, 3, 0, tzinfo=UTC)
        end_utc = start_utc + timedelta(hours=1)

        result = _entry_window(
            entries_in_use=100,
            capture_period_sec=900,
            start_utc=start_utc,
            end_utc=end_utc,
            now_utc=now,
        )

        assert result == (62, 8)

    def test_a_window_entirely_outside_the_buffer_still_returns_a_range(self) -> None:
        """The window function only clamps index bounds — it cannot know whether
        the requested time range overlaps the buffer's real contents. That is the
        row filter's job in ``read_load_profile``, not this function's (see
        ``TestReadLoadProfile.test_window_outside_the_buffers_range_yields_no_rows``)."""
        now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
        far_past_start = now - timedelta(days=365)
        far_past_end = far_past_start + timedelta(hours=1)

        result = _entry_window(
            entries_in_use=10,
            capture_period_sec=900,
            start_utc=far_past_start,
            end_utc=far_past_end,
            now_utc=now,
        )

        assert result is not None


class TestScalerResolver:
    """D5/D6 — pick the sibling by unit, never by whichever answers first."""

    def test_energy_uses_the_energy_sibling_not_the_power_sibling(self) -> None:
        """1.0.1.7 (ACTIVE_POWER) shares the energy column's C-group and answers
        first on the real meter (smw110w4-scan.md:129-137). Routed through
        ``read_load_profile`` — not ``_resolve_multiplier`` directly — because the
        thing under test is *which sibling the column map picks*, and
        ``_resolve_multiplier`` cannot reach the wrong one on its own: the sibling
        OBIS is one of its arguments. Giving both siblings different multipliers
        is what makes a wrong pick produce a visibly wrong number instead of an
        assertion that is true by construction."""
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, ENERGY_OBIS],
            buffer=[[datetime(2026, 8, 7, 11, 0), 10138]],
            sibling_scalers={
                ENERGY_SIBLING: (1.0, Unit.ACTIVE_ENERGY),
                POWER_SIBLING: (5.0, Unit.ACTIVE_POWER),
            },
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        # Mutation-tested: pointing the energy column's sibling at POWER_SIBLING
        # in _MAPPED_CAPTURE_COLUMNS turns this red — either as None (POWER_SIBLING
        # reports Unit.ACTIVE_POWER, which D6's unit check rejects) or, were that
        # check ever weakened too, as 10138 x 5.0 / 1000 = 50.69 instead of 10.138.
        # Either failure mode trips this assertion; a vacuously-true check would not.
        assert readings[0].import_active_kwh == pytest.approx(10.138)
        assert (POWER_SIBLING, 3) not in reader.calls

    def test_wrong_unit_yields_none_not_a_number(self) -> None:
        """A sibling that answers ACTIVE_POWER where ACTIVE_ENERGY was required
        must not be trusted for a multiplier (D6)."""
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, ENERGY_OBIS],
            buffer=[],
            sibling_scalers={ENERGY_SIBLING: (1.0, Unit.ACTIVE_POWER)},
        )
        driver = _build_driver(reader)

        multiplier = driver._resolve_multiplier(ENERGY_SIBLING, Unit.ACTIVE_ENERGY, "import_active_kwh")  # noqa: SLF001

        assert multiplier is None

    def test_unreadable_sibling_yields_none(self) -> None:
        """A refused scaler must not scale — never guess an exponent (D6)."""
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, ENERGY_OBIS],
            buffer=[],
            unreadable_siblings={ENERGY_SIBLING},
        )
        driver = _build_driver(reader)

        multiplier = driver._resolve_multiplier(ENERGY_SIBLING, Unit.ACTIVE_ENERGY, "import_active_kwh")  # noqa: SLF001

        assert multiplier is None

    def test_unreadable_sibling_logs_exactly_one_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """One event (the unreadable scaler), one WARNING line — not also the
        unit-mismatch line for the same failure."""
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, ENERGY_OBIS],
            buffer=[],
            unreadable_siblings={ENERGY_SIBLING},
        )
        driver = _build_driver(reader)

        with caplog.at_level("WARNING"):
            driver._resolve_multiplier(ENERGY_SIBLING, Unit.ACTIVE_ENERGY, "import_active_kwh")  # noqa: SLF001

        assert len(caplog.records) == 1

    def test_multiplier_is_the_scaler_value_itself_not_ten_to_its_power(self) -> None:
        """The trap the mandated skill's old snippet fell into: ``obj.scaler`` is
        already the multiplier, not an exponent — ``10 ** obj.scaler`` would be
        v1's phantom-x10 bug reborn."""
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, VOLT_L1_OBIS],
            buffer=[],
            sibling_scalers={VOLT_L1_SIBLING: (0.001, Unit.VOLTAGE)},
        )
        driver = _build_driver(reader)

        multiplier = driver._resolve_multiplier(VOLT_L1_SIBLING, Unit.VOLTAGE, "volt_l1")  # noqa: SLF001

        assert multiplier == pytest.approx(0.001)


# ─── Step 6: read_load_profile() end to end ────────────────────────────────────

# The full 20-column capture list, in buffer order (docs/meter-notes/smw110w4-scan.md:85-97;
# raw/smw110w4-tcp-probe-2026-08-07.txt:49-68). Columns 10-20 are the twelve
# dropped ones (status word, six PERCENTAGE, five PHASE_ANGLE_DEGREE).
_FULL_CAPTURE_OBJECTS = [
    CLOCK_OBIS,
    "0.0.96.5.0.255",
    ENERGY_OBIS,
    VOLT_L1_OBIS,
    "1.0.52.27.0.255",
    "1.0.72.27.0.255",
    CURRENT_L1_OBIS,
    "1.0.51.27.0.255",
    "1.0.71.27.0.255",
    "1.0.32.128.124.255",
    "1.0.52.128.124.255",
    "1.0.72.128.124.255",
    "1.0.31.128.124.255",
    "1.0.51.128.124.255",
    "1.0.71.128.124.255",
    "1.0.81.128.4.255",
    "1.0.81.128.15.255",
    "1.0.81.128.26.255",
    "1.0.81.128.1.255",
    "1.0.81.128.20.255",
]

_FULL_SIBLING_SCALERS = {
    ENERGY_SIBLING: (1.0, Unit.ACTIVE_ENERGY),
    VOLT_L1_SIBLING: (0.001, Unit.VOLTAGE),
    "1.0.52.7.0.255": (0.001, Unit.VOLTAGE),
    "1.0.72.7.0.255": (0.001, Unit.VOLTAGE),
    CURRENT_L1_SIBLING: (0.001, Unit.CURRENT),
    "1.0.51.7.0.255": (0.001, Unit.CURRENT),
    "1.0.71.7.0.255": (0.001, Unit.CURRENT),
}

# The verbatim row at raw/smw110w4-tcp-probe-2026-08-07.txt:179 (last-6 index
# [1]): clock 2026-08-07 11:00 meter-local, 20 real cells in capture order.
_VERBATIM_ROW = [
    datetime(2026, 8, 7, 11, 0),
    0,
    13130,
    228188,
    225989,
    228127,
    76833,
    76993,
    76552,
    1944,
    1995,
    2003,
    2780,
    2850,
    3090,
    0,
    359427,
    358854,
    240113,
    238848,
]


class TestReadLoadProfile:
    def test_naive_start_raises_value_error(self) -> None:
        driver = _build_driver(FakeLoadProfileReader(capture_objects=[], buffer=[]))

        with pytest.raises(ValueError, match="timezone-aware"):
            driver.read_load_profile(1, datetime(2026, 8, 7, 3, 0), datetime(2026, 8, 7, 5, 0, tzinfo=UTC))

    def test_naive_end_raises_value_error(self) -> None:
        driver = _build_driver(FakeLoadProfileReader(capture_objects=[], buffer=[]))

        with pytest.raises(ValueError, match="timezone-aware"):
            driver.read_load_profile(1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0))

    def test_disconnected_driver_returns_empty_list(self) -> None:
        """Mirrors ``read_register()``'s disconnected contract (D10)."""
        driver = Smw110Driver(ConnectionParams.net("198.51.100.9", 4059), password="secret")

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert readings == []

    def test_a_verbatim_recorded_row_replays_correctly(self) -> None:
        reader = FakeLoadProfileReader(
            capture_objects=_FULL_CAPTURE_OBJECTS,
            buffer=[_VERBATIM_ROW],
            sibling_scalers=_FULL_SIBLING_SCALERS,
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert len(readings) == 1
        reading = readings[0]
        assert reading.read_at == datetime(2026, 8, 7, 4, 0, tzinfo=UTC)
        assert reading.import_active_kwh == pytest.approx(13.130)
        assert reading.volt_l1 == pytest.approx(228.188)
        assert reading.volt_l2 == pytest.approx(225.989)
        assert reading.volt_l3 == pytest.approx(228.127)
        assert reading.current_l1 == pytest.approx(76.833)
        assert reading.current_l2 == pytest.approx(76.993)
        assert reading.current_l3 == pytest.approx(76.552)
        assert reading.source == driver.source

    def test_non_numeric_measurement_cell_is_skipped_not_multiplied(self) -> None:
        """A GXDateTime or raw ``bytearray`` in a measurement cell (not the clock
        cell) must not reach ``raw * multiplier`` — ``_normalize``'s non-numeric
        guard (`_dlms.py`) is unreachable if the multiply runs first and raises."""
        row = list(_VERBATIM_ROW)
        row[3] = bytearray(b"\x01\x02")  # volt_l1 cell — not a number
        reader = FakeLoadProfileReader(
            capture_objects=_FULL_CAPTURE_OBJECTS,
            buffer=[row],
            sibling_scalers=_FULL_SIBLING_SCALERS,
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert len(readings) == 1
        assert readings[0].volt_l1 is None
        # The rest of the row is unaffected by the one bad cell.
        assert readings[0].import_active_kwh == pytest.approx(13.130)
        assert readings[0].current_l1 == pytest.approx(76.833)

    def test_decimal_voltage_cell_is_scaled_correctly(self) -> None:
        """``_normalize`` treats ``Decimal`` as a real possibility from a register
        read (`_dlms.py`, `test_dlms_scaler.py::test_decimal_values_are_coerced_to_float`)
        — the field loop's guard must admit it *and* handle it, not just admit it.
        ``Decimal * float`` (the multiplier is always a float — ``obj.scaler`` comes
        from ``math.pow``) is unsupported, so this exercises the fractional-multiplier
        path (0.001) where the crash was verified."""
        row = list(_VERBATIM_ROW)
        row[3] = Decimal("228188")  # volt_l1 cell
        reader = FakeLoadProfileReader(
            capture_objects=_FULL_CAPTURE_OBJECTS,
            buffer=[row],
            sibling_scalers=_FULL_SIBLING_SCALERS,
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert len(readings) == 1
        assert readings[0].volt_l1 == pytest.approx(228.188)

    def test_decimal_energy_cell_is_scaled_and_divided_to_kwh(self) -> None:
        """Same as above but through the ÷1000 ``_normalize`` path (multiplier 1.0,
        not fractional) — the crash was verified independent of the multiplier's
        value, so this is the second, distinct path worth pinning."""
        row = list(_VERBATIM_ROW)
        row[2] = Decimal("13130")  # import_active_kwh (energy) cell
        reader = FakeLoadProfileReader(
            capture_objects=_FULL_CAPTURE_OBJECTS,
            buffer=[row],
            sibling_scalers=_FULL_SIBLING_SCALERS,
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert len(readings) == 1
        assert readings[0].import_active_kwh == pytest.approx(13.130)

    def test_freq_is_always_none_and_no_dropped_column_leaks_through(self) -> None:
        """D3: the dataclass's fixed field set is the structural guarantee — the
        twelve dropped capture columns (status word, PERCENTAGE, PHASE_ANGLE_DEGREE)
        have no field to leak into.

        The four M4c fields (``import_reactive_kvarh``, ``export_active_kwh``,
        ``export_reactive_kvarh``, ``avg_geo_pf`` — issue #24) exist on
        ``IntervalReading`` now because the three CEWE drivers produce them,
        but this model's load profile still has no columns for any of them,
        so they must stay ``None`` on every SMW110W4 row."""
        from dataclasses import fields

        reader = FakeLoadProfileReader(
            capture_objects=_FULL_CAPTURE_OBJECTS,
            buffer=[_VERBATIM_ROW],
            sibling_scalers=_FULL_SIBLING_SCALERS,
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert readings[0].freq is None
        assert readings[0].import_reactive_kvarh is None
        assert readings[0].export_active_kwh is None
        assert readings[0].export_reactive_kvarh is None
        assert readings[0].avg_geo_pf is None
        field_names = {f.name for f in fields(IntervalReading)}
        assert field_names == {
            "read_at",
            "source",
            "logger_id",
            "interval_sec",
            "volt_l1",
            "volt_l2",
            "volt_l3",
            "current_l1",
            "current_l2",
            "current_l3",
            "freq",
            "import_active_kwh",
            "import_reactive_kvarh",
            "export_active_kwh",
            "export_reactive_kvarh",
            "avg_geo_pf",
        }

    def test_reads_capture_objects_period_and_entries_live(self) -> None:
        """D7 — no schema cache, no assumed 900 s: attr 3, 4 and 7 on every call."""
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, ENERGY_OBIS],
            buffer=[[datetime(2026, 8, 7, 11, 0), 10138]],
            sibling_scalers={ENERGY_SIBLING: (1.0, Unit.ACTIVE_ENERGY)},
        )
        driver = _build_driver(reader)

        driver.read_load_profile(1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC))

        assert ("__profile__", 3) in reader.calls
        assert ("__profile__", 4) in reader.calls
        assert ("__profile__", 7) in reader.calls

    def test_row_with_wrong_cell_count_is_skipped_not_misaligned(self) -> None:
        """D7's residual mismatch handling: schema says 3 columns, the row has 2."""
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, ENERGY_OBIS, VOLT_L1_OBIS],
            buffer=[[datetime(2026, 8, 7, 11, 0), 10138]],
            sibling_scalers={
                ENERGY_SIBLING: (1.0, Unit.ACTIVE_ENERGY),
                VOLT_L1_SIBLING: (0.001, Unit.VOLTAGE),
            },
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert readings == []

    def test_row_with_none_timestamp_is_skipped(self) -> None:
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, ENERGY_OBIS],
            buffer=[[None, 10138]],
            sibling_scalers={ENERGY_SIBLING: (1.0, Unit.ACTIVE_ENERGY)},
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert readings == []

    def test_window_outside_the_buffers_range_yields_no_rows(self) -> None:
        """``_entry_window`` can still return a range for a window nowhere near
        the buffer's real contents (see ``TestEntryWindow`` above) — the row
        filter here is what actually empties the result."""
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, ENERGY_OBIS],
            buffer=[[datetime(2026, 8, 7, 11, 0), 10138]],
            sibling_scalers={ENERGY_SIBLING: (1.0, Unit.ACTIVE_ENERGY)},
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(1, datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 1, 1, 1, tzinfo=UTC))

        assert readings == []


class TestTheCapabilityContract:
    """M5a-1 D3 — ``supports_load_profile()`` is how the job asks, and it is the
    only way it may ask.

    ``hasattr`` is forbidden by ``CLAUDE.md``'s "no model branch in generic code"
    invariant for a specific reason: it makes a driver that *forgot* the method
    indistinguishable from one that deliberately lacks it, and the second failure
    is silent. So the method exists on every driver, answering ``False`` by
    default, and :meth:`read_load_profile` exists too — raising rather than
    missing.
    """

    def test_the_base_class_answers_no(self) -> None:
        # A minimal MeterDriver stub, not a real production driver (M4c,
        # issue #24: Prometer100Driver used to be "the driver with no load
        # profile" — then it grew one, and this test broke for the wrong
        # reason). Tests the base class's own default in isolation.
        from arichds.acquisition.drivers.base import MeterDriver

        class _MinimalDriver(MeterDriver):
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

        driver = _MinimalDriver()
        assert driver.supports_load_profile() is False

    def test_the_smw110_answers_yes(self) -> None:
        driver = Smw110Driver(ConnectionParams.net("198.51.100.9", 4059), password="secret")
        assert driver.supports_load_profile() is True

    def test_calling_the_base_read_raises_rather_than_being_absent(self) -> None:
        from arichds.acquisition.drivers.base import MeterDriver

        class _MinimalDriver(MeterDriver):
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

        driver = _MinimalDriver()
        with pytest.raises(NotImplementedError):
            driver.read_load_profile(1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC))


class TestLoggerIdComesFromTheObis:
    """M5a-1 D5 — the id is a property of the profile that was read, never of the
    order profiles happened to be discovered in (ADR 0005's principle applied to
    a logger instead of a serial)."""

    def test_the_two_scanned_profiles_map_to_one_and_two(self) -> None:
        from arichds.acquisition.obis import logger_id_for_profile

        assert logger_id_for_profile("1.0.99.1.0.255") == 1
        assert logger_id_for_profile("1.0.99.2.0.255") == 2

    def test_an_unscanned_profile_raises_rather_than_minting_an_id(self) -> None:
        """An explicit map, not a parse of the OBIS group: a parse would silently
        mint ids for profiles nobody has scanned, which is the same class of
        failure as deriving one from discovery order."""
        from arichds.acquisition.obis import logger_id_for_profile

        with pytest.raises(ValueError):
            logger_id_for_profile("1.0.99.3.0.255")

    def test_every_row_carries_the_id_of_the_profile_that_was_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reading Logger 2 must stamp ``2``. Under a discovery-order derivation
        the only profile read is the first one, so this yields ``1`` — which is
        what makes this test fail for the right reason.

        (The SMW110W4 itself has no Logger 2 — both field units answer "undefined
        object" — so this drives the driver at a profile OBIS it would never see
        in the field, on purpose: the *derivation* is what is under test.)
        """
        monkeypatch.setattr("arichds.acquisition.drivers.smw110.LOAD_PROFILE_OBIS", "1.0.99.2.0.255")
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, ENERGY_OBIS],
            buffer=[[datetime(2026, 8, 7, 11, 0), 10138], [datetime(2026, 8, 7, 11, 15), 10279]],
            sibling_scalers={ENERGY_SIBLING: (1.0, Unit.ACTIVE_ENERGY)},
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert len(readings) == 2
        assert [r.logger_id for r in readings] == [2, 2]

    def test_logger_one_is_what_this_model_really_reads(self) -> None:
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, ENERGY_OBIS],
            buffer=[[datetime(2026, 8, 7, 11, 0), 10138]],
            sibling_scalers={ENERGY_SIBLING: (1.0, Unit.ACTIVE_ENERGY)},
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert readings[0].logger_id == 1


class TestIntervalSecIsTheMetersOwnPeriod:
    """M5a-1 D4 — seconds straight off ProfileGeneric attr 4, no label conversion
    and no assumed 900 (SPEC §3.5: a Prometer 100's Logger 2 is 300 s)."""

    def test_the_live_capture_period_is_stamped_on_every_row(self) -> None:
        reader = FakeLoadProfileReader(
            capture_objects=[CLOCK_OBIS, ENERGY_OBIS],
            buffer=[[datetime(2026, 8, 7, 11, 0), 10138], [datetime(2026, 8, 7, 11, 5), 10279]],
            capture_period_sec=300,
            sibling_scalers={ENERGY_SIBLING: (1.0, Unit.ACTIVE_ENERGY)},
        )
        driver = _build_driver(reader)

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 3, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert len(readings) == 2
        assert [r.interval_sec for r in readings] == [300, 300]
