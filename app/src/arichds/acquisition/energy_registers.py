"""The Energy Registers read job (M7-1, issue #28) — the Meter Registers
tab's Read now button.

**Manual path only** — button-triggered, exactly once, no scheduler job:
Energy Registers are a cumulative snapshot, not a cadence (CONTEXT.md —
Energy Registers). Shaped on :mod:`arichds.acquisition.billing` for the
lock discipline (a single Transport Endpoint acquisition, Manual Read
priority, connect/read/disconnect in a ``finally``) but simpler — there is
no Open Period, no closed-vs-open split, and no background cycle at all.

**``read_at`` is our clock, truncated to whole seconds, stamped by the
writer — never the caller's** (decision 10). The truncation is what makes
``(device_id, read_at)`` mean "two clicks in one second are the same
reading": the *API* endpoint never passes ``now`` explicitly (letting it
default), and only a test injects one, to drive the upsert deterministically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from arichds.acquisition.drivers.base import EnergyRegisterReading, MeterDriver
from arichds.acquisition.locks import EndpointLocks, endpoint_locks
from arichds.acquisition.poller import build_driver
from arichds.constants import MANUAL_READ_LOCK_TIMEOUT_SEC
from arichds.db.models import Device
from arichds.db.models import EnergyRegisterReading as EnergyRegisterReadingRow
from arichds.db.session import session_scope

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnergyRegisterReadResult:
    """What one call to :func:`read_and_store_energy_registers` did.

    Attributes:
        supported: False when this device's driver has no Energy Registers
            at all, or could not be built. Nothing was read and no lock was
            taken.
        row_id: The stored row's id, or None when nothing was written
            (unsupported, or the read failed).
        error: An operator-facing sentence, or None. Never contains a
            password.
    """

    supported: bool
    row_id: int | None
    error: str | None


def read_and_store_energy_registers(
    device_id: int,
    *,
    locks: EndpointLocks | None = None,
    lock_timeout_sec: float = MANUAL_READ_LOCK_TIMEOUT_SEC,
    now: datetime | None = None,
) -> EnergyRegisterReadResult:
    """Read one device's Energy Registers and store the snapshot (M7-1,
    issue #28).

    Takes the Transport Endpoint lock as a **Manual Read** (ADR 0006) —
    there is no background variant of this job.

    Args:
        device_id: The device to read. It must exist — the caller resolved
            it.
        locks: Lock registry. Defaults to the process-wide one.
        lock_timeout_sec: How long to wait for the Transport Endpoint.
        now: When *we* read it — timezone-aware UTC. A parameter so a test
            drives the write without a clock; truncated to whole seconds
            here regardless of who supplied it (decision 10). The API
            endpoint never passes this — only a test may.

    Returns:
        What happened, including a sentence for the operator when it failed.

    Raises:
        ValueError: If *device_id* does not exist.
    """
    now_utc = (datetime.now(UTC) if now is None else now).replace(microsecond=0)
    registry = endpoint_locks() if locks is None else locks

    with session_scope() as session:
        device = session.get(Device, device_id)
        if device is None:
            raise ValueError(f"No device with id {device_id}")
        device_name = device.name
        try:
            driver = build_driver(device)
        except ValueError as exc:
            logger.warning("Energy register read skipped for device %s: %s", device_name, exc)
            return EnergyRegisterReadResult(supported=False, row_id=None, error=str(exc))

    if not driver.supports_energy_registers():
        logger.debug("Device %s (%s) has no Energy Registers — nothing to read", device_name, driver.model_name)
        return EnergyRegisterReadResult(supported=False, row_id=None, error=None)

    endpoint = driver.endpoint
    row_id: int | None = None
    error: str | None = None
    try:
        with registry.get(endpoint).manual(timeout=lock_timeout_sec):
            row_id, error = _read_while_holding(driver, device_id, device_name, endpoint, now_utc)
    except TimeoutError as exc:
        logger.warning("Energy register read of %s skipped: %s busy", device_name, endpoint)
        error = f"The line to {endpoint} was still busy after {lock_timeout_sec:g}s — nothing was read."
        _ = exc

    return EnergyRegisterReadResult(supported=True, row_id=row_id, error=error)


def _read_while_holding(
    driver: MeterDriver,
    device_id: int,
    device_name: str,
    endpoint: str,
    read_at: datetime,
) -> tuple[int | None, str | None]:
    """Connect, read the snapshot, disconnect — with the endpoint already held."""
    try:
        driver.connect()
    except Exception as exc:  # noqa: BLE001 — every meter failure becomes a sentence, never a 500.
        logger.exception("Energy register read of %s at %s failed to connect", device_name, endpoint)
        return None, f"The read of {endpoint} stopped after a {type(exc).__name__}."

    try:
        reading = driver.read_energy_registers()
        row_id = _upsert(device_id, reading, read_at)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Energy register read of %s at %s failed", device_name, endpoint)
        return None, f"The read of {endpoint} stopped after a {type(exc).__name__}."
    finally:
        driver.disconnect()

    return row_id, None


def _upsert(device_id: int, reading: EnergyRegisterReading, read_at: datetime) -> int:
    """Insert a new row, or update the existing one for the same
    ``(device_id, read_at)`` in place — the upsert decision 10 describes: two
    reads inside the same second are the same reading."""
    incoming = reading.as_columns()
    with session_scope() as session:
        existing = session.scalar(
            select(EnergyRegisterReadingRow).where(
                EnergyRegisterReadingRow.device_id == device_id,
                EnergyRegisterReadingRow.read_at == read_at,
            )
        )
        if existing is None:
            row = EnergyRegisterReadingRow(
                device_id=device_id,
                read_at=read_at,
                source=reading.source,
                meter_serial=reading.meter_serial,
                **incoming,
            )
            session.add(row)
            session.flush()
            return row.id

        existing.meter_serial = reading.meter_serial
        for key, value in incoming.items():
            setattr(existing, key, value)
        session.flush()
        return existing.id
