"""Shared ProfileGeneric column-mapping machinery — load profile & billing
(D5/D6, issue #24).

The position map and the per-row field-building loop are identical across
every DLMS meter model this product drives; only the **transport** — how the
buffer is actually fetched (SMW110W4's hand-driven 43-column span vs the CEWE
models' full-width entry/range read) — differs and stays inside each driver's
own ``read_load_profile()`` / ``read_billing()`` (D6).

Keying on ``(OBIS, attribute)`` rather than OBIS alone is what stops a
max-demand value (attribute 2) and its own capture time (attribute 5) — which
share one OBIS code, F2 — from colliding into the same position (D5). v1 keys
the same way (F1) and that is why it absorbs a 69/73/104/148-column layout
with no per-model branch.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from gurux_dlms import GXDLMSClient
from gurux_dlms.enums.DataType import DataType

from arichds.constants import METER_LOCAL_UTC_OFFSET_HOURS


def coerce_clock_cell(value: Any) -> datetime | None:
    """Defensively coerce a ProfileGeneric clock/time cell to a plain ``datetime``.

    Gurux hands back a clock cell as a ``GXDateTime`` (the value lives on
    ``.value``, never the object itself — gurux-dlms skill, patterns.md's
    "GXDateTime handling"), a plain ``datetime``, a raw ``bytearray`` when the
    schema was not fully typed, or ``None`` for a time-compressed row. ``None``
    out means the cell has no usable timestamp — the caller skips it (a row
    clock) or leaves it ``None`` (a Demand Time column, D11) rather than
    inventing one.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "value") and isinstance(value.value, datetime):
        return value.value
    if isinstance(value, (bytes, bytearray)):
        decoded = GXDLMSClient.changeType(value, DataType.DATETIME)
        if decoded is not None and isinstance(getattr(decoded, "value", None), datetime):
            return decoded.value
    return None


def meter_local_to_utc(local_dt: datetime) -> datetime:
    """Convert a meter-local clock reading to timezone-aware UTC.

    Every CEWE and SMW110W4 unit in service stores buffer timestamps in
    meter-local time (ICT, UTC+7 — no DST) rather than UTC (gurux-dlms skill,
    "Meter-local time in selective access";
    :data:`~arichds.constants.METER_LOCAL_UTC_OFFSET_HOURS`). A naive cell is
    the normal case; an aware one is handled the same way
    ``datetime.astimezone`` always is, rather than assumed away.
    """
    if local_dt.tzinfo is not None:
        return local_dt.astimezone(UTC)
    offset = timedelta(hours=METER_LOCAL_UTC_OFFSET_HOURS)
    return (local_dt - offset).replace(tzinfo=UTC)


def positions_by_obis_attr(capture_objects: list[tuple[Any, Any]]) -> dict[tuple[str, int], int]:
    """``{(obis, attribute_index): position}`` for a live ``captureObjects`` list.

    Args:
        capture_objects: ``pg.captureObjects`` — a list of
            ``(cosem_object, capture_definition)`` pairs, where the object
            carries ``.logicalName`` and the capture definition carries
            ``.attributeIndex``.

    Returns:
        Each column's zero-based position in the row, keyed on the pair that
        actually identifies it.
    """
    return {
        (str(obj.logicalName), int(capture_def.attributeIndex)): i
        for i, (obj, capture_def) in enumerate(capture_objects)
    }


def build_fields(
    row: list[Any],
    positions: dict[tuple[str, int], int],
    column_map: dict[tuple[str, int], str],
    multipliers: dict[tuple[str, int], float | None],
    *,
    scale: Callable[[str, float], float | None],
    passthrough_keys: frozenset[tuple[str, int]] | set[tuple[str, int]] = frozenset(),
) -> dict[str, Any]:
    """Turn one raw row into ``{field: value}`` for every mapped column.

    Shared by every driver's load-profile and billing read (D6) — the loop
    itself (look up position, look up multiplier, guard non-numeric, scale)
    is identical; only *which* columns are mapped and how they scale differs,
    and those come in as arguments.

    Args:
        row: One raw row from the meter, aligned to the live capture list.
        positions: This read's ``(obis, attr) -> index`` map
            (:func:`positions_by_obis_attr`).
        column_map: ``(obis, attr) -> field name`` for every column this
            driver maps.
        multipliers: ``(obis, attr) -> multiplier`` for the numeric columns —
            a column absent here, or mapping to ``None``, stays ``None`` on
            every row rather than storing an unscaled number that looks like
            data.
        scale: Called as ``scale(field, raw * multiplier)`` for a numeric
            column that resolved a multiplier — e.g. ``self._normalize`` for
            a load-profile column, or ``lambda f, v: v / WH_TO_KWH_DIVISOR``
            for a billing column.
        passthrough_keys: Columns that are **not** numeric — e.g. a Demand
            Time capture-time cell (D11): the raw cell (already converted to
            UTC by the caller) is stored as-is, never multiplied and never
            passed through ``scale``. A key in both ``column_map`` and
            ``passthrough_keys`` skips the multiplier/numeric guard entirely.

    Returns:
        ``{field: value}`` for every column in *column_map* — ``None`` for a
        column with no position, no multiplier, or a non-numeric raw cell
        (unless it is a passthrough column).
    """
    fields: dict[str, Any] = {}
    for key, field in column_map.items():
        pos = positions.get(key)
        raw = row[pos] if pos is not None else None

        if key in passthrough_keys:
            fields[field] = raw
            continue

        multiplier = multipliers.get(key)
        if raw is None or multiplier is None or not isinstance(raw, (Decimal, int, float)):
            fields[field] = None
        else:
            fields[field] = scale(field, float(raw) * multiplier)
    return fields
