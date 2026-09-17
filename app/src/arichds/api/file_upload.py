"""``/api/settings/file-upload`` — the File Upload Destination configuration,
the last cycle's status, and the manual ``Upload now`` trigger (SPEC §3.8,
ADR 0025, tickets 01-04).

**Admin only, for every route including ``GET``** — the same choice
``arichds.api.central_push`` makes and for the same reason: three sets of
credentials (a password or a key file, a certificate's trust, a Bearer
token) are machine-internal configuration, not meter data. Unlike Central
Push, this module **is** gated by a licence feature key
(``file_upload_destination``, ADR 0025) — the same shape
``database_destination`` uses in ``arichds.api.settings``.

Ticket 02 lands :mod:`arichds.fileupload.cycle` and the ``POST
.../upload-now`` endpoint below. HTTPS (ticket 03), SFTP (ticket 04) and
FTPS (ticket 05) all move real bytes today —
:func:`~arichds.fileupload.cycle._build_transport` builds a real transport
for every protocol the page offers.
"""

from __future__ import annotations

import threading
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from arichds.api.deps import AdminDep, SchedulerDep, SessionDep, get_current_user, require_feature
from arichds.api.envelope import ApiResponse
from arichds.constants import (
    FILEUPLOAD_BUDGET_SEC,
    FILEUPLOAD_FTPS_TEST_CONNECT_TIMEOUT_SEC,
    FILEUPLOAD_HTTPS_TEST_CONNECT_TIMEOUT_SEC,
    FILEUPLOAD_SFTP_TEST_CONNECT_TIMEOUT_SEC,
)
from arichds.db.app_settings import (
    FILEUPLOAD_ACTIVE_PROTOCOL_KEY,
    FILEUPLOAD_FTPS_HOST_KEY,
    FILEUPLOAD_FTPS_PASSWORD_KEY,
    FILEUPLOAD_FTPS_PORT_KEY,
    FILEUPLOAD_FTPS_REMOTE_ROOT_KEY,
    FILEUPLOAD_FTPS_USERNAME_KEY,
    FILEUPLOAD_HTTPS_REMOTE_ROOT_KEY,
    FILEUPLOAD_HTTPS_TOKEN_KEY,
    FILEUPLOAD_HTTPS_URL_KEY,
    FILEUPLOAD_SFTP_HOST_KEY,
    FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_KEY,
    FILEUPLOAD_SFTP_KEY_PASSPHRASE_KEY,
    FILEUPLOAD_SFTP_KEY_PATH_KEY,
    FILEUPLOAD_SFTP_PASSWORD_KEY,
    FILEUPLOAD_SFTP_PORT_KEY,
    FILEUPLOAD_SFTP_REMOTE_ROOT_KEY,
    FILEUPLOAD_SFTP_USERNAME_KEY,
    set_setting,
)
from arichds.fileupload.config import load_config
from arichds.fileupload.cycle import file_upload_cycle
from arichds.fileupload.ftps_transport import FtpsTestResult, check_ftps_connection
from arichds.fileupload.https_transport import FilesTestResult, check_https_connection
from arichds.fileupload.sftp_transport import SftpTestResult, check_sftp_connection
from arichds.fileupload.status import CycleStatus, last_cycle

router = APIRouter(
    prefix="/api/settings/file-upload",
    tags=["file-upload"],
    dependencies=[Depends(get_current_user), Depends(require_feature("file_upload_destination"))],
)


class FileUploadSftpOut(BaseModel):
    """The SFTP tab as the API reports it. **No ``password`` or
    ``key_passphrase`` field, and neither must ever be added** — both are
    write-only, the ``db_dest_password`` precedent."""

    host: str
    port: int
    username: str
    password_set: bool
    key_path: str
    key_passphrase_set: bool
    remote_root: str
    host_key_fingerprint: str


class FileUploadFtpsOut(BaseModel):
    """The FTPS tab as the API reports it. No ``password`` field, same rule."""

    host: str
    port: int
    username: str
    password_set: bool
    remote_root: str


class FileUploadHttpsOut(BaseModel):
    """The HTTPS tab as the API reports it. No ``token`` field, same rule."""

    url: str
    token_set: bool
    remote_root: str


class FileUploadStatusOut(BaseModel):
    """One completed cycle — see :class:`arichds.fileupload.status.CycleStatus`."""

    ran_at: datetime
    protocol: str
    outcome: str
    files_sent: int
    bytes_sent: int
    files_skipped_unchanged: int
    files_skipped_budget: int
    files_skipped_no_serial: int
    duration_sec: float
    error: str | None


class FileUploadOut(BaseModel):
    """What ``GET /api/settings/file-upload`` returns — every tab's settings
    (credentials as ``…_set`` booleans only) plus the last cycle's status.

    Attributes:
        active_protocol: ``""`` (nothing saved yet), ``"sftp"``, ``"ftps"``
            or ``"https"`` — the tab saved last. The other two tabs' settings
            are still returned, unchanged, so a form can be pre-filled even
            while inactive (ADR 0025 decision 1).
        status: ``None`` until a cycle has run — ticket 02's scheduler job
            (or ``POST .../upload-now``) is what runs the first one.
    """

    active_protocol: str
    sftp: FileUploadSftpOut
    ftps: FileUploadFtpsOut
    https: FileUploadHttpsOut
    status: FileUploadStatusOut | None


class FileUploadSftpIn(BaseModel):
    """The body ``PUT …/sftp`` takes.

    Attributes:
        password: **Omitted or ``null`` keeps the stored one; an explicit
            empty string clears it** — the ``db_dest_password`` convention.
        key_path: Not write-only — a file path is not a secret. Always
            replaced in full, like *host*.
        key_passphrase: Omit/null-keeps, empty-clears, the same as
            *password*.
    """

    host: str
    port: int
    username: str
    password: str | None = None
    key_path: str
    key_passphrase: str | None = None
    remote_root: str


class FileUploadFtpsIn(BaseModel):
    """The body ``PUT …/ftps`` takes. *password* follows the same
    omit-keeps/empty-clears rule as :class:`FileUploadSftpIn`."""

    host: str
    port: int
    username: str
    password: str | None = None
    remote_root: str


class FileUploadHttpsIn(BaseModel):
    """The body ``PUT …/https`` takes. *token* follows the same
    omit-keeps/empty-clears rule as :class:`FileUploadSftpIn.password`."""

    url: str
    token: str | None = None
    remote_root: str


def _validate_port(port: int) -> int:
    """Reject a port outside ``1..65535``, naming the offending value —
    ``arichds.api.settings._validate_port``'s own shape, kept local rather
    than imported: each settings sub-module owns its own validators, the
    convention ``arichds.dataout.destination`` and ``arichds.api.settings``
    already set independently of each other.

    Raises:
        ValueError: When *port* is outside the range.
    """
    if not 1 <= port <= 65535:
        raise ValueError(f"port must be between 1 and 65535 - got {port}")
    return port


def _status_out(cycle_status: CycleStatus | None) -> FileUploadStatusOut | None:
    """Project an in-memory :class:`CycleStatus` onto the API shape."""
    if cycle_status is None:
        return None
    return FileUploadStatusOut(
        ran_at=cycle_status.ran_at,
        protocol=cycle_status.protocol,
        outcome=cycle_status.outcome,
        files_sent=cycle_status.files_sent,
        bytes_sent=cycle_status.bytes_sent,
        files_skipped_unchanged=cycle_status.files_skipped_unchanged,
        files_skipped_budget=cycle_status.files_skipped_budget,
        files_skipped_no_serial=cycle_status.files_skipped_no_serial,
        duration_sec=cycle_status.duration_sec,
        error=cycle_status.error,
    )


def _current_settings(session: Session) -> FileUploadOut:
    """Read every File Upload Destination row plus the in-memory status."""
    config = load_config(session)
    return FileUploadOut(
        active_protocol=config.active_protocol,
        sftp=FileUploadSftpOut(
            host=config.sftp.host,
            port=config.sftp.port,
            username=config.sftp.username,
            password_set=bool(config.sftp.password),
            key_path=config.sftp.key_path,
            key_passphrase_set=bool(config.sftp.key_passphrase),
            remote_root=config.sftp.remote_root,
            host_key_fingerprint=config.sftp.host_key_fingerprint,
        ),
        ftps=FileUploadFtpsOut(
            host=config.ftps.host,
            port=config.ftps.port,
            username=config.ftps.username,
            password_set=bool(config.ftps.password),
            remote_root=config.ftps.remote_root,
        ),
        https=FileUploadHttpsOut(
            url=config.https.url,
            token_set=bool(config.https.token),
            remote_root=config.https.remote_root,
        ),
        status=_status_out(last_cycle()),
    )


@router.get("")
def get_file_upload_settings(session: SessionDep, _admin: AdminDep) -> ApiResponse[FileUploadOut]:
    """Return every tab's settings and the last cycle's status. Admin only."""
    return ApiResponse.ok(_current_settings(session))


@router.put("/sftp")
def put_file_upload_sftp(body: FileUploadSftpIn, session: SessionDep, _admin: AdminDep) -> ApiResponse[FileUploadOut]:
    """Save the SFTP tab and make it the active protocol. Admin only.

    **Refused when neither a password nor a key-file path would be
    configured after this save** — the *effective* value, not just what this
    request sent: an omitted *password* keeps whatever is already stored, so
    a save that only edits *host* must not be judged against an empty body
    field. A plain FTP or implicit-FTPS value cannot reach this endpoint at
    all — there is no such field on this tab.
    """
    try:
        port = _validate_port(body.port)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    key_path = body.key_path.strip()
    stored_password = load_config(session).sftp.password
    effective_password = body.password if body.password is not None else stored_password
    if not effective_password and not key_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide either a password or a key file path.",
        )

    set_setting(session, FILEUPLOAD_SFTP_HOST_KEY, body.host)
    set_setting(session, FILEUPLOAD_SFTP_PORT_KEY, str(port))
    set_setting(session, FILEUPLOAD_SFTP_USERNAME_KEY, body.username)
    if body.password is not None:
        set_setting(session, FILEUPLOAD_SFTP_PASSWORD_KEY, body.password)
    set_setting(session, FILEUPLOAD_SFTP_KEY_PATH_KEY, key_path)
    if body.key_passphrase is not None:
        set_setting(session, FILEUPLOAD_SFTP_KEY_PASSPHRASE_KEY, body.key_passphrase)
    set_setting(session, FILEUPLOAD_SFTP_REMOTE_ROOT_KEY, body.remote_root)
    set_setting(session, FILEUPLOAD_ACTIVE_PROTOCOL_KEY, "sftp")
    session.commit()

    return ApiResponse.ok(_current_settings(session))


class FileUploadSftpTestOut(BaseModel):
    """What ``POST /api/settings/file-upload/sftp/test`` returns — see
    :class:`arichds.fileupload.sftp_transport.SftpConnectionCheck`.

    Attributes:
        result: Which of :data:`~arichds.fileupload.sftp_transport.SftpTestResult`
            this is — naming the failure (host-key mismatch, bad
            credentials, a missing key file, ...) rather than a bare
            "Connection failed" (ticket 04's own acceptance criterion, the
            same one ticket 03 set for HTTPS).
        fingerprint: The server's host-key fingerprint as observed on this
            attempt, or ``None`` when the handshake itself never completed.
        manifest_exists: Whether the server already holds a manifest.
        message: One operator-actionable English sentence.
    """

    result: SftpTestResult
    fingerprint: str | None
    manifest_exists: bool
    message: str


@router.post("/sftp/test")
def test_file_upload_sftp(session: SessionDep, _admin: AdminDep) -> ApiResponse[FileUploadSftpTestOut]:
    """Connect with the **stored** SFTP settings and report which outcome it
    is. Admin only; gated by the router's own ``file_upload_destination``
    feature dependency.

    Never writes the pinned fingerprint row itself — a mismatched or
    first-contact fingerprint is only ever *reported* here (`ADR 0025`/
    ticket 04: "a cycle never pins on its own", and this endpoint is no
    exception); ``POST .../sftp/host-key`` below is the one place that
    writes it, and only when the operator supplies the fingerprint they saw.

    Uses the **short** connect timeout
    (:data:`~arichds.constants.FILEUPLOAD_SFTP_TEST_CONNECT_TIMEOUT_SEC`),
    passed explicitly — `test_file_upload_https`'s own reviewer-pinned
    shape (ticket 03 round 1): a Test button that used the cycle's own
    longer timeout could hold this request for much longer against an
    unreachable server.
    """
    config = load_config(session).sftp
    check = check_sftp_connection(
        host=config.host,
        port=config.port,
        username=config.username,
        password=config.password,
        key_path=config.key_path,
        key_passphrase=config.key_passphrase,
        remote_root=config.remote_root,
        pinned_fingerprint=config.host_key_fingerprint,
        connect_timeout=FILEUPLOAD_SFTP_TEST_CONNECT_TIMEOUT_SEC,
    )
    return ApiResponse.ok(
        FileUploadSftpTestOut(
            result=check.result,
            fingerprint=check.fingerprint,
            manifest_exists=check.manifest_exists,
            message=check.message,
        )
    )


class FileUploadSftpHostKeyIn(BaseModel):
    """The body ``POST .../sftp/host-key`` takes — the fingerprint the
    operator saw on the page (from ``POST .../sftp/test``), never derived by
    this endpoint itself. This is the **only** write path for the pinned
    fingerprint row — nothing in :mod:`arichds.fileupload.sftp_transport` or
    :mod:`arichds.fileupload.cycle` ever writes it (ADR 0025/ticket 04: "a
    cycle never pins on its own")."""

    fingerprint: str


@router.post("/sftp/host-key")
def pin_file_upload_sftp_host_key(
    body: FileUploadSftpHostKeyIn, session: SessionDep, _admin: AdminDep
) -> ApiResponse[FileUploadOut]:
    """Pin (or replace) the SFTP tab's trusted host-key fingerprint. Admin
    only. Refused when *fingerprint* is blank — there is nothing to pin."""
    fingerprint = body.fingerprint.strip()
    if not fingerprint:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="fingerprint is required.")

    set_setting(session, FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_KEY, fingerprint)
    session.commit()

    return ApiResponse.ok(_current_settings(session))


@router.put("/ftps")
def put_file_upload_ftps(body: FileUploadFtpsIn, session: SessionDep, _admin: AdminDep) -> ApiResponse[FileUploadOut]:
    """Save the FTPS tab and make it the active protocol. Admin only.

    Only *port* is validated at save time (``1..65535``) — an unreachable
    host or a self-signed certificate is what ticket 05's Test connection
    reports, not a 422, the same split ``database-destination`` makes.
    """
    try:
        port = _validate_port(body.port)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    set_setting(session, FILEUPLOAD_FTPS_HOST_KEY, body.host)
    set_setting(session, FILEUPLOAD_FTPS_PORT_KEY, str(port))
    set_setting(session, FILEUPLOAD_FTPS_USERNAME_KEY, body.username)
    if body.password is not None:
        set_setting(session, FILEUPLOAD_FTPS_PASSWORD_KEY, body.password)
    set_setting(session, FILEUPLOAD_FTPS_REMOTE_ROOT_KEY, body.remote_root)
    set_setting(session, FILEUPLOAD_ACTIVE_PROTOCOL_KEY, "ftps")
    session.commit()

    return ApiResponse.ok(_current_settings(session))


class FileUploadFtpsTestOut(BaseModel):
    """What ``POST /api/settings/file-upload/ftps/test`` returns — see
    :class:`arichds.fileupload.ftps_transport.FtpsConnectionCheck`.

    Attributes:
        result: Which of :data:`~arichds.fileupload.ftps_transport.FtpsTestResult`
            this is — naming the failure (an untrusted certificate, bad
            credentials, ...) rather than a bare "Connection failed", the
            same criterion tickets 03/04 already set for their own tabs.
        subject: The server's certificate subject as observed on this
            attempt, or ``None`` when the TLS handshake itself never
            completed.
        manifest_exists: Whether the server already holds a manifest.
        message: One operator-actionable English sentence.
    """

    result: FtpsTestResult
    subject: str | None
    manifest_exists: bool
    message: str


@router.post("/ftps/test")
def test_file_upload_ftps(session: SessionDep, _admin: AdminDep) -> ApiResponse[FileUploadFtpsTestOut]:
    """Connect with the **stored** FTPS settings and report which outcome it
    is. Admin only; gated by the router's own ``file_upload_destination``
    feature dependency.

    Uses the **short** connect timeout
    (:data:`~arichds.constants.FILEUPLOAD_FTPS_TEST_CONNECT_TIMEOUT_SEC`),
    passed explicitly — the same shape `test_file_upload_sftp`/
    `test_file_upload_https` already use, so a Test button never holds this
    request for the cycle's own longer timeout against an unreachable
    server. Never passes an ``ssl_context`` — production behaviour, exactly
    what a real cycle would do: a self-signed certificate is refused here
    too.
    """
    config = load_config(session).ftps
    check = check_ftps_connection(
        host=config.host,
        port=config.port,
        username=config.username,
        password=config.password,
        remote_root=config.remote_root,
        connect_timeout=FILEUPLOAD_FTPS_TEST_CONNECT_TIMEOUT_SEC,
    )
    return ApiResponse.ok(
        FileUploadFtpsTestOut(
            result=check.result, subject=check.subject, manifest_exists=check.manifest_exists, message=check.message
        )
    )


@router.put("/https")
def put_file_upload_https(body: FileUploadHttpsIn, session: SessionDep, _admin: AdminDep) -> ApiResponse[FileUploadOut]:
    """Save the HTTPS tab and make it the active protocol. Admin only.

    **Refused when the URL is blank** — unlike the other two tabs, HTTPS has
    no second way to name a server, so an empty URL is unambiguously
    nothing to save.
    """
    if not body.url.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="url is required.")

    set_setting(session, FILEUPLOAD_HTTPS_URL_KEY, body.url)
    if body.token is not None:
        set_setting(session, FILEUPLOAD_HTTPS_TOKEN_KEY, body.token)
    set_setting(session, FILEUPLOAD_HTTPS_REMOTE_ROOT_KEY, body.remote_root)
    set_setting(session, FILEUPLOAD_ACTIVE_PROTOCOL_KEY, "https")
    session.commit()

    return ApiResponse.ok(_current_settings(session))


@router.get("/status")
def get_file_upload_status(_admin: AdminDep) -> ApiResponse[FileUploadStatusOut | None]:
    """Return the last cycle's status."""
    return ApiResponse.ok(_status_out(last_cycle()))


class FileUploadHttpsTestOut(BaseModel):
    """What ``POST /api/settings/file-upload/https/test`` returns — see
    :class:`arichds.fileupload.https_transport.FilesConnectionCheck`.

    Attributes:
        result: ``"ok"`` / ``"unreachable"`` / ``"timed_out"`` /
            ``"unauthorized"`` / ``"other"`` — which check failed, naming it
            rather than a bare "Connection failed" (ticket 03's own
            acceptance criterion).
        http_status: The HTTP status the server answered with, ``None``
            when there was no response at all.
        manifest_exists: Whether the server already holds a manifest.
        message: One operator-actionable English sentence.
    """

    result: FilesTestResult
    http_status: int | None
    manifest_exists: bool
    message: str


@router.post("/https/test")
def test_file_upload_https(session: SessionDep, _admin: AdminDep) -> ApiResponse[FileUploadHttpsTestOut]:
    """Connect with the **stored** HTTPS settings and report which outcome it
    is. Admin only; gated by the router's own ``file_upload_destination``
    feature dependency.

    Per-protocol, mirroring ``POST /api/settings/database-destination/test``
    — the SFTP/FTPS tabs get their own ``.../sftp/test`` /
    ``.../ftps/test`` in tickets 04-05 alongside this one, rather than one
    endpoint branching on a body field, so each protocol's router entry
    stays self-contained the way the three ``PUT`` endpoints above already
    are.

    Uses the **short** connect timeout
    (:data:`~arichds.constants.FILEUPLOAD_HTTPS_TEST_CONNECT_TIMEOUT_SEC`,
    the ``database-destination`` test's own shape) — a Test button that used
    the cycle's own long timeout could hold this request for a minute
    against an unreachable server. It takes no body, for the same reason
    ``test_database_destination`` does not: a Test button that tested
    something other than what is saved would prove nothing about what the
    next cycle will do.

    **HTTP 200 for every outcome, including the four failures** — the
    ``database-destination`` test's own convention: a 4xx/5xx would be
    swallowed by the page's generic error surface, leaving only a bare
    "Connection failed" where the reason lives in ``result`` instead.
    """
    config = load_config(session).https
    check = check_https_connection(config.url, config.token, connect_timeout=FILEUPLOAD_HTTPS_TEST_CONNECT_TIMEOUT_SEC)
    return ApiResponse.ok(
        FileUploadHttpsTestOut(
            result=check.result,
            http_status=check.http_status,
            manifest_exists=check.manifest_exists,
            message=check.message,
        )
    )


class FileUploadUploadNowOut(BaseModel):
    """What ``POST .../upload-now`` returns.

    Attributes:
        finished: Whether the triggered cycle actually completed before
            this request's bounded wait ran out. When ``False``, *status*
            is whatever was already published before this request — it may
            be ``None``, or an unrelated earlier cycle's — and must not be
            read as "this cycle's result" (reviewer finding, ticket 02
            round 1, problem 2: the one-shot lane runs behind every
            registered job on the scheduler's single thread, and a
            load-profile pass alone can exceed this endpoint's own wait —
            ADR 0018 records a 95.5 s association on a Premier 550 — so a
            press during a normal pass must not be told "finished" while
            nothing has actually run yet).
        status: The last published cycle status, whether or not it belongs
            to the cycle this request triggered.
    """

    finished: bool
    status: FileUploadStatusOut | None


#: How much longer than the cycle's own budget this endpoint waits, to give
#: the one-shot a moment to be picked up after `run_soon` wakes the
#: scheduler thread. A named module constant (not an inline literal)
#: specifically so a test can shrink the whole wait to milliseconds without
#: monkeypatching `threading.Event` itself, which would affect every other
#: `Event` in the process (reviewer finding, ticket 02 round 1, problem 2 —
#: an earlier draft of this test file's own probe did exactly that and broke
#: unrelated `Thread` startup machinery).
_UPLOAD_NOW_WAIT_MARGIN_SEC = 10.0


@router.post("/upload-now")
def upload_file_upload_now(scheduler: SchedulerDep, _admin: AdminDep) -> ApiResponse[FileUploadUploadNowOut]:
    """Run one File Upload Destination cycle immediately and report whether
    it actually finished. Admin only.

    Runs on the Scheduler's one-shot lane
    (:meth:`~arichds.jobs.scheduler.Scheduler.run_soon`) — never inline in
    the request, since a cycle can read megabytes off disk and talk to a
    server — the same lane ``POST /devices`` queues a device's first
    load-profile read on. Unlike that fire-and-forget use, this request
    **waits** for the cycle to finish (bounded by
    :data:`~arichds.constants.FILEUPLOAD_BUDGET_SEC` plus a margin for the
    one-shot to be picked up): the entire point of an "Upload now" button is
    to show what happened, not merely that a request landed. **The wait can
    still time out** — the one-shot lane runs behind every job already due
    on the scheduler's one thread, so a slow meter read ahead of it can
    outlast this endpoint's own budget — and when it does, ``finished`` is
    ``False`` rather than silently reporting a stale or absent status as
    if it were this cycle's own (reviewer finding, ticket 02 round 1,
    problem 2).
    """
    done = threading.Event()

    def _run() -> None:
        try:
            file_upload_cycle()
        finally:
            done.set()

    scheduler.run_soon("file_upload_manual", _run)
    finished = done.wait(timeout=FILEUPLOAD_BUDGET_SEC + _UPLOAD_NOW_WAIT_MARGIN_SEC)
    return ApiResponse.ok(FileUploadUploadNowOut(finished=finished, status=_status_out(last_cycle())))
