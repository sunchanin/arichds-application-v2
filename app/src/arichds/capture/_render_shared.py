"""Shared rendering primitives for billing captures (M6b, issue #22).

One source for the section/field definitions and the two cell formatters,
imported by both :mod:`arichds.capture.pdf` and :mod:`arichds.capture.xlsx`
(decision 7, issue #22) so a field cannot exist in one output and be missing
from the other — the two formats are sold as separate features
(``auto_capture`` / ``billing_excel_export``), so silent drift between them is
a bug nobody using only one of the two would ever notice.

Built off v2's own forty :class:`~arichds.db.models.BillingReading` columns
(``db/models.py:314-360``) plus the row's metadata fields — **not** copied
from v1's three-tariff, thirty-column list (v1 stopped at Rate C; v2 has four
tariffs, SPEC §3.6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

__all__ = ["ALL_SECTIONS", "DisplayUnitScale", "ascii_cell", "format_cell", "scale_label", "scale_value"]

#: The machine-wide display-unit setting (a CR, not part of the original M6b
#: shape) — `"kilo"` is today's behaviour (kW/kWh/kvar/kvarh), `"base"` is
#: W/Wh/var/varh. Applied at render time only, on top of `format_cell`/
#: `ascii_cell` — the stored value and the API payload never change (
#: CLAUDE.md's write-time normalization invariant).
DisplayUnitScale = Literal["kilo", "base"]

#: The rate-column suffixes every measurement field carries (mirrors
#: `_measurement_section` below) — stripped off before looking at the unit
#: token so `scale_value`/`scale_value`'s caller can work off the raw
#: `BillingReading` attribute name.
_RATE_SUFFIXES = ("_total", "_rate_a", "_rate_b", "_rate_c", "_rate_d")

#: The unit token a field's prefix ends with, for the fields that ARE a
#: magnitude in kWh/kvarh/kW/kvar. Demand Time fields end in `_time` and
#: Metadata fields carry no such token at all — both fall through as
#: non-convertible, which is exactly right: one is a timestamp, the other is
#: an id/status/date string, and D20/the owner's kilo<->base ruling covers
#: energy and power only.
_CONVERTIBLE_UNIT_TOKENS = frozenset({"kwh", "kvarh", "kw", "kvar"})


def _is_convertible_field(attr: str) -> bool:
    """Whether *attr* (a `BillingReading` column name) is an energy/power
    magnitude the kilo<->base setting may scale."""
    for suffix in _RATE_SUFFIXES:
        if attr.endswith(suffix):
            token = attr[: -len(suffix)].rsplit("_", 1)[-1]
            return token in _CONVERTIBLE_UNIT_TOKENS
    return False


def scale_value(value: float | None, attr: str, scale: DisplayUnitScale) -> float | None:
    """Convert *value* for display under *scale*.

    `"kilo"` and a non-convertible *attr* (a Demand Time timestamp or a
    Metadata field) are both no-ops. `None` — "the meter never captured
    this" — passes through unchanged rather than raising; a genuine `0` is
    scaled like any other number (`value is None`, never `not value`).
    """
    if scale != "base" or value is None or not _is_convertible_field(attr):
        return value
    return value * 1000


#: Applied in order to a label/title string under `scale == "base"`. `"kWh"`
#: needs no entry of its own: replacing the `"kW"` substring inside it already
#: leaves the correct `"Wh"` (same reasoning for `"kvarh"` -> `"kvar"`).
_LABEL_REPLACEMENTS: tuple[tuple[str, str], ...] = (("kvar", "var"), ("kW", "W"))


def scale_label(label: str, scale: DisplayUnitScale) -> str:
    """Swap a label/title's kilo unit tokens (`kWh`, `kvarh`, `kW`, `kvar`)
    for their base equivalents (`Wh`, `varh`, `W`, `var`) under `"base"`.

    A no-op under `"kilo"`, and a no-op on a label with no unit token at all
    (Demand Time / Metadata section and field titles) — the value and the
    label must always move together (this feature's one hard requirement),
    so this is the single place either renderer touches a unit word.
    """
    if scale != "base":
        return label
    result = label
    for kilo, base in _LABEL_REPLACEMENTS:
        result = result.replace(kilo, base)
    return result


def format_cell(value: Any) -> str:
    """Format a field value verbatim (UTF-8-safe — for the xlsx renderer).

    ``None`` -> ``"-"``; a :class:`datetime` -> ISO with a space separator;
    everything else -> ``str()``.
    """
    if value is None:
        return "-"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)


def ascii_cell(value: Any) -> str:
    """:func:`format_cell` then ASCII-replace non-Latin characters.

    For the PDF renderer only — fpdf2's core fonts (``Helvetica``) are
    Latin-only, and the owner decided the document stays English rather than
    embed a font (issue #22 decision; ``docs/lib-notes/fpdf2-and-openpyxl.md``).
    """
    return format_cell(value).encode("ascii", "replace").decode("ascii")


def _measurement_section(title: str, prefix: str) -> list[tuple[str, str]]:
    """One measurement group's total-plus-four-tariff field list.

    Mirrors the column-naming scheme in ``db/models.py`` exactly
    (``<prefix>_total`` / ``<prefix>_rate_a``..``_rate_d``), so a mistyped
    prefix here would show up as a missing column in
    ``test_capture_render_shared.py``'s coverage check rather than silently
    rendering nothing.
    """
    return [
        (f"{title} Total", f"{prefix}_total"),
        (f"{title} Rate A", f"{prefix}_rate_a"),
        (f"{title} Rate B", f"{prefix}_rate_b"),
        (f"{title} Rate C", f"{prefix}_rate_c"),
        (f"{title} Rate D", f"{prefix}_rate_d"),
    ]


_SECTION_ENERGY = [
    *_measurement_section("Import Active kWh", "import_active_kwh"),
    *_measurement_section("Export Active kWh", "export_active_kwh"),
]

_SECTION_REACTIVE = [
    *_measurement_section("Import Reactive kvarh", "import_reactive_kvarh"),
    *_measurement_section("Export Reactive kvarh", "export_reactive_kvarh"),
]

_SECTION_DEMAND = [
    *_measurement_section("Max Demand Import Active kW", "max_demand_import_active_kw"),
    *_measurement_section("Max Demand Export Active kW", "max_demand_export_active_kw"),
    *_measurement_section("Max Demand Import Reactive kvar", "max_demand_import_reactive_kvar"),
    *_measurement_section("Max Demand Export Reactive kvar", "max_demand_export_reactive_kvar"),
]

# ── M4c, issue #24 — the twenty columns v1's screen has always shown ────────
# CONTEXT.md already carries the glossary entries for Demand Time and
# Cumulative Demand — these labels use those exact words (D18). Import side
# only (D10) — no screen shows the export side.
_SECTION_DEMAND_TIME = [
    *_measurement_section("Demand Time Import Active", "max_demand_import_active_time"),
    *_measurement_section("Demand Time Import Reactive", "max_demand_import_reactive_time"),
]

_SECTION_CUMULATIVE_DEMAND = [
    *_measurement_section("Cumulative Demand Import Active kW", "cumul_demand_import_active_kw"),
    *_measurement_section("Cumulative Demand Import Reactive kvar", "cumul_demand_import_reactive_kvar"),
]

_SECTION_META = [
    ("Bill Date", "bill_date"),
    ("Meter Serial", "meter_serial"),
    ("Record Status", "record_status"),
    ("Read At", "read_at"),
]

#: ``(section title, [(field label, row attribute name), ...])`` — the whole
#: capture content, in render order. Both renderers iterate this and nothing
#: else, so a field added here appears in both formats automatically.
#:
#: **Two sections, not four, for the M4c additions** (D18) — SPEC §3.6:709
#: said "เพิ่มอีก 4 หมวด" (four more sections), but ``_SECTION_DEMAND`` above
#: already bundles four *groups* into one section, so four sections here
#: would be inconsistent with the file's own established shape. "Demand Time"
#: and "Cumulative Demand" each bundle their two groups (import active /
#: import reactive) the same way.
ALL_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Energy (kWh)", _SECTION_ENERGY),
    ("Reactive Energy (kvarh)", _SECTION_REACTIVE),
    ("Maximum Demand", _SECTION_DEMAND),
    ("Demand Time", _SECTION_DEMAND_TIME),
    ("Cumulative Demand", _SECTION_CUMULATIVE_DEMAND),
    ("Metadata", _SECTION_META),
]
