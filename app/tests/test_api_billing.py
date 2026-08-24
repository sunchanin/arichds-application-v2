"""Billing API — reading a device's stored Billing Readings (M6a, issue #21).

Mirrors ``test_api_load_profile.py``, with the differences SPEC §3.6 and this
issue's step 9 call for:

* **``status`` is required** — ``closed`` or ``open`` — the two Billing page
  tabs, keyed off ``record_status``.
* **``device_id`` and the date range are optional**, unlike Load Profile's
  mandatory range: billing is ~13 rows per device per year, so forcing a range
  would only hide data, not protect the browser from row volume.
* **Eight ``*_total`` columns only** — the 32 tariff columns are stored but not
  returned; a response carries exactly what the page renders.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import mint_meter_activation_code
from fakes import FakeMeterState
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("fake_meter")

DEVICE = {
    "name": "Main Incomer",
    "brand": "mitsu",
    "model": "smw110",
    "site_name": "Plant A",
    "transport": {"kind": "net", "host": "127.0.0.1", "port": 4059},
    "password": "hunter2",
}

BASE = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def add_device(client: TestClient, fake_meter: FakeMeterState, *, serial: str = "SN-1", **overrides: object) -> int:
    fake_meter.meter_serial = serial
    payload = {**DEVICE, **overrides}
    payload.setdefault("meter_activation_code", mint_meter_activation_code(meter_serial=serial))
    response = client.post("/api/devices", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def seed_closed(device_id: int, bill_date: datetime, meter_serial: str | None = "1232002893", **columns: float) -> None:
    from arichds.db.models import BillingReading
    from arichds.db.session import session_scope

    with session_scope() as session:
        session.add(
            BillingReading(
                device_id=device_id,
                bill_date=bill_date,
                read_at=bill_date,
                record_status=None,
                source="dlms",
                meter_serial=meter_serial,
                **columns,
            )
        )


def seed_open(device_id: int, bill_date: datetime, **columns: float) -> None:
    from arichds.db.models import BillingReading
    from arichds.db.session import session_scope

    with session_scope() as session:
        session.add(
            BillingReading(
                device_id=device_id,
                bill_date=bill_date,
                read_at=bill_date,
                record_status="open",
                source="dlms",
                meter_serial="1232002893",
                **columns,
            )
        )


def fetch(client: TestClient, status: str, **params: object):
    query = {"status": status, **params}
    return client.get("/api/billing", params=query)


class TestStatusTabs:
    def test_closed_status_never_returns_an_open_row(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, BASE)
        seed_open(device_id, BASE + timedelta(days=1))

        response = fetch(admin_client, "closed")

        assert response.status_code == 200, response.text
        items = response.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["bill_date"].startswith("2026-08-01")

    def test_open_status_never_returns_a_closed_row(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, BASE)
        seed_open(device_id, BASE + timedelta(days=1))

        response = fetch(admin_client, "open")

        assert response.status_code == 200, response.text
        items = response.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["bill_date"].startswith("2026-08-02")

    def test_an_invalid_status_is_422(self, admin_client: TestClient) -> None:
        assert fetch(admin_client, "pending").status_code == 422


class TestEmptyIsNotAnError:
    def test_a_device_with_no_periods_is_a_200_with_an_empty_page(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)

        response = fetch(admin_client, "closed", device_id=device_id)

        assert response.status_code == 200, response.text
        assert response.json()["data"] == {"items": [], "total": 0, "limit": 100, "offset": 0}


class TestDeviceIdAndRangeAreOptional:
    def test_omitting_device_id_returns_every_devices_rows(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        mine = add_device(admin_client, fake_meter, serial="SN-1")
        theirs = add_device(
            admin_client, fake_meter, serial="SN-2", name="Second", transport={**DEVICE["transport"], "port": 4060}
        )
        seed_closed(mine, BASE)
        seed_closed(theirs, BASE)

        response = fetch(admin_client, "closed")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["total"] == 2

    def test_omitting_the_range_returns_everything(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, BASE)
        seed_closed(device_id, BASE - timedelta(days=365))

        response = fetch(admin_client, "closed", device_id=device_id)

        assert response.json()["data"]["total"] == 2

    def test_an_unknown_device_id_is_404(self, admin_client: TestClient) -> None:
        assert fetch(admin_client, "closed", device_id=4242).status_code == 404


class TestRange:
    def test_the_range_is_half_open_on_bill_date(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, BASE)
        seed_closed(device_id, BASE + timedelta(days=30))

        response = fetch(
            admin_client,
            "closed",
            device_id=device_id,
            start=BASE.isoformat(),
            end=(BASE + timedelta(days=30)).isoformat(),
        )

        assert response.json()["data"]["total"] == 1

    def test_end_not_later_than_start_is_422(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)

        response = fetch(admin_client, "closed", device_id=device_id, start=BASE.isoformat(), end=BASE.isoformat())

        assert response.status_code == 422, response.text


class TestMeterSerialFilter:
    """Decision 7, issue #38 — an optional ``meter_serial`` filter, added so
    this endpoint agrees with ``capture/service.py``'s
    ``_png_source_rows()`` (which already filters on ``meter_serial``)
    unconditionally, rather than only for a device that has never had its
    meter swapped (ADR 0005 — identity comes from the meter)."""

    def test_meter_serial_restricts_to_that_serial_only(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, BASE, meter_serial="OLD-SERIAL")
        seed_closed(device_id, BASE + timedelta(days=30), meter_serial="NEW-SERIAL")

        response = fetch(admin_client, "closed", device_id=device_id, meter_serial="NEW-SERIAL")

        assert response.status_code == 200, response.text
        items = response.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["meter_serial"] == "NEW-SERIAL"

    def test_omitting_meter_serial_returns_every_serial(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, BASE, meter_serial="OLD-SERIAL")
        seed_closed(device_id, BASE + timedelta(days=30), meter_serial="NEW-SERIAL")

        response = fetch(admin_client, "closed", device_id=device_id)

        assert response.json()["data"]["total"] == 2

    def test_an_unknown_meter_serial_is_a_200_with_an_empty_page_not_a_404(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, BASE, meter_serial="OLD-SERIAL")

        response = fetch(admin_client, "closed", device_id=device_id, meter_serial="NO-SUCH-SERIAL")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["items"] == []


#: All sixty measurement column names (D19, M4c issue #24) — the API now
#: returns every ``BillingReading`` measurement, not just the eight totals.
_MEASUREMENT_PREFIXES_FLOAT = [
    "import_active_kwh",
    "export_active_kwh",
    "import_reactive_kvarh",
    "export_reactive_kvarh",
    "max_demand_import_active_kw",
    "max_demand_export_active_kw",
    "max_demand_import_reactive_kvar",
    "max_demand_export_reactive_kvar",
    "cumul_demand_import_active_kw",
    "cumul_demand_import_reactive_kvar",
]
_MEASUREMENT_PREFIXES_DATETIME = ["max_demand_import_active_time", "max_demand_import_reactive_time"]
_RATE_SUFFIXES = ["total", "rate_a", "rate_b", "rate_c", "rate_d"]
_ALL_MEASUREMENT_FIELDS = {
    f"{prefix}_{suffix}"
    for prefix in (*_MEASUREMENT_PREFIXES_FLOAT, *_MEASUREMENT_PREFIXES_DATETIME)
    for suffix in _RATE_SUFFIXES
}


class TestRowShape:
    def test_all_sixty_measurement_fields_are_present(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(
            device_id,
            BASE,
            import_active_kwh_total=200464.501,
            import_active_kwh_rate_a=1.0,  # a tariff column — now returned too (D19)
        )

        response = fetch(admin_client, "closed", device_id=device_id)

        row = response.json()["data"]["items"][0]
        assert set(row) >= _ALL_MEASUREMENT_FIELDS
        assert set(row) == _ALL_MEASUREMENT_FIELDS | {
            "id",  # M6b, issue #22 — the download-capture link needs the row's own id
            "device_id",
            "device_name",
            "bill_date",
            "read_at",
            "meter_serial",
        }
        assert row["import_active_kwh_total"] == pytest.approx(200464.501)
        assert row["import_active_kwh_rate_a"] == pytest.approx(1.0)
        assert row["device_name"] == "Main Incomer"
        assert row["meter_serial"] == "1232002893"

    def test_a_null_total_stays_null(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, BASE)  # no measurement columns supplied

        response = fetch(admin_client, "closed", device_id=device_id)

        row = response.json()["data"]["items"][0]
        assert row["max_demand_import_active_kw_total"] is None
        assert row["max_demand_import_active_time_total"] is None
        assert row["cumul_demand_import_active_kw_total"] is None

    def test_a_demand_time_column_is_returned_as_utc(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """D19 — the ten Demand Time fields are datetimes and must get the
        same UTC re-attachment ``bill_date``/``read_at`` already get, since
        SQLite hands every timestamp back naive."""
        from datetime import UTC as _UTC
        from datetime import datetime as _datetime

        device_id = add_device(admin_client, fake_meter)
        moment = _datetime(2026, 8, 5, 9, 12, 0, tzinfo=_UTC)
        seed_closed(device_id, BASE, max_demand_import_active_time_total=moment)

        response = fetch(admin_client, "closed", device_id=device_id)

        row = response.json()["data"]["items"][0]
        assert row["max_demand_import_active_time_total"] == "2026-08-05T09:12:00Z"


class TestOrdering:
    def test_newest_bill_date_first(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, BASE)
        seed_closed(device_id, BASE + timedelta(days=30))
        seed_closed(device_id, BASE - timedelta(days=30))

        response = fetch(admin_client, "closed", device_id=device_id)

        dates = [row["bill_date"] for row in response.json()["data"]["items"]]
        assert dates == sorted(dates, reverse=True)


class TestSingleRowPageMatchesTheOnePeriodCaptureFallback:
    """Code review round, problem 4 — `capture/service.py:write_png_capture`'s
    detached/unmapped-row fallback seeds a one-row capture request
    (`pageSize` now `len(rows) == 1`, decision from problem 1's fix). This
    proves the composition that makes that fallback still succeed rather
    than time out: `limit=1` bounded by `end=<anchor.bill_date + 1s>` for
    the anchor's own `device_id`/`meter_serial` returns **exactly** the
    anchor row, even with older closed periods for the same device/serial
    on record — not some other row, and not more than one."""

    def test_limit_one_with_the_anchors_own_end_bound_returns_only_the_anchor(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter, serial="SN-1")
        anchor_bill_date = BASE
        seed_closed(device_id, anchor_bill_date - timedelta(days=31))  # older — must NOT come back
        seed_closed(device_id, anchor_bill_date - timedelta(days=62))  # older — must NOT come back
        seed_closed(device_id, anchor_bill_date)  # the anchor itself

        anchor_end = (anchor_bill_date + timedelta(seconds=1)).isoformat()
        response = fetch(
            admin_client, "closed", device_id=device_id, meter_serial="1232002893", end=anchor_end, limit=1
        )

        assert response.status_code == 200, response.text
        items = response.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["bill_date"].startswith("2026-08-01")


class TestAccess:
    def test_an_anonymous_caller_is_refused(self, anon_client: TestClient) -> None:
        assert fetch(anon_client, "closed").status_code == 401

    def test_a_plain_user_may_read(
        self, user_client: TestClient, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, BASE)

        response = fetch(user_client, "closed", device_id=device_id)

        assert response.status_code == 200, response.text
        assert response.json()["data"]["total"] == 1
