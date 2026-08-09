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
from typing import Any

__all__ = ["ALL_SECTIONS", "ascii_cell", "format_cell"]


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

_SECTION_META = [
    ("Bill Date", "bill_date"),
    ("Meter Serial", "meter_serial"),
    ("Record Status", "record_status"),
    ("Read At", "read_at"),
]

#: ``(section title, [(field label, row attribute name), ...])`` — the whole
#: capture content, in render order. Both renderers iterate this and nothing
#: else, so a field added here appears in both formats automatically.
ALL_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Energy (kWh)", _SECTION_ENERGY),
    ("Reactive Energy (kvarh)", _SECTION_REACTIVE),
    ("Maximum Demand", _SECTION_DEMAND),
    ("Metadata", _SECTION_META),
]
