"""The Poller — one worker thread per device, one lock per Transport Endpoint.

CONTEXT.md defines it: *"The background thread pool that reads meters on a fixed
cadence and writes Interval Readings. One worker per device, one lock per
Transport Endpoint."*

Two decisions carry real weight:

**The lock keys on the Transport Endpoint, not the device.** v1 locked on
``device_id``, which is accidentally correct for TCP (one meter = one socket) and
wrong the moment several devices share a line. Keying on the endpoint
(``host:port`` now, a COM port name once serial lands) makes devices on one line
queue behind one lock — see REMAKE-PLAN §3.2, which calls the v1 behaviour a
latent bug that only survived because sites had one meter per port.

**The Poller only runs while the license is valid.** SPEC §3.9: in Limited Mode
"polling หยุด · process ไม่ตาย". It subscribes to the LicenseService rather than
checking a flag it captured at startup (ADR 0001), so activation starts it
immediately and a lapsed lease stops it — both without a restart.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from sqlalchemy import select

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.base import InstantaneousReading, MeterDriver
from arichds.acquisition.drivers.factory import create_driver
from arichds.constants import (
    INTERVAL_LABEL_INSTANTANEOUS,
    POLL_INTERVAL_SEC,
    POLLER_STOP_JOIN_TIMEOUT_SEC,
)
from arichds.db.models import Device, IntervalReading
from arichds.db.session import session_scope
from arichds.licensing.service import LicenseState

logger = logging.getLogger(__name__)


class EndpointLocks:
    """Hands out one lock per Transport Endpoint, created on demand.

    Thread-safe: the registry itself is guarded, so two workers racing to poll
    the first two devices on one line still end up sharing a single lock.
    """

    def __init__(self) -> None:
        self._registry: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, endpoint: str) -> threading.Lock:
        """Return the lock for *endpoint*, creating it on first use."""
        with self._guard:
            lock = self._registry.get(endpoint)
            if lock is None:
                lock = threading.Lock()
                self._registry[endpoint] = lock
            return lock


def build_driver(device: Device) -> MeterDriver:
    """Construct the driver for *device* from its stored transport.

    Args:
        device: The configured device.

    Returns:
        An unconnected driver.

    Raises:
        ValueError: If the model is unknown or the transport is unusable.
    """
    transport = device.transport or {}
    host = transport.get("host")
    port = transport.get("port")
    if not host or not port:
        raise ValueError(f"Device {device.name!r} has no usable transport: {transport!r}")
    conn = ConnectionParams.net(str(host), int(port))
    return create_driver(device.model, conn, password=device.password or "")


def store_reading(device_id: int, reading: InstantaneousReading) -> int:
    """Persist one Interval Reading and return its row id.

    The driver already normalized the values (UTC + kWh); this function must not
    convert anything, or the contract would live in two places.

    Args:
        device_id: Owning device.
        reading: The normalized sample.

    Returns:
        The new row's primary key.
    """
    with session_scope() as session:
        row = IntervalReading(
            device_id=device_id,
            read_at=reading.read_at,
            source=reading.source,
            interval=INTERVAL_LABEL_INSTANTANEOUS,
            **reading.as_columns(),
        )
        session.add(row)
        session.flush()
        return row.id


def poll_once(device: Device, locks: EndpointLocks, shutdown: threading.Event | None = None) -> int | None:
    """Run one poll tick for *device*: connect, read, store, disconnect.

    Holds the Transport Endpoint lock for the whole exchange so devices sharing
    a line never interleave frames.

    Args:
        device: The device to read.
        locks: The endpoint lock registry.
        shutdown: Optional shutdown event handed to the driver so a connect
            retry aborts promptly.

    Returns:
        The stored row id, or ``None`` if the tick failed (already logged — a
        failed read is normal operational noise, never a crash).
    """
    try:
        driver = build_driver(device)
    except ValueError:
        logger.exception("Cannot build a driver for device %s", device.name)
        return None

    if shutdown is not None and hasattr(driver, "set_shutdown_event"):
        driver.set_shutdown_event(shutdown)

    with locks.get(driver.endpoint):
        try:
            driver.connect()
            reading = driver.read_instantaneous()
        except Exception:  # noqa: BLE001 — one unreachable meter must not stop the rest.
            logger.warning("Poll failed for %s at %s", device.name, driver.endpoint, exc_info=True)
            return None
        finally:
            driver.disconnect()

    row_id = store_reading(device.id, reading)
    logger.info(
        "Stored reading for %s (%s) at %s — V=%s/%s/%s Hz=%s kWh=%s",
        device.name,
        driver.endpoint,
        reading.read_at.isoformat(),
        reading.volt_l1,
        reading.volt_l2,
        reading.volt_l3,
        reading.freq,
        reading.import_active_kwh,
    )
    return row_id


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
        poll_fn: Callable[[Device, EndpointLocks, threading.Event], int | None] | None = None,
    ) -> None:
        """Initialise the Poller.

        Args:
            interval_sec: Seconds between ticks for each device. The first tick
                of every worker runs immediately — a monitor page should show a
                value now, not in a minute.
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
        """
        self._interval_sec = interval_sec
        self._enabled = enabled
        self._stop_timeout = stop_timeout
        self._poll_fn = poll_fn or poll_once
        self._locks = EndpointLocks()
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
        """Snapshot the enabled devices.

        Returns detached copies of the fields the workers need, so a worker
        never holds a Session across a 60-second sleep.
        """
        with session_scope() as session:
            devices = list(session.scalars(select(Device).where(Device.enabled.is_(True))))
            for device in devices:
                session.expunge(device)
            return devices

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
        duplicate Interval Readings, doubled meter load, and a thread budget
        that quietly drifts past SPEC §4's "2 + n".
        """
        logger.info("Poller worker for %s started (every %ss)", device.name, self._interval_sec)
        while not shutdown.is_set():
            try:
                self._poll_fn(device, self._locks, shutdown)
            except Exception:  # noqa: BLE001 — a worker must never die on one bad tick.
                logger.exception("Unhandled error polling %s", device.name)
            # Event.wait doubles as the sleep and the shutdown check, so stopping
            # never waits out a full interval.
            if shutdown.wait(self._interval_sec):
                break
        logger.info("Poller worker for %s stopped", device.name)

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
