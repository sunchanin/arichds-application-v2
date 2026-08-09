"""``acquisition.drivers._profile`` — the shared ProfileGeneric column-mapping
machinery every DLMS driver's load-profile and billing read uses (D6, D5,
issue #24).

The collision this module exists to prevent (F1/F2, D5): a max-demand value
(attribute 2) and its own capture time (attribute 5) share one OBIS code on
the CEWE billing profile. An OBIS-only position map would silently collapse
the two into the same slot; the fix is keying on ``(OBIS, attribute)``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arichds.acquisition.drivers._profile import build_fields, positions_by_obis_attr


def _capture_object(obis: str, attr: int) -> tuple[SimpleNamespace, SimpleNamespace]:
    return SimpleNamespace(logicalName=obis), SimpleNamespace(attributeIndex=attr)


class TestPositionsByObisAttr:
    def test_a_value_and_its_capture_time_sharing_one_obis_both_get_their_own_position(self) -> None:
        """The collision (F2): ``1.0.1.6.0.255`` at attr 2 (the value) AND attr 5
        (when it was captured) — this must fail against an OBIS-only map first."""
        capture_objects = [
            _capture_object("0.0.1.0.0.255", 2),
            _capture_object("1.0.1.6.0.255", 2),
            _capture_object("1.0.1.6.0.255", 5),
        ]

        positions = positions_by_obis_attr(capture_objects)

        assert positions[("1.0.1.6.0.255", 2)] == 1
        assert positions[("1.0.1.6.0.255", 5)] == 2
        assert positions[("1.0.1.6.0.255", 2)] != positions[("1.0.1.6.0.255", 5)]

    def test_position_is_index_order(self) -> None:
        capture_objects = [_capture_object("a", 2), _capture_object("b", 2), _capture_object("c", 2)]

        positions = positions_by_obis_attr(capture_objects)

        assert positions == {("a", 2): 0, ("b", 2): 1, ("c", 2): 2}


class TestBuildFields:
    """Given already-resolved positions/multipliers, turn one row into a
    ``{field: value}`` dict — the loop shared by every driver's per-row
    mapping (D6)."""

    def test_a_value_and_its_capture_time_both_land_in_their_own_field(self) -> None:
        positions = {("1.0.1.6.0.255", 2): 0, ("1.0.1.6.0.255", 5): 1}
        column_map = {
            ("1.0.1.6.0.255", 2): "max_demand_import_active_kw_total",
            ("1.0.1.6.0.255", 5): "max_demand_import_active_time_total",
        }
        multipliers = {("1.0.1.6.0.255", 2): 1.0}
        row = [123.0, "not-multiplied"]

        fields = build_fields(
            row,
            positions,
            column_map,
            multipliers,
            scale=lambda _field, value: value,
            passthrough_keys={("1.0.1.6.0.255", 5)},
        )

        assert fields["max_demand_import_active_kw_total"] == pytest.approx(123.0)
        assert fields["max_demand_import_active_time_total"] == "not-multiplied"

    def test_missing_position_is_none(self) -> None:
        column_map = {("x", 2): "field_x"}
        fields = build_fields([1, 2, 3], {}, column_map, {}, scale=lambda _f, v: v)
        assert fields["field_x"] is None

    def test_missing_multiplier_is_none(self) -> None:
        column_map = {("x", 2): "field_x"}
        positions = {("x", 2): 0}
        fields = build_fields([5], positions, column_map, {}, scale=lambda _f, v: v)
        assert fields["field_x"] is None

    def test_non_numeric_raw_is_none_rather_than_multiplied(self) -> None:
        column_map = {("x", 2): "field_x"}
        positions = {("x", 2): 0}
        multipliers = {("x", 2): 2.0}
        fields = build_fields([bytearray(b"\x01")], positions, column_map, multipliers, scale=lambda _f, v: v)
        assert fields["field_x"] is None

    def test_scale_callback_is_applied(self) -> None:
        column_map = {("x", 2): "field_x"}
        positions = {("x", 2): 0}
        multipliers = {("x", 2): 2.0}
        fields = build_fields([10], positions, column_map, multipliers, scale=lambda _f, v: v / 1000)
        assert fields["field_x"] == pytest.approx(0.02)
