"""PDF rendering for a closed Billing Reading (M6b, issue #22).

Ported from v1 ``cewe-worker/src/billing/pdf.py``, updated to fpdf2 2.8.7's
current API per ``docs/lib-notes/fpdf2-and-openpyxl.md``: the ``text=``
keyword (not ``txt=``), ``new_x``/``new_y`` (not the deprecated ``ln=``), and
``bytes(pdf.output())`` (``output()`` returns a ``bytearray``).
"""

from __future__ import annotations

import functools
import logging
from typing import Any

from fpdf import FPDF

from arichds.capture._render_shared import ALL_SECTIONS, ascii_cell

logger = logging.getLogger(__name__)

_PAGE_MARGIN = 8.0  # mm
_HEADER_H = 6.0  # mm per header line
_ROW_H = 5.5  # mm per data row
_SECTION_GAP = 3.0  # mm between sections


@functools.lru_cache(maxsize=256)
def _warn_non_ascii_once(original: str, replaced: str) -> None:
    """WARN once per distinct non-ASCII name (v1 ``pdf.py:24-30``) — not once
    per render, or one recurring operator name would flood the log forever."""
    logger.warning("render_billing_pdf: non-ASCII device name %r replaced with %r", original, replaced)


def render_billing_pdf(row: Any, device_name: str) -> bytes:
    """Render one closed Billing Reading as a landscape A4 PDF.

    Never touches the filesystem — the caller is responsible for the hardened
    write (:mod:`arichds.capture.write`).

    Args:
        row: Anything exposing the ``BillingReading`` field names as
            attributes named in :data:`~arichds.capture._render_shared.ALL_SECTIONS`
            (the ORM row, or a ``SimpleNamespace``).
        device_name: Raw device name for the header. Non-ASCII is replaced
            with ``?`` and warned once — the document is English by owner
            decision (issue #22); no embedded font.

    Returns:
        Complete PDF bytes.
    """
    ascii_name = ascii_cell(device_name)
    if device_name != ascii_name:
        _warn_non_ascii_once(device_name, ascii_name)

    meter_serial = ascii_cell(getattr(row, "meter_serial", None) or "unknown")
    bill_date_str = ascii_cell(getattr(row, "bill_date", None))

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_margins(_PAGE_MARGIN, _PAGE_MARGIN, _PAGE_MARGIN)
    pdf.set_auto_page_break(auto=True, margin=_PAGE_MARGIN)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, _HEADER_H + 2, text="ARICHDS Billing Report", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, _HEADER_H, text=f"Device: {ascii_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, _HEADER_H, text=f"Meter Serial: {meter_serial}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, _HEADER_H, text=f"Bill Date: {bill_date_str}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(_SECTION_GAP)

    effective_w = pdf.w - 2 * _PAGE_MARGIN
    label_w = effective_w * 0.38
    value_w = effective_w * 0.62

    for section_title, fields in ALL_SECTIONS:
        pdf.set_fill_color(210, 220, 240)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, _ROW_H, text=f"  {section_title}", fill=True, new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 8)
        fill = False
        for label, attr in fields:
            value_str = ascii_cell(getattr(row, attr, None))
            pdf.set_fill_color(248, 249, 252)
            pdf.cell(label_w, _ROW_H, text=f"  {label}", border=1, fill=fill, new_x="RIGHT", new_y="TOP")
            pdf.cell(value_w, _ROW_H, text=f"  {value_str}", border=1, fill=False, new_x="LMARGIN", new_y="NEXT")
            fill = not fill

        pdf.ln(_SECTION_GAP)

    return bytes(pdf.output())
