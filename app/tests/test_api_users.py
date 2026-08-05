"""The ``/api/users`` surface — admin CRUD over accounts (M2-2).

Every endpoint here is admin-only at the router level, so the tests below come
in pairs: what an admin can do, and the 403 a plain ``user`` gets for the same
call.

The lockout defence is the three self-targeting rules (an admin may not delete
itself, change its own role, or reset its own password). There is deliberately
no "last admin" count anywhere in the implementation, and
``test_the_admin_count_can_never_reach_zero`` is what pins the argument that one
is not needed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import ADMIN_CREDENTIALS, bearer_client, login_token

#: A second account the tests create through the real endpoint.
OPERATOR = {"username": "operator", "password": "operator-password"}


def create_operator(admin_client: TestClient, role: str = "user") -> int:
    """Create :data:`OPERATOR` through ``POST /api/users`` and return its id."""
    response = admin_client.post("/api/users", json={**OPERATOR, "role": role})
    assert response.status_code == 201, response.text
    return int(response.json()["data"]["id"])


class TestListUsers:
    def test_lists_every_account_oldest_first(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/users")

        assert response.status_code == 200
        data = response.json()["data"]
        assert [entry["username"] for entry in data] == ["admin"]
        assert data[0]["role"] == "admin"

    def test_an_account_renders_identically_however_it_was_fetched(self, admin_client: TestClient) -> None:
        """One account, three endpoints — the same row must serialise the same.

        ``created_at`` is the trap: SQLite hands it back naive, so the value
        straight out of a ``POST`` (never round-tripped) and the value out of a
        ``GET`` (round-tripped) would carry different offsets without
        ``UserOut``'s validator.
        """
        from_create = admin_client.post("/api/users", json={**OPERATOR, "role": "user"}).json()["data"]

        from_list = admin_client.get("/api/users").json()["data"][1]
        from_patch = admin_client.patch(f"/api/users/{from_create['id']}/role", json={"role": "user"}).json()["data"]

        assert from_list == from_create
        assert from_patch == from_create


class TestCreateUser:
    def test_creates_an_account_the_new_user_can_log_in_with(self, admin_client: TestClient) -> None:
        response = admin_client.post(
            "/api/users", json={"username": "operator", "password": "operator-password", "role": "user"}
        )

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["username"] == "operator"
        assert data["role"] == "user"

        token = login_token(admin_client, {"username": "operator", "password": "operator-password"})
        assert bearer_client(admin_client, token).get("/api/auth/me").json()["data"]["username"] == "operator"


class TestSetRole:
    def test_promotes_a_user_to_admin(self, admin_client: TestClient) -> None:
        created = admin_client.post(
            "/api/users", json={"username": "operator", "password": "operator-password", "role": "user"}
        ).json()["data"]

        response = admin_client.patch(f"/api/users/{created['id']}/role", json={"role": "admin"})

        assert response.status_code == 200
        assert response.json()["data"]["role"] == "admin"
        assert admin_client.get("/api/users").json()["data"][1]["role"] == "admin"


class TestResetPassword:
    def test_sets_a_new_password_the_user_can_log_in_with(self, admin_client: TestClient) -> None:
        user_id = create_operator(admin_client)

        response = admin_client.post(f"/api/users/{user_id}/reset-password", json={"new_password": "brand-new-pass"})

        assert response.status_code == 200
        assert response.json()["data"] is True
        assert login_token(admin_client, {"username": "operator", "password": "brand-new-pass"})

    def test_revokes_every_live_session_of_the_target(self, admin_client: TestClient) -> None:
        """The password was changed by someone other than the owner — either a
        forgotten-password recovery or a suspected compromise, and leaving open
        sessions alive defeats both. v1 revoked nothing here; v2 overrules it."""
        user_id = create_operator(admin_client)
        first = bearer_client(admin_client, login_token(admin_client, OPERATOR))
        second = bearer_client(admin_client, login_token(admin_client, OPERATOR))

        admin_client.post(f"/api/users/{user_id}/reset-password", json={"new_password": "brand-new-pass"})

        assert first.get("/api/auth/me").status_code == 401
        assert second.get("/api/auth/me").status_code == 401

    def test_leaves_the_acting_admins_own_session_working(self, admin_client: TestClient) -> None:
        user_id = create_operator(admin_client)

        admin_client.post(f"/api/users/{user_id}/reset-password", json={"new_password": "brand-new-pass"})

        assert admin_client.get("/api/auth/me").status_code == 200


class TestDeleteUser:
    def test_removes_the_account(self, admin_client: TestClient) -> None:
        user_id = create_operator(admin_client)

        response = admin_client.delete(f"/api/users/{user_id}")

        assert response.status_code == 200
        assert response.json()["data"] is True
        assert [entry["username"] for entry in admin_client.get("/api/users").json()["data"]] == ["admin"]

    def test_kills_the_deleted_users_live_session(self, admin_client: TestClient) -> None:
        """v2 has no ``is_active`` column: deleting the row *is* v1's deactivate,
        and the FK cascade takes the token rows with it (INV-DATA-02)."""
        user_id = create_operator(admin_client)
        victim = bearer_client(admin_client, login_token(admin_client, OPERATOR))
        assert victim.get("/api/auth/me").status_code == 200

        admin_client.delete(f"/api/users/{user_id}")

        assert victim.get("/api/auth/me").status_code == 401


class TestSelfTargetingIsRefused:
    """The whole lockout defence: an admin can never remove its own admin-ness.

    v1 only had the self-deactivation rule (INV-AUTHZ-02). v2 adds the other
    two because it ships to a customer machine with SQLite in ``%ProgramData%``
    and no recovery path — ``tools/arichds_vendor.py`` has only keygen/sign/
    fingerprint, so SPEC §3.2's vendor-CLI escape hatch does not exist yet.
    """

    def test_an_admin_cannot_delete_itself(self, admin_client: TestClient) -> None:
        own_id = admin_client.get("/api/auth/me").json()["data"]["id"]

        response = admin_client.delete(f"/api/users/{own_id}")

        assert response.status_code == 400
        assert response.json()["detail"] == "You cannot delete your own account."
        assert admin_client.get("/api/auth/me").status_code == 200

    def test_an_admin_cannot_change_its_own_role(self, admin_client: TestClient) -> None:
        own_id = admin_client.get("/api/auth/me").json()["data"]["id"]

        response = admin_client.patch(f"/api/users/{own_id}/role", json={"role": "user"})

        assert response.status_code == 400
        assert response.json()["detail"] == "You cannot change your own role."
        assert admin_client.get("/api/auth/me").json()["data"]["role"] == "admin"

    def test_an_admin_cannot_reset_its_own_password(self, admin_client: TestClient) -> None:
        """Otherwise it is a hole straight through the current-password check:
        a stolen token could set a new password without knowing the old one."""
        own_id = admin_client.get("/api/auth/me").json()["data"]["id"]

        response = admin_client.post(f"/api/users/{own_id}/reset-password", json={"new_password": "sneaky-new-pass"})

        assert response.status_code == 400
        assert response.json()["detail"] == "Use Change password to change your own password."
        assert login_token(admin_client, ADMIN_CREDENTIALS)


#: Every endpoint of this router, as ``(method, path, body)``. Used both for the
#: 403 sweep and for the admin-count argument below.
USERS_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/users", None),
    ("POST", "/api/users", {"username": "intruder", "password": "intruder-pass", "role": "admin"}),
    ("PATCH", "/api/users/1/role", {"role": "user"}),
    ("POST", "/api/users/1/reset-password", {"new_password": "intruder-pass"}),
    ("DELETE", "/api/users/1", None),
]


class TestRoleBoundary:
    @pytest.mark.parametrize(("method", "path", "body"), USERS_ENDPOINTS)
    def test_a_plain_user_is_refused_403(
        self, user_client: TestClient, method: str, path: str, body: dict | None
    ) -> None:
        """SPEC §3.2: managing users is an administrator's job, end to end."""
        response = user_client.request(method, path, json=body)

        assert response.status_code == 403

    def test_a_demoted_admin_is_refused_on_its_very_next_request(self, admin_client: TestClient) -> None:
        """No re-login, no revocation: ``require_admin`` reads the role off the
        database row, so the JWT's ``role`` claim never gets a vote."""
        second_id = create_operator(admin_client, role="admin")
        second = bearer_client(admin_client, login_token(admin_client, OPERATOR))
        assert second.get("/api/users").status_code == 200

        admin_client.patch(f"/api/users/{second_id}/role", json={"role": "user"})

        assert second.get("/api/users").status_code == 403
        # The token itself is untouched — only the authorization decision moved.
        assert second.get("/api/auth/me").status_code == 200

    def test_a_promoted_user_is_admitted_on_its_very_next_request(self, admin_client: TestClient) -> None:
        user_id = create_operator(admin_client)
        operator = bearer_client(admin_client, login_token(admin_client, OPERATOR))
        assert operator.get("/api/users").status_code == 403

        admin_client.patch(f"/api/users/{user_id}/role", json={"role": "admin"})

        assert operator.get("/api/users").status_code == 200


class TestValidation:
    def test_a_duplicate_username_is_409(self, admin_client: TestClient) -> None:
        create_operator(admin_client)

        response = admin_client.post("/api/users", json={**OPERATOR, "role": "user"})

        assert response.status_code == 409
        assert response.json()["detail"] == "A user named 'operator' already exists."

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("PATCH", "/api/users/999/role", {"role": "user"}),
            ("POST", "/api/users/999/reset-password", {"new_password": "brand-new-pass"}),
            ("DELETE", "/api/users/999", None),
        ],
    )
    def test_an_unknown_target_is_404(
        self, admin_client: TestClient, method: str, path: str, body: dict | None
    ) -> None:
        response = admin_client.request(method, path, json=body)

        assert response.status_code == 404
        assert response.json()["detail"] == "No user with id 999"

    def test_a_short_password_is_422(self, admin_client: TestClient) -> None:
        response = admin_client.post("/api/users", json={"username": "operator", "password": "short", "role": "user"})

        assert response.status_code == 422

    def test_a_password_over_72_bytes_is_422(self, admin_client: TestClient) -> None:
        """40 characters, 120 bytes — bcrypt counts bytes, so a character limit
        would let this through and the hash call would then raise."""
        password = "é" * 40

        response = admin_client.post("/api/users", json={"username": "operator", "password": password, "role": "user"})

        assert response.status_code == 422

    def test_a_reset_to_a_short_password_is_422(self, admin_client: TestClient) -> None:
        user_id = create_operator(admin_client)

        response = admin_client.post(f"/api/users/{user_id}/reset-password", json={"new_password": "short"})

        assert response.status_code == 422

    def test_an_unknown_role_is_422(self, admin_client: TestClient) -> None:
        response = admin_client.post(
            "/api/users", json={"username": "operator", "password": "operator-password", "role": "superuser"}
        )

        assert response.status_code == 422

    def test_a_missing_role_is_422(self, admin_client: TestClient) -> None:
        """No default: silently minting an admin because a field was omitted is
        not a default worth having."""
        response = admin_client.post("/api/users", json={"username": "operator", "password": "operator-password"})

        assert response.status_code == 422


def admin_count(client: TestClient) -> int:
    """How many accounts currently hold the ``admin`` role."""
    return sum(1 for entry in client.get("/api/users").json()["data"] if entry["role"] == "admin")


class TestNoLockoutIsPossible:
    def test_the_admin_count_can_never_reach_zero(self, admin_client: TestClient) -> None:
        """Why there is no explicit "last admin" check anywhere.

        Every users endpoint requires an admin actor, and the actor can neither
        delete nor demote *itself*, so the actor is still an admin after any
        operation it is allowed to perform — the count therefore cannot reach
        zero. An explicit count query would be dead code (CLAUDE.md: simplicity
        first). This walks the whole removal surface, from both admins, to pin
        that argument.
        """
        first_id = admin_client.get("/api/auth/me").json()["data"]["id"]
        second_id = create_operator(admin_client, role="admin")
        second = bearer_client(admin_client, login_token(admin_client, OPERATOR))
        assert admin_count(admin_client) == 2

        # Neither admin can remove itself, by any of the three paths.
        for client, own_id in ((admin_client, first_id), (second, second_id)):
            assert client.delete(f"/api/users/{own_id}").status_code == 400
            assert client.patch(f"/api/users/{own_id}/role", json={"role": "user"}).status_code == 400
            assert (
                client.post(f"/api/users/{own_id}/reset-password", json={"new_password": "x" * 12}).status_code == 400
            )
            assert admin_count(admin_client) == 2

        # Each *may* remove the other — D2: there is no bootstrap-admin special
        # case, because protecting id 1 forever would make a forgotten or
        # compromised first account permanently unremovable.
        assert second.patch(f"/api/users/{first_id}/role", json={"role": "user"}).status_code == 200
        assert admin_count(second) == 1

        # And the survivor still cannot remove itself.
        assert second.delete(f"/api/users/{second_id}").status_code == 400
        assert second.patch(f"/api/users/{second_id}/role", json={"role": "user"}).status_code == 400
        assert admin_count(second) == 1


class TestNothingSecretLeaks:
    def test_no_response_carries_a_password_or_a_hash(self, admin_client: TestClient) -> None:
        created = admin_client.post("/api/users", json={**OPERATOR, "role": "user"})
        listed = admin_client.get("/api/users")
        user_id = created.json()["data"]["id"]
        reset = admin_client.post(f"/api/users/{user_id}/reset-password", json={"new_password": "brand-new-pass"})

        for response in (created, listed, reset):
            assert OPERATOR["password"] not in response.text
            assert "brand-new-pass" not in response.text
            assert "password" not in response.text
            assert "$2b$" not in response.text

    def test_no_log_line_carries_a_password_or_a_hash(
        self, admin_client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("DEBUG"):
            created = admin_client.post("/api/users", json={**OPERATOR, "role": "user"})
            user_id = created.json()["data"]["id"]
            admin_client.patch(f"/api/users/{user_id}/role", json={"role": "admin"})
            admin_client.post(f"/api/users/{user_id}/reset-password", json={"new_password": "brand-new-pass"})
            admin_client.delete(f"/api/users/{user_id}")

        assert OPERATOR["password"] not in caplog.text
        assert "brand-new-pass" not in caplog.text
        assert "$2b$" not in caplog.text
