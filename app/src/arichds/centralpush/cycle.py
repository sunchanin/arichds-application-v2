"""The Central Push cycle (ADR 0024; spec.md "Central Push"; M14 ticket 08).

Every fifteen minutes, on the scheduler's one thread, **last** in the
registry — one job behind the Database Destination sync
(:func:`arichds.dataout.sync.database_destination_cycle`), because it is the
second job that talks to a machine we do not own (ADR 0024: "last in the
scheduler queue"). A machine with no URL configured makes **no request at
all** (ADR 0024, "Opting out").

**No state on our side** (ADR 0024, ADR 0008). Every cycle starts by asking
the server what it already holds (``GET /v1/holdings``) and sends only rows
missing or changed since that answer — there is no ``sync_state``, no
watermark column, and a partial cycle is not a lost cycle: the next one asks
again and converges. This is the same shape
:mod:`arichds.dataout.sync` already proved for the Database Destination,
applied to a different transport and a different contract (SPEC §3.10 —
"two transports, do not conflate them"; `centralpush/` shares no code with
`dataout/`).

**Licensed kinds only.** Billing needs the ``billing`` feature, load profile
the ``load_profile`` feature, the Energy Summary the ``energy_summary``
feature — the same background-path gate `dataout/sync.py` uses
(:func:`~arichds.licensing.features.feature_enabled` with
:func:`~arichds.licensing.current.current_license_service`, never
``require_feature``, because there is no ``Request`` on the scheduler
thread). The meter roster carries **no** feature key and is always sent
(ADR 0024).

**Any HTTP failure ends the cycle right there.** An unreachable server, a
connect or read timeout, or a non-2xx response on *any* request — the
holdings read or a push — stops the cycle immediately. Whatever the server
already accepted in an earlier request of the same cycle stays accepted;
nothing further is attempted this pass, and there is no retry within a
cycle (ADR 0024) — the next cycle's holdings answer is the retry.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa

from arichds.acquisition.status import display_status
from arichds.centralpush.client import PushRequestError, fetch_holdings, push_kind
from arichds.centralpush.contract import BillingItem, EnergySummaryItem, LoadProfileItem, MeterItem
from arichds.centralpush.status import CycleStatus, set_last_cycle
from arichds.config import get_settings
from arichds.constants import CENTRAL_PUSH_BUDGET_SEC, CENTRAL_PUSH_LOAD_PROFILE_REWIND_SEC
from arichds.db.app_settings import (
    CENTRAL_PUSH_TOKEN_DEFAULT,
    CENTRAL_PUSH_TOKEN_KEY,
    CENTRAL_PUSH_URL_DEFAULT,
    CENTRAL_PUSH_URL_KEY,
    get_setting,
)
from arichds.db.models import BillingReading, Device, LoadProfileReading
from arichds.db.models import EnergySummaryDay as EnergySummaryDayRow
from arichds.db.session import session_scope
from arichds.licensing.current import current_license_service
from arichds.licensing.features import feature_enabled

logger = logging.getLogger(__name__)


def _utc(value: datetime) -> datetime:
    """A SQLite-naive datetime, or an already-aware one, as UTC-aware.

    The same coercion ``api/billing.py``'s field validators use: SQLite
    hands a ``DateTime(timezone=True)`` column back naive, and every value
    in this store is UTC by CLAUDE.md's write-time normalization invariant.
    Applied to every outbound instant — "every instant carries a UTC offset"
    (Contract v1) is a property of the wire, not of what SQLite happens to
    return.
    """
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _utc_row(row: dict[str, Any]) -> dict[str, Any]:
    """Copy *row* with every ``datetime`` value made UTC-aware. A plain
    ``date`` (``local_date``) is left untouched — Contract v1: "`local_date`
    is a plain date, never UTC"."""
    return {key: (_utc(value) if isinstance(value, datetime) else value) for key, value in row.items()}


def _load_profile_start(threshold: datetime | None) -> datetime | None:
    """Where to resume one ``(meter_serial, logger_id)``'s load-profile send
    from — the server's own newest ``read_at``, rewound by
    :data:`~arichds.constants.CENTRAL_PUSH_LOAD_PROFILE_REWIND_SEC` (ADR
    0024's "small safety margin" — the server upserts on
    ``(meter_serial, logger_id, read_at)``, so a re-sent row collapses onto
    itself rather than duplicating).

    ``None`` in means ``None`` out — a server that has never seen this pair
    gets everything we hold.
    """
    if threshold is None:
        return None
    return threshold - timedelta(seconds=CENTRAL_PUSH_LOAD_PROFILE_REWIND_SEC)


class _Counts:
    """One cycle's running totals — the same shape
    ``dataout/sync.py::_Counts`` uses, so a partial cycle still reports
    honestly."""

    __slots__ = ("billing", "energy_summary", "load_profile", "meters", "skipped")

    def __init__(self) -> None:
        self.meters = 0
        self.billing = 0
        self.energy_summary = 0
        self.load_profile = 0
        self.skipped = 0


def _out_of_budget(deadline: float) -> bool:
    return time.monotonic() >= deadline


def central_push_cycle() -> None:
    """Ask the server what it holds, then send what is missing or changed.

    The Scheduler's ``central_push`` job — registered **last**
    (:func:`arichds.jobs.scheduler.default_jobs`). Nothing propagates: a
    failure is recorded on the in-memory status and the job runs again in
    fifteen minutes, matching ``database_destination_cycle``'s own contract.
    """
    with session_scope() as session:
        url = get_setting(session, CENTRAL_PUSH_URL_KEY, CENTRAL_PUSH_URL_DEFAULT).strip()
        token = get_setting(session, CENTRAL_PUSH_TOKEN_KEY, CENTRAL_PUSH_TOKEN_DEFAULT)

    if not url:
        logger.debug("Central Push: not configured — nothing to do")
        return

    license_service = current_license_service()
    if license_service is None:
        # No LicenseService published means "not booted yet" or "running
        # outside the app" — the same reasoning `features.feature_enabled`
        # documents for treating this as off. Without it there is no Machine
        # ID to put on the wire, so the cycle cannot run at all.
        logger.debug("Central Push: no LicenseService published — nothing to do")
        return
    machine_id = license_service.machine_id

    settings = get_settings()
    send_billing = feature_enabled("billing", license_service=license_service, settings=settings)
    send_load_profile = feature_enabled("load_profile", license_service=license_service, settings=settings)
    send_energy_summary = feature_enabled("energy_summary", license_service=license_service, settings=settings)

    started = time.monotonic()
    deadline = started + CENTRAL_PUSH_BUDGET_SEC
    sent_at = datetime.now(UTC)
    counts = _Counts()
    outcome: str = "success"
    error: str | None = None

    try:
        holdings = fetch_holdings(url, token)
        lp_watermarks = {(entry.meter_serial, entry.logger_id): entry.newest_read_at for entry in holdings.load_profile}
        billing_watermarks = {entry.meter_serial: entry.newest_updated_at for entry in holdings.billing}
        energy_watermarks = {entry.meter_serial: entry.newest_updated_at for entry in holdings.energy_summary}

        _send_meters(url, token, machine_id=machine_id, sent_at=sent_at, counts=counts)

        if send_billing and not _out_of_budget(deadline):
            _send_billing(
                url,
                token,
                machine_id=machine_id,
                sent_at=sent_at,
                watermarks=billing_watermarks,
                counts=counts,
                deadline=deadline,
            )

        if send_energy_summary and not _out_of_budget(deadline):
            _send_energy_summary(
                url,
                token,
                machine_id=machine_id,
                sent_at=sent_at,
                watermarks=energy_watermarks,
                counts=counts,
                deadline=deadline,
            )

        if send_load_profile and not _out_of_budget(deadline):
            _send_load_profile(
                url,
                token,
                machine_id=machine_id,
                sent_at=sent_at,
                watermarks=lp_watermarks,
                counts=counts,
                deadline=deadline,
            )
    except PushRequestError as exc:
        outcome = "skipped"
        error = str(exc)
        logger.warning("Central Push cycle ended skipped — %s", error)
    except Exception as exc:  # noqa: BLE001 — a misbehaving server must never strand the scheduler.
        outcome = "skipped"
        error = type(exc).__name__
        logger.exception("Central Push cycle failed")

    set_last_cycle(
        CycleStatus(
            ran_at=datetime.now(UTC),
            outcome=outcome,
            meters_rows=counts.meters,
            billing_rows=counts.billing,
            energy_summary_rows=counts.energy_summary,
            load_profile_rows=counts.load_profile,
            skipped_rows=counts.skipped,
            duration_sec=round(time.monotonic() - started, 3),
            error=error,
        )
    )
    logger.info(
        "Central Push cycle: %d meter(s), %d billing row(s), %d Energy Summary row(s), %d Interval Reading(s), "
        "%d skipped for a missing Meter Serial, in %.2fs%s",
        counts.meters,
        counts.billing,
        counts.energy_summary,
        counts.load_profile,
        counts.skipped,
        time.monotonic() - started,
        "" if outcome == "success" else f" ({outcome}: {error})",
    )


# ─── The meter roster — always sent, a full snapshot (ADR 0024) ──────────────


def _send_meters(url: str, token: str, *, machine_id: str, sent_at: datetime, counts: _Counts) -> None:
    with session_scope() as session:
        devices = list(session.scalars(sa.select(Device).order_by(Device.id)))

    items: list[MeterItem] = []
    for device in devices:
        if not device.meter_serial:
            counts.skipped += 1
            continue
        items.append(
            MeterItem(
                meter_serial=device.meter_serial,
                device_name=device.name,
                brand=device.brand,
                model=device.model,
                status=display_status(device),
            )
        )

    counts.meters = push_kind(
        url, token, machine_id=machine_id, kind="meters", items=items, sent_at=sent_at, send_when_empty=True
    )


# ─── Billing — updated_at newer than the server's own, per Meter Serial ──────


def _send_billing(
    url: str,
    token: str,
    *,
    machine_id: str,
    sent_at: datetime,
    watermarks: dict[str, datetime],
    counts: _Counts,
    deadline: float,
) -> None:
    device = Device.__table__
    billing = BillingReading.__table__
    # A review named the hazard: if a partial send (a budget stop, or a
    # later chunk failing) ever leaves an UNSENT row whose `updated_at` is
    # older than the NEWEST row already accepted for the same meter, that
    # unsent row is lost forever — the next cycle's watermark compare
    # (`updated_at <= threshold`) would skip it. Ordering by the effective
    # identity (the row's own `meter_serial`, falling back to the device's,
    # exactly as the fallback below resolves it) then by `updated_at`
    # ascending makes every prefix of the send safe **for rows with
    # distinct `updated_at` values**. Rows for the same meter that share
    # one `updated_at` are NOT protected by this ordering alone — a partial
    # send can still cut through a tie and strand one of them — but that is
    # only reachable once a kind holds more than CENTRAL_PUSH_ITEM_CAP
    # (5,000) rows, since a chunk that fits whole is never cut mid-kind.
    # `db/energy_summary_store.py` stamps a whole recompute pass with one
    # shared `now_utc`, so ties are real for the Energy Summary, not a
    # theoretical case. Comparing with `<` instead of `<=` is NOT the fix —
    # it would resend the newest, already-accepted row for a meter every
    # cycle and break "the second cycle sends only the roster".
    identity = sa.func.coalesce(billing.c.meter_serial, device.c.meter_serial)
    statement = (
        sa.select(*billing.columns, device.c.meter_serial.label("_device_serial"))
        .select_from(billing.join(device, device.c.id == billing.c.device_id))
        .order_by(identity, billing.c.updated_at)
    )

    items: list[BillingItem] = []
    with session_scope() as session:
        for mapping in session.execute(statement).mappings():
            row = dict(mapping)
            device_serial = row.pop("_device_serial")
            # ADR 0018: both driver read paths can store `meter_serial=None`
            # on the row itself when the serial register read failed after
            # the buffer was read — the row's own snapshot is tried first,
            # the device's current serial is the fallback, same as
            # `dataout/sync.py::_billing_rows`.
            serial = row.get("meter_serial") or device_serial
            if not serial:
                counts.skipped += 1
                continue

            row = _utc_row(row)
            threshold = watermarks.get(serial)
            if threshold is not None and row["updated_at"] <= threshold:
                continue

            fields = {key: value for key, value in row.items() if key in BillingItem.model_fields}
            fields["meter_serial"] = serial
            fields["is_open"] = row["record_status"] == "open"
            items.append(BillingItem(**fields))

    counts.billing = push_kind(
        url, token, machine_id=machine_id, kind="billing", items=items, sent_at=sent_at, deadline=deadline
    )


# ─── Energy Summary — the same updated_at rule as billing ────────────────────


def _send_energy_summary(
    url: str,
    token: str,
    *,
    machine_id: str,
    sent_at: datetime,
    watermarks: dict[str, datetime],
    counts: _Counts,
    deadline: float,
) -> None:
    device = Device.__table__
    energy = EnergySummaryDayRow.__table__
    # Same ordering, and the same limits, `_send_billing` documents — device
    # Meter Serial then `updated_at` ascending protects every prefix of the
    # send for rows with distinct `updated_at`, but NOT rows for one meter
    # that share a single `updated_at` (real here: a recompute pass stamps
    # every changed day with one shared `now_utc`, see
    # `db/energy_summary_store.py:97,134,145`) — reachable only past
    # CENTRAL_PUSH_ITEM_CAP rows in one kind, and not fixable by comparing
    # with `<` instead of `<=` (that would resend the newest row every
    # cycle and break "the second cycle sends only the roster").
    statement = (
        sa.select(*energy.columns, device.c.meter_serial.label("_device_serial"))
        .select_from(energy.join(device, device.c.id == energy.c.device_id))
        .order_by(device.c.meter_serial, energy.c.updated_at)
    )

    items: list[EnergySummaryItem] = []
    with session_scope() as session:
        for mapping in session.execute(statement).mappings():
            row = dict(mapping)
            serial = row.pop("_device_serial")
            if not serial:
                counts.skipped += 1
                continue

            row = _utc_row(row)
            threshold = watermarks.get(serial)
            if threshold is not None and row["updated_at"] <= threshold:
                continue

            fields = {key: value for key, value in row.items() if key in EnergySummaryItem.model_fields}
            fields["meter_serial"] = serial
            items.append(EnergySummaryItem(**fields))

    counts.energy_summary = push_kind(
        url, token, machine_id=machine_id, kind="energy_summary", items=items, sent_at=sent_at, deadline=deadline
    )


# ─── Load profile — per (meter_serial, logger_id), rewound by a safety margin ─


def _send_load_profile(
    url: str,
    token: str,
    *,
    machine_id: str,
    sent_at: datetime,
    watermarks: dict[tuple[str, int], datetime],
    counts: _Counts,
    deadline: float,
) -> None:
    """Send every ``(meter_serial, logger_id)`` pair's pending rows, one
    ``push_kind`` call per pair — never one giant list gathered across every
    pair first. A first-run backfill can be ~345k rows across ~70 requests
    (the review's own measurement, extrapolated from real constants); this
    is what lets the deadline check below actually save the DB read and the
    memory for every pair not yet reached, the same shape
    ``dataout/sync.py::_append_load_profile`` uses (checked before each
    pair, mirroring ``dataout/sync.py:375``). No ordering fix is needed
    here unlike billing/Energy Summary: each pair's own watermark is
    independent, so a pair never sent this cycle simply waits for the next
    one, and rows within one pair are already read_at-ascending.
    """
    device = Device.__table__
    lp = LoadProfileReading.__table__

    with session_scope() as session:
        pairs = session.execute(
            sa.select(lp.c.device_id, lp.c.logger_id, device.c.meter_serial)
            .select_from(lp.join(device, device.c.id == lp.c.device_id))
            .distinct()
            .order_by(lp.c.device_id, lp.c.logger_id)
        ).all()

    for device_id, logger_id, serial in pairs:
        if not serial:
            counts.skipped += _lp_row_count(device_id, logger_id)
            continue

        if _out_of_budget(deadline):
            return

        start = _load_profile_start(watermarks.get((serial, logger_id)))
        statement = sa.select(*lp.columns).where(lp.c.device_id == device_id, lp.c.logger_id == logger_id)
        if start is not None:
            statement = statement.where(lp.c.read_at > start)
        statement = statement.order_by(lp.c.read_at)

        items: list[LoadProfileItem] = []
        with session_scope() as session:
            for mapping in session.execute(statement).mappings():
                row = _utc_row(dict(mapping))
                fields = {key: value for key, value in row.items() if key in LoadProfileItem.model_fields}
                fields["meter_serial"] = serial
                items.append(LoadProfileItem(**fields))

        counts.load_profile += push_kind(
            url, token, machine_id=machine_id, kind="load_profile", items=items, sent_at=sent_at, deadline=deadline
        )


def _lp_row_count(device_id: int, logger_id: int) -> int:
    """How many rows one serial-less ``(device, logger)`` holds — issued
    only on the miss, mirroring ``dataout/sync.py::_unattributable_row_count``."""
    lp = LoadProfileReading.__table__
    statement = sa.select(sa.func.count()).where(lp.c.device_id == device_id, lp.c.logger_id == logger_id)
    with session_scope() as session:
        return int(session.execute(statement).scalar_one())


__all__ = ["central_push_cycle"]
