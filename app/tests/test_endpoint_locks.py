"""The priority-aware Transport Endpoint lock (M3-1).

ADR 0006: a Manual Read — the probe behind Create/Update, Test connection, Read
now — is granted the endpoint ahead of any background tick; an in-flight read is
never interrupted; a background tick that loses its slot is **skipped, not
queued**; and a skipped tick must stay distinguishable from a failed one.

Every test here proves those properties with counters and events, never with
``time.sleep`` races — a timing-based concurrency test that passes is not
evidence of anything.
"""

from __future__ import annotations

import threading
import time

from arichds.acquisition.locks import EndpointLocks, PriorityEndpointLock, endpoint_locks


def wait_for_manual_waiters(lock: PriorityEndpointLock, count: int, timeout: float = 5.0) -> bool:
    """Block until *count* Manual Reads are parked on *lock*.

    A bounded wait on an observable property, not a fixed sleep: the assertion
    that follows is about the priority rule, never about how fast a thread got
    scheduled.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if lock.manual_waiting >= count:
            return True
        time.sleep(0.01)
    return False


class TestRegistry:
    def test_same_endpoint_shares_one_lock(self) -> None:
        """Devices on one line queue behind a single lock (REMAKE-PLAN §3.2)."""
        locks = EndpointLocks()
        assert locks.get("10.0.0.1:4059") is locks.get("10.0.0.1:4059")

    def test_different_endpoints_get_different_locks(self) -> None:
        locks = EndpointLocks()
        assert locks.get("10.0.0.1:4059") is not locks.get("10.0.0.2:4059")

    def test_the_registry_hands_out_priority_locks(self) -> None:
        assert isinstance(EndpointLocks().get("10.0.0.1:4059"), PriorityEndpointLock)

    def test_the_process_registry_is_one_object(self) -> None:
        """The lock belongs to the machine's endpoints, not to any one caller."""
        assert endpoint_locks() is endpoint_locks()


class TestPriority:
    def test_background_gets_the_lock_when_nobody_wants_it(self) -> None:
        lock = PriorityEndpointLock()
        assert lock.try_acquire_background() is True
        lock.release()

    def test_background_is_refused_while_the_lock_is_held(self) -> None:
        """It returns immediately — a background tick never queues."""
        lock = PriorityEndpointLock()
        assert lock.acquire_manual(timeout=1) is True
        try:
            assert lock.try_acquire_background() is False
        finally:
            lock.release()

    def test_a_waiting_manual_read_blocks_the_next_background_tick(self) -> None:
        """A parked Manual Read wins the endpoint ahead of a background tick."""
        lock = PriorityEndpointLock()
        assert lock.acquire_manual(timeout=1) is True
        parked = threading.Event()
        got_it = threading.Event()

        def manual_waiter() -> None:
            parked.set()
            if lock.acquire_manual(timeout=5):
                got_it.set()
                lock.release()

        waiter = threading.Thread(target=manual_waiter, daemon=True)
        waiter.start()
        assert parked.wait(timeout=5)
        # The waiter has announced itself; wait for the counter to register.
        assert wait_for_manual_waiters(lock, 1)

        assert lock.try_acquire_background() is False

        lock.release()
        assert got_it.wait(timeout=5), "the parked Manual Read never got the endpoint"
        waiter.join(timeout=5)

        # Once the manual waiter is done the endpoint is free again.
        assert lock.try_acquire_background() is True
        lock.release()

    def test_an_in_flight_read_is_never_interrupted(self) -> None:
        """Priority decides who gets the lock next, never who keeps it now."""
        lock = PriorityEndpointLock()
        holding = threading.Event()
        holder_done = threading.Event()
        release_holder = threading.Event()
        manual_in = threading.Event()

        def background_holder() -> None:
            assert lock.try_acquire_background() is True
            holding.set()
            try:
                release_holder.wait(timeout=10)
                holder_done.set()
            finally:
                lock.release()

        def manual_reader() -> None:
            if lock.acquire_manual(timeout=10):
                manual_in.set()
                lock.release()

        holder = threading.Thread(target=background_holder, daemon=True)
        holder.start()
        assert holding.wait(timeout=5)

        reader = threading.Thread(target=manual_reader, daemon=True)
        reader.start()
        assert wait_for_manual_waiters(lock, 1)

        # The Manual Read is waiting, not preempting: the holder is still in.
        assert not manual_in.is_set()
        release_holder.set()
        assert manual_in.wait(timeout=5)
        assert holder_done.is_set()
        holder.join(timeout=5)
        reader.join(timeout=5)

    def test_a_waiting_manual_read_is_not_overtaken_when_the_endpoint_frees_up(self) -> None:
        """The state the priority rule exists for: free endpoint, Manual Read waiting.

        Every other test here holds the lock while asserting, which plain mutual
        exclusion already satisfies — so this is the only one that fails if the
        ``_manual_waiting`` half of ``try_acquire_background`` is ever dropped.
        """
        for _ in range(50):
            lock = PriorityEndpointLock()
            assert lock.try_acquire_background() is True  # a tick is mid-read
            granted = threading.Event()

            def manual_reader(lock: PriorityEndpointLock = lock, granted: threading.Event = granted) -> None:
                if lock.acquire_manual(timeout=5):
                    granted.set()
                    lock.release()

            reader = threading.Thread(target=manual_reader, daemon=True)
            reader.start()
            assert wait_for_manual_waiters(lock, 1)

            lock.release()  # the in-flight tick finishes; the endpoint is now FREE

            # The Poller's next tick must not take it out from under the person who
            # is already waiting — that is the whole of ADR 0006.
            assert lock.try_acquire_background() is False, "a background tick overtook a waiting Manual Read"
            assert granted.wait(timeout=5)
            reader.join(timeout=5)

    def test_manual_and_background_never_overlap(self) -> None:
        """A shared 'currently inside' counter must never exceed 1."""
        lock = PriorityEndpointLock()
        inside = 0
        max_inside = 0
        guard = threading.Lock()
        errors: list[str] = []

        def enter() -> None:
            nonlocal inside, max_inside
            with guard:
                inside += 1
                max_inside = max(max_inside, inside)

        def leave() -> None:
            nonlocal inside
            with guard:
                inside -= 1

        def manual_worker() -> None:
            for _ in range(50):
                if not lock.acquire_manual(timeout=10):
                    errors.append("manual timed out")
                    return
                enter()
                leave()
                lock.release()

        def background_worker() -> None:
            for _ in range(200):
                if lock.try_acquire_background():
                    enter()
                    leave()
                    lock.release()

        threads = [threading.Thread(target=manual_worker, daemon=True) for _ in range(3)]
        threads += [threading.Thread(target=background_worker, daemon=True) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert errors == []
        assert max_inside == 1, f"manual and background overlapped on one endpoint (max {max_inside})"
        assert inside == 0


class TestContextManagers:
    def test_manual_releases_on_the_way_out(self) -> None:
        lock = PriorityEndpointLock()
        with lock.manual():
            assert lock.try_acquire_background() is False
        assert lock.try_acquire_background() is True
        lock.release()

    def test_manual_releases_even_when_the_body_raises(self) -> None:
        """A leaked hold would wedge the endpoint for the life of the process."""
        lock = PriorityEndpointLock()

        class BoomError(Exception):
            pass

        try:
            with lock.manual():
                raise BoomError
        except BoomError:
            pass

        assert lock.try_acquire_background() is True
        lock.release()

    def test_manual_raises_on_timeout(self) -> None:
        lock = PriorityEndpointLock()
        assert lock.acquire_manual(timeout=1) is True
        try:
            try:
                with lock.manual(timeout=0.05):
                    raise AssertionError("the second Manual Read should not have got in")
            except TimeoutError:
                pass
        finally:
            lock.release()

    def test_background_yields_true_and_releases(self) -> None:
        lock = PriorityEndpointLock()
        with lock.background() as acquired:
            assert acquired is True
        assert lock.try_acquire_background() is True
        lock.release()

    def test_background_yields_false_when_skipped(self) -> None:
        lock = PriorityEndpointLock()
        assert lock.acquire_manual(timeout=1) is True
        try:
            with lock.background() as acquired:
                assert acquired is False
        finally:
            lock.release()

    def test_a_skipped_background_body_releases_nothing(self) -> None:
        """Exiting a skipped ``background()`` must not release someone else's hold."""
        lock = PriorityEndpointLock()
        assert lock.acquire_manual(timeout=1) is True
        with lock.background() as acquired:
            assert acquired is False
        # The Manual Read still holds it — a stray release would have freed it.
        assert lock.try_acquire_background() is False
        lock.release()

    def test_background_releases_even_when_the_body_raises(self) -> None:
        lock = PriorityEndpointLock()

        class BoomError(Exception):
            pass

        try:
            with lock.background() as acquired:
                assert acquired is True
                raise BoomError
        except BoomError:
            pass

        assert lock.try_acquire_background() is True
        lock.release()
