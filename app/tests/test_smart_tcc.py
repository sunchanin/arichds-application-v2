"""``acquisition.drivers.smart_tcc.SmartTccDriver`` — one driver for all five
SMART TCC models, on the encrypted (HighGMAC + Suite 0) path (M4c issue #25).

D1 governs every test in this file and in ``test_smart_tcc_replay.py``: the
meter is never reached. Every reader here is a fake reproducing the recorded
scan (``docs/meter-notes/tcc-obis-scan.md``), never a socket.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from gurux_dlms.enums import Unit
from gurux_dlms.objects import GXDLMSExtendedRegister, GXDLMSProfileGeneric, GXDLMSRegister

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.smart_tcc import SmartTccDriver

CLOCK_OBIS = "0.0.1.0.0.255"
CEWE_BILL_DATE_OBIS = "0.0.0.1.2.255"
TCC_NEAR_MISS_OBIS = "1.0.0.1.2.255"  # F6 — present, but UNSET/year-2000 in the buffer, unusable
BILLING_COUNTER_OBIS = "1.0.0.1.0.255"
DEMAND_C1_E0 = "1.0.1.6.0.255"


class TestProtocolArgsArePinned:
    """F1 — the argv order is load-bearing (v1 ``smart_tcc.py:166-215``,
    proven against the real 3CL meter). ``-s`` must precede ``-l`` (F1,
    ``GXSettings.py:343-349``: ``-l`` combines with whatever ``serverAddress``
    ``-s`` already set), and ``-P`` must be entirely absent — HighGMAC is
    keyless (F1)."""

    def _driver(self) -> SmartTccDriver:
        return SmartTccDriver(ConnectionParams.net("203.170.148.103", 4059), password="unused")

    def test_the_full_argv_matches_the_proven_v1_order_exactly(self) -> None:
        driver = self._driver()

        args = driver._protocol_args()  # noqa: SLF001

        assert args == [
            "-i",
            "HDLC",
            "-r",
            "ln",
            "-c",
            "1",
            "-s",
            "127",
            "-l",
            "127",
            "-a",
            "HighGMac",
            "-C",
            "AuthenticationEncryption",
            "-V",
            "Suite0",
            "-T",
            "4142434445464748",
            "-A",
            "D0D1D2D3D4D5D6D7D8D9DADBDCDDDEDF",
            "-B",
            "000102030405060708090A0B0C0D0E0F",
            "-v",
            "0.0.43.1.0.255",
            "-t",
            "Error",
        ]

    def test_s_precedes_l(self) -> None:
        args = self._driver()._protocol_args()  # noqa: SLF001
        assert args.index("-s") < args.index("-l")

    def test_no_password_flag_is_present(self) -> None:
        """HighGMAC carries no LLS password — must never emit ``-P``, unlike
        every CEWE model."""
        args = self._driver()._protocol_args()  # noqa: SLF001
        assert "-P" not in args

    def test_the_password_kwarg_is_absorbed_and_never_reaches_the_argv(self) -> None:
        driver = SmartTccDriver(
            ConnectionParams.net("203.170.148.103", 4059),
            password="D0D1D2D3D4D5D6D7D8D9DADBDCDDDEDF-should-never-appear",
        )
        args = driver._protocol_args()  # noqa: SLF001
        assert "D0D1D2D3D4D5D6D7D8D9DADBDCDDDEDF-should-never-appear" not in args

    def test_the_full_build_args_puts_transport_before_protocol_flags(self) -> None:
        """``_build_args()`` composes script + transport (``-h/-p``) +
        protocol flags — the transport fragment must come first, from
        ``ConnectionParams``, not duplicated here."""
        driver = self._driver()
        full_args = driver._build_args()  # noqa: SLF001
        assert full_args[1:5] == ["-h", "203.170.148.103", "-p", "4059"]
        assert full_args[5:] == driver._protocol_args()  # noqa: SLF001


class TestModelNameIsTheFamilyName:
    """D2 — ``model_name`` returns the family name, deliberately not any of
    the five catalog keys, because one class serves five models."""

    def test_model_name_is_smart_tcc(self) -> None:
        driver = SmartTccDriver(ConnectionParams.net("203.170.148.103", 4059), password="")
        assert driver.model_name == "smart_tcc"


class TestReadTimeoutAndInterFrameDelay:
    """F1 — 90 s read timeout, 500 ms inter-frame delay."""

    def test_read_timeout_is_90_seconds_in_milliseconds(self) -> None:
        driver = SmartTccDriver(ConnectionParams.net("203.170.148.103", 4059), password="")
        assert driver._read_timeout_ms() == 90_000  # noqa: SLF001

    def test_inter_frame_delay_is_500ms(self) -> None:
        driver = SmartTccDriver(ConnectionParams.net("203.170.148.103", 4059), password="")
        assert driver.get_inter_frame_delay_ms() == 500


class TestGetObisMapReturnsTheInstantaneousSet:
    """D10 — same shared, field-proven map as the three CEWE leaves."""

    def test_returns_the_shared_instantaneous_obis_map(self) -> None:
        from arichds.acquisition.obis import INSTANTANEOUS_OBIS

        driver = SmartTccDriver(ConnectionParams.net("203.170.148.103", 4059), password="")
        assert driver.get_obis_map() == dict(INSTANTANEOUS_OBIS)


class TestLoadProfileLogger1ColumnMap:
    """D7/D8 — Logger 1 only, 11 mapped columns out of the 35 the scan
    recorded."""

    def test_only_logger_1_is_declared(self) -> None:
        assert set(SmartTccDriver.LOAD_PROFILE_COLUMN_MAP) == {1}

    def test_logger_1_has_exactly_the_eleven_documented_columns(self) -> None:
        columns = SmartTccDriver.LOAD_PROFILE_COLUMN_MAP[1]
        expected_fields = {
            "import_active_kwh",
            "export_active_kwh",
            "import_reactive_kvarh",
            "export_reactive_kvarh",
            "volt_l1",
            "volt_l2",
            "volt_l3",
            "current_l1",
            "current_l2",
            "current_l3",
            "avg_geo_pf",
        }
        actual_fields = {field for field, _sibling, _unit in columns.values()}
        assert actual_fields == expected_fields

    def test_frequency_maps_to_nothing(self) -> None:
        """F3 — Logger 1 has no frequency capture column on this family."""
        columns = SmartTccDriver.LOAD_PROFILE_COLUMN_MAP[1]
        actual_fields = {field for field, _sibling, _unit in columns.values()}
        assert "freq" not in actual_fields

    def test_supports_load_profile_is_true(self) -> None:
        driver = SmartTccDriver(ConnectionParams.net("203.170.148.103", 4059), password="")
        assert driver.supports_load_profile() is True
        assert driver.load_profile_loggers() == (1,)


class TestTheFourD5Declarations:
    """D5 — SmartTccDriver's own values for the four per-driver seams."""

    def test_billing_profile_obis_is_scheme_1(self) -> None:
        """F5/F8 — Scheme 1. The Scheme-2 exclusion itself (never a bill cut)
        is discriminated by ``TestScheme2IsNeverRead`` below, which drives a
        real read rather than a static inequality."""
        assert SmartTccDriver.BILLING_PROFILE_OBIS == "0.0.98.1.0.255"

    def test_bill_date_candidates_is_clock_only(self) -> None:
        """F6 — CEWE's own bill-date column is absent from TCC's capture
        list; the near-miss ``1.0.0.1.2.255`` reads UNSET. Only Clock works."""
        assert SmartTccDriver.BILL_DATE_CANDIDATES == ((CLOCK_OBIS, 2),)

    def test_reset_reason_key_is_declared_absent(self) -> None:
        """F7 — no reset-reason register on this family."""
        assert SmartTccDriver.RESET_REASON_KEY is None

    def test_cumulative_demand_cosem_class_is_register(self) -> None:
        """F9 — Register on TCC, unlike CEWE's ExtendedRegister."""
        assert SmartTccDriver.CUMUL_DEMAND_COSEM_CLASS is GXDLMSRegister
        mapped = SmartTccDriver._mapped_billing_columns()  # noqa: SLF001
        _field, cumul_class, _unit = mapped[("1.0.1.2.0.255", 2)]
        _field, demand_class, _unit = mapped[(DEMAND_C1_E0, 2)]
        assert cumul_class is GXDLMSRegister
        assert demand_class is GXDLMSExtendedRegister  # F9 — D=6 unaffected, matches CEWE


class FakeTccBillingReader:
    """Reproduces the ``GXDLMSReader`` subset ``read_billing()`` calls,
    replaying the recorded TCC billing capture list (F5)."""

    def __init__(
        self,
        capture_objects: list[tuple[str, int]],
        entries_in_use: int,
        buffer: list[list[Any]],
        scalers: dict[str, tuple[float, Unit]] | None = None,
        meter_serial: str | None = "SN-TCC-1",
    ) -> None:
        self._capture_objects = capture_objects
        self._entries_in_use = entries_in_use
        self._buffer = buffer
        self._scalers = scalers or {}
        self._meter_serial = meter_serial
        self.calls: list[tuple[str, int]] = []
        self.opened_profile_obis: str | None = None

    def read(self, obj: Any, attr: int) -> Any:
        if isinstance(obj, GXDLMSProfileGeneric):
            self.opened_profile_obis = str(obj.logicalName)
            self.calls.append((self.opened_profile_obis, attr))
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
            multiplier, unit = self._scalers.get(obis, (1.0, Unit.NONE))
            obj.scaler = multiplier
            obj.unit = unit
            return None
        if attr == 2 and obis == SmartTccDriver.METER_SERIAL_OBIS[0]:
            return self._meter_serial
        raise AssertionError(f"unexpected attr {attr} for {obis}")

    def readRowsByEntry(self, pg: Any, index: int, count: int) -> list[list[Any]]:  # noqa: N802
        self.calls.append(("__rows__", index))
        return self._buffer[index - 1 : index - 1 + count]


def _build_driver(reader: FakeTccBillingReader) -> SmartTccDriver:
    driver = SmartTccDriver(ConnectionParams.net("203.170.148.103", 4059), password="")
    driver._reader = reader  # noqa: SLF001
    driver._client = SimpleNamespace(objects=[])  # noqa: SLF001
    return driver


def _minimal_billing_capture_list() -> list[tuple[str, int]]:
    """The four identity columns every real capture (F5, ``tcc-obis-scan.md``
    719-724) opens with, before the 144 measurement columns."""
    return [
        (CLOCK_OBIS, 2),
        ("0.0.98.1.0.255", -1),
        (BILLING_COUNTER_OBIS, 2),
        (TCC_NEAR_MISS_OBIS, 2),
    ]


class TestBillDateComesFromClockNotTheNearMiss:
    """F6 — the recorded field distinction: Clock reads the real date on
    every row; ``1.0.0.1.2.255`` is present but UNSET/year-2000 in the
    buffer. This is the mutation-detectable version of D12 part 3's pinned
    value (2026-07-14 16:00 meter-local -> 09:00 UTC)."""

    def test_bill_date_resolves_from_the_clock_column(self) -> None:
        columns = _minimal_billing_capture_list()
        reader = FakeTccBillingReader(
            columns,
            entries_in_use=1,
            buffer=[[datetime(2026, 7, 14, 16, 0), None, 1, datetime(2000, 1, 1, 0, 0)]],
        )
        driver = _build_driver(reader)

        readings = driver.read_billing()

        assert len(readings) == 1
        assert readings[0].bill_date == datetime(2026, 7, 14, 9, 0, tzinfo=UTC)


class TestOpenClosedPositionalFallbackIsSilent:
    """D5/F7 — TCC declares no reset-reason register; entry 0 is open by
    position, and no "reset-reason" WARNing fires (unlike a CEWE model whose
    declared key is merely absent from one read)."""

    def test_entry_zero_is_open_with_no_reset_reason_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        columns = _minimal_billing_capture_list()
        reader = FakeTccBillingReader(
            columns,
            entries_in_use=1,
            buffer=[[datetime(2026, 7, 14, 16, 0), None, 1, datetime(2000, 1, 1, 0, 0)]],
        )
        driver = _build_driver(reader)

        with caplog.at_level("WARNING"):
            readings = driver.read_billing()

        assert readings[0].is_open is True
        assert not any("reset-reason" in record.message.lower() for record in caplog.records)


class TestScheme2IsNeverRead:
    """F8 — Scheme 2 (``0.0.98.2.0.255``) is a daily snapshot, never a bill
    cut, and is not reachable from this driver at all."""

    def test_read_billing_opens_scheme_1_not_scheme_2(self) -> None:
        columns = _minimal_billing_capture_list()
        reader = FakeTccBillingReader(columns, entries_in_use=1, buffer=[[datetime(2026, 7, 14, 16, 0), None, 1, None]])
        driver = _build_driver(reader)

        driver.read_billing()

        assert reader.opened_profile_obis == "0.0.98.1.0.255"
        assert reader.opened_profile_obis != "0.0.98.2.0.255"
