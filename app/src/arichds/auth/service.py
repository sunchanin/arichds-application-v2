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
from sqlalchemy import delete, func, select, update
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


def list_users(session: Session) -> list[User]:
    """Return every account, oldest first."""
    return list(session.scalars(select(User).order_by(User.id)).all())


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


def create_user(session: Session, username: str, password: str, role: Role) -> User | None:
    """Create an account for an admin, unless the username is taken.

    Mirrors :func:`create_initial_admin`'s belt and braces: the pre-check
    answers the common case, and the UNIQUE constraint is what makes it atomic
    when two admins submit the same name at the same moment.

    Args:
        session: Open database session; committed on success.
        username: Desired username, already validated by the API.
        password: Plaintext password, already validated by the API.
        role: The role to grant.

    Returns:
        The created user, or None when the username is already taken.
    """
    if session.scalar(select(User).where(User.username == username)) is not None:
        return None

    user = User(username=username, password_hash=hash_password(password), role=role)
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        logger.info("Rejected creating user %r — the username was taken concurrently", username)
        return None

    session.refresh(user)
    return user


def set_role(session: Session, user: User, role: Role) -> User:
    """Change *user*'s role and return the refreshed row.

    Nothing is revoked: ``require_admin`` reads ``user.role`` off the database
    row that :func:`resolve_token` loads, so the change binds on the target's
    very next request with the token they already hold. The JWT's ``role`` claim
    is informational and is never consulted for authorization.
    """
    user.role = role
    session.commit()
    session.refresh(user)
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
    # the same trap DeviceOut._ensure_utc works around in the devices API.
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


def revoke_user_tokens(session: Session, user_id: int, keep_token_hash: str | None = None) -> None:
    """Revoke every live token of *user_id*, optionally sparing one.

    One bulk ``UPDATE`` rather than a loop: this runs while an operator waits on
    a password form, and the number of live sessions is not bounded by anything
    the API controls.

    The commit here covers anything already pending on *session* — which is the
    point when :func:`set_password` calls it, since the two writes have to land
    together or not at all.

    Args:
        session: Open database session; committed here, along with any pending
            changes the caller has already staged on it.
        user_id: Whose tokens to revoke.
        keep_token_hash: The hash of a token to leave alive — the one the caller
            presented, when they are changing their own password. ``None``
            revokes all of them, which is what an admin reset does.
    """
    conditions = [UserToken.user_id == user_id, UserToken.revoked_at.is_(None)]
    if keep_token_hash is not None:
        conditions.append(UserToken.token_hash != keep_token_hash)

    session.execute(update(UserToken).where(*conditions).values(revoked_at=datetime.now(UTC)))
    session.commit()


def set_password(session: Session, user: User, password: str, keep_token_hash: str | None = None) -> None:
    """Store a new password for *user* and revoke their live sessions.

    SPEC §3.2 / v1 INV-DATA-04: a password change invalidates the sessions that
    were opened under the old one. The single knob is which session survives —
    the presenting one when a user changes their own password, none at all when
    an admin resets someone else's.

    **Both writes share one transaction, and must keep sharing it** (v1
    ``repository.update_password_and_revoke_other_tokens`` did the same). There
    is deliberately no commit between them: a crash in that gap would leave the
    password changed while every old session stayed live for up to its full
    8 hours — exactly the outcome the admin-reset path exists to prevent, and
    the operator would have been told the account was secured. The bulk UPDATE
    below autoflushes the ``users`` row into the same transaction, and the hash
    is computed *before* that flush, so no write lock is held across bcrypt.

    Args:
        session: Open database session; committed here.
        user: The account to change.
        password: The new plaintext password, already validated by the API.
        keep_token_hash: Hash of the one token to spare, or None to revoke all.
    """
    user.password_hash = hash_password(password)
    revoke_user_tokens(session, user.id, keep_token_hash=keep_token_hash)


def delete_user(session: Session, user: User) -> None:
    """Delete an account. Its tokens go with it.

    ``user_tokens.user_id`` is ``ON DELETE CASCADE`` and every connection runs
    with ``PRAGMA foreign_keys=ON`` (``arichds.db.session``), so the token rows
    disappear in the same statement and :func:`resolve_token` stops finding
    them — a live session of a deleted account is 401 on its next request. A
    hand-written revoke-then-delete would only duplicate that.
    """
    session.delete(user)
    session.commit()


def purge_expired_tokens(session: Session, user_id: int) -> None:
    """Delete this user's tokens that have already expired.

    Housekeeping on the login path, so ``user_tokens`` cannot grow without
    bound on a machine that has been logging in for years. Only the user's own
    rows are touched — a login is not the place to sweep the whole table.
    """
    session.execute(delete(UserToken).where(UserToken.user_id == user_id, UserToken.expires_at < datetime.now(UTC)))
    session.commit()
