"""The eleven Load Profile columns that used to be read and discarded
(M13, issue 06).

Every one of these values already arrived in the buffer the product reads each
cycle; the driver's column map simply had nowhere to put them. This module
replays the **live capture lists**, read off the real meters on 2026-09-09 by
``scripts/probe_capture_objects.py``, and asserts the eleven land where they
belong.

Why the fake denies every own-address scaler read
-------------------------------------------------
Because the meters do. Confirmed on all twelve targets on 2026-09-09, and on
the whole measurement set on 2026-08-09 before that: a CEWE load-profile column
never answers ``scaler_unit`` at its own address, so the sibling is the only
path. A fake that answered the own address would prove the resolver works in a
world this product does not run in.

Why every cell carries a different number
-----------------------------------------
The failure mode this ticket designs against is not a wrong magnitude, it is a
**silently empty column** — every scaler on the reference meter is ``1.0``, so
a scaler that fails to resolve yields ``None`` rather than a visibly wrong
number, which is exactly how ``avg_geo_pf`` stayed empty for 87,000 rows
(issue 05). Distinct per-cell values mean a transposition between two columns
of the same quantity fails here rather than shipping.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from gurux_dlms.enums import Unit
from gurux_dlms.objects import GXDLMSExtendedRegister, GXDLMSProfileGeneric, GXDLMSRegister

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.premier550 import Premier550Driver
from arichds.acquisition.drivers.prometer100 import Prometer100Driver
from arichds.acquisition.drivers.saral305 import Saral305Driver
from arichds.acquisition.drivers.smart_tcc import SmartTccDriver

CLOCK = ("0.0.1.0.0.255", 2)

#: Prometer 100 Logger 1, exactly as the meter reported it on 2026-09-09
#: (``scripts/probe_capture_objects.py`` against ``WP079074``): 25 columns,
#: 900 s. **The four power columns are captured at attribute 3 of a class-5
#: Demand Register** — attribute 3 there is `last_average_value`, the average
#: over the closed demand interval, which is the quantity the customer asked
#: for. Everything else is attribute 2.
PROMETER_LOGGER1_LIVE: tuple[tuple[str, int], ...] = (
    CLOCK,
    ("1.0.1.29.0.255", 2),
    ("1.0.2.29.0.255", 2),
    ("1.0.3.29.0.255", 2),
    ("1.0.4.29.0.255", 2),
    ("1.0.96.5.4.255", 2),
    ("1.0.1.5.0.255", 3),
    ("1.0.2.5.0.255", 3),
    ("1.0.3.5.0.255", 3),
    ("1.0.4.5.0.255", 3),
    ("1.0.32.27.0.255", 2),
    ("1.0.52.27.0.255", 2),
    ("1.0.72.27.0.255", 2),
    ("1.0.31.27.0.255", 2),
    ("1.0.51.27.0.255", 2),
    ("1.0.71.27.0.255", 2),
    ("1.0.33.27.0.255", 2),
    ("1.0.53.27.0.255", 2),
    ("1.0.73.27.0.255", 2),
    ("1.0.13.24.0.255", 2),
    ("1.0.81.27.4.255", 2),
    ("1.0.81.27.15.255", 2),
    ("1.0.81.27.26.255", 2),
    ("1.0.14.27.0.255", 2),
    ("1.0.81.24.128.255", 2),
)

#: Prometer 100 Logger 2 — 8 columns, 300 s. The three line-to-line voltages
#: live here, not in Logger 1.
PROMETER_LOGGER2_LIVE: tuple[tuple[str, int], ...] = (
    CLOCK,
    ("1.0.157.27.0.255", 2),
    ("1.0.177.27.0.255", 2),
    ("1.0.197.27.0.255", 2),
    ("1.0.11.132.0.255", 2),
    ("1.0.11.132.124.255", 2),
    ("1.0.12.132.124.255", 2),
    ("1.0.14.27.0.255", 2),
)

#: Premier 550 Logger 1 — 7 columns, 900 s. Of the eleven it records only the
#: status word.
PREMIER_LOGGER1_LIVE: tuple[tuple[str, int], ...] = (
    CLOCK,
    ("1.0.96.71.0.255", 2),
    ("1.0.96.5.4.255", 2),
    ("1.0.1.29.0.255", 2),
    ("1.0.2.29.0.255", 2),
    ("1.0.3.29.0.255", 2),
    ("1.0.4.29.0.255", 2),
)

#: What each sibling answers with, measured 2026-09-09. Note the two export
#: power columns: their D=7 siblings are **denied**, and their max-demand
#: siblings answer only when read as an Extended Register. Every multiplier on
#: this meter is 1.0.
MEASURED_SIBLINGS: dict[tuple[str, type], tuple[float, Unit]] = {
    ("1.0.81.7.4.255", GXDLMSRegister): (1.0, Unit.PHASE_ANGLE_DEGREE),
    ("1.0.81.7.15.255", GXDLMSRegister): (1.0, Unit.PHASE_ANGLE_DEGREE),
    ("1.0.81.7.26.255", GXDLMSRegister): (1.0, Unit.PHASE_ANGLE_DEGREE),
    ("1.0.157.7.0.255", GXDLMSRegister): (1.0, Unit.VOLTAGE),
    ("1.0.177.7.0.255", GXDLMSRegister): (1.0, Unit.VOLTAGE),
    ("1.0.197.7.0.255", GXDLMSRegister): (1.0, Unit.VOLTAGE),
    ("1.0.1.7.0.255", GXDLMSRegister): (1.0, Unit.ACTIVE_POWER),
    ("1.0.3.7.0.255", GXDLMSRegister): (1.0, Unit.REACTIVE_POWER),
    ("1.0.2.6.0.255", GXDLMSExtendedRegister): (1.0, Unit.ACTIVE_POWER),
    ("1.0.4.6.0.255", GXDLMSExtendedRegister): (1.0, Unit.REACTIVE_POWER),
    # The pre-existing fourteen, so the replay produces a complete row.
    ("1.0.1.8.0.255", GXDLMSRegister): (1.0, Unit.ACTIVE_ENERGY),
    ("1.0.2.8.0.255", GXDLMSRegister): (1.0, Unit.ACTIVE_ENERGY),
    ("1.0.3.8.0.255", GXDLMSRegister): (1.0, Unit.REACTIVE_ENERGY),
    ("1.0.4.8.0.255", GXDLMSRegister): (1.0, Unit.REACTIVE_ENERGY),
    ("1.0.32.7.0.255", GXDLMSRegister): (1.0, Unit.VOLTAGE),
    ("1.0.52.7.0.255", GXDLMSRegister): (1.0, Unit.VOLTAGE),
    ("1.0.72.7.0.255", GXDLMSRegister): (1.0, Unit.VOLTAGE),
    ("1.0.31.7.0.255", GXDLMSRegister): (1.0, Unit.CURRENT),
    ("1.0.51.7.0.255", GXDLMSRegister): (1.0, Unit.CURRENT),
    ("1.0.71.7.0.255", GXDLMSRegister): (1.0, Unit.CURRENT),
    ("1.0.14.7.0.255", GXDLMSRegister): (1.0, Unit.FREQUENCY),
    ("1.0.13.7.0.255", GXDLMSRegister): (1.0, Unit.NO_UNIT),
}


class FakeLiveReader:
    """Replays one logger's recorded capture list and one row.

    Scaler reads answer only for :data:`MEASURED_SIBLINGS`; **every other
    address raises**, which is what the real meters do for a capture column's
    own address. Records every read so a test can assert what the cycle asked
    the meter for.
    """

    def __init__(
        self,
        capture_list: tuple[tuple[str, int], ...],
        capture_period_sec: int,
        row: list[Any],
        *,
        siblings: dict[tuple[str, type], tuple[float, Unit]] | None = None,
    ) -> None:
        self._capture_list = capture_list
        self._capture_period_sec = capture_period_sec
        self._row = row
        self._siblings = MEASURED_SIBLINGS if siblings is None else siblings
        self.profile_reads: list[int] = []
        self.scaler_reads: list[tuple[str, type, int]] = []
        self.row_fetches = 0

    def read(self, obj: Any, attr: int) -> Any:
        if isinstance(obj, GXDLMSProfileGeneric):
            self.profile_reads.append(attr)
            if attr == 3:
                obj.captureObjects = [
                    (SimpleNamespace(logicalName=obis), SimpleNamespace(attributeIndex=index))
                    for obis, index in self._capture_list
                ]
                return obj.captureObjects
            if attr == 4:
                return self._capture_period_sec
            raise AssertionError(f"unexpected ProfileGeneric attr {attr}")

        obis = str(obj.logicalName)
        self.scaler_reads.append((obis, type(obj), attr))
        answer = self._siblings.get((obis, type(obj)))
        if answer is None:
            raise RuntimeError(f"meter refused scaler_unit for {obis} as {type(obj).__name__}")
        obj.scaler, obj.unit = answer
        return None

    def readRowsByRange(self, pg: Any, start: datetime, end: datetime) -> list[list[Any]]:  # noqa: N802
        self.row_fetches += 1
        return [self._row]


def _row_for(capture_list: tuple[tuple[str, int], ...], values: dict[tuple[str, int], Any]) -> list[Any]:
    """One row aligned to *capture_list*, carrying *values* and ``None`` elsewhere."""
    return [values.get(key) for key in capture_list]


def _build(driver_cls: type, reader: FakeLiveReader) -> Any:
    driver = driver_cls(ConnectionParams.net("198.51.100.9", 4059), password="secret")
    driver._reader = reader  # noqa: SLF001
    driver._client = SimpleNamespace(objects=[])  # noqa: SLF001
    return driver


def _read_one(driver: Any, logger_id: int) -> Any:
    readings = driver.read_load_profile(
        logger_id,
        datetime(2026, 9, 9, 3, 0, tzinfo=UTC),
        datetime(2026, 9, 9, 4, 0, tzinfo=UTC),
    )
    assert len(readings) == 1
    return readings[0]


#: One Prometer 100 Logger 1 row. Every cell a distinct number, so a
#: transposition between two columns of the same quantity is a failure here.
#: The clock is meter-local (UTC+7) — 10:30 local is 03:30 UTC.
PROMETER_L1_CELLS: dict[tuple[str, int], Any] = {
    CLOCK: datetime(2026, 9, 9, 10, 30),
    ("1.0.96.5.4.255", 2): 17,
    ("1.0.1.5.0.255", 3): 34100.0,
    ("1.0.2.5.0.255", 3): 12200.0,
    ("1.0.3.5.0.255", 3): 5300.0,
    ("1.0.4.5.0.255", 3): 7400.0,
    ("1.0.81.27.4.255", 2): 118.5,
    ("1.0.81.27.15.255", 2): 238.25,
    ("1.0.81.27.26.255", 2): 358.75,
    ("1.0.1.29.0.255", 2): 8524.2,
}


class TestTheEightNewColumnsOnLoggerOne:
    """The status word, the four average powers and the three phase angles."""

    def _reading(self) -> Any:
        reader = FakeLiveReader(PROMETER_LOGGER1_LIVE, 900, _row_for(PROMETER_LOGGER1_LIVE, PROMETER_L1_CELLS))
        return _read_one(_build(Prometer100Driver, reader), 1)

    def test_the_three_phase_angles_land_in_their_own_columns(self) -> None:
        reading = self._reading()

        assert reading.phase_angle_a == pytest.approx(118.5)
        assert reading.phase_angle_b == pytest.approx(238.25)
        assert reading.phase_angle_c == pytest.approx(358.75)

    def test_the_four_average_powers_land_in_their_own_columns(self) -> None:
        """The meter reports watts and vars (DLMS units 27 and 29); the column
        names promise kW and kvar, so the thousand is divided out at write time
        — the same normalization ``import_active_kwh`` gets, and the same one
        the billing path already applies to its own max-demand kW columns."""
        reading = self._reading()

        assert reading.import_active_kw == pytest.approx(34.1)
        assert reading.export_active_kw == pytest.approx(12.2)
        assert reading.import_reactive_kvar == pytest.approx(5.3)
        assert reading.export_reactive_kvar == pytest.approx(7.4)

    def test_the_status_word_is_stored_as_the_raw_integer(self) -> None:
        """Never decoded here and never scaled. Its bit meanings are settled
        for CEWE and unverified for SMART TCC; storing words would make every
        historical row un-decodable the day the TCC word is verified."""
        reading = self._reading()

        assert reading.interval_status_flag == 17
        assert isinstance(reading.interval_status_flag, int)

    def test_the_status_word_never_asks_the_meter_for_a_scaler(self) -> None:
        reader = FakeLiveReader(PROMETER_LOGGER1_LIVE, 900, _row_for(PROMETER_LOGGER1_LIVE, PROMETER_L1_CELLS))
        _read_one(_build(Prometer100Driver, reader), 1)

        assert not [obis for obis, _cls, _attr in reader.scaler_reads if obis == "1.0.96.5.4.255"]

    def test_the_fourteen_existing_columns_are_undisturbed(self) -> None:
        reading = self._reading()

        assert reading.import_active_kwh == pytest.approx(8.5242)
        assert reading.interval_sec == 900
        assert reading.read_at == datetime(2026, 9, 9, 3, 30, tzinfo=UTC)


class TestTheDemandRegisterScalerIsReadAtTheRightAttribute:
    """A Demand Register carries ``scaler_unit`` at attribute 4; attribute 3 is
    ``last_average_value`` — a number, not a scaler, and exactly the kind of
    wrong answer that would be believed."""

    def test_the_own_address_attempt_reads_attribute_four(self) -> None:
        reader = FakeLiveReader(PROMETER_LOGGER1_LIVE, 900, _row_for(PROMETER_LOGGER1_LIVE, PROMETER_L1_CELLS))
        _read_one(_build(Prometer100Driver, reader), 1)

        power_reads = [(obis, attr) for obis, _cls, attr in reader.scaler_reads if obis == "1.0.1.5.0.255"]
        assert power_reads, "the own address was never tried for a power column"
        assert {attr for _obis, attr in power_reads} == {4}

    def test_the_sibling_attempt_reads_attribute_three(self) -> None:
        reader = FakeLiveReader(PROMETER_LOGGER1_LIVE, 900, _row_for(PROMETER_LOGGER1_LIVE, PROMETER_L1_CELLS))
        _read_one(_build(Prometer100Driver, reader), 1)

        sibling_reads = [(obis, attr) for obis, _cls, attr in reader.scaler_reads if obis == "1.0.1.7.0.255"]
        assert sibling_reads == [("1.0.1.7.0.255", 3)]


class TestTheExportPowerColumnsResolveOnlyAsAnExtendedRegister:
    """Measured 2026-09-09 and the reason issue 04 existed: on one meter the
    import power columns answer as a plain Register and the export ones answer
    only when their max-demand sibling is read as an Extended Register. Their
    own D=7 siblings are denied."""

    def test_the_export_columns_are_filled(self) -> None:
        reader = FakeLiveReader(PROMETER_LOGGER1_LIVE, 900, _row_for(PROMETER_LOGGER1_LIVE, PROMETER_L1_CELLS))
        reading = _read_one(_build(Prometer100Driver, reader), 1)

        assert reading.export_active_kw is not None
        assert reading.export_reactive_kvar is not None

    def test_reading_the_max_demand_sibling_as_a_plain_register_would_empty_them(self) -> None:
        """The mutation this guards against: declaring the export siblings as
        ``GXDLMSRegister`` like their import counterparts. On this meter that
        resolves nothing at all."""
        as_plain_register = dict(MEASURED_SIBLINGS)
        del as_plain_register[("1.0.2.6.0.255", GXDLMSExtendedRegister)]
        del as_plain_register[("1.0.4.6.0.255", GXDLMSExtendedRegister)]
        reader = FakeLiveReader(
            PROMETER_LOGGER1_LIVE,
            900,
            _row_for(PROMETER_LOGGER1_LIVE, PROMETER_L1_CELLS),
            siblings=as_plain_register,
        )

        reading = _read_one(_build(Prometer100Driver, reader), 1)

        assert reading.export_active_kw is None
        assert reading.export_reactive_kvar is None
        # ...while the import columns, which really are plain Registers, are fine.
        assert reading.import_active_kw is not None


class TestAColumnWithNoResolvedScalerStoresNothing:
    """The failure mode this whole ticket designs against. Every scaler on the
    reference meter is ``1.0``, so an unresolved scaler cannot show up as a
    wrong magnitude — it shows up as an empty column, which is what
    ``avg_geo_pf`` looked like for 87,000 rows. Asserted, not relied upon."""

    def test_a_denied_sibling_yields_none_and_never_the_raw_count(self) -> None:
        no_phase_angle_scalers = {
            key: value for key, value in MEASURED_SIBLINGS.items() if not key[0].startswith("1.0.81.")
        }
        reader = FakeLiveReader(
            PROMETER_LOGGER1_LIVE,
            900,
            _row_for(PROMETER_LOGGER1_LIVE, PROMETER_L1_CELLS),
            siblings=no_phase_angle_scalers,
        )

        reading = _read_one(_build(Prometer100Driver, reader), 1)

        assert reading.phase_angle_a is None
        assert reading.phase_angle_b is None
        assert reading.phase_angle_c is None
        # The raw cell held 118.5 — an unscaled number must never reach the column.
        assert reading.import_active_kw is not None, "only the phase angles should be affected"


class TestTheLineToLineVoltagesComeFromLoggerTwo:
    """On a Prometer 100 they are captured by Logger 2 at 300 s, not by
    Logger 1 — the one place in this product where a column's logger is not
    the obvious one."""

    def test_all_three_land_from_the_logger_two_buffer(self) -> None:
        cells: dict[tuple[str, int], Any] = {
            CLOCK: datetime(2026, 9, 9, 10, 30),
            ("1.0.157.27.0.255", 2): 411.5,
            ("1.0.177.27.0.255", 2): 412.25,
            ("1.0.197.27.0.255", 2): 413.75,
        }
        reader = FakeLiveReader(PROMETER_LOGGER2_LIVE, 300, _row_for(PROMETER_LOGGER2_LIVE, cells))

        reading = _read_one(_build(Prometer100Driver, reader), 2)

        assert reading.volt_l1_l2 == pytest.approx(411.5)
        assert reading.volt_l2_l3 == pytest.approx(412.25)
        assert reading.volt_l3_l1 == pytest.approx(413.75)
        assert reading.interval_sec == 300

    def test_logger_one_leaves_them_empty(self) -> None:
        reader = FakeLiveReader(PROMETER_LOGGER1_LIVE, 900, _row_for(PROMETER_LOGGER1_LIVE, PROMETER_L1_CELLS))

        reading = _read_one(_build(Prometer100Driver, reader), 1)

        assert reading.volt_l1_l2 is None
        assert reading.volt_l2_l3 is None
        assert reading.volt_l3_l1 is None


class TestPerModelCoverage:
    """A model that does not record a quantity gets an empty column, never a
    missing one — the shipped and accepted behaviour for ``Frequency (Hz)``."""

    def test_the_premier_550_records_the_status_word_and_nothing_else_new(self) -> None:
        cells: dict[tuple[str, int], Any] = {
            CLOCK: datetime(2026, 9, 9, 10, 30),
            ("1.0.96.5.4.255", 2): 2048,
            ("1.0.1.29.0.255", 2): 1000.0,
        }
        reader = FakeLiveReader(PREMIER_LOGGER1_LIVE, 900, _row_for(PREMIER_LOGGER1_LIVE, cells))

        reading = _read_one(_build(Premier550Driver, reader), 1)

        assert reading.interval_status_flag == 2048
        assert reading.phase_angle_a is None
        assert reading.import_active_kw is None
        assert reading.volt_l1_l2 is None

    def test_the_saral_305_declares_none_of_the_eleven(self) -> None:
        declared = {
            column.field
            for column_map in Saral305Driver.LOAD_PROFILE_COLUMN_MAP.values()
            for column in column_map.values()
        }

        assert declared.isdisjoint(NEW_COLUMNS)

    def test_the_smart_tcc_declares_the_three_phase_angles_and_no_status_word(self) -> None:
        """Its status word is ``0.0.96.10.1.255``, a different object whose bit
        meanings nobody has verified on hardware. v1 refused to map it and so
        do we — mapping it would store a number nothing can decode."""
        declared = {
            column.field
            for column_map in SmartTccDriver.LOAD_PROFILE_COLUMN_MAP.values()
            for column in column_map.values()
        }

        assert {"phase_angle_a", "phase_angle_b", "phase_angle_c"} <= declared
        assert "interval_status_flag" not in declared

    def test_the_smart_tcc_phase_angles_use_that_familys_own_addresses(self) -> None:
        """E=40/51/62 at D=7, not CEWE's E=4/15/26 at D=27
        (``docs/meter-notes/tcc-obis-scan.md``, the 2026-07-18 scan)."""
        keys = {
            key
            for column_map in SmartTccDriver.LOAD_PROFILE_COLUMN_MAP.values()
            for key, column in column_map.items()
            if column.field.startswith("phase_angle_")
        }

        assert keys == {("1.0.81.7.40.255", 2), ("1.0.81.7.51.255", 2), ("1.0.81.7.62.255", 2)}


#: The eleven this ticket adds — named once so the tests below cannot drift
#: apart from the storage layer they check.
NEW_COLUMNS: frozenset[str] = frozenset(
    {
        "phase_angle_a",
        "phase_angle_b",
        "phase_angle_c",
        "volt_l1_l2",
        "volt_l2_l3",
        "volt_l3_l1",
        "import_active_kw",
        "import_reactive_kvar",
        "export_active_kw",
        "export_reactive_kvar",
        "interval_status_flag",
    }
)


class TestTheElevenReachStorage:
    def test_every_new_field_is_carried_to_the_row_columns(self) -> None:
        """``as_columns()`` is what the writer inserts. A field on the
        dataclass that it forgets is read off the meter, scaled, and then
        dropped one line before the database — silently."""
        from arichds.acquisition.drivers.base import IntervalReading

        reading = IntervalReading(
            read_at=datetime(2026, 9, 9, tzinfo=UTC), source="dlms", logger_id=1, interval_sec=900
        )

        assert set(reading.as_columns()) >= NEW_COLUMNS

    def test_as_columns_holds_exactly_the_measurement_fields(self) -> None:
        """Mechanical, so the two cannot drift: every dataclass field except
        the four identity ones is a column, and nothing else is."""
        from dataclasses import fields as dataclass_fields

        from arichds.acquisition.drivers.base import IntervalReading

        identity = {"read_at", "source", "logger_id", "interval_sec"}
        declared = {f.name for f in dataclass_fields(IntervalReading)} - identity
        reading = IntervalReading(
            read_at=datetime(2026, 9, 9, tzinfo=UTC), source="dlms", logger_id=1, interval_sec=900
        )

        assert set(reading.as_columns()) == declared

    def test_the_table_has_a_column_for_every_new_field(self) -> None:
        from arichds.db.models import LoadProfileReading

        assert set(LoadProfileReading.__table__.columns.keys()) >= NEW_COLUMNS


class TestEveryDeclaredFieldIsAStorableColumn:
    """A driver may only name a field the reading actually has. Without this,
    a typo in a driver map — ``export_active_kw`` against the pre-existing
    ``export_active_kwh``, one character apart — either raises at read time on
    a real meter and nowhere else, or silently fills the wrong column."""

    def test_no_driver_declares_a_field_the_interval_reading_lacks(self) -> None:
        from dataclasses import fields as dataclass_fields

        from arichds.acquisition.drivers.base import IntervalReading
        from arichds.acquisition.drivers.factory import _registry

        known = {f.name for f in dataclass_fields(IntervalReading)}
        failures = []
        for model, driver_cls in _registry().items():
            for logger_id, column_map in getattr(driver_cls, "LOAD_PROFILE_COLUMN_MAP", {}).items():
                for key, column in column_map.items():
                    if column.field not in known:
                        failures.append(f"{model} logger {logger_id} {key}: unknown field {column.field!r}")
        assert not failures, "\n".join(failures)


class TestTheCycleAsksTheMeterForNothingNew:
    """The eleven cost no extra meter read: every value is already inside the
    buffer the product reads each cycle. Only the scaler resolutions are new,
    and those happen once per connection, not once per row."""

    def test_the_profile_reads_and_row_fetches_are_unchanged(self) -> None:
        reader = FakeLiveReader(PROMETER_LOGGER1_LIVE, 900, _row_for(PROMETER_LOGGER1_LIVE, PROMETER_L1_CELLS))
        _read_one(_build(Prometer100Driver, reader), 1)

        # attr 3 (capture objects) and attr 4 (capture period), read live, once
        # each — and exactly one buffer fetch. No new profile read, no poll.
        assert reader.profile_reads == [3, 4]
        assert reader.row_fetches == 1

    def test_each_scaler_is_resolved_once_per_connection(self) -> None:
        reader = FakeLiveReader(PROMETER_LOGGER1_LIVE, 900, _row_for(PROMETER_LOGGER1_LIVE, PROMETER_L1_CELLS))
        driver = _build(Prometer100Driver, reader)

        for _ in range(3):
            _read_one(driver, 1)

        attempted = [(obis, cls) for obis, cls, _attr in reader.scaler_reads]
        assert len(attempted) == len(set(attempted)), "a scaler was re-read on a later chunk"


class TestTheStatusWordSurvivesTheStore:
    """M13, issue 06 — measured, because the type is not what it looks like.

    A real meter returns this cell as a **Gurux integer subclass**, not a plain
    ``int``: a Premier 550 at ``49.229.159.44:50001`` answered with ``GXUInt8``
    on 2026-09-09, read-only. It is a passthrough column, so whatever the meter
    hands over is what reaches the ``INTEGER`` column — nothing coerces it on
    the way. That works, and these tests are here so it keeps working: the
    dependency is on ``sqlite3`` accepting an ``int`` subclass, which is not
    something the code says anywhere.
    """

    def test_a_gurux_integer_stores_and_reads_back_as_a_plain_int(self, migrated_db) -> None:  # noqa: ANN001
        from gurux_dlms.internal._GXCommon import GXUInt8

        from arichds.db.models import Device, LoadProfileReading
        from arichds.db.session import session_scope

        with session_scope() as session:
            device = Device(
                name="Main Incomer",
                brand="cewe",
                model="premier550",
                site_name="Plant A",
                transport={"kind": "net", "host": "127.0.0.1", "port": 50001},
                password="",
                meter_serial="SS18197374",
            )
            session.add(device)
            session.flush()
            session.add(
                LoadProfileReading(
                    device_id=device.id,
                    read_at=datetime(2026, 9, 9, 11, 45, tzinfo=UTC),
                    source="dlms",
                    logger_id=1,
                    interval_sec=900,
                    interval_status_flag=GXUInt8(17),
                )
            )

        with session_scope() as session:
            stored = session.query(LoadProfileReading).one().interval_status_flag

        assert stored == 17
        assert type(stored) is int, "the Gurux type must not survive into the row a reader gets"

    def test_the_decoder_accepts_the_gurux_type_directly(self) -> None:
        """Belt and braces: the CSV reads its rows back out of the database, so
        it never sees the Gurux type — but the decoder is a public function and
        a future caller might hand it one straight off a driver."""
        from gurux_dlms.internal._GXCommon import GXUInt8

        from arichds.interval_status import decode_interval_status

        assert decode_interval_status(GXUInt8(0)) == "OK"
        assert decode_interval_status(GXUInt8(17)) == "ALL_INVALID|DISTURBED"
