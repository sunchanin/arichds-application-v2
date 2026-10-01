"""A minimal, in-process ``pyftpdlib`` TLS server — for tests only (ADR 0025
decision 1/5, ticket 05's own criterion: "Transport tests against a
`pyftpdlib` TLS server in-process on an ephemeral port").

Same role `fake_sftp_server.py` plays for the SFTP transport (ticket 04):
the real server-side stack, never a mock of
`arichds.fileupload.ftps_transport`'s internals. Binds ``127.0.0.1`` on an
**ephemeral port** (port 0), so parallel ``pytest -n auto`` workers never
collide on a fixed one — the same `fake_central_push_receiver.py`/
`fake_sftp_server.py` shape.

Backed by a real directory on disk (a test's own ``tmp_path``), not an
in-memory filesystem, so ``FtpsTransport``'s own ``mkd``/``storbinary``/
``retrbinary``/``size`` calls exercise the exact server-side codepaths a
real FTPS server runs.
"""

from __future__ import annotations

import threading
from pathlib import Path

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import TLS_FTPHandler
from pyftpdlib.servers import FTPServer


def _refuse_active_mode(handler: TLS_FTPHandler, line: str) -> None:
    """Answers ``PORT``/``EPRT`` with a flat refusal — ADR 0025 decision 1
    requires passive mode; this pins that requirement in the fixture the way
    ``tls_data_required=True`` already pins ``PROT P`` (reviewer finding,
    round 1, problem 3)."""
    handler.respond("502 Active mode is refused by this fixture — use PASV.")


class FakeFtpsServer:
    """One in-process fake FTPS server (explicit TLS, `pyftpdlib`).

    Construct it with a real *root* directory (a test's own ``tmp_path``),
    a *cert_path*/*key_path* pair (the test's own throwaway certificate —
    ``tests/test_fileupload_ftps_transport.py`` generates one with
    `cryptography`, the `test_fileupload_https_transport.py` recipe), read
    ``.port``, drive `FtpsTransport`/`ftplib.FTP_TLS` against
    ``127.0.0.1:<port>``, then call :meth:`shutdown`.

    ``tls_data_required=True`` (pyftpdlib's own attribute,
    ``docs/lib-notes/pyftpdlib-tls.md`` §1) refuses a data-channel command
    issued without ``PROT P`` first — the server-side half of "dropping
    ``prot_p()`` from the transport turns the data-channel-protected test
    red" (ticket 05's own named mutation).

    ``PORT``/``EPRT`` (active mode) are refused outright — reviewer finding,
    round 1, problem 3: nothing previously pinned ``set_pasv(True)`` in
    ``ftps_transport.py``; a loopback fake tolerates active mode just fine,
    so flipping it to ``set_pasv(False)`` stayed green against the old
    fixture. Any transfer attempted without passive mode now fails here the
    same way an unprotected one already fails against ``tls_data_required``.

    No ``passive_ports`` range is pinned (reviewer finding, round 1, problem
    5, correcting this same digest's own §3): the address PASV advertises is
    always the control connection's own local address, already
    ``127.0.0.1`` once the server binds there — the port range buys nothing
    for a loopback-only fixture, and a fixed range plus pyftpdlib's own
    ``set_reuse_addr()`` made a 16-worker ``pytest -n auto`` run strictly
    worse on Windows than the default (``None``, kernel-picked).
    """

    def __init__(
        self,
        root: Path,
        cert_path: Path,
        key_path: Path,
        *,
        username: str = "arichds",
        password: str = "hunter2",
    ) -> None:
        authorizer = DummyAuthorizer()
        authorizer.add_user(username, password, str(root), perm="elradfmwMT")

        handler = type(f"_TLSHandler{id(self)}", (TLS_FTPHandler,), {})
        handler.certfile = str(cert_path)
        handler.keyfile = str(key_path)
        handler.authorizer = authorizer
        handler.tls_control_required = True
        handler.tls_data_required = True
        handler.ftp_PORT = _refuse_active_mode
        handler.ftp_EPRT = _refuse_active_mode

        self._server = FTPServer(("127.0.0.1", 0), handler)
        self.port = self._server.socket.getsockname()[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._server.close_all()
        self._thread.join(timeout=5)


__all__ = ["FakeFtpsServer"]
