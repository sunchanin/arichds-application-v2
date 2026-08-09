"""Golden roundtrip: vendor CLI signs → the app activates. No restart.

This is the test that proves M1's licensing exit criteria end to end:

* a code produced by the real ``tools/arichds_vendor.py`` activates the app;
* a code for another machine, or a tampered one, is refused;
* ``/api/*`` answers 403 ``LICENSE_INVALID`` in Limited Mode and 200 afterwards
  **on the same running app object** — the ADR 0001 requirement, and the thing
  v1 could not do.

The machine fingerprint is monkeypatched so the test signs for a known Machine
ID rather than whatever box CI happens to run on.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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
from arichds.constants import ERROR_LICENSE_INVALID
from arichds.licensing import activation_code as ac
from arichds.licensing.service import LicenseService
from tests.conftest import ADMIN_CREDENTIALS, login_token

TEST_MACHINE_ID = "c" * 64
OTHER_MACHINE_ID = "d" * 64


@pytest.fixture
def vendor_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Generate a throwaway vendor keypair and make the app trust it.

    The app normally verifies against the public key bundled in the package;
    pointing it at the test key keeps the real one out of the test's way.
    """
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    private_path = tmp_path / "vendor_private.pem"
    private_path.write_bytes(private_pem)
    monkeypatch.setattr(ac, "load_public_key_pem", lambda: public_pem)
    return private_path


@pytest.fixture
def this_machine(monkeypatch: pytest.MonkeyPatch) -> str:
    """Pin the Machine ID this process reports."""
    monkeypatch.setattr("arichds.licensing.service.machine_id", lambda: TEST_MACHINE_ID)
    return TEST_MACHINE_ID


def issue_code(vendor_cli, private_path: Path, *, machine_id: str, customer: str = "Acme Co", **kwargs) -> str:
    """Sign an Activation Code using the real vendor CLI module."""
    payload = vendor_cli.build_payload(customer=customer, machine_id=machine_id, **kwargs)
    return vendor_cli.sign_payload(private_path.read_bytes(), payload)


class TestIssuerVerifierAgreement:
    """The duplicated canonical rule must stay byte-identical on both sides."""

    def test_canonical_bytes_match(self, vendor_cli) -> None:
        payload = {"b": 2, "a": 1, "z": None}
        assert vendor_cli.canonical_payload_bytes(payload) == ac.canonical_payload_bytes(payload)

    def test_payload_shapes_match(self, vendor_cli) -> None:
        cli = vendor_cli.build_payload(customer="X", machine_id=TEST_MACHINE_ID)
        app_side = ac.build_payload(customer="X", machine_id=TEST_MACHINE_ID)
        assert set(cli) == set(app_side)
        assert cli["v"] == app_side["v"] == ac.PAYLOAD_VERSION
        assert cli["product"] == app_side["product"] == ac.PRODUCT

    def test_cli_signed_code_verifies_in_the_app(self, vendor_cli, vendor_keys: Path) -> None:
        code = issue_code(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID)
        result = ac.verify_activation_code(code, machine_id=TEST_MACHINE_ID)
        assert result.valid
        assert result.customer == "Acme Co"


class TestLicenseService:
    def test_starts_in_limited_mode_with_no_license(
        self, settings: Settings, this_machine: str, vendor_keys: Path
    ) -> None:
        service = LicenseService(settings.license_path)
        state = service.current_state()
        assert not state.valid
        assert state.reason == ac.NO_LICENSE

    def test_activate_persists_and_flips_state(
        self, settings: Settings, this_machine: str, vendor_keys: Path, vendor_cli
    ) -> None:
        service = LicenseService(settings.license_path)
        code = issue_code(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID)

        state = service.activate(code)

        assert state.valid
        assert settings.license_path.is_file()
        assert settings.license_path.read_text(encoding="utf-8") == code

    def test_activation_survives_a_new_service_instance(
        self, settings: Settings, this_machine: str, vendor_keys: Path, vendor_cli
    ) -> None:
        """A restart must find the machine still activated."""
        code = issue_code(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID)
        LicenseService(settings.license_path).activate(code)

        assert LicenseService(settings.license_path).current_state().valid

    def test_wrong_machine_code_is_refused_and_not_stored(
        self, settings: Settings, this_machine: str, vendor_keys: Path, vendor_cli
    ) -> None:
        service = LicenseService(settings.license_path)
        code = issue_code(vendor_cli, vendor_keys, machine_id=OTHER_MACHINE_ID)

        state = service.activate(code)

        assert not state.valid
        assert state.reason == ac.WRONG_MACHINE
        assert not settings.license_path.exists()

    def test_tampered_code_is_refused_and_not_stored(
        self, settings: Settings, this_machine: str, vendor_keys: Path, vendor_cli
    ) -> None:
        service = LicenseService(settings.license_path)
        payload = vendor_cli.build_payload(customer="Acme Co", machine_id=TEST_MACHINE_ID)
        code = vendor_cli.sign_payload(vendor_keys.read_bytes(), payload)
        payload["max_meters"] = 9999
        tampered = ac.encode_activation_code(payload, ac._b64url_decode(code.split(".")[1]))

        state = service.activate(tampered)

        assert not state.valid
        assert state.reason == ac.INVALID_SIGNATURE
        assert not settings.license_path.exists()

    def test_a_bad_paste_does_not_deactivate_a_licensed_machine(
        self, settings: Settings, this_machine: str, vendor_keys: Path, vendor_cli
    ) -> None:
        service = LicenseService(settings.license_path)
        good = issue_code(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID)
        service.activate(good)

        service.activate("obvious rubbish")

        assert service.current_state().valid
        assert settings.license_path.read_text(encoding="utf-8") == good

    def test_expired_lease_lands_in_limited_mode(
        self, settings: Settings, this_machine: str, vendor_keys: Path, vendor_cli
    ) -> None:
        service = LicenseService(settings.license_path)
        code = issue_code(
            vendor_cli,
            vendor_keys,
            machine_id=TEST_MACHINE_ID,
            mode="leased",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )

        state = service.activate(code)

        assert not state.valid
        assert state.reason == ac.EXPIRED

    def test_listeners_fire_on_activation(
        self, settings: Settings, this_machine: str, vendor_keys: Path, vendor_cli
    ) -> None:
        """This is the hook that starts the Poller the moment a code lands."""
        seen: list[bool] = []
        service = LicenseService(settings.license_path)
        service.add_listener(lambda state: seen.append(state.valid))

        service.activate(issue_code(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID))

        assert seen[-1] is True

    def test_machine_id_is_exposed_for_the_activation_page(self, settings: Settings, this_machine: str) -> None:
        assert LicenseService(settings.license_path).machine_id == TEST_MACHINE_ID


# ─── End-to-end through the real app ──────────────────────────────────────────


@pytest.fixture
def client(migrated_db: Settings, this_machine: str, vendor_keys: Path) -> Iterator[TestClient]:
    """A TestClient over the real app on a limited machine, signed in as admin.

    From M2-1 the license endpoints need a token and activation needs an
    ``admin``, so the fixture walks Setup → Login before it can touch them.
    That both endpoints answer here at all — on a machine with no license — is
    the point of putting ``/api/auth`` on the Limited Mode allow-list: a machine
    whose lease lapsed must still be loggable-into, or it could never be
    re-activated.

    These tests are about the *license* gate, so the auth gate is satisfied and
    then kept out of the way. ``tests/test_auth_guard.py`` covers the other
    side: the same endpoints answering 401 with no token.
    """
    from arichds.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        assert test_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS).status_code == 201
        token = login_token(test_client, ADMIN_CREDENTIALS)
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client


class TestLimitedModeEnforcement:
    def test_health_is_reachable_in_limited_mode(self, client: TestClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "ok"

    def test_license_status_is_reachable_in_limited_mode(self, client: TestClient) -> None:
        response = client.get("/api/license/status")
        assert response.status_code == 200
        body = response.json()["data"]
        assert body["state"] == "limited"
        assert body["reason"] == ac.NO_LICENSE
        assert body["machine_id"] == TEST_MACHINE_ID

    def test_guarded_endpoints_are_403_license_invalid(self, client: TestClient) -> None:
        response = client.get("/api/devices")
        assert response.status_code == 403
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == ERROR_LICENSE_INVALID

    def test_post_devices_is_also_guarded(self, client: TestClient) -> None:
        response = client.post(
            "/api/devices",
            json={"name": "X", "brand": "cewe", "model": "prometer100", "host": "127.0.0.1", "port": 4059},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == ERROR_LICENSE_INVALID

    def test_non_api_paths_are_never_guarded(self, client: TestClient) -> None:
        """The SPA must load in Limited Mode — it is the way out of it."""
        response = client.get("/openapi.json")
        assert response.status_code == 200


class TestActivationAppliesLive:
    """ADR 0001 — the same app object goes 403 → 200 with no restart."""

    def test_activation_flips_enforcement_without_restart(
        self, client: TestClient, vendor_cli, vendor_keys: Path
    ) -> None:
        assert client.get("/api/devices").status_code == 403

        code = issue_code(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID)
        activate = client.post("/api/license/activate", json={"code": code})

        assert activate.status_code == 200
        assert activate.json()["success"] is True
        assert activate.json()["data"]["state"] == "active"

        # Same client, same process, same app instance.
        assert client.get("/api/devices").status_code == 200

    def test_activation_starts_the_poller(self, client: TestClient, vendor_cli, vendor_keys: Path) -> None:
        code = issue_code(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID)
        client.post("/api/license/activate", json={"code": code})
        # No devices are configured, so the Poller runs with zero workers — but
        # it must be *running*, which is what proves the listener fired.
        assert client.app.state.poller.running

    def test_activation_starts_the_scheduler(self, client: TestClient, vendor_cli, vendor_keys: Path) -> None:
        """The periodic jobs come up on activation too (issue #16), no restart.

        Same listener mechanism as the Poller above, and the same reason it has
        to be subscribed before the first evaluation: an already-licensed machine
        must start its jobs on boot.
        """
        code = issue_code(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID)
        client.post("/api/license/activate", json={"code": code})
        assert client.app.state.scheduler.running

    def test_rejected_code_returns_the_reason_and_stays_limited(
        self, client: TestClient, vendor_cli, vendor_keys: Path
    ) -> None:
        code = issue_code(vendor_cli, vendor_keys, machine_id=OTHER_MACHINE_ID)

        response = client.post("/api/license/activate", json={"code": code})

        assert response.status_code == 200  # the request succeeded; the code did not
        body = response.json()
        assert body["success"] is False
        assert body["error"]["reason"] == ac.WRONG_MACHINE
        assert client.get("/api/devices").status_code == 403

    def test_status_reports_the_licensed_customer_after_activation(
        self, client: TestClient, vendor_cli, vendor_keys: Path
    ) -> None:
        code = issue_code(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID, customer="Ryosan")
        client.post("/api/license/activate", json={"code": code})

        body = client.get("/api/license/status").json()["data"]
        assert body["state"] == "active"
        assert body["customer"] == "Ryosan"
        assert body["mode"] == "offline"
