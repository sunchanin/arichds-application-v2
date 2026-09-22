"""``GET /api/billing/capture-classic/{device_id}`` — the Classic capture's
view model (ADR 0028, capture-style ticket 01).

Everything the Classic page draws, already formatted: the capture folder with
``/`` separators, the device's real group, ``<BRAND>`` and Meter Serial, a
Statistics Summary counted from the Poller's stored status over the devices
sharing that group, and the ten most recent closed periods **oldest first,
then by Billing Sequence** — exactly the window ``_png_source_rows`` selects
for the anchor, reversed. Every rule below is written as the mutation it
would catch (two devices per status, a thirteen-row seed with a same-second
pair), never as a scenario that passes on a one-row table.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("fake_meter")

#: 2026-01-21 00:00 local (+07:00) — the bill date ARICHDS Meter prints as
#: ``1/21/2026 00:00``.
NEWEST_BILL_DATE = datetime(2026, 1, 20, 17, 0, 0, tzinfo=UTC)
SERIAL = "WP081200"


def add_device(
    *,
    name: str,
    group_name: str | None,
    status: str = "unknown",
    enabled: bool = True,
    meter_serial: str | None = None,
    brand: str = "cewe",
) -> int:
    """Insert a device the way the Poller would have left it — ``status`` is
    the stored column ``acquisition/status.py`` writes; ``enabled=False`` is
    Pause (CONTEXT.md)."""
    from arichds.db.models import Device
    from arichds.db.session import session_scope

    with session_scope() as session:
        device = Device(
            name=name,
            brand=brand,
            model="prometer100",
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="",
            meter_serial=meter_serial,
            group_name=group_name,
            enabled=enabled,
            status=status,
        )
        session.add(device)
        session.flush()
        return device.id


def add_closed(device_id: int, bill_date: datetime, *, sequence: int = 0, **values: object) -> int:
    from arichds.db.models import BillingReading
    from arichds.db.session import session_scope

    with session_scope() as session:
        row = BillingReading(
            device_id=device_id,
            bill_date=bill_date,
            sequence=sequence,
            read_at=bill_date,
            record_status=None,
            source="dlms",
            meter_serial=SERIAL,
            **values,
        )
        session.add(row)
        session.flush()
        return row.id


def add_open(device_id: int, bill_date: datetime) -> int:
    from arichds.db.models import BillingReading
    from arichds.db.session import session_scope

    with session_scope() as session:
        row = BillingReading(
            device_id=device_id,
            bill_date=bill_date,
            read_at=bill_date,
            record_status="open",
            source="dlms",
            meter_serial=SERIAL,
        )
        session.add(row)
        session.flush()
        return row.id


def set_setting_raw(key: str, value: str) -> None:
    """Write a setting straight into the table — bypasses the PUT's path
    validation so a Windows path that does not exist on this machine can be
    the capture folder."""
    from arichds.db.app_settings import set_setting
    from arichds.db.session import session_scope

    with session_scope() as session:
        set_setting(session, key, value)


def configure_capture_dir(admin_client: TestClient, path: Path) -> None:
    response = admin_client.put("/api/billing/settings", json={"capture_dir": str(path)})
    assert response.status_code == 200, response.text


def fetch(client: TestClient, device_id: int, **params: object):
    return client.get(f"/api/billing/capture-classic/{device_id}", params=params)


def seed_thirteen_with_a_pair(device_id: int) -> dict[tuple[int, int], int]:
    """Thirteen closed periods a month apart, newest at :data:`NEWEST_BILL_DATE`;
    month-index 1 is a same-second pair (sequence 0 and 1). Returns
    ``{(month_index, sequence): id}``."""
    ids: dict[tuple[int, int], int] = {}
    for i in range(12):
        for sequence in (0, 1) if i == 1 else (0,):
            ids[(i, sequence)] = add_closed(
                device_id,
                NEWEST_BILL_DATE - timedelta(days=31 * i),
                sequence=sequence,
                import_active_kwh_total=1000.0 + i + sequence / 10,
            )
    return ids


class TestRowSelectionAndOrder:
    def test_rows_are_the_png_window_oldest_first_with_the_pairs_older_member_first(
        self, admin_client: TestClient, tmp_path: Path
    ) -> None:
        configure_capture_dir(admin_client, tmp_path)
        device_id = add_device(name="Main", group_name=None, meter_serial=SERIAL)
        ids = seed_thirteen_with_a_pair(device_id)
        add_open(device_id, NEWEST_BILL_DATE + timedelta(days=20))

        response = fetch(admin_client, device_id)

        assert response.status_code == 200, response.text
        rows = response.json()["data"]["rows"]
        # Ten of the thirteen: the pair counts twice, so month-indexes 9–11
        # fall out; the Open Period is never one of them.
        expected = [ids[(i, 0)] for i in range(8, 1, -1)] + [ids[(1, 1)], ids[(1, 0)], ids[(0, 0)]]
        assert [row["id"] for row in rows] == expected
        # A same-second pair is two rows with one Time.
        assert rows[7]["time"] == rows[8]["time"] == "12/21/2025 00:00"
        assert rows[9]["time"] == "1/21/2026 00:00"

    def test_reading_id_anchors_on_the_pairs_older_member_and_excludes_the_newer(
        self, admin_client: TestClient, tmp_path: Path
    ) -> None:
        configure_capture_dir(admin_client, tmp_path)
        device_id = add_device(name="Main", group_name=None, meter_serial=SERIAL)
        ids = seed_thirteen_with_a_pair(device_id)

        response = fetch(admin_client, device_id, reading_id=ids[(1, 1)])

        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()["data"]["rows"]] == [ids[(i, 0)] for i in range(10, 1, -1)] + [
            ids[(1, 1)]
        ]

    def test_a_reading_id_of_another_device_or_the_open_period_is_404(
        self, admin_client: TestClient, tmp_path: Path
    ) -> None:
        configure_capture_dir(admin_client, tmp_path)
        device_id = add_device(name="Main", group_name=None, meter_serial=SERIAL)
        other = add_device(name="Other", group_name=None, meter_serial="WP000001")
        add_closed(device_id, NEWEST_BILL_DATE)
        foreign = add_closed(other, NEWEST_BILL_DATE)
        open_id = add_open(device_id, NEWEST_BILL_DATE + timedelta(days=20))

        assert fetch(admin_client, device_id, reading_id=foreign).status_code == 404
        assert fetch(admin_client, device_id, reading_id=open_id).status_code == 404

    def test_a_device_with_no_closed_period_is_404(self, admin_client: TestClient, tmp_path: Path) -> None:
        configure_capture_dir(admin_client, tmp_path)
        device_id = add_device(name="Main", group_name=None, meter_serial=SERIAL)
        add_open(device_id, NEWEST_BILL_DATE)

        assert fetch(admin_client, device_id).status_code == 404

    def test_an_unknown_device_is_404(self, admin_client: TestClient, tmp_path: Path) -> None:
        configure_capture_dir(admin_client, tmp_path)
        assert fetch(admin_client, 9999).status_code == 404


class TestCellFormatting:
    """Confirmed 2026-09-22 from ARICHDS Meter's own ``billing.csv`` against
    its own image of WP081200 — Total kWh from ``import_active_kwh_*``, Prev
    kW Demand from ``max_demand_import_active_kw_rate_*``, Time of kW Demand
    A from ``max_demand_import_active_time_rate_a``."""

    def _one_row(self, admin_client: TestClient, tmp_path: Path, **values: object) -> dict[str, object]:
        configure_capture_dir(admin_client, tmp_path)
        device_id = add_device(name="Main", group_name=None, meter_serial=SERIAL)
        add_closed(device_id, NEWEST_BILL_DATE, **values)
        response = fetch(admin_client, device_id)
        assert response.status_code == 200, response.text
        (row,) = response.json()["data"]["rows"]
        return row

    def test_four_decimals_with_trailing_zeros_dropped(self, admin_client: TestClient, tmp_path: Path) -> None:
        row = self._one_row(
            admin_client,
            tmp_path,
            import_active_kwh_total=319840.2819,
            import_active_kwh_rate_a=100.302,
            import_active_kwh_rate_b=0.0,
            import_active_kwh_rate_c=9667.77931,
            max_demand_import_active_kw_rate_a=12.5,
            max_demand_import_active_kw_rate_b=1234.0,
        )

        assert row["total_kwh_total"] == "319840.2819"
        assert row["total_kwh_rate_a"] == "100.302"
        assert row["total_kwh_rate_b"] == "0"
        assert row["total_kwh_rate_c"] == "9667.7793"
        assert row["prev_kw_demand_rate_a"] == "12.5"
        assert row["prev_kw_demand_rate_b"] == "1234"

    def test_a_missing_value_is_an_empty_cell_never_zero(self, admin_client: TestClient, tmp_path: Path) -> None:
        row = self._one_row(
            admin_client, tmp_path, import_active_kwh_total=None, max_demand_import_active_kw_rate_a=None
        )

        assert row["total_kwh_total"] == ""
        assert row["prev_kw_demand_rate_a"] == ""
        assert row["time_of_kw_demand_a"] == ""

    def test_times_are_local_m_d_yyyy_hh_mm_without_leading_zeros(
        self, admin_client: TestClient, tmp_path: Path
    ) -> None:
        # 2026-01-10 12:30 local = 05:30 UTC.
        row = self._one_row(
            admin_client,
            tmp_path,
            max_demand_import_active_time_rate_a=datetime(2026, 1, 10, 5, 30, tzinfo=UTC),
        )

        assert row["time"] == "1/21/2026 00:00"
        assert row["time_of_kw_demand_a"] == "1/10/2026 12:30"

    def test_a_demand_time_at_the_meters_epoch_is_an_empty_cell(self, admin_client: TestClient, tmp_path: Path) -> None:
        # What TC's rows hold: 2000-01-01 00:00 local = 1999-12-31 17:00 UTC.
        row = self._one_row(
            admin_client,
            tmp_path,
            max_demand_import_active_time_rate_a=datetime(1999, 12, 31, 17, 0, tzinfo=UTC),
        )

        assert row["time_of_kw_demand_a"] == ""

    def test_name_is_brand_then_serial_in_parentheses(self, admin_client: TestClient, tmp_path: Path) -> None:
        row = self._one_row(admin_client, tmp_path)

        assert row["name"] == "CEWE (WP081200)"

    def test_the_display_unit_setting_never_reaches_the_cells(self, admin_client: TestClient, tmp_path: Path) -> None:
        from arichds.db.app_settings import DISPLAY_UNIT_SCALE_KEY

        set_setting_raw(DISPLAY_UNIT_SCALE_KEY, "base")

        row = self._one_row(
            admin_client,
            tmp_path,
            import_active_kwh_total=319840.2819,
            max_demand_import_active_kw_rate_a=12.5,
        )

        assert row["total_kwh_total"] == "319840.2819"
        assert row["prev_kw_demand_rate_a"] == "12.5"


class TestHeader:
    def test_save_path_uses_forward_slashes(self, admin_client: TestClient) -> None:
        from arichds.db.app_settings import CAPTURE_DIR_KEY

        set_setting_raw(CAPTURE_DIR_KEY, r"C:\CEWE DATA\Billing")
        device_id = add_device(name="Main", group_name="PWA Phase.2 Days1", meter_serial=SERIAL)
        add_closed(device_id, NEWEST_BILL_DATE)

        data = fetch(admin_client, device_id).json()["data"]

        assert data["save_path"] == "C:/CEWE DATA/Billing"
        assert data["group_name"] == "PWA Phase.2 Days1"
        assert data["brand"] == "CEWE"
        assert data["meter_serial"] == SERIAL

    def test_a_device_without_a_group_answers_null_not_an_invented_name(
        self, admin_client: TestClient, tmp_path: Path
    ) -> None:
        configure_capture_dir(admin_client, tmp_path)
        device_id = add_device(name="Main", group_name=None, meter_serial=SERIAL)
        add_closed(device_id, NEWEST_BILL_DATE)

        assert fetch(admin_client, device_id).json()["data"]["group_name"] is None

    def test_an_unconfigured_capture_folder_is_404(self, admin_client: TestClient) -> None:
        device_id = add_device(name="Main", group_name=None, meter_serial=SERIAL)
        add_closed(device_id, NEWEST_BILL_DATE)

        response = fetch(admin_client, device_id)

        assert response.status_code == 404, response.text


class TestStatisticsSummary:
    """Counted over the devices sharing the captured device's group from the
    Poller's stored status alone (ADR 0028): Paused not counted, Issues =
    Offline only, Unknown and Online counted but not issues, Complete =
    Total − Issues. Two devices per status so that a dropped filter moves a
    count by two, never by an amount another rule could hide."""

    def _seed_groups(self) -> None:
        for n in (1, 2):
            add_device(name=f"g1-online-{n}", group_name="G1", status="online")
            add_device(name=f"g1-offline-{n}", group_name="G1", status="offline")
            add_device(name=f"g1-unknown-{n}", group_name="G1", status="unknown")
            add_device(name=f"g1-paused-{n}", group_name="G1", status="online", enabled=False)
            add_device(name=f"g1-paused-offline-{n}", group_name="G1", status="offline", enabled=False)
            add_device(name=f"none-offline-{n}", group_name=None, status="offline")
            add_device(name=f"none-online-{n}", group_name=None, status="online")
            add_device(name=f"g2-offline-{n}", group_name="G2", status="offline")

    def test_a_named_group_counts_its_own_unpaused_devices_only(self, admin_client: TestClient, tmp_path: Path) -> None:
        configure_capture_dir(admin_client, tmp_path)
        self._seed_groups()
        device_id = add_device(name="Main", group_name="G1", meter_serial=SERIAL, status="online")
        add_closed(device_id, NEWEST_BILL_DATE)

        statistics = fetch(admin_client, device_id).json()["data"]["statistics"]

        # Main + 2 online + 2 offline + 2 unknown; the four paused are out.
        assert statistics == {"total": 7, "issues": 2, "complete": 5}

    def test_a_group_less_device_counts_with_the_other_group_less_devices(
        self, admin_client: TestClient, tmp_path: Path
    ) -> None:
        configure_capture_dir(admin_client, tmp_path)
        self._seed_groups()
        device_id = add_device(name="Main", group_name=None, meter_serial=SERIAL, status="unknown")
        add_closed(device_id, NEWEST_BILL_DATE)

        statistics = fetch(admin_client, device_id).json()["data"]["statistics"]

        # Main (unknown, counted, not an issue) + 2 offline + 2 online with no group.
        assert statistics == {"total": 5, "issues": 2, "complete": 3}

    def test_the_captured_device_itself_counts_as_an_issue_when_offline(
        self, admin_client: TestClient, tmp_path: Path
    ) -> None:
        configure_capture_dir(admin_client, tmp_path)
        self._seed_groups()
        device_id = add_device(name="Main", group_name="G2", meter_serial=SERIAL, status="offline")
        add_closed(device_id, NEWEST_BILL_DATE)

        statistics = fetch(admin_client, device_id).json()["data"]["statistics"]

        assert statistics == {"total": 3, "issues": 3, "complete": 0}

    def test_billing_rows_never_move_the_counts(self, admin_client: TestClient, tmp_path: Path) -> None:
        """The first meter of a group captured after a cut must not picture
        the others as broken (ADR 0028) — a device with no period at all is
        counted exactly as one with ten."""
        configure_capture_dir(admin_client, tmp_path)
        device_id = add_device(name="Main", group_name="G3", meter_serial=SERIAL, status="online")
        add_closed(device_id, NEWEST_BILL_DATE)
        for n in (1, 2):
            add_device(name=f"g3-online-no-bill-{n}", group_name="G3", status="online")

        statistics = fetch(admin_client, device_id).json()["data"]["statistics"]

        assert statistics == {"total": 3, "issues": 0, "complete": 3}


class TestAccessAndGates:
    def test_a_plain_user_may_read_it(self, admin_client: TestClient, user_client: TestClient, tmp_path: Path) -> None:
        configure_capture_dir(admin_client, tmp_path)
        device_id = add_device(name="Main", group_name=None, meter_serial=SERIAL)
        add_closed(device_id, NEWEST_BILL_DATE)

        assert fetch(user_client, device_id).status_code == 200

    def test_an_anonymous_caller_is_refused(self, anon_client: TestClient) -> None:
        assert fetch(anon_client, 1).status_code == 401

    def test_requires_billing_image_export(self, admin_client: TestClient, tmp_path: Path, relicense) -> None:
        configure_capture_dir(admin_client, tmp_path)
        device_id = add_device(name="Main", group_name=None, meter_serial=SERIAL)
        add_closed(device_id, NEWEST_BILL_DATE)

        relicense(admin_client, features=["billing"])  # no billing_image_export

        response = fetch(admin_client, device_id)

        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FEATURE_DISABLED"
        assert response.json()["error"]["reason"] == "billing_image_export"
