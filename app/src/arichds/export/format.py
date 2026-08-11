"""Pure row/filename formatting for the Load Profile CSV export (M7 slice 3,
issue #30). No I/O, no DB access — given the same merged rows and settings
this always produces the same output; the CSV exporter
(:mod:`arichds.export.csv_export`) adds the UTF-8 BOM, the header-on-empty
rule and the actual file write, none of which belong here.

**D-1 — the CSV never reads the display-unit setting (ADR 0013).** The
header is written once, when the file is absent or empty, and rows append
for months; an operator flipping kW/W to read a *screen* must never leave a
file whose header disagrees with its own rows a thousandfold. The unit here
is fixed at kWh/kvarh — nothing in this module divides a value by anything.

**D-3 — cells are mapped by name, never by position.** :data:`_CSV_COLUMNS`
names the twelve attributes in :data:`_EXPORT_HEADERS`' order; a future
reorder of the shared ``MERGED_COLUMNS`` tuple in
:mod:`arichds.db.load_profile_query` cannot silently reorder this contract
file, because this module never imports that tuple.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, timedelta
from typing import Any

from arichds.constants import METER_LOCAL_UTC_OFFSET_HOURS

#: F1 — the fourteen column headers, order frozen so a row appended to an
#: existing v1 file still lands in the right column. Only the four energy
#: strings differ from v1's own header (D-4, owner ruling 2026-08-11):
#: v1's "Import kWh Reactive" names a kvarh quantity "kWh", and "Export kWh
#: Re" is wrong in both name and unit.
_EXPORT_HEADERS: tuple[str, ...] = (
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

#: The twelve measurement attribute names, in the same order as the twelve
#: trailing entries of :data:`_EXPORT_HEADERS` (F1) — written out literally
#: here rather than imported from ``db.load_profile_query.MERGED_COLUMNS``
#: (D-3): a future reorder of that tuple must not silently reorder this
#: contract file.
_CSV_COLUMNS: tuple[str, ...] = (
    "import_active_kwh",
    "import_reactive_kvarh",
    "export_active_kwh",
    "export_reactive_kvarh",
    "avg_geo_pf",
    "volt_l1",
    "volt_l2",
    "volt_l3",
    "current_l1",
    "current_l2",
    "current_l3",
    "freq",
)

#: Which of the twelve columns are energy (formatted ``.9f``, v1 parity) —
#: everything else in _CSV_COLUMNS is PF/V/I/frequency (``.3f``).
_ENERGY_COLUMNS: frozenset[str] = frozenset(
    {"import_active_kwh", "import_reactive_kvarh", "export_active_kwh", "export_reactive_kvarh"}
)

_ENERGY_FORMAT = ".9f"
_MEASUREMENT_FORMAT = ".3f"

#: F3 — display-token to strftime translation for the ``export_date_format``
#: setting. Longest tokens first so "MM" is consumed before a lone "M"
#: could be. ``mm`` (lowercase) is month, ``MM`` (uppercase) is minute.
_DATE_FORMAT_TOKENS: tuple[tuple[str, str], ...] = (
    ("yyyy", "%Y"),
    ("mm", "%m"),
    ("dd", "%d"),
    ("HH", "%H"),
    ("MM", "%M"),
    ("SS", "%S"),
)

_ICT_OFFSET = timedelta(hours=METER_LOCAL_UTC_OFFSET_HOURS)


def _translate_date_format(token_format: str) -> str:
    """Translate an Excel-style token format to a Python strftime pattern.

    Tokens are replaced left-to-right without re-scanning, so an
    already-substituted ``%`` code is never touched by a later token.

    Args:
        token_format: An Excel-style date format string, e.g.
            ``"yyyy-mm-dd HH:MM:SS"``.

    Returns:
        The equivalent Python ``strftime`` pattern.
    """
    result: list[str] = []
    i = 0
    while i < len(token_format):
        for token, code in _DATE_FORMAT_TOKENS:
            if token_format.startswith(token, i):
                result.append(code)
                i += len(token)
                break
        else:
            result.append(token_format[i])
            i += 1
    return "".join(result)


def _num(value: object, fmt: str) -> str:
    """Format one numeric cell; the empty string when *value* is ``None`` or
    non-numeric (F2) — never ``"None"``, never ``0``."""
    if value is None:
        return ""
    try:
        as_float = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    return format(as_float, fmt)


def format_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    device_label: str,
    date_format: str,
) -> list[list[str]]:
    """Format merged Interval Reading rows into export cells (no header row).

    Args:
        rows: Merged rows — each a mapping carrying ``"read_at"`` (a
            timezone-aware UTC ``datetime``) plus the twelve
            :data:`_CSV_COLUMNS` names, e.g. the ``Row._mapping`` objects
            :func:`arichds.db.load_profile_query.merged_rows_select` yields.
        device_label: The already-built ``"<name> (<serial>)"`` label — every
            row in one export call belongs to the same device (F2), so this
            is computed once by the caller, not per row.
        date_format: The operator's ``export_date_format`` token string
            (F3), translated once for the whole call.

    Returns:
        One list of fourteen string cells per input row, in input order.
    """
    strftime_fmt = _translate_date_format(date_format)
    output: list[list[str]] = []
    for row in rows:
        read_at = row["read_at"]
        if read_at.tzinfo is None:
            # SQLite hands back naive datetimes; every stored read_at is UTC.
            read_at = read_at.replace(tzinfo=UTC)
        read_at_ict = read_at + _ICT_OFFSET  # UTC -> ICT (+7), F2.

        cells = [device_label, read_at_ict.strftime(strftime_fmt)]
        for name in _CSV_COLUMNS:
            fmt = _ENERGY_FORMAT if name in _ENERGY_COLUMNS else _MEASUREMENT_FORMAT
            cells.append(_num(row.get(name), fmt))
        output.append(cells)
    return output


def render_filename(template: str, meter_token: str) -> str:
    """Substitute the ``[meter]``/``[serial]``/``[date]`` filename tokens (F4).

    Args:
        template: The operator's ``export_csv_filename_tmpl`` value, e.g.
            ``"[meter].csv"``.
        meter_token: The sanitized meter serial — substituted for both
            ``[meter]`` and ``[serial]`` (v1 parity: the two tokens have
            always meant the same thing).

    Returns:
        The rendered filename with every token substituted.
    """
    filename = template.replace("[meter]", meter_token)
    filename = filename.replace("[serial]", meter_token)
    filename = filename.replace("[date]", date.today().isoformat())
    return filename


__all__ = ["format_rows", "render_filename"]
