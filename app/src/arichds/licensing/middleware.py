"""Limited Mode enforcement.

SPEC §3.9: when the license is missing / expired / bound to another machine, the
API answers 403 ``LICENSE_INVALID``, polling stops, and the process stays alive.
Health and the SPA stay reachable so the web UI can actually *show* the problem
and offer the Activation page — a gate that locked the SPA out would lock the
user out of the only way to fix it.

Written as a pure ASGI middleware rather than ``BaseHTTPMiddleware``: this gate
either short-circuits with a small JSON body or steps aside entirely, so it never
needs to touch the response stream, and a pure ASGI class avoids
``BaseHTTPMiddleware``'s interaction with streaming responses and background
tasks.

The license state is read **per request** from the service (ADR 0001) — never
captured when the middleware is constructed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from arichds.constants import ERROR_LICENSE_INVALID
from arichds.licensing.service import LicenseService

#: Path prefixes that stay open in Limited Mode. Health so monitoring and the
#: installer can probe a limited machine; the license endpoints so the
#: Activation page can read the Machine ID and post a code.
ALWAYS_ALLOWED_PREFIXES: tuple[str, ...] = ("/api/health", "/api/license")

#: The gate only covers the API. Non-API paths (the SPA, its assets, the docs)
#: always pass.
GUARDED_PREFIX: str = "/api"


def is_guarded_path(path: str) -> bool:
    """Return whether *path* is subject to Limited Mode enforcement.

    Args:
        path: The request path, e.g. ``"/api/devices"``.

    Returns:
        True for ``/api/*`` except the always-allowed prefixes; False for every
        non-API path.
    """
    if not path.startswith(GUARDED_PREFIX):
        return False
    return not any(path == prefix or path.startswith(f"{prefix}/") for prefix in ALWAYS_ALLOWED_PREFIXES)


def license_invalid_response(reason: str | None) -> JSONResponse:
    """Build the 403 body returned in Limited Mode.

    Shape matches the API envelope so the SPA can handle it like any other
    error response.
    """
    payload: dict[str, Any] = {
        "success": False,
        "data": None,
        "error": {
            "code": ERROR_LICENSE_INVALID,
            "message": "This machine is in Limited Mode. Activate it to use the API.",
            "reason": reason,
        },
    }
    return JSONResponse(status_code=403, content=payload)


class LimitedModeMiddleware:
    """ASGI middleware that 403s guarded ``/api/*`` paths in Limited Mode."""

    def __init__(self, app: ASGIApp, service_provider: Callable[[], LicenseService | None]) -> None:
        """Initialise the gate.

        Args:
            app: The wrapped ASGI application.
            service_provider: Returns the current LicenseService, or None if it
                does not exist yet. A *callable* rather than the service itself
                because Starlette builds middleware while the app is assembled —
                before the lifespan has created anything — and because resolving
                per request is the only way to be sure no license-derived state
                was captured early (ADR 0001).
        """
        self.app = app
        self.service_provider = service_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Let the request through, or short-circuit with 403 LICENSE_INVALID."""
        if scope["type"] != "http" or not is_guarded_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        service = self.service_provider()
        if service is None:
            # The lifespan has not run yet (or failed). There is no license
            # state to enforce against; pass through to the handler, which will
            # fail loudly on its own missing state rather than silently 403.
            await self.app(scope, receive, send)
            return

        state = service.current_state()
        if state.valid:
            await self.app(scope, receive, send)
            return

        response = license_invalid_response(state.reason)
        await response(scope, receive, send)


__all__: list[str] = [
    "ALWAYS_ALLOWED_PREFIXES",
    "GUARDED_PREFIX",
    "LimitedModeMiddleware",
    "is_guarded_path",
    "license_invalid_response",
]
