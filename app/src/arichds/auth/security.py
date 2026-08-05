"""Password hashes, token hashes and JWTs — the crypto boundary of M2-1.

bcrypt directly (no passlib) and **PyJWT**, not python-jose: jose is effectively
unmaintained, PyJWT is the maintained standard (docs/lib-notes/m2-auth.md,
verified against the installed PyJWT 2.13.0 / bcrypt 5.0.0).

Two traps this module owns:

* bcrypt 5.0 **raises** ``ValueError`` for passwords over 72 *bytes* where older
  versions truncated silently. The API rejects those at validation time
  (``arichds.api.auth.Password``); :func:`verify_password` also treats them as a
  plain mismatch so a login attempt can never 500.
* ``jwt.decode`` requires ``algorithms=[...]`` — plural, and omitting it is the
  classic PyJWT footgun.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import UTC, datetime

import bcrypt
import jwt

from arichds.config import get_settings

logger = logging.getLogger(__name__)

#: The only signing algorithm this build issues or accepts.
JWT_ALGORITHM: str = "HS256"

#: Length of the generated signing secret, in bytes of entropy.
JWT_SECRET_BYTES: int = 64


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain*.

    Args:
        plain: The plaintext password, already length-validated by the API.

    Returns:
        The bcrypt hash as a utf-8 string.

    Raises:
        ValueError: If *plain* is longer than 72 bytes (bcrypt 5.0).
    """
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return whether *plain* matches the bcrypt *hashed*.

    Any bcrypt failure — a malformed stored hash, or a submitted password over
    72 bytes — is a mismatch, not an error: this runs on the login path, where
    the only two honest answers are "yes" and "no".
    """
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


#: Pre-computed hash used when the username is unknown, so a login attempt costs
#: the same bcrypt work whether or not the user exists (v1 INV-AUTH-02/03).
#: Computed once at import — it is a constant, not license-derived state, so
#: ADR 0001 does not apply.
DUMMY_PASSWORD_HASH: str = hash_password("arichds-dummy-password")


def hash_token(raw: str) -> str:
    """Return the SHA-256 hex digest of a raw Access Token (v1 INV-AUTH-04)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_jwt_secret() -> str:
    """Return the JWT signing secret, generating and persisting one if needed.

    Resolution order (ADR 0003):

    1. ``ARICHDS_JWT_SECRET`` when set — the escape hatch for an operator who
       wants to control it.
    2. ``%DATA_DIR%/secret/jwt_secret.key`` when it exists.
    3. Otherwise generate one and write it there atomically.

    Deliberately **not** cached: the file is read on login and on token
    verification only, where bcrypt dominates the cost, and caching would freeze
    the value across tests the same way caching license state would break
    ADR 0001.
    """
    settings = get_settings()
    configured = (settings.jwt_secret or "").strip()
    if configured:
        return configured

    path = settings.jwt_secret_path
    if path.exists():
        stored = path.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    secret = secrets.token_urlsafe(JWT_SECRET_BYTES)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write via a temp file in the same directory and rename: a half-written
    # secret file would lock every user out until it was deleted by hand.
    temp_path = path.with_suffix(f".{os.getpid()}.tmp")
    temp_path.write_text(secret, encoding="utf-8")
    os.replace(temp_path, path)
    logger.info("Generated a new JWT signing secret at %s", path)
    return secret


def create_access_token(user_id: int, role: str, expires_at: datetime) -> str:
    """Sign an Access Token for *user_id*.

    The ``jti`` claim is not decoration: ``iat`` and ``exp`` are whole seconds,
    so without it two logins by the same user inside one second would produce a
    byte-identical token — and therefore a duplicate ``user_tokens.token_hash``,
    which is UNIQUE. Two browser tabs must be able to hold two live sessions.

    Args:
        user_id: The subject; encoded as a string, per the JWT spec.
        role: The user's role at issue time.
        expires_at: Absolute expiry (UTC). Also stored alongside the token hash.

    Returns:
        The encoded JWT.
    """
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": datetime.now(UTC),
        "exp": expires_at,
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and verify an Access Token.

    Args:
        token: The raw JWT.

    Returns:
        The claims.

    Raises:
        jwt.ExpiredSignatureError: The ``exp`` claim is in the past.
        jwt.InvalidTokenError: Bad signature, malformed token, wrong algorithm.
    """
    return jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
