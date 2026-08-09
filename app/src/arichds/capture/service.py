"""Wires the renderers and the hardened write together (M6b, issue #22).

The one place :mod:`arichds.acquisition.billing` (the eager write, after a
closed period commits) and :mod:`arichds.api.billing` (the render-on-miss
download) both build a path and write a file, so the two callers cannot drift
in how a path is derived or how a write is hardened.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arichds.capture.paths import sanitize_meter_serial
from arichds.capture.pdf import render_billing_pdf
from arichds.capture.write import write_capture
from arichds.capture.xlsx import render_billing_xlsx

logger = logging.getLogger(__name__)


def capture_target_paths(capture_dir: Path, meter_serial: str, bill_date: datetime) -> tuple[Path, Path]:
    """The fixed convention path for both formats (decision 15, ADR 0010) —
    never stored in the database, derived fresh on every render/write/download.

    ``<capture_dir>/<meter_serial>/<bill_date UTC as %Y-%m-%d_%H%M%S>.{pdf,xlsx}``

    Args:
        capture_dir: The current ``capture_dir`` setting value.
        meter_serial: The row's ``meter_serial`` snapshot.
        bill_date: The row's ``bill_date`` — naive values are treated as UTC
            (SQLite hands back naive datetimes for a ``DateTime(timezone=True)``
            column; every stored timestamp in this product is UTC).

    Returns:
        ``(pdf_path, xlsx_path)``, both resolved absolute paths.

    Raises:
        ValueError: *meter_serial* fails :func:`~arichds.capture.paths.sanitize_meter_serial`.
    """
    serial = sanitize_meter_serial(meter_serial)
    aware = bill_date if bill_date.tzinfo is not None else bill_date.replace(tzinfo=UTC)
    stem = aware.astimezone(UTC).strftime("%Y-%m-%d_%H%M%S")
    base = capture_dir.resolve() / serial / stem
    return base.with_suffix(".pdf"), base.with_suffix(".xlsx")


def write_pdf_capture(row: Any, device_name: str, target: Path, capture_dir: Path) -> None:
    """Render and hardened-write the PDF capture for *row* at *target*."""
    allowlist = [capture_dir.resolve()]
    write_capture(target, lambda: render_billing_pdf(row, device_name), allowlist)


def write_xlsx_capture(row: Any, device_name: str, target: Path, capture_dir: Path) -> None:
    """Render and hardened-write the xlsx capture for *row* at *target*."""
    allowlist = [capture_dir.resolve()]
    write_capture(target, lambda: render_billing_xlsx(row, device_name), allowlist)


def capture_reading(row: Any, device_name: str, capture_dir: Path, *, write_excel: bool) -> None:
    """Write the PDF (and, when *write_excel*, the xlsx) capture for one
    closed Billing Reading.

    A row whose ``meter_serial`` is ``None`` or fails sanitisation gets no
    capture — logged and skipped, never raised (decision 15, issue #22): a
    capture failure must never look like a billing-read failure to the caller.

    The xlsx write is a side effect of the PDF write (decision 13 — it is
    only ever written alongside a PDF) and never undoes it: an xlsx failure
    is logged and swallowed here, mirroring v1's ``_write_xlsx_capture``. A
    PDF write failure propagates to the caller, which is expected to catch it
    per-reading (:mod:`arichds.acquisition.billing`) or per-request
    (:mod:`arichds.api.billing`).

    Args:
        row: Anything :func:`~arichds.capture.pdf.render_billing_pdf` accepts
            — an ORM row read inside an open session, or a ``SimpleNamespace``.
        device_name: Raw device name for the document header.
        capture_dir: The current ``capture_dir`` setting value.
        write_excel: Whether ``billing_excel_export`` is enabled.
    """
    if getattr(row, "meter_serial", None) is None:
        logger.warning("Capture skipped for %s bill_date %s — no meter_serial stored", device_name, row.bill_date)
        return

    try:
        pdf_target, xlsx_target = capture_target_paths(capture_dir, row.meter_serial, row.bill_date)
    except ValueError as exc:
        logger.warning("Capture skipped for %s bill_date %s — %s", device_name, row.bill_date, exc)
        return

    write_pdf_capture(row, device_name, pdf_target, capture_dir)

    if write_excel:
        try:
            write_xlsx_capture(row, device_name, xlsx_target, capture_dir)
        except Exception:  # noqa: BLE001 — a side effect; the PDF result must survive (v1 parity).
            logger.exception("xlsx capture failed for %s bill_date %s (PDF unaffected)", device_name, row.bill_date)
