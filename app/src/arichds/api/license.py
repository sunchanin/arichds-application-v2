"""License endpoints — the Activation page's whole backend.

Open in Limited Mode (``/api/license/*`` is on the enforcement allow-list), for
the obvious reason: this is how a limited machine stops being limited. Passing
that gate is not the same as being public, though — from M2-1 both endpoints
require a token, and activation additionally requires an ``admin`` (SPEC §3.2),
so nobody on the site LAN can read this machine's Machine ID or replace its
license without an account.

Activation applies **immediately** (ADR 0001). The endpoint verifies, persists,
re-evaluates in place and lets the license listeners run — by the time the
response is written, the Poller is already coming up. No restart, and no "please
wait while the service restarts" in the UI.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from arichds.api.deps import AdminDep, LicenseServiceDep, get_current_user
from arichds.api.envelope import ApiResponse
from arichds.config import get_settings
from arichds.constants import ERROR_LICENSE_INVALID
from arichds.licensing.features import effective_features
from arichds.licensing.service import LicenseState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/license", tags=["license"], dependencies=[Depends(get_current_user)])


class LicenseStatus(BaseModel):
    """What the Activation page needs to render.

    Attributes:
        machine_id: This machine's Machine ID — shown with a copy button.
        state: ``"active"`` or ``"limited"``.
        reason: Why it is limited, or None when active.
        customer: Licensed customer name, when known.
        mode: ``"offline"`` or ``"leased"``, when known.
        expires_at: Lease end (UTC), or None for a non-expiring license.
        max_meters: Device quota, or None for unlimited.
        enabled_features: The **effective** feature set — ``.env FEATURES ∩
            licence`` — already resolved, sorted, and never null: an empty
            list means nothing is enabled, and the machine's own
            ``SELLABLE_FEATURE_KEYS`` are never re-derived on the client
            (issue 012, D1/D3). ``[]`` whenever the machine is not active,
            because a Limited Mode state carries ``features=None`` and that
            grandfathers everything (issue 012, D2).
        licensed_models: The licensed meter model keys (issue 015), **raw**
            rather than resolved — unlike ``enabled_features``, a model has
            no second source (no ``.env`` equivalent) to intersect against,
            so there is nothing to resolve and pretending otherwise would
            invent a concept. Sorted when it is a list. ``None`` means every
            catalogued model may be added (including on a Limited Mode
            state, whose ``models`` is always ``None`` — meaningless there,
            since Limited Mode blocks ``/api/*`` wholesale before any device
            handler runs); ``[]`` means none may be added.
    """

    machine_id: str
    state: str
    reason: str | None = None
    customer: str | None = None
    mode: str | None = None
    expires_at: datetime | None = None
    max_meters: int | None = None
    enabled_features: list[str] = Field(default_factory=list)
    licensed_models: list[str] | None = None


class ActivateRequest(BaseModel):
    """The pasted Activation Code.

    Attributes:
        code: One line of ``base64url(payload).base64url(signature)``.
            Surrounding whitespace is tolerated — people paste from email.
    """

    code: str = Field(min_length=1, description="The Activation Code issued by the vendor.")


def _enabled_features(state: LicenseState) -> list[str]:
    """The effective feature set for *state*, as the SPA's menu reads it.

    Deliberately the same two steps
    :func:`~arichds.licensing.features.feature_enabled` takes, in the same
    order, so the left nav and ``require_feature`` cannot drift about what
    "enabled" means (issue 012, D2): refuse everything unless the licence is
    valid — a Limited Mode state carries ``features=None``, which
    :func:`~arichds.licensing.features.effective_features` grandfathers — then
    intersect ``.env FEATURES`` with the licence.

    Settings are read per call via :func:`~arichds.config.get_settings` rather
    than injected, matching ``deps.require_feature`` and ``api.billing``; and
    the licence is read from the *passed* state, so nothing here is cached
    across an activation (ADR 0001).
    """
    if not state.valid:
        return []
    return sorted(effective_features(get_settings().enabled_feature_keys(), state.features))


def _licensed_models(state: LicenseState) -> list[str] | None:
    """The raw licensed model list for *state*, sorted — or ``None`` (decision C).

    Not gated on ``state.valid``: an invalid state's ``models`` is already
    ``None`` (``_from_verification``'s invalid branch carries none of the
    entitlement fields), so this needs no separate validity check the way
    :func:`_enabled_features` does — there is no "grandfather everything"
    risk to guard against, because ``None`` is already the correct answer
    for an inactive machine.
    """
    return sorted(state.models) if state.models is not None else None


def _to_status(machine_id: str, state: LicenseState) -> LicenseStatus:
    """Project a :class:`LicenseState` onto the API shape."""
    return LicenseStatus(
        machine_id=machine_id,
        state=state.state,
        reason=state.reason,
        customer=state.customer,
        mode=state.mode,
        expires_at=state.expires_at,
        max_meters=state.max_meters,
        enabled_features=_enabled_features(state),
        licensed_models=_licensed_models(state),
    )


@router.get("/status")
def get_license_status(license_service: LicenseServiceDep) -> ApiResponse[LicenseStatus]:
    """Return the Machine ID and the current license state.

    Any authenticated user (SPEC §3.2). The SPA polls this to decide whether to
    show the Activation page or the app shell, so it must always answer —
    including in Limited Mode — but only to someone who has logged in: the
    Machine ID identifies this computer and is not for every device on the LAN.
    """
    state = license_service.current_state()
    return ApiResponse.ok(_to_status(license_service.machine_id, state))


@router.post("/activate")
def activate_license(
    payload: ActivateRequest, license_service: LicenseServiceDep, admin: AdminDep
) -> ApiResponse[LicenseStatus]:
    """Verify and install an Activation Code. Takes effect immediately.

    Admin only (SPEC §3.2) — replacing the license is not something a viewer on
    the site LAN should be able to do.

    A rejected code changes nothing: the stored license and the current state
    are left exactly as they were, and the reason code comes back so the page
    can say *why* (wrong machine, expired, tampered) rather than just "invalid".

    Args:
        payload: The pasted code.

    Returns:
        Success with the new status, or a failure envelope carrying the reason.
    """
    state = license_service.activate(payload.code)
    status = _to_status(license_service.machine_id, state)

    if not state.valid:
        return ApiResponse[LicenseStatus](
            success=False,
            data=status,
            error={  # type: ignore[arg-type]
                "code": ERROR_LICENSE_INVALID,
                "message": "That Activation Code was not accepted.",
                "reason": state.reason,
            },
        )

    return ApiResponse.ok(status)
