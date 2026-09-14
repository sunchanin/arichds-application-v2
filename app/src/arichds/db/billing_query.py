"""Latest closed Billing Reading per device — one query, shared by the
All-Meters View and the billing export planned after it (issue 01).

Extracted rather than written inside ``api/billing.py`` for the reason
:mod:`arichds.db.load_profile_query` gives for its own extraction: the export
needs exactly this result and must call it directly rather than issue HTTP
against its own process. Two implementations of "the latest closed period per
device" means one of them drifts one day with nothing to catch it, because
each side only tests itself.

It lives under ``db/`` rather than ``acquisition/`` for the same reason
``db/retention.py:11-12`` gives for its placement: it reads no meter, builds
no driver and takes no Transport Endpoint lock — its domain is the rows.

**The row set is devices, not readings.** The join is an outer join *from*
``devices``, so a meter that has never produced a billing period is still one
row, with ``None`` where the reading would be. Deriving the row set from
``billing_readings`` would hide precisely the case the All-Meters View exists
to surface.

**The Open Period is excluded**, not merely deprioritised. Its ``bill_date``
advances on every read (ADR 0018, CONTEXT.md — Open Period), so including it
would make every meter look freshly cut and destroy the staleness signal the
caller derives from the Bill Date.

**No status, no ordering, no threshold.** Those belong to the caller: the
All-Meters View resolves a chip and sorts by it, the export will do neither.
Baking either in would make one caller work around a decision that was never
its own.
"""

from __future__ import annotations

from sqlalchemy import Select, func, select

from arichds.db.models import BillingReading, Device


def latest_closed_per_device() -> Select:
    """One row per device: ``(Device, BillingReading | None)``.

    The reading is that device's **latest closed** period — the greatest
    ``bill_date`` among rows whose ``record_status`` is ``NULL`` — or ``None``
    for a device that has never produced one.

    ``MAX(bill_date)`` identifies exactly one row per device because closed
    periods are unique on ``(device_id, bill_date)`` (ADR 0009's partial
    unique index), so this cannot fan a device out into two rows.

    Returns:
        A :class:`~sqlalchemy.Select` the caller executes. No ordering and no
        limit — see this module's docstring.
    """
    newest = (
        select(
            BillingReading.device_id.label("device_id"),
            func.max(BillingReading.bill_date).label("bill_date"),
        )
        .where(BillingReading.record_status.is_(None))
        .group_by(BillingReading.device_id)
        .subquery()
    )
    return (
        select(Device, BillingReading)
        .outerjoin(newest, newest.c.device_id == Device.id)
        .outerjoin(
            BillingReading,
            (BillingReading.device_id == newest.c.device_id)
            & (BillingReading.bill_date == newest.c.bill_date)
            & BillingReading.record_status.is_(None),
        )
    )


def closed_periods_with_record_no(device_id: int) -> Select:
    """Every closed Billing Reading for *device_id*, oldest first, each with the
    ``record_no`` the billing export file writes (M13, issue 01).

    ``record_no`` is the row's **ordinal among all of that device's closed
    periods**, counted from the oldest — not a count of lines already in the
    file. A line count would need the file read on every append and would reset
    the moment the file is rewritten under a new head
    (:mod:`arichds.export.writer`); this number is a property of the data, so
    it survives both. Billing Readings are not subject to Retention, so it is
    stable for the life of the device.

    The numbering happens in a subquery over *every* closed period, so a caller
    narrowing the result to what it has not exported yet still gets the
    ordinals those rows have in the whole series.

    The Open Period is excluded for the same reason
    :func:`latest_closed_per_device` excludes it: its ``bill_date`` advances on
    every read (ADR 0018), and a file that appends cannot hold a row whose key
    moves.

    Returns:
        A :class:`~sqlalchemy.Select` yielding ``(BillingReading, record_no)``,
        ordered oldest first. The caller adds its own ``bill_date`` lower bound.
    """
    numbered = (
        select(
            BillingReading.id.label("id"),
            func.row_number().over(order_by=BillingReading.bill_date.asc()).label("record_no"),
        )
        .where(BillingReading.device_id == device_id, BillingReading.record_status.is_(None))
        .subquery()
    )
    return (
        select(BillingReading, numbered.c.record_no)
        .join(numbered, numbered.c.id == BillingReading.id)
        .order_by(BillingReading.bill_date.asc())
    )
