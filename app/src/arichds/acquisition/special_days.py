"""The Special Days read-through (M7-1, issue #28) — what the Special Days
page shows.

**Read-through only — nothing is stored** (CONTEXT.md): the page shows what
a selected meter's own COSEM class-11 table currently holds, and Import from
meter (a **separate**, explicit action on the Holidays page) is the only
path that ever turns one of these entries into a stored Holiday row. Manual
Read only, same lock discipline as
:mod:`arichds.acquisition.energy_registers` — there is no scheduler job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from arichds.acquisition.drivers.base import MeterDriver, SpecialDayEntry
from arichds.acquisition.locks import EndpointLocks, endpoint_locks
from arichds.acquisition.poller import build_driver
from arichds.constants import MANUAL_READ_LOCK_TIMEOUT_SEC
from arichds.db.models import Device
from arichds.db.session import session_scope

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpecialDaysReadResult:
    """What one call to :func:`read_special_days` did.

    Attributes:
        supported: False when this device's driver has no Special Days
            Table at all, or could not be built. Nothing was read and no
            lock was taken.
        entries: The meter's own table, or an empty list on failure — an
            empty table from a *supported* driver is a valid answer, never
            confused with "not supported" (:attr:`supported` distinguishes
            the two).
        error: An operator-facing sentence, or None. Never contains a
            password.
    """

    supported: bool
    entries: list[SpecialDayEntry]
    error: str | None


def read_special_days(
    device_id: int,
    *,
    locks: EndpointLocks | None = None,
    lock_timeout_sec: float = MANUAL_READ_LOCK_TIMEOUT_SEC,
) -> SpecialDaysReadResult:
    """Read one device's whole Special Days Table, read-through (M7-1, issue
    #28). Stores nothing.

    Takes the Transport Endpoint lock as a **Manual Read** (ADR 0006) —
    there is no background variant of this job.

    Args:
        device_id: The device to read. It must exist — the caller resolved
            it.
        locks: Lock registry. Defaults to the process-wide one.
        lock_timeout_sec: How long to wait for the Transport Endpoint.

    Returns:
        What happened, including a sentence for the operator when it failed.

    Raises:
        ValueError: If *device_id* does not exist.
    """
    registry = endpoint_locks() if locks is None else locks

    with session_scope() as session:
        device = session.get(Device, device_id)
        if device is None:
            raise ValueError(f"No device with id {device_id}")
        device_name = device.name
        try:
            driver = build_driver(device)
        except ValueError as exc:
            logger.warning("Special Days read skipped for device %s: %s", device_name, exc)
            return SpecialDaysReadResult(supported=False, entries=[], error=str(exc))

    if not driver.supports_special_days():
        logger.debug("Device %s (%s) has no Special Days Table — nothing to read", device_name, driver.model_name)
        return SpecialDaysReadResult(supported=False, entries=[], error=None)

    endpoint = driver.endpoint
    entries: list[SpecialDayEntry] = []
    error: str | None = None
    try:
        with registry.get(endpoint).manual(timeout=lock_timeout_sec):
            entries, error = _read_while_holding(driver, device_name, endpoint)
    except TimeoutError as exc:
        logger.warning("Special Days read of %s skipped: %s busy", device_name, endpoint)
        error = f"The line to {endpoint} was still busy after {lock_timeout_sec:g}s — nothing was read."
        _ = exc

    return SpecialDaysReadResult(supported=True, entries=entries, error=error)


def _read_while_holding(
    driver: MeterDriver, device_name: str, endpoint: str
) -> tuple[list[SpecialDayEntry], str | None]:
    """Connect, read the table, disconnect — with the endpoint already held."""
    try:
        driver.connect()
    except Exception as exc:  # noqa: BLE001 — every meter failure becomes a sentence, never a 500.
        logger.exception("Special Days read of %s at %s failed to connect", device_name, endpoint)
        return [], f"The read of {endpoint} stopped after a {type(exc).__name__}."

    try:
        entries = driver.read_special_days()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Special Days read of %s at %s failed", device_name, endpoint)
        return [], f"The read of {endpoint} stopped after a {type(exc).__name__}."
    finally:
        driver.disconnect()

    return entries, None
