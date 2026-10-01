"""A minimal, in-process paramiko SFTP server — for tests only (ADR 0025
decision 1/5, ticket 04's own criterion: "every transport branch has a test
against a real in-process server").

Same role `fake_central_push_receiver.py` plays for the HTTPS transport
(ticket 03): the real paramiko server-side stack, never a mock of
`arichds.fileupload.sftp_transport`'s internals. Binds ``127.0.0.1`` on an
**ephemeral port** (port 0), so parallel ``pytest -n auto`` workers never
collide on a fixed one — the same `fake_central_push_receiver.py` shape.

Backed by a real directory on disk (a test's own ``tmp_path``) rather than
an in-memory filesystem, so `SftpTransport`'s own `mkdir`/`stat`/`put`/`open`
calls exercise the exact server-side codepaths a real `sshd` runs, per
``docs/lib-notes/paramiko-sftp.md`` §6 (the ``StubServer``/``StubSFTPServer``
shapes paramiko's own test suite uses, reimplemented here since
``tests/_stub_sftp.py`` ships with paramiko's *source checkout*, not the
installed package — nothing under ``site-packages/paramiko`` to import it
from).
"""

from __future__ import annotations

import contextlib
import os
import socket
import threading
from pathlib import Path

from paramiko import (
    AUTH_FAILED,
    AUTH_SUCCESSFUL,
    OPEN_SUCCEEDED,
    RSAKey,
    ServerInterface,
    SFTPAttributes,
    SFTPHandle,
    SFTPServer,
    SFTPServerInterface,
)
from paramiko.pkey import PKey
from paramiko.sftp import SFTP_OK
from paramiko.transport import Transport


class _StubServer(ServerInterface):
    """The SSH-level authentication policy — password and/or one accepted
    public key, whichever the test configures. Never `AutoAddPolicy`-shaped:
    this decides *authentication*, not host-key trust, which is
    `sftp_transport.py`'s own job on the client side."""

    def __init__(self, *, username: str, password: str | None, authorized_key: PKey | None) -> None:
        super().__init__()
        self._username = username
        self._password = password
        self._authorized_key = authorized_key

    def check_auth_password(self, username: str, password: str) -> int:
        if self._password is not None and username == self._username and password == self._password:
            return AUTH_SUCCESSFUL
        return AUTH_FAILED

    def check_auth_publickey(self, username: str, key: PKey) -> int:
        if (
            self._authorized_key is not None
            and username == self._username
            and key.get_base64() == self._authorized_key.get_base64()
        ):
            return AUTH_SUCCESSFUL
        return AUTH_FAILED

    def get_allowed_auths(self, username: str) -> str:
        methods = []
        if self._password is not None:
            methods.append("password")
        if self._authorized_key is not None:
            methods.append("publickey")
        return ",".join(methods) if methods else "none"

    def check_channel_request(self, kind: str, chanid: int) -> int:
        return OPEN_SUCCEEDED


class _StubSFTPHandle(SFTPHandle):
    def stat(self) -> SFTPAttributes:
        try:
            return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
        except OSError as exc:
            return SFTPServer.convert_errno(exc.errno)


class _StubSFTPServer(SFTPServerInterface):
    """Backed by *root* (a real directory) — every path the client sends is
    resolved under it, the same "point at tmp_path" shape
    ``docs/lib-notes/paramiko-sftp.md`` §6 describes. Server-side-only —
    tests drive it exclusively through `SftpTransport`/`SFTPClient`, never
    directly."""

    def __init__(self, server: ServerInterface, *, root: str) -> None:
        super().__init__(server)
        self._root = root

    def _realpath(self, path: str) -> str:
        return self._root + self.canonicalize(path)

    def list_folder(self, path: str):
        real = self._realpath(path)
        try:
            out = []
            for name in os.listdir(real):
                attr = SFTPAttributes.from_stat(os.stat(os.path.join(real, name)))
                attr.filename = name
                out.append(attr)
            return out
        except OSError as exc:
            return SFTPServer.convert_errno(exc.errno)

    def stat(self, path: str):
        try:
            return SFTPAttributes.from_stat(os.stat(self._realpath(path)))
        except OSError as exc:
            return SFTPServer.convert_errno(exc.errno)

    def lstat(self, path: str):
        try:
            return SFTPAttributes.from_stat(os.lstat(self._realpath(path)))
        except OSError as exc:
            return SFTPServer.convert_errno(exc.errno)

    def open(self, path: str, flags: int, attr: SFTPAttributes):
        real = self._realpath(path)
        try:
            mode = getattr(attr, "st_mode", None)
            fd = os.open(real, flags, mode if mode is not None else 0o666)
        except OSError as exc:
            return SFTPServer.convert_errno(exc.errno)

        if flags & os.O_WRONLY:
            pymode = "ab" if flags & os.O_APPEND else "wb"
        elif flags & os.O_RDWR:
            pymode = "a+b" if flags & os.O_APPEND else "r+b"
        else:
            pymode = "rb"
        handle = _StubSFTPHandle(flags)
        handle.filename = real
        handle.readfile = handle.writefile = os.fdopen(fd, pymode)
        return handle

    def remove(self, path: str):
        try:
            os.remove(self._realpath(path))
        except OSError as exc:
            return SFTPServer.convert_errno(exc.errno)
        return SFTP_OK

    def rename(self, oldpath: str, newpath: str):
        try:
            os.rename(self._realpath(oldpath), self._realpath(newpath))
        except OSError as exc:
            return SFTPServer.convert_errno(exc.errno)
        return SFTP_OK

    def mkdir(self, path: str, attr: SFTPAttributes):
        try:
            os.mkdir(self._realpath(path))
        except OSError as exc:
            return SFTPServer.convert_errno(exc.errno)
        return SFTP_OK

    def rmdir(self, path: str):
        try:
            os.rmdir(self._realpath(path))
        except OSError as exc:
            return SFTPServer.convert_errno(exc.errno)
        return SFTP_OK


class FakeSftpServer:
    """One in-process fake SFTP server.

    Construct it with a real *root* directory (a test's own ``tmp_path``),
    read ``.port``/``.fingerprint``, drive `SftpTransport`/`SFTPClient`
    against ``127.0.0.1:<port>``, then call :meth:`shutdown`.

    Accepts any number of connections, one per accepted socket, each on its
    own daemon thread — the exact per-connection pattern
    ``docs/lib-notes/paramiko-sftp.md`` §6 shows (`Transport(conn)`,
    `add_server_key`, `set_subsystem_handler`, `start_server`).
    """

    def __init__(
        self,
        root: Path,
        *,
        username: str = "arichds",
        password: str | None = "hunter2",
        authorized_key: PKey | None = None,
        host_key: RSAKey | None = None,
    ) -> None:
        self._root = str(root)
        self._username = username
        self._password = password
        self._authorized_key = authorized_key
        self.host_key = host_key or RSAKey.generate(2048)

        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(5)
        self.port = self._listener.getsockname()[1]

        self._stopped = False
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    @property
    def fingerprint(self) -> str:
        return self.host_key.fingerprint

    def _accept_loop(self) -> None:
        self._listener.settimeout(0.5)
        while not self._stopped:
            try:
                conn, _addr = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._serve_one, args=(conn,), daemon=True).start()

    def _serve_one(self, conn: socket.socket) -> None:
        transport = Transport(conn)
        transport.add_server_key(self.host_key)
        transport.set_subsystem_handler("sftp", SFTPServer, _StubSFTPServer, root=self._root)
        server = _StubServer(username=self._username, password=self._password, authorized_key=self._authorized_key)
        event = threading.Event()
        try:
            transport.start_server(event, server)
        except Exception:  # noqa: BLE001 — a hostile/failed handshake must never crash the accept loop.
            transport.close()
            return
        event.wait(5.0)

    def shutdown(self) -> None:
        self._stopped = True
        with contextlib.suppress(OSError):
            self._listener.close()
        self._accept_thread.join(timeout=2.0)


__all__ = ["FakeSftpServer"]
