"""The SFTP File Upload Destination transport (ADR 0025 decision 1; spec.md
"SFTP specifics"; ticket 04) — the second real transport behind the seam
:mod:`arichds.fileupload.transport`, and the one runtime dependency this
whole feature adds (paramiko + PyNaCl, ``docs/lib-notes/paramiko-sftp.md``).

**Drives `paramiko.Transport` directly, never `SSHClient`** — the digest's
own §1: we pin exactly one fingerprint per server row, not a `known_hosts`
file, and `SSHClient`'s `MissingHostKeyPolicy` machinery (default
`RejectPolicy`, the demo-only `AutoAddPolicy` this product must never use)
is built for the latter shape. `Transport.get_remote_server_key()` is
available immediately after `start_client()` — **before** any
authentication attempt — so the fingerprint can always be observed and
reported, whether or not this module goes on to authenticate.

**Host key pinning is asymmetric between Test connection and the cycle**
(ticket 04's own acceptance criterion): a real transport (:class:`SftpTransport`,
what the cycle builds) refuses outright — :class:`HostKeyNotPinnedError` /
:class:`HostKeyMismatchError` — the moment a fingerprint is missing or wrong,
**never** authenticating against an unverified server. :func:`check_sftp_connection`
(Test connection) is the one place allowed to *observe* an unpinned or
changed fingerprint and report it for a human to accept — it still refuses
to authenticate past that point, the same "never send credentials to an
unverified server" rule, but returns the fingerprint instead of only a class
name. **Only `POST .../sftp/host-key` writes the pinned row** (`api/file_upload.py`)
— nothing in this module ever does, which is what "a cycle never pins on
its own" means in code.

**Reconnects per operation**, the same shape :class:`~arichds.fileupload.https_transport.HttpsTransport`
already has (a fresh `urllib` request per call) — simpler and safer than
holding one connection open across an unbounded number of candidates for a
whole cycle, at the cost of re-handshaking SSH2 per file. Flagged as an
assumption in the implementation report: nothing in ADR 0025 or spec.md
asks for connection pooling, and `FILEUPLOAD_BUDGET_SEC` already bounds a
cycle's total wall time regardless.
"""

from __future__ import annotations

import posixpath
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from paramiko import PKey, SFTPClient
from paramiko import Transport as ParamikoTransport
from paramiko.ssh_exception import AuthenticationException, SSHException

from arichds.constants import (
    FILEUPLOAD_SFTP_CONNECT_TIMEOUT_SEC,
    FILEUPLOAD_SFTP_READ_TIMEOUT_SEC,
    FILEUPLOAD_SFTP_TEST_CONNECT_TIMEOUT_SEC,
)
from arichds.fileupload.manifest import MANIFEST_FILENAME, Manifest, decode_manifest, encode_manifest
from arichds.fileupload.transport import TransportError


class HostKeyMismatchError(TransportError):
    """The server's host key no longer matches the pinned fingerprint.

    ``str(self)`` is still class-name-only (``TransportError``'s own rule) —
    the *new* fingerprint an operator would need to decide whether to accept
    is never carried here; it only ever reaches :class:`SftpConnectionCheck`
    (Test connection), never a log line or an exception message a background
    cycle might print.
    """


class HostKeyNotPinnedError(TransportError):
    """No fingerprint has been pinned yet. Raised only by the real transport
    (:class:`SftpTransport`, what the cycle builds) — never by
    :func:`check_sftp_connection`, which reports this case instead of
    raising, so the page can show the fingerprint to accept."""


#: What :func:`check_sftp_connection` (and, through it, `describe()`) can
#: answer — mirrors :data:`~arichds.fileupload.https_transport.FilesTestResult`'s
#: "every outcome is data, not an exception" shape, extended with the two
#: host-key-specific outcomes and paramiko's own credential/key-file failure
#: modes.
SftpTestResult = Literal[
    "ok",
    "unreachable",
    "timed_out",
    "bad_credentials",
    "host_key_mismatch",
    "host_key_not_pinned",
    "missing_key_file",
    "other",
]


@dataclass(frozen=True, slots=True)
class SftpConnectionCheck:
    """One Test connection result.

    Attributes:
        result: Which of :data:`SftpTestResult` this is.
        fingerprint: The server's host-key fingerprint as observed on *this*
            attempt — present whenever the TCP/SSH2 handshake itself
            succeeded (``ok``, both host-key outcomes), ``None`` when the
            connection never got that far (unreachable/timed out/other).
            **Never** carried on `bad_credentials`/`missing_key_file` even
            though the handshake succeeded there too — those failures are
            about the *credential*, not the *server's identity*, and the
            page's "Pin this key" action only ever appears next to the two
            host-key outcomes.
        manifest_exists: Whether the server already holds a manifest.
        message: One operator-actionable English sentence.
    """

    result: SftpTestResult
    fingerprint: str | None
    manifest_exists: bool
    message: str


def _remote_path(remote_root: str, relative_path: str) -> str:
    """*relative_path* prefixed by *remote_root* — preserves a leading ``/``
    (an absolute server-side path, the common case: ``/home/arichds``) rather
    than stripping it the way :func:`arichds.fileupload.https_transport._remote_path`
    strips a URL path segment, since stripping it here would silently turn an
    absolute remote root into one relative to the SFTP session's own default
    directory."""
    root = remote_root.rstrip("/")
    return f"{root}/{relative_path}" if root else relative_path


def _mkdir_p(sftp: SFTPClient, remote_dir: str) -> None:
    """Create *remote_dir* and every missing parent, tolerating "already
    exists" — `mkdir` is **not** idempotent on its own
    (``docs/lib-notes/paramiko-sftp.md`` §3: the "exists" failure carries no
    errno on most real `sshd`s), so each segment is `stat()`-ed first and
    `mkdir`-ed only when missing."""
    if remote_dir in ("", "/", "."):
        return
    path = "/" if remote_dir.startswith("/") else ""
    for segment in filter(None, remote_dir.split("/")):
        path = posixpath.join(path, segment)
        try:
            sftp.stat(path)
        except OSError:
            sftp.mkdir(path)


def _authenticate(
    transport: ParamikoTransport, *, username: str, password: str, key_path: str, key_passphrase: str
) -> None:
    """Password or key-file authentication — key file wins when both are
    configured, mirroring the SSH convention of trying pubkey before a
    password. The key is read from *key_path* here, at connect time, under
    the service account — never at save time (spec.md: "the file never
    enters the database") — via `PKey.from_path`, which auto-detects RSA vs
    Ed25519 from the file's own contents (paramiko 5.0.0; its `password=`
    kwarg was `passphrase=` before 5.0, `docs/lib-notes/paramiko-sftp.md` §2).

    **`password=` requires `bytes`, despite its own `str | None` annotation**
    (measured against the installed 5.0.0, `docs/lib-notes/paramiko-sftp.md`
    §2, corrected) — passing the configured passphrase as `str` raises
    `TypeError: password must be bytes` before it ever reaches the key
    material, so every encrypted key would fail regardless of whether the
    passphrase was right. Encoded UTF-8 here, the one place this module
    talks to `cryptography`'s loader directly.
    """
    if key_path:
        key = PKey.from_path(key_path, password=key_passphrase.encode("utf-8") if key_passphrase else None)
        transport.auth_publickey(username, key)
    else:
        transport.auth_password(username, password)


def _classify_exception(exc: Exception) -> tuple[SftpTestResult, TransportError]:
    """Map any exception this module can raise while connecting,
    authenticating or operating to both the Test-connection result literal
    and the `TransportError` a real transport method raises — the one
    classifier every call site shares (mirrors
    `https_transport.py`'s own single classifier between `describe()` and
    `check_https_connection()`). `str()` on the returned `TransportError` is
    always `type(exc).__name__` alone — never a host, a credential, or a
    paramiko message that might carry one (`docs/lib-notes/paramiko-sftp.md`
    §4)."""
    if isinstance(exc, FileNotFoundError):
        return "missing_key_file", TransportError(type(exc).__name__)
    if isinstance(exc, (ValueError, TypeError)):
        # `PKey.from_path` (loading *key_path*) raises `cryptography`'s own
        # `ValueError` for a wrong passphrase or a malformed key file, and
        # `TypeError` for a missing passphrase on an encrypted key
        # (`docs/lib-notes/paramiko-sftp.md` §2, corrected) — both are a bad
        # credential under the ticket's own failure list, never `other`.
        # Nothing else on this module's connect/auth/operate path raises
        # either.
        return "bad_credentials", TransportError(type(exc).__name__)
    if isinstance(exc, AuthenticationException):
        return "bad_credentials", TransportError(type(exc).__name__)
    if isinstance(exc, TimeoutError):
        return "timed_out", TransportError(type(exc).__name__)
    if isinstance(exc, (OSError, SSHException)):
        return "unreachable", TransportError(type(exc).__name__)
    return "other", TransportError(type(exc).__name__)


def _handshake(host: str, port: int, connect_timeout: float, read_timeout: float) -> tuple[ParamikoTransport, str]:
    """Open a TCP connection, negotiate SSH2, and return the still-
    unauthenticated `Transport` plus the server's host-key fingerprint.

    *connect_timeout* bounds the TCP connect and the SSH2 banner/kex alone
    (`sock.settimeout(connect_timeout)` before `Transport(sock)` — paramiko
    reads the banner and negotiates the key exchange off the raw socket
    during `start_client`, `docs/lib-notes/paramiko-sftp.md` §5); the socket
    is then loosened to *read_timeout* for whatever authentication and data
    transfer follows, so a large Billing capture document over a slow link
    is not mistaken for a stalled connection the way a single short timeout
    covering the whole call would.  Any exception here propagates
    unclassified — every caller wraps this in its own try/except and calls
    :func:`_classify_exception`.
    """
    sock = socket.create_connection((host, port), timeout=connect_timeout)
    sock.settimeout(connect_timeout)
    transport = ParamikoTransport(sock)
    transport.start_client(timeout=connect_timeout)
    sock.settimeout(read_timeout)
    fingerprint = transport.get_remote_server_key().fingerprint
    return transport, fingerprint


def _stat_exists(sftp: SFTPClient, path: str) -> bool:
    try:
        sftp.stat(path)
        return True
    except OSError:
        return False


def _message_for(result: SftpTestResult, fingerprint: str | None) -> str:
    if result == "unreachable":
        return "Could not reach the server."
    if result == "timed_out":
        return "The connection timed out."
    if result == "bad_credentials":
        return "The server refused the password or key."
    if result == "missing_key_file":
        return "The key file could not be read on this machine."
    if result == "host_key_mismatch":
        return (
            f"The server presented a different host key ({fingerprint}) than the one pinned. Refused — accept it "
            "below only if you expect the server's key to have changed."
        )
    if result == "host_key_not_pinned":
        return f"First contact — the server's host key is {fingerprint}. Accept it below to pin it and connect."
    return "The connection failed."


def check_sftp_connection(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    key_path: str,
    key_passphrase: str,
    remote_root: str,
    pinned_fingerprint: str,
    connect_timeout: float = FILEUPLOAD_SFTP_TEST_CONNECT_TIMEOUT_SEC,
) -> SftpConnectionCheck:
    """`Test connection` on the SFTP tab — the short connect timeout the
    Database Destination's own test uses (never the cycle's own longer one).

    Every parameter is keyword-only (reviewer finding, ticket 04 round 1,
    problem 5) — eight positional scalars of the same type (`str`) is
    exactly the shape where two adjacent arguments transpose silently; a
    caller must now name each one.

    Never raises — every outcome is :data:`SftpTestResult`, the same
    "always answers" shape :func:`~arichds.fileupload.https_transport.check_https_connection`
    uses. A missing or mismatched pinned fingerprint is reported, **never**
    treated as a reason to authenticate anyway — the one place this module
    is allowed to observe an unpinned/changed key without refusing outright,
    but it still never sends a credential past that point.
    """
    if not host.strip():
        return SftpConnectionCheck(
            "other",
            None,
            False,
            "No host is saved — uploads are off. Fill in the host on the SFTP tab and save to start.",
        )

    try:
        transport, fingerprint = _handshake(host, port, connect_timeout, connect_timeout)
    except Exception as exc:  # noqa: BLE001 — classified below, never re-raised as-is.
        result, _ = _classify_exception(exc)
        return SftpConnectionCheck(result, None, False, _message_for(result, None))

    try:
        if not pinned_fingerprint:
            return SftpConnectionCheck(
                "host_key_not_pinned", fingerprint, False, _message_for("host_key_not_pinned", fingerprint)
            )
        if fingerprint != pinned_fingerprint:
            return SftpConnectionCheck(
                "host_key_mismatch", fingerprint, False, _message_for("host_key_mismatch", fingerprint)
            )
        try:
            _authenticate(
                transport, username=username, password=password, key_path=key_path, key_passphrase=key_passphrase
            )
            sftp = SFTPClient.from_transport(transport)
            if sftp is None:
                raise SSHException("SFTP subsystem request failed")
            try:
                # "Lists the remote root" (ticket 04's own criterion) — best
                # effort: a root the operator has not created on the server
                # yet is not a Test-connection failure (ADR 0025 decision 4:
                # "directories are created on demand"), so a missing target
                # is swallowed here rather than propagated to the generic
                # classifier below — but recorded, so the operator still
                # gets the one signal a typo in the field would otherwise
                # cost them (reviewer finding, ticket 04 round 1, problem 6:
                # `ok` must not read as "the root exists" when it doesn't).
                remote_root_exists = True
                try:
                    sftp.listdir(remote_root.rstrip("/") or ".")
                except FileNotFoundError:
                    remote_root_exists = False
                manifest_exists = _stat_exists(sftp, _remote_path(remote_root, MANIFEST_FILENAME))
            finally:
                sftp.close()
        except Exception as exc:  # noqa: BLE001 — classified below.
            result, _ = _classify_exception(exc)
            return SftpConnectionCheck(result, fingerprint, False, _message_for(result, fingerprint))
    finally:
        transport.close()

    message = (
        "Connected. The server holds a manifest." if manifest_exists else "Connected. The server has no manifest yet."
    )
    if not remote_root_exists:
        message += " The remote root does not exist yet; it will be created on the first upload."
    return SftpConnectionCheck("ok", fingerprint, manifest_exists, message)


def _close(sftp: SFTPClient) -> None:
    """`SFTPClient.close()` alone only closes the SFTP channel, not the
    underlying `Transport` (its own docstring: "Close the SFTP session and
    its underlying channel") — the TCP connection is only actually released
    once the `Transport` is closed too."""
    channel = sftp.get_channel()
    transport = channel.get_transport() if channel is not None else None
    sftp.close()
    if transport is not None:
        transport.close()


class SftpTransport:
    """The :class:`~arichds.fileupload.transport.Transport` seam, implemented
    over SFTP (paramiko). Every method raises :class:`TransportError` —
    carrying only the failure's class name, host-key mismatch/not-pinned
    included — never a host, a credential, or a paramiko message that might
    carry one; the cycle decides what that means (ticket 02)."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        key_path: str,
        key_passphrase: str,
        remote_root: str,
        pinned_fingerprint: str,
        connect_timeout: float = FILEUPLOAD_SFTP_CONNECT_TIMEOUT_SEC,
        read_timeout: float = FILEUPLOAD_SFTP_READ_TIMEOUT_SEC,
    ) -> None:
        """Every parameter is keyword-only (reviewer finding, ticket 04
        round 1, problem 5) — the same reasoning `check_sftp_connection`'s
        own docstring gives."""
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._key_path = key_path
        self._key_passphrase = key_passphrase
        self._remote_root = remote_root
        self._pinned_fingerprint = pinned_fingerprint
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout

    def _open(self) -> SFTPClient:
        """Connect, refuse a missing or mismatched pinned fingerprint —
        **never** authenticating past that point ("a cycle never pins on its
        own") — authenticate, and return a ready `SFTPClient`. The caller is
        responsible for closing it with :func:`_close`."""
        try:
            transport, fingerprint = _handshake(self._host, self._port, self._connect_timeout, self._read_timeout)
        except Exception as exc:  # noqa: BLE001 — classified below.
            _, error = _classify_exception(exc)
            raise error from exc

        try:
            if not self._pinned_fingerprint:
                raise HostKeyNotPinnedError
            if fingerprint != self._pinned_fingerprint:
                raise HostKeyMismatchError
            _authenticate(
                transport,
                username=self._username,
                password=self._password,
                key_path=self._key_path,
                key_passphrase=self._key_passphrase,
            )
            sftp = SFTPClient.from_transport(transport)
            if sftp is None:
                raise SSHException("SFTP subsystem request failed")
            return sftp
        except Exception as exc:  # noqa: BLE001 — classified below (or re-raised as-is when already ours).
            transport.close()
            if isinstance(exc, TransportError):
                raise
            _, error = _classify_exception(exc)
            raise error from exc

    def read_manifest(self) -> Manifest | None:
        sftp = self._open()
        try:
            remote_path = _remote_path(self._remote_root, MANIFEST_FILENAME)
            try:
                with sftp.open(remote_path, "rb") as handle:
                    data = handle.read()
            except FileNotFoundError:
                return None
            try:
                return decode_manifest(data)
            except ValueError:
                # An unreadable manifest means "send everything" (ADR 0025
                # decision 2) — the same as a missing one, never a crash
                # reaching the cycle.
                return None
        except TransportError:
            raise
        except Exception as exc:  # noqa: BLE001 — classified below.
            _, error = _classify_exception(exc)
            raise error from exc
        finally:
            _close(sftp)

    def put_file(self, relative_path: str, local_path: Path) -> None:
        sftp = self._open()
        try:
            remote_path = _remote_path(self._remote_root, relative_path)
            _mkdir_p(sftp, posixpath.dirname(remote_path))
            sftp.put(str(local_path), remote_path, confirm=True)
        except TransportError:
            raise
        except Exception as exc:  # noqa: BLE001 — classified below.
            _, error = _classify_exception(exc)
            raise error from exc
        finally:
            _close(sftp)

    def write_manifest(self, manifest: Manifest) -> None:
        sftp = self._open()
        try:
            remote_path = _remote_path(self._remote_root, MANIFEST_FILENAME)
            _mkdir_p(sftp, posixpath.dirname(remote_path))
            with sftp.open(remote_path, "wb") as handle:
                handle.write(encode_manifest(manifest))
        except TransportError:
            raise
        except Exception as exc:  # noqa: BLE001 — classified below.
            _, error = _classify_exception(exc)
            raise error from exc
        finally:
            _close(sftp)

    def describe(self) -> str:
        """One line naming the server's identity — Test connection's own
        check, run again here so `describe()` never gets out of sync with
        what `POST .../sftp/test` actually reports (`HttpsTransport.describe()`'s
        own shape)."""
        return check_sftp_connection(
            host=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            key_path=self._key_path,
            key_passphrase=self._key_passphrase,
            remote_root=self._remote_root,
            pinned_fingerprint=self._pinned_fingerprint,
            connect_timeout=self._connect_timeout,
        ).message


__all__ = [
    "HostKeyMismatchError",
    "HostKeyNotPinnedError",
    "SftpConnectionCheck",
    "SftpTestResult",
    "SftpTransport",
    "check_sftp_connection",
]
