"""HTTP API. Every route lives under ``/api``; ``/`` is the SPA."""

from arichds.api.envelope import ApiError, ApiResponse

__all__ = ["ApiError", "ApiResponse"]
