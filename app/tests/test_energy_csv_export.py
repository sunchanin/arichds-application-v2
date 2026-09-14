"""``export.energy_csv`` — the Energy Summary export file (M13, issue 02).

Judged on the bytes on disk, like every other export file. The two things that
are *not* in the file and still matter are the watermark — which is what stops
a day being written twice, and what has to move past an empty day — and the
fact that the on-demand save never touches it.
"""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from arichds.config import Settings
from arichds.db.app_settings import (
    EXPORT_AUTO_SAVE_ENABLED_KEY,
    EXPORT_DATE_FORMAT_KEY,
    EXPORT_ENERGY_FILENAME_TMPL_KEY,
    EXPORT_OUTPUT_DIR_KEY,
    set_setting,
)
from arichds.db.models import Device, Holiday, LoadProfileReading
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


def seed_day(device_id: int, day: date, *, kwh: float = 10.0, hour_local: int = 10) -> None:
    """One Interval Reading inside *day*, local time."""
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


def watermark(device_id: int) -> date | None:
    with session_scope() as session:
        device = session.get(Device, device_id)
        assert device is not None
        return device.energy_exported_through


def set_watermark(device_id: int, value: date) -> None:
    with session_scope() as session:
        session.get(Device, device_id).energy_exported_through = value


class TestTheDailyFile:
    def test_the_head_is_the_block_then_nine_columns_and_no_total_row(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        """No total row in either form: it cannot exist in a file that appends,
        and giving only the on-demand file one would leave two shapes for one
        concept."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        yesterday = local_today() - timedelta(days=1)
        set_watermark(device_id, yesterday - timedelta(days=1))
        seed_day(device_id, yesterday, kwh=12.5)

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
        yesterday = local_today() - timedelta(days=1)
        set_watermark(device_id, yesterday - timedelta(days=1))
        seed_day(device_id, yesterday)

        export_device_energy(device_id, require_auto_save=True)

        assert data_rows(tmp_path / "SN-1-energy.csv")[0][0] == yesterday.isoformat()

    def test_today_is_never_written(self, migrated_db: Settings, tmp_path: Path) -> None:
        """Today is still accumulating, and a partial day appended to a file
        that cannot be revised would be wrong for ever."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        today = local_today()
        set_watermark(device_id, today - timedelta(days=1))
        seed_day(device_id, today)

        result = export_device_energy(device_id, require_auto_save=True)

        assert result.rows_written == 0
        assert not (tmp_path / "SN-1-energy.csv").exists()

    def test_a_second_run_appends_nothing_when_nothing_is_new(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        yesterday = local_today() - timedelta(days=1)
        set_watermark(device_id, yesterday - timedelta(days=1))
        seed_day(device_id, yesterday)

        export_device_energy(device_id, require_auto_save=True)
        second = export_device_energy(device_id, require_auto_save=True)

        assert second.rows_written == 0
        assert len(data_rows(tmp_path / "SN-1-energy.csv")) == 1


class TestTheWatermarkMovesPastADayThatProducedNothing:
    """The trap this codebase has shipped once already: a budgeted walk that
    never reaches data re-runs the same empty window for ever, silently."""

    def test_a_day_with_no_readings_still_advances_the_watermark(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        yesterday = local_today() - timedelta(days=1)
        set_watermark(device_id, yesterday - timedelta(days=1))
        # No readings seeded at all.

        result = export_device_energy(device_id, require_auto_save=True)

        assert result.rows_written == 0
        assert watermark(device_id) == yesterday

    def test_a_gap_in_the_middle_does_not_stall_the_days_after_it(self, migrated_db: Settings, tmp_path: Path) -> None:
        """The failure mode is not a missing row — it is every later row never
        arriving because the walk keeps re-asking about the gap."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        yesterday = local_today() - timedelta(days=1)
        set_watermark(device_id, yesterday - timedelta(days=3))
        seed_day(device_id, yesterday - timedelta(days=2))
        # yesterday - 1 is a genuine gap.
        seed_day(device_id, yesterday)

        export_device_energy(device_id, require_auto_save=True)

        written = [row[0] for row in data_rows(tmp_path / "SN-1-energy.csv")]
        assert written == [
            (yesterday - timedelta(days=2)).isoformat(),
            yesterday.isoformat(),
        ]
        assert watermark(device_id) == yesterday

    def test_the_skipped_day_is_never_revisited(self, migrated_db: Settings, tmp_path: Path) -> None:
        """Readings that arrive late — through the ninety-day backfill — do not
        reach the daily file. This is the consequence the ticket names, and the
        on-demand save is its corrective."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        yesterday = local_today() - timedelta(days=1)
        gap = yesterday - timedelta(days=1)
        set_watermark(device_id, gap - timedelta(days=1))
        seed_day(device_id, yesterday)
        export_device_energy(device_id, require_auto_save=True)

        seed_day(device_id, gap, kwh=99.0)
        export_device_energy(device_id, require_auto_save=True)

        written = [row[0] for row in data_rows(tmp_path / "SN-1-energy.csv")]
        assert gap.isoformat() not in written


class TestTheOnDemandSave:
    def test_its_filename_carries_the_range_so_it_cannot_collide(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        day = local_today() - timedelta(days=2)
        seed_day(device_id, day)

        result = export_energy_range(device_id, day, day)

        assert result.path is not None
        assert result.path.name == f"SN-1-energy-{day.isoformat()}-to-{day.isoformat()}.csv"
        assert result.path.exists()

    def test_it_never_touches_the_watermark(self, migrated_db: Settings, tmp_path: Path) -> None:
        """It is a snapshot somebody asked for, not the archive. Advancing the
        watermark here would make a corrective save skip the very days the
        daily file still owes."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        day = local_today() - timedelta(days=2)
        seed_day(device_id, day)

        export_energy_range(device_id, day, day)

        assert watermark(device_id) is None

    def test_it_ignores_the_auto_save_switch(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path, auto_save_enabled=False)
        day = local_today() - timedelta(days=2)
        seed_day(device_id, day)

        assert export_energy_range(device_id, day, day).rows_written == 1

    def test_it_corrects_a_day_the_daily_file_already_wrote_under_the_old_rules(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        """The whole reason the button exists: the archive froze one answer, a
        Holiday changed what the answer should be, and this is how a file that
        agrees with the screen is produced."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        # A weekday: a weekend day is already Holiday, so adding one would change nothing.
        day = local_today() - timedelta(days=1)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        set_watermark(device_id, day - timedelta(days=1))
        seed_day(device_id, day, kwh=40.0, hour_local=10)
        export_device_energy(device_id, require_auto_save=True)
        archived = data_rows(tmp_path / "SN-1-energy.csv")[0]

        with session_scope() as session:
            session.add(Holiday(kind="public", date=day, name="Declared late"))

        export_energy_range(device_id, day, day)

        corrected = data_rows(tmp_path / f"SN-1-energy-{day.isoformat()}-to-{day.isoformat()}.csv")[0]
        holiday_column = ENERGY_EXPORT_HEADERS.index("Holiday Import (kWh)")
        assert archived[holiday_column] != corrected[holiday_column]
        assert corrected[holiday_column] == "40"

    def test_a_range_with_no_readings_writes_no_file(self, migrated_db: Settings, tmp_path: Path) -> None:
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
        yesterday = local_today() - timedelta(days=1)
        set_watermark(device_id, yesterday - timedelta(days=1))
        seed_day(device_id, yesterday)

        assert export_device_energy(device_id, require_auto_save=True).rows_written == 0
        assert watermark(device_id) == yesterday - timedelta(days=1), "a hold must not advance the watermark"

    def test_no_meter_serial_holds(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device(serial=None)
        configure(output_dir=tmp_path)

        assert export_device_energy(device_id, require_auto_save=True).rows_written == 0
        assert list(tmp_path.glob("*.csv")) == []


class TestSaveToFileThroughTheApi:
    def test_it_writes_the_range_the_operator_is_looking_at(
        self, migrated_db: Settings, admin_client, tmp_path: Path
    ) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        day = local_today() - timedelta(days=2)
        seed_day(device_id, day)

        response = admin_client.post(f"/api/energy/export?device_id={device_id}&start_date={day}&end_date={day}")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["rows_written"] == 1

    def test_an_unconfigured_output_dir_is_a_422(self, migrated_db: Settings, admin_client) -> None:
        device_id = make_device()
        day = local_today() - timedelta(days=2)
        seed_day(device_id, day)

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
        seed_day(device_id, day)

        response = user_client.post(f"/api/energy/export?device_id={device_id}&start_date={day}&end_date={day}")

        assert response.status_code == 200, response.text

    def test_an_unknown_device_is_404(self, migrated_db: Settings, admin_client, tmp_path: Path) -> None:
        configure(output_dir=tmp_path)
        day = local_today() - timedelta(days=2)

        response = admin_client.post(f"/api/energy/export?device_id=999&start_date={day}&end_date={day}")

        assert response.status_code == 404, response.text


class TestAHolidayChangeReportsTheEnergyFilesItMayHaveLeftBehind:
    """M13, issue 03. The Energy Summary is derived on every request precisely
    so a Holiday entered today changes what last January reports tomorrow
    (ADR 0012). The daily file froze one night's answer, and nothing else in the
    product would ever say so."""

    def test_a_past_public_holiday_reports_the_meters_whose_files_passed_it(
        self, migrated_db: Settings, admin_client
    ) -> None:
        device_id = make_device()
        past = local_today() - timedelta(days=3)
        set_watermark(device_id, local_today() - timedelta(days=1))

        response = admin_client.post(
            "/api/holidays", json={"kind": "public", "name": "Declared late", "date": past.isoformat()}
        )

        assert response.status_code == 201, response.text
        data = response.json()["data"]
        assert data["affected_date"] == past.isoformat()
        assert data["energy_files_written_past"] == 1

    def test_a_future_holiday_reports_nothing_at_all(self, migrated_db: Settings, admin_client) -> None:
        """The silence is the feature: a warning that fired on every holiday
        entered in advance would stop meaning anything."""
        device_id = make_device()
        set_watermark(device_id, local_today() - timedelta(days=1))
        future = local_today() + timedelta(days=30)

        response = admin_client.post(
            "/api/holidays", json={"kind": "public", "name": "Next month", "date": future.isoformat()}
        )

        data = response.json()["data"]
        assert data["affected_date"] is None
        assert data["energy_files_written_past"] == 0

    def test_a_machine_whose_files_have_not_reached_the_day_reports_zero(
        self, migrated_db: Settings, admin_client
    ) -> None:
        device_id = make_device()
        past = local_today() - timedelta(days=3)
        set_watermark(device_id, past - timedelta(days=1))

        response = admin_client.post(
            "/api/holidays", json={"kind": "public", "name": "Declared late", "date": past.isoformat()}
        )

        assert response.json()["data"]["energy_files_written_past"] == 0

    def test_a_device_that_has_never_exported_is_never_counted(self, migrated_db: Settings, admin_client) -> None:
        make_device()
        past = local_today() - timedelta(days=3)

        response = admin_client.post(
            "/api/holidays", json={"kind": "public", "name": "Declared late", "date": past.isoformat()}
        )

        assert response.json()["data"]["energy_files_written_past"] == 0

    def test_an_annual_holiday_reports_its_most_recent_occurrence(self, migrated_db: Settings, admin_client) -> None:
        """An annual holiday recurs, so the day that matters is the last one
        that has already happened — not the abstract month and day."""
        device_id = make_device()
        set_watermark(device_id, local_today())
        yesterday = local_today() - timedelta(days=1)

        response = admin_client.post(
            "/api/holidays",
            json={"kind": "annual", "name": "Every year", "month": yesterday.month, "day": yesterday.day},
        )

        assert response.status_code == 201, response.text
        data = response.json()["data"]
        assert data["affected_date"] == yesterday.isoformat()
        assert data["energy_files_written_past"] == 1

    def test_deleting_a_holiday_warns_the_same_way_adding_one_does(self, migrated_db: Settings, admin_client) -> None:
        """Removing a Holiday changes what an already-written day should say
        exactly as much as adding one does."""
        device_id = make_device()
        past = local_today() - timedelta(days=3)
        set_watermark(device_id, local_today() - timedelta(days=1))
        created = admin_client.post(
            "/api/holidays", json={"kind": "public", "name": "Wrong call", "date": past.isoformat()}
        ).json()["data"]["holiday"]

        response = admin_client.delete(f"/api/holidays/{created['id']}")

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["holiday"] is None
        assert data["affected_date"] == past.isoformat()
        assert data["energy_files_written_past"] == 1

    def test_editing_a_holiday_reports_against_its_new_day(self, migrated_db: Settings, admin_client) -> None:
        device_id = make_device()
        set_watermark(device_id, local_today() - timedelta(days=1))
        far_past = local_today() - timedelta(days=40)
        created = admin_client.post(
            "/api/holidays", json={"kind": "public", "name": "Moved", "date": far_past.isoformat()}
        ).json()["data"]["holiday"]
        moved_to = local_today() - timedelta(days=2)

        response = admin_client.patch(
            f"/api/holidays/{created['id']}",
            json={"kind": "public", "name": "Moved", "date": moved_to.isoformat()},
        )

        assert response.json()["data"]["affected_date"] == moved_to.isoformat()

    def test_the_created_holiday_still_comes_back_on_the_response(self, migrated_db: Settings, admin_client) -> None:
        """The count rides alongside the row; it does not replace it."""
        response = admin_client.post("/api/holidays", json={"kind": "annual", "name": "New Year", "month": 1, "day": 1})

        holiday = response.json()["data"]["holiday"]
        assert holiday["name"] == "New Year"
        assert holiday["kind"] == "annual"
