"""Probe — read a meter's identity before anything is written (M3-1).

CONTEXT.md: *"Talking to a meter to read its identity before committing
anything. Creating or updating a device probes first: no serial, no row. A probe
is not a reading — it writes no Interval Reading."*

ADR 0005 is why this module exists at all, and it decides the two hard parts:

* A probe is a **Manual Read**, so it takes the Transport Endpoint lock ahead of
  any background tick (ADR 0006). Having won the lock, a failure is always about
  the meter and never about queueing — so the message shown to an operator is
  never "busy, try again".
* A failure must **name its cause**, because the operator's next action differs
  completely between a rejected password, a slow meter and a wrong address.
  :class:`ProbeFailure` is that vocabulary, ported from v1's error contract
  (``connection_manager.py``: E1 refused, E2 timeout, E4/E5 DLMS auth, E7 DNS).

One attempt, no retry loop:
:meth:`~arichds.acquisition.drivers._dlms_tcp.TcpDlmsDriver.connect` already
carries a bounded association retry, and a person is waiting on this call.
"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass
from enum import StrEnum

from gurux_dlms import GXDLMSException

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.base import MeterConnectionError
from arichds.acquisition.drivers.factory import create_driver
from arichds.acquisition.locks import EndpointLocks, endpoint_locks
from arichds.constants import MANUAL_READ_LOCK_TIMEOUT_SEC

logger = logging.getLogger(__name__)


class ProbeFailure(StrEnum):
    """Why a probe did not produce an identity.

    Four values, not one, because each implies a different next action: fix the
    password, wait or shorten the line, fix the address, or call the meter
    vendor.
    """

    AUTH_FAILED = "AUTH_FAILED"  # the meter rejected the credentials
    TIMEOUT = "TIMEOUT"  # it answered too slowly or not at all
    UNREACHABLE = "UNREACHABLE"  # no route / refused / bad host
    NO_SERIAL = "NO_SERIAL"  # connected, but reported no identity


class ProbeError(Exception):
    """A probe that failed, carrying an operator-facing sentence and a reason.

    ``str(exc)`` is shown to a person, so it names the endpoint and what went
    wrong and **never** contains the password.

    Attributes:
        reason: Which :class:`ProbeFailure` this was.
    """

    def __init__(self, reason: ProbeFailure, message: str) -> None:
        """Initialise the error.

        Args:
            reason: The classified cause.
            message: The operator-facing sentence.
        """
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ProbeResult:
    """What a successful probe learned.

    Attributes:
        meter_serial: The Meter Serial, trimmed, exactly as the meter reported.
        latency_ms: How long the probe took, including any wait for the
            Transport Endpoint. Optional in the type so a driver-reported
            latency can replace it later; :func:`probe_meter` always sets it.
    """

    meter_serial: str
    latency_ms: int | None


def _classify(exc: Exception, endpoint: str) -> ProbeError:
    """Translate a driver exception into a :class:`ProbeError`.

    The specific classes come before ``OSError`` because
    ``ConnectionRefusedError`` and friends are all subclasses of it, and
    ``TimeoutError`` is ``socket.timeout``.

    Args:
        exc: What the driver raised.
        endpoint: The Transport Endpoint, for the message.

    Returns:
        The classified error, ready to raise.
    """
    if isinstance(exc, GXDLMSException):
        # v1's E4/E5 — a rejected association, including HLS access denied.
        return ProbeError(
            ProbeFailure.AUTH_FAILED,
            f"The meter at {endpoint} rejected the credentials ({exc}).",
        )
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return ProbeError(
            ProbeFailure.TIMEOUT,
            f"The meter at {endpoint} did not answer in time.",
        )
    if isinstance(exc, MeterConnectionError):
        return ProbeError(
            ProbeFailure.UNREACHABLE,
            f"Could not open a connection to {endpoint} ({exc}).",
        )
    if isinstance(exc, (socket.gaierror, OSError)):
        # ConnectionRefused/Reset/Aborted are OSError subclasses and land here.
        return ProbeError(
            ProbeFailure.UNREACHABLE,
            f"Could not reach the meter at {endpoint} ({type(exc).__name__}).",
        )

    # Anything else is a bug or a driver surprise. It still has to answer the
    # operator's question ("can this machine reach that meter?"), so it maps to
    # UNREACHABLE — but with a stack trace in the log, because unlike the four
    # classified cases nobody has seen this one before.
    logger.warning("Unexpected error probing %s", endpoint, exc_info=True)
    return ProbeError(
        ProbeFailure.UNREACHABLE,
        f"Could not reach the meter at {endpoint} ({type(exc).__name__}).",
    )


def probe_meter(
    *,
    model: str,
    host: str,
    port: int,
    password: str,
    locks: EndpointLocks | None = None,
    lock_timeout_sec: float = MANUAL_READ_LOCK_TIMEOUT_SEC,
) -> ProbeResult:
    """Connect to a meter, read its Meter Serial, disconnect.

    Writes nothing: a Probe is not a reading (CONTEXT.md). Takes the Transport
    Endpoint lock as a **Manual Read**, so it goes ahead of any background tick
    on the same line and an in-flight tick is waited out rather than interrupted
    (ADR 0006).

    **The wait for the endpoint is bounded.** This runs inside an HTTP handler,
    and a background tick holds the endpoint across a connect plus every
    register read — on a dying meter that is minutes. Waiting forever would
    leave ``POST /api/devices`` answering nothing at all, which is the opposite
    of ADR 0005's "the UI must say what is happening rather than spin". Giving
    up reports :attr:`ProbeFailure.TIMEOUT`, not a fifth reason: from the
    operator's side "the meter did not answer in time" is the same next action
    either way.

    Args:
        model: Model identifier, case-insensitive.
        host: TCP host of the Transport Endpoint.
        port: TCP port of the Transport Endpoint.
        password: DLMS authentication password. Never logged, never in the
            error message.
        locks: Lock registry. Defaults to the process-wide one, which is the
            registry the Poller uses.
        lock_timeout_sec: How long to wait for the Transport Endpoint before
            giving up. A parameter so tests can drive it without waiting out
            the real two minutes.

    Returns:
        The meter's identity.

    Raises:
        ValueError: If *model* has no registered driver — raised before any
            connection is attempted, because that is a form error, not a meter
            failure.
        ProbeError: If the endpoint stayed busy, or the meter could not be
            reached, refused the credentials, or reported no identity.
    """
    conn = ConnectionParams.net(host, port)
    driver = create_driver(model, conn, password=password)
    registry = endpoint_locks() if locks is None else locks

    started = time.monotonic()
    try:
        with registry.get(driver.endpoint).manual(timeout=lock_timeout_sec):
            try:
                driver.connect()
                serial = driver.read_meter_serial()
            except Exception as exc:  # noqa: BLE001 — every failure becomes a named reason.
                raise _classify(exc, driver.endpoint) from exc
            finally:
                driver.disconnect()
    except TimeoutError as exc:
        # Only ``manual()`` can raise this here: a TimeoutError from the meter
        # itself is already converted to a ProbeError by the handler above.
        #
        # The message must not say "busy, try again" — ADR 0006 is explicit that
        # having won (or given up on) the lock, the operator is never told to
        # retry. It names the endpoint and reports the meter as unresponsive,
        # which is what is actually true after a two-minute wait.
        raise ProbeError(
            ProbeFailure.TIMEOUT,
            f"The line to {driver.endpoint} was still busy after {lock_timeout_sec:g}s — the meter is not answering.",
        ) from exc

    if serial is None:
        raise ProbeError(
            ProbeFailure.NO_SERIAL,
            f"The meter at {driver.endpoint} answered but reported no serial number.",
        )

    # Measured here rather than read off the driver: this is how long the
    # *probe* took, waiting for the endpoint included, which is the number that
    # answers "why did adding a meter feel slow?".
    latency_ms = int((time.monotonic() - started) * 1000)
    logger.info("Probed %s at %s — serial %s", model, driver.endpoint, serial)
    return ProbeResult(meter_serial=serial, latency_ms=latency_ms)
