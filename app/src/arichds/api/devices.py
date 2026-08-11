"""Device Manager — probe-first CRUD and catalog (M3-1); status, history,
Pause/Resume, Read now and Delete all data (M3-2).

**No handler here reports a measured value (ADR 0007).** M3-3 removed
``GET /{device_id}/readings/latest`` along with the Monitor page that was its
only caller: v2 has no live-value display, so an endpoint serving one had
nobody to serve. Read now reports whether the meter *answered*, never what it
read. That stayed true when M5 gave the module rows to write: Read now stores
the meter's own load profile from #15
(:func:`~arichds.acquisition.load_profile.read_and_store_load_profile`), and the
Scheduler's job does the same on a cadence from #16 — but neither *reports* a
value, they report whether the meter answered and how many intervals were
stored. M6a (issue #21) adds the same pair for billing
(:func:`~arichds.acquisition.billing.read_and_store_billing`). Reading either
set of rows back out belongs to :mod:`arichds.api.load_profile` and
:mod:`arichds.api.billing`, not here. The other handler touching
:class:`~arichds.db.models.LoadProfileReading` and
:class:`~arichds.db.models.BillingReading` is Delete all data, which counts the
rows it destroys.

Three independent gates sit in front of every handler here:

* **Limited Mode** — everything in this router is under ``/api`` and not on the
  license allow-list, so an unlicensed machine gets 403 ``LICENSE_INVALID``
  before any handler runs.
* **Authentication** (M2-1) — the router-level dependency means an
  unauthenticated request is refused with 401 *before* its body is validated,
  so a ``POST`` with no body answers 401 rather than 422.
* **Role** (SPEC §3.2) — changing a device (including Pause/Resume and Delete
  all data), and testing a connection, are admin-only; reading **and Read now**
  are open to any authenticated user.

**Status is not asked for, it is remembered (ADR 0004).** Nothing in this module
polls, schedules or health-checks anything: the Poller's ticks and the Manual
Reads below write what they proved through
:mod:`arichds.acquisition.status`, and every read path here just projects the
columns. ``paused`` is the one status computed rather than stored, which is what
makes it impossible for this API to report ``online`` for a device nobody is
reading.

**Identity comes from the meter (ADR 0005).** Create and Update both Probe
before they write, so ``meter_serial`` is never typed by a person and never
arrives "eventually". A probe takes seconds and holds a Transport Endpoint lock
as a Manual Read (ADR 0006), which is why every handler here is a plain ``def``:
FastAPI runs a sync handler in a threadpool, and a blocking meter conversation
has no business on the event loop.

**Status codes follow one rule (D7).** A *client* fault gets an HTTP status —
409 for a conflict, 404, 403, 422. A *meter* fault gets a failure envelope with
``code="PROBE_FAILED"`` and HTTP **502**: the upstream device failed, not the
request, and ``web/src/api.ts`` already reads ``error.code`` / ``error.message``
/ ``error.reason`` off the envelope regardless of status. ``POST
/api/license/activate`` set that precedent for "the operation legitimately
failed for a domain reason".
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select

from arichds.acquisition.billing import read_and_store_billing
from arichds.acquisition.catalog import CATALOG, ModelSpec
from arichds.acquisition.connection_params import connection_params_from_transport
from arichds.acquisition.drivers.factory import supported_models
from arichds.acquisition.load_profile import read_and_store_load_profile
from arichds.acquisition.probe import ProbeError, ProbeResult, probe_meter
from arichds.acquisition.status import (
    DeviceEventKind,
    DeviceStatus,
    display_status,
    record_event,
    record_failure,
    record_no_driver,
    record_success,
)
from arichds.api.deps import AdminDep, CurrentUserDep, LicenseServiceDep, PollerDep, SessionDep, get_current_user
from arichds.api.envelope import ApiResponse
from arichds.constants import JOB_BILLING, JOB_LIVENESS, JOB_LOAD_PROFILE
from arichds.db.models import BillingReading, Device, DeviceEvent, LoadProfileReading

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["devices"], dependencies=[Depends(get_current_user)])

#: The envelope error code every meter-side failure carries.
ERROR_PROBE_FAILED = "PROBE_FAILED"

#: The five parity names the vendored ``GXSettings`` ``-S`` parser resolves
#: (``Parity[value.upper()]`` against the installed ``gurux_common.io.Parity``
#: — see ``connection_params.py`` and the gurux-dlms skill's ``-S`` row).
_SERIAL_PARITY_NAMES = ("NONE", "ODD", "EVEN", "MARK", "SPACE")


class NetTransport(BaseModel):
    """A TCP/IP Transport Endpoint — ``{"kind": "net", host, port}``.

    The key names are not free choices: they are exactly what
    ``Device.transport_endpoint`` (``db/models.py``) reads and what
    ``Device.transport`` stores, so a validated instance's
    ``model_dump()`` needs no translation to become a DB row's JSON.
    """

    kind: Literal["net"] = "net"
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)


class SerialTransport(BaseModel):
    """A serial Transport Endpoint — five fields, no flow control.

    No flow control (SPEC §3.3, amended by issue #9): the ``-S`` argv seam
    ``GXSettings`` parses carries no flow-control slot at all, and both field
    units at the customer site run at the default of "no flow control" —
    there is nothing to configure.

    Bounds are chosen from what the vendored ``-S`` parser can actually parse
    (``GXSettings.py:224-244``), not arbitrarily: data bits is sliced to a
    single character, so a value outside 5-8 would silently corrupt the argv
    rather than fail cleanly; stop bits is read as a human count and the
    parser subtracts 1 to reach ``StopBits.ONE``/``TWO`` — 3 has no target.
    """

    kind: Literal["serial"] = "serial"
    serial_port: str = Field(min_length=1, max_length=32)
    baud_rate: int = Field(gt=0, le=1_000_000)
    data_bits: int = Field(ge=5, le=8)
    parity: str = Field(min_length=1, max_length=10)
    stop_bits: int = Field(ge=1, le=2)

    @field_validator("parity")
    @classmethod
    def _known_parity_name(cls, value: str) -> str:
        """Normalize to Title case and reject anything the parser cannot resolve."""
        upper = value.upper()
        if upper not in _SERIAL_PARITY_NAMES:
            raise ValueError(f"Unknown parity {value!r}. Use one of: {', '.join(_SERIAL_PARITY_NAMES)}.")
        return upper.title()


#: A device's transport, discriminated on ``kind`` — makes "the API requires
#: only the fields the chosen transport actually needs" true by schema, not by
#: an ``if`` in a handler (the repo's rule: transport branching lives in
#: ``connection_params.py`` alone).
Transport = Annotated[NetTransport | SerialTransport, Field(discriminator="kind")]


class NetTransportOut(BaseModel):
    """``net`` transport as the API *reports* it — no request-side bounds.

    A response is not a submission (code review, issue #9): the min-length/ge
    constraints on :class:`NetTransport` exist to reject a bad *request*
    before it is written, not to make an already-stored row unreportable. A
    malformed/legacy row (an empty ``{}``, say) must still round-trip as
    itself — see :func:`_transport_out`.
    """

    kind: Literal["net"] = "net"
    host: str
    port: int


class SerialTransportOut(BaseModel):
    """``serial`` transport as the API *reports* it — no request-side bounds.

    See :class:`NetTransportOut` — the same reasoning applies to a stored
    serial row missing a field a submission could never have gotten past.
    """

    kind: Literal["serial"] = "serial"
    serial_port: str
    baud_rate: int
    data_bits: int
    parity: str
    stop_bits: int


TransportOut = Annotated[NetTransportOut | SerialTransportOut, Field(discriminator="kind")]


def _safe_int(value: Any) -> int:
    """Coerce *value* to ``int``, or ``0`` if it cannot be — never raises.

    A malformed stored row can hold anything in a JSON column (a string, a
    list, ``None``); :func:`_transport_out` must degrade it, not crash on it.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _transport_out(transport: dict[str, Any]) -> NetTransportOut | SerialTransportOut:
    """Project a stored transport dict onto the response shape, honestly.

    Two things a malformed/legacy row (an empty ``{}`` default, a serial row
    missing a field, ...) must never do (code review, issue #9):

    * **claim a ``kind`` other than the one actually stored** — the same rule
      :meth:`~arichds.db.models.Device.transport_endpoint` already uses
      (``kind == "serial"`` is the only special case; everything else,
      including a missing ``kind``, is ``net``). ``web/src/pages/Devices.tsx``
      trusts ``transport.kind`` alone to decide which form fields to show, so
      reporting a serial row as ``net`` would have the next Update save
      silently rewrite it to the wrong transport — a read path corrupting
      write-path data.
    * **violate the schema the API itself publishes** for the field it is
      returned in. Reusing the request-side :data:`Transport` union for this
      would do exactly that (``NetTransport.host`` requires a non-blank
      string), so the response uses the separate, unconstrained
      :data:`TransportOut` union instead — a response's job is to describe
      what is stored, not to pretend a bad row is a well-formed submission.

    A row written through this module's own Create/Update always validates
    against the strict :data:`Transport` union already, so this only ever
    changes behaviour for data this module did not write.
    """
    if transport.get("kind") == "serial":
        return SerialTransportOut(
            serial_port=str(transport.get("serial_port", "")),
            baud_rate=_safe_int(transport.get("baud_rate")),
            data_bits=_safe_int(transport.get("data_bits")),
            parity=str(transport.get("parity", "")),
            stop_bits=_safe_int(transport.get("stop_bits")),
        )
    return NetTransportOut(host=str(transport.get("host", "")), port=_safe_int(transport.get("port")))


class DeviceCreate(BaseModel):
    """Request body for adding a device.

    ``meter_serial`` is deliberately absent: it is read off the meter, never
    submitted (ADR 0005).

    Attributes:
        name: Operator-facing label, unique on this machine.
        brand: Meter brand, e.g. ``"cewe"``. Data the form fills from the
            catalog; nothing branches on it.
        model: Model identifier resolving a driver, e.g. ``"prometer100"``.
        site_name: Which site this meter is at. Required (SPEC §3.3).
        transport: The Transport Endpoint — ``net`` or ``serial`` (issue #9).
            A discriminated union, so the API requires only the fields the
            chosen transport actually needs.
        password: DLMS authentication password. Stored, and — owner ruling,
            2026-08-11 — **returned in the clear**: meter passwords are not a
            security boundary, so convenience (the edit form prefills it and
            Test Connection needs no retyping) wins over secrecy. The two
            cipher keys below are unaffected — they are never returned.
        site_code: Record-only.
        customer: Record-only.
        meter_number: Record-only operator label — not the Meter Serial.
        group_name: Free-text group.
        block_cipher_key: DLMS encryption key (used from M4). Never returned.
        authentication_key: DLMS authentication key (used from M4). Never returned.
        first_bill_date: Billing anchor date. Logic lands in M6.
        bill_day_feb28/bill_day_feb29/bill_day_30/bill_day_31: Period close day
            per month length. Logic lands in M6.
    """

    name: str = Field(min_length=1, max_length=128)
    brand: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=64)
    site_name: str = Field(min_length=1, max_length=255)
    transport: Transport
    password: str = Field(default="", max_length=128)
    site_code: str | None = Field(default=None, max_length=80)
    customer: str | None = Field(default=None, max_length=255)
    meter_number: str | None = Field(default=None, max_length=80)
    group_name: str | None = Field(default=None, max_length=80)
    block_cipher_key: str | None = Field(default=None, max_length=255)
    authentication_key: str | None = Field(default=None, max_length=255)
    first_bill_date: date | None = None
    bill_day_feb28: int | None = Field(default=None, ge=1, le=28)
    bill_day_feb29: int | None = Field(default=None, ge=1, le=29)
    bill_day_30: int | None = Field(default=None, ge=1, le=30)
    bill_day_31: int | None = Field(default=None, ge=1, le=31)


class DeviceUpdate(DeviceCreate):
    """Request body for editing a device — every field is editable.

    The three secrets are the exception to "a PUT replaces everything":
    **empty means keep** (SPEC §3.3, v1's behaviour). An operator editing a
    site name should not have to retype a DLMS password they may not know, and
    a form that returns blank secrets — which it must, since the API never
    returns them — would otherwise wipe them on every save.
    """

    password: str | None = Field(default=None, max_length=128)


class DeviceOut(BaseModel):
    """A device as the API exposes it.

    The two cipher keys are absent by construction: they are not fields of
    this model, so no handler can leak them by accident. ``password`` is the
    deliberate exception — owner ruling, 2026-08-11: meter passwords are not
    a security boundary, so this field returns the stored value in the
    clear, in favor of convenience over secrecy.

    Attributes:
        id: Surrogate key.
        name: Operator-facing label.
        brand: Meter brand.
        model: Model identifier.
        meter_serial: The Meter Serial read off the meter, or None for a row
            created before M3 that has not been re-identified yet.
        site_name: Which site this meter is at.
        site_code: Record-only.
        customer: Record-only.
        meter_number: Record-only.
        group_name: Free-text group.
        password: DLMS authentication password, in the clear (owner ruling,
            2026-08-11 — see the class docstring).
        transport: The Transport Endpoint — ``net`` or ``serial`` (issue #9).
            Unlike the request-side :data:`Transport`, this carries no
            min-length/ge bounds (:class:`NetTransportOut`/
            :class:`SerialTransportOut`) — a response describes what is
            stored, including a malformed legacy row, and never lies about
            which ``kind`` that row actually is (see :func:`_transport_out`).
        endpoint: The Transport Endpoint's lock key — ``host:port`` for net,
            the bare COM port name for serial (CONTEXT.md).
        enabled: Whether the Poller reads it.
        status: What to show — ``paused`` whenever *enabled* is false, otherwise
            the last thing a read proved (ADR 0004). Computed by
            :func:`~arichds.acquisition.status.display_status`, so this field can
            never report ``online`` for a device nobody is reading.
        status_detail: A sentence explaining a non-online status, or None.
        status_checked_at: When a read last reported on this device (UTC), or
            None when none ever has.
        first_bill_date: Billing anchor date (M6 logic).
        bill_day_feb28/bill_day_feb29/bill_day_30/bill_day_31: M6 logic.
        created_at: When it was added (UTC).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    brand: str
    model: str
    meter_serial: str | None
    site_name: str
    site_code: str | None
    customer: str | None
    meter_number: str | None
    group_name: str | None
    password: str
    transport: TransportOut
    endpoint: str
    enabled: bool
    status: DeviceStatus
    status_detail: str | None
    status_checked_at: datetime | None
    first_bill_date: date | None
    bill_day_feb28: int | None
    bill_day_feb29: int | None
    bill_day_30: int | None
    bill_day_31: int | None
    created_at: datetime

    @field_validator("status_checked_at")
    @classmethod
    def _ensure_utc(cls, value: datetime | None) -> datetime | None:
        """Re-attach UTC to the naive datetime SQLite hands back (D15).

        Without it the SPA computes freshness ("checked 40 s ago") against a
        timestamp with no offset, and is wrong by the machine's timezone.
        """
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class DeviceEventOut(BaseModel):
    """One Device Event as the API exposes it.

    Attributes:
        id: Surrogate key — also the tiebreak the drawer pages on.
        kind: What happened (:class:`~arichds.acquisition.status.DeviceEventKind`).
        detail: A sentence for a person, or None.
        actor: Who did it, or **None for an automatic transition** (D11) — a
            meter going offline was nobody's action.
        created_at: When it was recorded (UTC).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: DeviceEventKind
    detail: str | None
    actor: str | None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        """Re-attach UTC to the naive datetime SQLite hands back (D15)."""
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class DeviceEventPage(BaseModel):
    """One page of a device's history.

    ``total`` is the **unpaged** count, which is what lets the drawer show
    "1-50 of 214" and know whether another page exists.

    Attributes:
        items: The events, newest first.
        total: How many events this device has in total.
        limit: The page size that was applied.
        offset: How many rows were skipped.
    """

    items: list[DeviceEventOut]
    total: int
    limit: int
    offset: int


class CatalogEntry(BaseModel):
    """One selectable meter model, with what the Add form needs to prefill.

    ``fixed_password`` is included on purpose: it is a documented brand-wide
    default (CEWE's is printed in this repo's README), not a per-site secret,
    and prefilling it is what stops an operator from guessing.

    **Carries no transport information** (issue #9) — every catalogued model
    is offered both transports; the operator picks per device on the form's
    own Transport switch, not from the catalog.

    Attributes:
        model: Canonical model identifier — what to submit.
        brand: Owning brand.
        ui_label: What to show in the dropdown.
        fixed_password: Prefill for the Password field, or None when the model
            uses key-based auth.
        supports_battery: True if the model exposes a battery reading.
        supports_energy_summary: True if the model exposes an energy summary.
        supports_special_days: True if the model exposes a special-days table.
    """

    model: str
    brand: str
    ui_label: str
    fixed_password: str | None
    supports_battery: bool
    supports_energy_summary: bool
    supports_special_days: bool


class QuotaOut(BaseModel):
    """How many meters this machine may have, and how many it has.

    Its own endpoint rather than a field on the device list: ``GET /api/devices``
    must keep returning a plain list — the Devices tree maps straight over it —
    and ``/api/license/status`` knows ``max_meters`` but not the count.

    Attributes:
        used: How many devices exist right now.
        max_meters: The licensed limit, or None for unlimited.
        over_quota: True when an existing set of devices exceeds a newly
            reduced limit. Always False when *max_meters* is None.
    """

    used: int
    max_meters: int | None
    over_quota: bool


class TestConnectionRequest(BaseModel):
    """A form's transport values, to try without writing anything.

    No ``name`` and no ``site_name``: this diagnoses the connection, not the
    device.

    Attributes:
        model: Model identifier resolving a driver.
        transport: The Transport Endpoint to try — ``net`` or ``serial``.
        password: DLMS authentication password. Never stored, never echoed.
    """

    model: str = Field(min_length=1, max_length=64)
    transport: Transport
    password: str = Field(default="", max_length=128)


class TestConnectionOut(BaseModel):
    """What Test connection learned.

    Attributes:
        reachable: Whether the meter answered with an identity.
        meter_serial: The Meter Serial, when it did.
        reason: The :class:`~arichds.acquisition.probe.ProbeFailure` when it did
            not, so the operator knows whether to fix the password or the address.
        message: A sentence to show. Never contains the password.
    """

    reachable: bool
    meter_serial: str | None
    reason: str | None
    message: str


class ReadNowJobResult(BaseModel):
    """What one job of a Read now did.

    Attributes:
        job: Which job this entry is about — :data:`~arichds.constants.JOB_LIVENESS`,
            :data:`~arichds.constants.JOB_LOAD_PROFILE` (M5a-1) or
            :data:`~arichds.constants.JOB_BILLING` (M6a).
        ok: Whether it succeeded. A meter that refuses reports ``False`` here,
            not through an HTTP status (D10) — and so does a job that could not
            run at all, which is the same thing from the operator's side.
        detail: A sentence for a person. **Never a measured value** (ADR 0007):
            v2 has no live-value display. The load-profile job may say *how
            many* rows it stored and how far it got, which is coverage rather
            than a reading.
    """

    job: str
    ok: bool
    detail: str


class ReadNowOut(BaseModel):
    """What a Read now produced.

    A **list** of job results — ``liveness``, ``load_profile`` (M5a-1) and
    ``billing`` (M6a) — because a multi-job read can be partially successful,
    which is exactly what a single HTTP status cannot say.

    Attributes:
        results: One entry per job Read now **considered**, not per job that
            ran. A job that could not run says so with ``ok=False`` and a
            sentence, because the Read-now modal renders a row per entry and
            nothing at all for an absent one — so silence would tell the
            operator nothing (M5a-1, D12).
        status: The device's status after the read, re-read from the row, so the
            caller sees the state its own click produced.
        checked_at: When that status was established (UTC), or None when nothing
            checked anything.
    """

    results: list[ReadNowJobResult]
    status: DeviceStatus
    checked_at: datetime | None

    @field_validator("checked_at")
    @classmethod
    def _ensure_utc(cls, value: datetime | None) -> datetime | None:
        """Re-attach UTC to the naive datetime SQLite hands back (D15)."""
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ClearReadingsRequest(BaseModel):
    """The typed confirmation that guards an irreversible delete.

    Attributes:
        confirm_name: The device's name, typed by the operator. It must match
            exactly — deleting a device's history cannot be undone (SPEC §3.3).
    """

    confirm_name: str = Field(min_length=1, max_length=128)


DeviceIdPath = Annotated[int, Path(ge=1, description="Device id")]


def _to_out(device: Device) -> DeviceOut:
    """Project a :class:`Device` row onto the API shape (secrets excluded)."""
    return DeviceOut(
        id=device.id,
        name=device.name,
        brand=device.brand,
        model=device.model,
        meter_serial=device.meter_serial,
        site_name=device.site_name,
        site_code=device.site_code,
        customer=device.customer,
        meter_number=device.meter_number,
        group_name=device.group_name,
        password=device.password,
        transport=_transport_out(device.transport or {}),
        endpoint=device.transport_endpoint,
        enabled=device.enabled,
        status=display_status(device),
        status_detail=device.status_detail,
        status_checked_at=device.status_checked_at,
        first_bill_date=device.first_bill_date,
        bill_day_feb28=device.bill_day_feb28,
        bill_day_feb29=device.bill_day_feb29,
        bill_day_30=device.bill_day_30,
        bill_day_31=device.bill_day_31,
        created_at=device.created_at,
    )


def _to_catalog_entry(model: str, spec: ModelSpec) -> CatalogEntry:
    """Project a catalog :class:`ModelSpec` onto the API shape."""
    return CatalogEntry(
        model=model,
        brand=spec.brand.value,
        ui_label=spec.ui_label,
        fixed_password=spec.fixed_password,
        supports_battery=spec.supports_battery,
        supports_energy_summary=spec.supports_energy_summary,
        supports_special_days=spec.supports_special_days,
    )


def _require_known_model(model: str) -> None:
    """Refuse a model this build has no driver for.

    A form error, not a meter failure, so it answers 422 and never opens a
    socket.

    Raises:
        HTTPException: 422 if the model has no registered driver.
    """
    if model.lower() not in supported_models():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown meter model {model!r}. Supported: {supported_models()}",
        )


def _probe_failure(response: Response, exc: ProbeError) -> ApiResponse[DeviceOut]:
    """Turn a :class:`ProbeError` into a 502 failure envelope (D7)."""
    response.status_code = status.HTTP_502_BAD_GATEWAY
    logger.warning("Probe refused the operation: %s (%s)", exc, exc.reason)
    return ApiResponse[DeviceOut].failed(code=ERROR_PROBE_FAILED, message=str(exc), reason=exc.reason.value)


def _reject_duplicate_serial(session: SessionDep, meter_serial: str, *, exclude_id: int | None = None) -> None:
    """Refuse a serial that another device already holds.

    CONTEXT.md — Meter Serial: *"two rows may not point at the same physical
    meter"*. Naming the holder is the point: the operator's next action is to
    edit that row, not to create a second one.

    Raises:
        HTTPException: 409 if another device already has *meter_serial*.
    """
    query = select(Device).where(Device.meter_serial == meter_serial)
    if exclude_id is not None:
        query = query.where(Device.id != exclude_id)
    holder = session.scalar(query)
    if holder is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Meter serial {meter_serial} already belongs to device {holder.name!r}. "
                "Edit that device instead of adding a second one."
            ),
        )


def _reject_duplicate_name(session: SessionDep, name: str, *, exclude_id: int | None = None) -> None:
    """Refuse a name another device already uses.

    Raises:
        HTTPException: 409 if the name is taken.
    """
    query = select(Device).where(Device.name == name)
    if exclude_id is not None:
        query = query.where(Device.id != exclude_id)
    if session.scalar(query) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A device named {name!r} exists.")


def _quota(session: SessionDep, max_meters: int | None) -> QuotaOut:
    """Build the current quota snapshot."""
    used = session.scalar(select(func.count()).select_from(Device)) or 0
    return QuotaOut(
        used=used,
        max_meters=max_meters,
        over_quota=max_meters is not None and used > max_meters,
    )


def _enforce_quota(session: SessionDep, max_meters: int | None) -> None:
    """Refuse a new device once the licensed count is reached (SPEC §3.3).

    409, not 403: 403 is spoken for by the role guard and by Limited Mode, and
    being at your limit is a state conflict rather than an authorization
    failure.

    Counting and then inserting is a TOCTOU race — two concurrent creates could
    land one device over the limit. Accepted deliberately: one process, one
    SQLite file, 10-30 meters, and one admin. A lock or a retry here would cost
    more than the failure it prevents.

    Raises:
        HTTPException: 409 when the machine is at or over its licensed count.
    """
    if max_meters is None:
        return
    used = session.scalar(select(func.count()).select_from(Device)) or 0
    if used >= max_meters:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This machine is licensed for {max_meters} meter(s) and already has {used}. "
                "Delete a device or ask the vendor for a larger license."
            ),
        )


def _require_device(session: SessionDep, device_id: int) -> Device:
    """Load a device or refuse with 404.

    Raises:
        HTTPException: 404 if no such device.
    """
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No device with id {device_id}")
    return device


def _kept(new: str | None, stored: str) -> str:
    """Return the secret to store: the new one, or the stored one if blank (D10)."""
    return new if new else stored


# ─── Static routes ────────────────────────────────────────────────────────────
#
# Declared BEFORE ``/{device_id}`` so ``/catalog`` is not parsed as a device id.
#
# A *mistyped* path under this prefix — ``/api/devices/models``, say, which M3-1
# removed — answers **405, not 404**, because Starlette matches the ``/{device_id}``
# template (which carries PUT and DELETE) before FastAPI converts the segment to an
# int. Declaring the routes as ``/{device_id:int}`` would fix that, and was tried:
# it makes the router's own path string disagree with the one OpenAPI documents,
# which breaks ``test_the_sweep_sees_everything_openapi_documents`` — the guard that
# stops a new router from escaping the JWT sweep. A cosmetic status code on a route
# with no callers is not worth normalising converter spellings inside that guard,
# so 405 stands. Don't re-try it without reading that test first.


@router.get("")
def list_devices(session: SessionDep) -> ApiResponse[list[DeviceOut]]:
    """List every configured device, oldest first. Any authenticated role."""
    devices = session.scalars(select(Device).order_by(Device.id)).all()
    return ApiResponse.ok([_to_out(device) for device in devices])


@router.get("/catalog")
def list_catalog() -> ApiResponse[list[CatalogEntry]]:
    """List the meter models this build can actually drive, in dropdown order.

    Takes no ``SessionDep``: the answer is a constant derived from the catalog and
    the driver registry, so opening a database session per request would buy
    nothing. (The router-level JWT guard still applies.)

    Filtered against the **driver registry**, which is the single source of
    truth for what can be driven — so the Model dropdown can never offer a model
    that will fail to connect. M3 shows ``prometer100`` alone; the other eight
    appear when M4 lands their drivers, with no change here (SPEC §3.3).

    Any authenticated role.
    """
    drivable = set(supported_models())
    return ApiResponse.ok([_to_catalog_entry(model, spec) for model, spec in CATALOG.items() if model in drivable])


@router.get("/quota")
def get_quota(session: SessionDep, license_service: LicenseServiceDep) -> ApiResponse[QuotaOut]:
    """Report how many meters are configured and how many are licensed.

    ``max_meters`` is read through the LicenseService **per request** (ADR 0001)
    — never captured in a module-level variable, a default argument or a cache —
    so a new Activation Code changes this answer without a restart.

    Any authenticated role.
    """
    return ApiResponse.ok(_quota(session, license_service.current_state().max_meters))


@router.post("/test-connection")
def test_connection(payload: TestConnectionRequest, admin: AdminDep) -> ApiResponse[TestConnectionOut]:
    """Try a form's transport values against a meter, writing nothing.

    Always answers **200**: a meter that refuses is a *successful* execution of
    a diagnostic, which is exactly what makes this different from Create. The
    verdict is in the payload.

    Admin only. SPEC §3.2 grants read and Read now to every role and everything
    mutating to admin; Test connection is neither, so it is decided on its own
    terms — it is the diagnostic half of the admin-only Create/Update form, and
    it points this machine's socket (or COM port) at whatever the form holds.

    Raises:
        HTTPException: 403 for a non-admin, 422 if the model is unknown.
    """
    _require_known_model(payload.model)
    conn = connection_params_from_transport(payload.transport.model_dump())
    try:
        result = probe_meter(model=payload.model, conn=conn, password=payload.password)
    except ProbeError as exc:
        return ApiResponse.ok(
            TestConnectionOut(reachable=False, meter_serial=None, reason=exc.reason.value, message=str(exc))
        )

    return ApiResponse.ok(
        TestConnectionOut(
            reachable=True,
            meter_serial=result.meter_serial,
            reason=None,
            message=f"Connected — the meter reports serial {result.meter_serial}.",
        )
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_device(
    payload: DeviceCreate,
    response: Response,
    session: SessionDep,
    poller: PollerDep,
    license_service: LicenseServiceDep,
    admin: AdminDep,
) -> ApiResponse[DeviceOut]:
    """Probe a meter, then add it and put it into the Poller rotation.

    Admin only (SPEC §3.2). The order of checks is deliberate: the model, the
    quota and the name are cheap and decided locally, so a person never waits
    seconds on a DLMS association to be told they made a typo. Only then does
    the machine talk to the meter, and only if the meter answers with an
    identity is a row written — ADR 0005's "no serial, no row".

    The Poller restarts so the new device gets a worker without waiting for a
    process restart — the same "applies live" principle as activation.

    Raises:
        HTTPException: 403 for a non-admin · 422 for an unknown model · 409 for
            a full quota, a taken name, or a serial another device holds.

    Returns:
        The created device, or a 502 failure envelope naming why the meter
        refused — in which case **nothing was written**.
    """
    _require_known_model(payload.model)
    _enforce_quota(session, license_service.current_state().max_meters)
    _reject_duplicate_name(session, payload.name)

    transport = payload.transport.model_dump()
    conn = connection_params_from_transport(transport)
    try:
        probe = probe_meter(model=payload.model, conn=conn, password=payload.password)
    except ProbeError as exc:
        return _probe_failure(response, exc)

    _reject_duplicate_serial(session, probe.meter_serial)

    device = Device(
        name=payload.name,
        brand=payload.brand,
        model=payload.model.lower(),
        meter_serial=probe.meter_serial,
        site_name=payload.site_name,
        site_code=payload.site_code,
        customer=payload.customer,
        meter_number=payload.meter_number,
        group_name=payload.group_name,
        transport=transport,
        password=payload.password,
        block_cipher_key=payload.block_cipher_key,
        authentication_key=payload.authentication_key,
        first_bill_date=payload.first_bill_date,
        bill_day_feb28=payload.bill_day_feb28,
        bill_day_feb29=payload.bill_day_feb29,
        bill_day_30=payload.bill_day_30,
        bill_day_31=payload.bill_day_31,
        enabled=True,
        # Online immediately, not Unknown-until-the-first-tick: the probe above
        # held a conversation with this meter seconds ago, so making the operator
        # watch Unknown for a minute would report less than we know (ADR 0004).
        status=DeviceStatus.ONLINE.value,
        status_detail=None,
        status_checked_at=datetime.now(UTC),
        consecutive_failures=0,
    )
    session.add(device)
    session.flush()
    record_event(session, device_id=device.id, kind=DeviceEventKind.CREATED, actor=admin.username)
    session.commit()
    session.refresh(device)
    logger.info("Device %s added at %s (serial %s)", device.name, device.transport_endpoint, device.meter_serial)

    poller.restart()
    return ApiResponse.ok(_to_out(device))


@router.put("/{device_id}")
def update_device(
    device_id: DeviceIdPath,
    payload: DeviceUpdate,
    response: Response,
    session: SessionDep,
    poller: PollerDep,
    admin: AdminDep,
) -> ApiResponse[DeviceOut]:
    """Re-probe a meter, then save every edited field.

    Admin only (SPEC §3.2). **Update always probes** (ADR 0005): if the serial
    that comes back differs from the stored one, the edit is pointing this row
    at a different physical meter, and accepting it would silently merge two
    meters' history into one row. A row whose serial is still NULL — created
    before M3 — is identified here, which is that row's only way out.

    Nothing is assigned until the probe has succeeded and both serial checks
    have passed, so a refusal leaves every column exactly as it was.

    Raises:
        HTTPException: 403 for a non-admin · 404 for an unknown device · 422 for
            an unknown model · 409 for a taken name, a changed serial, or a
            serial another device holds.

    Returns:
        The updated device, or a 502 failure envelope naming why the meter
        refused — in which case **nothing was written**.
    """
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No device with id {device_id}")

    _require_known_model(payload.model)
    _reject_duplicate_name(session, payload.name, exclude_id=device_id)

    # The effective secrets: blank means keep (D10). The re-probe has to use the
    # password that will actually be stored, or a saved device could hold
    # credentials that were never proven against the meter.
    password = _kept(payload.password, device.password)
    block_cipher_key = _kept(payload.block_cipher_key, device.block_cipher_key or "") or None
    authentication_key = _kept(payload.authentication_key, device.authentication_key or "") or None

    transport = payload.transport.model_dump()
    conn = connection_params_from_transport(transport)
    try:
        probe = probe_meter(model=payload.model, conn=conn, password=password)
    except ProbeError as exc:
        return _probe_failure(response, exc)

    _reject_changed_serial(device, probe)
    _reject_duplicate_serial(session, probe.meter_serial, exclude_id=device_id)

    device.name = payload.name
    device.brand = payload.brand
    device.model = payload.model.lower()
    device.meter_serial = probe.meter_serial
    device.site_name = payload.site_name
    device.site_code = payload.site_code
    device.customer = payload.customer
    device.meter_number = payload.meter_number
    device.group_name = payload.group_name
    device.transport = transport
    device.password = password
    device.block_cipher_key = block_cipher_key
    device.authentication_key = authentication_key
    device.first_bill_date = payload.first_bill_date
    device.bill_day_feb28 = payload.bill_day_feb28
    device.bill_day_feb29 = payload.bill_day_feb29
    device.bill_day_30 = payload.bill_day_30
    device.bill_day_31 = payload.bill_day_31
    record_event(session, device_id=device.id, kind=DeviceEventKind.UPDATED, actor=admin.username)
    session.commit()
    session.refresh(device)
    logger.info("Device %s updated at %s", device.name, device.transport_endpoint)

    poller.restart()
    return ApiResponse.ok(_to_out(device))


def _reject_changed_serial(device: Device, probe: ProbeResult) -> None:
    """Refuse an edit that points this row at a different physical meter.

    A stored NULL serial means the row was created before M3 and was never
    identified; filling it in is the intended outcome, not a mismatch.

    Raises:
        HTTPException: 409 naming both serials, so the operator can see whether
            they typed the wrong host or moved the meter.
    """
    if device.meter_serial is None or device.meter_serial == probe.meter_serial:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"This device is meter {device.meter_serial}, but {probe.meter_serial} answered at that address. "
            "Nothing was changed — add a new device for the other meter, or correct the address."
        ),
    )


@router.delete("/{device_id}")
def delete_device(
    device_id: DeviceIdPath, session: SessionDep, poller: PollerDep, admin: AdminDep
) -> ApiResponse[bool]:
    """Delete a device and its readings, then rebuild the Poller rotation.

    Admin only (SPEC §3.2). The device's Meter Serial becomes reusable
    immediately — there is no tombstone (ADR 0005), because remembering every
    serial ever seen would turn one mistyped meter into a permanent block on
    re-adding hardware the customer physically owns.

    Raises:
        HTTPException: 403 for a non-admin, 404 if no such device.
    """
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No device with id {device_id}")

    session.delete(device)
    session.commit()
    logger.info("Device %s deleted", device_id)

    poller.restart()
    return ApiResponse.ok(True)


@router.post("/{device_id}/pause")
def pause_device(
    device_id: DeviceIdPath, session: SessionDep, poller: PollerDep, admin: AdminDep
) -> ApiResponse[DeviceOut]:
    """Stop every background read of one device, leaving it fully visible.

    Admin only (SPEC §3.2). Pause is one column — the existing ``enabled``
    (CONTEXT.md — Pause). There is no ``polling_paused`` beside it: v1 needed two
    because its ``is_active`` was a soft-delete that hid the device from every
    list, and v2 deletes for real.

    **Writing the column is not enough.** ``Device.enabled`` is read in exactly
    one place in the Poller — ``_enabled_devices()``, called only from
    ``start()`` — and a worker loops over a snapshot it never re-reads. Without
    the restart below, a paused meter would keep being read until somebody
    happened to add or delete a device. Restarting rather than adding a per-tick
    check is also what preserves v1 ADR 0009's intent: ``stop()`` waits for the
    in-flight read instead of cutting the socket.

    The stored status columns are deliberately left alone: the API already
    reports ``paused`` because ``enabled`` is false, and what the last read
    proved stays on the row for Resume to discard.

    Raises:
        HTTPException: 403 for a non-admin, 404 for an unknown device.

    Returns:
        The device as it now reads.
    """
    device = _require_device(session, device_id)
    if not device.enabled:
        # Already paused. 200 with the unchanged device, no event (nothing
        # changed) and no restart — there is no reason to respawn every worker
        # on the site because somebody clicked twice.
        return ApiResponse.ok(_to_out(device))

    device.enabled = False
    record_event(session, device_id=device_id, kind=DeviceEventKind.PAUSED, actor=admin.username)
    session.commit()
    session.refresh(device)
    logger.info("Device %s paused by %s", device.name, admin.username)

    # After the commit, always: start() re-reads the enabled devices from the
    # database, so an uncommitted change would be invisible to it.
    poller.restart()
    return ApiResponse.ok(_to_out(device))


@router.post("/{device_id}/resume")
def resume_device(
    device_id: DeviceIdPath, session: SessionDep, poller: PollerDep, admin: AdminDep
) -> ApiResponse[DeviceOut]:
    """Put a paused device back into the Poller rotation.

    Admin only (SPEC §3.2). It resumes into **Unknown**, not into the status it
    had before the pause: while paused nobody talked to the meter, so nobody
    knows whether it is still there (ADR 0004). ``status_checked_at`` is cleared
    for the same reason — a pre-pause check time shown as current would present a
    stale fact as fresh — and the strike counter starts over, because three
    failures from before an operator intervened are not evidence about now.

    Raises:
        HTTPException: 403 for a non-admin, 404 for an unknown device.

    Returns:
        The device as it now reads.
    """
    device = _require_device(session, device_id)
    if device.enabled:
        # Already running: 200, unchanged, no event, no restart (D13). In
        # particular it must NOT reset an online device to unknown for nothing.
        return ApiResponse.ok(_to_out(device))

    device.enabled = True
    device.status = DeviceStatus.UNKNOWN.value
    device.status_detail = "Resumed — waiting for the first tick."
    device.status_checked_at = None
    device.consecutive_failures = 0
    record_event(session, device_id=device_id, kind=DeviceEventKind.RESUMED, actor=admin.username)
    session.commit()
    session.refresh(device)
    logger.info("Device %s resumed by %s", device.name, admin.username)

    poller.restart()
    return ApiResponse.ok(_to_out(device))


@router.post("/{device_id}/read-now")
def read_now(device_id: DeviceIdPath, session: SessionDep, user: CurrentUserDep) -> ApiResponse[ReadNowOut]:
    """Read a device now, ahead of the Poller, and report what happened.

    **Every authenticated role** (SPEC §3.2), and it works on a **paused**
    device: Pause governs background reads only, and a person asking whether a
    meter they just fixed is answering is precisely what Read now is for.

    Three jobs run, in this order:

    1. ``liveness`` — the same :func:`~arichds.acquisition.probe.probe_meter`
       Create and Update use: one association, one register (the Meter Serial),
       disconnect. That is what ADR 0007 §2 calls a liveness read, it **cannot**
       return an electrical value by construction, and it writes no Interval
       Reading. It is also the **only** job here that touches device status
       (ADR 0004).
    2. ``load_profile`` (M5a-1) — :func:`~arichds.acquisition.load_profile.read_and_store_load_profile`,
       which walks from the stored watermark to now in 24 h chunks under one
       Manual Read acquisition and stores what it reads. It runs only after the
       liveness read succeeded: a meter that did not answer one register will
       not answer a profile, and asking anyway would just spend the operator's
       wait.
    3. ``billing`` (M6a, issue #21) — :func:`~arichds.acquisition.billing.read_and_store_billing`,
       which reads the whole billing buffer in one round trip (ADR 0009 — no
       window, no watermark) and stores it. Same "only after liveness
       succeeded" rule, and its failure is never a strike either.

    Every job that was *considered* gets an entry, including one that could not
    run (D12) — see :class:`ReadNowOut`.

    The serial it reads is deliberately ignored beyond "it answered" (D9).
    Serial-mismatch handling belongs to Update (ADR 0005); doing it here would
    let Read now fail for a reason its button does not promise.

    Always answers **200** (D10) — a meter that refuses is a successful
    execution of a diagnostic, exactly as ``POST /test-connection`` decided. The
    verdict is in ``results[].ok``.

    Raises:
        HTTPException: 404 if no such device.

    Returns:
        The job results plus the device's status as this call left it.
    """
    device = _require_device(session, device_id)
    endpoint = device.transport_endpoint
    transport = device.transport or {}
    results: list[ReadNowJobResult] = []

    if device.model.lower() not in supported_models():
        # Not a meter failure and therefore not a strike: nothing was asked of
        # the meter. `record_no_driver` parks it at Unknown with the reason.
        # No `load_profile` entry either — there is no driver to ask whether
        # this model has one.
        record_no_driver(device_id, device.model)
        results.append(
            ReadNowJobResult(
                job=JOB_LIVENESS,
                ok=False,
                detail=(
                    f"Model {device.model!r} has no driver in this build — press Update to re-identify this device."
                ),
            )
        )
    else:
        try:
            conn = connection_params_from_transport(transport)
            probe_meter(model=device.model, conn=conn, password=device.password)
        except ProbeError as exc:
            # `str(exc)` is already operator-facing and already free of the
            # password — that is ProbeError's contract, so it is passed straight
            # through rather than reworded here.
            record_failure(device_id, str(exc))
            results.append(ReadNowJobResult(job=JOB_LIVENESS, ok=False, detail=str(exc)))
            results.append(
                ReadNowJobResult(
                    job=JOB_LOAD_PROFILE,
                    ok=False,
                    detail="Skipped — the meter did not answer the liveness read.",
                )
            )
            results.append(
                ReadNowJobResult(
                    job=JOB_BILLING,
                    ok=False,
                    detail="Skipped — the meter did not answer the liveness read.",
                )
            )
        except ValueError as exc:
            # A malformed stored transport — never produced by this module's
            # own Create/Update, which always validate first, but a config
            # problem rather than a meter refusal either way, so it is not a
            # strike (mirrors the no-driver branch above). Nothing can be built
            # to ask about a load profile, so that job gets no entry.
            detail = f"Device {device.name!r} has no usable transport: {exc}"
            logger.warning(detail)
            results.append(ReadNowJobResult(job=JOB_LIVENESS, ok=False, detail=detail))
        else:
            record_success(device_id)
            results.append(ReadNowJobResult(job=JOB_LIVENESS, ok=True, detail=f"The meter answered at {endpoint}."))
            results.append(_read_load_profile_job(device_id, device.model))
            results.append(_read_billing_job(device_id, device.model))

    # Re-read: the recorders wrote through their own session (they have to — the
    # Poller calls them with no request session), so this request's identity map
    # still holds the pre-read row. Without this the caller would be told the
    # state its own click *replaced*.
    session.refresh(device)
    return ApiResponse.ok(
        ReadNowOut(results=results, status=display_status(device), checked_at=device.status_checked_at)
    )


def _read_load_profile_job(device_id: int, model: str) -> ReadNowJobResult:
    """Run the load-profile job for a device whose liveness read just succeeded.

    Never touches device status (ADR 0004, D11): the liveness read above is the
    evidence status is made of, and a load profile that failed afterwards must
    not undo an Online the meter just earned. The job returns its failures as
    sentences rather than raising, so this cannot turn Read now into a 500.
    """
    outcome = read_and_store_load_profile(device_id)

    if not outcome.supported:
        # `outcome.error` is only set here by an unbuildable driver, which this
        # branch cannot reach — the liveness probe built one seconds ago. It is
        # preferred anyway rather than discarded, because a sentence that says
        # what actually went wrong beats one that guesses.
        detail = outcome.error or f"Model {model!r} has no load profile in this build — nothing was read."
        return ReadNowJobResult(job=JOB_LOAD_PROFILE, ok=False, detail=detail)

    if outcome.error is not None:
        return ReadNowJobResult(
            job=JOB_LOAD_PROFILE,
            ok=False,
            detail=f"Stored {outcome.stored} Interval Readings before the read stopped: {outcome.error}",
        )

    if outcome.stored == 0:
        return ReadNowJobResult(job=JOB_LOAD_PROFILE, ok=True, detail="The meter had no new intervals to store.")

    # `through` is the highest `read_at` now in the table, so it cannot be None
    # once a row was stored — the fallback exists so a surprise there degrades
    # to a shorter sentence instead of a TypeError inside the format.
    through = f" up to {outcome.through:%Y-%m-%d %H:%M} UTC" if outcome.through is not None else ""
    detail = f"Stored {outcome.stored} Interval Readings{through}."
    if outcome.budget_exhausted:
        detail += " More history remains — press Read now again to continue."
    return ReadNowJobResult(job=JOB_LOAD_PROFILE, ok=True, detail=detail)


def _read_billing_job(device_id: int, model: str) -> ReadNowJobResult:
    """Run the billing job (M6a, issue #21) for a device whose liveness read
    just succeeded.

    Never touches device status (ADR 0004, D11) — same reason as
    :func:`_read_load_profile_job`: a billing read that failed afterwards must
    not undo an Online the meter just earned, and it is never a strike.
    """
    outcome = read_and_store_billing(device_id)

    if not outcome.supported:
        detail = outcome.error or f"Model {model!r} has no billing profile in this build — nothing was read."
        return ReadNowJobResult(job=JOB_BILLING, ok=False, detail=detail)

    if outcome.error is not None:
        return ReadNowJobResult(job=JOB_BILLING, ok=False, detail=outcome.error)

    if outcome.stored == 0 and not outcome.open_updated:
        return ReadNowJobResult(job=JOB_BILLING, ok=True, detail="The meter had no new billing periods to store.")

    parts: list[str] = []
    if outcome.stored:
        parts.append(f"{outcome.stored} closed billing period{'s' if outcome.stored != 1 else ''}")
    if outcome.open_updated:
        parts.append("the Open Period")
    return ReadNowJobResult(job=JOB_BILLING, ok=True, detail=f"Stored {' and '.join(parts)}.")


@router.post("/{device_id}/readings/clear")
def clear_readings(
    device_id: DeviceIdPath, payload: ClearReadingsRequest, session: SessionDep, admin: AdminDep
) -> ApiResponse[int]:
    """Delete every Interval Reading and Billing Reading of one device, keeping
    the device and its history.

    **It deletes real rows from M5a-1 on.** ADR 0007 stopped the Poller writing
    rows (M3-4), so between then and now this always answered ``0``; issue #15
    landed the load-profile reader that fills ``load_profile_readings``, and this
    is the one place they are removed again. **M6a (issue #21) extends it to
    cover ``billing_readings`` too** — one button, one confirmation, both tables,
    rather than a second irreversible-delete ritual for the same device.

    Deleting the load-profile rows also resets what the load-profile job knows:
    the watermark **is** the data (ADR 0008), so the next Read now starts its
    walk 90 days back rather than where the deleted rows ended. Billing has no
    watermark to reset — ADR 0009's read is always the whole buffer — but the
    same fact makes the deleted billing periods **come back**: the next billing
    read (Manual or the daily job) re-imports every closed period still in the
    meter. That repairs a value that was wrong on *our* side (a scaler fix,
    re-read correctly); it is a no-op for a value the meter itself reports
    wrong. The frontend confirmation text says so.

    Admin only (SPEC §3.2). The device's Device Events are kept **on purpose**:
    they are the evidence of who deleted the data, and destroying that evidence
    in the same click as the data would be the one thing an audit trail exists to
    prevent.

    The typed confirmation is the guard, because this cannot be undone. A
    mismatch answers 409 — a conflict, consistent with this router's rule — and
    the message does **not** repeat the correct name: echoing it would turn the
    ritual into copy-paste and remove the only thing it was protecting.

    Raises:
        HTTPException: 403 for a non-admin · 404 for an unknown device · 409 if
            the confirmation name does not match, in which case **nothing was
            deleted**.

    Returns:
        The **total** rows deleted (interval readings plus billing periods),
        so the toast can say — the API contract stays one number for a device
        event detail that already names both counts.
    """
    device = _require_device(session, device_id)
    if payload.confirm_name != device.name:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The confirmation name does not match this device. Nothing was deleted.",
        )

    intervals = session.execute(
        delete(LoadProfileReading).where(LoadProfileReading.device_id == device_id),
        execution_options={"synchronize_session": False},
    ).rowcount
    periods = session.execute(
        delete(BillingReading).where(BillingReading.device_id == device_id),
        execution_options={"synchronize_session": False},
    ).rowcount
    record_event(
        session,
        device_id=device_id,
        kind=DeviceEventKind.DATA_CLEARED,
        detail=f"Deleted {intervals} interval readings and {periods} billing periods.",
        actor=admin.username,
    )
    session.commit()
    logger.info(
        "Deleted %d interval readings and %d billing periods of device %s by %s",
        intervals,
        periods,
        device.name,
        admin.username,
    )

    return ApiResponse.ok(intervals + periods)


@router.get("/{device_id}/events")
def list_device_events(
    device_id: DeviceIdPath,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200, description="Page size")] = 50,
    offset: Annotated[int, Query(ge=0, description="Rows to skip")] = 0,
) -> ApiResponse[DeviceEventPage]:
    """Return one page of a device's history, newest first. Any authenticated role.

    The ``id`` tiebreak in the ordering is load-bearing, not decoration: SQLite's
    ``CURRENT_TIMESTAMP`` has one-second resolution, so several events written
    while an operator clicks share a timestamp exactly, and without the tiebreak
    their order — and therefore which page they land on — is undefined.

    Raises:
        HTTPException: 404 if no such device.
    """
    _require_device(session, device_id)

    total = session.scalar(select(func.count()).select_from(DeviceEvent).where(DeviceEvent.device_id == device_id)) or 0
    events = session.scalars(
        select(DeviceEvent)
        .where(DeviceEvent.device_id == device_id)
        .order_by(DeviceEvent.created_at.desc(), DeviceEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return ApiResponse.ok(
        DeviceEventPage(
            items=[DeviceEventOut.model_validate(event) for event in events],
            total=total,
            limit=limit,
            offset=offset,
        )
    )
