"""Health endpoint — reachable in Limited Mode by design.

SPEC §3.9: health stays available when the license is invalid, so monitoring
and the installer can tell "unlicensed" apart from "dead".
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from arichds import __version__
from arichds.api.envelope import ApiResponse

router = APIRouter(prefix="/api/health", tags=["health"])


class HealthStatus(BaseModel):
    """Liveness payload.

    Attributes:
        status: Always ``"ok"`` when the process is serving.
        version: Application version.
    """

    status: str
    version: str


@router.get("")
def get_health() -> ApiResponse[HealthStatus]:
    """Report that the process is up.

    Deliberately says nothing about the license — that is
    ``GET /api/license/status``'s job, and a health probe should not flap
    because a lease lapsed.
    """
    return ApiResponse.ok(HealthStatus(status="ok", version=__version__))
