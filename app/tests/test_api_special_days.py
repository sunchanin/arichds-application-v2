"""Special Days API (M7-1, issue #28) — read-through, stores nothing."""

from __future__ import annotations

import pytest
from conftest import mint_meter_activation_code
from fakes import FakeMeterState
from fastapi.testclient import TestClient

from arichds.acquisition.drivers.base import SpecialDayEntry

pytestmark = pytest.mark.usefixtures("fake_meter")

DEVICE = {
    "name": "Main Incomer",
    "brand": "mitsu",
    "model": "smw110",
    "site_name": "Plant A",
    "transport": {"kind": "net", "host": "127.0.0.1", "port": 4059},
    "password": "hunter2",
}


def add_device(client: TestClient, fake_meter: FakeMeterState, *, serial: str = "SN-1", **overrides: object) -> int:
    fake_meter.meter_serial = serial
    payload = {**DEVICE, **overrides}
    payload.setdefault("meter_activation_code", mint_meter_activation_code(meter_serial=serial))
    response = client.post("/api/devices", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


class TestReadThrough:
    def test_returns_the_meters_entries(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)
        fake_meter.special_days_entries = [
            SpecialDayEntry(index=1, day_id=7, year=None, month=4, day=13),
            SpecialDayEntry(index=2, day_id=9, year=2026, month=3, day=3),
        ]

        response = admin_client.get(f"/api/special-days?device_id={device_id}")
        assert response.status_code == 200, response.text
        body = response.json()["data"]
        assert body["error"] is None
        entries = body["entries"]
        assert len(entries) == 2
        assert entries[0]["kind"] == "annual"
        assert entries[0]["year"] is None
        assert entries[1]["kind"] == "public"
        assert entries[1]["year"] == 2026

    def test_a_user_role_can_read_too(
        self, user_client: TestClient, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        response = user_client.get(f"/api/special-days?device_id={device_id}")
        assert response.status_code == 200, response.text

    def test_nothing_is_stored_by_reading(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)
        fake_meter.special_days_entries = [SpecialDayEntry(index=1, day_id=1, year=None, month=1, day=1)]

        admin_client.get(f"/api/special-days?device_id={device_id}")

        holidays = admin_client.get("/api/holidays").json()["data"]
        assert holidays == []


class TestUnsupportedDevice:
    def test_a_cewe_model_is_404(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter, brand="cewe", model="prometer100")
        response = admin_client.get(f"/api/special-days?device_id={device_id}")
        assert response.status_code == 404


class TestErrorPaths:
    def test_an_unknown_device_is_404_not_500(self, admin_client: TestClient) -> None:
        """Error-path audit finding: the job function raises `ValueError`
        for a missing device, which the router must translate to 404 —
        never let propagate into an unhandled 500."""
        response = admin_client.get("/api/special-days?device_id=999")
        assert response.status_code == 404

    def test_a_connect_failure_comes_back_as_a_payload_error_not_an_http_error(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        fake_meter.connect_error = ConnectionError("boom")

        response = admin_client.get(f"/api/special-days?device_id={device_id}")
        assert response.status_code == 200, response.text
        body = response.json()["data"]
        assert body["entries"] == []
        assert body["error"] is not None
