"""Auth business logic against a real database, with no HTTP in the picture.

Setup-once, constant-time login, and the token lifecycle — the rules the API
layer merely translates into status codes.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from arichds.auth import service
from arichds.auth.roles import Role
from arichds.auth.security import create_access_token, hash_token, verify_password
from arichds.config import Settings, get_settings
from arichds.db.models import User, UserToken
from arichds.db.session import session_scope


def in_minutes(minutes: float) -> datetime:
    """An aware UTC instant *minutes* from now (negative for the past)."""
    return datetime.now(UTC) + timedelta(minutes=minutes)


class TestSetup:
    def test_creates_the_bootstrap_admin(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            user = service.create_initial_admin(session, "alice", "hunter2hunter2")

            assert user is not None
            assert user.username == "alice"
            assert user.role is Role.ADMIN

    def test_the_password_is_stored_hashed(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            user = service.create_initial_admin(session, "alice", "hunter2hunter2")

            assert user is not None
            assert user.password_hash != "hunter2hunter2"
            assert verify_password("hunter2hunter2", user.password_hash)

    def test_setup_is_closed_after_the_first_account(self, migrated_db: Settings) -> None:
        """Second call returns None — Setup is permanently closed (CONTEXT.md)."""
        with session_scope() as session:
            service.create_initial_admin(session, "alice", "hunter2hunter2")

        with session_scope() as session:
            assert service.create_initial_admin(session, "bob", "hunter2hunter2") is None
            assert service.user_count(session) == 1

    def test_user_count_starts_at_zero(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            assert service.user_count(session) == 0


class TestAuthenticate:
    def test_valid_credentials_issue_a_token(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            service.create_initial_admin(session, "alice", "hunter2hunter2")

        with session_scope() as session:
            result = service.authenticate(session, "alice", "hunter2hunter2")

            assert result is not None
            token, user = result
            assert token
            assert user.username == "alice"

    def test_an_unknown_username_fails(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            service.create_initial_admin(session, "alice", "hunter2hunter2")

        with session_scope() as session:
            assert service.authenticate(session, "nobody", "hunter2hunter2") is None

    def test_a_wrong_password_fails(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            service.create_initial_admin(session, "alice", "hunter2hunter2")

        with session_scope() as session:
            assert service.authenticate(session, "alice", "wrong-password") is None

    def test_no_token_row_is_written_on_failure(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            service.create_initial_admin(session, "alice", "hunter2hunter2")

        with session_scope() as session:
            service.authenticate(session, "alice", "wrong-password")

        with session_scope() as session:
            assert session.scalars(select(UserToken)).all() == []

    def test_only_the_token_hash_is_stored(self, migrated_db: Settings) -> None:
        """v1 INV-AUTH-04: a stolen copy of arichds.db must not be replayable."""
        with session_scope() as session:
            service.create_initial_admin(session, "alice", "hunter2hunter2")

        with session_scope() as session:
            result = service.authenticate(session, "alice", "hunter2hunter2")
            assert result is not None
            raw_token, _ = result

        with session_scope() as session:
            row = session.scalars(select(UserToken)).one()
            assert row.token_hash == hash_token(raw_token)
            assert raw_token not in row.token_hash

    def test_logging_in_twice_expires_nothing(self, migrated_db: Settings) -> None:
        """Two browsers, two live sessions — no single-session assumption."""
        with session_scope() as session:
            service.create_initial_admin(session, "alice", "hunter2hunter2")

        with session_scope() as session:
            first = service.authenticate(session, "alice", "hunter2hunter2")
            second = service.authenticate(session, "alice", "hunter2hunter2")

        assert first is not None
        assert second is not None
        with session_scope() as session:
            assert len(session.scalars(select(UserToken)).all()) == 2


def login(username: str = "alice", password: str = "hunter2hunter2") -> str:
    """Create the admin if needed and return a fresh raw Access Token."""
    with session_scope() as session:
        service.create_initial_admin(session, username, password)
        result = service.authenticate(session, username, password)
        assert result is not None
        return result[0]


def login_with_expiry_minutes(minutes: int) -> str:
    """Log in with ``ARICHDS_TOKEN_EXPIRE_MINUTES`` temporarily overridden.

    A negative value yields a token that was already expired when it was
    issued — the only way to reach the expiry paths without sleeping.
    """
    previous = os.environ.get("ARICHDS_TOKEN_EXPIRE_MINUTES")
    os.environ["ARICHDS_TOKEN_EXPIRE_MINUTES"] = str(minutes)
    get_settings.cache_clear()
    try:
        return login()
    finally:
        if previous is None:
            del os.environ["ARICHDS_TOKEN_EXPIRE_MINUTES"]
        else:
            os.environ["ARICHDS_TOKEN_EXPIRE_MINUTES"] = previous
        get_settings.cache_clear()


class TestResolveToken:
    def test_a_fresh_token_resolves_to_its_user(self, migrated_db: Settings) -> None:
        raw_token = login()

        with session_scope() as session:
            user = service.resolve_token(session, raw_token)

            assert user is not None
            assert user.username == "alice"

    def test_a_tampered_token_does_not_resolve(self, migrated_db: Settings) -> None:
        raw_token = login()

        with session_scope() as session:
            assert service.resolve_token(session, raw_token + "x") is None

    def test_gibberish_does_not_resolve(self, migrated_db: Settings) -> None:
        login()

        with session_scope() as session:
            assert service.resolve_token(session, "not-a-jwt") is None

    def test_a_revoked_token_does_not_resolve(self, migrated_db: Settings) -> None:
        raw_token = login()

        with session_scope() as session:
            service.revoke_token(session, hash_token(raw_token))

        with session_scope() as session:
            assert service.resolve_token(session, raw_token) is None

    def test_an_expired_jwt_does_not_resolve(self, migrated_db: Settings) -> None:
        raw_token = login_with_expiry_minutes(-1)

        with session_scope() as session:
            assert service.resolve_token(session, raw_token) is None

    def test_a_stored_row_that_has_lapsed_does_not_resolve(self, migrated_db: Settings) -> None:
        """The stored expiry is checked in its own right, not just the JWT's.

        SQLite hands ``expires_at`` back **naive**; comparing that to an aware
        ``now`` raises TypeError unless UTC is re-attached first. This branch is
        the one that would blow up, so it gets its own test.
        """
        with session_scope() as session:
            service.create_initial_admin(session, "alice", "hunter2hunter2")
            user_id = session.scalars(select(User)).one().id

        raw_token = create_access_token(user_id=user_id, role="admin", expires_at=in_minutes(60))
        with session_scope() as session:
            session.add(
                UserToken(
                    user_id=user_id,
                    token_hash=hash_token(raw_token),
                    expires_at=in_minutes(-60),
                )
            )

        with session_scope() as session:
            assert service.resolve_token(session, raw_token) is None

    def test_a_token_whose_row_is_gone_does_not_resolve(self, migrated_db: Settings) -> None:
        """A valid signature is not a session — the stored hash is the record."""
        raw_token = login()

        with session_scope() as session:
            session.execute(delete(UserToken))

        with session_scope() as session:
            assert service.resolve_token(session, raw_token) is None

    def test_a_token_whose_user_is_gone_does_not_resolve(self, migrated_db: Settings) -> None:
        """M2-2 locks an account out by deleting it; live tokens must die with it."""
        raw_token = login()

        with session_scope() as session:
            session.delete(session.scalars(select(User)).one())

        with session_scope() as session:
            assert service.resolve_token(session, raw_token) is None


class TestRevokeToken:
    def test_revoking_is_idempotent(self, migrated_db: Settings) -> None:
        raw_token = login()

        with session_scope() as session:
            service.revoke_token(session, hash_token(raw_token))
            service.revoke_token(session, hash_token(raw_token))

        with session_scope() as session:
            assert session.scalars(select(UserToken)).one().revoked_at is not None

    def test_revoking_an_unknown_hash_is_a_no_op(self, migrated_db: Settings) -> None:
        login()

        with session_scope() as session:
            service.revoke_token(session, "f" * 64)

        with session_scope() as session:
            assert session.scalars(select(UserToken)).one().revoked_at is None


class TestPurgeExpiredTokens:
    def test_expired_rows_go_and_live_ones_stay(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            service.create_initial_admin(session, "alice", "hunter2hunter2")
            user_id = session.scalars(select(User)).one().id
            session.add(UserToken(user_id=user_id, token_hash="dead" + "0" * 60, expires_at=in_minutes(-60)))
            session.add(UserToken(user_id=user_id, token_hash="live" + "0" * 60, expires_at=in_minutes(60)))

        with session_scope() as session:
            service.purge_expired_tokens(session, user_id)

        with session_scope() as session:
            assert [t.token_hash for t in session.scalars(select(UserToken))] == ["live" + "0" * 60]

    def test_another_users_expired_rows_are_left_alone(self, migrated_db: Settings) -> None:
        """A login sweeps its own rows, not the whole table."""
        with session_scope() as session:
            service.create_initial_admin(session, "alice", "hunter2hunter2")
            alice_id = session.scalars(select(User)).one().id
            bob = User(username="bob", password_hash="x", role=Role.USER)
            session.add(bob)
            session.flush()
            bob_id = bob.id
            session.add(UserToken(user_id=bob_id, token_hash="dead" + "0" * 60, expires_at=in_minutes(-60)))

        with session_scope() as session:
            service.purge_expired_tokens(session, alice_id)

        with session_scope() as session:
            assert len(session.scalars(select(UserToken)).all()) == 1
