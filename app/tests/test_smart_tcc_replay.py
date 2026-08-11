"""Replay tests against the recorded SMART TCC field scan (D12, M4c issue
#25) — the reinterpretation of the issue's "replay parity" criterion.

**Why this file exists instead of a row-level replay like
``test_cewe_replay_parity.py``**: the recorded scan
(``docs/meter-notes/tcc-obis-scan.md``) contains the **layout** (both
profiles' capture lists, in wire order) but no billing **row values** — the
meter is unreachable (F13, D1) and nobody has read a live row. The only
values the scan actually recorded are the bill date (14/07/2026 16:00
meter-local), the billing-period counter (1), ``entries_in_use`` (1),
``capturePeriod`` (900 s on Logger 1, 0 s on billing) and scaler exponent
(0). D12 splits "parity" into three provable parts instead of pretending a
row-level replay exists:

1. The recorded **layout** is pinned as a verbatim fixture, and every column
   this driver maps is asserted present in it (mirrors
   ``test_cewe_replay_parity.py``'s ``TestLiveCaptureListsMatchTheMeterNotes``).
2. ``read_billing()`` is driven against a fake reader replaying the exact
   148-column layout with **synthetic** row values, proving the
   ``(OBIS, attribute)`` collision (a max-demand value at attr 2 and its own
   capture time at attr 5, same OBIS) resolves to two different, correctly
   treated fields.
3. The values the scan actually recorded are pinned directly: column counts,
   capture periods, ``entries_in_use``, and the bill-date conversion.

D1 applies here exactly as everywhere else in this issue: every reader below
is a fake replaying the recorded scan. Nothing here opens a socket.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from gurux_dlms.enums import Unit
from gurux_dlms.objects import GXDLMSProfileGeneric, GXDLMSRegister

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.smart_tcc import SmartTccDriver

CLOCK_OBIS = "0.0.1.0.0.255"

# ─── Part 1 — the recorded layout, verbatim (docs/meter-notes/tcc-obis-scan.md) ──

#: Logger 1 (``1.0.99.1.0.255``) — capturePeriod 900 s, 297 entries, 35
#: capture columns (F3, ``tcc-obis-scan.md``:648-684). OBIS only, no attr —
#: every measurement cell in this profile is attr 2, the same shape
#: ``test_cewe_replay_parity.py``'s live capture lists use.
TCC_LOGGER1_LIVE: list[str] = [
    "0.0.1.0.0.255",
    "1.0.99.1.0.255",  # PROFILE_GENERIC self-reference (attr -1)
    "0.0.96.10.1.255",
    "1.0.1.29.0.255",
    "1.0.21.29.0.255",
    "1.0.41.29.0.255",
    "1.0.61.29.0.255",
    "1.0.2.29.0.255",
    "1.0.22.29.0.255",
    "1.0.42.29.0.255",
    "1.0.62.29.0.255",
    "1.0.3.29.0.255",
    "1.0.23.29.0.255",
    "1.0.43.29.0.255",
    "1.0.63.29.0.255",
    "1.0.4.29.0.255",
    "1.0.24.29.0.255",
    "1.0.44.29.0.255",
    "1.0.64.29.0.255",
    "1.0.32.27.0.255",
    "1.0.52.27.0.255",
    "1.0.72.27.0.255",
    "1.0.31.27.0.255",
    "1.0.51.27.0.255",
    "1.0.71.27.0.255",
    "1.0.32.24.124.255",
    "1.0.52.24.124.255",
    "1.0.72.24.124.255",
    "1.0.31.24.124.255",
    "1.0.51.24.124.255",
    "1.0.71.24.124.255",
    "1.0.13.27.0.255",
    "1.0.81.7.40.255",
    "1.0.81.7.51.255",
    "1.0.81.7.62.255",
]


def _billing_group(c: int, d: int, attr: int) -> list[tuple[str, int]]:
    """One ``C.D`` tariff group, E=0..8 — the shape every group in the
    billing capture list repeats nine times (F5)."""
    return [(f"1.0.{c}.{d}.{e}.255", attr) for e in range(9)]


#: Billing (``0.0.98.1.0.255``, Scheme 1) — capturePeriod 0 s, entries_in_use
#: 1, exactly 148 capture columns (F5, ``tcc-obis-scan.md``:719-868) — the
#: four identity columns, then sixteen ``C.D`` tariff groups of nine (E=0..8)
#: each, in the recorded wire order.
TCC_BILLING_LIVE: list[tuple[str, int]] = [
    (CLOCK_OBIS, 2),
    ("1.0.98.1.0.255", -1),  # PROFILE_GENERIC self-reference, as scanned (mirror OBIS, not 0.0.98.1.0.255)
    ("1.0.0.1.0.255", 2),  # billing-period counter
    ("1.0.0.1.2.255", 2),  # F6 near-miss — present, but UNSET/year-2000 in the buffer
    *_billing_group(1, 8, 2),  # energy import active
    *_billing_group(2, 8, 2),  # energy export active
    *_billing_group(1, 6, 2),  # max demand import active — value
    *_billing_group(2, 6, 2),  # max demand export active — value
    *_billing_group(1, 6, 5),  # max demand import active — capture time
    *_billing_group(2, 6, 5),  # max demand export active — capture time
    *_billing_group(1, 2, 2),  # cumulative demand import active
    *_billing_group(2, 2, 2),  # cumulative demand export active
    *_billing_group(3, 8, 2),  # energy import reactive
    *_billing_group(4, 8, 2),  # energy export reactive
    *_billing_group(3, 6, 2),  # max demand import reactive — value
    *_billing_group(4, 6, 2),  # max demand export reactive — value
    *_billing_group(3, 6, 5),  # max demand import reactive — capture time
    *_billing_group(4, 6, 5),  # max demand export reactive — capture time
    *_billing_group(3, 2, 2),  # cumulative demand import reactive
    *_billing_group(4, 2, 2),  # cumulative demand export reactive
]


class TestTheRecordedLayoutMatchesTheDocumentedColumnCounts:
    """Pins the two counts F3/F5 record, mirroring
    ``test_cewe_replay_parity.py::TestLiveCaptureListsMatchTheMeterNotes``."""

    def test_logger1_has_the_documented_35_columns(self) -> None:
        assert len(TCC_LOGGER1_LIVE) == 35  # tcc-obis-scan.md:649

    def test_billing_has_the_documented_148_columns(self) -> None:
        assert len(TCC_BILLING_LIVE) == 148  # tcc-obis-scan.md, F5


class TestEveryMappedColumnIsPresentInTheRecordedLayout:
    """The OBIS map this driver declares must be a subset of what the meter
    actually captures — a mapped column absent from the live list would
    silently resolve to ``None`` forever, which is a mapping bug, not the
    meter's doing (mirrors ``test_cewe_replay_parity.py``)."""

    def test_every_logger1_mapped_column_is_present_live(self) -> None:
        mapped_obis = {obis for obis, _attr in SmartTccDriver.LOAD_PROFILE_COLUMN_MAP[1]}
        missing = mapped_obis - set(TCC_LOGGER1_LIVE)
        assert not missing, f"SmartTccDriver logger 1 maps {missing}, absent from the recorded scan"

    def test_every_billing_mapped_column_is_present_live(self) -> None:
        live_keys = set(TCC_BILLING_LIVE)
        mapped = SmartTccDriver._mapped_billing_columns()  # noqa: SLF001
        from arichds.acquisition.drivers._dlms_profile import CEWE_DEMAND_TIME_COLUMNS

        all_mapped_keys = set(mapped) | set(CEWE_DEMAND_TIME_COLUMNS)
        missing = all_mapped_keys - live_keys
        assert not missing, f"SmartTccDriver billing maps {missing}, absent from the recorded scan"

    def test_the_declared_bill_date_candidate_is_present_live(self) -> None:
        assert set(SmartTccDriver.BILL_DATE_CANDIDATES) <= set(TCC_BILLING_LIVE)


# ─── Part 2 — the (OBIS, attribute) collision, replayed with synthetic values ──


class FakeTccReplayReader:
    """Replays :data:`TCC_BILLING_LIVE` verbatim, with synthetic row values
    supplied by position."""

    def __init__(self, row: list[Any], entries_in_use: int = 1) -> None:
        self._row = row
        self._entries_in_use = entries_in_use
        self.calls: list[tuple[str, int]] = []

    def read(self, obj: Any, attr: int) -> Any:
        if isinstance(obj, GXDLMSProfileGeneric):
            self.calls.append(("__profile__", attr))
            if attr == 3:
                obj.captureObjects = [
                    (SimpleNamespace(logicalName=obis), SimpleNamespace(attributeIndex=a))
                    for obis, a in TCC_BILLING_LIVE
                ]
                return obj.captureObjects
            if attr == 7:
                return self._entries_in_use
            raise AssertionError(f"unexpected ProfileGeneric attr {attr}")

        obis = str(obj.logicalName)
        self.calls.append((obis, attr))
        if attr == 3:
            # F10 — every energy/demand register reported exponent 0 on the
            # real meter, so multiplier 1.0 for everything replayed here.
            # ``GXDLMSExtendedRegister`` subclasses ``GXDLMSRegister``, so the
            # exact-type check (not ``isinstance``) is what actually tells
            # the D=6/D=2 (power) groups apart from the D=8 (energy) group —
            # only the one OBIS this test asserts on (the max-demand group)
            # needs to resolve; every other column is free to stay None,
            # matching F10's real "most, not all, resolve" outcome.
            obj.scaler = 1.0
            obj.unit = Unit.ACTIVE_ENERGY if type(obj) is GXDLMSRegister else Unit.ACTIVE_POWER
            return None
        if attr == 2 and obis == SmartTccDriver.METER_SERIAL_OBIS[0]:
            return "SN-TCC-3CL"
        raise AssertionError(f"unexpected attr {attr} for {obis}")

    def readRowsByEntry(self, pg: Any, index: int, count: int) -> list[list[Any]]:  # noqa: N802
        self.calls.append(("__rows__", index))
        return [self._row][index - 1 : index - 1 + count]


def _synthetic_row() -> list[Any]:
    """One synthetic billing row, aligned to :data:`TCC_BILLING_LIVE` — every
    cell defaults to ``None`` except the four identity columns and one
    max-demand group (``1.0.1.6.0.255``), which carries a distinct value at
    attr 2 and a distinct capture time at attr 5 (F2's collision)."""
    row: list[Any] = [None] * len(TCC_BILLING_LIVE)
    row[TCC_BILLING_LIVE.index((CLOCK_OBIS, 2))] = datetime(2026, 7, 14, 16, 0)
    row[TCC_BILLING_LIVE.index(("1.0.0.1.0.255", 2))] = 1
    row[TCC_BILLING_LIVE.index(("1.0.0.1.2.255", 2))] = datetime(2000, 1, 1, 0, 0)  # F6 — UNSET, unused
    row[TCC_BILLING_LIVE.index(("1.0.1.6.0.255", 2))] = 123.0  # the max-demand VALUE
    row[TCC_BILLING_LIVE.index(("1.0.1.6.0.255", 5))] = datetime(2026, 8, 5, 9, 12, 0)  # its capture TIME
    return row


def _build_driver(reader: FakeTccReplayReader) -> SmartTccDriver:
    driver = SmartTccDriver(ConnectionParams.net("203.170.148.103", 4059), password="")
    driver._reader = reader  # noqa: SLF001
    driver._client = SimpleNamespace(objects=[])  # noqa: SLF001
    return driver


class TestTheMaxDemandValueAndItsCaptureTimeLandInDifferentFields:
    """F2's collision, replayed against the full recorded 148-column layout —
    the strongest form of D12 part 2's claim."""

    def test_the_value_is_scaled_and_the_time_is_not(self) -> None:
        reader = FakeTccReplayReader(_synthetic_row())
        driver = _build_driver(reader)

        readings = driver.read_billing()

        assert len(readings) == 1
        row = readings[0]
        # The value column: divided by WH_TO_KWH_DIVISOR like every other
        # billing number (D11) — 123.0 W -> 0.123 kW.
        assert row.max_demand_import_active_kw_total == pytest.approx(0.123)
        # The time column: converted meter-local -> UTC, never scaled.
        assert row.max_demand_import_active_time_total == datetime(2026, 8, 5, 2, 12, 0, tzinfo=UTC)

    def test_bill_date_converts_from_the_clock_column_correctly(self) -> None:
        reader = FakeTccReplayReader(_synthetic_row())
        driver = _build_driver(reader)

        readings = driver.read_billing()

        # D12 part 3 — the pinned recorded value: 2026-07-14 16:00
        # meter-local (UTC+7) -> 2026-07-14T09:00:00+00:00.
        assert readings[0].bill_date == datetime(2026, 7, 14, 9, 0, tzinfo=UTC)


# ─── Part 3 — the values the scan actually recorded ────────────────────────────


class FakeTccLoggerReader:
    """Replays Logger 1's recorded shape (:data:`TCC_LOGGER1_LIVE`) with the
    recorded ``capturePeriod`` (900 s, F3) — read live through
    :meth:`SmartTccDriver.read_load_profile`, never assumed, matching every
    other DlmsProfileDriver read path (D7)."""

    def __init__(self, capture_period_sec: int, row: list[Any]) -> None:
        self._capture_period_sec = capture_period_sec
        self._row = row

    def read(self, obj: Any, attr: int) -> Any:
        assert isinstance(obj, GXDLMSProfileGeneric)
        if attr == 3:
            # The profile self-reference is recorded at attr -1 (PROFILE_GENERIC,
            # tcc-obis-scan.md:651); every other column is attr 2 — unmapped
            # either way, but faithful to the scan rather than a blanket 2.
            obj.captureObjects = [
                (
                    SimpleNamespace(logicalName=obis),
                    SimpleNamespace(attributeIndex=-1 if obis == "1.0.99.1.0.255" else 2),
                )
                for obis in TCC_LOGGER1_LIVE
            ]
            return obj.captureObjects
        if attr == 4:
            return self._capture_period_sec
        raise AssertionError(f"unexpected ProfileGeneric attr {attr}")

    def readRowsByRange(self, pg: Any, start: datetime, end: datetime) -> list[list[Any]]:  # noqa: N802
        return [self._row]


class TestTheRecordedFieldValues:
    """D12 part 3 — every value the 2026-07-18 field scan actually recorded,
    pinned directly against production behaviour (not restated as a
    tautology): 148/35 column counts (pinned above against
    ``LOAD_PROFILE_COLUMN_MAP``/``_mapped_billing_columns()``), Logger 1's
    live-read capture period, ``entries_in_use`` flowing through to the
    returned row count, and the bill-date conversion arithmetic."""

    def test_logger1_capture_period_flows_through_to_interval_sec(self) -> None:
        row = [None] * len(TCC_LOGGER1_LIVE)
        row[TCC_LOGGER1_LIVE.index("0.0.1.0.0.255")] = datetime(2026, 8, 7, 11, 0)
        driver = SmartTccDriver(ConnectionParams.net("203.170.148.103", 4059), password="")
        driver._reader = FakeTccLoggerReader(900, row)  # noqa: SLF001
        driver._client = SimpleNamespace(objects=[])  # noqa: SLF001

        readings = driver.read_load_profile(
            1, datetime(2026, 8, 7, 4, 0, tzinfo=UTC), datetime(2026, 8, 7, 5, 0, tzinfo=UTC)
        )

        assert len(readings) == 1
        assert readings[0].interval_sec == 900  # tcc-obis-scan.md:649 — capturePeriod: 900 s, read live

    def test_entries_in_use_of_one_returns_exactly_one_row(self) -> None:
        """tcc-obis-scan.md:597,720 — the scanned 3CL held one real cut."""
        reader = FakeTccReplayReader(_synthetic_row(), entries_in_use=1)
        driver = _build_driver(reader)

        readings = driver.read_billing()

        assert len(readings) == 1

    def test_the_recorded_bill_date_converts_meter_local_to_utc_correctly(self) -> None:
        from arichds.acquisition.drivers._profile import meter_local_to_utc

        recorded_local = datetime(2026, 7, 14, 16, 0)  # tcc-obis-scan.md:597 — 14/07/2026 16:00
        assert meter_local_to_utc(recorded_local) == datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
