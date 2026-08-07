"""Device status — the state machine ADR 0004 describes (M3-2).

*"The status of a device is a function of its Poller ticks. The job registry
gains nothing at M3."* Nothing in this module connects to a meter, schedules
anything, or runs in the background: it is called **after** something already
talked (or failed to talk) to a meter, and it writes down what that proved.

Four rules live here and nowhere else:

* **Offline after three consecutive failures**, not the first
  (:data:`~arichds.constants.OFFLINE_AFTER_CONSECUTIVE_FAILURES`). A single
  timeout on a GPRS link is normal.
* **``paused`` is computed, never stored.** :func:`display_status` derives it
  from ``enabled``, so no code path can report a paused device as ``online`` —
  not even one that forgot to check.
* **Events record changes only** (CONTEXT.md — Device Event). A meter that stays
  online all month writes no rows, and the fourth, fifth and sixth failure of one
  outage are the same outage.
* **Automatic transitions carry no actor.** ``actor`` answers "who changed this
  device"; when a meter goes offline nobody did. Only the five operator actions
  carry a username.

**Plain functions, no class.** The Poller and the API both record outcomes, and
the point of putting the rules here is that they cannot each grow their own copy
of them — a registry or an event bus would add indirection without adding a
second implementation to choose between.

**This module deliberately does not import** :mod:`arichds.acquisition.poller`.
The Poller imports *this*, and the reverse would close a cycle — which is why
:func:`record_success` and :func:`record_failure` take no ``TickOutcome``. The
mapping from an outcome to a call lives at the Poller's call site, where the
"a skipped tick is not a strike" rule (ADR 0006) is also readable.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.orm import Session

from arichds.constants import OFFLINE_AFTER_CONSECUTIVE_FAILURES
from arichds.db.models import Device, DeviceEvent
from arichds.db.session import session_scope

logger = logging.getLogger(__name__)


class DeviceStatus(StrEnum):
    """The four statuses of ADR 0004.

    Three of them are stored on ``devices.status``. :attr:`PAUSED` is **not**:
    it is computed at read time from ``enabled`` by :func:`display_status`,
    because a paused device's stored status is the last thing a read proved and
    that fact stops being current the moment nobody is reading.
    """

    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"
    PAUSED = "paused"  # computed at read time — NEVER stored


class DeviceEventKind(StrEnum):
    """What a Device Event row records.

    Two status transitions plus the five operator actions, exactly as ADR 0004
    lists them. There is no ``unknown`` kind by design (D12): unknown is an
    absence of knowledge, not a change in the meter.
    """

    ONLINE = "online"
    OFFLINE = "offline"
    CREATED = "created"
    UPDATED = "updated"
    PAUSED = "paused"
    RESUMED = "resumed"
    DATA_CLEARED = "data_cleared"


def display_status(device: Device) -> DeviceStatus:
    """Return the status to show for *device*.

    Args:
        device: The device row.

    Returns:
        :attr:`DeviceStatus.PAUSED` whenever the device is disabled, otherwise
        the stored status.
    """
    if not device.enabled:
        return DeviceStatus.PAUSED
    return DeviceStatus(device.status)


def record_event(
    session: Session,
    *,
    device_id: int,
    kind: DeviceEventKind,
    detail: str | None = None,
    actor: str | None = None,
) -> None:
    """Add one Device Event row to *session* without committing it.

    Takes a Session rather than opening its own, so an API handler's event row
    lands in the same transaction as the column change it describes: either both
    are true afterwards or neither is.

    Args:
        session: The caller's session. **The caller commits.**
        device_id: Which device the event is about.
        kind: What happened.
        detail: A sentence for a person, or None.
        actor: The username that caused it, or None for an automatic transition.
    """
    session.add(DeviceEvent(device_id=device_id, kind=kind.value, detail=detail, actor=actor))


def record_success(device_id: int) -> None:
    """Record that a read of *device_id* succeeded.

    Opens its own session: the Poller has no request session, and a Manual Read
    that records through here wants the same rules.

    Args:
        device_id: The device that answered.
    """
    with session_scope() as session:
        device = session.get(Device, device_id)
        if device is None:
            # Deleted between the read and the write — a normal race with
            # `delete_device`, not a fault. INFO, because nothing is wrong and
            # nobody needs to act.
            logger.info("Device %s vanished before its success could be recorded", device_id)
            return

        was_online = device.status == DeviceStatus.ONLINE
        device.status = DeviceStatus.ONLINE.value
        device.status_detail = None
        device.status_checked_at = datetime.now(UTC)
        device.consecutive_failures = 0

        if not was_online:
            record_event(session, device_id=device_id, kind=DeviceEventKind.ONLINE)
            logger.info("Device %s is online", device.name)


def _streak_detail(failures: int) -> str:
    """Describe a failure streak for a person to read.

    The fallback used when the caller has no cause of its own — all this layer
    knows is how many reads in a row did not work; the cause is in the
    application log. The singular is spelled out rather than pluralised
    arithmetically because this string is shown in the UI, and "1 consecutive
    failed reads" is not English.

    Args:
        failures: How many consecutive reads have failed. Always at least 1.

    Returns:
        The sentence to store in ``status_detail``.
    """
    if failures <= 1:
        return "The last read failed — see the application log for the cause."
    return f"{failures} consecutive failed reads — see the application log for the cause."


def record_failure(device_id: int, detail: str | None = None) -> None:
    """Record that a read of *device_id* failed.

    Below the threshold the stored status is left exactly as it was: an online
    device stays online through one or two failures (that is the whole point of
    the rule), and an unknown one stays unknown, because two failures do not
    amount to knowing a meter is dead.

    Args:
        device_id: The device that did not answer.
        detail: An operator-facing sentence, when the caller has one. Without it
            the streak is reported instead, which is the only thing this layer
            knows — the cause is in the application log.
    """
    with session_scope() as session:
        device = session.get(Device, device_id)
        if device is None:
            logger.info("Device %s vanished before its failure could be recorded", device_id)
            return

        device.consecutive_failures += 1
        device.status_checked_at = datetime.now(UTC)
        device.status_detail = detail or _streak_detail(device.consecutive_failures)

        reached_threshold = device.consecutive_failures >= OFFLINE_AFTER_CONSECUTIVE_FAILURES
        already_offline = device.status == DeviceStatus.OFFLINE
        if reached_threshold and not already_offline:
            device.status = DeviceStatus.OFFLINE.value
            record_event(session, device_id=device_id, kind=DeviceEventKind.OFFLINE, detail=device.status_detail)
            logger.warning(
                "Device %s is offline after %d consecutive failed reads",
                device.name,
                device.consecutive_failures,
            )


def record_no_driver(device_id: int, model: str) -> None:
    """Record that this build cannot drive *device_id*'s model.

    Not a failure and not a strike: nobody asked the meter anything, so it never
    reaches Offline however long it sits there. The detail exists so an operator
    who resumes a parked pre-M3 row can see *why* nothing happens instead of
    staring at a permanent Unknown.

    ``status_checked_at`` is cleared for the same reason Resume clears it: a
    stale check time presented as current would report a fact we do not have.

    Args:
        device_id: The device that cannot be read.
        model: Its model identifier, named in the detail.
    """
    with session_scope() as session:
        device = session.get(Device, device_id)
        if device is None:
            logger.info("Device %s vanished before its missing driver could be recorded", device_id)
            return

        device.status = DeviceStatus.UNKNOWN.value
        device.status_detail = f"Model {model!r} has no driver in this build — press Update to re-identify this device."
        device.status_checked_at = None
        device.consecutive_failures = 0
