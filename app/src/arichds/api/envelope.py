"""The ``{success, data, error}`` response envelope.

Carried over from v1 so the SPA has one shape to handle, and deliberately thin:
it carries a success flag, a payload, and a structured error — nothing else.

The Limited Mode 403 body (``arichds.licensing.middleware``) matches this shape
too, so a licence rejection is not a special case in the frontend.
"""

from __future__ import annotations

from pydantic import BaseModel


class ApiError(BaseModel):
    """A structured error.

    Attributes:
        code: Stable machine-readable code, e.g. ``LICENSE_INVALID``.
        message: Human-readable message, English only (SPEC §2 — no i18n).
        reason: Optional detail code that refines *code*.
    """

    code: str
    message: str
    reason: str | None = None


class ApiResponse[T](BaseModel):
    """Uniform envelope for every ``/api`` response.

    Attributes:
        success: False only when *error* is set.
        data: The payload, or None on failure.
        error: The error, or None on success.
    """

    success: bool = True
    data: T | None = None
    error: ApiError | None = None

    @classmethod
    def ok(cls, data: T) -> ApiResponse[T]:
        """Build a success envelope around *data*."""
        return cls(success=True, data=data, error=None)

    @classmethod
    def failed(cls, code: str, message: str, reason: str | None = None) -> ApiResponse[T]:
        """Build a failure envelope."""
        return cls(success=False, data=None, error=ApiError(code=code, message=message, reason=reason))
