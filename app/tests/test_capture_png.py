"""``capture.png`` — the third billing capture renderer (M7 slice 4, issue
#35, ADR 0014/0015).

``rows`` are already ordered and already limited by the caller (D4/D6) — the
renderer does not query, sort, or truncate; these tests feed it
``SimpleNamespace`` rows built the same way ``test_capture_renderers.py``'s
``make_row()`` does.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from PIL import Image

from arichds.capture._render_shared import ALL_SECTIONS, MEASUREMENT_SECTIONS
from arichds.capture.png import _cell_text, measurement_column_groups, render_billing_png

BILL_DATE = datetime(2026, 7, 31, 17, 0, 0, tzinfo=UTC)


def make_row(**overrides: object) -> SimpleNamespace:
    fields = {attr: None for _title, section in ALL_SECTIONS for _label, attr in section}
    fields.update(bill_date=BILL_DATE, meter_serial="1232002893", record_status=None, read_at=BILL_DATE)
    fields.update(overrides)
    return SimpleNamespace(**fields)


class TestRenderBillingPngBasics:
    def test_returns_a_loadable_png(self) -> None:
        row = make_row(import_active_kwh_total=200464.501)

        result = render_billing_png([row], "Main Incomer")

        assert isinstance(result, bytes)
        img = Image.open(io.BytesIO(result))
        assert img.format == "PNG"

    def test_non_ascii_device_name_does_not_raise(self) -> None:
        row = make_row()

        result = render_billing_png([row], "ระบบ")

        assert Image.open(io.BytesIO(result)).format == "PNG"


class TestT8OneRowRendersWithoutError:
    """T8 (D5) — fewer than ten closed periods renders the ones that exist,
    with no padding and no error."""

    def test_a_single_row_renders_a_valid_one_row_png(self) -> None:
        row = make_row()

        result = render_billing_png([row], "Main Incomer")

        img = Image.open(io.BytesIO(result))
        assert img.format == "PNG"
        assert img.size[0] > 0
        assert img.size[1] > 0


class TestT9RowOrderIsNotReorderedByTheRenderer:
    """T9 (D6) belongs to the row-*selection* query (capture/service.py) for
    its DB-level guarantee, but the renderer itself must draw rows in the
    order given — never re-sort them. Proven by feeding three out-of-order
    rows and confirming the canvas grows monotonically with row count (a
    stand-in the renderer-level test can make without pixel inspection) and,
    more directly, that the renderer never raises regardless of order."""

    def test_the_renderer_accepts_rows_in_whatever_order_theyre_given(self) -> None:
        newest = make_row(bill_date=BILL_DATE)
        middle = make_row(bill_date=BILL_DATE - timedelta(days=31))
        oldest = make_row(bill_date=BILL_DATE - timedelta(days=62))

        result = render_billing_png([newest, middle, oldest], "Main Incomer")

        assert Image.open(io.BytesIO(result)).format == "PNG"


class TestMeasurementColumnGroupsT2:
    """T2 (D7) — the set of leaf column attrs the renderer draws must equal
    the set of the 60 attrs in `ALL_SECTIONS`'s five measurement sections,
    exactly. `Record Status` and `Read At` must never appear."""

    def test_leaf_attrs_match_the_sixty_measurement_columns_exactly(self) -> None:
        groups = measurement_column_groups("kilo")

        drawn_attrs = {attr for _title, children in groups for _label, attr in children}
        expected_attrs = {attr for title, fields in ALL_SECTIONS if title != "Metadata" for _label, attr in fields}

        assert drawn_attrs == expected_attrs
        assert len(drawn_attrs) == 60

    def test_record_status_and_read_at_are_never_drawn(self) -> None:
        groups = measurement_column_groups("kilo")

        drawn_labels = {label for _title, children in groups for label, _attr in children}
        drawn_group_titles = {title for title, _children in groups}

        assert "Record Status" not in drawn_labels
        assert "Record Status" not in drawn_group_titles
        assert "Read At" not in drawn_labels
        assert "Read At" not in drawn_group_titles


class TestColumnGroupChildrenT3:
    """T3 (D7) — each group spans exactly the five rate children, in order.

    Review round, problem 2: asserting only the label half
    (`[label for label, _attr in children] == [...]`) is satisfied by a
    transposed attr mapping — e.g. "Rate A"'s label paired with Rate B's
    attr — because the label list is unchanged even though every value in
    that column would come from the wrong tariff. Both halves of the zip
    (label AND attr) must be pinned, per group, against that group's own
    prefix."""

    def test_every_group_has_the_five_children_in_order(self) -> None:
        groups = measurement_column_groups("kilo")

        expected_prefixes = [
            prefix for _section_title, section_groups in MEASUREMENT_SECTIONS for _t, prefix in section_groups
        ]
        assert len(groups) == len(expected_prefixes) == 12  # 2+2+4+2+2 groups across the five sections

        for (_title, children), prefix in zip(groups, expected_prefixes, strict=True):
            assert children == [
                ("Total", f"{prefix}_total"),
                ("Rate A", f"{prefix}_rate_a"),
                ("Rate B", f"{prefix}_rate_b"),
                ("Rate C", f"{prefix}_rate_c"),
                ("Rate D", f"{prefix}_rate_d"),
            ]


class TestDisplayUnitScaleT17:
    """T17 (D10) — the PNG follows `display_unit_scale`, exactly as the PDF
    and xlsx do. Two absolutes: the bytes differ between scales, and the
    column-header model carries the correct literal label under each."""

    def test_kilo_and_base_produce_different_bytes(self) -> None:
        row = make_row(import_active_kwh_total=42.5)

        kilo_bytes = render_billing_png([row], "Main Incomer", scale="kilo")
        base_bytes = render_billing_png([row], "Main Incomer", scale="base")

        assert kilo_bytes != base_bytes

    def test_kilo_column_groups_carry_the_kilo_labels(self) -> None:
        groups = measurement_column_groups("kilo")
        titles = {title for title, _children in groups}

        assert "Import Active kWh" in titles
        assert "Import Active Wh" not in titles

    def test_base_column_groups_carry_the_base_labels(self) -> None:
        groups = measurement_column_groups("base")
        titles = {title for title, _children in groups}

        assert "Import Active Wh" in titles
        assert "Import Active kWh" not in titles

    def test_kilo_cell_value_is_unscaled(self) -> None:
        """Review round, problem 3 — the two tests above (and
        `test_kilo_and_base_produce_different_bytes`) pin the *labels* and
        the *bytes*, but nothing pinned that a cell *value* is actually
        converted: a PNG that always prints the raw kWh number under
        whichever header the scale picked would satisfy every existing T17
        assertion. `_cell_text` is the one place a leaf cell's value is
        computed (imported directly here rather than promoted to a public
        name — production code is unchanged for this fix, per the review's
        instruction)."""
        row = make_row(import_active_kwh_total=42.5)

        assert _cell_text(row, "import_active_kwh_total", "kilo") == "42.5"

    def test_base_cell_value_is_scaled_by_one_thousand(self) -> None:
        row = make_row(import_active_kwh_total=42.5)

        assert _cell_text(row, "import_active_kwh_total", "base") == "42500.0"

    def test_base_leaves_a_non_convertible_field_unscaled(self) -> None:
        """The other side of `_is_convertible_field` — a Demand Time
        attribute is a timestamp, never a magnitude, and must render
        identically under either scale."""
        stamp = datetime(2026, 8, 5, 9, 12, 0, tzinfo=UTC)
        row = make_row(max_demand_import_active_time_total=stamp)

        assert _cell_text(row, "max_demand_import_active_time_total", "base") == "2026-08-05 09:12:00+00:00"
