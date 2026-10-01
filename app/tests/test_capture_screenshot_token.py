"""``capture.screenshot`` — the capture token lifecycle (decision 9, issue
#38), against the real database. No browser, no HTTP — just the mint/delete
pair the orchestration wraps around a capture attempt.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from arichds.auth.roles import Role
from arichds.auth.security import hash_password
from arichds.capture.screenshot import BrowserCaptureError, _delete_capture_token, _mint_capture_token
from arichds.config import Settings
from arichds.db.models import User, UserToken
from arichds.db.session import session_scope


def _make_user(username: str, role: Role) -> User:
    return User(username=username, password_hash=hash_password("irrelevant-pw"), role=role)


class TestMintCaptureToken:
    def test_mints_a_token_for_the_lowest_id_admin(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            session.add(_make_user("operator", Role.USER))  # a non-admin must never be chosen
            session.flush()
            first_admin = _make_user("admin-a", Role.ADMIN)
            session.add(first_admin)
            session.flush()
            second_admin = _make_user("admin-b", Role.ADMIN)
            session.add(second_admin)
            session.flush()
            assert first_admin.id < second_admin.id

            minted = _mint_capture_token(session)

        assert minted.user_id == first_admin.id
        assert minted.username == "admin-a"
        assert minted.role == Role.ADMIN.value

        with session_scope() as session:
            row = session.query(UserToken).filter(UserToken.token_hash == minted.token_hash).one()
            assert row.user_id == first_admin.id

    def test_the_token_expires_in_five_minutes(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            session.add(_make_user("admin", Role.ADMIN))
            session.flush()
            before = datetime.now(UTC)
            minted = _mint_capture_token(session)
            after = datetime.now(UTC)

        with session_scope() as session:
            row = session.query(UserToken).filter(UserToken.token_hash == minted.token_hash).one()
            expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
            assert before + timedelta(minutes=5) <= expires_at <= after + timedelta(minutes=5)

    def test_raises_when_no_admin_exists(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            session.add(_make_user("operator", Role.USER))
            session.flush()

            with pytest.raises(BrowserCaptureError, match="admin"):
                _mint_capture_token(session)


class TestDeleteCaptureToken:
    def test_deletes_the_row_rather_than_revoking_it(self, migrated_db: Settings) -> None:
        with session_scope() as session:
            session.add(_make_user("admin", Role.ADMIN))
            session.flush()
            minted = _mint_capture_token(session)

        _delete_capture_token(minted.token_hash)

        with session_scope() as session:
            assert session.query(UserToken).filter(UserToken.token_hash == minted.token_hash).one_or_none() is None

    def test_deleting_an_unknown_hash_does_not_raise(self, migrated_db: Settings) -> None:
        _delete_capture_token("no-such-hash")  # must not raise
