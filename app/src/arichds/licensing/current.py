"""Process-wide holder for the LicenseService (M6b, issue #22).

Background code with no request and no ``app.state`` — the eager capture path
in :mod:`arichds.acquisition.billing` — needs to ask "is this feature enabled"
without a ``Request`` to resolve the per-request dependency from. Same shape
as :mod:`arichds.acquisition.locks`'s ``_PROCESS_LOCKS`` / ``endpoint_locks()``:
one process-wide slot, set by the lifespan (``main.py``) once the service
exists and cleared in its ``finally`` so nothing outlives the app.

Holds the **service**, never a state snapshot — every read still calls
:meth:`~arichds.licensing.service.LicenseService.current_state`, which
re-evaluates on staleness (ADR 0001). No service published means "not booted
yet" or "running outside the app" (a script, a test that drives the
acquisition module directly without the lifespan) — in both cases
:func:`~arichds.licensing.features.feature_enabled` treats that as "off", so
no capture file is ever written by accident.
"""

from __future__ import annotations

import threading

from arichds.licensing.service import LicenseService

_lock = threading.Lock()
_service: LicenseService | None = None


def set_current_license_service(service: LicenseService | None) -> None:
    """Publish (or, with ``None``, clear) the process-wide LicenseService."""
    global _service  # noqa: PLW0603
    with _lock:
        _service = service


def current_license_service() -> LicenseService | None:
    """Return the process-wide LicenseService, or ``None`` if never published."""
    with _lock:
        return _service
