"""The FTPS File Upload Destination transport (ADR 0025 decision 1; spec.md
"FTPS specifics"; ticket 05) — the third and last real transport behind the
seam :mod:`arichds.fileupload.transport`, driven over the standard library's
``ftplib.FTP_TLS`` alone (``docs/lib-notes/pyftpdlib-tls.md`` §5-§7): explicit
``AUTH TLS`` on the configured port, passive mode, ``PROT P``, and a default
SSL context — the system trust store, hostname verification on. Implicit
FTPS (port 990) is not offered; nothing here special-cases that port, because
``ftplib`` itself has nothing to call for it.

**No CA-file field** (ADR 0025 Out of Scope). :class:`FtpsTransport` and
:func:`check_ftps_connection` both take a keyword-only
``ssl_context: ssl.SSLContext | None = None`` that defaults to
``ssl.create_default_context()`` at call time — a **constructor seam for
tests only**, never a setting: the product (the cycle, the endpoint) never
passes one, so a self-signed certificate is always refused in production.
Tests pass a context with ``load_verify_locations(cafile=<the test's own
cert>)`` to trust the in-process ``pyftpdlib`` server without touching the
machine's real trust store.

**`AUTH TLS` before `login()`, not through it** — ``ftplib.FTP_TLS.login()``
issues ``AUTH TLS`` automatically when ``secure=True`` (its default) and the
socket is not already TLS-wrapped, but that leaves no chance to read the
server's certificate before credentials are sent. This module calls
``auth()`` explicitly first — the point at which a self-signed or untrusted
certificate raises ``ssl.SSLCertVerificationError``, measured against a real
``pyftpdlib`` ``TLS_FTPHandler`` (``docs/lib-notes/pyftpdlib-tls.md``, this
ticket's own measurement pass) — reads the certificate subject off the now
TLS-wrapped socket, then calls ``login(secure=True)``, which sees an already
TLS socket and does not re-``auth()``.

**Binary mode throughout.** ``ftplib``'s default transfer type is ASCII;
``SIZE`` (used to test whether the manifest exists) is refused in ASCII mode
on a real server (measured: ``550 SIZE not allowed in ASCII mode``) —
``TYPE I`` is set once, right after login, rather than relying on
``storbinary``/``retrbinary``'s own per-call switch.

**Reconnects per operation**, the same shape
:class:`~arichds.fileupload.https_transport.HttpsTransport`/
:class:`~arichds.fileupload.sftp_transport.SftpTransport` already have —
simpler and safer than holding one connection open across an unbounded
number of candidates for a whole cycle, at the cost of re-handshaking TLS per
file. Flagged as an assumption in the implementation report, the same one
ticket 04 flagged for SFTP: nothing in ADR 0025 or spec.md asks for
connection pooling, and ``FILEUPLOAD_BUDGET_SEC`` already bounds a cycle's
total wall time regardless.
"""

from __future__ import annotations

import contextlib
import ftplib
import io
import posixpath
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from arichds.constants import (
    FILEUPLOAD_FTPS_CONNECT_TIMEOUT_SEC,
    FILEUPLOAD_FTPS_READ_TIMEOUT_SEC,
    FILEUPLOAD_FTPS_TEST_CONNECT_TIMEOUT_SEC,
)
from arichds.fileupload.manifest import MANIFEST_FILENAME, Manifest, decode_manifest, encode_manifest
from arichds.fileupload.transport import TransportError

#: What :func:`check_ftps_connection` (and, through it, `describe()`) can
#: answer — mirrors :data:`~arichds.fileupload.sftp_transport.SftpTestResult`'s
#: "every outcome is data, not an exception" shape, narrowed to what
#: `ftplib`/`ssl` actually distinguish for FTPS (measured, not assumed —
#: `docs/lib-notes/pyftpdlib-tls.md` §6-7, this ticket's own re-measurement).
FtpsTestResult = Literal["ok", "unreachable", "timed_out", "bad_credentials", "untrusted_certificate", "other"]


@dataclass(frozen=True, slots=True)
class FtpsConnectionCheck:
    """One Test connection result.

    Attributes:
        result: Which of :data:`FtpsTestResult` this is.
        subject: The server's certificate subject as observed on *this*
            attempt (``CN=...`` — :func:`_render_subject`), present whenever
            the TLS handshake itself succeeded (``ok``, ``bad_credentials``
            — the certificate is trusted, only the password was wrong).
            ``None`` when the connection never got that far (unreachable,
            timed out, untrusted certificate, other).
        manifest_exists: Whether the server already holds a manifest.
        message: One operator-actionable English sentence.
    """

    result: FtpsTestResult
    subject: str | None
    manifest_exists: bool
    message: str


#: Short-name abbreviations for the common `getpeercert()["subject"]` RDN
#: attribute names — enough to render a readable `CN=..., O=...` string;
#: anything else falls back to its own attribute name unabbreviated.
_SUBJECT_ABBREVIATIONS = {
    "commonName": "CN",
    "organizationName": "O",
    "organizationalUnitName": "OU",
    "countryName": "C",
    "stateOrProvinceName": "ST",
    "localityName": "L",
}


def _render_subject(cert: dict | None) -> str:
    """Render `ssl.SSLSocket.getpeercert()`'s own subject shape (a tuple of
    RDN tuples of `(attribute, value)` pairs) as a readable `CN=...,O=...`
    string — never the raw tuple, which is not what an operator reads."""
    if not cert:
        return "(no subject)"
    parts = [f"{_SUBJECT_ABBREVIATIONS.get(key, key)}={value}" for rdn in cert.get("subject", ()) for key, value in rdn]
    return ",".join(parts) if parts else "(no subject)"


def _remote_path(remote_root: str, relative_path: str) -> str:
    """*relative_path* prefixed by *remote_root* — the same "preserve a
    leading ``/``" shape :func:`arichds.fileupload.sftp_transport._remote_path`
    uses (an absolute server-side path is the common case)."""
    root = remote_root.rstrip("/")
    return f"{root}/{relative_path}" if root else relative_path


def _mkdir_p(ftps: ftplib.FTP_TLS, remote_dir: str) -> None:
    """Create *remote_dir* and every missing parent, tolerating "already
    exists" — `mkd` is **not** idempotent (measured: a real server answers
    ``550 File exists.``, `ftplib`'s own `error_perm`, the same shape
    paramiko's SFTP `mkdir` has, `docs/lib-notes/pyftpdlib-tls.md` §6) — each
    segment is `mkd`-ed and any `error_perm` is swallowed rather than
    checked first, since `ftplib` has no cheap "does this directory exist"
    call the way SFTP's `stat` is."""
    if remote_dir in ("", "/", "."):
        return
    path = "/" if remote_dir.startswith("/") else ""
    for segment in filter(None, remote_dir.split("/")):
        path = posixpath.join(path, segment)
        with contextlib.suppress(ftplib.error_perm):
            ftps.mkd(path)


def _reply_code(exc: Exception) -> str | None:
    """The leading 3-digit FTP reply code from *exc*'s own message (e.g.
    ``"530"`` from ``ftplib.error_perm("530 Authentication failed.")``), or
    ``None`` when the message is not shaped like a real reply. **Never
    returns more than the code itself** — the rest of a reply can echo a
    command's own argument back (`USER`/`PASS`), and while
    `check_ftps_connection`'s message is shown to the operator rather than
    logged, there is still no reason to carry more than the one thing this
    ticket's own fix (reviewer finding, round 1, problem 4) asks for."""
    text = str(exc)
    code = text[:3]
    return code if code.isdigit() else None


def _classify_exception(exc: Exception) -> tuple[FtpsTestResult, TransportError]:
    """Map any exception this module can raise while connecting,
    authenticating or operating to both the Test-connection result literal
    and the `TransportError` a real transport method raises — the one
    classifier every call site shares (mirrors
    `sftp_transport.py`'s own single classifier between `describe()` and
    `check_sftp_connection()`). `str()` on the returned `TransportError` is
    always `type(exc).__name__` alone — never a host, a credential, or an
    `ftplib` message that might carry one.

    Ordering matters and is measured, not assumed
    (`docs/lib-notes/pyftpdlib-tls.md` §6-7, this ticket's own pass against a
    real `pyftpdlib` server): `ssl.SSLCertVerificationError` is a subclass of
    `OSError` (via `ssl.SSLError`), and `TimeoutError` is *also* a subclass
    of `OSError` on this Python — both are checked ahead of the general
    `OSError` branch, or a self-signed certificate or a stalled connection
    would misreport as `unreachable`.
    """
    if isinstance(exc, ssl.SSLCertVerificationError):
        return "untrusted_certificate", TransportError(type(exc).__name__)
    if isinstance(exc, TimeoutError):
        return "timed_out", TransportError(type(exc).__name__)
    if isinstance(exc, ftplib.error_perm):
        # Measured: wrong credentials answer `530 Authentication failed.` —
        # `ftplib.error_perm`, the same exception class a refused `PROT P`/
        # `PBSZ` (a server with data-channel protection disabled) or a
        # missing remote directory answers a 5xx with. Only `530`/`532`
        # ("not logged in" / "need account for storing files") are
        # classified `bad_credentials` — reviewer finding, round 1, problem
        # 4: collapsing every `error_perm` into `bad_credentials` told an
        # operator whose server refused `PROT P` to re-type a correct
        # password, on the exact page whose how-to exists so nobody calls
        # the vendor. Directory-existence checks are swallowed locally
        # before ever reaching this classifier (`check_ftps_connection`'s
        # own `nlst`/`_manifest_exists`, `_mkdir_p`) and never arrive here.
        if _reply_code(exc) in ("530", "532"):
            return "bad_credentials", TransportError(type(exc).__name__)
        return "other", TransportError(type(exc).__name__)
    if isinstance(exc, (OSError, ftplib.Error)):
        return "unreachable", TransportError(type(exc).__name__)
    return "other", TransportError(type(exc).__name__)


def _message_for(result: FtpsTestResult, subject: str | None, *, reply_code: str | None = None) -> str:
    if result == "unreachable":
        return "Could not reach the server."
    if result == "timed_out":
        return "The connection timed out."
    if result == "bad_credentials":
        return "The server refused the username or password."
    if result == "untrusted_certificate":
        return "The server presented a certificate this machine does not trust. Refused — use a certificate from a trusted authority."
    if reply_code:
        # `result == "other"` reached through an `error_perm` that was not
        # `530`/`532` — naming the 3-digit code only (`_reply_code`'s own
        # rule), so an operator whose server refuses `PROT P`/`PBSZ` gets a
        # real diagnostic instead of a generic "connection failed".
        return f"The connection failed (server replied {reply_code})."
    return f"The connection failed{f' ({subject})' if subject else ''}."


def _connect_and_authenticate(
    *, host: str, port: int, connect_timeout: float, read_timeout: float, ssl_context: ssl.SSLContext | None
) -> tuple[ftplib.FTP_TLS, str]:
    """Open the TCP connection, negotiate explicit ``AUTH TLS``, and return
    the still-unauthenticated (at the FTP-login level) ``FTP_TLS`` plus the
    server's certificate subject.

    *connect_timeout* bounds the TCP connect and the ``AUTH TLS`` handshake
    alone; the socket is then loosened to *read_timeout* for whatever login,
    listing and file transfer follows — the same split
    :func:`~arichds.fileupload.sftp_transport._handshake` documents for SSH2.
    **Both** `ftps.sock.settimeout(read_timeout)` (the *current* control
    socket) **and** `ftps.timeout = read_timeout` (the `FTP` instance's own
    attribute) are needed — `ftplib.FTP.ntransfercmd` opens every passive
    *data* connection with `socket.create_connection(…, self.timeout, …)`,
    reading `self.timeout` fresh each time, not the control socket's own
    timeout (reviewer finding, round 1, problem 2: without the second
    assignment, every `STOR`/`RETR`/`NLST` ran at *connect_timeout*, never
    *read_timeout*, silently — verified against the installed `ftplib`).
    Any exception here propagates unclassified — every caller wraps this in
    its own try/except and calls :func:`_classify_exception`.
    """
    context = ssl_context if ssl_context is not None else ssl.create_default_context()
    ftps = ftplib.FTP_TLS(context=context, timeout=connect_timeout)
    try:
        ftps.connect(host, port, timeout=connect_timeout)
        ftps.auth()  # explicit AUTH TLS — raises ssl.SSLCertVerificationError for an untrusted cert
        subject = _render_subject(ftps.sock.getpeercert())
        ftps.sock.settimeout(read_timeout)
        ftps.timeout = read_timeout
    except Exception:
        with contextlib.suppress(Exception):
            ftps.close()
        raise
    return ftps, subject


def _prepare_session(ftps: ftplib.FTP_TLS, *, username: str, password: str) -> None:
    """Log in (over the already-TLS-wrapped control channel — `login()`
    sees `self.sock` is already an `ssl.SSLSocket` and does not re-`auth()`),
    protect the data channel (`PROT P`), go passive, and fix binary mode for
    the whole session — `SIZE` (existence checks) is refused in ASCII mode on
    a real server (measured: `550 SIZE not allowed in ASCII mode`)."""
    ftps.login(user=username, passwd=password, secure=True)
    ftps.prot_p()
    ftps.set_pasv(True)
    ftps.voidcmd("TYPE I")


def check_ftps_connection(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    remote_root: str,
    connect_timeout: float = FILEUPLOAD_FTPS_TEST_CONNECT_TIMEOUT_SEC,
    ssl_context: ssl.SSLContext | None = None,
) -> FtpsConnectionCheck:
    """`Test connection` on the FTPS tab — the short connect timeout the
    Database Destination's own test uses (never the cycle's own longer one).

    Never raises — every outcome is :data:`FtpsTestResult`, the same
    "always answers" shape :func:`~arichds.fileupload.sftp_transport.check_sftp_connection`
    uses. *ssl_context* is a test-only seam (module docstring) — the product
    never passes one, so a self-signed certificate is always refused here
    exactly as it would be for a real cycle.
    """
    if not host.strip():
        return FtpsConnectionCheck(
            "other",
            None,
            False,
            "No host is saved — uploads are off. Fill in the host on the FTPS tab and save to start.",
        )

    try:
        ftps, subject = _connect_and_authenticate(
            host=host, port=port, connect_timeout=connect_timeout, read_timeout=connect_timeout, ssl_context=ssl_context
        )
    except Exception as exc:  # noqa: BLE001 — classified below, never re-raised as-is.
        result, _ = _classify_exception(exc)
        reply_code = _reply_code(exc) if isinstance(exc, ftplib.error_perm) else None
        return FtpsConnectionCheck(result, None, False, _message_for(result, None, reply_code=reply_code))

    try:
        try:
            _prepare_session(ftps, username=username, password=password)
            # "Lists the remote root" (ticket 05's own criterion) — a real
            # `NLST` over the *protected, passive* data channel, not `cwd`
            # (control channel only, reviewer finding, round 1, problem 1:
            # the old code never actually opened a data connection here, so
            # a blocked/NAT-broken passive channel — ADR 0025's own reason
            # FTPS was nearly dropped — reported "Connected" while every
            # later `STOR` would fail). `error_perm` here is still the same
            # "the operator has not created the root yet" case ADR 0025
            # decision 4 names — directories are created on demand — so it
            # is swallowed the same way `cwd` used to be, never a
            # Test-connection failure.
            try:
                ftps.nlst(remote_root.rstrip("/") or ".")
                remote_root_exists = True
            except ftplib.error_perm:
                remote_root_exists = False
            # `ftplib.FTP.nlst()` sends `TYPE A` internally (`retrlines`,
            # unconditionally) — binary mode does not survive a listing, so
            # it is restored here before `_manifest_exists`'s own `SIZE`,
            # which — like every other `SIZE` in this module — is refused in
            # ASCII mode (measured, module docstring's own "Binary mode
            # throughout" note).
            ftps.voidcmd("TYPE I")
            manifest_exists = _manifest_exists(ftps, remote_root)
        except Exception as exc:  # noqa: BLE001 — classified below.
            result, _ = _classify_exception(exc)
            reply_code = _reply_code(exc) if isinstance(exc, ftplib.error_perm) else None
            return FtpsConnectionCheck(result, subject, False, _message_for(result, subject, reply_code=reply_code))
    finally:
        with contextlib.suppress(Exception):
            ftps.close()

    message = (
        "Connected. The server holds a manifest." if manifest_exists else "Connected. The server has no manifest yet."
    )
    if not remote_root_exists:
        message += " The remote root does not exist yet; it will be created on the first upload."
    return FtpsConnectionCheck("ok", subject, manifest_exists, message)


def _manifest_exists(ftps: ftplib.FTP_TLS, remote_root: str) -> bool:
    try:
        ftps.size(_remote_path(remote_root, MANIFEST_FILENAME))
        return True
    except ftplib.error_perm:
        return False


class FtpsTransport:
    """The :class:`~arichds.fileupload.transport.Transport` seam, implemented
    over FTPS (`ftplib.FTP_TLS`). Every method raises :class:`TransportError`
    — carrying only the failure's class name, never a host or a credential —
    on any failure; the cycle decides what that means (ticket 02)."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        remote_root: str,
        connect_timeout: float = FILEUPLOAD_FTPS_CONNECT_TIMEOUT_SEC,
        read_timeout: float = FILEUPLOAD_FTPS_READ_TIMEOUT_SEC,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        """Every parameter is keyword-only — the same reasoning
        `SftpTransport.__init__`'s own docstring gives (reviewer finding,
        ticket 04 round 1, problem 5). *ssl_context* is the test-only seam
        the module docstring describes; the product never passes one."""
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._remote_root = remote_root
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._ssl_context = ssl_context

    def _open(self) -> ftplib.FTP_TLS:
        """Connect, negotiate `AUTH TLS`, authenticate, protect the data
        channel and go passive — every failure raises :class:`TransportError`.
        The caller is responsible for closing it (``finally: ftps.close()``)."""
        try:
            ftps, _subject = _connect_and_authenticate(
                host=self._host,
                port=self._port,
                connect_timeout=self._connect_timeout,
                read_timeout=self._read_timeout,
                ssl_context=self._ssl_context,
            )
        except Exception as exc:  # noqa: BLE001 — classified below.
            _, error = _classify_exception(exc)
            raise error from exc

        try:
            _prepare_session(ftps, username=self._username, password=self._password)
        except Exception as exc:  # noqa: BLE001 — classified below.
            with contextlib.suppress(Exception):
                ftps.close()
            _, error = _classify_exception(exc)
            raise error from exc
        return ftps

    def read_manifest(self) -> Manifest | None:
        ftps = self._open()
        try:
            remote_path = _remote_path(self._remote_root, MANIFEST_FILENAME)
            buffer = io.BytesIO()
            try:
                ftps.retrbinary(f"RETR {remote_path}", buffer.write)
            except ftplib.error_perm:
                return None
            try:
                return decode_manifest(buffer.getvalue())
            except ValueError:
                # An unreadable manifest means "send everything" (ADR 0025
                # decision 2) — the same as a missing one, never a crash
                # reaching the cycle.
                return None
        except Exception as exc:  # noqa: BLE001 — classified below.
            _, error = _classify_exception(exc)
            raise error from exc
        finally:
            with contextlib.suppress(Exception):
                ftps.close()

    def put_file(self, relative_path: str, local_path: Path) -> None:
        ftps = self._open()
        try:
            remote_path = _remote_path(self._remote_root, relative_path)
            _mkdir_p(ftps, posixpath.dirname(remote_path))
            with local_path.open("rb") as handle:
                ftps.storbinary(f"STOR {remote_path}", handle)
        except Exception as exc:  # noqa: BLE001 — classified below.
            _, error = _classify_exception(exc)
            raise error from exc
        finally:
            with contextlib.suppress(Exception):
                ftps.close()

    def write_manifest(self, manifest: Manifest) -> None:
        ftps = self._open()
        try:
            remote_path = _remote_path(self._remote_root, MANIFEST_FILENAME)
            _mkdir_p(ftps, posixpath.dirname(remote_path))
            ftps.storbinary(f"STOR {remote_path}", io.BytesIO(encode_manifest(manifest)))
        except Exception as exc:  # noqa: BLE001 — classified below.
            _, error = _classify_exception(exc)
            raise error from exc
        finally:
            with contextlib.suppress(Exception):
                ftps.close()

    def describe(self) -> str:
        """One line naming the server's identity — Test connection's own
        check, run again here so `describe()` never gets out of sync with
        what `POST .../ftps/test` actually reports (`HttpsTransport.describe()`'s
        own shape). Never passes `self._ssl_context` on to a *different*
        server than the product would actually reach — it is the same
        context the real transport connects with, test-only in practice
        because production never sets it."""
        return check_ftps_connection(
            host=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            remote_root=self._remote_root,
            connect_timeout=self._connect_timeout,
            ssl_context=self._ssl_context,
        ).message


__all__ = ["FtpsConnectionCheck", "FtpsTestResult", "FtpsTransport", "check_ftps_connection"]
