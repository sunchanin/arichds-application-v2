"""``capture._render_shared`` — the one source of section/field definitions
and cell formatters both renderers import (decision 7, issue #22).
"""

from __future__ import annotations

from datetime import UTC, datetime

from arichds.capture._render_shared import ALL_SECTIONS, ascii_cell, format_cell


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
    def test_every_one_of_the_forty_measurement_columns_appears_exactly_once(self) -> None:
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
        assert len(field_attrs) == len(set(field_attrs)) == 40  # no duplicate, none dropped

    def test_metadata_fields_are_present(self) -> None:
        meta_section = next(fields for title, fields in ALL_SECTIONS if title == "Metadata")
        attrs = {attr for _label, attr in meta_section}
        assert attrs == {"bill_date", "meter_serial", "record_status", "read_at"}
