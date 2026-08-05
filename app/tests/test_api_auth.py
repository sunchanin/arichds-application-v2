"""The ``/api/auth`` surface — Setup, Login, Logout, Me (M2-1).

Setup → Login → Activation is the first-run walk (SPEC §3.2), so most of these
run against a fresh, unlicensed machine: the auth endpoints are on the Limited
Mode allow-list precisely so a lapsed machine can still be logged into and
re-activated.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from arichds.config import get_settings
from tests.conftest import ADMIN_CREDENTIALS, USER_CREDENTIALS, bearer_client, login_token


class TestCheckSetup:
    def test_setup_is_required_on_a_fresh_machine(self, unlicensed_client: TestClient) -> None:
        response = unlicensed_client.get("/api/auth/check-setup")

        assert response.status_code == 200
        assert response.json()["data"] == {"setup_required": True}

    def test_setup_is_not_required_once_an_account_exists(self, unlicensed_client: TestClient) -> None:
        unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS)

        assert unlicensed_client.get("/api/auth/check-setup").json()["data"] == {"setup_required": False}


class TestSetup:
    def test_creates_the_bootstrap_admin(self, unlicensed_client: TestClient) -> None:
        response = unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS)

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["username"] == "admin"
        assert data["role"] == "admin"

    def test_never_returns_the_password_or_its_hash(self, unlicensed_client: TestClient) -> None:
        response = unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS)

        assert "password" not in response.json()["data"]
        assert "password_hash" not in response.json()["data"]
        assert ADMIN_CREDENTIALS["password"] not in response.text

    def test_a_second_setup_is_409(self, unlicensed_client: TestClient) -> None:
        """ "Already done" is a conflict, not a permissions problem."""
        unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS)

        response = unlicensed_client.post(
            "/api/auth/setup", json={"username": "intruder", "password": "another-password"}
        )

        assert response.status_code == 409

    def test_a_short_password_is_422(self, unlicensed_client: TestClient) -> None:
        response = unlicensed_client.post("/api/auth/setup", json={"username": "admin", "password": "short"})

        assert response.status_code == 422

    def test_a_password_over_72_bytes_is_422_not_500(self, unlicensed_client: TestClient) -> None:
        """40 characters, 120 bytes — a character limit would let this through
        and bcrypt 5.0 would then raise inside the hash call."""
        password = "é" * 40
        assert len(password) < 72
        assert len(password.encode("utf-8")) > 72

        response = unlicensed_client.post("/api/auth/setup", json={"username": "admin", "password": password})

        assert response.status_code == 422

    def test_a_72_byte_password_is_accepted(self, unlicensed_client: TestClient) -> None:
        """The boundary is inclusive — bcrypt accepts exactly 72 bytes."""
        response = unlicensed_client.post("/api/auth/setup", json={"username": "admin", "password": "x" * 72})

        assert response.status_code == 201

    def test_a_short_username_is_422(self, unlicensed_client: TestClient) -> None:
        response = unlicensed_client.post("/api/auth/setup", json={"username": "ab", "password": "long-enough"})

        assert response.status_code == 422


class TestLogin:
    def test_valid_credentials_return_a_token_and_the_user(self, unlicensed_client: TestClient) -> None:
        unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS)

        response = unlicensed_client.post("/api/auth/login", json=ADMIN_CREDENTIALS)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["access_token"]
        assert data["token_type"] == "bearer"
        assert data["user"]["username"] == "admin"
        assert data["user"]["role"] == "admin"

    def test_a_wrong_password_is_401(self, unlicensed_client: TestClient) -> None:
        unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS)

        response = unlicensed_client.post("/api/auth/login", json={"username": "admin", "password": "not-the-password"})

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid username or password"

    def test_an_unknown_username_gives_the_same_401(self, unlicensed_client: TestClient) -> None:
        """Same status, same words — no account-enumeration oracle."""
        unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS)

        response = unlicensed_client.post(
            "/api/auth/login", json={"username": "nobody", "password": "not-the-password"}
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid username or password"

    def test_the_401_carries_the_bearer_challenge(self, unlicensed_client: TestClient) -> None:
        unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS)

        response = unlicensed_client.post("/api/auth/login", json={"username": "admin", "password": "wrong-one"})

        assert response.headers["WWW-Authenticate"] == "Bearer"


class TestMe:
    def test_returns_the_authenticated_user(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/auth/me")

        assert response.status_code == 200
        assert response.json()["data"]["username"] == "admin"

    def test_is_401_without_a_token(self, anon_client: TestClient) -> None:
        assert anon_client.get("/api/auth/me").status_code == 401

    def test_is_401_with_a_garbage_token(self, activated_client: TestClient) -> None:
        response = activated_client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})

        assert response.status_code == 401

    def test_is_401_with_a_non_bearer_scheme(self, activated_client: TestClient) -> None:
        response = activated_client.get("/api/auth/me", headers={"Authorization": "Basic YWRtaW46YWRtaW4="})

        assert response.status_code == 401

    def test_created_at_is_reported_the_same_way_as_setup_reported_it(self, unlicensed_client: TestClient) -> None:
        """One account, two endpoints — the same instant must render identically."""
        from_setup = unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS).json()["data"]
        token = unlicensed_client.post("/api/auth/login", json=ADMIN_CREDENTIALS).json()["data"]["access_token"]

        from_me = unlicensed_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["data"]

        assert from_me == from_setup


class TestLogout:
    def test_revokes_the_presenting_token(self, admin_client: TestClient) -> None:
        assert admin_client.post("/api/auth/logout").json()["data"] is True

        assert admin_client.get("/api/auth/me").status_code == 401

    def test_is_401_without_a_token(self, anon_client: TestClient) -> None:
        assert anon_client.post("/api/auth/logout").status_code == 401

    def test_another_session_survives(self, activated_client: TestClient) -> None:
        """Logging out of one browser must not log the wall display out."""
        first = login_token(activated_client, ADMIN_CREDENTIALS)
        second = login_token(activated_client, ADMIN_CREDENTIALS)

        activated_client.post("/api/auth/logout", headers={"Authorization": f"Bearer {first}"})

        still_valid = activated_client.get("/api/auth/me", headers={"Authorization": f"Bearer {second}"})
        assert still_valid.status_code == 200

    def test_an_expired_token_is_401(self, activated_client: TestClient, monkeypatch) -> None:
        """End-to-end through the API, because the stored expiry comes back from
        SQLite naive and comparing it to an aware `now` is a TypeError trap."""
        monkeypatch.setenv("ARICHDS_TOKEN_EXPIRE_MINUTES", "-1")
        get_settings.cache_clear()
        expired = login_token(activated_client, ADMIN_CREDENTIALS)
        monkeypatch.delenv("ARICHDS_TOKEN_EXPIRE_MINUTES")
        get_settings.cache_clear()

        response = activated_client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})

        assert response.status_code == 401


class TestChangePassword:
    """Changing your own password (M2-2).

    The only non-admin endpoint of this slice, which is why it lives on
    ``/api/auth`` rather than the admin-only ``/api/users`` router — and being
    on the Limited Mode allow-list means an operator on a lapsed machine can
    still change their password.
    """

    def test_replaces_the_password(self, admin_client: TestClient) -> None:
        response = admin_client.post(
            "/api/auth/change-password",
            json={"current_password": ADMIN_CREDENTIALS["password"], "new_password": "a-brand-new-pass"},
        )

        assert response.status_code == 200
        assert response.json()["data"] is True

    def test_the_old_password_stops_working_and_the_new_one_starts(self, admin_client: TestClient) -> None:
        admin_client.post(
            "/api/auth/change-password",
            json={"current_password": ADMIN_CREDENTIALS["password"], "new_password": "a-brand-new-pass"},
        )

        assert admin_client.post("/api/auth/login", json=ADMIN_CREDENTIALS).status_code == 401
        assert login_token(admin_client, {"username": "admin", "password": "a-brand-new-pass"})

    def test_a_wrong_current_password_is_400_not_401(self, admin_client: TestClient) -> None:
        response = admin_client.post(
            "/api/auth/change-password",
            json={"current_password": "not-the-password", "new_password": "a-brand-new-pass"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Current password is incorrect."

    def test_a_wrong_current_password_does_not_sign_the_operator_out(self, admin_client: TestClient) -> None:
        """A 401 here would be read by the SPA's request helper as a bad token
        and would clear the session — a typo must not sign anyone out."""
        admin_client.post(
            "/api/auth/change-password",
            json={"current_password": "not-the-password", "new_password": "a-brand-new-pass"},
        )

        assert admin_client.get("/api/auth/me").status_code == 200

    def test_the_presenting_session_survives_and_the_others_do_not(self, activated_client: TestClient) -> None:
        """v1 INV-DATA-04: sessions opened under the old password go, but not
        the browser the operator is standing in front of."""
        first = login_token(activated_client, ADMIN_CREDENTIALS)
        second = login_token(activated_client, ADMIN_CREDENTIALS)
        changing = bearer_client(activated_client, first)

        changing.post(
            "/api/auth/change-password",
            json={"current_password": ADMIN_CREDENTIALS["password"], "new_password": "a-brand-new-pass"},
        )

        assert changing.get("/api/auth/me").status_code == 200
        assert bearer_client(activated_client, second).get("/api/auth/me").status_code == 401

    def test_a_user_role_account_can_change_its_own_password(self, user_client: TestClient) -> None:
        """Not admin-only — it is the one non-admin endpoint of this slice."""
        response = user_client.post(
            "/api/auth/change-password",
            json={"current_password": USER_CREDENTIALS["password"], "new_password": "a-brand-new-pass"},
        )

        assert response.status_code == 200
        assert user_client.get("/api/auth/me").status_code == 200

    def test_is_401_without_a_token(self, anon_client: TestClient) -> None:
        """A well-formed body with no token must be refused before it is read —
        a 422 here would mean the guard is attached too deep."""
        response = anon_client.post(
            "/api/auth/change-password",
            json={"current_password": "whatever-it-is", "new_password": "a-brand-new-pass"},
        )

        assert response.status_code == 401

    def test_a_new_password_equal_to_the_current_one_is_422(self, admin_client: TestClient) -> None:
        response = admin_client.post(
            "/api/auth/change-password",
            json={"current_password": ADMIN_CREDENTIALS["password"], "new_password": ADMIN_CREDENTIALS["password"]},
        )

        assert response.status_code == 422

    def test_a_short_new_password_is_422(self, admin_client: TestClient) -> None:
        response = admin_client.post(
            "/api/auth/change-password",
            json={"current_password": ADMIN_CREDENTIALS["password"], "new_password": "short"},
        )

        assert response.status_code == 422

    def test_a_new_password_over_72_bytes_is_422(self, admin_client: TestClient) -> None:
        response = admin_client.post(
            "/api/auth/change-password",
            json={"current_password": ADMIN_CREDENTIALS["password"], "new_password": "é" * 40},
        )

        assert response.status_code == 422

    def test_no_response_carries_either_password(self, admin_client: TestClient) -> None:
        response = admin_client.post(
            "/api/auth/change-password",
            json={"current_password": ADMIN_CREDENTIALS["password"], "new_password": "a-brand-new-pass"},
        )

        assert ADMIN_CREDENTIALS["password"] not in response.text
        assert "a-brand-new-pass" not in response.text
