"""The device-status state machine (M3-2).

ADR 0004 in code: status is a pure function of tick outcomes, ``Offline`` after
three consecutive failures, ``Unknown`` when nobody has asked the meter yet, and
``Paused`` computed at read time from ``enabled`` rather than stored.

Everything here drives :mod:`arichds.acquisition.status` directly, with no
threads and no meter — the recorder is the seam the Poller and the API both call,
so testing it here means neither of them needs a state-machine test of its own.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from arichds.acquisition.status import (
    DeviceEventKind,
    DeviceStatus,
    display_status,
    record_event,
    record_failure,
    record_no_driver,
    record_success,
)
from arichds.config import Settings
from arichds.constants import OFFLINE_AFTER_CONSECUTIVE_FAILURES
from arichds.db.models import Device, DeviceEvent
from arichds.db.session import session_scope


@pytest.fixture
def device_id(migrated_db: Settings) -> int:
    """A saved device, freshly created and never yet polled."""
    with session_scope() as session:
        device = Device(
            name="Main Incomer",
            brand="cewe",
            model="prometer100",
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            enabled=True,
        )
        session.add(device)
        session.flush()
        return device.id


def stored(device_id: int) -> Device:
    """Return a detached snapshot of the device row."""
    with session_scope() as session:
        device = session.get(Device, device_id)
        session.expunge(device)
        return device


def events(device_id: int) -> list[DeviceEvent]:
    """Every Device Event for *device_id*, oldest first."""
    with session_scope() as session:
        rows = list(
            session.scalars(select(DeviceEvent).where(DeviceEvent.device_id == device_id).order_by(DeviceEvent.id))
        )
        for row in rows:
            session.expunge(row)
        return rows


class TestRecordSuccess:
    def test_a_successful_tick_reports_online(self, device_id: int) -> None:
        record_success(device_id)
        assert stored(device_id).status == DeviceStatus.ONLINE

    def test_it_stamps_when_the_meter_was_last_checked(self, device_id: int) -> None:
        record_success(device_id)
        assert stored(device_id).status_checked_at is not None

    def test_it_clears_the_detail(self, device_id: int) -> None:
        record_failure(device_id, "something went wrong")
        record_success(device_id)
        assert stored(device_id).status_detail is None

    def test_it_resets_the_strike_counter(self, device_id: int) -> None:
        record_failure(device_id)
        record_failure(device_id)
        record_success(device_id)
        assert stored(device_id).consecutive_failures == 0

    def test_the_first_success_writes_one_online_event(self, device_id: int) -> None:
        record_success(device_id)
        assert [event.kind for event in events(device_id)] == [DeviceEventKind.ONLINE]

    def test_an_automatic_transition_has_no_actor(self, device_id: int) -> None:
        """D11 — ``actor`` answers "who changed this device", and nobody did."""
        record_success(device_id)
        assert events(device_id)[0].actor is None

    def test_ten_successes_in_a_row_write_one_event(self, device_id: int) -> None:
        """A meter that stays online all month writes no rows (CONTEXT.md)."""
        for _ in range(10):
            record_success(device_id)
        assert len(events(device_id)) == 1


class TestRecordFailure:
    def test_one_failure_does_not_flip_the_status(self, device_id: int) -> None:
        record_success(device_id)
        record_failure(device_id)
        assert stored(device_id).status == DeviceStatus.ONLINE

    def test_two_failures_still_do_not(self, device_id: int) -> None:
        record_success(device_id)
        record_failure(device_id)
        record_failure(device_id)
        assert stored(device_id).status == DeviceStatus.ONLINE
        assert len(events(device_id)) == 1  # the online one only

    def test_the_third_failure_flips_it_offline(self, device_id: int) -> None:
        record_success(device_id)
        for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
            record_failure(device_id)
        assert stored(device_id).status == DeviceStatus.OFFLINE

    def test_the_flip_writes_exactly_one_offline_event(self, device_id: int) -> None:
        for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
            record_failure(device_id)
        assert [event.kind for event in events(device_id)] == [DeviceEventKind.OFFLINE]

    def test_further_failures_write_no_further_events(self, device_id: int) -> None:
        """Failures 4, 5, 6… are the same outage, not new ones."""
        for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES + 2):
            record_failure(device_id)
        assert len(events(device_id)) == 1

    def test_the_counter_keeps_climbing(self, device_id: int) -> None:
        for _ in range(5):
            record_failure(device_id)
        assert stored(device_id).consecutive_failures == 5

    def test_an_unknown_device_stays_unknown_below_the_threshold(self, device_id: int) -> None:
        record_failure(device_id)
        assert stored(device_id).status == DeviceStatus.UNKNOWN

    def test_it_stamps_when_the_meter_was_last_checked(self, device_id: int) -> None:
        record_failure(device_id)
        assert stored(device_id).status_checked_at is not None

    def test_a_given_detail_is_kept_verbatim(self, device_id: int) -> None:
        record_failure(device_id, "The meter at 127.0.0.1:4059 did not answer in time.")
        assert stored(device_id).status_detail == "The meter at 127.0.0.1:4059 did not answer in time."

    def test_without_a_detail_it_names_the_streak(self, device_id: int) -> None:
        record_failure(device_id)
        record_failure(device_id)
        detail = stored(device_id).status_detail
        assert detail is not None
        assert "2 consecutive failed reads" in detail

    def test_the_first_failure_reads_as_english(self, device_id: int) -> None:
        """It is shown to a person, so "1 consecutive failed reads" will not do."""
        record_failure(device_id)
        assert stored(device_id).status_detail == "The last read failed — see the application log for the cause."

    def test_a_success_after_offline_comes_back_online(self, device_id: int) -> None:
        for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
            record_failure(device_id)
        record_success(device_id)

        assert stored(device_id).status == DeviceStatus.ONLINE
        assert [event.kind for event in events(device_id)] == [DeviceEventKind.OFFLINE, DeviceEventKind.ONLINE]

    def test_the_outage_can_repeat(self, device_id: int) -> None:
        """Two outages are two pairs of transitions, not one."""
        for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
            record_failure(device_id)
        record_success(device_id)
        for _ in range(OFFLINE_AFTER_CONSECUTIVE_FAILURES):
            record_failure(device_id)

        assert [event.kind for event in events(device_id)] == [
            DeviceEventKind.OFFLINE,
            DeviceEventKind.ONLINE,
            DeviceEventKind.OFFLINE,
        ]


class TestRecordNoDriver:
    def test_it_reports_unknown_not_offline(self, device_id: int) -> None:
        """Nobody asked the meter anything — this is a configuration problem."""
        record_no_driver(device_id, "sim")
        assert stored(device_id).status == DeviceStatus.UNKNOWN

    def test_the_detail_names_the_model_and_the_way_out(self, device_id: int) -> None:
        record_no_driver(device_id, "sim")
        detail = stored(device_id).status_detail
        assert detail is not None
        assert "sim" in detail
        assert "Update" in detail

    def test_nothing_was_checked_so_there_is_no_check_time(self, device_id: int) -> None:
        record_success(device_id)
        record_no_driver(device_id, "sim")
        assert stored(device_id).status_checked_at is None

    def test_it_resets_the_strike_counter(self, device_id: int) -> None:
        record_failure(device_id)
        record_failure(device_id)
        record_no_driver(device_id, "sim")
        assert stored(device_id).consecutive_failures == 0

    def test_it_writes_no_event(self, device_id: int) -> None:
        """D12 — unknown is an absence of knowledge, not a change in the meter."""
        record_success(device_id)
        record_no_driver(device_id, "sim")
        assert [event.kind for event in events(device_id)] == [DeviceEventKind.ONLINE]


class TestDisplayStatus:
    @pytest.mark.parametrize(
        "storable",
        [DeviceStatus.ONLINE, DeviceStatus.OFFLINE, DeviceStatus.UNKNOWN],
    )
    def test_a_paused_device_reads_paused_whatever_is_stored(self, device_id: int, storable: DeviceStatus) -> None:
        """``paused`` is computed, never stored — the API can never report online."""
        with session_scope() as session:
            device = session.get(Device, device_id)
            device.status = storable.value
            device.enabled = False

        assert display_status(stored(device_id)) is DeviceStatus.PAUSED

    @pytest.mark.parametrize(
        "storable",
        [DeviceStatus.ONLINE, DeviceStatus.OFFLINE, DeviceStatus.UNKNOWN],
    )
    def test_an_enabled_device_reads_what_is_stored(self, device_id: int, storable: DeviceStatus) -> None:
        with session_scope() as session:
            session.get(Device, device_id).status = storable.value

        assert display_status(stored(device_id)) is storable


class TestRecordEvent:
    def test_it_does_not_commit_its_own_transaction(self, device_id: int) -> None:
        """The caller owns the transaction, so its column change and its event
        row land together or not at all."""
        with pytest.raises(RuntimeError, match="rolled back"), session_scope() as session:
            record_event(session, device_id=device_id, kind=DeviceEventKind.PAUSED, actor="admin")
            raise RuntimeError("the handler rolled back")

        assert events(device_id) == []

    def test_an_operator_action_carries_the_username(self, device_id: int) -> None:
        with session_scope() as session:
            record_event(session, device_id=device_id, kind=DeviceEventKind.PAUSED, actor="admin")

        event = events(device_id)[0]
        assert event.kind == DeviceEventKind.PAUSED
        assert event.actor == "admin"

    def test_the_detail_is_optional(self, device_id: int) -> None:
        with session_scope() as session:
            record_event(session, device_id=device_id, kind=DeviceEventKind.RESUMED, actor="admin")
        assert events(device_id)[0].detail is None
