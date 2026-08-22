"""``capture._render_shared`` — the one source of section/field definitions
and cell formatters both renderers import (decision 7, issue #22).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from arichds.capture._render_shared import ALL_SECTIONS, ascii_cell, format_cell, scale_label, scale_value


class TestFormatCell:
    def test_none_becomes_a_dash(self) -> None:
        assert format_cell(None) == "-"

    def test_a_datetime_is_iso_with_a_space_separator(self) -> None:
        value = datetime(2026, 8, 1, 12, 30, 45, tzinfo=UTC)
        assert format_cell(value) == "2026-08-01 12:30:45+00:00"

    def test_a_number_is_stringified(self) -> None:
        assert format_cell(200464.501) == "200464.501"

    def test_non_ascii_is_preserved_verbatim(self) -> None:
        assert format_cell("ระบบ") == "ระบบ"


class TestAsciiCell:
    def test_non_ascii_is_replaced_with_question_marks(self) -> None:
        assert ascii_cell("ระบบ") == "?" * len("ระบบ".encode("ascii", "replace").decode("ascii"))

    def test_ascii_input_is_unchanged(self) -> None:
        assert ascii_cell("Main Incomer") == "Main Incomer"

    def test_none_becomes_a_dash(self) -> None:
        assert ascii_cell(None) == "-"


class TestAllSectionsCoversEveryMeasurementColumn:
    def test_every_one_of_the_sixty_measurement_columns_appears_exactly_once(self) -> None:
        from arichds.db.models import BillingReading

        model_columns = {
            column.name
            for column in BillingReading.__table__.columns
            if column.name
            not in {
                "id",
                "device_id",
                "bill_date",
                "read_at",
                "record_status",
                "source",
                "meter_serial",
                "created_at",
                "updated_at",
            }
        }

        field_attrs = [attr for title, fields in ALL_SECTIONS if title != "Metadata" for _label, attr in fields]

        assert set(field_attrs) == model_columns
        assert len(field_attrs) == len(set(field_attrs)) == 60  # no duplicate, none dropped

    def test_metadata_fields_are_present(self) -> None:
        meta_section = next(fields for title, fields in ALL_SECTIONS if title == "Metadata")
        attrs = {attr for _label, attr in meta_section}
        assert attrs == {"bill_date", "meter_serial", "record_status", "read_at"}

    def test_demand_time_and_cumulative_demand_sections_exist(self) -> None:
        """D18 — two new sections, four new groups, twenty new rows (M4c,
        issue #24)."""
        titles = [title for title, _fields in ALL_SECTIONS]
        assert "Demand Time" in titles
        assert "Cumulative Demand" in titles

    def test_demand_time_section_has_the_two_groups(self) -> None:
        section = next(fields for title, fields in ALL_SECTIONS if title == "Demand Time")
        attrs = {attr for _label, attr in section}
        assert attrs == {
            "max_demand_import_active_time_total",
            "max_demand_import_active_time_rate_a",
            "max_demand_import_active_time_rate_b",
            "max_demand_import_active_time_rate_c",
            "max_demand_import_active_time_rate_d",
            "max_demand_import_reactive_time_total",
            "max_demand_import_reactive_time_rate_a",
            "max_demand_import_reactive_time_rate_b",
            "max_demand_import_reactive_time_rate_c",
            "max_demand_import_reactive_time_rate_d",
        }

    def test_cumulative_demand_section_has_the_two_groups(self) -> None:
        section = next(fields for title, fields in ALL_SECTIONS if title == "Cumulative Demand")
        attrs = {attr for _label, attr in section}
        assert attrs == {
            "cumul_demand_import_active_kw_total",
            "cumul_demand_import_active_kw_rate_a",
            "cumul_demand_import_active_kw_rate_b",
            "cumul_demand_import_active_kw_rate_c",
            "cumul_demand_import_active_kw_rate_d",
            "cumul_demand_import_reactive_kvar_total",
            "cumul_demand_import_reactive_kvar_rate_a",
            "cumul_demand_import_reactive_kvar_rate_b",
            "cumul_demand_import_reactive_kvar_rate_c",
            "cumul_demand_import_reactive_kvar_rate_d",
        }


class TestFormatCellHandlesDemandTime:
    def test_a_demand_time_datetime_formats_the_same_as_bill_date(self) -> None:
        """SPEC §3.6:650 flagged this as needing new-type support in the
        formatter — it does not (D18's own note): ``format_cell`` already
        renders any ``datetime`` as ISO with a space separator, and a Demand
        Time cell is a plain ``datetime`` like every other one."""
        value = datetime(2026, 8, 5, 9, 12, 0, tzinfo=UTC)
        assert format_cell(value) == "2026-08-05 09:12:00+00:00"


class TestScaleValue:
    """Machine-wide display-unit setting (kW/kWh vs W/Wh) — conversion at
    render time only, never on the stored value (CLAUDE.md's write-time
    normalization invariant)."""

    def test_kilo_leaves_an_energy_value_unchanged(self) -> None:
        assert scale_value(200464.501, "import_active_kwh_total", "kilo") == 200464.501

    def test_base_multiplies_an_energy_value_by_1000(self) -> None:
        assert scale_value(200.464501, "import_active_kwh_total", "base") == pytest.approx(200464.501)

    def test_base_multiplies_a_reactive_energy_value(self) -> None:
        assert scale_value(1.5, "import_reactive_kvarh_total", "base") == 1500.0

    def test_base_multiplies_a_demand_power_value(self) -> None:
        assert scale_value(2.5, "max_demand_import_active_kw_rate_a", "base") == 2500.0

    def test_base_multiplies_a_reactive_demand_power_value(self) -> None:
        assert scale_value(3.0, "max_demand_import_reactive_kvar_rate_b", "base") == 3000.0

    def test_base_multiplies_a_cumulative_demand_value(self) -> None:
        assert scale_value(4.0, "cumul_demand_import_active_kw_total", "base") == 4000.0

    def test_a_demand_time_field_is_never_scaled(self) -> None:
        """Demand Time carries a datetime, not a magnitude — `scale_value`
        must never be asked to multiply one, but a caller that got the field
        list wrong must not corrupt a timestamp either."""
        assert scale_value(5.0, "max_demand_import_active_time_total", "base") == 5.0

    def test_a_metadata_field_is_never_scaled(self) -> None:
        assert scale_value(5.0, "bill_date", "base") == 5.0

    def test_none_stays_none_under_base(self) -> None:
        """The null-means-not-captured rule must survive scaling — `None * 1000`
        would raise, and a scaled `None` must still render as the dash
        `format_cell` gives every other absent measurement."""
        assert scale_value(None, "import_active_kwh_total", "base") is None

    def test_none_stays_none_under_kilo(self) -> None:
        assert scale_value(None, "import_active_kwh_total", "kilo") is None

    def test_zero_is_not_treated_as_absent(self) -> None:
        """A genuine 0 kWh must scale to a genuine 0 Wh, not fall through to
        `None`'s early-return — this is the same `value is None` vs `not value`
        distinction the frontend's own `num()` helpers document."""
        assert scale_value(0.0, "import_active_kwh_total", "base") == 0.0


class TestAllSectionsExplicitLiteral:
    """D8/T1 (issue #35): `ALL_SECTIONS` must equal an explicit literal of all
    six sections and all 64 `(label, attr)` pairs, in order — not `len()`,
    not a set of attrs. This is what pairs with "PDF/xlsx unchanged": if the
    new `MEASUREMENT_SECTIONS` declaration that now builds `ALL_SECTIONS`
    (issue #35, D8) drops or renames anything, this fails immediately."""

    def test_all_sections_matches_the_literal_exactly(self) -> None:
        def group(title: str, prefix: str) -> list[tuple[str, str]]:
            return [
                (f"{title} Total", f"{prefix}_total"),
                (f"{title} Rate A", f"{prefix}_rate_a"),
                (f"{title} Rate B", f"{prefix}_rate_b"),
                (f"{title} Rate C", f"{prefix}_rate_c"),
                (f"{title} Rate D", f"{prefix}_rate_d"),
            ]

        expected: list[tuple[str, list[tuple[str, str]]]] = [
            (
                "Energy (kWh)",
                [
                    *group("Import Active kWh", "import_active_kwh"),
                    *group("Export Active kWh", "export_active_kwh"),
                ],
            ),
            (
                "Reactive Energy (kvarh)",
                [
                    *group("Import Reactive kvarh", "import_reactive_kvarh"),
                    *group("Export Reactive kvarh", "export_reactive_kvarh"),
                ],
            ),
            (
                "Maximum Demand",
                [
                    *group("Max Demand Import Active kW", "max_demand_import_active_kw"),
                    *group("Max Demand Export Active kW", "max_demand_export_active_kw"),
                    *group("Max Demand Import Reactive kvar", "max_demand_import_reactive_kvar"),
                    *group("Max Demand Export Reactive kvar", "max_demand_export_reactive_kvar"),
                ],
            ),
            (
                "Demand Time",
                [
                    *group("Demand Time Import Active", "max_demand_import_active_time"),
                    *group("Demand Time Import Reactive", "max_demand_import_reactive_time"),
                ],
            ),
            (
                "Cumulative Demand",
                [
                    *group("Cumulative Demand Import Active kW", "cumul_demand_import_active_kw"),
                    *group("Cumulative Demand Import Reactive kvar", "cumul_demand_import_reactive_kvar"),
                ],
            ),
            (
                "Metadata",
                [
                    ("Bill Date", "bill_date"),
                    ("Meter Serial", "meter_serial"),
                    ("Record Status", "record_status"),
                    ("Read At", "read_at"),
                ],
            ),
        ]

        assert expected == ALL_SECTIONS
        total_fields = sum(len(fields) for _title, fields in ALL_SECTIONS)
        assert total_fields == 64


class TestScaleLabel:
    def test_kilo_leaves_a_label_unchanged(self) -> None:
        assert scale_label("Energy (kWh)", "kilo") == "Energy (kWh)"

    def test_base_converts_kwh_to_wh(self) -> None:
        assert scale_label("Energy (kWh)", "base") == "Energy (Wh)"

    def test_base_converts_kvarh_to_varh(self) -> None:
        assert scale_label("Reactive Energy (kvarh)", "base") == "Reactive Energy (varh)"

    def test_base_converts_kw_to_w(self) -> None:
        assert scale_label("Max Demand Import Active kW Total", "base") == "Max Demand Import Active W Total"

    def test_base_converts_kvar_to_var(self) -> None:
        assert scale_label("Max Demand Import Reactive kvar Total", "base") == "Max Demand Import Reactive var Total"

    def test_base_leaves_a_label_with_no_unit_token_unchanged(self) -> None:
        assert scale_label("Bill Date", "base") == "Bill Date"
