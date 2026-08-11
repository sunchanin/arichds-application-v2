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

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from arichds.api.deps import AdminDep, SessionDep, get_current_user, require_feature
from arichds.api.envelope import ApiResponse
from arichds.capture._render_shared import DisplayUnitScale
from arichds.capture.paths import validate_directory_setting
from arichds.config import get_settings
from arichds.db.app_settings import (
    DISPLAY_UNIT_SCALE_DEFAULT,
    DISPLAY_UNIT_SCALE_KEY,
    EXPORT_AUTO_SAVE_ENABLED_DEFAULT,
    EXPORT_AUTO_SAVE_ENABLED_KEY,
    EXPORT_CSV_FILENAME_TMPL_DEFAULT,
    EXPORT_CSV_FILENAME_TMPL_KEY,
    EXPORT_DATE_FORMAT_DEFAULT,
    EXPORT_DATE_FORMAT_KEY,
    EXPORT_OUTPUT_DIR_DEFAULT,
    EXPORT_OUTPUT_DIR_KEY,
    get_setting,
    set_setting,
)

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


# ─── Export Format (M7 slice 3, issue #30) ────────────────────────────────────
# The settings the new ExportFormat page owns — `export_date_format` and
# `export_csv_filename_tmpl` — plus the two the Load Profile page's own
# auto-save controls write through the same PUT (D-16): `export_auto_save_enabled`
# and `export_output_dir`. One PUT, one full replace of all four (D-17) —
# splitting it in two would let the two pages disagree about which write won.


class ExportFormatSettingsOut(BaseModel):
    """What ``GET``/``PUT /api/settings/export-format`` return.

    Attributes:
        export_date_format: The Excel-style token string
            :func:`arichds.export.format._translate_date_format` reads
            (F3) — free text, validated at save time only for
            non-emptiness (an empty format would silently blank the
            Date/Time column of every future export).
        export_csv_filename_tmpl: The ``[meter]``/``[serial]``/``[date]``
            filename template (F4).
        export_auto_save_enabled: The scheduler job's own switch (D-11) —
            "Save CSV now" ignores it.
        export_output_dir: ``""`` means "not configured" — same convention
            as ``capture_dir``.
    """

    export_date_format: str
    export_csv_filename_tmpl: str
    export_auto_save_enabled: bool
    export_output_dir: str


class ExportFormatSettingsIn(BaseModel):
    """The body ``PUT /api/settings/export-format`` takes — a full replace
    of all four values."""

    export_date_format: str
    export_csv_filename_tmpl: str
    export_auto_save_enabled: bool
    export_output_dir: str


#: D-13 — a filename, not a path: reject empty/whitespace, a path separator
#: and a NUL byte, with the offending character named in the 422.
_FILENAME_UNSAFE_RE = re.compile(r"[/\\\x00]")


def _validate_filename_template(template: str) -> str:
    """Reject an ``export_csv_filename_tmpl`` that could escape
    ``export_output_dir`` once rendered (D-13).

    Raises:
        ValueError: On any rejection, with an operator-actionable sentence
            naming the offending character.
    """
    if not template or not template.strip():
        raise ValueError("export_csv_filename_tmpl must not be empty")
    if ".." in template:
        raise ValueError("export_csv_filename_tmpl must not contain '..'")
    match = _FILENAME_UNSAFE_RE.search(template)
    if match:
        raise ValueError(f"export_csv_filename_tmpl must not contain {match.group()!r}")
    return template


def _validate_date_format(token_format: str) -> str:
    """Reject an empty ``export_date_format`` (nit 3, code review) — an
    empty token string translates to an empty ``strftime`` pattern, which
    would silently blank the Date/Time column of every row exported from
    then on. No other shape is rejected: the token translator
    (:func:`arichds.export.format._translate_date_format`) passes any
    character it does not recognise straight through, so there is nothing
    else here that can be wrong in a way worth a 422 for.

    Raises:
        ValueError: When *token_format* is empty or whitespace-only.
    """
    if not token_format or not token_format.strip():
        raise ValueError("export_date_format must not be empty")
    return token_format


def _current_export_format_settings(session: Session) -> ExportFormatSettingsOut:
    """Read all four Export Format keys, defaulted for a fresh database."""
    return ExportFormatSettingsOut(
        export_date_format=get_setting(session, EXPORT_DATE_FORMAT_KEY, EXPORT_DATE_FORMAT_DEFAULT),
        export_csv_filename_tmpl=get_setting(session, EXPORT_CSV_FILENAME_TMPL_KEY, EXPORT_CSV_FILENAME_TMPL_DEFAULT),
        export_auto_save_enabled=get_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, EXPORT_AUTO_SAVE_ENABLED_DEFAULT)
        == "true",
        export_output_dir=get_setting(session, EXPORT_OUTPUT_DIR_KEY, EXPORT_OUTPUT_DIR_DEFAULT),
    )


@router.get("/export-format", dependencies=[Depends(require_feature("load_profile"))])
def get_export_format_settings(session: SessionDep) -> ApiResponse[ExportFormatSettingsOut]:
    """Return the current Export Format settings — any authenticated caller
    (D-17), gated behind ``load_profile`` (D-14): the CSV is Load Profile
    data, the same gate ``GET /api/load-profile`` already carries.
    """
    return ApiResponse.ok(_current_export_format_settings(session))


@router.put("/export-format", dependencies=[Depends(require_feature("load_profile"))])
def put_export_format_settings(
    body: ExportFormatSettingsIn, session: SessionDep, _admin: AdminDep
) -> ApiResponse[ExportFormatSettingsOut]:
    """Save all four Export Format settings — admin-only, a full replace.

    ``export_csv_filename_tmpl`` is validated at save time (D-13) — a
    rejection is a 422 and never reaches disk. ``export_date_format`` is
    rejected only when empty (nit 3, code review) — an empty format would
    silently blank the Date/Time column of every future export.
    ``export_output_dir`` is validated the same way ``capture_dir`` is
    (D-13, F7), against ``Settings.capture_allowlist_roots()`` — the same
    allowlist v1 shared between the two. Enabling ``export_auto_save_enabled``
    with an empty ``export_output_dir`` is a 422 (D-7): a switch nothing can
    act on is a trap, not a stored preference.
    """
    try:
        date_format = _validate_date_format(body.export_date_format)
        filename_tmpl = _validate_filename_template(body.export_csv_filename_tmpl)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    output_dir_value = ""
    if body.export_output_dir.strip():
        try:
            resolved = validate_directory_setting(
                body.export_output_dir, get_settings().capture_allowlist_roots(), setting_name="export_output_dir"
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
        output_dir_value = str(resolved)

    if body.export_auto_save_enabled and not output_dir_value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="export_auto_save_enabled requires export_output_dir to be set first.",
        )

    set_setting(session, EXPORT_DATE_FORMAT_KEY, date_format)
    set_setting(session, EXPORT_CSV_FILENAME_TMPL_KEY, filename_tmpl)
    set_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, "true" if body.export_auto_save_enabled else "false")
    set_setting(session, EXPORT_OUTPUT_DIR_KEY, output_dir_value)
    session.commit()

    return ApiResponse.ok(_current_export_format_settings(session))
