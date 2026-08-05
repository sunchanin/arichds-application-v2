"""Auth endpoints — Setup, Login, Logout, Me (M2-1) and Change password (M2-2).

The first-run walk is **Setup → Login → Activation** (SPEC §3.2). Setup is open
only while zero users exist and is permanently closed afterwards; re-running it
is a 409, not a 403, because "already done" is a conflict rather than a
permissions problem.

This whole router is on the Limited Mode allow-list
(``arichds.licensing.middleware.ALWAYS_ALLOWED_PREFIXES``). That is not an
oversight: if login were license-gated, a machine whose lease lapsed could never
be logged into, and therefore never re-activated.

``POST /change-password`` lives here rather than on ``/api/users`` for two
reasons: it is the only endpoint of M2-2 that is *not* admin-only, so it would
break that router's clean router-level ``require_admin``; and being on the
allow-list above means a user on a lapsed machine can still change their
password, while ``/api/users`` is deliberately frozen by Limited Mode.

Error style follows M1 — ``HTTPException`` with a ``detail`` string, no new
error-code taxonomy. The status code carries the meaning: 401 for any credential
or token failure, 403 for the wrong role, 409 for Setup-already-done, 422 for
validation.

**One exception to "401 for any credential failure"** (M2-2): a wrong
``current_password`` on ``POST /change-password`` answers **400**, not 401. The
SPA's request helper clears the stored session on any 401 that carried a token,
so a 401 there would sign the operator out over a typo — and it would be
misleading anyway: the token is perfectly good, a submitted *field* is wrong.
401 is reserved for "your token is bad".
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from arichds.api.deps import BearerDep, CurrentUserDep, SessionDep
from arichds.api.envelope import ApiResponse
from arichds.auth import service
from arichds.auth.roles import Role
from arichds.auth.security import hash_token, verify_password
from arichds.constants import BCRYPT_MAX_PASSWORD_BYTES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _within_bcrypt_limit(value: str) -> str:
    """Reject a password bcrypt would refuse to hash.

    Pydantic's ``max_length`` counts *characters*; bcrypt 5.0 counts **bytes**
    and raises past 72 of them. A 40-character non-ASCII password can therefore
    pass a character limit and still blow up inside the hash call, so the check
    has to be on the encoded length. Raising ``ValueError`` here turns it into a
    clean 422 instead of a 500.
    """
    if len(value.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes when UTF-8 encoded.")
    return value


#: Every password field in the API uses this — one rule, one place.
Password = Annotated[str, Field(min_length=8), AfterValidator(_within_bcrypt_limit)]

#: Usernames are short and unique per machine.
Username = Annotated[str, Field(min_length=3, max_length=64)]


class SetupStatus(BaseModel):
    """Whether the machine still needs its bootstrap admin.

    Attributes:
        setup_required: True while zero accounts exist.
    """

    setup_required: bool


class Credentials(BaseModel):
    """Username and password, as submitted by Setup and Login.

    Attributes:
        username: The account name.
        password: The plaintext password. Never stored, never logged.
    """

    username: Username
    password: Password


class UserOut(BaseModel):
    """A user as the API exposes it. The password hash is never included.

    Attributes:
        id: Surrogate key.
        username: The account name.
        role: ``admin`` or ``user``.
        created_at: When the account was created (UTC).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Role
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _ensure_utc(cls, value: datetime) -> datetime:
        """Re-attach UTC to the naive datetime SQLite hands back.

        Without this the same account would serialise with an offset from
        ``POST /setup`` (where the value is still the one just written) and
        without one from ``GET /me`` (where it has been round-tripped through
        SQLite).
        """
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class PasswordChange(BaseModel):
    """Request body for changing your own password.

    ``current_password`` is a plain ``str`` on purpose: it is only ever
    compared, never hashed, and length-validating it would turn a wrong guess
    into a 422 that leaks the shape of the stored password.

    Attributes:
        current_password: The password in force right now.
        new_password: The password to replace it with.
    """

    current_password: str
    new_password: Password

    @model_validator(mode="after")
    def _must_differ(self) -> PasswordChange:
        """Reject a "change" that changes nothing (v1 INV-DATA-04's companion rule)."""
        if self.new_password == self.current_password:
            raise ValueError("New password must differ from the current password.")
        return self


class LoginResult(BaseModel):
    """A successful login.

    Attributes:
        access_token: The raw JWT. Only its SHA-256 hash is stored server-side.
        token_type: Always ``"bearer"``.
        user: Who was logged in.
    """

    access_token: str
    token_type: str = "bearer"
    user: UserOut


def _client_ip(request: Request) -> str | None:
    """Return the caller's address for the login log line, if known."""
    return request.client.host if request.client else None


@router.get("/check-setup")
def check_setup(session: SessionDep) -> ApiResponse[SetupStatus]:
    """Report whether first-run Setup is still open.

    Open to everyone by necessity — it is the question the SPA has to ask
    before it can know whether anyone can log in at all.
    """
    return ApiResponse.ok(SetupStatus(setup_required=service.user_count(session) == 0))


@router.post("/setup", status_code=status.HTTP_201_CREATED)
def setup(payload: Credentials, session: SessionDep) -> ApiResponse[UserOut]:
    """Create the bootstrap admin. Works once, then never again.

    Raises:
        HTTPException: 409 once any account exists.
    """
    user = service.create_initial_admin(session, payload.username, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup has already been completed on this machine.",
        )

    return ApiResponse.ok(UserOut.model_validate(user))


@router.post("/login")
def login(payload: Credentials, session: SessionDep, request: Request) -> ApiResponse[LoginResult]:
    """Exchange credentials for an Access Token.

    Every failure — unknown username, wrong password — answers with the same
    401 and the same message, and costs the same bcrypt work (v1
    INV-AUTH-02/03). Distinguishing them would turn this endpoint into an
    account-enumeration oracle.

    Raises:
        HTTPException: 401 on any credential failure.
    """
    result = service.authenticate(session, payload.username, payload.password, client_ip=_client_ip(request))
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_token, user = result
    return ApiResponse.ok(
        LoginResult(access_token=raw_token, user=UserOut.model_validate(user)),
    )


@router.post("/logout")
def logout(current_user: CurrentUserDep, credentials: BearerDep, session: SessionDep) -> ApiResponse[bool]:
    """Revoke the token this request presented. Idempotent.

    Only the presenting token is revoked; a session open in another browser
    stays open, which is what an operator with a wall display and a laptop
    expects.
    """
    if credentials is not None:
        service.revoke_token(session, hash_token(credentials.credentials))
    logger.info("User %r logged out", current_user.username)
    return ApiResponse.ok(True)


@router.post("/change-password")
def change_password(
    payload: PasswordChange,
    current_user: CurrentUserDep,
    credentials: BearerDep,
    session: SessionDep,
) -> ApiResponse[bool]:
    """Change your own password, keeping this session and ending the others.

    The current password is verified first (v1 INV-DATA-04) — that check is the
    only thing standing between a stolen token and a permanent account takeover.
    Every other live session of this user is then revoked, because they were
    opened under a password that is no longer in force; the presenting one
    survives so the operator is not signed out of the form they just submitted.

    Available to every role. Admins do **not** reset their own password through
    ``/api/users/{id}/reset-password`` — that path is refused for the actor's own
    id precisely so it cannot be used to bypass the check above.

    Raises:
        HTTPException: 400 when the current password is wrong.
    """
    if not verify_password(payload.current_password, current_user.password_hash):
        # Deliberately **400, not v1's 401**. A 401 here would be read by the
        # SPA's request helper as "your token went bad" and would clear the
        # session, signing the operator out over a typo. The token is fine; a
        # submitted *field* is wrong.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    keep = hash_token(credentials.credentials) if credentials is not None else None
    service.set_password(session, current_user, payload.new_password, keep_token_hash=keep)
    logger.info("User id=%s changed their own password", current_user.id)
    return ApiResponse.ok(True)


@router.get("/me")
def get_me(current_user: CurrentUserDep) -> ApiResponse[UserOut]:
    """Return the caller's own account.

    Exists so the SPA can *validate* a token restored from storage rather than
    trust it: an 8-hour token in localStorage may well have been revoked or
    expired since the tab was last open.
    """
    return ApiResponse.ok(UserOut.model_validate(current_user))
