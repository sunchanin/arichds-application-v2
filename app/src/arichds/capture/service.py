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

from sqlalchemy import select
from sqlalchemy.orm import object_session
from sqlalchemy.orm.exc import UnmappedInstanceError

from arichds.capture._render_shared import DisplayUnitScale
from arichds.capture.paths import sanitize_meter_serial
from arichds.capture.pdf import render_billing_pdf
from arichds.capture.png import render_billing_png
from arichds.capture.write import write_capture
from arichds.capture.xlsx import render_billing_xlsx
from arichds.db.models import BillingReading as BillingReadingRow

logger = logging.getLogger(__name__)


def capture_target_paths(capture_dir: Path, meter_serial: str, bill_date: datetime) -> tuple[Path, Path, Path]:
    """The fixed convention path for all three formats (decision 15, ADR
    0010; the ``.png`` added M7 slice 4, issue #35, D2) — never stored in the
    database, derived fresh on every render/write/download.

    ``<capture_dir>/<meter_serial>/<bill_date UTC as %Y-%m-%d_%H%M%S>.{pdf,xlsx,png}``

    **One stem, three extensions** (ADR 0015) — deriving it in one function
    rather than a separate ``capture_png_path()`` is what stops the three
    formats from drifting apart later.

    Args:
        capture_dir: The current ``capture_dir`` setting value.
        meter_serial: The row's ``meter_serial`` snapshot.
        bill_date: The row's ``bill_date`` — naive values are treated as UTC
            (SQLite hands back naive datetimes for a ``DateTime(timezone=True)``
            column; every stored timestamp in this product is UTC).

    Returns:
        ``(pdf_path, xlsx_path, png_path)``, all resolved absolute paths
        sharing one filename stem.

    Raises:
        ValueError: *meter_serial* fails :func:`~arichds.capture.paths.sanitize_meter_serial`.
    """
    serial = sanitize_meter_serial(meter_serial)
    aware = bill_date if bill_date.tzinfo is not None else bill_date.replace(tzinfo=UTC)
    stem = aware.astimezone(UTC).strftime("%Y-%m-%d_%H%M%S")
    base = capture_dir.resolve() / serial / stem
    return base.with_suffix(".pdf"), base.with_suffix(".xlsx"), base.with_suffix(".png")


def write_pdf_capture(
    row: Any, device_name: str, target: Path, capture_dir: Path, scale: DisplayUnitScale = "kilo"
) -> None:
    """Render and hardened-write the PDF capture for *row* at *target*."""
    allowlist = [capture_dir.resolve()]
    write_capture(target, lambda: render_billing_pdf(row, device_name, scale=scale), allowlist)


def write_xlsx_capture(
    row: Any, device_name: str, target: Path, capture_dir: Path, scale: DisplayUnitScale = "kilo"
) -> None:
    """Render and hardened-write the xlsx capture for *row* at *target*."""
    allowlist = [capture_dir.resolve()]
    write_capture(target, lambda: render_billing_xlsx(row, device_name, scale=scale), allowlist)


def _png_source_rows(session: Any, anchor: Any) -> list[Any]:
    """The rows the PNG capture is built from (D4, issue #35).

    Same device_id and meter_serial as *anchor*, closed periods only
    (``record_status IS NULL``), ``bill_date <= anchor.bill_date`` — not "the
    ten newest for the device": a single read can commit several newly closed
    periods at once, and the image for the *older* of two must not contain
    the newer one (ADR 0015's "an older period's own image still holds the
    ten periods that preceded it"). Newest first, limited to ten.

    Lives on the service side, not the renderer and not
    :mod:`arichds.acquisition.billing` — both the eager write
    (:func:`write_png_capture`) and the render-on-miss download
    (:mod:`arichds.api.billing`) share this one query through it.
    """
    return list(
        session.scalars(
            select(BillingReadingRow)
            .where(
                BillingReadingRow.device_id == anchor.device_id,
                BillingReadingRow.meter_serial == anchor.meter_serial,
                BillingReadingRow.record_status.is_(None),
                BillingReadingRow.bill_date <= anchor.bill_date,
            )
            .order_by(BillingReadingRow.bill_date.desc())
            .limit(10)
        )
    )


def write_png_capture(
    row: Any, device_name: str, target: Path, capture_dir: Path, scale: DisplayUnitScale = "kilo"
) -> None:
    """Render and hardened-write the PNG capture (up to ten closed periods,
    D4) for *row*'s meter at *target*.

    *row* must be an open-session ORM row for the ten-period query (D4) to
    run — :func:`~sqlalchemy.orm.object_session` resolves the session it is
    already attached to (both callers hold one: the eager path
    (:mod:`arichds.acquisition.billing`) and the render-on-miss download
    (:mod:`arichds.api.billing`)).

    Two different "no query" cases, deliberately not collapsed onto one
    (review round, problem 4):

    * **Unmapped** (a ``SimpleNamespace`` test row — not an ORM instance at
      all): the intended, silent fallback, matching the row shape
      :func:`write_pdf_capture` / :func:`write_xlsx_capture` accept.
    * **Mapped but detached** (a real ``BillingReading`` with no attached
      session): not reachable through either production caller today — both
      hold an open session on the row they pass in — but if it ever
      happened, silently rendering *row* alone would produce a one-period
      image inside a file whose name promises up to ten, with nothing on
      disk or in the log to say so (ADR 0015's own "the failure mode is a
      person sending months of data believing they sent one" — the same
      shape, one row short instead of nine over). Logged loudly instead.
    """
    try:
        session = object_session(row)
    except UnmappedInstanceError:
        rows: list[Any] = [row]
    else:
        if session is None:
            logger.warning(
                "PNG capture for %s bill_date %s meter_serial %s has no attached session — "
                "rendering the single period instead of the usual up-to-ten window",
                device_name,
                getattr(row, "bill_date", None),
                getattr(row, "meter_serial", None),
            )
            rows = [row]
        else:
            rows = _png_source_rows(session, row)

    allowlist = [capture_dir.resolve()]
    write_capture(target, lambda: render_billing_png(rows, device_name, scale=scale), allowlist)


def capture_reading(
    row: Any,
    device_name: str,
    capture_dir: Path,
    *,
    write_excel: bool,
    write_image: bool,
    scale: DisplayUnitScale = "kilo",
) -> None:
    """Write the PDF (and, when enabled, the xlsx and/or PNG) capture for one
    closed Billing Reading.

    A row whose ``meter_serial`` is ``None`` or fails sanitisation gets no
    capture — logged and skipped, never raised (decision 15, issue #22): a
    capture failure must never look like a billing-read failure to the caller.

    The xlsx and PNG writes are both side effects of the PDF write (decision
    13; extended M7 slice 4, issue #35, D3 — the PNG is only ever written
    alongside a PDF) and neither undoes it: a failure in either is logged and
    swallowed here, mirroring v1's ``_write_xlsx_capture``. Order is PDF,
    then xlsx, then PNG. A PDF write failure propagates to the caller, which
    is expected to catch it per-reading (:mod:`arichds.acquisition.billing`)
    or per-request (:mod:`arichds.api.billing`).

    Args:
        row: Anything :func:`~arichds.capture.pdf.render_billing_pdf` accepts
            — an ORM row read inside an open session, or a ``SimpleNamespace``.
        device_name: Raw device name for the document header.
        capture_dir: The current ``capture_dir`` setting value.
        write_excel: Whether ``billing_excel_export`` is enabled.
        write_image: Whether ``billing_image_export`` is enabled (D1/D3,
            issue #35).
        scale: The current ``display_unit_scale`` setting value — see
            :func:`~arichds.capture.pdf.render_billing_pdf`.
    """
    if getattr(row, "meter_serial", None) is None:
        logger.warning("Capture skipped for %s bill_date %s — no meter_serial stored", device_name, row.bill_date)
        return

    try:
        pdf_target, xlsx_target, png_target = capture_target_paths(capture_dir, row.meter_serial, row.bill_date)
    except ValueError as exc:
        logger.warning("Capture skipped for %s bill_date %s — %s", device_name, row.bill_date, exc)
        return

    write_pdf_capture(row, device_name, pdf_target, capture_dir, scale)

    if write_excel:
        try:
            write_xlsx_capture(row, device_name, xlsx_target, capture_dir, scale)
        except Exception:  # noqa: BLE001 — a side effect; the PDF result must survive (v1 parity).
            logger.exception("xlsx capture failed for %s bill_date %s (PDF unaffected)", device_name, row.bill_date)

    if write_image:
        try:
            write_png_capture(row, device_name, png_target, capture_dir, scale)
        except Exception:  # noqa: BLE001 — a side effect; the PDF result must survive (D3).
            logger.exception("png capture failed for %s bill_date %s (PDF unaffected)", device_name, row.bill_date)
