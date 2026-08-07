"""The DLMS scaler and the Wh→kWh division — locked by test (SPEC §3.4).

Two invariants live here, and both are one careless edit away from silently
moving every energy number by a decade:

**1. scaler_unit (attr 3) is read BEFORE the value (attr 2).**
In Gurux Python, reading attr 3 populates ``obj.scaler`` with the *multiplier*
(``10**exponent``), and ``GXDLMSRegister.setValue`` then applies it when attr 2
is parsed. Read them the other way round and attr 2 is parsed with the default
multiplier of 1, yielding a raw, unscaled integer.

v1 did exactly that and then "corrected" it with ``10 ** int(obj.scaler)`` —
treating the multiplier as an exponent. At exponent 0 that is ``int(1.0) == 1``,
a phantom ×10, which a compensating ÷10000 elsewhere cancelled back out
(v1 ADR 0010). SPEC §3.4 says to write the scaler correctly from the start and
not carry that pair over; ADR 0002 records the reversal. These tests are what
stop it creeping back.

**2. Energy is divided to kWh at write time, in the driver.**
``load_profile_readings`` is always kWh (REMAKE-PLAN §6.1) and column names
match the unit stored. V/I/frequency are already in engineering units and must
NOT be divided.

No hardware needed: a fake reader reproduces Gurux's scaler semantics exactly.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms import DlmsDriver

VOLT_L1_OBIS = "1.0.32.7.0.255"
IMPORT_OBIS = "1.0.1.8.0.255"


class FakeGuruxReader:
    """Reproduces ``GXDLMSReader.read`` for Register objects, scaler and all.

    Mirrors the real semantics precisely, because that is what is under test:

    * ``read(obj, 3)`` sets ``obj.scaler = 10**exponent`` (a MULTIPLIER).
    * ``read(obj, 2)`` returns ``raw * obj.scaler`` — Gurux applies the
      multiplier inside ``setValue``, so a value read before the scaler comes
      back unscaled (multiplier still 1).

    Attributes:
        calls: Every ``(obis, attr)`` in order — lets a test assert the ordering
            directly, not just its arithmetic consequence.
    """

    def __init__(
        self,
        raw_values: dict[str, Any],
        exponents: dict[str, int] | None = None,
        unreadable_scalers: set[str] | None = None,
    ) -> None:
        self.raw_values = raw_values
        self.exponents = exponents or {}
        self.unreadable_scalers = unreadable_scalers or set()
        self.calls: list[tuple[str, int]] = []

    def read(self, obj: Any, attr: int) -> Any:
        obis = str(obj.logicalName)
        self.calls.append((obis, attr))

        if attr == 3:
            if obis in self.unreadable_scalers:
                raise RuntimeError("meter refused scaler_unit")
            obj.scaler = math.pow(10, self.exponents.get(obis, 0))
            return None

        if attr == 2:
            raw = self.raw_values[obis]
            if not isinstance(raw, (int, float)):
                return raw
            return raw * obj.scaler

        raise AssertionError(f"unexpected attribute {attr}")


class ScalerTestDriver(DlmsDriver):
    """A concrete DlmsDriver wired to a fake reader instead of a socket."""

    def __init__(self, reader: FakeGuruxReader) -> None:
        super().__init__(ConnectionParams.net("198.51.100.7", 4059), password="secret")
        self._reader = reader
        self._client = SimpleNamespace(objects=[])

    @property
    def model_name(self) -> str:
        return "scaler-test"

    def _protocol_args(self) -> list[str]:
        return []

    def _read_timeout_ms(self) -> int:
        return 1000

    def get_obis_map(self) -> dict[str, tuple[str, int]]:
        return {"volt_l1": (VOLT_L1_OBIS, 2), "import_active_kwh": (IMPORT_OBIS, 2)}


def build(raw_values, exponents=None, unreadable=None) -> tuple[ScalerTestDriver, FakeGuruxReader]:
    """Build a driver over a fake reader, returning both."""
    reader = FakeGuruxReader(raw_values, exponents, unreadable)
    return ScalerTestDriver(reader), reader


class TestScalerReadOrder:
    """Attr 3 before attr 2 — the ordering the whole scheme rests on."""

    def test_scaler_is_read_before_the_value(self) -> None:
        driver, reader = build({VOLT_L1_OBIS: 240.0})

        driver.read_register(VOLT_L1_OBIS, 2)

        assert reader.calls == [(VOLT_L1_OBIS, 3), (VOLT_L1_OBIS, 2)], (
            "scaler_unit must be read first so Gurux applies the multiplier to the value"
        )

    def test_negative_exponent_is_applied(self) -> None:
        """The case that catches a reordering: raw 240000 at 10^-3 is 240 V.

        Reverse the two reads and this returns 240000 — a 1000x error that no
        other assertion in the suite would notice.
        """
        driver, _ = build({VOLT_L1_OBIS: 240_000}, exponents={VOLT_L1_OBIS: -3})

        assert driver.read_register(VOLT_L1_OBIS, 2) == pytest.approx(240.0)

    def test_positive_exponent_is_applied(self) -> None:
        driver, _ = build({VOLT_L1_OBIS: 24}, exponents={VOLT_L1_OBIS: 1})

        assert driver.read_register(VOLT_L1_OBIS, 2) == pytest.approx(240.0)

    def test_exponent_zero_passes_the_value_through(self) -> None:
        """The deployed Prometer 100 fleet reports exponent 0 on every register.

        Verified live 2026-08-04 against 203.170.151.152 via
        ``scripts/probe_meter.py --show-scaler``.
        """
        driver, _ = build({VOLT_L1_OBIS: 239.77}, exponents={VOLT_L1_OBIS: 0})

        assert driver.read_register(VOLT_L1_OBIS, 2) == pytest.approx(239.77)

    def test_no_phantom_multiplication_at_exponent_zero(self) -> None:
        """v1's bug, pinned: ``10 ** int(multiplier)`` gave a phantom x10."""
        driver, _ = build({VOLT_L1_OBIS: 239.77}, exponents={VOLT_L1_OBIS: 0})

        value = driver.read_register(VOLT_L1_OBIS, 2)

        assert value == pytest.approx(239.77)
        assert value != pytest.approx(2397.7)

    def test_unreadable_scaler_falls_back_to_multiplier_one(self) -> None:
        """A refused scaler must not scale — never guess an exponent."""
        driver, _ = build({VOLT_L1_OBIS: 240.0}, unreadable={VOLT_L1_OBIS})

        assert driver.read_register(VOLT_L1_OBIS, 2) == pytest.approx(240.0)

    def test_disconnected_driver_returns_none(self) -> None:
        driver, _ = build({VOLT_L1_OBIS: 240.0})
        driver._reader = None

        assert driver.read_register(VOLT_L1_OBIS, 2) is None


class TestWhToKwhNormalization:
    """Energy is divided at write time, in the driver (REMAKE-PLAN §6.1)."""

    def test_energy_column_is_divided_to_kwh(self) -> None:
        driver, _ = build({VOLT_L1_OBIS: 240.0, IMPORT_OBIS: 5_000})

        assert driver._normalize("import_active_kwh", 5_000) == pytest.approx(5.0)

    def test_field_value_converts_to_the_expected_kwh(self) -> None:
        """The real register read from the field meter, 2026-08-04."""
        driver, _ = build({IMPORT_OBIS: 149_643_850.176})

        assert driver._normalize("import_active_kwh", 149_643_850.176) == pytest.approx(149_643.850176)

    @pytest.mark.parametrize("column", ["volt_l1", "volt_l3", "current_l2", "freq"])
    def test_non_energy_columns_are_never_divided(self, column: str) -> None:
        driver, _ = build({VOLT_L1_OBIS: 240.0})

        assert driver._normalize(column, 240.0) == pytest.approx(240.0)

    def test_decimal_values_are_coerced_to_float(self) -> None:
        from decimal import Decimal

        driver, _ = build({IMPORT_OBIS: 1000})

        result = driver._normalize("import_active_kwh", Decimal("1000"))
        assert isinstance(result, float)
        assert result == pytest.approx(1.0)

    def test_none_stays_none(self) -> None:
        driver, _ = build({})

        assert driver._normalize("volt_l1", None) is None

    def test_non_numeric_becomes_none(self) -> None:
        """A GXDateTime in a measurement column is stored as NULL, not coerced."""
        driver, _ = build({})

        assert driver._normalize("volt_l1", object()) is None


class TestScalerEndToEnd:
    """Scaler + normalization together, over the driver's real read path.

    These three used to run through the driver's instantaneous read, which
    ADR 0007 deleted (issue #8, M3-4). They now go through ``read_register()``
    and ``_normalize()`` — the two halves that method used to chain — so
    ADR 0002's coverage did not shrink to pay for the removal. Only one
    assertion was dropped: the old ``read_at.tzinfo is not None``, which pinned
    the deleted method's own timestamp rather than anything about the scaler,
    and which no production code can produce again until M5's load-profile
    writer.
    """

    def test_scaler_and_kwh_apply_over_the_read_path(self) -> None:
        driver, _ = build(
            {VOLT_L1_OBIS: 239.77, IMPORT_OBIS: 149_643_850.176},
            exponents={VOLT_L1_OBIS: 0, IMPORT_OBIS: 0},
        )

        assert driver._normalize("volt_l1", driver.read_register(VOLT_L1_OBIS, 2)) == pytest.approx(239.77)
        assert driver._normalize("import_active_kwh", driver.read_register(IMPORT_OBIS, 2)) == pytest.approx(
            149_643.850176
        )

    def test_scaled_energy_is_divided_once_not_twice(self) -> None:
        """Raw 149_643_850_176 at 10^-3 Wh is still 149_643.850176 kWh.

        The load-bearing case: the scaler multiplies (to Wh) and the driver
        divides (to kWh), and each must happen exactly once. Both halves are
        asserted so a regression says which one moved.
        """
        driver, _ = build(
            {VOLT_L1_OBIS: 239.77, IMPORT_OBIS: 149_643_850_176},
            exponents={IMPORT_OBIS: -3},
        )

        scaled = driver.read_register(IMPORT_OBIS, 2)

        assert scaled == pytest.approx(149_643_850.176)
        assert driver._normalize("import_active_kwh", scaled) == pytest.approx(149_643.850176)

    def test_a_failing_register_propagates(self) -> None:
        """A register the meter refuses raises out of ``read_register``.

        This replaces the old degrade-to-``None`` case, whose loop lived inside
        the deleted instantaneous read and died with it. Propagating is now the
        contract the Poller depends on: ``poll_once`` marks the tick FAILED off
        exactly this exception, which is how a meter that accepts an association
        but cannot serve a register avoids being reported Online (ADR 0007).
        """

        class ExplodingReader(FakeGuruxReader):
            def read(self, obj: Any, attr: int) -> Any:
                if str(obj.logicalName) == VOLT_L1_OBIS:
                    raise RuntimeError("undefined object")
                return super().read(obj, attr)

        driver = ScalerTestDriver(ExplodingReader({IMPORT_OBIS: 1_000}))

        with pytest.raises(RuntimeError, match="undefined object"):
            driver.read_register(VOLT_L1_OBIS, 2)
