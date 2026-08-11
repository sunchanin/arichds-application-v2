"""``GET``/``PUT /api/settings/display`` — the machine-wide display-unit
setting (kW/kWh vs W/Wh; a CR, not part of any milestone's original shape).

Modelled directly on ``GET``/``PUT /api/billing/settings``
(:mod:`arichds.api.billing`): ``GET`` is any authenticated caller — reading a
setting is not admin-only there either — and ``PUT`` is admin-only. Unlike
``capture_dir``, the value has no free-form validation of its own: it is one
of exactly two literals, so the request/response models declare that as a
``Literal`` type and pydantic does the rejecting — there is no hand-rolled
check here to drift from the model.

**The stored value and every readings API payload never change** — this
setting only ever affects how a value is *rendered*: the web UI (kW/kWh vs
W/Wh columns) and the capture PDF/xlsx renderers
(:mod:`arichds.capture._render_shared`). Re-interpreting a reading on the
read path would be exactly the violation CLAUDE.md's write-time
normalization invariant forbids — the conversion lives at render time only,
in two places (TypeScript and Python), deliberately.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from arichds.api.deps import AdminDep, SessionDep, get_current_user
from arichds.api.envelope import ApiResponse
from arichds.capture._render_shared import DisplayUnitScale
from arichds.db.app_settings import DISPLAY_UNIT_SCALE_DEFAULT, DISPLAY_UNIT_SCALE_KEY, get_setting, set_setting

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(get_current_user)],
)


class DisplaySettingsOut(BaseModel):
    """What ``GET``/``PUT /api/settings/display`` return."""

    display_unit_scale: DisplayUnitScale


class DisplaySettingsIn(BaseModel):
    """The body ``PUT /api/settings/display`` takes."""

    display_unit_scale: DisplayUnitScale


@router.get("/display")
def get_display_settings(session: SessionDep) -> ApiResponse[DisplaySettingsOut]:
    """Return the current ``display_unit_scale`` — ``"kilo"`` on a fresh
    database (a missing key means today's behaviour, so an existing install
    is unchanged). Any authenticated caller.
    """
    value = get_setting(session, DISPLAY_UNIT_SCALE_KEY, DISPLAY_UNIT_SCALE_DEFAULT)
    return ApiResponse.ok(DisplaySettingsOut(display_unit_scale=value))  # type: ignore[arg-type]


@router.put("/display")
def put_display_settings(
    body: DisplaySettingsIn, session: SessionDep, _admin: AdminDep
) -> ApiResponse[DisplaySettingsOut]:
    """Save ``display_unit_scale`` — admin-only. The body's `Literal` type
    already refused anything but ``"kilo"``/``"base"`` with 422 before this
    runs.
    """
    set_setting(session, DISPLAY_UNIT_SCALE_KEY, body.display_unit_scale)
    session.commit()
    return ApiResponse.ok(DisplaySettingsOut(display_unit_scale=body.display_unit_scale))
