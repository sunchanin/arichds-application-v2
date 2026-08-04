"""Shared FastAPI dependencies.

Everything the request handlers need comes from ``app.state``, which the
lifespan populates. Reading the LicenseService per request (rather than binding
a module-level singleton at import) is what keeps ADR 0001 honest: nothing here
caches license-derived state.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from arichds.acquisition.poller import Poller
from arichds.db.session import get_session_factory
from arichds.licensing.service import LicenseService


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


SessionDep = Annotated[Session, Depends(get_db_session)]
LicenseServiceDep = Annotated[LicenseService, Depends(get_license_service)]
PollerDep = Annotated[Poller, Depends(get_poller)]
