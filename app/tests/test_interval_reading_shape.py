"""``IntervalReading``'s M4c fields (issue #24) — the four ``load_profile_readings``
measurement columns migration 0006 already added but no driver produced until
now: ``import_reactive_kvarh``, ``export_active_kwh``, ``export_reactive_kvarh``,
``avg_geo_pf``. All three CEWE models produce at least one of them (F7).
"""

from __future__ import annotations

from dataclasses import fields

from arichds.acquisition.drivers.base import IntervalReading


class TestTheFourM4cFields:
    def test_the_field_set_now_includes_all_twelve_measurement_columns(self) -> None:
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

    def test_the_four_new_fields_default_to_none(self) -> None:
        from datetime import UTC, datetime

        reading = IntervalReading(
            read_at=datetime(2026, 8, 7, tzinfo=UTC), source="dlms", logger_id=1, interval_sec=900
        )
        assert reading.import_reactive_kvarh is None
        assert reading.export_active_kwh is None
        assert reading.export_reactive_kvarh is None
        assert reading.avg_geo_pf is None

    def test_as_columns_carries_all_twelve_measurement_fields(self) -> None:
        from datetime import UTC, datetime

        reading = IntervalReading(
            read_at=datetime(2026, 8, 7, tzinfo=UTC),
            source="dlms",
            logger_id=1,
            interval_sec=900,
            import_reactive_kvarh=1.5,
            export_active_kwh=2.5,
            export_reactive_kvarh=3.5,
            avg_geo_pf=0.95,
        )
        columns = reading.as_columns()
        assert columns["import_reactive_kvarh"] == 1.5
        assert columns["export_active_kwh"] == 2.5
        assert columns["export_reactive_kvarh"] == 3.5
        assert columns["avg_geo_pf"] == 0.95
        assert len(columns) == 12
