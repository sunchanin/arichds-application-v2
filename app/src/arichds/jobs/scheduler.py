"""The scheduler — one thread, every periodic job, one registry (M5a-2, issue #16).

SPEC §4: *"scheduler thread เดียวรันทุก periodic job จาก registry
`[(name, interval, fn)]`"*. One thread, not one per job: v1 grew seven
`_DaemonScheduler` subclasses — `battery_reader`, `billing_auto_reader`,
`billing_backfill_scheduler`, `load_profile_scheduler`,
`modbus_billing_cut_scheduler`, `retention_scheduler` and `LpCsvExporter` — one
per *module* rather than for any concurrency reason (REMAKE-PLAN §3.2). Nothing
here is per-module: a job is a name, an interval and a callable.

Jobs run **sequentially**, in registry order, on the one thread. That is a
choice, not a limitation: the Transport Endpoint lock already serialises
everything sharing a line, so concurrency between jobs would buy contention
rather than throughput.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from arichds.acquisition.battery import battery_cycle
from arichds.acquisition.billing import billing_cycle
from arichds.acquisition.load_profile import load_profile_cycle
from arichds.constants import (
    BACKUP_INTERVAL_SEC,
    BATTERY_INTERVAL_SEC,
    BILLING_INTERVAL_SEC,
    JOB_BACKUP,
    JOB_BATTERY,
    JOB_BILLING,
    JOB_LOAD_PROFILE,
    JOB_RETENTION,
    LOAD_PROFILE_INTERVAL_SEC,
    RETENTION_INTERVAL_SEC,
    SCHEDULER_MIN_SLEEP_SEC,
    SCHEDULER_STOP_JOIN_TIMEOUT_SEC,
)
from arichds.db.backup import backup_database
from arichds.db.retention import purge_expired
from arichds.licensing.service import LicenseState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Job:
    """One periodic job: what to call, what to call it, and how often.

    Attributes:
        name: What this job is called in logs. The only thing that identifies it.
        interval_sec: Seconds between runs, measured from when the previous run
            **finished** (see :meth:`Scheduler._run`).
        fn: The work. Takes nothing and returns nothing — everything it needs it
            resolves itself, so the registry entry stays one line.
    """

    name: str
    interval_sec: float
    fn: Callable[[], None]


class Scheduler:
    """Runs every registered job on its own interval, on one daemon thread.

    Start and stop are idempotent, so the license listener can call them freely.
    """

    def __init__(
        self,
        *,
        jobs: list[Job] | None = None,
        enabled: bool = True,
        stop_timeout: float = SCHEDULER_STOP_JOIN_TIMEOUT_SEC,
    ) -> None:
        """Initialise the Scheduler.

        Args:
            jobs: The registry to run. Defaults to :func:`default_jobs`. Tests
                pass their own — **the registry is the only seam they need**,
                which is the same thing that makes adding a real job one entry.
            enabled: Master switch (``ARICHDS_POLL_ENABLED``). When False,
                :meth:`start` is a no-op, so a valid license does not bring a
                background thread up. Shared with the Poller: since M5c it gates
                more than meter reads — the daily purge and the daily backup
                touch no meter and stop with it too. Still one switch by decision
                (issue #19, see :class:`arichds.config.Settings`): it is a
                dev/test switch, and a second one would be missed by exactly the
                fixtures that already set this.
            stop_timeout: How long :meth:`stop` waits for the thread to finish
                the job it is inside. A load-profile cycle can legitimately
                outlast it, which is why the shutdown event is bound per run.
        """
        self._jobs = list(default_jobs() if jobs is None else jobs)
        self._enabled = enabled
        self._stop_timeout = stop_timeout
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self._guard = threading.Lock()
        self._running = False

    @property
    def running(self) -> bool:
        """True while the job thread is alive."""
        return self._running

    @property
    def enabled(self) -> bool:
        """Whether the master switch allows this Scheduler to run at all."""
        return self._enabled

    def start(self) -> None:
        """Start the job thread.

        No-op if already running, or if the master switch is off.
        """
        with self._guard:
            if self._running:
                return
            if not self._enabled:
                logger.info("Scheduler disabled by configuration — not starting the job thread")
                return
            # A fresh event per run, passed to the thread BELOW rather than
            # re-read from the attribute: a thread abandoned by a previous stop()
            # must keep watching the event that was set for it, or it would see
            # the next start()'s unset event and run on forever beside its
            # replacement. Same rule as Poller._worker, one thread instead of n.
            self._shutdown = threading.Event()
            shutdown = self._shutdown
            self._thread = threading.Thread(
                target=self._run,
                args=(shutdown,),
                name="arichds-scheduler",
                daemon=True,
            )
            self._thread.start()
            self._running = True
            logger.info("Scheduler started with %d job(s): %s", len(self._jobs), ", ".join(j.name for j in self._jobs))

    def stop(self, timeout: float | None = None) -> None:
        """Signal the job thread to stop and wait for it. No-op if stopped.

        A thread parked in a slow meter read can outlast the join. That is not an
        error — its shutdown event is already set, so it exits as soon as the read
        returns — but it must not be silent, or a genuinely stuck job looks
        identical to a slow one.

        Args:
            timeout: Join timeout. Defaults to the configured ``stop_timeout``.
        """
        join_timeout = self._stop_timeout if timeout is None else timeout
        with self._guard:
            if not self._running:
                return
            self._shutdown.set()
            thread = self._thread
            self._thread = None
            self._running = False

        # Joined outside the guard: a job that outlasts the join must not hold
        # start() out for the length of the timeout.
        if thread is not None:
            thread.join(timeout=join_timeout)
            if thread.is_alive():
                logger.warning(
                    "Scheduler thread %s did not stop within %.1fs — it is finishing a job and "
                    "will exit on its own (its shutdown event is set)",
                    thread.name,
                    join_timeout,
                )
                return
        logger.info("Scheduler stopped")

    def _run(self, shutdown: threading.Event) -> None:
        """Run every due job, then sleep until the next one is due.

        ``shutdown`` is the event bound when this thread was created, NOT
        ``self._shutdown`` — see :meth:`start`.

        Two timing rules, both deliberate:

        * **Every job runs immediately on the first pass** (D10), like the
          Poller's first tick. A machine that was just activated should start
          collecting now, not in fifteen minutes — which is also what makes
          "Interval Readings appear with nobody pressing anything" observable.
        * **The next due time is measured from when the job finished** (D11), so
          a job that overruns its interval delays the ones behind it and is never
          queued twice. There are no catch-up runs: for the load-profile job the
          watermark already makes a late cycle read everything it missed, and a
          job that stacks up would be reading the same meter twice at once.
        """
        logger.info("Scheduler thread started")
        # Due immediately: the first pass runs everything.
        due = [time.monotonic()] * len(self._jobs)

        while not shutdown.is_set():
            now = time.monotonic()
            for index, job in enumerate(self._jobs):
                # Checked per job, not just per pass: a job already running is
                # never interrupted, but one that has not started must not begin
                # after shutdown was signalled. Load-bearing since M5c: backup is
                # registered behind a slow load-profile cycle, so this is the
                # difference between stopping and starting a fresh backup of a
                # database the process is closing.
                if shutdown.is_set():
                    break
                if due[index] > now:
                    continue
                try:
                    job.fn()
                except Exception:  # noqa: BLE001 — one bad job must never kill the thread or the jobs behind it.
                    # Logged with its traceback and otherwise ignored: the job is
                    # not dropped from the registry, it simply loses this cycle.
                    # A retention job that throws on a locked file must still run
                    # tomorrow, and the load-profile cycle heals from its
                    # watermark (ADR 0008) with nobody intervening.
                    logger.exception("Job %s failed", job.name)
                due[index] = time.monotonic() + job.interval_sec

            # Event.wait doubles as the sleep and the shutdown check, so stopping
            # never waits out a full interval. With an empty registry there is no
            # next due time and it waits for the shutdown alone.
            delay = max(min(due) - time.monotonic(), SCHEDULER_MIN_SLEEP_SEC) if due else None
            if shutdown.wait(delay):
                break
        logger.info("Scheduler thread stopped")

    # ── License integration (ADR 0001) ───────────────────────────────────────

    def on_license_state(self, state: LicenseState) -> None:
        """Start or stop in response to a license state change.

        Registered with :class:`~arichds.licensing.service.LicenseService`, which
        is what makes activation take effect immediately: the moment a valid code
        is pasted this fires and the jobs come up. No restart. In Limited Mode
        the thread stops — SPEC §3.9's *"polling หยุด · process ไม่ตาย"* covers
        every background meter read, not only the Poller's.

        **Since M5c that stops two jobs that read no meter**: the daily purge and
        the daily backup go quiet in Limited Mode too. Intended rather than
        overlooked — an unlicensed machine collects no new rows, so it has
        nothing to expire and nothing new to back up, and the existing backups
        stay on disk untouched until it is licensed again.
        """
        if state.valid:
            self.start()
        else:
            self.stop()


def default_jobs() -> list[Job]:
    """The registry the product runs.

    **Adding a job is adding one line here**, plus its function in the module
    that owns its domain. M5c's retention and backup landed that way, M6a's
    billing auto-read did too, and M8's sync will — no new thread, no new
    class, no subclass of anything.

    A function returning a fresh list rather than a module-level constant,
    mirroring ``drivers.factory._registry()``: one ``monkeypatch.setattr`` then
    swaps the whole registry, which is why neither has a ``register()`` API for
    anything to half-register through.

    The license recheck SPEC §4 lists is deliberately **not** here: it is served
    by the staleness TTL in :mod:`arichds.licensing.service`, which is M1's lean
    version of the same thing.
    """
    return [
        Job(name=JOB_LOAD_PROFILE, interval_sec=LOAD_PROFILE_INTERVAL_SEC, fn=load_profile_cycle),
        # Billing sits with the other read job, before backup/retention — a
        # read job belongs with the read job (M6a, issue #21).
        Job(name=JOB_BILLING, interval_sec=BILLING_INTERVAL_SEC, fn=billing_cycle),
        # Battery sits with the other read jobs too, before backup/retention
        # (M7-2, issue #29) — hourly, not daily: the day-guard inside
        # battery_cycle() is what keeps this at one meter read per device per
        # day in the common case; the hourly cadence exists only to survive a
        # skipped background tick (see battery.py's module docstring, D1).
        Job(name=JOB_BATTERY, interval_sec=BATTERY_INTERVAL_SEC, fn=battery_cycle),
        # Backup runs BEFORE retention, deliberately (M5c, issue #19): the
        # backup then still contains the rows retention is about to delete, so a
        # retention bug stays recoverable for the seven days of backups that are
        # kept. The cost is a marginally larger backup file, which is the cheaper
        # side of that trade by a wide margin.
        Job(name=JOB_BACKUP, interval_sec=BACKUP_INTERVAL_SEC, fn=backup_database),
        Job(name=JOB_RETENTION, interval_sec=RETENTION_INTERVAL_SEC, fn=purge_expired),
    ]
