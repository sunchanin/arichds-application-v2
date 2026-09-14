"""``export.billing_csv`` — the billing export file (M13, issue 01; rewritten
whole from every closed period on every export cycle since ADR 0023, M14
ticket 04).

Everything here is judged **on the bytes that reach disk**, because that file
is the whole deliverable: a person opens it in Excel and every rule in the
ticket is either visible there or it is not enforced. There is no watermark
any more (`devices.billing_exported_through` is dropped, migration 0018):
every call rewrites the file's whole current content from every closed
period, so a second cycle over unchanged data must reproduce the same file,
never duplicate a row.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from arichds.config import Settings
from arichds.db.app_settings import (
    EXPORT_AUTO_SAVE_ENABLED_KEY,
    EXPORT_BILLING_FILENAME_TMPL_KEY,
    EXPORT_DATE_FORMAT_KEY,
    EXPORT_OUTPUT_DIR_KEY,
    set_setting,
)
from arichds.db.models import BillingReading, Device
from arichds.db.session import session_scope
from arichds.export.billing_csv import export_device_billing
from arichds.export.format import BILLING_EXPORT_HEADERS

pytestmark = pytest.mark.usefixtures("fake_meter")

JAN = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

#: What a SMART TCC stores for a tariff whose demand was never recorded —
#: local 2000-01-01, which is 1999-12-31 17:00 UTC. Read off the customer's own
#: database, 2026-09-09.
TCC_NEVER = datetime(1999, 12, 31, 17, 0, tzinfo=UTC)


def make_device(
    *,
    name: str = "Main Incomer",
    serial: str | None = "SN-1",
    site_name: str = "Plant A",
    customer: str | None = "TFTECH",
    enabled: bool = True,
) -> int:
    with session_scope() as session:
        device = Device(
            name=name,
            brand="mitsu",
            model="smw110",
            site_name=site_name,
            customer=customer,
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="hunter2",
            enabled=enabled,
            meter_serial=serial,
        )
        session.add(device)
        session.flush()
        return device.id


def seed(device_id: int, bill_date: datetime, *, status: str | None = None, **columns: object) -> None:
    with session_scope() as session:
        session.add(
            BillingReading(
                device_id=device_id,
                bill_date=bill_date,
                read_at=bill_date + timedelta(hours=1),
                record_status=status,
                source="dlms",
                meter_serial="SN-1",
                **columns,
            )
        )


def configure(
    *,
    output_dir: Path,
    auto_save_enabled: bool = True,
    filename_tmpl: str = "[meter]-billing.csv",
    date_format: str = "yyyy-mm-dd HH:MM:SS",
) -> None:
    with session_scope() as session:
        set_setting(session, EXPORT_OUTPUT_DIR_KEY, str(output_dir))
        set_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, "true" if auto_save_enabled else "false")
        set_setting(session, EXPORT_BILLING_FILENAME_TMPL_KEY, filename_tmpl)
        set_setting(session, EXPORT_DATE_FORMAT_KEY, date_format)


def read_rows(path: Path) -> list[list[str]]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


def data_rows(path: Path) -> list[list[str]]:
    """Everything below the five-line block and the column header row."""
    return read_rows(path)[6:]


def cell(path: Path, row_index: int, header: str) -> str:
    return data_rows(path)[row_index][BILLING_EXPORT_HEADERS.index(header)]


class TestTheFileTheCustomerAskedFor:
    def test_the_head_is_the_five_line_block_then_the_twenty_four_columns(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN, import_active_kwh_total=100.0)

        export_device_billing(device_id, require_auto_save=True)

        rows = read_rows(tmp_path / "SN-1-billing.csv")
        assert rows[0] == ["Customer :", "TFTECH"]
        assert rows[1] == ["Site Name :", "Plant A"]
        assert rows[2] == ["Serial Meter :", "SN-1"]
        assert rows[3] == ["Setting :", "1"]
        assert rows[4] == ["Billing :", ""]
        assert rows[5] == list(BILLING_EXPORT_HEADERS)
        assert len(rows[5]) == 24

    def test_a_device_with_no_customer_still_gets_the_line(self, migrated_db: Settings, tmp_path: Path) -> None:
        """Customer is a record-only field — empty is normal, not an error, and
        dropping the line would shift every line below it."""
        device_id = make_device(customer=None)
        configure(output_dir=tmp_path)
        seed(device_id, JAN, import_active_kwh_total=100.0)

        export_device_billing(device_id, require_auto_save=True)

        assert read_rows(tmp_path / "SN-1-billing.csv")[0] == ["Customer :", ""]

    def test_the_four_export_columns_are_present_and_cleanly_spelled(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        """Twenty-four columns always — the customer's own files spell these
        four different ways, and their other program can omit them entirely."""
        assert "Billing total Export kWh Total" in BILLING_EXPORT_HEADERS
        assert "Billing total Export kWh Rate A" in BILLING_EXPORT_HEADERS
        assert "Billing total Export kWh Rate B" in BILLING_EXPORT_HEADERS
        assert "Billing total Export kWh Rate C" in BILLING_EXPORT_HEADERS

        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN, export_active_kwh_total=12.5)

        export_device_billing(device_id, require_auto_save=True)

        assert cell(tmp_path / "SN-1-billing.csv", 0, "Billing total Export kWh Total") == "12.5"

    def test_there_is_no_rate_d_column(self, migrated_db: Settings, tmp_path: Path) -> None:
        """The customer's contract has three tariffs. Rate D is 0.0 on their own
        meter and NULL on every stored CEWE row."""
        assert not any("Rate D" in header for header in BILLING_EXPORT_HEADERS)


class TestOnlyClosedPeriodsReachTheFile:
    def test_the_open_period_is_never_written(self, migrated_db: Settings, tmp_path: Path) -> None:
        """Its Bill Date advances on every read (ADR 0018), so a file that
        appends would gain the same period again on every cycle under a date
        that had moved."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN, import_active_kwh_total=100.0)
        seed(device_id, JAN + timedelta(days=31), status="open", import_active_kwh_total=200.0)

        export_device_billing(device_id, require_auto_save=True)

        rows = data_rows(tmp_path / "SN-1-billing.csv")
        assert len(rows) == 1
        assert cell(tmp_path / "SN-1-billing.csv", 0, "111 Billing total kWh Total") == "100"

    def test_a_device_holding_only_an_open_period_writes_no_file(self, migrated_db: Settings, tmp_path: Path) -> None:
        """The customer's own machine is in exactly this state today."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN, status="open", import_active_kwh_total=100.0)

        result = export_device_billing(device_id, require_auto_save=True)

        assert result.rows_written == 0
        assert not (tmp_path / "SN-1-billing.csv").exists()

    def test_record_status_reads_closed_on_every_row(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN, import_active_kwh_total=100.0)

        export_device_billing(device_id, require_auto_save=True)

        assert cell(tmp_path / "SN-1-billing.csv", 0, "Record Status") == "closed"


class TestRecordNoCountsFromTheOldestPeriod:
    def test_it_numbers_the_series_not_the_file(self, migrated_db: Settings, tmp_path: Path) -> None:
        """The second export continues the numbering rather than restarting at
        1 — the ordinal is a property of the data, so it survives both an
        incremental append and a whole-file rewrite."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN, import_active_kwh_total=100.0)
        seed(device_id, JAN + timedelta(days=31), import_active_kwh_total=200.0)
        export_device_billing(device_id, require_auto_save=True)

        seed(device_id, JAN + timedelta(days=62), import_active_kwh_total=300.0)
        export_device_billing(device_id, require_auto_save=True)

        path = tmp_path / "SN-1-billing.csv"
        assert [row[0] for row in data_rows(path)] == ["1", "2", "3"]

    def test_the_oldest_period_is_one(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN + timedelta(days=31), import_active_kwh_total=200.0)
        seed(device_id, JAN, import_active_kwh_total=100.0)

        export_device_billing(device_id, require_auto_save=True)

        path = tmp_path / "SN-1-billing.csv"
        assert cell(path, 0, "Record No") == "1"
        assert cell(path, 0, "111 Billing total kWh Total") == "100"


class TestTimestampCellsTellNeverApartFromAReading:
    def test_a_null_demand_time_reads_as_a_dash(self, migrated_db: Settings, tmp_path: Path) -> None:
        """What a CEWE stores for a tariff whose demand was never recorded."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN, max_demand_import_active_time_rate_a=None)

        export_device_billing(device_id, require_auto_save=True)

        assert cell(tmp_path / "SN-1-billing.csv", 0, "050T Previous Time of kW deman") == "-"

    def test_the_meter_epoch_sentinel_also_reads_as_a_dash(self, migrated_db: Settings, tmp_path: Path) -> None:
        """What a SMART TCC stores for the same thing. Left unfiltered it prints
        as a date a reader cannot tell from a real one — this assertion is the
        whole reason the sentinel rule exists."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN, max_demand_import_active_time_rate_a=TCC_NEVER)

        export_device_billing(device_id, require_auto_save=True)

        assert cell(tmp_path / "SN-1-billing.csv", 0, "050T Previous Time of kW deman") == "-"

    def test_a_real_demand_time_is_written_in_meter_local_time(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN, max_demand_import_active_time_rate_a=datetime(2026, 1, 13, 5, 45, tzinfo=UTC))

        export_device_billing(device_id, require_auto_save=True)

        # UTC +7 — the same conversion the Load Profile CSV applies.
        assert cell(tmp_path / "SN-1-billing.csv", 0, "050T Previous Time of kW deman") == "2026-01-13 12:45:00"

    def test_the_bill_date_uses_the_shared_date_format_setting(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path, date_format="dd/mm/yyyy HH:MM")
        seed(device_id, JAN, import_active_kwh_total=1.0)

        export_device_billing(device_id, require_auto_save=True)

        assert cell(tmp_path / "SN-1-billing.csv", 0, "Time") == "01/01/2026 07:00"


class TestNumbersLookLikeTheCustomersOwnFile:
    @pytest.mark.parametrize(
        ("stored", "expected"),
        [
            (9587.1515, "9587.1515"),
            (1133.8140, "1133.814"),
            (0.0, "0"),
            (100.0, "100"),
            (0.123456, "0.1235"),
        ],
    )
    def test_at_most_four_decimals_with_trailing_zeros_trimmed(
        self, migrated_db: Settings, tmp_path: Path, stored: float, expected: str
    ) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN, import_active_kwh_total=stored)

        export_device_billing(device_id, require_auto_save=True)

        assert cell(tmp_path / "SN-1-billing.csv", 0, "111 Billing total kWh Total") == expected

    def test_a_missing_value_is_empty_never_zero(self, migrated_db: Settings, tmp_path: Path) -> None:
        """A meter that does not report a register is not a meter reporting
        zero, and a file that says otherwise is lying about a measurement."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN, import_active_kwh_total=1.0, export_active_kwh_total=None)

        export_device_billing(device_id, require_auto_save=True)

        assert cell(tmp_path / "SN-1-billing.csv", 0, "Billing total Export kWh Total") == ""


class TestEveryCycleRewritesTheWholeFile:
    """ADR 0023 (ticket 04): rewritten whole every cycle, not appended — a
    second cycle over unchanged data must reproduce the same file rather
    than duplicating a row, since there is no watermark left to prevent it
    the old way."""

    def test_a_second_export_over_unchanged_data_does_not_duplicate_the_row(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN, import_active_kwh_total=100.0)

        export_device_billing(device_id, require_auto_save=True)
        second = export_device_billing(device_id, require_auto_save=True)

        assert second.rows_written == 1
        assert len(data_rows(tmp_path / "SN-1-billing.csv")) == 1

    def test_a_write_failure_writes_zero_rows(self, migrated_db: Settings, tmp_path: Path) -> None:
        """A write that cannot land must not be reported as having written
        anything — the caller has nothing to advance any more, but the
        result must still say so honestly."""
        device_id = make_device()
        outside = tmp_path / "outside"
        outside.mkdir()
        configure(output_dir=outside)
        seed(device_id, JAN, import_active_kwh_total=100.0)
        # A template that renders to a directory makes the open() fail.
        with session_scope() as session:
            set_setting(session, EXPORT_BILLING_FILENAME_TMPL_KEY, "sub")
        (outside / "sub").mkdir()

        result = export_device_billing(device_id, require_auto_save=True)

        assert result.rows_written == 0


class TestTheAutoSaveSwitch:
    def test_the_scheduler_path_holds_when_auto_save_is_off(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path, auto_save_enabled=False)
        seed(device_id, JAN, import_active_kwh_total=100.0)

        result = export_device_billing(device_id, require_auto_save=True)

        assert result.rows_written == 0
        assert not (tmp_path / "SN-1-billing.csv").exists()

    def test_save_now_ignores_it(self, migrated_db: Settings, tmp_path: Path) -> None:
        """Pressing a button already expresses intent — making an operator flip
        a *background* switch first would be a trap."""
        device_id = make_device()
        configure(output_dir=tmp_path, auto_save_enabled=False)
        seed(device_id, JAN, import_active_kwh_total=100.0)

        result = export_device_billing(device_id, require_auto_save=False)

        assert result.rows_written == 1


class TestADeviceWithNothingToNameItsFileHoldsQuietly:
    def test_no_meter_serial_writes_nothing(self, migrated_db: Settings, tmp_path: Path) -> None:
        """An undiscovered serial is the normal early state (ADR 0005)."""
        device_id = make_device(serial=None)
        configure(output_dir=tmp_path)
        seed(device_id, JAN, import_active_kwh_total=100.0)

        result = export_device_billing(device_id, require_auto_save=True)

        assert result.rows_written == 0
        assert list(tmp_path.glob("*.csv")) == []

    def test_an_unconfigured_output_dir_writes_nothing(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        with session_scope() as session:
            set_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, "true")
        seed(device_id, JAN, import_active_kwh_total=100.0)

        assert export_device_billing(device_id, require_auto_save=True).rows_written == 0


class TestAChangedHeadIsReflectedOnTheNextCycle:
    """A file that mirrors the whole series (ADR 0023, ticket 04) needs no
    special "head changed" branch any more — an edit to the device's own
    fields, like every other change, simply shows up rewritten in place,
    atomically, the next time the file is exported.

    Exercised here through the **file header block**, because the block carries
    values an operator can edit at any time. The column row is the other half of
    the same head and rewrites through the same code path.
    """

    def test_renaming_the_site_rewrites_the_one_file_under_the_new_head(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        device_id = make_device(site_name="Plant A")
        configure(output_dir=tmp_path)
        seed(device_id, JAN, import_active_kwh_total=100.0)
        export_device_billing(device_id, require_auto_save=True)

        with session_scope() as session:
            session.get(Device, device_id).site_name = "Plant B"
        seed(device_id, JAN + timedelta(days=31), import_active_kwh_total=200.0)
        export_device_billing(device_id, require_auto_save=True)

        live = tmp_path / "SN-1-billing.csv"
        assert list(tmp_path.glob("SN-1-billing.*.csv")) == [], "no dated edition may ever be created"
        assert read_rows(live)[1] == ["Site Name :", "Plant B"]

    def test_every_closed_period_reaches_the_rewritten_file_under_the_new_head(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        """The behaviour a plain append cannot give: the period the first
        export already wrote *under the old head* must still be in the file
        after a rewrite — a rewrite reproduces the whole series, not just
        what a stale watermark still calls pending, which is also why
        `Record No` is unaffected: both periods keep the ordinal the whole
        series gives them."""
        device_id = make_device(site_name="Plant A")
        configure(output_dir=tmp_path)
        seed(device_id, JAN, import_active_kwh_total=100.0)
        export_device_billing(device_id, require_auto_save=True)

        with session_scope() as session:
            session.get(Device, device_id).site_name = "Plant B"
        seed(device_id, JAN + timedelta(days=31), import_active_kwh_total=200.0)
        export_device_billing(device_id, require_auto_save=True)

        rows = data_rows(tmp_path / "SN-1-billing.csv")
        assert [row[0] for row in rows] == ["1", "2"], "both periods must land under the new head"

    def test_repeated_head_changes_never_leave_a_dated_file_behind(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device(site_name="Plant A")
        configure(output_dir=tmp_path)
        seed(device_id, JAN, import_active_kwh_total=100.0)
        export_device_billing(device_id, require_auto_save=True)

        for index, site in enumerate(("Plant B", "Plant C"), start=1):
            with session_scope() as session:
                session.get(Device, device_id).site_name = site
            seed(device_id, JAN + timedelta(days=31 * index), import_active_kwh_total=200.0)
            export_device_billing(device_id, require_auto_save=True)

        assert list(tmp_path.glob("SN-1-billing.*.csv")) == []
        assert [row[0] for row in data_rows(tmp_path / "SN-1-billing.csv")] == ["1", "2", "3"]

    def test_a_period_removed_from_billing_readings_disappears_from_the_file(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        """The file mirrors `billing_readings`, not a history of what was once
        true — the whole reason a watermark is no longer needed. (In practice
        a closed period is never deleted, ADR 0009, but the export makes no
        such assumption: it always reproduces whatever is there now.)"""
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN, import_active_kwh_total=100.0)
        seed(device_id, JAN + timedelta(days=31), import_active_kwh_total=200.0)
        export_device_billing(device_id, require_auto_save=True)
        assert len(data_rows(tmp_path / "SN-1-billing.csv")) == 2

        with session_scope() as session:
            row = session.query(BillingReading).filter_by(device_id=device_id, bill_date=JAN).one()
            session.delete(row)
        export_device_billing(device_id, require_auto_save=True)

        written = [row[0] for row in data_rows(tmp_path / "SN-1-billing.csv")]
        assert len(written) == 1


class TestSaveBillingFileNowThroughTheApi:
    """The button an installer presses to prove the output folder is right,
    rather than waiting a whole cycle to find out — which is the failure issue
    017 shipped to a customer."""

    def test_an_unconfigured_output_dir_is_a_422_with_an_actionable_sentence(
        self, migrated_db: Settings, admin_client
    ) -> None:
        """The scheduler job no-ops quietly here. A person pressing a button
        must not get a silent "0 rows written" 200 instead of being told the
        destination was never set."""
        device_id = make_device()
        seed(device_id, JAN, import_active_kwh_total=100.0)

        response = admin_client.post(f"/api/billing/export?device_id={device_id}")

        assert response.status_code == 422, response.text
        assert "export_output_dir" in response.text

    def test_it_ignores_the_auto_save_switch(self, migrated_db: Settings, admin_client, tmp_path: Path) -> None:
        device_id = make_device()
        configure(output_dir=tmp_path, auto_save_enabled=False)
        seed(device_id, JAN, import_active_kwh_total=100.0)

        response = admin_client.post(f"/api/billing/export?device_id={device_id}")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["rows_written"] == 1

    def test_a_plain_user_may_press_it(self, migrated_db: Settings, user_client, tmp_path: Path) -> None:
        """Exporting stored device data is not an admin act — the same rule
        "Save CSV now" follows."""
        device_id = make_device()
        configure(output_dir=tmp_path)
        seed(device_id, JAN, import_active_kwh_total=100.0)

        assert user_client.post(f"/api/billing/export?device_id={device_id}").status_code == 200

    def test_an_unknown_device_is_404(self, migrated_db: Settings, admin_client, tmp_path: Path) -> None:
        configure(output_dir=tmp_path)

        assert admin_client.post("/api/billing/export?device_id=999").status_code == 404

    def test_an_anonymous_caller_is_refused(self, migrated_db: Settings, anon_client) -> None:
        assert anon_client.post("/api/billing/export?device_id=1").status_code == 401
