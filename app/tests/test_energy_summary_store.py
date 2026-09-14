"""The Energy Summary recompute job (ADR 0022, M14 ticket 01) —
``energy_summary_days``, upserted from the unchanged Time-of-Use aggregation
in ``arichds.db.energy_query`` over the whole retention window, every cycle.

``test_api_energy.py`` exercises the read side end to end through
``GET /api/energy/summary`` (Output Parity against real HTTP requests,
Stored-not-live). This file owns the write side: the diff-then-upsert that
keeps ``updated_at`` quiet on an unchanged day, the retroactive and
late-reading reach a full-window recompute gives for free, and "a day with no
readings produces no row".
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from arichds.config import Settings
from arichds.constants import RETENTION_DAYS, SOURCE_DLMS
from arichds.db.energy_query import energy_summary_rows
from arichds.db.energy_summary_store import _BUCKET_FIELDS, energy_summary_recompute_cycle
from arichds.db.models import Device, EnergySummaryDay, Holiday, LoadProfileReading
from arichds.db.session import session_scope

NOW = datetime(2026, 8, 8, 6, 0, tzinfo=UTC)


def make_device(name: str = "Main Incomer") -> int:
    with session_scope() as session:
        device = Device(
            name=name,
            brand="mitsu",
            model="smw110",
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="hunter2",
        )
        session.add(device)
        session.flush()
        return device.id


def seed(device_id: int, rows: list[tuple[datetime, float, float]], *, logger_id: int = 1) -> None:
    """One Interval Reading per ``(read_at, import_active_kwh, export_active_kwh)``."""
    with session_scope() as session:
        session.add_all(
            LoadProfileReading(
                device_id=device_id,
                read_at=read_at,
                source=SOURCE_DLMS,
                logger_id=logger_id,
                interval_sec=900,
                import_active_kwh=imp,
                export_active_kwh=exp,
            )
            for read_at, imp, exp in rows
        )


def stored_rows(device_id: int) -> dict[date, dict[str, object]]:
    """Every stored ``energy_summary_days`` row for *device_id*, as plain
    values keyed by local date — extracted inside the session so nothing
    here touches a detached ORM instance."""
    with session_scope() as session:
        rows = session.scalars(select(EnergySummaryDay).where(EnergySummaryDay.device_id == device_id)).all()
        return {
            row.local_date: {
                **{field: getattr(row, field) for field in _BUCKET_FIELDS},
                "updated_at": row.updated_at.replace(tzinfo=UTC) if row.updated_at.tzinfo is None else row.updated_at,
            }
            for row in rows
        }


class TestOutputParity:
    """Ticket 01 — the stored rows equal what the current live aggregation
    returns, day by day and bucket by bucket, on a dataset covering a
    weekend, a public Holiday, an annual Holiday, both sides of the peak
    boundary and an all-invalid interval."""

    def test_stored_rows_match_the_live_aggregation_bucket_by_bucket(self, migrated_db: Settings) -> None:
        device_id = make_device()
        today = date(2026, 8, 9)  # a Sunday — weekend Holiday, in range
        with session_scope() as session:
            session.add(Holiday(kind="public", name="One-off", date=date(2026, 8, 3)))
            session.add(Holiday(kind="annual", name="Songkran", month=4, day=13))

        seed(
            device_id,
            [
                (datetime(2026, 8, 3, 8, 0, tzinfo=UTC), 3.0, 0.5),  # public Holiday
                (datetime(2026, 8, 9, 8, 0, tzinfo=UTC), 2.0, 0.0),  # weekend Holiday
                (datetime(2026, 8, 6, 1, 59, tzinfo=UTC), 1.0, 0.0),  # off-peak, just before the boundary
                (datetime(2026, 8, 6, 2, 0, tzinfo=UTC), 2.0, 0.0),  # peak, on the boundary
                (datetime(2027, 4, 13, 10, 0, tzinfo=UTC), 4.0, 0.0),  # annual Holiday — outside this window
            ],
        )
        with session_scope() as session:
            session.add(
                LoadProfileReading(
                    device_id=device_id,
                    read_at=datetime(2026, 8, 6, 10, 0, tzinfo=UTC),
                    source=SOURCE_DLMS,
                    logger_id=1,
                    interval_sec=900,
                    import_active_kwh=99.0,  # would dominate the day if counted
                    interval_status_flag=1,  # ALL_INVALID — excluded (INV-LP-06)
                )
            )

        energy_summary_recompute_cycle(today=today, now=NOW)

        window_start = today - timedelta(days=RETENTION_DAYS - 1)
        with session_scope() as session:
            live = {day.date: day for day in energy_summary_rows(session, device_id, window_start, today)}

        stored = stored_rows(device_id)
        assert set(stored) == set(live), (
            f"stored days {sorted(stored)} do not match the live aggregation's days {sorted(live)}"
        )
        for local_date, live_day in live.items():
            for field in _BUCKET_FIELDS:
                assert stored[local_date][field] == pytest.approx(getattr(live_day, field)), (
                    f"{local_date} {field}: stored={stored[local_date][field]} live={getattr(live_day, field)}"
                )
        # The all-invalid row's 99.0 must not have leaked into 2026-08-06's total.
        assert stored[date(2026, 8, 6)]["total_import_kwh"] == pytest.approx(3.0)


class TestADayWithNoReadingsProducesNoRow:
    def test_a_device_with_nothing_in_the_window_gets_no_rows(self, migrated_db: Settings) -> None:
        device_id = make_device()

        energy_summary_recompute_cycle(today=date(2026, 8, 8), now=NOW)

        assert stored_rows(device_id) == {}


class TestStaleRowsAreDeleted:
    """ADR 0022 (``docs/adr/0022-…md:57-58``) — "invalidates nothing: it
    recomputes everything, every time." A stored day inside the window whose
    readings are gone (``Delete all data``, or a re-read that reclassifies
    every interval all-invalid) must not linger with a wrong number until
    Retention — it is deleted on the very next recompute."""

    def test_a_day_whose_readings_are_gone_is_deleted_on_the_next_recompute(self, migrated_db: Settings) -> None:
        device_id = make_device()
        today = date(2026, 8, 7)
        kept_day = date(2026, 8, 6)
        removed_day = date(2026, 8, 7)
        seed(
            device_id,
            [
                (datetime(2026, 8, 6, 10, 0, tzinfo=UTC), 2.5, 0.0),
                (datetime(2026, 8, 7, 10, 0, tzinfo=UTC), 1.0, 0.0),
            ],
        )
        energy_summary_recompute_cycle(today=today, now=NOW)
        before = stored_rows(device_id)
        assert set(before) == {kept_day, removed_day}, "both seeded days should have produced a row"

        with session_scope() as session:
            session.execute(
                delete(LoadProfileReading).where(
                    LoadProfileReading.device_id == device_id,
                    LoadProfileReading.read_at >= datetime(2026, 8, 7, 0, 0, tzinfo=UTC),
                )
            )

        energy_summary_recompute_cycle(today=today, now=NOW + timedelta(hours=1))
        after = stored_rows(device_id)

        assert removed_day not in after, "the stale row survived a recompute after its readings were deleted"
        assert kept_day in after
        assert after[kept_day]["updated_at"] == before[kept_day]["updated_at"], (
            "an unrelated day's updated_at moved just because another day's row was deleted"
        )


class TestLateReadings:
    """Rows inserted for a past day after a recompute are counted after the next."""

    def test_a_reading_inserted_after_the_first_recompute_is_counted_on_the_next(self, migrated_db: Settings) -> None:
        device_id = make_device()
        today = date(2026, 8, 6)  # a Thursday
        seed(device_id, [(datetime(2026, 8, 6, 10, 0, tzinfo=UTC), 2.5, 0.0)])

        energy_summary_recompute_cycle(today=today, now=NOW)
        assert stored_rows(device_id)[today]["total_import_kwh"] == pytest.approx(2.5)

        seed(device_id, [(datetime(2026, 8, 6, 1, 0, tzinfo=UTC), 1.5, 0.0)])  # arrives late, e.g. a backfill
        energy_summary_recompute_cycle(today=today, now=NOW + timedelta(seconds=1))

        assert stored_rows(device_id)[today]["total_import_kwh"] == pytest.approx(4.0), (
            "the late-arriving row was never counted on the next recompute"
        )


class TestQuietRecompute:
    """A second recompute over unchanged data leaves every ``updated_at``
    untouched; changing one day's data moves only that day's ``updated_at``."""

    def test_a_recompute_over_unchanged_data_does_not_move_updated_at(self, migrated_db: Settings) -> None:
        device_id = make_device()
        today = date(2026, 8, 6)
        seed(device_id, [(datetime(2026, 8, 6, 10, 0, tzinfo=UTC), 2.5, 0.0)])

        energy_summary_recompute_cycle(today=today, now=NOW)
        first = stored_rows(device_id)[today]["updated_at"]

        energy_summary_recompute_cycle(today=today, now=NOW + timedelta(hours=1))
        second = stored_rows(device_id)[today]["updated_at"]

        assert second == first, "a recompute over unchanged data moved updated_at"
        assert second == NOW, "updated_at was re-stamped even though nothing changed"

    def test_changing_one_days_data_moves_only_that_days_updated_at(self, migrated_db: Settings) -> None:
        device_id = make_device()
        today = date(2026, 8, 7)
        unchanged_day = date(2026, 8, 6)
        changed_day = date(2026, 8, 7)
        seed(
            device_id,
            [
                (datetime(2026, 8, 6, 10, 0, tzinfo=UTC), 2.5, 0.0),
                (datetime(2026, 8, 7, 10, 0, tzinfo=UTC), 1.0, 0.0),
            ],
        )
        energy_summary_recompute_cycle(today=today, now=NOW)
        before = stored_rows(device_id)

        seed(device_id, [(datetime(2026, 8, 7, 11, 0, tzinfo=UTC), 5.0, 0.0)])  # only touches 2026-08-07
        later = NOW + timedelta(hours=1)
        energy_summary_recompute_cycle(today=today, now=later)

        after = stored_rows(device_id)
        assert after[unchanged_day]["updated_at"] == before[unchanged_day]["updated_at"], (
            "an unrelated day's updated_at moved"
        )
        assert after[changed_day]["updated_at"] == later, "the changed day's updated_at did not move to the new stamp"
        assert after[changed_day]["total_import_kwh"] == pytest.approx(6.0)


class TestSequentialOverDevices:
    """Mirrors every other cycle job (battery, billing) — one device's
    failure never strands the rest of the site's recompute."""

    def test_a_device_that_raises_does_not_strand_the_next_device(
        self, migrated_db: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = make_device("First")
        second = make_device("Second")
        seed(first, [(datetime(2026, 8, 6, 10, 0, tzinfo=UTC), 1.0, 0.0)])
        seed(second, [(datetime(2026, 8, 6, 10, 0, tzinfo=UTC), 2.0, 0.0)])

        real_rows = energy_summary_rows

        def explode_for_first(session: object, device_id: int, start: date, end: date) -> object:
            if device_id == first:
                raise RuntimeError("boom")
            return real_rows(session, device_id, start, end)

        monkeypatch.setattr("arichds.db.energy_summary_store.energy_summary_rows", explode_for_first)

        energy_summary_recompute_cycle(today=date(2026, 8, 6), now=NOW)

        assert stored_rows(first) == {}, "the failing device should not have written a row"
        assert stored_rows(second)[date(2026, 8, 6)]["total_import_kwh"] == pytest.approx(2.0), (
            "the device behind the one that raised was never recomputed"
        )
