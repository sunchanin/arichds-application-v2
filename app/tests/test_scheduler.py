"""The job scheduler and the load-profile cycle (M5a-2, issue #16).

One thread runs every periodic job from a registry of ``(name, interval, fn)``.
The tests drive it through **the registry** — ``Scheduler(jobs=[Job(...)])`` —
because that is the seam the design is about: adding a job later must be one
entry in a list plus a function in its own module, never a new thread and never
a new class. There is deliberately no fake clock; a second time source would be
one only tests ever use, and the Poller has proved for two milestones that a
tiny interval is enough.

The load-profile cycle's tests live here too rather than in
``test_load_profile_job.py``: that module owns issue #15's read path, this one
owns the job wrapped around it.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fakes import fake_meter_state
from sqlalchemy import select

from arichds.acquisition.drivers.base import IntervalReading
from arichds.acquisition.load_profile import (
    LoadProfileReadResult,
    load_profile_cycle,
    read_and_store_load_profile,
)
from arichds.acquisition.locks import endpoint_locks
from arichds.acquisition.status import DeviceStatus
from arichds.config import Settings
from arichds.constants import (
    BACKUP_INTERVAL_SEC,
    LOAD_PROFILE_INTERVAL_SEC,
    MANUAL_READ_LOCK_TIMEOUT_SEC,
    RETENTION_INTERVAL_SEC,
    SOURCE_DLMS,
)
from arichds.db.backup import backup_database
from arichds.db.models import Device, DeviceEvent, LoadProfileReading
from arichds.db.retention import purge_expired
from arichds.db.session import session_scope
from arichds.jobs.scheduler import Job, Scheduler, default_jobs
from arichds.licensing.service import STATE_ACTIVE, STATE_LIMITED, LicenseState


def wait_until(predicate, *, timeout: float = 5.0) -> bool:  # noqa: ANN001
    """Poll *predicate* until it is true or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class TestTheRegistryIsTheOnlyThingAJobNeeds:
    """Adding a job = one entry in a list. No thread, no subclass (REMAKE-PLAN §3)."""

    def test_a_registered_job_runs(self) -> None:
        ran = threading.Event()
        scheduler = Scheduler(jobs=[Job(name="fake", interval_sec=0.02, fn=ran.set)])
        try:
            scheduler.start()
            assert ran.wait(timeout=5), "the registered job never ran"
        finally:
            scheduler.stop()


class TestOneBadJobCostsOnlyItsOwnCycle:
    """The thread survives, the jobs behind it run, and the failure is visible."""

    def test_a_throwing_job_does_not_stop_the_job_behind_it(self, caplog: pytest.LogCaptureFixture) -> None:
        runs: list[str] = []

        def boom() -> None:
            runs.append("boom")
            raise RuntimeError("the job blew up")

        scheduler = Scheduler(
            jobs=[
                Job(name="throws", interval_sec=0.02, fn=boom),
                Job(name="behind_it", interval_sec=0.02, fn=lambda: runs.append("behind_it")),
            ]
        )
        with caplog.at_level(logging.ERROR, logger="arichds.jobs.scheduler"):
            try:
                scheduler.start()
                # Two runs of the *second* job proves the thread kept cycling
                # after the first one threw — one run could be the first pass
                # racing the exception.
                assert wait_until(lambda: runs.count("behind_it") >= 2), f"the thread died on the bad job: {runs}"
            finally:
                scheduler.stop()

        assert runs.count("boom") >= 2, "the throwing job was dropped from the registry instead of retried"
        assert "Job throws failed" in caplog.text
        assert "the job blew up" in caplog.text, "the traceback of the failing job was not logged"


def live_scheduler_threads() -> list[threading.Thread]:
    """Every live scheduler thread in this process.

    SPEC §4 budgets a fixed 2 threads (main + scheduler) plus one Poller worker
    per meter, so counting by name is how "one thread, and it does not outlive
    the app" gets asserted.
    """
    return [t for t in threading.enumerate() if t.is_alive() and t.name == "arichds-scheduler"]


class TestStartAndStopAreIdempotent:
    """The license listener calls both freely, so neither may double up."""

    def test_starting_twice_leaves_one_thread(self) -> None:
        scheduler = Scheduler(jobs=[Job(name="fake", interval_sec=0.02, fn=lambda: None)])
        before = len(live_scheduler_threads())
        try:
            scheduler.start()
            scheduler.start()
            assert len(live_scheduler_threads()) == before + 1, "the second start() smuggled in a second thread"
        finally:
            scheduler.stop()

    def test_a_scheduler_built_with_no_jobs_runs_the_default_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``jobs=None`` means :func:`default_jobs` — the wiring ``main.py`` uses.

        Patching the function wholesale is enough precisely because it is a
        function returning a fresh list rather than a module constant, the same
        property that makes ``drivers.factory._registry`` swappable.
        """
        ran = threading.Event()
        monkeypatch.setattr(
            "arichds.jobs.scheduler.default_jobs",
            lambda: [Job(name="stand_in", interval_sec=0.02, fn=ran.set)],
        )
        scheduler = Scheduler()
        try:
            scheduler.start()
            assert ran.wait(timeout=5), "a Scheduler built with no jobs ran nothing"
        finally:
            scheduler.stop()

    def test_no_thread_outlives_stop(self) -> None:
        scheduler = Scheduler(jobs=[Job(name="fake", interval_sec=0.02, fn=lambda: None)])
        before = len(live_scheduler_threads())
        scheduler.start()
        scheduler.stop()

        assert not scheduler.running
        assert wait_until(lambda: len(live_scheduler_threads()) == before), "a scheduler thread outlived stop()"

    def test_an_empty_registry_does_not_kill_the_thread(self) -> None:
        """There is no next due time to compute. It waits for the shutdown alone.

        Reachable only from a caller passing ``jobs=[]``, but the failure mode is
        an exception on the first pass, which would look identical to a thread
        that started and died silently.
        """
        scheduler = Scheduler(jobs=[])
        try:
            scheduler.start()
            assert len(live_scheduler_threads()) == 1
            # Still alive a moment later: it parked on the event, it did not fall
            # over computing the minimum of nothing.
            time.sleep(0.1)
            assert len(live_scheduler_threads()) == 1
        finally:
            scheduler.stop()
        assert wait_until(lambda: not live_scheduler_threads())

    def test_stopping_twice_is_harmless(self) -> None:
        scheduler = Scheduler(jobs=[Job(name="fake", interval_sec=0.02, fn=lambda: None)])
        scheduler.start()
        scheduler.stop()
        scheduler.stop()
        assert not scheduler.running


class TestAnOverrunningJobDoesNotStackUp:
    """D11 — the next due time is measured from when the job *finished*.

    The alternative (advancing the due time by one interval from the instant it
    was *scheduled* for) looks equivalent and is not: a job slower than its own
    interval falls permanently behind ``now`` and then runs on **every** pass,
    separated only by ``SCHEDULER_MIN_SLEEP_SEC``. For the load-profile cycle
    that means reading every meter on the site back-to-back, forever, holding
    endpoints throughout. This is the rule M6, M7 and M8 all inherit.
    """

    def test_the_gap_between_runs_includes_the_interval(self) -> None:
        interval = 0.1
        duration = 0.2  # deliberately longer than the interval — an overrun
        starts: list[float] = []
        third_run = threading.Event()

        def slow() -> None:
            starts.append(time.monotonic())
            if len(starts) >= 3:
                third_run.set()
            time.sleep(duration)

        scheduler = Scheduler(jobs=[Job(name="overruns", interval_sec=interval, fn=slow)], stop_timeout=1.0)
        scheduler.start()
        try:
            assert third_run.wait(timeout=10), f"the job ran only {len(starts)} time(s)"
        finally:
            scheduler.stop()

        gaps = [later - earlier for earlier, later in zip(starts, starts[1:], strict=False)]
        # Correct: duration + interval = 0.30. Stacked: duration + the 0.01 s
        # sleep floor = 0.21. The bound sits between them with room for jitter.
        assert all(gap >= 0.27 for gap in gaps), (
            f"consecutive runs were {gaps} apart — the interval is not being added after the job finished, "
            f"so an overrunning job is stacking up and running on every pass"
        )


class TestJobsWithDifferentIntervalsCoexist:
    """The registry is heterogeneous from M5c on: 900 s beside two 86,400 s jobs.

    Until issue #19 the registry had exactly one entry, so nothing had ever
    exercised the per-job due time. Two ways to get this wrong both look
    plausible: sleeping until the *latest* due time would stall the frequent job
    behind the daily one, and one shared due time would run the daily job on the
    frequent one's cadence — which for the real registry means a full database
    backup every fifteen minutes.
    """

    def test_a_daily_job_runs_once_while_the_frequent_one_keeps_its_cadence(self) -> None:
        frequent: list[float] = []
        daily: list[float] = []

        scheduler = Scheduler(
            jobs=[
                Job(name="frequent", interval_sec=0.02, fn=lambda: frequent.append(time.monotonic())),
                # 30 s stands in for the real 86,400 s: long enough that a second
                # run inside this test could only come from a scheduling bug.
                Job(name="daily", interval_sec=30.0, fn=lambda: daily.append(time.monotonic())),
            ]
        )
        scheduler.start()
        try:
            assert wait_until(lambda: len(frequent) >= 5), (
                f"the frequent job ran {len(frequent)} time(s) — the thread is sleeping until the daily job is due "
                f"instead of until the *next* job is due"
            )
        finally:
            scheduler.stop()

        assert len(daily) == 1, f"the daily job ran {len(daily)} times — it is following the frequent job's cadence"


class TestStopIsPrompt:
    """Shutdown must not wait out an interval — the real one is 900 s."""

    def test_stop_does_not_wait_out_the_interval(self) -> None:
        ran = threading.Event()
        # 30 s between passes: if stop() waited for the sleep rather than
        # interrupting it, this test would take 30 s instead of milliseconds.
        scheduler = Scheduler(jobs=[Job(name="slow_cadence", interval_sec=30.0, fn=ran.set)])
        scheduler.start()
        try:
            assert ran.wait(timeout=5), "the job never ran"

            started = time.monotonic()
            scheduler.stop()
            elapsed = time.monotonic() - started
        finally:
            # Without this, a failure above leaks a live 30 s-interval thread
            # into the rest of the session and turns one red into several.
            scheduler.stop()

        assert elapsed < 5, f"stop() waited {elapsed:.1f}s — it is sleeping through the interval, not on the event"

    def test_shutdown_does_not_start_the_jobs_behind_the_one_in_flight(self) -> None:
        """A job already running is never interrupted; one not yet started must not begin.

        Load-bearing since M5c registered backup behind the load-profile cycle: a
        shutdown landing mid-pass must not kick off a fresh backup of a database
        the process is closing.
        """
        in_first = threading.Event()
        release = threading.Event()
        second_ran = threading.Event()

        def first() -> None:
            in_first.set()
            release.wait(timeout=10)

        scheduler = Scheduler(
            jobs=[
                Job(name="in_flight", interval_sec=0.02, fn=first),
                Job(name="behind_it", interval_sec=0.02, fn=second_ran.set),
            ],
            stop_timeout=0.1,
        )
        scheduler.start()
        try:
            assert in_first.wait(timeout=5), "the first job never started"
            scheduler.stop()  # signalled while the first job is still parked
            second_ran.clear()  # ignore any pass that completed before the signal
            release.set()

            assert not second_ran.wait(timeout=0.5), "a job started after shutdown was signalled"
        finally:
            release.set()

    def test_stop_returns_and_warns_while_a_job_is_parked(self, caplog: pytest.LogCaptureFixture) -> None:
        """A load-profile cycle can outlast the join. That must be loud, not silent.

        Otherwise a genuinely wedged job looks exactly like a slow one.
        """
        in_job = threading.Event()
        release = threading.Event()

        def parked() -> None:
            in_job.set()
            release.wait(timeout=10)

        # stop_timeout shorter than the job, the way a 60 s meter read makes the
        # join time out in production.
        scheduler = Scheduler(jobs=[Job(name="parked", interval_sec=0.02, fn=parked)], stop_timeout=0.1)
        scheduler.start()
        try:
            assert in_job.wait(timeout=5), "the job never started"
            with caplog.at_level(logging.WARNING, logger="arichds.jobs.scheduler"):
                started = time.monotonic()
                scheduler.stop()
                elapsed = time.monotonic() - started

            assert elapsed < 5, f"stop() blocked {elapsed:.1f}s on a parked job instead of giving up on its timeout"
            assert "did not stop within" in caplog.text
            assert "arichds-scheduler" in caplog.text, "the warning does not name the thread"
        finally:
            release.set()


class TestSchedulerFollowsLicenseState:
    """SPEC §3.9 — jobs stop in Limited Mode and start on activation, no restart (ADR 0001)."""

    def test_a_valid_license_starts_the_jobs(self) -> None:
        scheduler = Scheduler(jobs=[Job(name="fake", interval_sec=0.02, fn=lambda: None)])
        try:
            scheduler.on_license_state(LicenseState(state=STATE_ACTIVE, reason=None))
            assert scheduler.running
        finally:
            scheduler.stop()

    def test_limited_mode_stops_the_jobs(self) -> None:
        scheduler = Scheduler(jobs=[Job(name="fake", interval_sec=0.02, fn=lambda: None)])
        try:
            scheduler.on_license_state(LicenseState(state=STATE_ACTIVE, reason=None))
            scheduler.on_license_state(LicenseState(state=STATE_LIMITED, reason="NO_LICENSE"))
            assert not scheduler.running
        finally:
            scheduler.stop()


class TestSchedulerMasterSwitch:
    """``ARICHDS_POLL_ENABLED=false`` must hold even with a valid license."""

    def test_a_disabled_scheduler_does_not_start(self) -> None:
        scheduler = Scheduler(jobs=[Job(name="fake", interval_sec=0.02, fn=lambda: None)], enabled=False)
        scheduler.start()
        assert not scheduler.running
        assert not live_scheduler_threads()

    def test_a_disabled_scheduler_ignores_a_valid_license(self) -> None:
        scheduler = Scheduler(jobs=[Job(name="fake", interval_sec=0.02, fn=lambda: None)], enabled=False)
        scheduler.on_license_state(LicenseState(state=STATE_ACTIVE, reason=None))
        assert not scheduler.running


class TestTheDefaultRegistry:
    """D12 — three jobs at M5c. M6/M8 add theirs one line at a time."""

    def test_it_holds_the_load_profile_backup_and_retention_jobs(self) -> None:
        jobs = default_jobs()

        # Asserted deliberately so that whoever adds M6's billing auto-read has
        # to come here and update the count on purpose.
        assert len(jobs) == 3
        assert [job.name for job in jobs] == ["load_profile", "backup", "retention"]
        assert [job.interval_sec for job in jobs] == [
            LOAD_PROFILE_INTERVAL_SEC,
            BACKUP_INTERVAL_SEC,
            RETENTION_INTERVAL_SEC,
        ]
        assert [job.fn for job in jobs] == [load_profile_cycle, backup_database, purge_expired]

    def test_backup_runs_before_retention(self) -> None:
        """Deliberate order (issue #19): the backup still holds the rows retention
        is about to delete, so a retention bug is recoverable for seven days. The
        cost is a marginally larger backup file.
        """
        names = [job.name for job in default_jobs()]

        assert names.index("backup") < names.index("retention")

    def test_it_returns_a_fresh_list_each_call(self) -> None:
        """A function, not a module constant — one ``setattr`` swaps it whole."""
        assert default_jobs() is not default_jobs()


# ─── The load-profile cycle (D5–D7) ───────────────────────────────────────────

#: A fixed anchor so the seeded buffer is arithmetic rather than a clock race.
NOW = datetime(2026, 8, 7, 6, 0, tzinfo=UTC)


def make_device(
    name: str,
    *,
    port: int = 4059,
    enabled: bool = True,
    status: str = DeviceStatus.UNKNOWN,
    model: str = "smw110",
) -> int:
    """Insert one device and return its id.

    ``status`` is written directly because the Poller is the only thing that
    writes it in the product (ADR 0004) and these tests are about what the cycle
    *reads*, not about how the column got its value.
    """
    with session_scope() as session:
        device = Device(
            name=name,
            brand="mitsu",
            model=model,
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": port},
            password="hunter2",
            enabled=enabled,
            status=status,
        )
        session.add(device)
        session.flush()
        return device.id


def seed_buffer(*moments: datetime) -> None:
    """Put rows in the fake meter's buffer for it to replay. **Synthesized.**"""
    fake_meter_state().load_profile_rows = [
        IntervalReading(
            read_at=moment,
            source=SOURCE_DLMS,
            logger_id=1,
            interval_sec=900,
            import_active_kwh=1.0,
        )
        for moment in moments
    ]


def stored_read_ats(device_id: int) -> list[datetime]:
    """Every ``read_at`` stored for *device_id*, oldest first."""
    with session_scope() as session:
        return [
            value.replace(tzinfo=UTC)
            for value in session.scalars(
                select(LoadProfileReading.read_at)
                .where(LoadProfileReading.device_id == device_id)
                .order_by(LoadProfileReading.read_at)
            )
        ]


class TestTheCycleReadsTheDevicesItShould:
    """D5 — enabled and not Offline, and nothing else decides."""

    def test_it_reads_an_enabled_device(self, migrated_db: Settings) -> None:
        device_id = make_device("Main Incomer", status=DeviceStatus.ONLINE)
        seed_buffer(NOW - timedelta(hours=1))

        load_profile_cycle()

        assert stored_read_ats(device_id) == [NOW - timedelta(hours=1)]

    def test_an_offline_device_is_skipped_and_its_online_neighbour_is_not(self, migrated_db: Settings) -> None:
        """SPEC §3.5 — a dead meter otherwise burns a full read timeout every cycle."""
        online_id = make_device("Alive", port=4059, status=DeviceStatus.ONLINE)
        offline_id = make_device("Dead", port=4060, status=DeviceStatus.OFFLINE)
        seed_buffer(NOW - timedelta(hours=1))

        load_profile_cycle()

        assert stored_read_ats(online_id) == [NOW - timedelta(hours=1)]
        assert stored_read_ats(offline_id) == [], "the Offline device was read anyway"

    def test_an_unknown_device_is_read(self, migrated_db: Settings) -> None:
        """Only Offline is skipped. A device is Unknown until its first tick, and
        stranding its 90-day backfill behind the Poller's cadence buys nothing.
        """
        device_id = make_device("Fresh", status=DeviceStatus.UNKNOWN)
        seed_buffer(NOW - timedelta(hours=1))

        load_profile_cycle()

        assert stored_read_ats(device_id) == [NOW - timedelta(hours=1)]

    def test_a_disabled_device_is_skipped(self, migrated_db: Settings) -> None:
        device_id = make_device("Paused", enabled=False, status=DeviceStatus.ONLINE)
        seed_buffer(NOW - timedelta(hours=1))

        load_profile_cycle()

        assert stored_read_ats(device_id) == [], "a paused device was read"


@contextmanager
def manual_read_holding(endpoint: str, *, release_after: float) -> Iterator[None]:
    """Hold *endpoint* as a Manual Read, releasing it *release_after* seconds later.

    The process-wide registry on purpose: it is the one
    :func:`load_profile_cycle` uses, and contending on a private one would prove
    nothing about the real path (ADR 0006's registry is process-level by design).

    The timed release is what keeps the failure fast. A background reader that
    wrongly waits blocks for ``MANUAL_READ_LOCK_TIMEOUT_SEC`` — 120 s — so a test
    that simply held the lock would take two minutes to go red.
    """
    lock = endpoint_locks().get(endpoint)
    assert lock.acquire_manual(timeout=5), "the test could not take the endpoint"
    released = threading.Event()

    def release_later() -> None:
        time.sleep(release_after)
        lock.release()
        released.set()

    releaser = threading.Thread(target=release_later, name="test-manual-read", daemon=True)
    releaser.start()
    try:
        yield
    finally:
        released.wait(timeout=10)
        releaser.join(timeout=5)


class TestABusyEndpointIsSkippedNotQueued:
    """CLAUDE.md § Invariants, ADR 0006 — background work is *skipped*, never queued.

    The cycle is background work. If it waited for the endpoint it would hold a
    person's Read now, Test connection or create-time probe behind up to a full
    60 s walk — the exact cost ADR 0006 refuses to pay: *"a skipped background
    tick costs one minute of data, a person waiting on a button costs trust."*
    """

    def test_the_cycle_returns_at_once_when_a_manual_read_holds_the_line(self, migrated_db: Settings) -> None:
        device_id = make_device("Busy", status=DeviceStatus.ONLINE)
        seed_buffer(NOW - timedelta(hours=1))

        with manual_read_holding("127.0.0.1:4059", release_after=1.5):
            started = time.monotonic()
            load_profile_cycle()
            elapsed = time.monotonic() - started

        assert elapsed < 0.5, (
            f"the cycle waited {elapsed:.2f}s for a held endpoint — it queued instead of skipping, "
            f"and on a real line it would wait up to {MANUAL_READ_LOCK_TIMEOUT_SEC:g}s"
        )
        assert stored_read_ats(device_id) == [], "the skipped device was read anyway"

    def test_nothing_is_lost_the_cycle_after_the_line_frees_up(self, migrated_db: Settings) -> None:
        """A skip costs one cycle, not the data (ADR 0008 — the watermark is the data)."""
        device_id = make_device("Busy", status=DeviceStatus.ONLINE)
        pending = NOW - timedelta(hours=1)
        seed_buffer(pending)

        with manual_read_holding("127.0.0.1:4059", release_after=1.5):
            load_profile_cycle()
        assert stored_read_ats(device_id) == []

        load_profile_cycle()

        assert stored_read_ats(device_id) == [pending], "the rows pending during the skip never arrived"

    def test_one_busy_line_does_not_strand_the_rest_of_the_sweep(self, migrated_db: Settings) -> None:
        busy_id = make_device("Busy", port=4059, status=DeviceStatus.ONLINE)
        free_id = make_device("Free", port=4060, status=DeviceStatus.ONLINE)
        seed_buffer(NOW - timedelta(hours=1))

        with manual_read_holding("127.0.0.1:4059", release_after=1.5):
            load_profile_cycle()

        assert stored_read_ats(busy_id) == []
        assert stored_read_ats(free_id) == [NOW - timedelta(hours=1)], (
            "a device on a different endpoint was stranded by the busy one"
        )

    def test_read_now_keeps_its_priority_and_still_waits(self, migrated_db: Settings) -> None:
        """The default path is unchanged: a person's read outranks and waits its turn.

        This is the half that must NOT change — Read now calls
        ``read_and_store_load_profile(device_id)`` with no flag, and it is
        entitled to the endpoint (ADR 0006).
        """
        device_id = make_device("Busy", status=DeviceStatus.ONLINE)
        seed_buffer(NOW - timedelta(hours=1))

        with manual_read_holding("127.0.0.1:4059", release_after=1.0):
            started = time.monotonic()
            result = read_and_store_load_profile(device_id, now=NOW)
            elapsed = time.monotonic() - started

        assert elapsed >= 0.9, f"Read now gave up its priority and skipped after {elapsed:.2f}s"
        assert result.error is None
        assert stored_read_ats(device_id) == [NOW - timedelta(hours=1)]


class TestOneDeviceDoesNotStopTheNext:
    """D7 — the walk is sequential, and sequential must not mean fragile."""

    def test_a_device_that_raises_does_not_strand_the_rest(
        self, migrated_db: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A device deleted mid-cycle raises ``ValueError``; the rest must still run."""
        first = make_device("First", port=4059, status=DeviceStatus.ONLINE)
        second = make_device("Second", port=4060, status=DeviceStatus.ONLINE)
        attempted: list[int] = []

        def explode_on_the_first(device_id: int, **kwargs: object) -> LoadProfileReadResult:
            attempted.append(device_id)
            if device_id == first:
                raise ValueError(f"No device with id {device_id}")
            return LoadProfileReadResult(supported=True, stored=0, through=None, budget_exhausted=False, error=None)

        monkeypatch.setattr("arichds.acquisition.load_profile.read_and_store_load_profile", explode_on_the_first)

        with caplog.at_level(logging.ERROR, logger="arichds.acquisition.load_profile"):
            load_profile_cycle()

        assert attempted == [first, second], "the cycle stopped at the device that raised"
        assert "No device with id" in caplog.text, "the failure was swallowed without a trace"


def status_columns(device_id: int) -> tuple[str, str | None, datetime | None, int]:
    """The four columns ADR 0004 reserves for the Poller."""
    with session_scope() as session:
        device = session.get(Device, device_id)
        return (device.status, device.status_detail, device.status_checked_at, device.consecutive_failures)


def event_kinds(device_id: int) -> list[str]:
    """Every Device Event kind recorded for *device_id*, oldest first."""
    with session_scope() as session:
        return list(
            session.scalars(select(DeviceEvent.kind).where(DeviceEvent.device_id == device_id).order_by(DeviceEvent.id))
        )


class TestTheCycleNeverTouchesDeviceStatus:
    """ADR 0004 / SPEC §3.5 — *"LP job ห้ามแตะสถานะ device"*. One source, the Poller."""

    def test_a_successful_read_writes_no_status(self, migrated_db: Settings) -> None:
        device_id = make_device("Main Incomer", status=DeviceStatus.UNKNOWN)
        seed_buffer(NOW - timedelta(hours=1))
        before = status_columns(device_id)

        load_profile_cycle()

        assert stored_read_ats(device_id), "the device was not read at all, so this proves nothing"
        assert status_columns(device_id) == before, "the cycle wrote device status after a successful read"
        assert event_kinds(device_id) == []

    def test_a_failed_read_is_not_a_strike(self, migrated_db: Settings) -> None:
        """The failure a meter produces must not flip a device Offline.

        Status is what the *Poller* proved. A load-profile read that failed says
        nothing the Poller has not already asked, more recently.
        """
        device_id = make_device("Sulky", status=DeviceStatus.ONLINE)
        fake_meter_state().load_profile_error = TimeoutError("the meter stopped answering")
        before = status_columns(device_id)

        load_profile_cycle()

        # The device really was reached and really did fail — otherwise a change
        # that stopped reading it entirely would pass this test vacuously.
        assert fake_meter_state().load_profile_windows, "the meter was never asked, so this proves nothing"
        assert status_columns(device_id) == before, "a failed load-profile read struck the device"
        assert event_kinds(device_id) == []


def set_status(device_id: int, status: str) -> None:
    """Write ``devices.status`` the way the Poller would (ADR 0004)."""
    with session_scope() as session:
        session.get(Device, device_id).status = status


class TestRecoveryNeedsNoRecoveryCode:
    """A device that comes back is read again because the query re-runs. That is all."""

    def test_the_outage_is_backfilled_when_the_device_returns(self, migrated_db: Settings) -> None:
        """The rows behind an outage arrive on the first cycle after recovery.

        Nothing here retries, remembers, or re-queues: the Poller writes
        ``online`` (ADR 0004), the next cycle's query includes the device again,
        and the watermark (ADR 0008) makes the walk start where the data stopped.
        """
        device_id = make_device("Main Incomer", status=DeviceStatus.ONLINE)
        before_outage = NOW - timedelta(hours=3)
        during_outage = NOW - timedelta(hours=2)

        seed_buffer(before_outage)
        load_profile_cycle()
        assert stored_read_ats(device_id) == [before_outage]

        # The meter dies: the Poller strikes it out, and the meter keeps logging.
        set_status(device_id, DeviceStatus.OFFLINE)
        seed_buffer(before_outage, during_outage)
        load_profile_cycle()
        assert stored_read_ats(device_id) == [before_outage], "the Offline device was read during its outage"

        # It answers again, so the Poller marks it online.
        set_status(device_id, DeviceStatus.ONLINE)
        load_profile_cycle()

        assert stored_read_ats(device_id) == [before_outage, during_outage], (
            "the rows logged during the outage were never backfilled"
        )


class TestTheSchedulerRunsTheCycleWithNobodyPressingAnything:
    """Criterion 2 of issue #16, end to end through a real Scheduler thread."""

    def test_a_device_added_after_start_is_picked_up_with_no_restart(self, migrated_db: Settings) -> None:
        seed_buffer(NOW - timedelta(hours=1))
        scheduler = Scheduler(jobs=[Job(name="load_profile", interval_sec=0.05, fn=load_profile_cycle)])
        scheduler.start()
        try:
            # Created *after* the thread is already running and has already made
            # its first pass over an empty device table.
            device_id = make_device("Latecomer", status=DeviceStatus.ONLINE)

            assert wait_until(lambda: stored_read_ats(device_id) == [NOW - timedelta(hours=1)]), (
                "the device added after start() was never read — the cycle needs a restart to see it"
            )
        finally:
            scheduler.stop()
