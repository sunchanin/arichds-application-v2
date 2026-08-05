"""Password hashing, token hashing and JWT primitives (M2-1).

The crypto boundary, tested without any HTTP in the picture.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest

from arichds.auth import security
from arichds.config import Settings, get_settings


class TestPasswordHashing:
    def test_hash_and_verify_round_trip(self) -> None:
        hashed = security.hash_password("correct horse")
        assert security.verify_password("correct horse", hashed)

    def test_wrong_password_does_not_verify(self) -> None:
        hashed = security.hash_password("correct horse")
        assert not security.verify_password("battery staple", hashed)

    def test_the_same_password_hashes_differently_each_time(self) -> None:
        """Per-hash salt — two identical passwords must not share a digest."""
        assert security.hash_password("same") != security.hash_password("same")

    def test_an_over_long_password_is_a_mismatch_not_a_crash(self) -> None:
        """bcrypt 5.0 raises past 72 bytes; the login path must still answer."""
        hashed = security.hash_password("correct horse")
        assert not security.verify_password("x" * 73, hashed)

    def test_a_malformed_stored_hash_is_a_mismatch(self) -> None:
        assert not security.verify_password("anything", "not-a-bcrypt-hash")

    def test_the_dummy_hash_is_usable_and_within_the_byte_limit(self) -> None:
        """The constant-time path must run real bcrypt work, not raise."""
        assert security.verify_password("nope", security.DUMMY_PASSWORD_HASH) is False


class TestTokenHashing:
    def test_hash_token_is_stable(self) -> None:
        assert security.hash_token("a.b.c") == security.hash_token("a.b.c")

    def test_hash_token_is_a_sha256_hex_digest(self) -> None:
        digest = security.hash_token("a.b.c")
        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")

    def test_different_tokens_hash_differently(self) -> None:
        assert security.hash_token("a.b.c") != security.hash_token("a.b.d")


class TestJwtSecret:
    def test_generated_once_and_reused(self, settings: Settings) -> None:
        first = security.get_jwt_secret()
        assert security.get_jwt_secret() == first

    def test_the_generated_secret_is_persisted(self, settings: Settings) -> None:
        secret = security.get_jwt_secret()
        assert settings.jwt_secret_path.read_text(encoding="utf-8").strip() == secret

    def test_an_existing_file_is_reused_across_processes(self, settings: Settings) -> None:
        """A service restart must not log everyone out (ADR 0003)."""
        settings.jwt_secret_path.parent.mkdir(parents=True, exist_ok=True)
        settings.jwt_secret_path.write_text("persisted-secret", encoding="utf-8")
        assert security.get_jwt_secret() == "persisted-secret"

    def test_the_env_override_wins(self, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        settings.jwt_secret_path.parent.mkdir(parents=True, exist_ok=True)
        settings.jwt_secret_path.write_text("file-secret", encoding="utf-8")
        monkeypatch.setenv("ARICHDS_JWT_SECRET", "env-secret")
        get_settings.cache_clear()

        assert security.get_jwt_secret() == "env-secret"

    def test_no_secret_file_is_written_when_the_env_var_is_set(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ARICHDS_JWT_SECRET", "env-secret")
        get_settings.cache_clear()

        security.get_jwt_secret()

        assert not settings.jwt_secret_path.exists()

    def test_no_temp_files_are_left_behind(self, settings: Settings) -> None:
        security.get_jwt_secret()
        leftovers = [p.name for p in settings.secret_dir.iterdir() if p.name != "jwt_secret.key"]
        assert leftovers == []


class TestAccessTokens:
    def test_encode_then_decode_round_trip(self, settings: Settings) -> None:
        expires = datetime.now(UTC) + timedelta(minutes=480)
        token = security.create_access_token(user_id=7, role="admin", expires_at=expires)

        claims = security.decode_access_token(token)

        assert claims["sub"] == "7"
        assert claims["role"] == "admin"
        assert claims["exp"] == int(expires.timestamp())

    def test_two_tokens_issued_in_the_same_second_differ(self, settings: Settings) -> None:
        """`iat`/`exp` are whole seconds — only `jti` keeps two logins distinct,
        and `user_tokens.token_hash` is UNIQUE."""
        expires = datetime.now(UTC) + timedelta(minutes=5)
        first = security.create_access_token(user_id=1, role="admin", expires_at=expires)
        second = security.create_access_token(user_id=1, role="admin", expires_at=expires)

        assert first != second

    def test_an_expired_token_raises(self, settings: Settings) -> None:
        token = security.create_access_token(
            user_id=1, role="user", expires_at=datetime.now(UTC) - timedelta(seconds=1)
        )

        with pytest.raises(jwt.ExpiredSignatureError):
            security.decode_access_token(token)

    def test_a_tampered_token_raises(self, settings: Settings) -> None:
        token = security.create_access_token(
            user_id=1, role="user", expires_at=datetime.now(UTC) + timedelta(minutes=5)
        )

        with pytest.raises(jwt.InvalidTokenError):
            security.decode_access_token(token + "x")

    def test_a_token_signed_with_another_secret_raises(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Deleting jwt_secret.key is the rotation mechanism (ADR 0003)."""
        token = security.create_access_token(
            user_id=1, role="user", expires_at=datetime.now(UTC) + timedelta(minutes=5)
        )
        monkeypatch.setenv("ARICHDS_JWT_SECRET", "a-different-secret")
        get_settings.cache_clear()

        with pytest.raises(jwt.InvalidTokenError):
            security.decode_access_token(token)
