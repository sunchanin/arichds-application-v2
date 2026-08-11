"""``export.format`` — pure row/filename formatting for the Load Profile CSV
(M7 slice 3, issue #30).

No I/O, no DB. Given the same merged rows and settings it always produces
the same output — the CSV exporter and any future caller both build on this.
"""

from __future__ import annotations

from datetime import UTC, datetime

from arichds.export.format import (
    _CSV_COLUMNS,
    _EXPORT_HEADERS,
    _translate_date_format,
    format_rows,
    render_filename,
)


class TestTranslateDateFormat:
    def test_the_default_v1_format_translates_token_by_token(self) -> None:
        assert _translate_date_format("yyyy-mm-dd HH:MM:SS") == "%Y-%m-%d %H:%M:%S"

    def test_lowercase_mm_is_month_uppercase_mm_is_minute(self) -> None:
        """The whole reason for longest-token-first, left-to-right substitution."""
        assert _translate_date_format("mm/MM") == "%m/%M"

    def test_an_unknown_character_passes_through_untouched(self) -> None:
        assert _translate_date_format("yyyy_dd") == "%Y_%d"


class TestExportHeaders:
    """T3 — the header text, written out literally so this test cannot pass
    merely by importing itself."""

    def test_the_headers_are_exactly_f1s_fourteen_strings_in_order(self) -> None:
        assert _EXPORT_HEADERS == (
            "Name",
            "Date/Time",
            "Import Active (kWh)",
            "Import Reactive (kvarh)",
            "Export Active (kWh)",
            "Export Reactive (kvarh)",
            "Avg Geo PF",
            "Voltage L1 (V)",
            "Voltage L2 (V)",
            "Voltage L3 (V)",
            "Current L1 (A)",
            "Current L2 (A)",
            "Current L3 (A)",
            "Frequency (Hz)",
        )

    def test_v1s_wrong_headers_are_absent(self) -> None:
        v1_strings = {"Import kWh Active", "Import kWh Reactive", "Export kWh Active", "Export kWh Re"}
        assert v1_strings.isdisjoint(_EXPORT_HEADERS)


class TestFormatRowsColumnOrder:
    """T3 — distinct non-zero energy values are what make a transposition detectable."""

    def test_the_four_energy_cells_land_in_the_right_columns(self) -> None:
        rows = [
            {
                "read_at": datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
                "import_active_kwh": 11.0,
                "import_reactive_kvarh": 22.0,
                "export_active_kwh": 33.0,
                "export_reactive_kvarh": 44.0,
                "avg_geo_pf": None,
                "volt_l1": None,
                "volt_l2": None,
                "volt_l3": None,
                "current_l1": None,
                "current_l2": None,
                "current_l3": None,
                "freq": None,
            }
        ]

        [cells] = format_rows(rows, device_label="Main (SN-1)", date_format="yyyy-mm-dd HH:MM:SS")

        assert cells[2] == format(11.0, ".9f")
        assert cells[3] == format(22.0, ".9f")
        assert cells[4] == format(33.0, ".9f")
        assert cells[5] == format(44.0, ".9f")


class TestFormatRowsNoneAndFormatting:
    def test_none_renders_as_empty_string_and_measurement_columns_use_three_decimals(self) -> None:
        rows = [
            {
                "read_at": datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
                "import_active_kwh": None,
                "import_reactive_kvarh": None,
                "export_active_kwh": None,
                "export_reactive_kvarh": None,
                "avg_geo_pf": 0.987654321,
                "volt_l1": 230.12345,
                "volt_l2": None,
                "volt_l3": None,
                "current_l1": None,
                "current_l2": None,
                "current_l3": None,
                "freq": None,
            }
        ]

        [cells] = format_rows(rows, device_label="Main (SN-1)", date_format="yyyy-mm-dd HH:MM:SS")

        assert cells[2] == "", "a None energy cell must render as the empty string, not '0' or 'None'"
        assert cells[6] == format(0.987654321, ".3f")
        assert cells[7] == format(230.12345, ".3f")

    def test_the_label_includes_the_serial_when_present(self) -> None:
        rows = [{"read_at": datetime(2026, 8, 1, tzinfo=UTC), **{name: None for name in _CSV_COLUMNS}}]

        [cells] = format_rows(rows, device_label="Main Incomer (SN-1)", date_format="yyyy-mm-dd HH:MM:SS")

        assert cells[0] == "Main Incomer (SN-1)"

    def test_the_timestamp_shifts_seven_hours_and_can_cross_midnight(self) -> None:
        """T9 — an instant that crosses midnight under the +7h ICT shift is
        what makes an omitted or misapplied shift visible."""
        rows = [{"read_at": datetime(2026, 8, 1, 18, 30, tzinfo=UTC), **{name: None for name in _CSV_COLUMNS}}]

        [cells] = format_rows(rows, device_label="Main (SN-1)", date_format="yyyy-mm-dd HH:MM:SS")

        assert cells[1] == "2026-08-02 01:30:00"


class TestRenderFilename:
    def test_meter_and_serial_tokens_both_substitute(self) -> None:
        assert render_filename("[meter].csv", "SN-1") == "SN-1.csv"
        assert render_filename("[serial].csv", "SN-1") == "SN-1.csv"

    def test_the_date_token_substitutes_todays_iso_date(self) -> None:
        from datetime import date as _date

        assert render_filename("[date]-[meter].csv", "SN-1") == f"{_date.today().isoformat()}-SN-1.csv"
