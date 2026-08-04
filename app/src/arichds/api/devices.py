"""Device CRUD and latest readings — the Monitor page's backend.

Minimal by intent: M1 proves the chain, M3 turns this into the real Device
Manager (catalog of nine models, serial transport, pause/reconnect, quota
checks). Adding fields here now would be inventing M3's shape early.

Guarded by Limited Mode: everything in this router is under ``/api`` and not on
the allow-list, so an unlicensed machine gets 403 ``LICENSE_INVALID`` before any
handler runs.

**No authentication** — deliberately, per SPEC §3.1. M2 fits the guard
retroactively to every endpoint M1 leaves open.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from arichds.acquisition.drivers.factory import supported_models
from arichds.api.deps import PollerDep, SessionDep
from arichds.api.envelope import ApiResponse
from arichds.db.models import Device, IntervalReading

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["devices"])


class DeviceCreate(BaseModel):
    """Request body for adding a device.

    Attributes:
        name: Operator-facing label, unique on this machine.
        brand: Meter brand, e.g. ``"CEWE"`` or ``"SIM"``.
        model: Model identifier resolving a driver, e.g. ``"prometer100"``/``"SIM"``.
        host: TCP host of the Transport Endpoint.
        port: TCP port of the Transport Endpoint.
        password: DLMS authentication password. Stored, never returned.
    """

    name: str = Field(min_length=1, max_length=128)
    brand: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=64)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    password: str = Field(default="", max_length=128)


class DeviceOut(BaseModel):
    """A device as the API exposes it. The password is never included.

    Attributes:
        id: Surrogate key.
        name: Operator-facing label.
        brand: Meter brand.
        model: Model identifier.
        host: TCP host.
        port: TCP port.
        endpoint: The Transport Endpoint (``host:port``) — the Poller lock key.
        enabled: Whether the Poller reads it.
        created_at: When it was added (UTC).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    brand: str
    model: str
    host: str
    port: int
    endpoint: str
    enabled: bool
    created_at: datetime


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
    """Project a :class:`Device` row onto the API shape (password excluded)."""
    transport = device.transport or {}
    return DeviceOut(
        id=device.id,
        name=device.name,
        brand=device.brand,
        model=device.model,
        host=str(transport.get("host", "")),
        port=int(transport.get("port", 0)),
        endpoint=device.transport_endpoint,
        enabled=device.enabled,
        created_at=device.created_at,
    )


@router.get("")
def list_devices(session: SessionDep) -> ApiResponse[list[DeviceOut]]:
    """List every configured device, oldest first."""
    devices = session.scalars(select(Device).order_by(Device.id)).all()
    return ApiResponse.ok([_to_out(device) for device in devices])


@router.get("/models")
def list_supported_models(session: SessionDep) -> ApiResponse[list[str]]:
    """List the meter models this build can drive.

    Lets the Add-device form offer only models that actually resolve to a
    driver, instead of hard-coding a list in the SPA that drifts from M4's
    registry.
    """
    return ApiResponse.ok(supported_models())


@router.post("", status_code=status.HTTP_201_CREATED)
def create_device(payload: DeviceCreate, session: SessionDep, poller: PollerDep) -> ApiResponse[DeviceOut]:
    """Add a device and put it into the Poller rotation immediately.

    The Poller restarts so the new device gets a worker without waiting for a
    process restart — the same "applies live" principle as activation.

    Raises:
        HTTPException: 409 if the name is taken, 422 if the model is unknown.
    """
    if payload.model.lower() not in supported_models():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown meter model {payload.model!r}. Supported: {supported_models()}",
        )

    if session.scalar(select(Device).where(Device.name == payload.name)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A device named {payload.name!r} exists.")

    device = Device(
        name=payload.name,
        brand=payload.brand,
        model=payload.model.lower(),
        transport={"kind": "net", "host": payload.host, "port": payload.port},
        password=payload.password,
        enabled=True,
    )
    session.add(device)
    session.commit()
    session.refresh(device)
    logger.info("Device %s added at %s", device.name, device.transport_endpoint)

    poller.restart()
    return ApiResponse.ok(_to_out(device))


@router.delete("/{device_id}")
def delete_device(device_id: DeviceIdPath, session: SessionDep, poller: PollerDep) -> ApiResponse[bool]:
    """Delete a device and its readings, then rebuild the Poller rotation.

    Raises:
        HTTPException: 404 if no such device.
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
