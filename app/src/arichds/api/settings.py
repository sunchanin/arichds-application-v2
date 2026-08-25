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
from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from arichds.api.deps import AdminDep, SessionDep, get_current_user, require_feature
from arichds.api.envelope import ApiResponse
from arichds.capture._render_shared import DisplayUnitScale
from arichds.capture.paths import validate_directory_setting
from arichds.config import get_settings
from arichds.dataout.destination import ConnectionResult, check_destination_connection, load_config
from arichds.dataout.status import last_sync
from arichds.db.app_settings import (
    DB_DEST_DATABASE_DEFAULT,
    DB_DEST_DATABASE_KEY,
    DB_DEST_HOST_DEFAULT,
    DB_DEST_HOST_KEY,
    DB_DEST_PASSWORD_DEFAULT,
    DB_DEST_PASSWORD_KEY,
    DB_DEST_PORT_DEFAULT,
    DB_DEST_PORT_KEY,
    DB_DEST_USER_DEFAULT,
    DB_DEST_USER_KEY,
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


# ─── Database Destination (SPEC §3.10, ADR 0016/0020/0021, issue #46) ─────────
# The connection to the customer's own MariaDB/MySQL — a Data-out Destination
# (CONTEXT.md), never our store. One typed pair plus a test action, all three
# behind `require_feature("database_destination")` at the route level, the same
# shape `/export-format` uses for `load_profile`.


class DatabaseDestinationSyncStatus(BaseModel):
    """What the last sync cycle did — **in memory only** (ADR 0008).

    ``None`` on the enclosing model means no cycle has run since the service
    started. That is not an error state and the page must not render it as one.

    Attributes:
        ran_at: When the cycle finished, UTC. Our store's convention — ADR
            0021's local-time boundary is the destination's rows, not this.
        load_profile_rows: Interval Readings sent. A re-sent row inside the
            watermark rewind is counted here even though it changes nothing at
            the destination, so this is "sent", never "gained".
        billing_rows: Billing Readings written by the whole-table replace.
        purged_rows: Rows removed from the destination past the Mirror Window.
        skipped_rows: Rows with no Meter Serial to attribute them to.
        duration_sec: Wall clock for the cycle.
        error: The failure that ended the cycle, or ``None``.
        budget_exhausted: The cycle stopped on its wall-clock budget and will
            resume next tick. **Not** an error — the watermark lives in the
            destination, so a partial cycle is not a lost cycle.
    """

    ran_at: datetime
    load_profile_rows: int
    billing_rows: int
    purged_rows: int
    skipped_rows: int
    duration_sec: float
    error: str | None
    budget_exhausted: bool


class DatabaseDestinationOut(BaseModel):
    """What ``GET``/``PUT /api/settings/database-destination`` return.

    **There is no ``password`` field, and one must never be added.** SPEC
    §3.10 makes the password write-only: it is stored in the clear following
    the ``block_cipher_key`` precedent (``db/models.py:129-131``), and the two
    things protecting it are that this model cannot serialise it and that
    :class:`~arichds.logging_config.CredentialRedactionFilter` redacts the
    setting key. ``password_set`` exists so the form can show "unchanged"
    rather than an empty box that reads as a cleared value.

    Attributes:
        host: Empty means "not configured" — the sync then returns immediately
            with one DEBUG line and no error.
        port: MySQL/MariaDB port, 3306 unless changed.
        database: The database the customer created for us. Empty means "not
            configured", same as *host*.
        user: The account we connect as.
        password_set: Whether a non-empty password is stored. Deliberately not
            a length, a hash or a mask — none of those are needed and each
            leaks something.
        last_sync: The last cycle, or ``None`` if none has run.
    """

    host: str
    port: int
    database: str
    user: str
    password_set: bool
    last_sync: DatabaseDestinationSyncStatus | None


class DatabaseDestinationIn(BaseModel):
    """The body ``PUT /api/settings/database-destination`` takes.

    Attributes:
        host: Not validated at save time. An unreachable host is what the Test
            connection button is for, not a 422 — a customer may legitimately
            save settings before their DBA opens the firewall.
        port: The one validated field, ``1..65535``.
        database: Not validated at save time, same reasoning as *host*.
        user: Not validated at save time.
        password: **Omitted or ``null`` keeps the stored password; an explicit
            empty string stores an empty one.** See the endpoint docstring —
            this is a deliberate decision, not the obvious reading.
    """

    host: str
    port: int
    database: str
    user: str
    password: str | None = None


def _validate_port(port: int) -> int:
    """Reject a port outside ``1..65535``, naming the offending value.

    The style :func:`_validate_filename_template` set: the 422 says what was
    wrong with what the operator typed, not merely that something was.

    Raises:
        ValueError: When *port* is outside the range.
    """
    if not 1 <= port <= 65535:
        raise ValueError(f"port must be between 1 and 65535 - got {port}")
    return port


def _current_database_destination_settings(session: Session) -> DatabaseDestinationOut:
    """Read all five keys plus the in-memory last-cycle status.

    ``port`` is stored as a string like every other value in the ``settings``
    table. A row holding something unparseable — only reachable by editing the
    database by hand, since the PUT validates — falls back to the default
    rather than 500-ing the page that would let an operator fix it.
    """
    try:
        port = int(get_setting(session, DB_DEST_PORT_KEY, DB_DEST_PORT_DEFAULT))
    except ValueError:
        port = int(DB_DEST_PORT_DEFAULT)

    status_now = last_sync()
    return DatabaseDestinationOut(
        host=get_setting(session, DB_DEST_HOST_KEY, DB_DEST_HOST_DEFAULT),
        port=port,
        database=get_setting(session, DB_DEST_DATABASE_KEY, DB_DEST_DATABASE_DEFAULT),
        user=get_setting(session, DB_DEST_USER_KEY, DB_DEST_USER_DEFAULT),
        password_set=bool(get_setting(session, DB_DEST_PASSWORD_KEY, DB_DEST_PASSWORD_DEFAULT)),
        last_sync=None if status_now is None else DatabaseDestinationSyncStatus(**asdict(status_now)),
    )


@router.get("/database-destination", dependencies=[Depends(require_feature("database_destination"))])
def get_database_destination_settings(session: SessionDep) -> ApiResponse[DatabaseDestinationOut]:
    """Return the Database Destination settings and the last cycle's status.

    Any authenticated caller, the same as ``/display`` and ``/export-format`` —
    reading a setting is not admin-only anywhere in this module. **The password
    is not in the response**, by the shape of :class:`DatabaseDestinationOut`
    rather than by a filter here.
    """
    return ApiResponse.ok(_current_database_destination_settings(session))


@router.put("/database-destination", dependencies=[Depends(require_feature("database_destination"))])
def put_database_destination_settings(
    body: DatabaseDestinationIn, session: SessionDep, _admin: AdminDep
) -> ApiResponse[DatabaseDestinationOut]:
    """Save the Database Destination settings — admin-only.

    **An omitted or ``null`` password keeps the stored one; an explicit empty
    string stores an empty password.** That is decided deliberately and against
    the more obvious reading, which would treat both as "keep": XAMPP's
    ``root`` genuinely has an empty password by default, and XAMPP is the
    customer's reference configuration, so treating an empty string as "keep"
    would make the one setup this module was designed against impossible to
    enter through the form. The page sends ``password`` only when the field was
    actually edited, so an untouched form cannot clear a stored password.

    Only ``port`` is validated (``1..65535``, a 422 naming the value). A host
    that does not resolve or a database that does not exist are **not** 422s —
    that is what ``POST …/test`` reports, with a sentence saying which of them
    is wrong.
    """
    try:
        port = _validate_port(body.port)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    set_setting(session, DB_DEST_HOST_KEY, body.host)
    set_setting(session, DB_DEST_PORT_KEY, str(port))
    set_setting(session, DB_DEST_DATABASE_KEY, body.database)
    set_setting(session, DB_DEST_USER_KEY, body.user)
    if body.password is not None:
        set_setting(session, DB_DEST_PASSWORD_KEY, body.password)
    session.commit()

    return ApiResponse.ok(_current_database_destination_settings(session))


class DatabaseDestinationTestOut(BaseModel):
    """What ``POST /api/settings/database-destination/test`` returns.

    Attributes:
        result: Which of the six outcomes. Distinguishing them is the entire
            reason this endpoint exists — "Connection failed" alone tells the
            operator nothing about which field to fix.
        message: One operator-actionable English sentence.
        server_version: ``SELECT VERSION()`` on success, ``None`` otherwise.
    """

    result: ConnectionResult
    message: str
    server_version: str | None


@router.post("/database-destination/test", dependencies=[Depends(require_feature("database_destination"))])
def test_database_destination(session: SessionDep, _admin: AdminDep) -> ApiResponse[DatabaseDestinationTestOut]:
    """Connect with the **stored** settings and report which outcome it is.

    Admin-only. It takes no body on purpose: a Test button that tested
    something other than what is saved would prove nothing about what the sync
    job will do at the next tick.

    **HTTP 200 for every outcome, including the four failures.** A 4xx or 5xx
    would be swallowed by the page's generic error surface and the operator
    would be shown "Connection failed" — precisely the message this endpoint
    exists to replace. The failure lives in ``result``, not in the status code.

    Creates nothing permanent — two reads and a disposed engine.
    """
    config = load_config(session)
    check = check_destination_connection(config)
    return ApiResponse.ok(
        DatabaseDestinationTestOut(result=check.result, message=check.message, server_version=check.server_version)
    )
