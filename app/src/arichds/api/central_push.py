"""``/api/settings/central-push`` — the Central Push configuration, the last
cycle's status, and the published contract (ADR 0024, ticket 07).

**Admin only, and gated by no licence feature key** (ADR 0024, Implementation
Decisions → Central Push → "Endpoints"): unlike most of `arichds.api.settings`,
even `GET` here is `AdminDep` rather than any authenticated user — the URL
and the fact that a token is set are machine-internal configuration, the
same reasoning `App Log` and the Data-out Destination pages already use, and
"no licence key" is deliberate: the push is a free capability, not a
sellable one.

Nothing here talks to the team's server — that is ticket 08's
`arichds.centralpush` cycle. This module owns the settings, the write-only
Push Token verification, the in-memory status read, and the contract render.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from arichds.api.deps import AdminDep, LicenseServiceDep, SessionDep, get_current_user
from arichds.api.envelope import ApiResponse
from arichds.centralpush.contract import Contract, render_contract
from arichds.centralpush.status import CycleStatus, last_cycle
from arichds.constants import ERROR_PUSH_TOKEN_INVALID
from arichds.db.app_settings import (
    CENTRAL_PUSH_TOKEN_DEFAULT,
    CENTRAL_PUSH_TOKEN_KEY,
    CENTRAL_PUSH_URL_DEFAULT,
    CENTRAL_PUSH_URL_KEY,
    get_setting,
    set_setting,
)
from arichds.licensing.push_token import verify_push_token

router = APIRouter(
    prefix="/api/settings/central-push",
    tags=["central-push"],
    dependencies=[Depends(get_current_user)],
)

#: One operator-actionable sentence per :mod:`arichds.licensing.push_token`
#: reason code, plus this endpoint's own `WRONG_MACHINE` — "message naming
#: the failed check" (ticket 07's own acceptance criterion), not just
#: "invalid".
_FAILURE_MESSAGES: dict[str, str] = {
    "MALFORMED": "That does not look like a Push Token.",
    "INVALID_SIGNATURE": "That Push Token's signature did not verify — it was tampered with, or signed by a different key.",
    "WRONG_PRODUCT": "That token was not issued as a Push Token.",
    "UNSUPPORTED_VERSION": "That Push Token's version is not supported by this build.",
    "LICENCE_CODE_NOT_PUSH_TOKEN": "That looks like an Activation Code or a Meter Activation Code, not a Push Token.",
    "WRONG_MACHINE": "That Push Token was issued for a different machine.",
}


class CycleStatusOut(BaseModel):
    """One completed Central Push cycle — see
    :class:`arichds.centralpush.status.CycleStatus`."""

    ran_at: datetime
    outcome: str
    meters_rows: int
    billing_rows: int
    energy_summary_rows: int
    load_profile_rows: int
    skipped_rows: int
    duration_sec: float
    error: str | None


class CentralPushOut(BaseModel):
    """What ``GET``/``PUT /api/settings/central-push`` return.

    **There is no ``token`` field, and one must never be added.** The Push
    Token is write-only, the same shape ``DatabaseDestinationOut`` uses for
    its password (``api/settings.py``): the two protections are that this
    model cannot serialise it, and that
    :class:`~arichds.logging_config.CredentialRedactionFilter` covers the
    ``central_push_token`` setting key.

    Attributes:
        url: ``""`` means the push is disabled (ADR 0024).
        token_set: Whether a non-empty token is stored. Deliberately not a
            length or a hash — neither is needed and each leaks something.
        last_cycle: The last cycle, or ``None`` if none has run. Always
            ``None`` before ticket 08 lands the job that populates it.
    """

    url: str
    token_set: bool
    last_cycle: CycleStatusOut | None


class CentralPushIn(BaseModel):
    """The body ``PUT /api/settings/central-push`` takes.

    Attributes:
        url: Not validated at save time — the same convention ``db_dest_host``
            uses. ``""`` disables the push.
        token: **Omitted or ``null`` keeps the stored token. An explicit
            non-empty string is verified before it is stored — see the
            endpoint docstring. An explicit empty string clears it.**
    """

    url: str
    token: str | None = None


def _status_out(status: CycleStatus | None) -> CycleStatusOut | None:
    """Project an in-memory :class:`CycleStatus` onto the API shape."""
    if status is None:
        return None
    return CycleStatusOut(
        ran_at=status.ran_at,
        outcome=status.outcome,
        meters_rows=status.meters_rows,
        billing_rows=status.billing_rows,
        energy_summary_rows=status.energy_summary_rows,
        load_profile_rows=status.load_profile_rows,
        skipped_rows=status.skipped_rows,
        duration_sec=status.duration_sec,
        error=status.error,
    )


def _current_settings(session: Session) -> CentralPushOut:
    """Read the two Central Push keys plus the in-memory last-cycle status."""
    return CentralPushOut(
        url=get_setting(session, CENTRAL_PUSH_URL_KEY, CENTRAL_PUSH_URL_DEFAULT),
        token_set=bool(get_setting(session, CENTRAL_PUSH_TOKEN_KEY, CENTRAL_PUSH_TOKEN_DEFAULT)),
        last_cycle=_status_out(last_cycle()),
    )


@router.get("")
def get_central_push_settings(session: SessionDep, _admin: AdminDep) -> ApiResponse[CentralPushOut]:
    """Return the Central Push configuration and the last cycle's status.

    Admin only — see the module docstring for why this, unlike most of
    ``/api/settings/*``, is not open to a ``user``.
    """
    return ApiResponse.ok(_current_settings(session))


@router.put("")
def put_central_push_settings(
    body: CentralPushIn, session: SessionDep, admin: AdminDep, license_service: LicenseServiceDep
) -> ApiResponse[CentralPushOut]:
    """Save the Central Push configuration. Admin only.

    **A non-empty ``token`` is verified on the spot** with
    :func:`~arichds.licensing.push_token.verify_push_token`, plus one check
    that verifier alone cannot make: the token's Machine ID must equal this
    machine's own — read through
    :attr:`~arichds.licensing.service.LicenseService.machine_id`, the one
    Machine ID source in this codebase, never a new derivation. A rejected
    token changes **nothing**: the stored URL and token are left exactly as
    they were, and the response's ``error.reason`` names which check failed
    so the page can say why rather than just "invalid" (ticket 07's own
    acceptance criterion).
    """
    if body.token is not None and body.token.strip():
        token = body.token.strip()
        verification = verify_push_token(token)
        if not verification.valid:
            reason = verification.reason or "MALFORMED"
            return ApiResponse[CentralPushOut].failed(
                ERROR_PUSH_TOKEN_INVALID, _FAILURE_MESSAGES.get(reason, "That Push Token was refused."), reason
            )
        if verification.machine_id != license_service.machine_id:
            return ApiResponse[CentralPushOut].failed(
                ERROR_PUSH_TOKEN_INVALID, _FAILURE_MESSAGES["WRONG_MACHINE"], "WRONG_MACHINE"
            )
        set_setting(session, CENTRAL_PUSH_TOKEN_KEY, token)
    elif body.token is not None:
        # An explicit empty string clears the stored token — the same
        # "omit to keep, empty string to clear" convention
        # `db_dest_password` uses.
        set_setting(session, CENTRAL_PUSH_TOKEN_KEY, "")

    set_setting(session, CENTRAL_PUSH_URL_KEY, body.url)
    session.commit()

    return ApiResponse.ok(_current_settings(session))


@router.get("/status")
def get_central_push_status(_admin: AdminDep) -> ApiResponse[CycleStatusOut | None]:
    """Return the last cycle's status — ``None`` until one has run.

    ADR 0008: no persisted job state, so this is always ``None`` before
    ticket 08 lands the scheduler job that populates it, and resets to
    ``None`` on every restart after.
    """
    return ApiResponse.ok(_status_out(last_cycle()))


@router.get("/contract")
def get_central_push_contract(_admin: AdminDep) -> ApiResponse[Contract]:
    """Return the published contract.

    Generated from the same payload models ticket 08's push cycle will
    serialize — see :func:`arichds.centralpush.contract.render_contract` —
    never a hand-written document that could drift from what the machine
    actually sends.
    """
    return ApiResponse.ok(render_contract())
