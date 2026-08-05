"""Device + readings API, over an activated app, as an authenticated user.

M1's step 6 exit condition, re-pointed at M2-1's fixtures: the machine is
activated (Limited Mode is covered in ``test_license_roundtrip.py``) and the
caller carries a token (the 401 side is covered in ``test_auth_guard.py``).
What is left for this file is the device behaviour itself, plus the role
boundary: managing meters is admin-only, reading them is not.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

SIM_DEVICE = {
    "name": "Sim Meter",
    "brand": "SIM",
    "model": "sim",
    "host": "127.0.0.1",
    "port": 4059,
    "password": "hunter2",
}


class TestCreateDevice:
    def test_creates_and_returns_the_device(self, admin_client: TestClient) -> None:
        response = admin_client.post("/api/devices", json=SIM_DEVICE)

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["name"] == "Sim Meter"
        assert data["endpoint"] == "127.0.0.1:4059"
        assert data["enabled"] is True

    def test_never_returns_the_password(self, admin_client: TestClient) -> None:
        response = admin_client.post("/api/devices", json=SIM_DEVICE)
        assert "password" not in response.json()["data"]
        assert "hunter2" not in response.text

    def test_duplicate_name_is_409(self, admin_client: TestClient) -> None:
        admin_client.post("/api/devices", json=SIM_DEVICE)
        response = admin_client.post("/api/devices", json=SIM_DEVICE)
        assert response.status_code == 409

    def test_unknown_model_is_rejected(self, admin_client: TestClient) -> None:
        response = admin_client.post("/api/devices", json={**SIM_DEVICE, "model": "not-a-meter"})
        assert response.status_code == 422

    def test_invalid_port_is_rejected(self, admin_client: TestClient) -> None:
        response = admin_client.post("/api/devices", json={**SIM_DEVICE, "port": 0})
        assert response.status_code == 422


class TestListDevices:
    def test_empty_to_start(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/devices")
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_lists_created_devices(self, admin_client: TestClient) -> None:
        admin_client.post("/api/devices", json=SIM_DEVICE)
        admin_client.post("/api/devices", json={**SIM_DEVICE, "name": "Second", "port": 4060})

        data = admin_client.get("/api/devices").json()["data"]
        assert [d["name"] for d in data] == ["Sim Meter", "Second"]

    def test_supported_models_include_sim_and_prometer100(self, admin_client: TestClient) -> None:
        data = admin_client.get("/api/devices/models").json()["data"]
        assert "sim" in data
        assert "prometer100" in data


class TestDeleteDevice:
    def test_deletes(self, admin_client: TestClient) -> None:
        device_id = admin_client.post("/api/devices", json=SIM_DEVICE).json()["data"]["id"]

        assert admin_client.delete(f"/api/devices/{device_id}").status_code == 200
        assert admin_client.get("/api/devices").json()["data"] == []

    def test_unknown_id_is_404(self, admin_client: TestClient) -> None:
        assert admin_client.delete("/api/devices/999").status_code == 404


class TestLatestReading:
    def test_null_before_the_first_tick(self, admin_client: TestClient) -> None:
        device_id = admin_client.post("/api/devices", json=SIM_DEVICE).json()["data"]["id"]

        response = admin_client.get(f"/api/devices/{device_id}/readings/latest")

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["data"] is None

    def test_returns_the_newest_reading(self, admin_client: TestClient) -> None:
        import threading

        from arichds.acquisition.poller import EndpointLocks, poll_once
        from arichds.db.models import Device
        from arichds.db.session import session_scope

        device_id = admin_client.post("/api/devices", json=SIM_DEVICE).json()["data"]["id"]
        with session_scope() as session:
            device = session.get(Device, device_id)
            session.expunge(device)
        poll_once(device, EndpointLocks(), threading.Event())

        data = admin_client.get(f"/api/devices/{device_id}/readings/latest").json()["data"]

        assert data is not None
        assert data["device_id"] == device_id
        assert data["source"] == "sim"
        assert data["interval"] == "60s"
        assert 200 < data["volt_l1"] < 260
        assert 45 < data["freq"] < 55
        assert data["import_active_kwh"] > 0

    def test_unknown_device_is_404(self, admin_client: TestClient) -> None:
        assert admin_client.get("/api/devices/999/readings/latest").status_code == 404


class TestEnvelope:
    def test_every_response_uses_the_envelope(self, admin_client: TestClient) -> None:
        body = admin_client.get("/api/devices").json()
        assert set(body) == {"success", "data", "error"}
        assert body["success"] is True
        assert body["error"] is None


class TestRoleBoundary:
    """SPEC §3.2 — a ``user`` sees everything and changes nothing."""

    def test_a_user_cannot_create_a_device(self, user_client: TestClient) -> None:
        assert user_client.post("/api/devices", json=SIM_DEVICE).status_code == 403

    def test_a_user_cannot_delete_a_device(self, admin_client: TestClient, user_client: TestClient) -> None:
        device_id = admin_client.post("/api/devices", json=SIM_DEVICE).json()["data"]["id"]

        assert user_client.delete(f"/api/devices/{device_id}").status_code == 403
        assert len(admin_client.get("/api/devices").json()["data"]) == 1

    def test_a_user_can_list_devices(self, admin_client: TestClient, user_client: TestClient) -> None:
        admin_client.post("/api/devices", json=SIM_DEVICE)

        response = user_client.get("/api/devices")

        assert response.status_code == 200
        assert [d["name"] for d in response.json()["data"]] == ["Sim Meter"]

    def test_a_user_can_read_the_supported_models(self, user_client: TestClient) -> None:
        assert user_client.get("/api/devices/models").status_code == 200

    def test_a_user_can_read_the_latest_reading(self, admin_client: TestClient, user_client: TestClient) -> None:
        device_id = admin_client.post("/api/devices", json=SIM_DEVICE).json()["data"]["id"]

        assert user_client.get(f"/api/devices/{device_id}/readings/latest").status_code == 200

    def test_the_403_is_not_a_401(self, user_client: TestClient) -> None:
        """Authenticated-but-not-allowed is a different answer from unauthenticated."""
        response = user_client.post("/api/devices", json=SIM_DEVICE)

        assert response.status_code == 403
        assert "WWW-Authenticate" not in response.headers
