"""Device + readings API, over an activated app.

Step 6's exit condition. The client fixture activates the machine first, since
every route here is behind the Limited Mode gate (that gate is covered in
``test_license_roundtrip.py``).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from fastapi.testclient import TestClient

from arichds.config import Settings
from arichds.licensing import activation_code as ac

TEST_MACHINE_ID = "e" * 64

SIM_DEVICE = {
    "name": "Sim Meter",
    "brand": "SIM",
    "model": "sim",
    "host": "127.0.0.1",
    "port": 4059,
    "password": "hunter2",
}


@pytest.fixture
def activated_client(
    migrated_db: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, vendor_cli
) -> Iterator[TestClient]:
    """A TestClient over a running, activated app, with the Poller switched off.

    These tests are about the HTTP surface. Letting background workers write
    rows underneath them would make every assertion about reading counts race
    the clock — so the Poller's master switch is off and the tests that need a
    reading call ``poll_once`` explicitly.
    """
    monkeypatch.setenv("ARICHDS_POLL_ENABLED", "false")
    from arichds.config import get_settings

    get_settings.cache_clear()

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(ac, "load_public_key_pem", lambda: public_pem)
    monkeypatch.setattr("arichds.licensing.service.machine_id", lambda: TEST_MACHINE_ID)

    from arichds.main import create_app

    payload = vendor_cli.build_payload(customer="Acme Co", machine_id=TEST_MACHINE_ID)
    code = vendor_cli.sign_payload(private_pem, payload)

    app = create_app()
    with TestClient(app) as client:
        assert client.post("/api/license/activate", json={"code": code}).json()["success"] is True
        yield client


class TestCreateDevice:
    def test_creates_and_returns_the_device(self, activated_client: TestClient) -> None:
        response = activated_client.post("/api/devices", json=SIM_DEVICE)

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["name"] == "Sim Meter"
        assert data["endpoint"] == "127.0.0.1:4059"
        assert data["enabled"] is True

    def test_never_returns_the_password(self, activated_client: TestClient) -> None:
        response = activated_client.post("/api/devices", json=SIM_DEVICE)
        assert "password" not in response.json()["data"]
        assert "hunter2" not in response.text

    def test_duplicate_name_is_409(self, activated_client: TestClient) -> None:
        activated_client.post("/api/devices", json=SIM_DEVICE)
        response = activated_client.post("/api/devices", json=SIM_DEVICE)
        assert response.status_code == 409

    def test_unknown_model_is_rejected(self, activated_client: TestClient) -> None:
        response = activated_client.post("/api/devices", json={**SIM_DEVICE, "model": "not-a-meter"})
        assert response.status_code == 422

    def test_invalid_port_is_rejected(self, activated_client: TestClient) -> None:
        response = activated_client.post("/api/devices", json={**SIM_DEVICE, "port": 0})
        assert response.status_code == 422


class TestListDevices:
    def test_empty_to_start(self, activated_client: TestClient) -> None:
        response = activated_client.get("/api/devices")
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_lists_created_devices(self, activated_client: TestClient) -> None:
        activated_client.post("/api/devices", json=SIM_DEVICE)
        activated_client.post("/api/devices", json={**SIM_DEVICE, "name": "Second", "port": 4060})

        data = activated_client.get("/api/devices").json()["data"]
        assert [d["name"] for d in data] == ["Sim Meter", "Second"]

    def test_supported_models_include_sim_and_prometer100(self, activated_client: TestClient) -> None:
        data = activated_client.get("/api/devices/models").json()["data"]
        assert "sim" in data
        assert "prometer100" in data


class TestDeleteDevice:
    def test_deletes(self, activated_client: TestClient) -> None:
        device_id = activated_client.post("/api/devices", json=SIM_DEVICE).json()["data"]["id"]

        assert activated_client.delete(f"/api/devices/{device_id}").status_code == 200
        assert activated_client.get("/api/devices").json()["data"] == []

    def test_unknown_id_is_404(self, activated_client: TestClient) -> None:
        assert activated_client.delete("/api/devices/999").status_code == 404


class TestLatestReading:
    def test_null_before_the_first_tick(self, activated_client: TestClient) -> None:
        device_id = activated_client.post("/api/devices", json=SIM_DEVICE).json()["data"]["id"]

        response = activated_client.get(f"/api/devices/{device_id}/readings/latest")

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["data"] is None

    def test_returns_the_newest_reading(self, activated_client: TestClient) -> None:
        import threading

        from arichds.acquisition.poller import EndpointLocks, poll_once
        from arichds.db.models import Device
        from arichds.db.session import session_scope

        device_id = activated_client.post("/api/devices", json=SIM_DEVICE).json()["data"]["id"]
        with session_scope() as session:
            device = session.get(Device, device_id)
            session.expunge(device)
        poll_once(device, EndpointLocks(), threading.Event())

        data = activated_client.get(f"/api/devices/{device_id}/readings/latest").json()["data"]

        assert data is not None
        assert data["device_id"] == device_id
        assert data["source"] == "sim"
        assert data["interval"] == "60s"
        assert 200 < data["volt_l1"] < 260
        assert 45 < data["freq"] < 55
        assert data["import_active_kwh"] > 0

    def test_unknown_device_is_404(self, activated_client: TestClient) -> None:
        assert activated_client.get("/api/devices/999/readings/latest").status_code == 404


class TestEnvelope:
    def test_every_response_uses_the_envelope(self, activated_client: TestClient) -> None:
        body = activated_client.get("/api/devices").json()
        assert set(body) == {"success", "data", "error"}
        assert body["success"] is True
        assert body["error"] is None
