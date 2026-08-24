"""Battery API — reading a device's stored Battery Readings (M7-2, issue #29).

Mirrors ``test_api_energy.py``'s list-endpoint shape and
``test_api_billing.py``'s pagination/date-bound shape. **Read-only and
bounded from the first commit** (unlike `docs/issues/002-…`'s open ticket) —
there is no Read-now endpoint here (D5): the job that fills this table is
background-only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import mint_meter_activation_code
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("fake_meter")

DEVICE = {
    "name": "Main Incomer",
    "brand": "cewe",
    "model": "prometer100",
    "site_name": "Plant A",
    "transport": {"kind": "net", "host": "127.0.0.1", "port": 4059},
    "password": "hunter2",
}

BASE = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def add_device(client: TestClient, *, serial: str = "SN-1", **overrides: object) -> int:
    from fakes import fake_meter_state

    fake_meter_state().meter_serial = serial
    payload = {**DEVICE, **overrides}
    payload.setdefault("meter_activation_code", mint_meter_activation_code(meter_serial=serial))
    response = client.post("/api/devices", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def seed(device_id: int, read_at: datetime, status: str | None = "4321") -> None:
    from arichds.db.models import BatteryReading
    from arichds.db.session import session_scope

    with session_scope() as session:
        session.add(BatteryReading(device_id=device_id, read_at=read_at, status=status))


def fetch(client: TestClient, **params: object):
    return client.get("/api/battery", params=params)


class TestEmptyIsNotAnError:
    def test_a_device_with_no_readings_is_a_200_with_an_empty_page(self, admin_client: TestClient) -> None:
        add_device(admin_client)

        response = fetch(admin_client)

        assert response.status_code == 200, response.text
        body = response.json()["data"]
        assert body["items"] == []
        assert body["total"] == 0


class TestPagination:
    def test_total_is_the_unpaged_count(self, admin_client: TestClient) -> None:
        device_id = add_device(admin_client)
        for i in range(5):
            seed(device_id, BASE + timedelta(hours=i))

        response = fetch(admin_client, limit=2, offset=0)

        assert response.status_code == 200, response.text
        body = response.json()["data"]
        assert len(body["items"]) == 2
        assert body["total"] == 5
        assert body["limit"] == 2
        assert body["offset"] == 0

    def test_offset_skips_rows(self, admin_client: TestClient) -> None:
        device_id = add_device(admin_client)
        for i in range(3):
            seed(device_id, BASE + timedelta(hours=i), status=str(i))

        response = fetch(admin_client, limit=1, offset=1)

        assert response.status_code == 200, response.text
        items = response.json()["data"]["items"]
        assert len(items) == 1

    def test_newest_first(self, admin_client: TestClient) -> None:
        device_id = add_device(admin_client)
        seed(device_id, BASE, status="OLD")
        seed(device_id, BASE + timedelta(hours=1), status="NEW")

        response = fetch(admin_client)

        items = response.json()["data"]["items"]
        assert [row["status"] for row in items] == ["NEW", "OLD"]


class TestDeviceFilter:
    def test_restricts_to_one_device(self, admin_client: TestClient) -> None:
        device_a = add_device(admin_client, serial="SN-A", name="Meter A")
        device_b = add_device(admin_client, serial="SN-B", name="Meter B")
        seed(device_a, BASE, status="A")
        seed(device_b, BASE, status="B")

        response = fetch(admin_client, device_id=device_a)

        items = response.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["status"] == "A"
        assert items[0]["device_id"] == device_a

    def test_joins_device_name_and_meter_serial(self, admin_client: TestClient) -> None:
        device_id = add_device(admin_client, serial="SN-JOINED")
        seed(device_id, BASE, status="X")

        response = fetch(admin_client, device_id=device_id)

        item = response.json()["data"]["items"][0]
        assert item["device_name"] == "Main Incomer"
        assert item["meter_serial"] == "SN-JOINED"


class TestDateBounds:
    def test_start_is_inclusive(self, admin_client: TestClient) -> None:
        device_id = add_device(admin_client)
        seed(device_id, BASE, status="AT_START")

        response = fetch(admin_client, start=BASE.isoformat())

        items = response.json()["data"]["items"]
        assert any(row["status"] == "AT_START" for row in items)

    def test_end_is_exclusive(self, admin_client: TestClient) -> None:
        device_id = add_device(admin_client)
        seed(device_id, BASE, status="AT_END")

        response = fetch(admin_client, end=BASE.isoformat())

        items = response.json()["data"]["items"]
        assert all(row["status"] != "AT_END" for row in items)

    def test_a_row_before_end_is_included(self, admin_client: TestClient) -> None:
        device_id = add_device(admin_client)
        seed(device_id, BASE, status="BEFORE_END")

        response = fetch(admin_client, end=(BASE + timedelta(seconds=1)).isoformat())

        items = response.json()["data"]["items"]
        assert any(row["status"] == "BEFORE_END" for row in items)


class TestErrorPaths:
    def test_an_unknown_device_is_404(self, admin_client: TestClient) -> None:
        response = fetch(admin_client, device_id=999)

        assert response.status_code == 404, response.text

    def test_end_before_start_is_422(self, admin_client: TestClient) -> None:
        response = fetch(admin_client, start=(BASE + timedelta(hours=1)).isoformat(), end=BASE.isoformat())

        assert response.status_code == 422, response.text

    def test_a_page_size_over_five_hundred_is_422(self, admin_client: TestClient) -> None:
        """Bounded from the first commit — `docs/issues/002-…` is the open
        ticket for the one sibling endpoint that is not; this must not
        become the second."""
        response = fetch(admin_client, limit=501)

        assert response.status_code == 422, response.text


class TestFeatureGate:
    def test_403_when_battery_feature_is_off(self, admin_client: TestClient, relicense) -> None:
        relicense(admin_client, features=[])

        response = fetch(admin_client)

        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FEATURE_DISABLED"
        assert response.json()["error"]["reason"] == "battery"


class TestAuth:
    def test_an_anonymous_caller_is_refused(self, anon_client: TestClient) -> None:
        assert fetch(anon_client).status_code == 401

    def test_a_user_role_can_read(self, admin_client: TestClient, user_client: TestClient) -> None:
        add_device(admin_client)

        response = fetch(user_client)

        assert response.status_code == 200, response.text

    def test_an_admin_role_can_read(self, admin_client: TestClient) -> None:
        add_device(admin_client)

        response = fetch(admin_client)

        assert response.status_code == 200, response.text
