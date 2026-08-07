"""The priority-aware Transport Endpoint lock registry (M3-1).

CONTEXT.md defines the lock key: *"The physical channel a meter is reached
through — ``host:port`` for TCP, a COM port name for serial. Concurrency locks
key on the endpoint, not the device: devices sharing a serial line queue behind
one lock."*

**The priority rule (ADR 0006).** A **Manual Read** — the probe behind Create or
Update, Test connection, Read now — is granted the endpoint ahead of any
background tick. One rule delivers all four of the ADR's requirements at once:

    ``try_acquire_background`` fails immediately when the lock is held **or**
    when a Manual Read is waiting for it.

* Manual Reads win, because a waiting one shuts the background path out.
* Background never queues — ``try_acquire_background`` never blocks; a tick that
  cannot have the endpoint is *skipped*, and the next one is 60 seconds away
  carrying a correct timestamp.
* Nothing in flight is preempted — priority decides who gets the lock next,
  never who keeps it now.
* There is no fairness parameter to tune, so there is nothing to get wrong on a
  site nobody can log into.

**The registry is process-level, not a Poller attribute.** The lock is a
property of *this machine's* Transport Endpoints, not of the thing that happens
to be reading them. A probe must take the same lock as a background tick even
when the Poller's master switch is off (``ARICHDS_POLL_ENABLED=false``) and
after ``Poller.restart()`` — which ``create_device`` and ``delete_device`` both
call. Holding the registry here makes that true by construction rather than by
the accident of ``Poller.__init__`` running once.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class PriorityEndpointLock:
    """One Transport Endpoint's lock, with Manual Reads ahead of background ticks.

    Not a queue, not a semaphore, not a timeout race: a
    :class:`threading.Condition` guarding a held flag plus a count of waiting
    Manual Reads. Deliberately the one place in v2 where lock behaviour is not
    the language default (ADR 0006), and therefore the one place tested hardest.
    """

    def __init__(self) -> None:
        """Create an unheld lock with no waiting Manual Reads."""
        self._condition = threading.Condition()
        self._held = False
        self._manual_waiting = 0

    @property
    def manual_waiting(self) -> int:
        """How many Manual Reads are currently waiting for this endpoint.

        The state the priority rule turns on, exposed read-only so the behaviour
        is observable rather than inferred from timing.
        """
        with self._condition:
            return self._manual_waiting

    def acquire_manual(self, timeout: float | None = None) -> bool:
        """Take the endpoint for a Manual Read, waiting for it if necessary.

        Announces the wait *before* blocking, which is what shuts background
        ticks out for the duration.

        Args:
            timeout: Seconds to wait, or None to wait indefinitely.

        Returns:
            True once the endpoint is held; False if *timeout* elapsed first.
        """
        with self._condition:
            self._manual_waiting += 1
            try:
                acquired = self._condition.wait_for(lambda: not self._held, timeout=timeout)
                if acquired:
                    self._held = True
                return acquired
            finally:
                self._manual_waiting -= 1

    def try_acquire_background(self) -> bool:
        """Take the endpoint for a background tick, or give up immediately.

        Never blocks. Refuses while the endpoint is held **or** while any Manual
        Read is waiting for it.

        **Do not "simplify" the ``or self._manual_waiting`` half away.** Without
        it this is plain mutual exclusion, and the priority rule is silently
        gone: the only state it changes is *endpoint free, Manual Read already
        waiting*, which is exactly the moment a background tick would overtake a
        person who is waiting. That state is transient — it lives between
        :meth:`release` and the woken waiter re-taking the condition mutex — so
        it is constructed deliberately by
        ``test_endpoint_locks.py::TestPriority::
        test_a_waiting_manual_read_is_not_overtaken_when_the_endpoint_frees_up``,
        which is the one test in the suite that fails if this clause goes.

        Returns:
            True if the endpoint is now held by the caller; False if the tick
            should be skipped.
        """
        with self._condition:
            if self._held or self._manual_waiting:
                return False
            self._held = True
            return True

    def release(self) -> None:
        """Release the endpoint and wake whoever is waiting for it.

        Raises:
            RuntimeError: If the lock was not held — a bug in the caller, and
                one that would otherwise corrupt the held flag silently.
        """
        with self._condition:
            if not self._held:
                raise RuntimeError("Releasing a Transport Endpoint lock that is not held")
            self._held = False
            self._condition.notify_all()

    @contextmanager
    def manual(self, timeout: float | None = None) -> Iterator[None]:
        """Hold the endpoint for a Manual Read for the duration of the block.

        Args:
            timeout: Seconds to wait for the endpoint, or None to wait forever.

        Raises:
            TimeoutError: If the endpoint could not be taken within *timeout*.
        """
        if not self.acquire_manual(timeout=timeout):
            raise TimeoutError(f"Timed out after {timeout}s waiting for the Transport Endpoint")
        try:
            yield
        finally:
            self.release()

    @contextmanager
    def background(self) -> Iterator[bool]:
        """Hold the endpoint for a background tick, or yield False.

        Yields:
            True while the endpoint is held; False when the tick must be
            skipped, in which case nothing is held and nothing is released.
        """
        acquired = self.try_acquire_background()
        try:
            yield acquired
        finally:
            if acquired:
                self.release()


class EndpointLocks:
    """Hands out one :class:`PriorityEndpointLock` per Transport Endpoint.

    Thread-safe: the registry itself is guarded, so two workers racing to poll
    the first two devices on one line still end up sharing a single lock.
    Entries are never removed — a lock outlives the device that first needed it,
    which costs a few dozen bytes and removes a whole class of race.
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._registry: dict[str, PriorityEndpointLock] = {}
        self._guard = threading.Lock()

    def get(self, endpoint: str) -> PriorityEndpointLock:
        """Return the lock for *endpoint*, creating it on first use."""
        with self._guard:
            lock = self._registry.get(endpoint)
            if lock is None:
                lock = PriorityEndpointLock()
                self._registry[endpoint] = lock
            return lock


#: The process-wide registry. Everything that talks to a meter — the Poller and
#: every Manual Read path in the API — takes its locks from here.
_PROCESS_LOCKS = EndpointLocks()


def endpoint_locks() -> EndpointLocks:
    """Return the process-wide Transport Endpoint lock registry."""
    return _PROCESS_LOCKS
