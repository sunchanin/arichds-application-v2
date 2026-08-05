"""User Management — admin CRUD over accounts (M2-2).

Admin-only end to end: the guard sits on the *router*, like ``devices.py`` and
``license.py``, so an unauthenticated ``POST`` is refused 401 before its body is
validated rather than answering 422. Handlers that need to know *which* admin is
calling additionally take ``AdminDep``; FastAPI's per-request dependency cache
means the token is still resolved once.

Not on the Limited Mode allow-list, on purpose: user management is product
surface that an unlicensed machine should have frozen, and activation is the way
out. Only ``/api/auth`` and ``/api/license`` stay open there.

**Three self-targeting rules are the whole lockout defence.** An admin may not
delete itself (v1 INV-AUTHZ-02), change its own role, or reset its own password.
Because every endpoint here requires an admin actor and the actor can never
remove its own admin-ness, the number of admins cannot reach zero — so there is
deliberately **no "last admin" count query** anywhere; it would be dead code.
``tests/test_api_users.py::TestNoLockoutIsPossible`` pins that argument.

**There is no bootstrap-admin special case, and there must not be one.** User id
1 is an ordinary row: a second admin may delete or demote the first. Protecting
id 1 forever would make a forgotten or compromised first account permanently
unremovable on a machine that has no recovery path at all.

Deliberately not built:

* ``GET /api/users/{id}`` — the list already carries every field and the SPA has
  no detail view.
* pagination / search — v1 had them; this box holds a handful of accounts, and
  unrequested flexibility is against CLAUDE.md.
* a general ``PUT /api/users/{id}`` — it would force username-rename semantics
  nobody has asked for. Role and password each get their own narrow endpoint.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from arichds.api.auth import Password, Username, UserOut
from arichds.api.deps import AdminDep, SessionDep, require_admin
from arichds.api.envelope import ApiResponse
from arichds.auth import service
from arichds.auth.roles import Role
from arichds.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"], dependencies=[Depends(require_admin)])


class UserCreate(BaseModel):
    """Request body for adding an account.

    Attributes:
        username: The new account name, unique on this machine.
        password: The initial password. Never stored in the clear, never logged.
        role: ``admin`` or ``user``. Required on purpose — silently minting an
            admin because a field was omitted is not a default worth having.
    """

    username: Username
    password: Password
    role: Role


class RoleUpdate(BaseModel):
    """Request body for changing an account's role.

    Attributes:
        role: The role to move the account to.
    """

    role: Role


class PasswordReset(BaseModel):
    """Request body for an admin-set password.

    Attributes:
        new_password: The password to set on the target account.
    """

    new_password: Password


UserIdPath = Annotated[int, Path(ge=1, description="User id")]


def _load_user(session: Session, user_id: int) -> User:
    """Return the target account, or raise the 404 every handler here shares."""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No user with id {user_id}")
    return user


def _refuse_self(admin: User, user_id: int, detail: str) -> None:
    """Refuse an operation the acting admin aimed at its own account.

    Checked in the API layer rather than the service because it is an
    authorization decision about *the caller* — ``deps.require_admin`` is the
    precedent, and the service functions deliberately take no actor. Runs before
    the 404 lookup, which cannot fire for this id anyway: the actor exists by
    definition.

    Raises:
        HTTPException: 400 when *user_id* is the acting admin's own id.
    """
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.get("")
def list_users(session: SessionDep) -> ApiResponse[list[UserOut]]:
    """List every account on this machine, oldest first."""
    return ApiResponse.ok([UserOut.model_validate(user) for user in service.list_users(session)])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, session: SessionDep, admin: AdminDep) -> ApiResponse[UserOut]:
    """Add an account.

    Raises:
        HTTPException: 409 when the username is taken.
    """
    user = service.create_user(session, payload.username, payload.password, payload.role)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user named {payload.username!r} already exists.",
        )

    logger.info("Admin %r created user %r (role=%s)", admin.username, user.username, user.role.value)
    return ApiResponse.ok(UserOut.model_validate(user))


@router.patch("/{user_id}/role")
def set_user_role(
    user_id: UserIdPath, payload: RoleUpdate, session: SessionDep, admin: AdminDep
) -> ApiResponse[UserOut]:
    """Change an account's role.

    An admin may not change its own role: demoting the last admin would be an
    unrecoverable lockout, and role is read live from the database on every
    request, so it would bite on the very next call.

    Raises:
        HTTPException: 400 when targeting yourself, 404 if no such user.
    """
    _refuse_self(admin, user_id, "You cannot change your own role.")
    user = _load_user(session, user_id)

    updated = service.set_role(session, user, payload.role)
    logger.info("Admin %r changed user %r role to %s", admin.username, updated.username, updated.role.value)
    return ApiResponse.ok(UserOut.model_validate(updated))


@router.post("/{user_id}/reset-password")
def reset_user_password(
    user_id: UserIdPath, payload: PasswordReset, session: SessionDep, admin: AdminDep
) -> ApiResponse[bool]:
    """Set a new password for an account and sign it out everywhere.

    Every live session of the target is revoked — this overrules v1, which left
    them open. The password was changed by someone other than the owner, so it
    is either a forgotten-password recovery or a suspected compromise, and
    leaving sessions alive defeats both.

    An admin may not reset *its own* password here — that would be a hole
    straight through the current-password check on ``POST
    /api/auth/change-password``: someone holding a stolen token could set a new
    password without knowing the old one.

    Raises:
        HTTPException: 400 when targeting yourself, 404 if no such user.
    """
    _refuse_self(admin, user_id, "Use Change password to change your own password.")
    user = _load_user(session, user_id)

    service.set_password(session, user, payload.new_password)
    logger.info("Admin %r reset the password of user %r", admin.username, user.username)
    return ApiResponse.ok(True)


@router.delete("/{user_id}")
def delete_user(user_id: UserIdPath, session: SessionDep, admin: AdminDep) -> ApiResponse[bool]:
    """Delete an account, ending every session it had open.

    This is v2's version of v1's "deactivate": there is no ``is_active`` column,
    and the FK cascade on ``user_tokens`` carries the sessions away with the row
    (v1 INV-DATA-02).

    An admin may not delete itself (v1 INV-AUTHZ-02).

    Raises:
        HTTPException: 400 when targeting yourself, 404 if no such user.
    """
    _refuse_self(admin, user_id, "You cannot delete your own account.")
    user = _load_user(session, user_id)

    username = user.username
    service.delete_user(session, user)
    logger.info("Admin %r deleted user %r", admin.username, username)
    return ApiResponse.ok(True)
