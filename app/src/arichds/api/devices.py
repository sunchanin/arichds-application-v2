"""Device Manager — probe-first CRUD, the model catalog, and the device quota (M3-1).

Three independent gates sit in front of every handler here:

* **Limited Mode** — everything in this router is under ``/api`` and not on the
  license allow-list, so an unlicensed machine gets 403 ``LICENSE_INVALID``
  before any handler runs.
* **Authentication** (M2-1) — the router-level dependency means an
  unauthenticated request is refused with 401 *before* its body is validated,
  so a ``POST`` with no body answers 401 rather than 422.
* **Role** (SPEC §3.2) — changing a device, and testing a connection, are
  admin-only; reading is open to any authenticated user.

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
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from arichds.acquisition.catalog import CATALOG, ModelSpec
from arichds.acquisition.drivers.factory import supported_models
from arichds.acquisition.probe import ProbeError, ProbeResult, probe_meter
from arichds.api.deps import AdminDep, LicenseServiceDep, PollerDep, SessionDep, get_current_user
from arichds.api.envelope import ApiResponse
from arichds.db.models import Device, IntervalReading

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["devices"], dependencies=[Depends(get_current_user)])

#: The envelope error code every meter-side failure carries.
ERROR_PROBE_FAILED = "PROBE_FAILED"


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
        host: TCP host of the Transport Endpoint.
        port: TCP port of the Transport Endpoint.
        password: DLMS authentication password. Stored, never returned.
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
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
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

    The password and the two cipher keys are absent by construction: they are
    not fields of this model, so no handler can leak them by accident.

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
        host: TCP host.
        port: TCP port.
        endpoint: The Transport Endpoint (``host:port``) — the Poller lock key.
        enabled: Whether the Poller reads it.
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
    host: str
    port: int
    endpoint: str
    enabled: bool
    first_bill_date: date | None
    bill_day_feb28: int | None
    bill_day_feb29: int | None
    bill_day_30: int | None
    bill_day_31: int | None
    created_at: datetime


class CatalogEntry(BaseModel):
    """One selectable meter model, with what the Add form needs to prefill.

    ``fixed_password`` is included on purpose: it is a documented brand-wide
    default (CEWE's is printed in this repo's README), not a per-site secret,
    and prefilling it is what stops an operator from guessing.

    Attributes:
        model: Canonical model identifier — what to submit.
        brand: Owning brand.
        ui_label: What to show in the dropdown.
        default_port: Prefill for the Port field, or None for serial-only models.
        fixed_password: Prefill for the Password field, or None when the model
            uses key-based auth.
        supports_serial: True if the model connects over serial transport.
        supports_battery: True if the model exposes a battery reading.
        supports_energy_summary: True if the model exposes an energy summary.
        supports_special_days: True if the model exposes a special-days table.
    """

    model: str
    brand: str
    ui_label: str
    default_port: int | None
    fixed_password: str | None
    supports_serial: bool
    supports_battery: bool
    supports_energy_summary: bool
    supports_special_days: bool


class QuotaOut(BaseModel):
    """How many meters this machine may have, and how many it has.

    Its own endpoint rather than a field on the device list: ``GET /api/devices``
    must keep returning a plain list (Monitor depends on it), and
    ``/api/license/status`` knows ``max_meters`` but not the count.

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
        host: TCP host to try.
        port: TCP port to try.
        password: DLMS authentication password. Never stored, never echoed.
    """

    model: str = Field(min_length=1, max_length=64)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
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


class ReadingOut(BaseModel):
    """One Interval Reading — always UTC, always kWh.

    SQLite has no timezone type, so ``read_at`` comes back off the database as a
    naive datetime even though the stored wall clock is UTC by contract. The
    validator re-attaches UTC here so the JSON carries an explicit offset and no
    client ever has to assume one.

    Attributes:
        device_id: Owning device.
        read_at: When the value was taken (UTC).
        source: Which acquisition path produced it.
        interval: Cadence label.
        volt_l1/volt_l2/volt_l3: Phase-to-neutral voltage (V).
        current_l1/current_l2/current_l3: Line current (A).
        freq: Frequency (Hz).
        import_active_kwh: Cumulative active energy import (kWh).
    """

    model_config = ConfigDict(from_attributes=True)

    device_id: int
    read_at: datetime
    source: str
    interval: str
    volt_l1: float | None = None
    volt_l2: float | None = None
    volt_l3: float | None = None
    current_l1: float | None = None
    current_l2: float | None = None
    current_l3: float | None = None
    freq: float | None = None
    import_active_kwh: float | None = None

    @field_validator("read_at")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        """Re-attach UTC to the naive datetime SQLite hands back."""
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


DeviceIdPath = Annotated[int, Path(ge=1, description="Device id")]


def _to_out(device: Device) -> DeviceOut:
    """Project a :class:`Device` row onto the API shape (secrets excluded)."""
    transport = device.transport or {}
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
        host=str(transport.get("host", "")),
        port=int(transport.get("port", 0)),
        endpoint=device.transport_endpoint,
        enabled=device.enabled,
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
        default_port=spec.default_port,
        fixed_password=spec.fixed_password,
        supports_serial=spec.supports_serial,
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


def _kept(new: str | None, stored: str) -> str:
    """Return the secret to store: the new one, or the stored one if blank (D10)."""
    return new if new else stored


# ─── Static routes ────────────────────────────────────────────────────────────
#
# Declared BEFORE ``/{device_id}`` so ``/catalog`` is not parsed as a device id.


@router.get("")
def list_devices(session: SessionDep) -> ApiResponse[list[DeviceOut]]:
    """List every configured device, oldest first. Any authenticated role."""
    devices = session.scalars(select(Device).order_by(Device.id)).all()
    return ApiResponse.ok([_to_out(device) for device in devices])


@router.get("/catalog")
def list_catalog(session: SessionDep) -> ApiResponse[list[CatalogEntry]]:
    """List the meter models this build can actually drive, in dropdown order.

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
    it points this machine's socket at an arbitrary ``host:port``.

    Raises:
        HTTPException: 403 for a non-admin, 422 if the model is unknown.
    """
    _require_known_model(payload.model)
    try:
        result = probe_meter(model=payload.model, host=payload.host, port=payload.port, password=payload.password)
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

    try:
        probe = probe_meter(model=payload.model, host=payload.host, port=payload.port, password=payload.password)
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
        transport={"kind": "net", "host": payload.host, "port": payload.port},
        password=payload.password,
        block_cipher_key=payload.block_cipher_key,
        authentication_key=payload.authentication_key,
        first_bill_date=payload.first_bill_date,
        bill_day_feb28=payload.bill_day_feb28,
        bill_day_feb29=payload.bill_day_feb29,
        bill_day_30=payload.bill_day_30,
        bill_day_31=payload.bill_day_31,
        enabled=True,
    )
    session.add(device)
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

    try:
        probe = probe_meter(model=payload.model, host=payload.host, port=payload.port, password=password)
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
    device.transport = {"kind": "net", "host": payload.host, "port": payload.port}
    device.password = password
    device.block_cipher_key = block_cipher_key
    device.authentication_key = authentication_key
    device.first_bill_date = payload.first_bill_date
    device.bill_day_feb28 = payload.bill_day_feb28
    device.bill_day_feb29 = payload.bill_day_feb29
    device.bill_day_30 = payload.bill_day_30
    device.bill_day_31 = payload.bill_day_31
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


@router.get("/{device_id}/readings/latest")
def get_latest_reading(device_id: DeviceIdPath, session: SessionDep) -> ApiResponse[ReadingOut | None]:
    """Return the most recent Interval Reading for a device.

    ``data`` is null when the Poller has not completed a tick yet — a new
    device with no readings is a normal state, not an error.

    Raises:
        HTTPException: 404 if no such device.
    """
    if session.get(Device, device_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No device with id {device_id}")

    reading = session.scalars(
        select(IntervalReading)
        .where(IntervalReading.device_id == device_id)
        .order_by(IntervalReading.read_at.desc(), IntervalReading.id.desc())
        .limit(1)
    ).first()

    return ApiResponse.ok(ReadingOut.model_validate(reading) if reading is not None else None)
