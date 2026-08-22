"""PNG rendering for the Billing History table (M7 slice 4, issue #35,
ADR 0014, ADR 0015).

The third renderer over :mod:`arichds.capture._render_shared` — drawn with
Pillow rather than screenshotted (ADR 0014: nothing is looking at a page when
this is written, so there is no screen to photograph). Unlike
:mod:`arichds.capture.pdf` / :mod:`arichds.capture.xlsx`, which each render
**one** closed Billing Reading, this renders **up to ten** — the caller
selects and orders those rows (D4/D6, issue #35); this module never queries,
sorts, or truncates.

Signatures and every colour/spacing choice are read out of the installed
Pillow 12.3.0 package per ``docs/lib-notes/pillow-imagedraw.md`` — no
filesystem font, no truetype lookup (D9): :func:`PIL.ImageFont.load_default`
called with a ``size`` returns a real scalable face backed by bytes embedded
in the PIL package itself, so this can never fail on a missing font file.
"""

from __future__ import annotations

import functools
import io
import logging
from collections.abc import Sequence
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from arichds.capture._render_shared import MEASUREMENT_SECTIONS, DisplayUnitScale, ascii_cell, scale_label, scale_value

logger = logging.getLogger(__name__)

#: The product's deep teal (`web/src/theme.ts:13`) — used for the header band
#: so the image reads as this program's own table (ADR 0014).
_TEAL = "#0f766e"
_WHITE = "#ffffff"
_GRID = "#d9dde3"
_ROW_ALT = "#f4f6fa"
_TEXT = "#111827"

_TITLE_SIZE = 20.0
_HEADER_SIZE = 12.0
_BODY_SIZE = 12.0
_PAD_X = 8
_PAD_Y = 6
_MARGIN = 14
_LINE_GAP = 4

_RATE_CHILD_LABELS: tuple[str, ...] = ("Total", "Rate A", "Rate B", "Rate C", "Rate D")
_RATE_SUFFIXES: tuple[str, ...] = ("total", "rate_a", "rate_b", "rate_c", "rate_d")


@functools.lru_cache(maxsize=256)
def _warn_non_ascii_once(original: str, replaced: str) -> None:
    """WARN once per distinct non-ASCII name — same treatment as
    ``pdf.py:_warn_non_ascii_once``, not once per render."""
    logger.warning("render_billing_png: non-ASCII device name %r replaced with %r", original, replaced)


def measurement_column_groups(scale: DisplayUnitScale = "kilo") -> list[tuple[str, list[tuple[str, str]]]]:
    """``(group title, [(child label, row attribute), ...])`` for every
    measurement column group the grouped header draws, in render order (D7).

    One group per :data:`~arichds.capture._render_shared.MEASUREMENT_SECTIONS`
    entry — 12 groups, 60 leaf columns total, each group with exactly the
    five rate children in ``Total, Rate A, Rate B, Rate C, Rate D`` order,
    matching the Billing page's own ``buildColumns()`` grouping
    (``web/src/pages/Billing.tsx:113-149``). Exposed as a module-level
    function so tests can assert against the drawn column model directly
    (Step 8, T2/T3/T17) rather than parsing pixels.

    ``Metadata`` (``Record Status`` / ``Read At``) is never included — see D7.
    """
    groups: list[tuple[str, list[tuple[str, str]]]] = []
    for _section_title, section_groups in MEASUREMENT_SECTIONS:
        for group_title, prefix in section_groups:
            children = [
                (label, f"{prefix}_{suffix}") for label, suffix in zip(_RATE_CHILD_LABELS, _RATE_SUFFIXES, strict=True)
            ]
            groups.append((scale_label(group_title, scale), children))
    return groups


def _font(size: float) -> ImageFont.FreeTypeFont:
    """``ImageFont.load_default(size=...)`` only (D9) — a real scalable face
    backed by bytes embedded in the PIL package, never a filesystem lookup."""
    return ImageFont.load_default(size=size)


def _cell_text(row: Any, attr: str, scale: DisplayUnitScale) -> str:
    """One leaf cell's rendered value — ``scale_value`` then ``ascii_cell``,
    the same pairing ``pdf.py`` applies (D10). ``ascii_cell(None)`` already
    yields ``"-"`` (``format_cell``'s rule), so an absent measurement needs no
    special case here."""
    raw = getattr(row, attr, None)
    return ascii_cell(scale_value(raw, attr, scale))


def render_billing_png(
    rows: Sequence[Any],
    device_name: str,
    scale: DisplayUnitScale = "kilo",
) -> bytes:
    """Render the Billing History table (up to ten closed periods) as a PNG.

    Never touches the filesystem — the caller is responsible for the
    hardened write (:mod:`arichds.capture.write`), exactly like
    :func:`~arichds.capture.pdf.render_billing_pdf` and
    :func:`~arichds.capture.xlsx.render_billing_xlsx`.

    Args:
        rows: Already ordered newest-``bill_date``-first and already limited
            to at most ten (D4/D5/D6) — this function does not query, sort,
            or truncate. Anything exposing the ``BillingReading`` field names
            as attributes (the ORM row, or a ``SimpleNamespace``). May be
            empty (an edge case the caller should not hit in practice, since
            the anchor row is always one of the rows, but never raises here).
        device_name: Raw device name for the header block. Non-ASCII is
            replaced with ``?`` and warned once (D9's font has no non-Latin
            glyphs — the same rule ``pdf.py`` follows).
        scale: The machine-wide display-unit setting — ``"kilo"`` (default)
            or ``"base"``. Applied to every value/label pair together
            (:func:`~arichds.capture._render_shared.scale_value` /
            :func:`~arichds.capture._render_shared.scale_label`), exactly
            like the other two renderers (D10).

    Returns:
        Complete PNG bytes.
    """
    ascii_name = ascii_cell(device_name)
    if device_name != ascii_name:
        _warn_non_ascii_once(device_name, ascii_name)

    meter_serial = ascii_cell(getattr(rows[0], "meter_serial", None)) if rows else "-"

    title_font = _font(_TITLE_SIZE)
    header_font = _font(_HEADER_SIZE)
    body_font = _font(_BODY_SIZE)

    measure_img = Image.new("RGB", (1, 1))
    measure_draw = ImageDraw.Draw(measure_img)

    def text_w(text: str, font: ImageFont.FreeTypeFont) -> float:
        return measure_draw.textlength(text, font=font)

    def line_h(font: ImageFont.FreeTypeFont) -> float:
        bbox = measure_draw.textbbox((0, 0), "Hg0", font=font)
        return bbox[3] - bbox[1]

    groups = measurement_column_groups(scale)

    # ── Column widths — measured from the header labels and every rendered
    # value, never a hardcoded guess (the table is ~61 leaf columns wide, so
    # a fixed width would silently truncate columns). ─────────────────────
    bill_date_values = [ascii_cell(getattr(row, "bill_date", None)) for row in rows]
    bill_date_w = (
        max([text_w("Bill Date", header_font), *[text_w(v, body_font) for v in bill_date_values]]) + 2 * _PAD_X
    )

    leaf_widths: list[list[float]] = []  # per group, one width per child column
    for _group_title, children in groups:
        widths = []
        for label, attr in children:
            values = [_cell_text(row, attr, scale) for row in rows]
            content_w = max([text_w(label, header_font), *[text_w(v, body_font) for v in values]])
            widths.append(content_w + 2 * _PAD_X)
        leaf_widths.append(widths)

    for (group_title, _children), widths in zip(groups, leaf_widths, strict=True):
        group_w_needed = text_w(group_title, header_font) + 2 * _PAD_X
        deficit = group_w_needed - sum(widths)
        if deficit > 0:
            share = deficit / len(widths)
            for i in range(len(widths)):
                widths[i] += share

    table_w = bill_date_w + sum(sum(widths) for widths in leaf_widths)

    header_row_h = line_h(header_font) + 2 * _PAD_Y
    body_row_h = line_h(body_font) + 2 * _PAD_Y
    group_header_h = header_row_h
    child_header_h = header_row_h
    table_header_h = group_header_h + child_header_h

    title_h = line_h(title_font) + _LINE_GAP
    detail_h = line_h(header_font) + _LINE_GAP
    header_block_h = title_h + detail_h * 2 + _LINE_GAP

    canvas_w = int(2 * _MARGIN + table_w)
    canvas_h = int(2 * _MARGIN + header_block_h + table_header_h + body_row_h * len(rows))

    img = Image.new("RGB", (canvas_w, canvas_h), _WHITE)
    draw = ImageDraw.Draw(img)

    # ── Header block ─────────────────────────────────────────────────────
    y = float(_MARGIN)
    draw.text((_MARGIN, y), "ARICHDS Billing History", font=title_font, fill=_TEXT)
    y += title_h
    draw.text((_MARGIN, y), f"Device: {ascii_name}", font=header_font, fill=_TEXT)
    y += detail_h
    draw.text((_MARGIN, y), f"Meter Serial: {meter_serial}", font=header_font, fill=_TEXT)
    y += detail_h + _LINE_GAP

    table_top = y
    x = float(_MARGIN)

    # ── Bill Date column — one cell spanning both header rows ───────────
    draw.rectangle([x, table_top, x + bill_date_w, table_top + table_header_h], fill=_TEAL, outline=_GRID)
    draw.text(
        (x + bill_date_w / 2, table_top + table_header_h / 2),
        "Bill Date",
        font=header_font,
        fill=_WHITE,
        anchor="mm",
    )
    x += bill_date_w

    # ── Grouped header — group title row, then the five rate-child cells ─
    for (group_title, children), widths in zip(groups, leaf_widths, strict=True):
        group_w = sum(widths)
        draw.rectangle([x, table_top, x + group_w, table_top + group_header_h], fill=_TEAL, outline=_GRID)
        draw.text(
            (x + group_w / 2, table_top + group_header_h / 2), group_title, font=header_font, fill=_WHITE, anchor="mm"
        )
        child_x = x
        for (label, _attr), width in zip(children, widths, strict=True):
            draw.rectangle(
                [child_x, table_top + group_header_h, child_x + width, table_top + table_header_h],
                fill=_TEAL,
                outline=_GRID,
            )
            draw.text(
                (child_x + width / 2, table_top + group_header_h + child_header_h / 2),
                label,
                font=header_font,
                fill=_WHITE,
                anchor="mm",
            )
            child_x += width
        x += group_w

    # ── Data rows — drawn in the order given, never re-sorted (D6) ──────
    row_top = table_top + table_header_h
    for row_index, row in enumerate(rows):
        row_fill = _ROW_ALT if row_index % 2 == 1 else _WHITE
        y0 = row_top + row_index * body_row_h
        y1 = y0 + body_row_h

        x = float(_MARGIN)
        draw.rectangle([x, y0, x + bill_date_w, y1], fill=row_fill, outline=_GRID)
        draw.text(
            (x + _PAD_X, y0 + body_row_h / 2), bill_date_values[row_index], font=body_font, fill=_TEXT, anchor="lm"
        )
        x += bill_date_w

        for (_group_title, children), widths in zip(groups, leaf_widths, strict=True):
            for (_label, attr), width in zip(children, widths, strict=True):
                value = _cell_text(row, attr, scale)
                draw.rectangle([x, y0, x + width, y1], fill=row_fill, outline=_GRID)
                draw.text((x + _PAD_X, y0 + body_row_h / 2), value, font=body_font, fill=_TEXT, anchor="lm")
                x += width

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()
