"""The auth boundary on ``/api/license`` and the Limited Mode carve-out (M2-1).

Two rules meet here and are easy to confuse:

* The license endpoints are exempt from the **Limited Mode** gate — otherwise a
  lapsed machine could never be re-activated.
* They are **not** exempt from the auth gate. Reading the status needs any
  account; activating needs an ``admin`` (SPEC §3.2).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from arichds.constants import ERROR_LICENSE_INVALID
from tests.conftest import ADMIN_CREDENTIALS


class TestLicenseRoles:
    def test_any_authenticated_user_can_read_the_status(self, user_client: TestClient) -> None:
        response = user_client.get("/api/license/status")

        assert response.status_code == 200
        assert response.json()["data"]["state"] == "active"

    def test_a_user_cannot_activate(self, user_client: TestClient, activation_code: str) -> None:
        response = user_client.post("/api/license/activate", json={"code": activation_code})

        assert response.status_code == 403

    def test_an_admin_can_activate(self, admin_client: TestClient, activation_code: str) -> None:
        response = admin_client.post("/api/license/activate", json={"code": activation_code})

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_the_machine_id_is_not_readable_without_a_token(self, anon_client: TestClient) -> None:
        """It identifies this computer; nobody on the site LAN gets it for free."""
        response = anon_client.get("/api/license/status")

        assert response.status_code == 401
        assert "e" * 64 not in response.text


class TestLimitedMode:
    """A machine with no license must still be reachable enough to fix."""

    def test_check_setup_answers(self, unlicensed_client: TestClient) -> None:
        assert unlicensed_client.get("/api/auth/check-setup").status_code == 200

    def test_setup_and_login_both_work(self, unlicensed_client: TestClient) -> None:
        assert unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS).status_code == 201

        response = unlicensed_client.post("/api/auth/login", json=ADMIN_CREDENTIALS)

        assert response.status_code == 200
        assert response.json()["data"]["access_token"]

    def test_a_logged_in_admin_still_cannot_reach_devices(self, unlicensed_client: TestClient) -> None:
        """Authentication does not lift Limited Mode — they are separate gates."""
        unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS)
        token = unlicensed_client.post("/api/auth/login", json=ADMIN_CREDENTIALS).json()["data"]["access_token"]

        response = unlicensed_client.get("/api/devices", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 403
        assert response.json()["error"]["code"] == ERROR_LICENSE_INVALID

    def test_devices_is_403_not_401_even_without_a_token(self, unlicensed_client: TestClient) -> None:
        """The license gate runs first, as ASGI middleware, before any dependency."""
        response = unlicensed_client.get("/api/devices")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == ERROR_LICENSE_INVALID
