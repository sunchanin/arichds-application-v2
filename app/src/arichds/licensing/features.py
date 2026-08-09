"""Feature entitlement — ``.env FEATURES ∩ license features`` (M6b, issue #22).

SPEC §3.9: enabled = ``.env FEATURES ∩ license features``. Ported from v1
``cewe-worker/src/features.py:22-40``, with the one deliberate difference ADR
0001 requires everywhere in v2: nothing here caches license *state* — every
call re-derives the answer from whatever :class:`~arichds.licensing.service.LicenseService`
says right now.

Two entry points read this module:

* :func:`~arichds.api.deps.require_feature` — a per-request FastAPI dependency,
  resolving the ``LicenseService`` off ``app.state`` (a real ``Request``).
* The eager capture path in :mod:`arichds.acquisition.billing` — background
  code with no request, which resolves the service from the process-wide
  holder in :mod:`arichds.licensing.current` instead.

Both call :func:`feature_enabled`, so the two paths cannot drift in what
"enabled" means.
"""

from __future__ import annotations

from arichds.config import Settings
from arichds.constants import SELLABLE_FEATURE_KEYS
from arichds.licensing.service import LicenseService


def effective_features(env_enabled: frozenset[str], license_features: list[str] | None) -> frozenset[str]:
    """Return the enabled feature keys for this deployment.

    Args:
        env_enabled: What ``.env FEATURES`` asks for
            (:meth:`Settings.enabled_feature_keys` — an empty/unset
            ``ARICHDS_FEATURES`` already expands to all of
            :data:`~arichds.constants.FEATURE_KEYS`).
        license_features: The signed sellable ceiling
            (:attr:`~arichds.licensing.service.LicenseState.features`).
            ``None`` — every license issued before this landed — grandfathers
            every sellable key; an **empty list** is meaningfully different: it
            means the license sold nothing sellable, and that is deliberately
            not the same as ``None``.

    Returns:
        The ops-only keys ``.env`` asked for (never license-governed) plus the
        sellable keys ``.env`` asked for that the license also permits.
    """
    ceiling = SELLABLE_FEATURE_KEYS if license_features is None else frozenset(license_features)
    return (env_enabled - SELLABLE_FEATURE_KEYS) | (env_enabled & SELLABLE_FEATURE_KEYS & ceiling)


def feature_enabled(name: str, *, license_service: LicenseService | None, settings: Settings) -> bool:
    """Whether feature *name* is enabled right now.

    Refines an **already-valid** license — an invalid one is blocked wholesale
    by ``LimitedModeMiddleware`` (403 ``LICENSE_INVALID``) before any feature
    check runs (SPEC §3.9), so a limited machine answers False here too rather
    than grandfathering everything through a ``None`` license state.

    Args:
        name: The feature key, e.g. ``"billing"``.
        license_service: The service to ask, or ``None`` when nothing has
            published one yet (a request before the lifespan ran, or
            background code outside the app entirely) — treated as "off",
            never as "grandfathered", so nothing writes a file or serves a
            page by accident.
        settings: The process :class:`~arichds.config.Settings`.

    Returns:
        True when *name* is in the effective feature set.
    """
    if license_service is None:
        return False
    state = license_service.current_state()
    if not state.valid:
        return False
    return name in effective_features(settings.enabled_feature_keys(), state.features)
