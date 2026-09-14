"""``export.energy_csv`` — the Energy Summary export file (M13, issue 02;
rewritten whole from `energy_summary_days` every cycle since ADR 0022/0023,
M14 ticket 04).

Judged on the bytes on disk, like every other export file. There is no
watermark any more (`devices.energy_exported_through` is dropped, migration
0018): every call rewrites the file's whole current content from the stored
table, so what matters here is that the file always equals the table for the
window it claims to cover.
"""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from arichds.config import Settings
from arichds.constants import RETENTION_DAYS
from arichds.db.app_settings import (
    EXPORT_AUTO_SAVE_ENABLED_KEY,
    EXPORT_DATE_FORMAT_KEY,
    EXPORT_ENERGY_FILENAME_TMPL_KEY,
    EXPORT_OUTPUT_DIR_KEY,
    set_setting,
)
from arichds.db.energy_summary_store import energy_summary_recompute_cycle, stored_energy_summary_rows
from arichds.db.models import Device, Holiday, LoadProfileReading
from arichds.db.models import EnergySummaryDay as EnergySummaryDayRow
from arichds.db.session import session_scope
from arichds.export.energy_csv import export_device_energy, export_energy_range, local_today
from arichds.export.format import ENERGY_EXPORT_HEADERS

pytestmark = pytest.mark.usefixtures("fake_meter")


def make_device(*, serial: str | None = "SN-1", customer: str | None = "TFTECH") -> int:
    with session_scope() as session:
        device = Device(
            name="Main Incomer",
            brand="mitsu",
            model="smw110",
            site_name="Plant A",
            customer=customer,
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="hunter2",
            meter_serial=serial,
        )
        session.add(device)
        session.flush()
        return device.id


def local_midnight_utc(day: date) -> datetime:
    """The UTC instant at which *day* begins in the meter's local zone (+7)."""
    return datetime.combine(day, datetime.min.time(), UTC) - timedelta(hours=7)


def seed_reading(device_id: int, day: date, *, kwh: float = 10.0, hour_local: int = 10) -> None:
    """One Interval Reading inside *day*, local time — for the integration
    tests that go through the real recompute job rather than seeding the
    stored table directly."""
    with session_scope() as session:
        session.add(
            LoadProfileReading(
                device_id=device_id,
                read_at=local_midnight_utc(day) + timedelta(hours=hour_local),
                source="dlms",
                logger_id=1,
                interval_sec=900,
                import_active_kwh=kwh,
                export_active_kwh=0.0,
            )
        )


def seed_summary_day(device_id: int, day: date, *, total_import_kwh: float = 10.0) -> None:
    """One `energy_summary_days` row, written directly — what
    `export_device_energy`/`export_energy_range` read since ticket 04. Bypasses
    the recompute job entirely; `test_energy_summary_store.py` owns proving the
    recompute job itself is correct."""
    with session_scope() as session:
        session.add(
            EnergySummaryDayRow(
                device_id=device_id,
                local_date=day,
                peak_import_kwh=0.0,
                offpeak_import_kwh=0.0,
                holiday_import_kwh=0.0,
                total_import_kwh=total_import_kwh,
                peak_export_kwh=0.0,
                offpeak_export_kwh=0.0,
                holiday_export_kwh=0.0,
                total_export_kwh=0.0,
                updated_at=datetime.now(UTC),
            )
        )


def configure(
    *,
    output_dir: Path,
    auto_save_enabled: bool = True,
    filename_tmpl: str = "[meter]-energy.csv",
    date_format: str = "yyyy-mm-dd HH:MM:SS",
) -> None:
    with session_scope() as session:
        set_setting(session, EXPORT_OUTPUT_DIR_KEY, str(output_dir))
        set_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, "true" if auto_save_enabled else "false")
        set_setting(session, EXPORT_ENERGY_FILENAME_TMPL_KEY, filename_tmpl)
        set_setting(session, EXPORT_DATE_FORMAT_KEY, date_format)


def read_rows(path: Path) -> list[list[str]]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


def data_rows(path: Path) -> list[list[str]]:
    return read_rows(path)[6:]


class TestTheDailyFile:
    def test_the_head_is_the_block_then_nine_columns_and_no_total_row(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed_summary_day(device_id, local_today() - timedelta(days=1), total_import_kwh=12.5)

        export_device_energy(device_id, require_auto_save=True)

        rows = read_rows(tmp_path / "SN-1-energy.csv")
        assert rows[4] == ["Energy :", ""]
        assert rows[5] == list(ENERGY_EXPORT_HEADERS)
        assert len(rows[5]) == 9
        assert len(rows) == 7, "one block, one header row, one data row — no total"

    def test_the_date_cell_carries_no_time_of_day(self, migrated_db: Settings, tmp_path: Path) -> None:
        """The row key is a local calendar day, not an instant. Writing a time
        beside it would invent a precision the number does not have."""
        device_id = make_device()
        configure(output_dir=tmp_path, date_format="yyyy-mm-dd HH:MM:SS")
        day = local_today() - timedelta(days=1)
        seed_summary_day(device_id, day)

        export_device_energy(device_id, require_auto_save=True)

        assert data_rows(tmp_path / "SN-1-energy.csv")[0][0] == day.isoformat()


class TestEveryCycleRewritesTheWholeFile:
    """ADR 0023 (ticket 04): the file is rewritten in place, atomically, every
    export cycle — not appended, and never conditional on the head having
    changed. Reverting to an append-only file, or to only rewriting on a head
    change, turns every test in this class red."""

    def test_a_second_cycle_still_holds_exactly_what_is_stored_now(self, migrated_db: Settings, tmp_path: Path) -> None:
        """A second cycle over unchanged data must not duplicate the row —
        the tell for "still appending" rather than "always rewriting"."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed_summary_day(device_id, local_today() - timedelta(days=1))

        export_device_energy(device_id, require_auto_save=True)
        export_device_energy(device_id, require_auto_save=True)

        assert len(data_rows(tmp_path / "SN-1-energy.csv")) == 1

    def test_a_row_added_to_the_store_between_cycles_appears_on_the_next_cycle(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        first_day = local_today() - timedelta(days=3)
        second_day = local_today() - timedelta(days=1)
        seed_summary_day(device_id, first_day)

        export_device_energy(device_id, require_auto_save=True)
        seed_summary_day(device_id, second_day)
        export_device_energy(device_id, require_auto_save=True)

        written = [row[0] for row in data_rows(tmp_path / "SN-1-energy.csv")]
        assert written == [first_day.isoformat(), second_day.isoformat()]

    def test_renaming_the_site_rewrites_the_one_file_with_no_dated_edition(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        first_day = local_today() - timedelta(days=3)
        second_day = local_today() - timedelta(days=1)
        seed_summary_day(device_id, first_day, total_import_kwh=11.0)
        export_device_energy(device_id, require_auto_save=True)

        with session_scope() as session:
            session.get(Device, device_id).site_name = "Plant B"
        seed_summary_day(device_id, second_day, total_import_kwh=22.0)
        export_device_energy(device_id, require_auto_save=True)

        path = tmp_path / "SN-1-energy.csv"
        rows = read_rows(path)
        assert rows[1] == ["Site Name :", "Plant B"]
        written_dates = [row[0] for row in data_rows(path)]
        assert written_dates == [first_day.isoformat(), second_day.isoformat()], (
            "the day already written under the old head must still be in the rewritten file"
        )
        assert list(tmp_path.glob("SN-1-energy.*.csv")) == [], "no dated edition may ever be created"

    def test_a_day_removed_from_the_store_is_removed_from_the_file(self, migrated_db: Settings, tmp_path: Path) -> None:
        """The file mirrors the table, not a history of what was once true —
        the whole reason a watermark is no longer needed."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        day = local_today() - timedelta(days=1)
        seed_summary_day(device_id, day)
        export_device_energy(device_id, require_auto_save=True)
        assert len(data_rows(tmp_path / "SN-1-energy.csv")) == 1

        with session_scope() as session:
            row = session.query(EnergySummaryDayRow).filter_by(device_id=device_id, local_date=day).one()
            session.delete(row)
        # A device that still has at least one other stored day keeps being
        # rewritten — seed a second day so the export does not hold quietly.
        seed_summary_day(device_id, day - timedelta(days=1))
        export_device_energy(device_id, require_auto_save=True)

        written = [row[0] for row in data_rows(tmp_path / "SN-1-energy.csv")]
        assert day.isoformat() not in written


class TestTheWindow:
    """ADR 0023: the Energy file carries no day older than 90 days."""

    def test_a_day_exactly_ninety_days_back_is_in_the_window(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        oldest_in_window = local_today() - timedelta(days=RETENTION_DAYS - 1)
        seed_summary_day(device_id, oldest_in_window)

        export_device_energy(device_id, require_auto_save=True)

        written = [row[0] for row in data_rows(tmp_path / "SN-1-energy.csv")]
        assert oldest_in_window.isoformat() in written

    def test_a_day_one_day_older_than_the_window_is_excluded(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        in_window = local_today() - timedelta(days=1)
        outside_window = local_today() - timedelta(days=RETENTION_DAYS)
        seed_summary_day(device_id, in_window)
        seed_summary_day(device_id, outside_window)

        export_device_energy(device_id, require_auto_save=True)

        written = [row[0] for row in data_rows(tmp_path / "SN-1-energy.csv")]
        assert outside_window.isoformat() not in written
        assert in_window.isoformat() in written


class TestMatchesTheStore:
    """User story 55 / ticket 04's own acceptance criterion: after a Holiday
    change and one recompute, the file's rows equal the stored rows for the
    same days — because both the file and the page now read the same table."""

    def test_a_retroactive_holiday_reaches_the_file_after_one_recompute(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        # A weekday: a weekend day is already Holiday, so adding one would change nothing.
        day = local_today() - timedelta(days=2)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        seed_reading(device_id, day, kwh=40.0, hour_local=10)
        energy_summary_recompute_cycle()

        holiday_column = ENERGY_EXPORT_HEADERS.index("Holiday Import (kWh)")

        # Write the file once, BEFORE the Holiday exists — this is what makes
        # the later assertion prove a rewrite happened rather than merely
        # matching what a first-ever export would have produced anyway.
        export_device_energy(device_id, require_auto_save=True)
        before = data_rows(tmp_path / "SN-1-energy.csv")
        assert before[[row[0] for row in before].index(day.isoformat())][holiday_column] == "0"

        with session_scope() as session:
            session.add(Holiday(kind="public", date=day, name="Declared late"))
        energy_summary_recompute_cycle()
        export_device_energy(device_id, require_auto_save=True)

        with session_scope() as session:
            expected = stored_energy_summary_rows(
                session, device_id, local_today() - timedelta(days=RETENTION_DAYS - 1), local_today()
            )
        written = data_rows(tmp_path / "SN-1-energy.csv")
        assert [row[0] for row in written] == [d.date.isoformat() for d in expected]
        matching = next(d for d in expected if d.date == day)
        assert written[[d.date for d in expected].index(day)][holiday_column] == "40"
        assert matching.holiday_import_kwh == 40.0


class TestTheOnDemandSave:
    def test_its_filename_carries_the_range_so_it_cannot_collide(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        day = local_today() - timedelta(days=2)
        seed_summary_day(device_id, day)

        result = export_energy_range(device_id, day, day)

        assert result.path is not None
        assert result.path.name == f"SN-1-energy-{day.isoformat()}-to-{day.isoformat()}.csv"
        assert result.path.exists()

    def test_it_ignores_the_auto_save_switch(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path, auto_save_enabled=False)
        day = local_today() - timedelta(days=2)
        seed_summary_day(device_id, day)

        assert export_energy_range(device_id, day, day).rows_written == 1

    def test_it_reads_the_stored_table_not_a_live_aggregation(self, migrated_db: Settings, tmp_path: Path) -> None:
        """Ticket 04: **Save to file** now reads `energy_summary_days`, so it
        agrees with the daily file and the page for the same days — a row
        that exists only in `load_profile_readings` and has never been
        recomputed must not appear."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        day = local_today() - timedelta(days=2)
        seed_reading(device_id, day, kwh=99.0)  # never recomputed into the store

        result = export_energy_range(device_id, day, day)

        assert result.rows_written == 0
        assert list(tmp_path.glob("*.csv")) == []

    def test_a_range_with_no_stored_rows_writes_no_file(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        day = local_today() - timedelta(days=2)

        result = export_energy_range(device_id, day, day)

        assert result.rows_written == 0
        assert list(tmp_path.glob("*.csv")) == []


class TestHoldsAreQuiet:
    def test_auto_save_off_holds_the_daily_file(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path, auto_save_enabled=False)
        seed_summary_day(device_id, local_today() - timedelta(days=1))

        assert export_device_energy(device_id, require_auto_save=True).rows_written == 0
        assert not (tmp_path / "SN-1-energy.csv").exists()

    def test_no_meter_serial_holds(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device(serial=None)
        configure(output_dir=tmp_path)

        assert export_device_energy(device_id, require_auto_save=True).rows_written == 0
        assert list(tmp_path.glob("*.csv")) == []

    def test_a_device_with_nothing_stored_holds_quietly(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)

        result = export_device_energy(device_id, require_auto_save=True)

        assert result.rows_written == 0
        assert list(tmp_path.glob("*.csv")) == []


class TestSaveToFileThroughTheApi:
    def test_it_writes_the_range_the_operator_is_looking_at(
        self, migrated_db: Settings, admin_client, tmp_path: Path
    ) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        day = local_today() - timedelta(days=2)
        seed_summary_day(device_id, day)

        response = admin_client.post(f"/api/energy/export?device_id={device_id}&start_date={day}&end_date={day}")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["rows_written"] == 1

    def test_an_unconfigured_output_dir_is_a_422(self, migrated_db: Settings, admin_client) -> None:
        device_id = make_device()
        day = local_today() - timedelta(days=2)
        seed_summary_day(device_id, day)

        response = admin_client.post(f"/api/energy/export?device_id={device_id}&start_date={day}&end_date={day}")

        assert response.status_code == 422, response.text
        assert "export_output_dir" in response.text

    def test_a_range_wider_than_the_screen_allows_is_a_422(
        self, migrated_db: Settings, admin_client, tmp_path: Path
    ) -> None:
        """The same bound the Summary Report carries — and it stops one press
        turning into an unbounded scan."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        end = local_today() - timedelta(days=1)
        start = end - timedelta(days=40)

        response = admin_client.post(f"/api/energy/export?device_id={device_id}&start_date={start}&end_date={end}")

        assert response.status_code == 422, response.text

    def test_a_backwards_range_is_a_422(self, migrated_db: Settings, admin_client, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        day = local_today() - timedelta(days=2)

        response = admin_client.post(
            f"/api/energy/export?device_id={device_id}&start_date={day}&end_date={day - timedelta(days=1)}"
        )

        assert response.status_code == 422, response.text

    def test_a_plain_user_may_press_it(self, migrated_db: Settings, user_client, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        day = local_today() - timedelta(days=2)
        seed_summary_day(device_id, day)

        response = user_client.post(f"/api/energy/export?device_id={device_id}&start_date={day}&end_date={day}")

        assert response.status_code == 200, response.text

    def test_an_unknown_device_is_404(self, migrated_db: Settings, admin_client, tmp_path: Path) -> None:
        configure(output_dir=tmp_path)
        day = local_today() - timedelta(days=2)

        response = admin_client.post(f"/api/energy/export?device_id=999&start_date={day}&end_date={day}")

        assert response.status_code == 404, response.text
