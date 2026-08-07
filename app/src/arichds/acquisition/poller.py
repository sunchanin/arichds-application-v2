"""The Poller — one worker thread per device, one lock per Transport Endpoint.

CONTEXT.md defines it: *"The background thread pool that reads every meter on a
fixed cadence to prove it still answers. One worker per device, one lock per
Transport Endpoint."*

**The tick proves liveness, not data** (ADR 0007). It reads one register — the
Meter Serial, the same driver seam the Probe uses (ADR 0005) — and throws the
answer away. Merely connecting would not do: a meter that accepts an association
but cannot serve a register would report Online while being useless. Nothing
instantaneous is persisted anywhere, and no value the tick read ever reaches a
log line, an API response or a cache; what issue #5 needs from a tick is its
**outcome**, not its payload.

Two more decisions carry real weight:

**The lock keys on the Transport Endpoint, not the device.** v1 locked on
``device_id``, which is accidentally correct for TCP (one meter = one socket) and
wrong the moment several devices share a line. Keying on the endpoint
(``host:port`` for TCP, the bare COM port name for serial — issue #9) makes devices on one line
queue behind one lock — see REMAKE-PLAN §3.2, which calls the v1 behaviour a
latent bug that only survived because sites had one meter per port. The registry
itself lives in :mod:`arichds.acquisition.locks`, process-wide, because Manual
Reads in the API take the very same locks (ADR 0006).

**The Poller only runs while the license is valid.** SPEC §3.9: in Limited Mode
"polling หยุด · process ไม่ตาย". It subscribes to the LicenseService rather than
checking a flag it captured at startup (ADR 0001), so activation starts it
immediately and a lapsed lease stops it — both without a restart.

**A tick's outcome is also the device's status** (ADR 0004), which is why there
is no health-check job anywhere in v2: this connection has already answered the
question a connectivity probe would ask, more recently and more thoroughly. The
mapping lives in :meth:`Poller._record` and the rules behind it in
:mod:`arichds.acquisition.status` — nothing in this file decides what "offline"
means.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from enum import StrEnum

from sqlalchemy import select

from arichds.acquisition.connection_params import connection_params_from_transport
from arichds.acquisition.drivers.base import MeterDriver
from arichds.acquisition.drivers.factory import create_driver, supported_models
from arichds.acquisition.locks import EndpointLocks, endpoint_locks
from arichds.acquisition.status import record_failure, record_no_driver, record_success
from arichds.constants import POLL_INTERVAL_SEC, POLLER_STOP_JOIN_TIMEOUT_SEC
from arichds.db.models import Device
from arichds.db.session import session_scope
from arichds.licensing.service import LicenseState

logger = logging.getLogger(__name__)


class TickOutcome(StrEnum):
    """What one poll tick did.

    ``OK`` means the meter answered a real register read — nothing was stored,
    because a tick stores nothing (ADR 0007). It was ``STORED`` until issue #8
    made that a lie.

    ``SKIPPED`` is not ``FAILED`` and that distinction is the point (ADR 0006):
    a tick that never ran because a Manual Read held the endpoint must not count
    toward the 3-consecutive-failures rule that flips a device Offline. If both
    came back as "nothing happened", pressing *Read now* would become a way to
    mark your own meter Offline.
    """

    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


def build_driver(device: Device) -> MeterDriver:
    """Construct the driver for *device* from its stored transport.

    Goes through :func:`~arichds.acquisition.connection_params.connection_params_from_transport`
    — the single transport-to-:class:`ConnectionParams` mapping, shared with
    every Manual Read path in the API (issue #9). Two implementations of this
    mapping is how a background tick and a Manual Read came to compute
    different lock keys for a serial device; one function is the fix.

    Args:
        device: The configured device.

    Returns:
        An unconnected driver.

    Raises:
        ValueError: If the model is unknown or the transport is unusable.
    """
    transport = device.transport or {}
    try:
        conn = connection_params_from_transport(transport)
    except ValueError as exc:
        raise ValueError(f"Device {device.name!r} has no usable transport: {transport!r}") from exc
    return create_driver(device.model, conn, password=device.password or "")


def poll_once(device: Device, locks: EndpointLocks, shutdown: threading.Event | None = None) -> TickOutcome:
    """Run one poll tick for *device*: connect, read the identity, disconnect.

    Takes the Transport Endpoint lock on the **background** path for the whole
    exchange, so devices sharing a line never interleave frames — and so a tick
    that arrives while a Manual Read holds (or is waiting for) the endpoint is
    skipped rather than queued (ADR 0006).

    The serial it reads is **discarded** (ADR 0007). It is read to prove the
    meter answers a real register — one register, not eight — and re-identifying
    the device off it is deliberately not done here: a serial that no longer
    matches is Update's business (ADR 0005), not a background thread's.

    Args:
        device: The device to read.
        locks: The endpoint lock registry.
        shutdown: Optional shutdown event handed to the driver so a connect
            retry aborts promptly.

    Returns:
        The tick outcome. A failed read is normal operational noise, never a
        crash, and is already logged by the time this returns.
    """
    try:
        driver = build_driver(device)
    except ValueError as exc:
        # A backstop, not the main guard: the Poller filters unusable models out
        # before it creates a worker, so reaching here means someone called
        # poll_once directly. WARNING, not exception() — this is a
        # configuration problem, not a crash, and it must not shout every tick.
        logger.warning("Cannot build a driver for device %s: %s", device.name, exc)
        return TickOutcome.FAILED

    if shutdown is not None and hasattr(driver, "set_shutdown_event"):
        driver.set_shutdown_event(shutdown)

    with locks.get(driver.endpoint).background() as acquired:
        if not acquired:
            logger.info("Skipping tick for %s — a Manual Read holds %s", device.name, driver.endpoint)
            return TickOutcome.SKIPPED
        try:
            driver.connect()
            serial = driver.read_meter_serial()
        except Exception:  # noqa: BLE001 — one unreachable meter must not stop the rest.
            logger.warning("Poll failed for %s at %s", device.name, driver.endpoint, exc_info=True)
            return TickOutcome.FAILED
        finally:
            driver.disconnect()

    if serial is None:
        # The association succeeded and the register came back empty. That
        # proves the meter is listening, not that it can serve a read — the
        # exact state ADR 0007 refuses to report as Online. ``probe_meter``
        # classifies the same answer as ``ProbeFailure.NO_SERIAL``.
        logger.warning("Poll failed for %s at %s — the meter reported no serial", device.name, driver.endpoint)
        return TickOutcome.FAILED

    # One line, no payload: the serial is discarded here and never logged
    # (ADR 0007 — the tick proves liveness, and a Meter Serial is identity, not
    # liveness).
    logger.info("Tick OK for %s (%s)", device.name, driver.endpoint)
    return TickOutcome.OK


class Poller:
    """Runs one worker thread per enabled device on a fixed cadence.

    Start and stop are idempotent, so the license listener can call them freely.
    """

    def __init__(
        self,
        *,
        interval_sec: float = POLL_INTERVAL_SEC,
        enabled: bool = True,
        stop_timeout: float = POLLER_STOP_JOIN_TIMEOUT_SEC,
        poll_fn: Callable[[Device, EndpointLocks, threading.Event], TickOutcome] | None = None,
        locks: EndpointLocks | None = None,
    ) -> None:
        """Initialise the Poller.

        Args:
            interval_sec: Seconds between ticks for each device. The first tick
                of every worker runs immediately — a device that has just been
                added should report its status now, not in a minute.
            enabled: Master switch (``ARICHDS_POLL_ENABLED``). When False,
                :meth:`start` is a no-op, so a valid license does not bring
                background threads up. Used by tests and by dev runs that want
                the API without touching meters.
            stop_timeout: How long :meth:`stop` waits for each worker to finish
                its current tick. A worker mid-read can legitimately outlast
                this (a DLMS read can take the full 60 s timeout), which is
                exactly why the shutdown event is bound per worker.
            poll_fn: Override for the per-tick work (tests). Defaults to
                :func:`poll_once`.
            locks: The Transport Endpoint lock registry. Defaults to the
                process-wide one, which is what makes a Manual Read in the API
                contend with a background tick for the same endpoint — including
                across a :meth:`restart` (ADR 0006). Tests pass their own.
        """
        self._interval_sec = interval_sec
        self._enabled = enabled
        self._stop_timeout = stop_timeout
        self._poll_fn = poll_fn or poll_once
        self._locks = locks if locks is not None else endpoint_locks()
        self._shutdown = threading.Event()
        self._threads: list[threading.Thread] = []
        self._guard = threading.Lock()
        self._running = False

    @property
    def running(self) -> bool:
        """True while worker threads are alive."""
        return self._running

    @property
    def enabled(self) -> bool:
        """Whether the master switch allows this Poller to run at all."""
        return self._enabled

    def _enabled_devices(self) -> list[Device]:
        """Snapshot the enabled devices whose model this build can actually drive.

        Returns detached copies of the fields the workers need, so a worker
        never holds a Session across a 60-second sleep.

        A row whose model has no registered driver — a pre-M3 ``sim`` row that
        somebody re-enabled by hand, say — gets **no worker at all**. Filtering
        here rather than inside ``poll_once`` means the unusable device costs no
        thread and produces exactly one log line per Poller start, instead of a
        warning every 60 seconds forever.
        """
        drivable = set(supported_models())
        with session_scope() as session:
            devices = list(session.scalars(select(Device).where(Device.enabled.is_(True))))
            for device in devices:
                session.expunge(device)

        usable: list[Device] = []
        for device in devices:
            if device.model.lower() in drivable:
                usable.append(device)
            else:
                logger.warning(
                    "Device %s is enabled but its model %r has no driver in this build — not polling it",
                    device.name,
                    device.model,
                )
                # Say so on the device too, not just in the log. Without this an
                # operator who resumes a parked pre-M3 row watches a permanent
                # Unknown with no explanation anywhere they can see.
                record_no_driver(device.id, device.model)
        return usable

    def start(self) -> None:
        """Start one worker per enabled device.

        No-op if already running, or if the master switch is off.
        """
        with self._guard:
            if self._running:
                return
            if not self._enabled:
                logger.info("Poller disabled by configuration — not starting workers")
                return
            devices = self._enabled_devices()
            # A fresh event per run. It is passed to each worker BELOW rather
            # than re-read from the attribute, so a worker abandoned by a
            # previous stop() keeps watching the event that was set for it.
            self._shutdown = threading.Event()
            shutdown = self._shutdown
            self._threads = []
            for device in devices:
                thread = threading.Thread(
                    target=self._worker,
                    args=(device, shutdown),
                    name=f"poller-{device.name}",
                    daemon=True,
                )
                thread.start()
                self._threads.append(thread)
            self._running = True
            logger.info("Poller started with %d device worker(s)", len(self._threads))

    def stop(self, timeout: float | None = None) -> None:
        """Signal every worker to stop and wait for them. No-op if stopped.

        A worker parked in a slow meter read can outlast the join. That is not
        an error — its shutdown event is already set, so it exits as soon as the
        read returns — but it must not be silent, or a genuinely stuck worker
        looks identical to a slow one.

        Args:
            timeout: Per-worker join timeout. Defaults to the configured
                ``stop_timeout``.
        """
        join_timeout = self._stop_timeout if timeout is None else timeout
        with self._guard:
            if not self._running:
                return
            self._shutdown.set()
            threads = list(self._threads)
            self._threads = []
            self._running = False

        lingering = 0
        for thread in threads:
            thread.join(timeout=join_timeout)
            if thread.is_alive():
                lingering += 1
                logger.warning(
                    "Poller worker %s did not stop within %.1fs — it is finishing a read and "
                    "will exit on its own (its shutdown event is set)",
                    thread.name,
                    join_timeout,
                )

        if lingering:
            logger.info("Poller stopped (%d worker(s) still winding down)", lingering)
        else:
            logger.info("Poller stopped")

    def restart(self) -> None:
        """Stop and start again — how a new device joins the rotation."""
        self.stop()
        self.start()

    def _worker(self, device: Device, shutdown: threading.Event) -> None:
        """Poll one device until *shutdown* is signalled.

        ``shutdown`` is the event bound when this thread was created, NOT
        ``self._shutdown``. That distinction is the whole fix: ``stop()`` sets
        event A and gives up waiting after ``stop_timeout``, then ``start()``
        rebinds the attribute to a fresh unset event B. A worker still inside a
        slow meter read that later re-read the attribute would see B, never
        learn it was retired, and poll on forever beside its replacement —
        doubled meter load, a device status written twice a tick by two threads
        racing each other, and a thread budget that quietly drifts past SPEC
        §4's "2 + n".
        """
        logger.info("Poller worker for %s started (every %ss)", device.name, self._interval_sec)
        while not shutdown.is_set():
            try:
                outcome = self._poll_fn(device, self._locks, shutdown)
                self._record(device, outcome)
            except Exception:  # noqa: BLE001 — a worker must never die on one bad tick.
                logger.exception("Unhandled error polling %s", device.name)
                # A driver that raises must still be able to reach Offline: from
                # the operator's side "it threw" and "it timed out" are the same
                # fact — this machine could not read that meter.
                #
                # Guarded because this call is in the handler of last resort: a
                # database error here would otherwise escape the loop and kill
                # the worker, and "a worker must never die on one bad tick" is
                # the whole reason this except exists.
                try:
                    record_failure(device.id)
                except Exception:  # noqa: BLE001 — see above.
                    logger.exception("Could not record the failed tick for %s", device.name)
            # Event.wait doubles as the sleep and the shutdown check, so stopping
            # never waits out a full interval.
            if shutdown.wait(self._interval_sec):
                break
        logger.info("Poller worker for %s stopped", device.name)

    def _record(self, device: Device, outcome: TickOutcome) -> None:
        """Turn one tick outcome into device status (ADR 0004).

        Called at the ``poll_fn`` seam rather than from inside :func:`poll_once`
        for two reasons. ``poll_fn`` is the injection point the tests use, so
        recording here lets a test drive the whole state machine with fabricated
        outcomes and no threads-versus-meter timing. And it keeps
        :mod:`arichds.acquisition.status` free of any import of this module, so
        the outcome vocabulary could be renamed without the state machine
        noticing — which is exactly what issue #8 then did, turning ``STORED``
        into ``OK`` here and touching nothing in ``status.py``.

        Args:
            device: The device that was (or was not) read.
            outcome: What the tick did.
        """
        if outcome is TickOutcome.OK:
            record_success(device.id)
        elif outcome is TickOutcome.FAILED:
            record_failure(device.id)
        # SKIPPED is a total no-op — not a strike, not a reset, not even a fresh
        # `status_checked_at`. A tick skipped because a Manual Read held the
        # endpoint (ADR 0006) checked nothing, so it has nothing to report; if it
        # counted as a failure, pressing Read now three times in a row would be a
        # way to mark your own meter Offline.

    # ── License integration (ADR 0001) ───────────────────────────────────────

    def on_license_state(self, state: LicenseState) -> None:
        """Start or stop in response to a license state change.

        Registered with :class:`~arichds.licensing.service.LicenseService`, which
        is what makes activation take effect immediately: the moment a valid
        code is pasted, this fires and the Poller comes up. No restart.
        """
        if state.valid:
            self.start()
        else:
            self.stop()
