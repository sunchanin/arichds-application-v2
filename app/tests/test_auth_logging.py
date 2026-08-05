"""What a failed login leaves in the log (M2-1).

SPEC §3.2 rules out lockout and rate limiting and asks for a logged failure
instead — that line is the whole audit trail (it surfaces in the App Log in M7),
so it has to carry enough to act on and nothing that must not be written down.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from arichds.config import Settings, get_settings
from tests.conftest import ADMIN_CREDENTIALS


def read_log(settings: Settings) -> str:
    """Return the contents of the rotating application log."""
    return (settings.log_dir / "arichds.log").read_text(encoding="utf-8", errors="replace")


class TestFailedLoginLogging:
    def test_a_failure_is_logged_with_the_username(self, unlicensed_client: TestClient) -> None:
        unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS)

        unlicensed_client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})

        log = read_log(get_settings())
        assert "Login failed" in log
        assert "admin" in log

    def test_the_submitted_password_is_never_logged(self, unlicensed_client: TestClient) -> None:
        unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS)

        unlicensed_client.post("/api/auth/login", json={"username": "admin", "password": "sup3rsecretpassword"})

        assert "sup3rsecretpassword" not in read_log(get_settings())

    def test_an_unknown_username_is_logged_too(self, unlicensed_client: TestClient) -> None:
        unlicensed_client.post("/api/auth/login", json={"username": "intruder", "password": "guessing"})

        log = read_log(get_settings())
        assert "Login failed" in log
        assert "intruder" in log

    def test_the_setup_password_is_never_logged(self, unlicensed_client: TestClient) -> None:
        unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS)

        assert ADMIN_CREDENTIALS["password"] not in read_log(get_settings())

    def test_the_issued_token_is_never_logged(self, unlicensed_client: TestClient) -> None:
        unlicensed_client.post("/api/auth/setup", json=ADMIN_CREDENTIALS)

        token = unlicensed_client.post("/api/auth/login", json=ADMIN_CREDENTIALS).json()["data"]["access_token"]

        assert token not in read_log(get_settings())
