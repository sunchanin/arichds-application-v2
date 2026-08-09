"""Excel (.xlsx) rendering for a closed Billing Reading (M6b, issue #22).

Ported from v1 ``cewe-worker/src/billing/xlsx.py``. Mirrors the PDF renderer's
sections exactly — both import :data:`~arichds.capture._render_shared.ALL_SECTIONS`
rather than declaring the field list twice, so they cannot drift.

Unlike the PDF path, values are formatted with
:func:`~arichds.capture._render_shared.format_cell` (no ASCII stripping) —
openpyxl writes UTF-8 natively, so a non-ASCII device name is preserved
verbatim here even though the PDF replaces it with ``?``. That asymmetry is
intended (``docs/lib-notes/fpdf2-and-openpyxl.md``).
"""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook

from arichds.capture._render_shared import ALL_SECTIONS, format_cell


def render_billing_xlsx(row: Any, device_name: str) -> bytes:
    """Render one closed Billing Reading as an .xlsx workbook.

    Never touches the filesystem — ``save()`` writes into an in-memory
    buffer, so the caller's hardened write (:mod:`arichds.capture.write`) is
    what actually creates a file.

    Args:
        row: Same shape :func:`arichds.capture.pdf.render_billing_pdf` takes.
        device_name: Raw device name for the header block — preserved
            verbatim (UTF-8).

    Returns:
        Complete .xlsx bytes.
    """
    meter_serial = format_cell(getattr(row, "meter_serial", None))

    wb = Workbook()
    sheet = wb.active
    sheet.title = "Billing"

    sheet.append(["Device", format_cell(device_name)])
    sheet.append(["Meter Serial", meter_serial])
    sheet.append(["Bill Date", format_cell(getattr(row, "bill_date", None))])
    sheet.append([])

    for section_title, fields in ALL_SECTIONS:
        sheet.append([section_title])
        for label, attr in fields:
            sheet.append([label, format_cell(getattr(row, attr, None))])
        sheet.append([])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
