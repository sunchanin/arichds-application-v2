"""Shared FastAPI dependencies, including the auth guard.

Everything the request handlers need comes from ``app.state``, which the
lifespan populates. Reading the LicenseService per request (rather than binding
a module-level singleton at import) is what keeps ADR 0001 honest: nothing here
caches license-derived state.

The guard is a **dependency**, not middleware (M2-1). Middleware could not hand
the authenticated user to a handler, would duplicate the path matching Limited
Mode already does, and would stay invisible in OpenAPI. What middleware *would*
have bought — "closed by default, including for routers nobody has written
yet" — is bought instead by the route-table sweep in ``tests/test_auth_guard.py``.

Nothing here touches the LicenseService: authentication and licensing are
independent gates, and a machine in Limited Mode must still be loggable-into.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from arichds.acquisition.poller import Poller
from arichds.auth.roles import Role
from arichds.auth.service import resolve_token
from arichds.config import get_settings
from arichds.db.models import User
from arichds.db.session import get_session_factory
from arichds.jobs.scheduler import Scheduler
from arichds.licensing.features import feature_enabled
from arichds.licensing.service import LicenseService

#: ``auto_error=False`` on purpose: with the default, FastAPI answers a missing
#: ``Authorization`` header with **403**, and "no token means 401" is an
#: acceptance criterion of this slice. Extracting the credentials ourselves is
#: what lets the correct status and ``WWW-Authenticate`` header come back.
bearer_scheme = HTTPBearer(auto_error=False)


def get_db_session() -> Iterator[Session]:
    """Yield a database Session, closed after the response is sent."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def get_license_service(request: Request) -> LicenseService:
    """Return the process LicenseService from application state."""
    return request.app.state.license_service


def get_poller(request: Request) -> Poller:
    """Return the process Poller from application state."""
    return request.app.state.poller


def get_scheduler(request: Request) -> Scheduler:
    """Return the process Scheduler from application state."""
    return request.app.state.scheduler


SessionDep = Annotated[Session, Depends(get_db_session)]
LicenseServiceDep = Annotated[LicenseService, Depends(get_license_service)]
PollerDep = Annotated[Poller, Depends(get_poller)]
SchedulerDep = Annotated[Scheduler, Depends(get_scheduler)]
BearerDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def _unauthenticated(detail: str) -> HTTPException:
    """Build the 401 every authentication failure returns.

    ``WWW-Authenticate: Bearer`` is not decoration — it is what makes the 401 a
    correct HTTP challenge rather than a bare rejection.
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(credentials: BearerDep, session: SessionDep) -> User:
    """Resolve the caller's Access Token into a user, or refuse with 401.

    Missing, malformed, expired and revoked tokens all end the same way. The
    distinction is deliberately not exposed: a caller holding a bad token has
    exactly one useful next step either way, and telling them *which* kind of
    bad it is only helps someone probing.

    Raises:
        HTTPException: 401 when no usable token was presented.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthenticated("Not authenticated")

    user = resolve_token(session, credentials.credentials)
    if user is None:
        raise _unauthenticated("Invalid or expired token")

    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUserDep) -> User:
    """Require the caller to be an ``admin``, or refuse with 403.

    Depends on :func:`get_current_user`, so FastAPI's per-request dependency
    cache validates the token once even when a route carries both.

    Raises:
        HTTPException: 403 when the caller is authenticated but not an admin.
    """
    if user.role is not Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires an administrator account.",
        )
    return user


AdminDep = Annotated[User, Depends(require_admin)]


class FeatureDisabledError(Exception):
    """Raised by :func:`require_feature` when *feature* is not enabled.

    A plain exception, not :class:`~fastapi.HTTPException`, because the
    response needs the ``{success, data, error}`` envelope shape with
    ``code="FEATURE_DISABLED"`` and ``reason=<feature key>`` (decision 5,
    issue #22) — a bare ``HTTPException`` only renders ``{"detail": ...}``.
    Translated to a 403 by the handler registered in
    :func:`~arichds.main.create_app`.
    """

    def __init__(self, feature: str) -> None:
        self.feature = feature
        super().__init__(f"Feature {feature!r} is not enabled for this deployment.")


def require_feature(name: str):  # noqa: ANN201 — returns a dependency function, not a fixed type.
    """Return a dependency enforcing that feature *name* is enabled (M6b, issue #22).

    Reads ``.env FEATURES ∩ license features`` live through the
    :class:`~arichds.licensing.service.LicenseService` on every call (ADR
    0001) — never a cached snapshot. Router-level use, mirroring v1's
    ``require_feature`` (``api/dependencies.py:110-140``)::

        router = APIRouter(
            ...,
            dependencies=[Depends(get_current_user), Depends(require_feature("billing"))],
        )

    This **refines an already-valid license**: an invalid one is blocked
    wholesale by ``LimitedModeMiddleware`` (403 ``LICENSE_INVALID``) before
    any dependency on the route runs.

    Args:
        name: The feature key, e.g. ``"billing"``.

    Returns:
        A dependency function raising :class:`FeatureDisabledError` when
        *name* is not in the effective feature set.
    """

    def _check(license_service: LicenseServiceDep) -> None:
        if not feature_enabled(name, license_service=license_service, settings=get_settings()):
            raise FeatureDisabledError(name)

    return _check
