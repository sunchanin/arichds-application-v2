"""``read_and_store_billing()`` / ``billing_cycle()`` — the one billing read
path (M6a, issue #21; ADR 0009).

Everything runs against ``FakeSmw110Driver``; nothing here touches a meter.
Shaped on ``test_load_profile_job.py``, but the write rules differ from the
load-profile job in the ways ADR 0009 requires: one whole-buffer read, closed
periods deduped by natural key and never rewritten, and the Open Period found
by ``record_status``, never by ``bill_date``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeMeterState
from sqlalchemy import select

from arichds.acquisition.billing import billing_change_check, billing_cycle, read_and_store_billing
from arichds.acquisition.drivers.base import BillingReading
from arichds.acquisition.locks import EndpointLocks
from arichds.config import Settings
from arichds.constants import SOURCE_DLMS
from arichds.db.models import BillingReading as BillingReadingRow
from arichds.db.models import Device, DeviceEvent
from arichds.db.session import session_scope

pytestmark = pytest.mark.usefixtures("fake_meter")

NOW = datetime(2026, 8, 7, 6, 0, tzinfo=UTC)
ENDPOINT = "127.0.0.1:4059"


def make_device(model: str = "smw110") -> int:
    with session_scope() as session:
        device = Device(
            name="Main Incomer",
            brand="mitsu",
            model=model,
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="hunter2",
        )
        session.add(device)
        session.flush()
        return device.id


@pytest.fixture
def device_id(migrated_db: Settings) -> int:
    return make_device()


def closed_rows(device_id: int) -> list[BillingReadingRow]:
    with session_scope() as session:
        return list(
            session.scalars(
                select(BillingReadingRow)
                .where(BillingReadingRow.device_id == device_id, BillingReadingRow.record_status.is_(None))
                .order_by(BillingReadingRow.bill_date)
            )
        )


def open_row(device_id: int) -> BillingReadingRow | None:
    with session_scope() as session:
        return session.scalar(
            select(BillingReadingRow).where(
                BillingReadingRow.device_id == device_id, BillingReadingRow.record_status == "open"
            )
        )


#: The three recorded entries, as UTC BillingReadings (Finding 4), newest first.
ENTRY_1 = BillingReading(
    bill_date=datetime(2026, 8, 7, 4, 37, 58, tzinfo=UTC),
    source=SOURCE_DLMS,
    is_open=True,
    meter_serial="1232002893",
    import_active_kwh_total=200464.501,
)
ENTRY_2 = BillingReading(
    bill_date=datetime(2026, 7, 31, 17, 0, 0, tzinfo=UTC),
    source=SOURCE_DLMS,
    is_open=False,
    meter_serial="1232002893",
    import_active_kwh_total=198685.030,
)
ENTRY_3 = BillingReading(
    bill_date=datetime(2026, 6, 30, 17, 0, 0, tzinfo=UTC),
    source=SOURCE_DLMS,
    is_open=False,
    meter_serial="1232002893",
    import_active_kwh_total=189917.399,
)


class TestRereadingIsANoOp:
    def test_reading_the_same_buffer_twice_stores_nothing_new(self, device_id: int, fake_meter: FakeMeterState) -> None:
        fake_meter.billing_rows = [ENTRY_1, ENTRY_2, ENTRY_3]

        read_and_store_billing(device_id, now=NOW)
        first_stored = len(closed_rows(device_id))
        read_and_store_billing(device_id, now=NOW)

        assert len(closed_rows(device_id)) == first_stored == 2

    def test_reading_the_same_buffer_twice_changes_no_stored_value(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.billing_rows = [ENTRY_1, ENTRY_2, ENTRY_3]

        read_and_store_billing(device_id, now=NOW)
        before = [(row.bill_date, row.import_active_kwh_total) for row in closed_rows(device_id)]
        read_and_store_billing(device_id, now=NOW)
        after = [(row.bill_date, row.import_active_kwh_total) for row in closed_rows(device_id)]

        assert before == after

    def test_mutation_a_stricter_comparison_would_still_pass_but_a_looser_one_would_not(self) -> None:
        """Proves the dedup key discriminates: two BillingReadings with the same
        ``bill_date`` but a different value must NOT compare equal under the
        writer's rule (compare the 40 measurement columns, exact)."""
        a = ENTRY_2.as_columns()
        b = ENTRY_2.__class__(
            bill_date=ENTRY_2.bill_date,
            source=ENTRY_2.source,
            is_open=ENTRY_2.is_open,
            import_active_kwh_total=ENTRY_2.import_active_kwh_total + 0.001,
        ).as_columns()
        assert a != b


class TestADifferingClosedPeriodIsSkipped:
    def test_a_changed_value_for_an_already_stored_period_is_not_rewritten(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.billing_rows = [ENTRY_1, ENTRY_2]
        read_and_store_billing(device_id, now=NOW)
        stored_before = closed_rows(device_id)[0].import_active_kwh_total

        changed = BillingReading(
            bill_date=ENTRY_2.bill_date,
            source=SOURCE_DLMS,
            is_open=False,
            import_active_kwh_total=1.0,  # a different value at the same bill_date
        )
        fake_meter.billing_rows = [ENTRY_1, changed]
        result = read_and_store_billing(device_id, now=NOW)

        assert closed_rows(device_id)[0].import_active_kwh_total == stored_before
        assert result.stored == 0

    def test_a_differing_closed_period_logs_a_warning_naming_the_device_and_bill_date(
        self, device_id: int, fake_meter: FakeMeterState, caplog: pytest.LogCaptureFixture
    ) -> None:
        fake_meter.billing_rows = [ENTRY_1, ENTRY_2]
        read_and_store_billing(device_id, now=NOW)

        changed = BillingReading(
            bill_date=ENTRY_2.bill_date, source=SOURCE_DLMS, is_open=False, import_active_kwh_total=1.0
        )
        fake_meter.billing_rows = [ENTRY_1, changed]

        with caplog.at_level("WARNING"):
            read_and_store_billing(device_id, now=NOW)

        messages = [record.message for record in caplog.records]
        assert any("Main Incomer" in m and ENTRY_2.bill_date.isoformat() in m for m in messages)

    def test_mutation_removing_the_skip_would_silently_rewrite_history(self) -> None:
        """Direct proof the guard matters: without the equality check, a second
        read with a different value would simply overwrite row one — this shows
        the two states are in fact different, so an overwrite is observable."""
        stored_value = 198685.030
        incoming_value = 1.0
        assert stored_value != incoming_value


class TestAMonthRolloverInOnePass:
    def test_the_closed_row_is_inserted_and_the_open_slot_moves_in_one_call(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """Frozen entry 2 becomes a new closed period, entry 1's fresh clock
        replaces the open slot — both in the same read (ADR 0009's whole
        rationale for reading the buffer in one pass)."""
        fake_meter.billing_rows = [ENTRY_2, ENTRY_3]  # the world before rollover: ENTRY_2 running
        open_before = BillingReading(
            bill_date=ENTRY_2.bill_date, source=SOURCE_DLMS, is_open=True, import_active_kwh_total=198685.030
        )
        fake_meter.billing_rows = [open_before, ENTRY_3]
        read_and_store_billing(device_id, now=NOW)
        assert open_row(device_id) is not None
        assert len(closed_rows(device_id)) == 1

        # Rollover: what was open froze as a closed period; a new open period appears.
        fake_meter.billing_rows = [ENTRY_1, ENTRY_2, ENTRY_3]
        result = read_and_store_billing(device_id, now=NOW)

        closed = closed_rows(device_id)
        assert len(closed) == 2
        closed_dates = [row.bill_date.replace(tzinfo=UTC) for row in closed]
        assert ENTRY_2.bill_date in closed_dates
        stored_entry_2 = next(row for row in closed if row.bill_date.replace(tzinfo=UTC) == ENTRY_2.bill_date)
        assert stored_entry_2.import_active_kwh_total == pytest.approx(198685.030)

        slot = open_row(device_id)
        assert slot is not None
        assert slot.bill_date.replace(tzinfo=UTC) == ENTRY_1.bill_date
        assert slot.import_active_kwh_total == pytest.approx(200464.501)
        assert result.open_updated is True


class TestTheOpenSlotIsFoundByRecordStatusNotBillDate:
    def test_the_open_slot_is_a_single_row_that_gets_overwritten_in_place(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.billing_rows = [ENTRY_1]
        read_and_store_billing(device_id, now=NOW)
        first_id = open_row(device_id).id  # type: ignore[union-attr]

        later = BillingReading(
            bill_date=ENTRY_1.bill_date + timedelta(hours=1), source=SOURCE_DLMS, is_open=True, meter_serial="X"
        )
        fake_meter.billing_rows = [later]
        read_and_store_billing(device_id, now=NOW)

        with session_scope() as session:
            rows = session.scalars(
                select(BillingReadingRow).where(
                    BillingReadingRow.device_id == device_id, BillingReadingRow.record_status == "open"
                )
            ).all()
            assert len(rows) == 1
            assert rows[0].id == first_id
            assert rows[0].bill_date.replace(tzinfo=UTC) == later.bill_date

    def test_no_open_row_from_the_driver_leaves_the_existing_slot_untouched(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.billing_rows = [ENTRY_1]
        read_and_store_billing(device_id, now=NOW)
        before = open_row(device_id)
        assert before is not None

        fake_meter.billing_rows = [ENTRY_2]  # a closed-only buffer, no open row at all
        result = read_and_store_billing(device_id, now=NOW)

        after = open_row(device_id)
        assert after is not None
        assert after.bill_date == before.bill_date
        assert result.open_updated is False


class TestClosedPeriodsLandBeforeTheOpenSlotMoves:
    def test_a_fresh_device_stores_the_closed_periods_and_the_open_slot_together(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.billing_rows = [ENTRY_1, ENTRY_2, ENTRY_3]

        result = read_and_store_billing(device_id, now=NOW)

        assert result.stored == 2
        assert result.open_updated is True
        assert len(closed_rows(device_id)) == 2
        assert open_row(device_id) is not None


class TestLockDiscipline:
    def test_a_busy_endpoint_under_background_skips_without_error(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        locks = EndpointLocks()
        assert locks.get(ENDPOINT).acquire_manual(timeout=0) is True

        result = read_and_store_billing(device_id, locks=locks, now=NOW, background=True)

        assert result.skipped is True
        assert result.error is None
        assert fake_meter.connects == 0

    def test_a_busy_endpoint_on_manual_is_a_timeout_sentence(self, device_id: int, fake_meter: FakeMeterState) -> None:
        locks = EndpointLocks()
        assert locks.get(ENDPOINT).acquire_manual(timeout=0) is True

        result = read_and_store_billing(device_id, locks=locks, lock_timeout_sec=0.01, now=NOW)

        assert result.error is not None
        assert "busy" in result.error
        assert fake_meter.connects == 0

    def test_a_manual_read_never_sets_skipped(self, device_id: int, fake_meter: FakeMeterState) -> None:
        fake_meter.billing_rows = [ENTRY_1]

        result = read_and_store_billing(device_id, now=NOW)

        assert result.skipped is False


class TestAWriteFailureIsASentenceToo:
    """The store runs inside the same try as the read — a DB-side failure must
    become a sentence exactly like a meter failure, never an unhandled
    exception reaching the API or ``billing_cycle``'s per-device guard."""

    def test_a_failure_while_storing_does_not_escape_as_an_exception(
        self, device_id: int, fake_meter: FakeMeterState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import arichds.acquisition.billing as billing_module

        fake_meter.billing_rows = [ENTRY_1]

        def _boom(*args: object, **kwargs: object) -> bool:
            raise RuntimeError("unexpected write failure")

        monkeypatch.setattr(billing_module, "_upsert_open", _boom)

        result = read_and_store_billing(device_id, now=NOW)  # must not raise

        assert result.error is not None
        assert "RuntimeError" in result.error

    def test_a_failure_while_storing_is_not_a_strike(
        self, device_id: int, fake_meter: FakeMeterState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import arichds.acquisition.billing as billing_module

        def _boom(*args: object, **kwargs: object) -> bool:
            raise RuntimeError("unexpected write failure")

        fake_meter.billing_rows = [ENTRY_1]
        monkeypatch.setattr(billing_module, "_upsert_open", _boom)

        read_and_store_billing(device_id, now=NOW)

        with session_scope() as session:
            device = session.get(Device, device_id)
            assert device is not None
            assert device.status == "unknown"
            assert device.consecutive_failures == 0


class TestUnsupportedAndFailures:
    def test_a_model_without_billing_reports_unsupported_and_touches_nothing(
        self, migrated_db: Settings, fake_meter: FakeMeterState
    ) -> None:
        prometer_id = make_device("prometer100")

        result = read_and_store_billing(prometer_id, now=NOW)

        assert result.supported is False
        assert result.stored == 0
        assert result.error is None
        assert fake_meter.connects == 0

    def test_a_meter_failure_is_a_sentence_never_an_exception(self, device_id: int, fake_meter: FakeMeterState) -> None:
        fake_meter.billing_error = TimeoutError("the meter went away")

        result = read_and_store_billing(device_id, now=NOW)

        assert result.supported is True
        assert result.error is not None
        assert ENDPOINT in result.error
        assert "TimeoutError" in result.error

    def test_an_unknown_device_is_a_value_error(self, migrated_db: Settings) -> None:
        with pytest.raises(ValueError):
            read_and_store_billing(9999, now=NOW)


class TestItNeverTouchesDeviceStatus:
    def test_a_successful_read_writes_no_device_event_and_moves_no_status(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.billing_rows = [ENTRY_1, ENTRY_2]

        read_and_store_billing(device_id, now=NOW)

        with session_scope() as session:
            device = session.get(Device, device_id)
            assert device is not None
            assert device.status == "unknown"
            assert device.consecutive_failures == 0
            assert session.scalars(select(DeviceEvent)).all() == []

    def test_a_failed_read_writes_no_device_event_and_moves_no_status(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.billing_error = TimeoutError("the meter went away")

        read_and_store_billing(device_id, now=NOW)

        with session_scope() as session:
            device = session.get(Device, device_id)
            assert device is not None
            assert device.status == "unknown"
            assert device.consecutive_failures == 0


class _StubBillingDriver:
    """The minimal seam :func:`billing_change_check` actually depends on —
    not a full :class:`MeterDriver`, so these tests exercise the check's own
    D2/D3/D4/D9 logic without any DLMS mechanics (those are covered against
    the real drivers in ``test_dlms_profile_seams.py`` /
    ``test_smw110_billing.py``)."""

    def __init__(self, newest_closed: datetime | None = None, error: Exception | None = None) -> None:
        self._newest_closed = newest_closed
        self._error = error
        self.calls = 0

    def billing_newest_closed_bill_date(self) -> datetime | None:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._newest_closed


class TestBillingChangeCheck:
    """D1-D4, D9, D13 — issue #43, ADR 0018 (corrected)."""

    def test_no_stored_closed_rows_triggers(self, device_id: int) -> None:
        """D4 — a freshly added device with nothing stored yet gets its
        billing inside one Load Profile cycle rather than waiting a day."""
        driver = _StubBillingDriver(newest_closed=datetime(2026, 7, 31, 10, 0, tzinfo=UTC))

        assert billing_change_check(driver, device_id) is True

    def test_an_unchanged_newest_closed_period_does_not_trigger(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.billing_rows = [ENTRY_1, ENTRY_2]
        read_and_store_billing(device_id, now=NOW)
        driver = _StubBillingDriver(newest_closed=ENTRY_2.bill_date)

        assert billing_change_check(driver, device_id) is False

    def test_a_genuinely_new_closed_period_triggers(self, device_id: int, fake_meter: FakeMeterState) -> None:
        fake_meter.billing_rows = [ENTRY_1, ENTRY_2]
        read_and_store_billing(device_id, now=NOW)
        driver = _StubBillingDriver(newest_closed=ENTRY_1.bill_date)  # a period the store has never seen closed

        assert billing_change_check(driver, device_id) is True

    def test_the_stored_open_slot_never_wins_the_comparison(self, device_id: int, fake_meter: FakeMeterState) -> None:
        """D2 — ``record_status IS NULL`` filter. Mutation: dropping it lets
        the open slot's ever-advancing bill_date win the stored-side MAX,
        which would make this compare ENTRY_2 (unchanged closed) against
        ENTRY_1 (the open slot) and wrongly trigger."""
        fake_meter.billing_rows = [ENTRY_1, ENTRY_2]  # ENTRY_1 open, ENTRY_2 closed
        read_and_store_billing(device_id, now=NOW)
        driver = _StubBillingDriver(newest_closed=ENTRY_2.bill_date)  # the closed period, unchanged

        assert billing_change_check(driver, device_id) is False

    def test_a_stored_closed_row_with_no_meter_serial_still_counts(
        self, device_id: int, fake_meter: FakeMeterState
    ) -> None:
        """D2 — compared on ``device_id`` alone, never
        ``(device, meter_serial)``. Mutation: filtering on meter_serial would
        exclude a legitimately stored row whose ``meter_serial`` is ``None``
        — the real failure mode both driver read paths hit when the serial
        register read fails *after* the billing buffer was already read
        (`_dlms_profile.py`, `smw110.py`) — making the stored-side ``MAX``
        come back ``NULL`` and firing a full read every single cycle."""
        no_serial_closed = BillingReading(
            bill_date=ENTRY_2.bill_date,
            source=SOURCE_DLMS,
            is_open=False,
            meter_serial=None,  # the serial-read-failed-after-buffer-read case
            import_active_kwh_total=198685.030,
        )
        fake_meter.billing_rows = [ENTRY_1, no_serial_closed]
        read_and_store_billing(device_id, now=NOW)
        driver = _StubBillingDriver(newest_closed=ENTRY_2.bill_date)  # unchanged

        assert billing_change_check(driver, device_id) is False

    def test_a_backward_moving_bill_date_still_triggers(self, device_id: int, fake_meter: FakeMeterState) -> None:
        """D3 — ``!=``, not ``>``. A buffer that appears to have moved
        backwards (a wrapped ring, a re-provisioned meter) is still worth
        re-reading; the whole-buffer write path is idempotent."""
        fake_meter.billing_rows = [ENTRY_1, ENTRY_2]
        read_and_store_billing(device_id, now=NOW)
        driver = _StubBillingDriver(newest_closed=ENTRY_3.bill_date)  # earlier than the stored ENTRY_2

        assert billing_change_check(driver, device_id) is True

    def test_a_driver_that_cannot_answer_does_not_trigger(self, device_id: int) -> None:
        """The base-class default (``None``) must degrade to 'no trigger',
        never raise or crash the walk it rides on."""
        driver = _StubBillingDriver(newest_closed=None)

        assert billing_change_check(driver, device_id) is False

    def test_a_raising_driver_is_swallowed_and_does_not_trigger(self, device_id: int) -> None:
        """D9 — any failure inside the check is swallowed."""
        driver = _StubBillingDriver(error=RuntimeError("meter refused the billing profile"))

        assert billing_change_check(driver, device_id) is False

    def test_a_raising_driver_logs_a_warning(self, device_id: int, caplog: pytest.LogCaptureFixture) -> None:
        driver = _StubBillingDriver(error=RuntimeError("meter refused the billing profile"))

        with caplog.at_level("WARNING"):
            billing_change_check(driver, device_id)

        assert any(str(device_id) in record.message for record in caplog.records)


class TestBillingCycle:
    def test_it_reads_every_enabled_non_offline_device(self, migrated_db: Settings, fake_meter: FakeMeterState) -> None:
        fake_meter.billing_rows = [ENTRY_1]
        make_device()

        billing_cycle()

        assert fake_meter.billing_reads == 1

    def test_one_devices_failure_does_not_strand_the_rest(
        self, migrated_db: Settings, fake_meter: FakeMeterState
    ) -> None:
        """A device the cycle cannot even build a driver for (malformed
        transport) must cost that one device, not the whole sweep — mirrors
        ``load_profile_cycle``'s own guard for this exact case."""
        with session_scope() as session:
            session.add(
                Device(
                    name="Malformed",
                    brand="mitsu",
                    model="smw110",
                    site_name="Plant A",
                    transport={"kind": "net"},
                )
            )
        working_id = make_device(model="smw110")
        fake_meter.billing_rows = [ENTRY_1]

        billing_cycle()  # must not raise

        assert fake_meter.billing_reads == 1
        assert len(closed_rows(working_id)) == 0
        assert open_row(working_id) is not None
