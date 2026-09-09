"""Pure row/filename formatting for the export files — the Load Profile CSV
(M7 slice 3, issue #30) and, since M13, the billing CSV (issue 01) and the
Energy Summary file (issue 02). No I/O, no
DB access — given the same rows and settings this always produces the same
output; :mod:`arichds.export.writer` adds the UTF-8 BOM, the head-comparison
rule and the actual file write, none of which belong here.

**D-1 — the CSV never reads the display-unit setting (ADR 0013).** The
header is written once and rows append for months; an operator flipping kW/W
to read a *screen* must never leave a file whose header disagrees with its own
rows a thousandfold. The unit here is fixed at kWh/kvarh/kW/kvar — nothing in
this module divides a value by anything. Since M13 issue 07 this file carries
four **power** columns as well, which is the first time the boundary runs in
both directions on the same quantity: the Load Profile page scales those four
and this file never does.

**D-3 — cells are mapped by name, never by position.** :data:`_CSV_COLUMNS`
names the twenty-three attributes in :data:`_EXPORT_HEADERS`' order; a future
reorder of the shared ``MERGED_COLUMNS`` tuple in
:mod:`arichds.db.load_profile_query` cannot silently reorder this contract
file, because this module never imports that tuple.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from arichds.constants import METER_LOCAL_UTC_OFFSET_HOURS
from arichds.interval_status import decode_interval_status

#: F1 — the column headers, order frozen so a row appended to an existing file
#: still lands in the right column. Only the four energy strings differ from
#: v1's own header (D-4, owner ruling 2026-08-11): v1's "Import kWh Reactive"
#: names a kvarh quantity "kWh", and "Export kWh Re" is wrong in both name and
#: unit.
#:
#: **Twenty-five since M13 issue 07**, and in the customer's own order, which
#: inserts the three phase angles and the status column *before* ``Frequency
#: (Hz)`` rather than appending everything at the end. That moves an existing
#: column's position, and is only survivable because :mod:`arichds.export.writer`
#: closes the old file under a dated name when the head changes.
#:
#: Names continue this product's own convention rather than the customer's
#: spelling, which repeats v1's unit error (``Import kVar Reactive`` for a
#: kvar quantity) and carries stray whitespace; adopting it verbatim would
#: leave one file using two naming conventions. **The status column is the one
#: exception** — it keeps the customer's own header word, because the file
#: speaks their language while the product speaks the glossary's (the same
#: split ADR 0013 already draws, and the reason the stored column is named
#: ``interval_status_flag``).
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
    "Avg Phase Angle Ph-A",
    "Avg Phase Angle Ph-B",
    "Avg Phase Angle Ph-C",
    "Frequency (Hz)",
    "Record Status",
    "Import Active (kW)",
    "Import Reactive (kvar)",
    "Export Active (kW)",
    "Export Reactive (kvar)",
    "Voltage L1-L2 (V)",
    "Voltage L2-L3 (V)",
    "Voltage L3-L1 (V)",
)

#: The twenty-three measurement attribute names, in the same order as the
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
    "phase_angle_a",
    "phase_angle_b",
    "phase_angle_c",
    "freq",
    "interval_status_flag",
    "import_active_kw",
    "import_reactive_kvar",
    "export_active_kw",
    "export_reactive_kvar",
    "volt_l1_l2",
    "volt_l2_l3",
    "volt_l3_l1",
)

#: The one column that is not a number. Rendered through
#: :func:`~arichds.interval_status.decode_interval_status`, the same decoder the
#: Load Profile page's own column goes through, so the two can never word the
#: same bitmap differently.
_STATUS_COLUMN = "interval_status_flag"

#: Which columns are energy (formatted ``.9f``, v1 parity) — everything else
#: numeric in _CSV_COLUMNS is PF/V/I/frequency/phase-angle/power (``.3f``).
#: **Unchanged by M13 issue 07**: this file has an Output Parity obligation
#: against v1 that the two files added in this phase do not, so the eleven new
#: columns adopt its existing measurement format rather than the trimmed
#: decimals the billing and Energy files use.
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
            timezone-aware UTC ``datetime``) plus the twenty-three
            :data:`_CSV_COLUMNS` names, e.g. the ``Row._mapping`` objects
            :func:`arichds.db.load_profile_query.merged_rows_select` yields.
            A column this model does not record is absent or ``None`` and
            renders empty — never missing, so every meter's file has the same
            shape.
        device_label: The already-built ``"<name> (<serial>)"`` label — every
            row in one export call belongs to the same device (F2), so this
            is computed once by the caller, not per row.
        date_format: The operator's ``export_date_format`` token string
            (F3), translated once for the whole call.

    Returns:
        One list of twenty-five string cells per input row, in input order.
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
            if name == _STATUS_COLUMN:
                cells.append(decode_interval_status(row.get(name)))
                continue
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


# ─── The file header block (M13, issue 01) ────────────────────────────────────
# Every one of the customer's four sample files opens with the same block above
# the column header row, and every one of its values is already on the device
# row. It is what makes a file that has been copied out of its folder still say
# which meter it came from.


#: The literal the customer's own files carry, reproduced because their tooling
#: may count lines. **Nobody on either side knows what it means** — it appears
#: as `Setting : 1` in all four samples with no explanation anywhere, and there
#: is no setting in this product it corresponds to. Copying one constant line
#: costs nothing; omitting it would shift every line of a file some unknown
#: consumer reads by offset, with no error to notice.
_SETTING_LINE_VALUE = "1"


def file_header_block(*, customer: str | None, site_name: str, meter_serial: str, file_label: str) -> list[list[str]]:
    """Build the five-line block that opens an export file.

    Args:
        customer: The device's Customer, or ``None`` — a record-only field, so
            an empty cell is normal rather than an error.
        site_name: The device's Site Name (always present).
        meter_serial: The Meter Serial as it is written into the filename.
        file_label: ``"Load Profile"``, ``"Billing"`` or ``"Energy"`` — the
            sample files carry a bare label with no value beside it.

    Returns:
        Five ``[label, value]`` rows, in the customer's own order.
    """
    return [
        ["Customer :", customer or ""],
        ["Site Name :", site_name],
        ["Serial Meter :", meter_serial],
        ["Setting :", _SETTING_LINE_VALUE],
        [f"{file_label} :", ""],
    ]


# ─── The billing CSV (M13, issue 01) ──────────────────────────────────────────
# Twenty-four columns, in the customer's own order, always — their other
# program offers an operator a twenty-column variant, and a file that appends
# cannot carry a switchable shape.


#: How many decimals the customer's samples carry, with trailing zeros and a
#: trailing point trimmed: `9587.1515`, `1133.814`, and a plain `0`. The Load
#: Profile CSV's own `.9f`/`.3f` are untouched — that file answers to Output
#: Parity against v1, and this one has no such obligation because neither
#: product has ever produced it.
_BILLING_DECIMALS = 4

#: What a timestamp cell reads when the meter never set it — the customer's own
#: samples write this in exactly that case.
_NO_VALUE = "-"

#: A Demand Time this old is the meter's "never" sentinel, not a reading. A
#: SMART TCC returns local 2000-01-01 for a tariff whose demand was never
#: recorded; a CEWE returns NULL for the same thing. Both mean the same and
#: both must print :data:`_NO_VALUE` — an unfiltered sentinel prints as a date
#: a reader cannot tell from a real one.
_SENTINEL_BEFORE = 2001


#: ``(header, field, kind)`` per column, in file order. The header strings are
#: the customer's own, **including the 30-character truncation their producing
#: program applied** (`050T Previous Time of kW deman`): the OBIS-number prefix
#: still makes each unique, and un-truncating would mean inventing the text
#: that was cut off. The four Export headers are the exception — the customer's
#: files spell those four different ways, with stray double and leading spaces,
#: so they take the clean single-spaced form (owner ruling, A4).
_BILLING_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("Record No", "record_no", "int"),
    ("Time", "bill_date", "time"),
    ("111 Billing total kWh Total", "import_active_kwh_total", "num"),
    ("010 Billing total kWh Rate A", "import_active_kwh_rate_a", "num"),
    ("020 Billing total kWh Rate B", "import_active_kwh_rate_b", "num"),
    ("030 Billing total kWh Rate C", "import_active_kwh_rate_c", "num"),
    ("Billing total Export kWh Total", "export_active_kwh_total", "num"),
    ("Billing total Export kWh Rate A", "export_active_kwh_rate_a", "num"),
    ("Billing total Export kWh Rate B", "export_active_kwh_rate_b", "num"),
    ("Billing total Export kWh Rate C", "export_active_kwh_rate_c", "num"),
    ("050 Previous kW demand Rate A", "max_demand_import_active_kw_rate_a", "num"),
    ("050T Previous Time of kW deman", "max_demand_import_active_time_rate_a", "time"),
    ("060 Previous kW demand Rate B", "max_demand_import_active_kw_rate_b", "num"),
    ("060T Previous Time of kW deman", "max_demand_import_active_time_rate_b", "time"),
    ("070 Previous kW demand Rate C", "max_demand_import_active_kw_rate_c", "num"),
    ("070T Previous Time of kW deman", "max_demand_import_active_time_rate_c", "time"),
    ("015 Cumul kW demand Rate A", "cumul_demand_import_active_kw_rate_a", "num"),
    ("016 Cumul kW demand Rate B", "cumul_demand_import_active_kw_rate_b", "num"),
    ("017 Cumul kW demand Rate C", "cumul_demand_import_active_kw_rate_c", "num"),
    ("222 Billing total Varh Total", "import_reactive_kvarh_total", "num"),
    ("280 Previous Var demand Total", "max_demand_import_reactive_kvar_total", "num"),
    ("280T Previous Time of Var dem", "max_demand_import_reactive_time_total", "time"),
    ("118 Cumul Var demand Total", "cumul_demand_import_reactive_kvar_total", "num"),
    # Only closed periods are exported (the Open Period's Bill Date advances on
    # every read, ADR 0018), so this is constant — but constant and true beats
    # blank and ambiguous, and it already means something the day that
    # exclusion is reconsidered. It is NOT the Load Profile file's column of
    # the same name: that one is a per-interval word from the meter
    # (CONTEXT.md — Interval Status), this is a per-period state.
    ("Record Status", "record_status", "closed"),
)

#: The twenty-four headers, order frozen — a row appended to an existing file
#: must still land in the right column.
BILLING_EXPORT_HEADERS: tuple[str, ...] = tuple(header for header, _field, _kind in _BILLING_COLUMNS)

#: The reading attributes :func:`format_billing_rows` reads, so a caller builds
#: its mappings from one list rather than restating twenty-three names. Excludes
#: ``record_no``, which the query supplies rather than the row.
BILLING_FIELDS: tuple[str, ...] = tuple(field for _header, field, kind in _BILLING_COLUMNS if kind in {"num", "time"})


def _decimal(value: object) -> str:
    """Format one numeric cell the way the customer's samples do — at most
    :data:`_BILLING_DECIMALS` decimals, trailing zeros and a trailing point
    trimmed. Empty for ``None`` or a non-numeric cell (never ``"None"``,
    never ``"0"``)."""
    if value is None:
        return ""
    try:
        as_float = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    text = format(as_float, f".{_BILLING_DECIMALS}f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _timestamp(value: object, strftime_fmt: str) -> str:
    """Format one timestamp cell in meter-local time, or :data:`_NO_VALUE`.

    Both shapes of "the meter never set this" collapse to the same cell: a
    ``None`` (what a CEWE stores) and a pre-:data:`_SENTINEL_BEFORE` datetime
    (what a SMART TCC stores).
    """
    if not isinstance(value, datetime):
        return _NO_VALUE
    moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    local = moment + _ICT_OFFSET
    if local.year < _SENTINEL_BEFORE:
        return _NO_VALUE
    return local.strftime(strftime_fmt)


def format_billing_rows(rows: Sequence[Mapping[str, Any]], *, date_format: str) -> list[list[str]]:
    """Format closed Billing Readings into export cells (no header row).

    Args:
        rows: One mapping per period, carrying ``"record_no"`` plus every name
            in :data:`BILLING_FIELDS`. Ordered oldest first by the caller —
            this appends in the order it is given.
        date_format: The operator's ``export_date_format`` token string,
            shared with the Load Profile CSV and translated once per call.

    Returns:
        One list of twenty-four string cells per input row, in input order.
    """
    strftime_fmt = _translate_date_format(date_format)
    output: list[list[str]] = []
    for row in rows:
        cells: list[str] = []
        for _header, field, kind in _BILLING_COLUMNS:
            if kind == "closed":
                cells.append("closed")
            elif kind == "int":
                cells.append(str(row.get(field, "")))
            elif kind == "time":
                cells.append(_timestamp(row.get(field), strftime_fmt))
            else:
                cells.append(_decimal(row.get(field)))
        output.append(cells)
    return output


# ─── The Energy Summary file (M13, issue 02) ──────────────────────────────────
# The same eight Time-of-Use columns the Summary Report tab shows, and a Date.
# **No total row**, in either the daily file or the on-demand one: a total row
# cannot exist in a file that appends, and giving only the on-demand file one
# would leave two shapes to maintain for one concept. The total belongs to the
# screen.


#: ``(header, field)`` per column, in file order — the screen's own order.
_ENERGY_COLUMNS_OUT: tuple[tuple[str, str], ...] = (
    ("Date", "date"),
    ("Peak Import (kWh)", "peak_import_kwh"),
    ("Off-Peak Import (kWh)", "offpeak_import_kwh"),
    ("Holiday Import (kWh)", "holiday_import_kwh"),
    ("Total Import (kWh)", "total_import_kwh"),
    ("Peak Export (kWh)", "peak_export_kwh"),
    ("Off-Peak Export (kWh)", "offpeak_export_kwh"),
    ("Holiday Export (kWh)", "holiday_export_kwh"),
    ("Total Export (kWh)", "total_export_kwh"),
)

#: The nine headers, order frozen.
ENERGY_EXPORT_HEADERS: tuple[str, ...] = tuple(header for header, _field in _ENERGY_COLUMNS_OUT)

#: The date-only part of the operator's token format — the Energy Summary's row
#: key is a local calendar day, not an instant, so writing a time of day beside
#: it would invent a precision the number does not have.
_DATE_ONLY_TOKENS = ("yyyy", "mm", "dd")


def _date_only_format(token_format: str) -> str:
    """Strip everything after the last date token, so a format carrying a time
    still yields a date-only pattern.

    Falls back to ISO when the operator's format names no date token at all,
    rather than emitting an empty cell.
    """
    last = max((token_format.rfind(token) + len(token) for token in _DATE_ONLY_TOKENS), default=-1)
    date_part = token_format[:last].strip() if last > 0 else ""
    return _translate_date_format(date_part) if date_part else "%Y-%m-%d"


def format_energy_rows(days: Sequence[Any], *, date_format: str) -> list[list[str]]:
    """Format Energy Summary days into export cells (no header row).

    Args:
        days: One object per local day carrying ``date`` plus the eight
            Time-of-Use attributes — the same objects
            :func:`arichds.api.energy.energy_summary_rows` returns, passed
            straight through rather than re-shaped, so the file and the screen
            can never disagree about what a day's numbers are.
        date_format: The operator's ``export_date_format`` token string, of
            which only the date part is used.

    Returns:
        One list of nine string cells per day, in input order.
    """
    strftime_fmt = _date_only_format(date_format)
    output: list[list[str]] = []
    for day in days:
        cells = [day.date.strftime(strftime_fmt)]
        cells.extend(_decimal(getattr(day, field)) for _header, field in _ENERGY_COLUMNS_OUT[1:])
        output.append(cells)
    return output


__all__ = [
    "BILLING_EXPORT_HEADERS",
    "BILLING_FIELDS",
    "ENERGY_EXPORT_HEADERS",
    "file_header_block",
    "format_billing_rows",
    "format_energy_rows",
    "format_rows",
    "render_filename",
]
