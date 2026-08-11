"""Holidays API (M7-1, issue #28) — CRUD, JSON export/import, and the
meter-import replace-the-whole-set path.
"""

from __future__ import annotations

import pytest
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


def add_device(client: TestClient, fake_meter: FakeMeterState, *, serial: str = "SN-1") -> int:
    fake_meter.meter_serial = serial
    response = client.post("/api/devices", json=DEVICE)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


class TestListIsOpenToAnyRole:
    def test_user_can_list(self, user_client: TestClient) -> None:
        response = user_client.get("/api/holidays")
        assert response.status_code == 200, response.text
        assert response.json()["data"] == []


class TestCreateIsAdminOnly:
    def test_user_cannot_create(self, user_client: TestClient) -> None:
        response = user_client.post("/api/holidays", json={"kind": "annual", "name": "New Year", "month": 1, "day": 1})
        assert response.status_code == 403

    def test_admin_can_create_annual(self, admin_client: TestClient) -> None:
        response = admin_client.post("/api/holidays", json={"kind": "annual", "name": "New Year", "month": 1, "day": 1})
        assert response.status_code == 201, response.text
        body = response.json()["data"]
        assert body["kind"] == "annual"
        assert body["month"] == 1
        assert body["day"] == 1
        assert body["date"] is None

    def test_admin_can_create_public(self, admin_client: TestClient) -> None:
        response = admin_client.post(
            "/api/holidays", json={"kind": "public", "name": "Makha Bucha", "date": "2026-02-12"}
        )
        assert response.status_code == 201, response.text
        body = response.json()["data"]
        assert body["kind"] == "public"
        assert body["date"] == "2026-02-12"
        assert body["month"] is None


class Test29FebRefusal:
    def test_29_february_annual_is_refused_on_create(self, admin_client: TestClient) -> None:
        response = admin_client.post("/api/holidays", json={"kind": "annual", "name": "Leap", "month": 2, "day": 29})
        assert response.status_code == 422

    def test_29_february_public_in_a_leap_year_is_fine(self, admin_client: TestClient) -> None:
        response = admin_client.post("/api/holidays", json={"kind": "public", "name": "Leap Day", "date": "2028-02-29"})
        assert response.status_code == 201, response.text


class TestShapeValidation:
    def test_annual_with_a_date_is_refused(self, admin_client: TestClient) -> None:
        response = admin_client.post(
            "/api/holidays", json={"kind": "annual", "name": "Bad", "month": 1, "day": 1, "date": "2026-01-01"}
        )
        assert response.status_code == 422

    def test_public_without_a_date_is_refused(self, admin_client: TestClient) -> None:
        response = admin_client.post("/api/holidays", json={"kind": "public", "name": "Bad"})
        assert response.status_code == 422

    def test_public_with_extraneous_month_day_is_refused(self, admin_client: TestClient) -> None:
        """The symmetric partner of `test_annual_with_a_date_is_refused` —
        `_validate_holiday_shape`'s public branch had no test pinning its
        own `month is not None or day is not None` check."""
        response = admin_client.post(
            "/api/holidays", json={"kind": "public", "name": "Bad", "date": "2026-01-01", "month": 1, "day": 1}
        )
        assert response.status_code == 422


class TestUniqueCollision:
    def test_two_public_holidays_on_the_same_date_is_422_never_500(self, admin_client: TestClient) -> None:
        first = admin_client.post("/api/holidays", json={"kind": "public", "name": "A", "date": "2026-01-01"})
        assert first.status_code == 201

        second = admin_client.post("/api/holidays", json={"kind": "public", "name": "B", "date": "2026-01-01"})
        assert second.status_code == 422


class TestDelete:
    def test_admin_can_delete(self, admin_client: TestClient) -> None:
        created = admin_client.post(
            "/api/holidays", json={"kind": "annual", "name": "New Year", "month": 1, "day": 1}
        ).json()["data"]

        response = admin_client.delete(f"/api/holidays/{created['id']}")
        assert response.status_code == 200

        listing = admin_client.get("/api/holidays").json()["data"]
        assert listing == []


class TestExportImportRoundTrip:
    def test_export_then_import_reproduces_the_same_set(self, admin_client: TestClient) -> None:
        admin_client.post("/api/holidays", json={"kind": "annual", "name": "New Year", "month": 1, "day": 1})
        admin_client.post("/api/holidays", json={"kind": "public", "name": "Makha Bucha", "date": "2026-02-12"})

        exported = admin_client.get("/api/holidays/export")
        assert exported.status_code == 200, exported.text
        document = exported.json()["data"]
        assert document["version"] == 1
        assert len(document["holidays"]) == 2

        imported = admin_client.post("/api/holidays/import", json=document)
        assert imported.status_code == 200, imported.text
        assert len(imported.json()["data"]) == 2

        listing = admin_client.get("/api/holidays").json()["data"]
        assert len(listing) == 2

    def test_import_replaces_the_whole_set(self, admin_client: TestClient) -> None:
        admin_client.post("/api/holidays", json={"kind": "annual", "name": "Old", "month": 5, "day": 5})

        document = {"version": 1, "holidays": [{"kind": "annual", "name": "New Year", "month": 1, "day": 1}]}
        response = admin_client.post("/api/holidays/import", json=document)
        assert response.status_code == 200, response.text

        listing = admin_client.get("/api/holidays").json()["data"]
        assert len(listing) == 1
        assert listing[0]["name"] == "New Year"

    def test_import_user_cannot(self, user_client: TestClient) -> None:
        document = {"version": 1, "holidays": []}
        response = user_client.post("/api/holidays/import", json=document)
        assert response.status_code == 403

    def test_import_with_a_duplicate_key_refuses_the_whole_document(self, admin_client: TestClient) -> None:
        document = {
            "version": 1,
            "holidays": [
                {"kind": "public", "name": "A", "date": "2026-01-01"},
                {"kind": "public", "name": "B", "date": "2026-01-01"},
            ],
        }
        response = admin_client.post("/api/holidays/import", json=document)
        assert response.status_code == 422

        # Refused wholesale — nothing was written.
        listing = admin_client.get("/api/holidays").json()["data"]
        assert listing == []

    def test_import_with_29_february_annual_is_refused(self, admin_client: TestClient) -> None:
        document = {"version": 1, "holidays": [{"kind": "annual", "name": "Bad", "month": 2, "day": 29}]}
        response = admin_client.post("/api/holidays/import", json=document)
        assert response.status_code == 422


class TestImportFromMeter:
    def test_replaces_the_whole_set_and_deduplicates(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        from arichds.acquisition.drivers.base import SpecialDayEntry

        device_id = add_device(admin_client, fake_meter)
        admin_client.post("/api/holidays", json={"kind": "annual", "name": "Old", "month": 5, "day": 5})

        fake_meter.special_days_entries = [
            SpecialDayEntry(index=1, day_id=7, year=None, month=1, day=1),
            SpecialDayEntry(index=2, day_id=7, year=None, month=1, day=1),  # duplicate key -> skipped
            SpecialDayEntry(index=3, day_id=9, year=2026, month=3, day=3),
        ]

        response = admin_client.post(f"/api/holidays/import-from-meter?device_id={device_id}")
        assert response.status_code == 200, response.text
        body = response.json()["data"]
        assert body["skipped"] == 1
        assert len(body["imported"]) == 2
        assert {row["name"] for row in body["imported"]} == {"Meter day ID 7", "Meter day ID 9"}

        listing = admin_client.get("/api/holidays").json()["data"]
        assert len(listing) == 2  # "Old" is gone — replace-the-whole-set

    def test_a_29_february_annual_entry_refuses_the_whole_import(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        from arichds.acquisition.drivers.base import SpecialDayEntry

        device_id = add_device(admin_client, fake_meter)
        admin_client.post("/api/holidays", json={"kind": "annual", "name": "Kept", "month": 5, "day": 5})
        fake_meter.special_days_entries = [SpecialDayEntry(index=1, day_id=1, year=None, month=2, day=29)]

        response = admin_client.post(f"/api/holidays/import-from-meter?device_id={device_id}")
        assert response.status_code == 422

        listing = admin_client.get("/api/holidays").json()["data"]
        assert len(listing) == 1
        assert listing[0]["name"] == "Kept"  # untouched — the whole import was refused

    def test_a_device_with_no_special_days_table_is_404(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.meter_serial = "SN-2"
        response = admin_client.post(
            "/api/devices",
            json={**DEVICE, "brand": "cewe", "model": "prometer100"},
        )
        assert response.status_code == 201, response.text
        device_id = response.json()["data"]["id"]

        result = admin_client.post(f"/api/holidays/import-from-meter?device_id={device_id}")
        assert result.status_code == 404

    def test_user_cannot_import_from_meter(
        self, user_client: TestClient, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        response = user_client.post(f"/api/holidays/import-from-meter?device_id={device_id}")
        assert response.status_code == 403

    def test_an_unknown_device_is_404_not_500(self, admin_client: TestClient) -> None:
        """Error-path audit finding: the job function raises `ValueError`
        for a missing device, which the router must translate to 404 —
        never let propagate into an unhandled 500."""
        response = admin_client.post("/api/holidays/import-from-meter?device_id=999")
        assert response.status_code == 404
