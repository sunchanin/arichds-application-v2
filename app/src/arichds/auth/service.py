"""Auth business logic — plain functions over a ``Session``, no HTTP types.

The rules live here; :mod:`arichds.api.auth` and :mod:`arichds.api.deps` only
translate them into status codes. Failure is expressed as ``None``, not as an
exception class, because every caller in this slice already has a single
correct response for it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from jwt import InvalidTokenError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arichds.auth.roles import Role
from arichds.auth.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_token,
    verify_password,
)
from arichds.config import get_settings
from arichds.db.models import User, UserToken

logger = logging.getLogger(__name__)


def user_count(session: Session) -> int:
    """Return how many accounts exist. Zero means Setup is still open."""
    return session.scalar(select(func.count()).select_from(User)) or 0


def create_initial_admin(session: Session, username: str, password: str) -> User | None:
    """Create the bootstrap admin, once and only once.

    Setup is open only while zero users exist (CONTEXT.md — Setup). The count
    check answers the common case; the UNIQUE constraint is what actually makes
    it atomic when two browsers post at the same moment.

    Args:
        session: Open database session; committed on success.
        username: Desired admin username, already validated by the API.
        password: Plaintext password, already validated by the API.

    Returns:
        The created admin, or None when Setup is already closed.
    """
    if user_count(session) > 0:
        return None

    user = User(username=username, password_hash=hash_password(password), role=Role.ADMIN)
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        logger.info("Setup rejected — an account was created concurrently")
        return None

    session.refresh(user)
    logger.info("Initial admin %r created", username)
    return user


def authenticate(
    session: Session,
    username: str,
    password: str,
    client_ip: str | None = None,
) -> tuple[str, User] | None:
    """Check credentials and issue an Access Token.

    Constant-time by construction (v1 INV-AUTH-02/03): an unknown username
    still costs one bcrypt verification against :data:`DUMMY_PASSWORD_HASH`, so
    the response time does not reveal which accounts exist. There is no lockout
    and no rate limit — bcrypt is the natural brake and the machine sits on a
    closed LAN (SPEC §3.2).

    Args:
        session: Open database session; committed when a token is issued.
        username: Submitted username.
        password: Submitted plaintext password. Never logged.
        client_ip: Client address, for the failure log line only.

    Returns:
        ``(raw_token, user)`` on success, or None on any credential failure.
    """
    user = session.scalar(select(User).where(User.username == username))

    if user is None:
        verify_password(password, DUMMY_PASSWORD_HASH)
        logger.warning("Login failed for username=%r from %s", username, client_ip)
        return None

    if not verify_password(password, user.password_hash):
        logger.warning("Login failed for username=%r from %s", username, client_ip)
        return None

    expires_at = datetime.now(UTC) + timedelta(minutes=get_settings().token_expire_minutes)
    raw_token = create_access_token(user_id=user.id, role=user.role.value, expires_at=expires_at)

    session.add(UserToken(user_id=user.id, token_hash=hash_token(raw_token), expires_at=expires_at))
    session.commit()

    purge_expired_tokens(session, user.id)

    logger.info("User %r authenticated from %s", username, client_ip)
    return raw_token, user


def resolve_token(session: Session, raw_token: str) -> User | None:
    """Return the user a raw Access Token belongs to, or None.

    Order matters: the signature and ``exp`` are checked *before* the database
    is touched, so a forged token costs one HMAC and no query. Then the stored
    hash decides whether the token is still live — a JWT that verifies but was
    revoked at logout, or whose row is gone, is not a session.

    Args:
        session: Open database session (read-only here).
        raw_token: The raw bearer token as presented.

    Returns:
        The owning user, or None if the token is invalid, expired or revoked.
    """
    try:
        claims = decode_access_token(raw_token)
    except InvalidTokenError:
        # Covers ExpiredSignatureError too — it is a subclass.
        return None

    try:
        user_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError):
        return None

    stored = session.scalar(select(UserToken).where(UserToken.token_hash == hash_token(raw_token)))
    if stored is None or stored.revoked_at is not None:
        return None

    # SQLite hands `expires_at` back naive even though it was written as UTC;
    # comparing that to an aware `now` raises TypeError. Re-attach UTC first —
    # the same trap ReadingOut._ensure_utc works around in the devices API.
    expires_at = stored.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        return None

    return session.get(User, user_id)


def revoke_token(session: Session, token_hash: str) -> None:
    """Mark a token as revoked. Idempotent — re-revoking is a no-op."""
    stored = session.scalar(select(UserToken).where(UserToken.token_hash == token_hash))
    if stored is None or stored.revoked_at is not None:
        return

    stored.revoked_at = datetime.now(UTC)
    session.commit()
    logger.info("Access Token revoked (hash prefix %s…)", token_hash[:8])


def purge_expired_tokens(session: Session, user_id: int) -> None:
    """Delete this user's tokens that have already expired.

    Housekeeping on the login path, so ``user_tokens`` cannot grow without
    bound on a machine that has been logging in for years. Only the user's own
    rows are touched — a login is not the place to sweep the whole table.
    """
    session.execute(delete(UserToken).where(UserToken.user_id == user_id, UserToken.expires_at < datetime.now(UTC)))
    session.commit()
