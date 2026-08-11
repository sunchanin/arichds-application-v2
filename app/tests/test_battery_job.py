"""``read_and_store_battery()`` / ``battery_cycle()`` — the battery read job
(M7-2, issue #29).

Everything runs against ``FakeMeterDriver`` (``prometer100`` — the
battery-capable registration, D10); nothing here touches a meter. Shaped on
``test_billing_job.py`` for the fixture pattern and the background lock
discipline, but the day-guard is unique to this job (D1-D4): the interval is
hourly and ``battery_cycle()`` skips any device that already has today's row,
so a failed read must leave no row at all — that is the single interaction
every test below is ultimately protecting.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fakes import FakeMeterState
from sqlalchemy import select

from arichds.acquisition.battery import battery_cycle, read_and_store_battery
from arichds.acquisition.locks import EndpointLocks
from arichds.acquisition.status import DeviceStatus
from arichds.config import Settings
from arichds.db.models import BatteryReading as BatteryReadingRow
from arichds.db.models import Device
from arichds.db.session import session_scope

pytestmark = pytest.mark.usefixtures("fake_meter")

NOW = datetime(2026, 8, 11, 10, 0, 0, tzinfo=UTC)
ENDPOINT = "127.0.0.1:4059"


def make_device(
    model: str = "prometer100",
    *,
    name: str = "Main Incomer",
    enabled: bool = True,
    status: str = DeviceStatus.UNKNOWN,
) -> int:
    with session_scope() as session:
        device = Device(
            name=name,
            brand="cewe",
            model=model,
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="hunter2",
            enabled=enabled,
            status=status,
        )
        session.add(device)
        session.flush()
        return device.id


@pytest.fixture
def device_id(migrated_db: Settings) -> int:
    return make_device()


def stored_rows(device_id: int) -> list[BatteryReadingRow]:
    with session_scope() as session:
        return list(
            session.scalars(
                select(BatteryReadingRow).where(BatteryReadingRow.device_id == device_id).order_by(BatteryReadingRow.id)
            )
        )


class TestStoringAReading:
    def test_a_supported_read_stores_one_row(self, device_id: int, fake_meter: FakeMeterState) -> None:
        fake_meter.battery_status = "4321"

        result = read_and_store_battery(device_id, now=NOW)

        assert result.supported is True
        assert result.error is None
        assert result.skipped is False
        assert result.row_id is not None
        rows = stored_rows(device_id)
        assert len(rows) == 1
        assert rows[0].status == "4321"
        assert rows[0].read_at.replace(tzinfo=UTC) == NOW
        assert fake_meter.disconnects == 1, "the endpoint must be released after a successful read"


class TestASuccessfulReadReturningNoneStillWritesARow:
    def test_none_status_stores_a_row_with_null_status(self, device_id: int, fake_meter: FakeMeterState) -> None:
        """D4 — the meter answering with nothing is still a *successful*
        read: it counts as today's row and must not be retried."""
        fake_meter.battery_status = None

        result = read_and_store_battery(device_id, now=NOW)

        assert result.error is None
        assert result.row_id is not None
        rows = stored_rows(device_id)
        assert len(rows) == 1
        assert rows[0].status is None


class TestAFailedReadWritesNoRow:
    def test_a_raising_read_leaves_no_row(self, device_id: int, fake_meter: FakeMeterState) -> None:
        """D4 — this is the single most important interaction in the
        issue: a failed read must not write a row, or the day-guard would
        suppress the remaining 23 retries."""
        fake_meter.battery_error = TimeoutError("the meter went away")

        result = read_and_store_battery(device_id, now=NOW)

        assert result.supported is True
        assert result.row_id is None
        assert result.error is not None
        assert "TimeoutError" in result.error
        assert stored_rows(device_id) == []
        assert fake_meter.disconnects == 1, "the endpoint must be released even after a failed read"

    def test_a_connect_failure_leaves_no_row(self, device_id: int, fake_meter: FakeMeterState) -> None:
        fake_meter.connect_error = ConnectionError("boom")

        result = read_and_store_battery(device_id, now=NOW)

        assert result.row_id is None
        assert result.error is not None
        assert stored_rows(device_id) == []


class TestStatusTruncation:
    def test_a_status_longer_than_twenty_chars_is_truncated_and_warned(
        self, device_id: int, fake_meter: FakeMeterState, caplog: pytest.LogCaptureFixture
    ) -> None:
        fake_meter.battery_status = "1234567890123456789012345"  # 25 chars

        with caplog.at_level("WARNING"):
            result = read_and_store_battery(device_id, now=NOW)

        rows = stored_rows(device_id)
        assert rows[0].status == "12345678901234567890"  # first 20 chars
        assert len(rows[0].status) == 20
        assert any("truncat" in record.message.lower() for record in caplog.records)
        assert result.error is None


class TestUnsupportedModel:
    def test_a_model_with_no_battery_register_is_skipped_without_connecting(
        self, migrated_db: Settings, fake_meter: FakeMeterState
    ) -> None:
        """D10 — smw110 is not battery-capable; this is what the explicit
        `FakeSmw110Driver.supports_battery() -> False` override buys."""
        smw110_id = make_device("smw110")

        result = read_and_store_battery(smw110_id, now=NOW)

        assert result.supported is False
        assert result.row_id is None
        assert result.error is None
        assert fake_meter.connects == 0
        assert stored_rows(smw110_id) == []


class TestLockDiscipline:
    def test_a_busy_endpoint_skips_without_connecting_and_writes_nothing(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """D5 — background only, so a busy endpoint is skipped, never
        queued (ADR 0006)."""
        locks = EndpointLocks()
        assert locks.get(ENDPOINT).acquire_manual(timeout=0) is True

        result = read_and_store_battery(device_id, locks=locks, now=NOW)

        assert result.supported is True
        assert result.skipped is True
        assert result.error is None
        assert fake_meter.connects == 0
        assert stored_rows(device_id) == []


class TestItNeverTouchesDeviceStatus:
    """ADR 0004 — only ``liveness`` touches status; a battery read (success,
    failure, or a busy-endpoint skip) is never a strike."""

    def test_a_successful_read_moves_no_status(self, device_id: int, fake_meter: FakeMeterState) -> None:
        fake_meter.battery_status = "OK"

        read_and_store_battery(device_id, now=NOW)

        with session_scope() as session:
            device = session.get(Device, device_id)
            assert device is not None
            assert device.status == "unknown"
            assert device.consecutive_failures == 0

    def test_a_failed_read_moves_no_status(self, device_id: int, fake_meter: FakeMeterState) -> None:
        fake_meter.battery_error = TimeoutError("the meter went away")

        read_and_store_battery(device_id, now=NOW)

        with session_scope() as session:
            device = session.get(Device, device_id)
            assert device is not None
            assert device.status == "unknown"
            assert device.consecutive_failures == 0

    def test_a_busy_endpoint_skip_moves_no_status(self, device_id: int, fake_meter: FakeMeterState) -> None:
        locks = EndpointLocks()
        assert locks.get(ENDPOINT).acquire_manual(timeout=0) is True

        read_and_store_battery(device_id, locks=locks, now=NOW)

        with session_scope() as session:
            device = session.get(Device, device_id)
            assert device is not None
            assert device.status == "unknown"
            assert device.consecutive_failures == 0


class TestAnUnknownDeviceIsAValueError:
    def test_raises(self, migrated_db: Settings) -> None:
        with pytest.raises(ValueError):
            read_and_store_battery(9999, now=NOW)


class TestBatteryCycleDayGuard:
    """D1-D4 — the whole reason for the hourly cadence lives here."""

    def test_running_the_cycle_twice_in_one_day_makes_one_meter_call(
        self, migrated_db: Settings, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.battery_status = "4321"
        device_id = make_device()

        battery_cycle()
        battery_cycle()

        assert fake_meter.battery_reads == 1
        assert len(stored_rows(device_id)) == 1

    def test_the_day_guard_is_per_device_not_global(
        self, migrated_db: Settings, fake_meter: FakeMeterState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reviewer finding 1 — the day-guard must be keyed on ``device_id``,
        never on "some device was read today". A one-device test cannot tell
        the two apart, because with one device they always agree; this one
        seeds device A with today's row and leaves device B untouched, so a
        global guard (which would skip B too, since *a* row exists today)
        and a per-device guard (which reads B) disagree on both the call
        count and on which device got the new row."""
        device_a = make_device(name="Device A")
        device_b = make_device(name="Device B")
        today = datetime(2026, 8, 11, 4, 0, 0, tzinfo=UTC)
        with session_scope() as session:
            session.add(BatteryReadingRow(device_id=device_a, read_at=today, status="OLD"))

        import arichds.acquisition.battery as battery_module

        monkeypatch.setattr(battery_module, "datetime", _FrozenDatetime)
        fake_meter.battery_status = "NEW"

        battery_cycle()

        assert fake_meter.battery_reads == 1
        rows_a = stored_rows(device_a)
        rows_b = stored_rows(device_b)
        assert len(rows_a) == 1, "device A already had today's row and must not gain a second"
        assert len(rows_b) == 1, "device B had no row today and must be read"
        assert rows_b[0].status == "NEW"

    def test_a_row_at_yesterday_23_59_59_utc_is_still_read(
        self, migrated_db: Settings, fake_meter: FakeMeterState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        device_id = make_device()
        yesterday_end = datetime(2026, 8, 10, 23, 59, 59, tzinfo=UTC)
        with session_scope() as session:
            session.add(BatteryReadingRow(device_id=device_id, read_at=yesterday_end, status="OLD"))

        import arichds.acquisition.battery as battery_module

        monkeypatch.setattr(battery_module, "datetime", _FrozenDatetime)
        fake_meter.battery_status = "NEW"

        battery_cycle()

        assert fake_meter.battery_reads == 1
        assert len(stored_rows(device_id)) == 2

    def test_a_row_at_today_00_00_00_utc_is_not_read_again(
        self, migrated_db: Settings, fake_meter: FakeMeterState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        device_id = make_device()
        today_start = datetime(2026, 8, 11, 0, 0, 0, tzinfo=UTC)
        with session_scope() as session:
            session.add(BatteryReadingRow(device_id=device_id, read_at=today_start, status="OLD"))

        import arichds.acquisition.battery as battery_module

        monkeypatch.setattr(battery_module, "datetime", _FrozenDatetime)
        fake_meter.battery_status = "NEW"

        battery_cycle()

        assert fake_meter.battery_reads == 0
        assert len(stored_rows(device_id)) == 1

    def test_a_raising_read_is_retried_on_the_next_cycle(
        self, migrated_db: Settings, fake_meter: FakeMeterState
    ) -> None:
        """The test that proves the hourly cadence is worth anything (D4)."""
        make_device()
        fake_meter.battery_error = TimeoutError("boom")

        battery_cycle()
        assert fake_meter.battery_reads == 1

        fake_meter.battery_error = None
        fake_meter.battery_status = "OK"
        battery_cycle()

        assert fake_meter.battery_reads == 2

    def test_one_devices_failure_does_not_strand_the_rest(
        self, migrated_db: Settings, fake_meter: FakeMeterState
    ) -> None:
        with session_scope() as session:
            session.add(
                Device(
                    name="Malformed",
                    brand="cewe",
                    model="prometer100",
                    site_name="Plant A",
                    transport={"kind": "net"},
                )
            )
        working_id = make_device()
        fake_meter.battery_status = "OK"

        battery_cycle()  # must not raise

        assert fake_meter.battery_reads == 1
        assert len(stored_rows(working_id)) == 1

    def test_it_reads_every_enabled_non_offline_device(self, migrated_db: Settings, fake_meter: FakeMeterState) -> None:
        """Reviewer finding 2 — a single eligible device cannot prove the two
        filters exist at all, only that an eligible device is read. Adding a
        Paused (``enabled=False``) and an Offline device is what makes this
        test actually exercise ``Device.enabled``/``Device.status`` rather
        than merely claiming to, in its name."""
        fake_meter.battery_status = "OK"
        eligible_id = make_device(name="Eligible")
        paused_id = make_device(name="Paused", enabled=False)
        offline_id = make_device(name="Offline", status=DeviceStatus.OFFLINE)

        battery_cycle()

        assert fake_meter.battery_reads == 1
        assert len(stored_rows(eligible_id)) == 1
        assert stored_rows(paused_id) == [], "CONTEXT.md — Pause stops every background read of a device"
        assert stored_rows(offline_id) == []


class _FrozenDatetime(datetime):
    """A ``datetime`` whose ``now()`` always answers 2026-08-11T10:00:00Z —
    the fixed "now" the day-guard boundary tests need."""

    @classmethod
    def now(cls, tz: object = None) -> datetime:  # type: ignore[override]
        return datetime(2026, 8, 11, 10, 0, 0, tzinfo=UTC)
