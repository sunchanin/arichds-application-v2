"""The FTPS File Upload Destination transport (ADR 0025, spec.md "FTPS
specifics", ticket 05) — driven against `FakeFtpsServer`, a real in-process
`pyftpdlib` TLS server on an ephemeral port
(`docs/lib-notes/pyftpdlib-tls.md`), the same "a good test drives the cycle
from the outside ... and asserts on what the server holds afterwards"
discipline spec.md's own Testing Decisions section states, and
`test_fileupload_https_transport.py`/`test_fileupload_sftp_transport.py`
already follow against their own fakes.
"""

from __future__ import annotations

import contextlib
import datetime
import ipaddress
import logging
import socket
import ssl
import threading
from datetime import UTC
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fake_ftps_server import FakeFtpsServer
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import TLS_FTPHandler
from pyftpdlib.servers import FTPServer

from arichds.db.app_settings import (
    EXPORT_OUTPUT_DIR_KEY,
    FILEUPLOAD_ACTIVE_PROTOCOL_KEY,
    FILEUPLOAD_FTPS_HOST_KEY,
    FILEUPLOAD_FTPS_PASSWORD_KEY,
    FILEUPLOAD_FTPS_PORT_KEY,
    FILEUPLOAD_FTPS_REMOTE_ROOT_KEY,
    FILEUPLOAD_FTPS_USERNAME_KEY,
    set_setting,
)
from arichds.db.models import Device
from arichds.db.session import session_scope
from arichds.fileupload import ftps_transport as ftps_transport_module
from arichds.fileupload.cycle import file_upload_cycle
from arichds.fileupload.ftps_transport import FtpsTransport, check_ftps_connection
from arichds.fileupload.manifest import Manifest, ManifestEntry
from arichds.fileupload.status import last_cycle, set_last_cycle
from arichds.fileupload.transport import TransportError
from arichds.licensing.current import set_current_license_service
from arichds.licensing.service import LicenseState
from arichds.logging_config import CredentialRedactionFilter

TEST_MACHINE_ID = "c" * 64
PASSWORD = "hunter2"


class _StubLicenseService:
    """The same minimal stand-in the HTTPS/SFTP transport tests use for the
    background-path licence gate."""

    def __init__(self, features: list[str] | None, *, machine_id: str = TEST_MACHINE_ID) -> None:
        self._features = features
        self.machine_id = machine_id

    def current_state(self) -> LicenseState:
        return LicenseState(state="active", reason=None, features=self._features)


def _write_self_signed_cert(tmp_path: Path) -> tuple[Path, Path]:
    """A throwaway self-signed certificate for ``127.0.0.1`` — the
    `docs/lib-notes/pyftpdlib-tls.md` §4 recipe (a SAN for ``127.0.0.1`` so
    hostname verification can pass for the *trusted* variant of a test; the
    *untrusted* variant never loads this certificate as a CA and is refused
    regardless of the SAN)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
        )
    )
    return cert_path, key_path


@pytest.fixture
def ftps_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    return root


@pytest.fixture
def cert(tmp_path: Path) -> tuple[Path, Path]:
    return _write_self_signed_cert(tmp_path)


@pytest.fixture
def trusted_context(cert: tuple[Path, Path]) -> ssl.SSLContext:
    """Trusts the fixture server's own self-signed certificate without
    touching the machine's real trust store — `load_verify_locations` on a
    normally-built context, `docs/lib-notes/pyftpdlib-tls.md` §7."""
    cert_path, _key_path = cert
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(cert_path))
    return context


@pytest.fixture
def server(ftps_root: Path, cert: tuple[Path, Path]):
    cert_path, key_path = cert
    s = FakeFtpsServer(ftps_root, cert_path, key_path, password=PASSWORD)
    yield s
    s.shutdown()


def _closed_port() -> int:
    """A port nothing listens on — mirrors
    `test_fileupload_sftp_transport.py::_closed_port`'s own helper."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class _PatchedSsl:
    """A thin proxy over the real `ssl` module that answers
    `create_default_context()` with a pre-built (trusted) context and
    delegates everything else — the "monkeypatch `ssl.create_default_context`
    in the transport module for that one test" seam the delegation prompt
    names, scoped to `ftps_transport`'s own module-level `ssl` binding only
    (never the process-wide `ssl` module, which would leak into every other
    test in the same worker)."""

    def __init__(self, context: ssl.SSLContext) -> None:
        self._context = context

    def create_default_context(self, *args: object, **kwargs: object) -> ssl.SSLContext:
        return self._context

    def __getattr__(self, name: str) -> object:
        return getattr(ssl, name)


class _ProtRefusingFtpsServer:
    """A one-off fixture, not `FakeFtpsServer`, for problem 4's own scenario
    (reviewer finding, round 1): a server that accepts TLS and credentials
    but refuses `PROT P` with a non-`530`/`532` 5xx — measured against a
    real `pyftpdlib` server as `534 Request denied for policy reasons.`,
    `ftplib.error_perm`. Lives here rather than in `fake_ftps_server.py`
    since no other test needs a server shaped like this."""

    def __init__(self, root: Path, cert_path: Path, key_path: Path) -> None:
        authorizer = DummyAuthorizer()
        authorizer.add_user("arichds", PASSWORD, str(root), perm="elradfmwMT")

        def _refuse_prot(handler: TLS_FTPHandler, _line: str) -> None:
            handler.respond("534 Request denied for policy reasons.")

        handler = type(f"_ProtRefusingHandler{id(self)}", (TLS_FTPHandler,), {})
        handler.certfile = str(cert_path)
        handler.keyfile = str(key_path)
        handler.authorizer = authorizer
        handler.tls_control_required = True
        handler.ftp_PROT = _refuse_prot

        self._server = FTPServer(("127.0.0.1", 0), handler)
        self.port = self._server.socket.getsockname()[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._server.close_all()
        self._thread.join(timeout=5)


class _StallingServer:
    """Accepts a connection and never answers — proves the `timed_out`
    branch (reviewer finding, round 1, problem 6: nothing under test
    previously pinned it, so dropping the `TimeoutError` branch from
    `_classify_exception` stayed green). Mirrors
    `test_fileupload_https_transport.py::TestCheckHttpsConnection`'s own
    `receiver.stall_seconds` shape, adapted to FTPS's own protocol: the
    client blocks reading `ftplib.FTP.connect()`'s welcome banner, which
    `socket.create_connection`'s own timeout (passed through as
    *connect_timeout*) bounds."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self._stopped = False
        # Every accepted connection is kept here — an unreferenced socket
        # object is garbage-collected (and closed) almost immediately,
        # which sends the client an instant `EOFError` instead of a stall
        # (measured: the first draft of this fixture did exactly that, and
        # the test it was meant to pin got `other`, not `timed_out`).
        self._connections: list[socket.socket] = []
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        self._sock.settimeout(0.5)
        while not self._stopped:
            try:
                conn, _addr = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            # Held open and never written to — the client's own read times
            # out first, never this side.
            self._connections.append(conn)

    def shutdown(self) -> None:
        self._stopped = True
        with contextlib.suppress(OSError):
            self._sock.close()
        self._thread.join(timeout=2)
        for conn in self._connections:
            with contextlib.suppress(OSError):
                conn.close()


class TestPutFile:
    def test_the_file_arrives_byte_equal(
        self, server: FakeFtpsServer, ftps_root: Path, trusted_context: ssl.SSLContext, tmp_path: Path
    ) -> None:
        """Also the discriminating test for the named mutation "drop
        `prot_p()`" (ticket 05's own delegation prompt): the fake server is
        built with `tls_data_required=True`
        (`docs/lib-notes/pyftpdlib-tls.md` §1), which refuses an unprotected
        data-channel command — an unprotected `STOR` would raise
        `ftplib.error_perm` here instead of succeeding."""
        local = tmp_path / "SN0001.csv"
        local.write_bytes(b"csv content\r\n1,2,3\r\n")
        transport = FtpsTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            remote_root="",
            ssl_context=trusted_context,
        )

        transport.put_file("export/SN0001.csv", local)

        assert (ftps_root / "export" / "SN0001.csv").read_bytes() == local.read_bytes()

    def test_nested_directories_are_created_on_demand(
        self, server: FakeFtpsServer, ftps_root: Path, trusted_context: ssl.SSLContext, tmp_path: Path
    ) -> None:
        """Mutation: making `_mkdir_p` a no-op turns this red — the nested
        `captures/<serial>/` layer (ADR 0025 decision 4) does not exist on a
        fresh server."""
        local = tmp_path / "2026-09-01.pdf"
        local.write_bytes(b"%PDF-fake")
        transport = FtpsTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            remote_root="",
            ssl_context=trusted_context,
        )

        transport.put_file("captures/SN0001/2026-09-01.pdf", local)

        assert (ftps_root / "captures" / "SN0001" / "2026-09-01.pdf").read_bytes() == local.read_bytes()

    def test_remote_root_is_folded_into_the_relative_path(
        self, server: FakeFtpsServer, ftps_root: Path, trusted_context: ssl.SSLContext, tmp_path: Path
    ) -> None:
        local = tmp_path / "SN0001.csv"
        local.write_bytes(b"x")
        transport = FtpsTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            remote_root="/arichds",
            ssl_context=trusted_context,
        )

        transport.put_file("export/SN0001.csv", local)

        assert (ftps_root / "arichds" / "export" / "SN0001.csv").read_bytes() == local.read_bytes()


class TestDescribe:
    def test_it_matches_check_ftps_connections_own_message(
        self, server: FakeFtpsServer, trusted_context: ssl.SSLContext
    ) -> None:
        transport = FtpsTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            remote_root="",
            ssl_context=trusted_context,
        )

        assert (
            transport.describe()
            == check_ftps_connection(
                host="127.0.0.1",
                port=server.port,
                username="arichds",
                password=PASSWORD,
                remote_root="",
                ssl_context=trusted_context,
            ).message
        )


class TestManifestRoundTrips:
    def test_a_fresh_root_reads_as_no_manifest(self, server: FakeFtpsServer, trusted_context: ssl.SSLContext) -> None:
        transport = FtpsTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            remote_root="",
            ssl_context=trusted_context,
        )

        assert transport.read_manifest() is None

    def test_write_then_read_returns_the_same_manifest(
        self, server: FakeFtpsServer, trusted_context: ssl.SSLContext
    ) -> None:
        transport = FtpsTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            remote_root="",
            ssl_context=trusted_context,
        )
        manifest = Manifest(
            version=1,
            machine_id=TEST_MACHINE_ID,
            files={
                "export/SN0001.csv": ManifestEntry(
                    sha256="abc123", size=42, uploaded_at=datetime.datetime(2026, 9, 1, tzinfo=UTC)
                )
            },
        )

        transport.write_manifest(manifest)
        round_tripped = transport.read_manifest()

        assert round_tripped == manifest


class TestWrongPasswordIsBadCredentials:
    def test_put_file_raises_a_transport_error_named_error_perm(
        self, server: FakeFtpsServer, trusted_context: ssl.SSLContext, tmp_path: Path
    ) -> None:
        local = tmp_path / "a.csv"
        local.write_text("x", encoding="utf-8")
        transport = FtpsTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password="wrong-password",
            remote_root="",
            ssl_context=trusted_context,
        )

        with pytest.raises(TransportError) as excinfo:
            transport.put_file("export/a.csv", local)
        assert str(excinfo.value) == "error_perm"


class TestSelfSignedCertificateIsRefused:
    """Memory: *a transport branch no test reaches ships broken* — the
    `HttpsTransport`/`SftpTransport` precedent. No `ssl_context=` is passed
    here, exactly what production does (the module docstring's own
    "the product never passes one" rule): the real default trust store
    refuses the fixture server's self-signed certificate."""

    def test_read_manifest_raises_a_transport_error_not_typeerror(self, server: FakeFtpsServer) -> None:
        transport = FtpsTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            remote_root="",
            connect_timeout=5,
            read_timeout=5,
        )

        with pytest.raises(TransportError) as excinfo:
            transport.read_manifest()

        assert str(excinfo.value) == "SSLCertVerificationError"


class TestUnreachableHost:
    def test_read_manifest_raises_a_transport_error_not_typeerror(self) -> None:
        transport = FtpsTransport(
            host="127.0.0.1",
            port=_closed_port(),
            username="arichds",
            password=PASSWORD,
            remote_root="",
            connect_timeout=2,
            read_timeout=2,
        )

        with pytest.raises(TransportError):
            transport.read_manifest()


class TestCheckFtpsConnection:
    def test_ok_and_no_manifest(self, server: FakeFtpsServer, trusted_context: ssl.SSLContext) -> None:
        check = check_ftps_connection(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            remote_root="",
            ssl_context=trusted_context,
        )

        assert check.result == "ok"
        assert check.manifest_exists is False
        assert check.subject is not None
        assert "127.0.0.1" in check.subject

    def test_ok_and_manifest_present(self, server: FakeFtpsServer, trusted_context: ssl.SSLContext) -> None:
        transport = FtpsTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            remote_root="",
            ssl_context=trusted_context,
        )
        transport.write_manifest(Manifest(version=1, machine_id=TEST_MACHINE_ID, files={}))

        check = check_ftps_connection(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            remote_root="",
            ssl_context=trusted_context,
        )

        assert check.result == "ok"
        assert check.manifest_exists is True

    def test_wrong_password_is_bad_credentials(self, server: FakeFtpsServer, trusted_context: ssl.SSLContext) -> None:
        check = check_ftps_connection(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password="wrong-password",
            remote_root="",
            ssl_context=trusted_context,
        )

        assert check.result == "bad_credentials"
        # The handshake itself succeeded (the certificate is trusted) —
        # `subject` is still reported, only the credential was refused
        # (`FtpsConnectionCheck`'s own docstring).
        assert check.subject is not None

    def test_a_self_signed_certificate_is_untrusted(self, server: FakeFtpsServer) -> None:
        """Mutation: replacing the default context with `CERT_NONE` (or
        dropping the untrusted-certificate branch) turns this red — the
        named mutation ticket 05's own delegation prompt calls out. No
        `ssl_context=` here — the real default trust store."""
        check = check_ftps_connection(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            remote_root="",
            connect_timeout=5,
        )

        assert check.result == "untrusted_certificate"
        assert check.subject is None

    def test_a_closed_port_is_unreachable_or_timed_out(self) -> None:
        check = check_ftps_connection(
            host="127.0.0.1",
            port=_closed_port(),
            username="arichds",
            password=PASSWORD,
            remote_root="",
            connect_timeout=2,
        )

        assert check.result in ("unreachable", "timed_out")
        assert check.subject is None

    def test_a_blank_host_is_other_and_makes_no_request(self) -> None:
        check = check_ftps_connection(host="", port=21, username="arichds", password=PASSWORD, remote_root="")

        assert check.result == "other"
        assert check.subject is None

    def test_an_unset_remote_root_that_does_not_exist_yet_still_reports_ok(
        self, server: FakeFtpsServer, trusted_context: ssl.SSLContext
    ) -> None:
        """ADR 0025 decision 4 — "directories are created on demand" — Test
        connection must not fail just because the operator has not created
        the remote root folder yet, the same `check_sftp_connection`
        convention."""
        check = check_ftps_connection(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            remote_root="/not-created-yet",
            ssl_context=trusted_context,
        )

        assert check.result == "ok"
        assert "does not exist yet" in check.message

    def test_an_existing_remote_root_gets_no_does_not_exist_clause(
        self, server: FakeFtpsServer, trusted_context: ssl.SSLContext
    ) -> None:
        check = check_ftps_connection(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            remote_root="",
            ssl_context=trusted_context,
        )

        assert check.result == "ok"
        assert "does not exist yet" not in check.message

    def test_ok_confirms_an_existing_root_via_a_real_listing(
        self, server: FakeFtpsServer, ftps_root: Path, trusted_context: ssl.SSLContext
    ) -> None:
        """Reviewer finding, round 1, problem 1: `check_ftps_connection`
        used to call `cwd()` (control channel only) and never actually
        opened a data connection, so a blocked/NAT-broken passive channel —
        ADR 0025's own reason FTPS was nearly dropped — still reported
        "Connected", and every later `STOR` would then fail.

        Mutation-probed against the two ways a data channel actually goes
        bad, not against `nlst`/`cwd` in isolation — the two commands agree
        whenever the root merely *exists*, which a root exists either way
        regardless of the data channel, so swapping one for the other with
        nothing else broken does **not** discriminate (measured: reverting
        `nlst` to `cwd` alone left this test green). What does discriminate
        is the data channel itself failing while the control channel stays
        fine — exactly the case `cwd` could never detect and `nlst` now
        can:
        - dropping `prot_p()` from `_prepare_session` (the fake's own
          `tls_data_required=True` then refuses the unprotected `NLST`) —
          measured red, via the "does not exist yet" clause appearing for a
          root that does exist.
        - flipping `set_pasv(True)` to `False` (the fake's own
          `_refuse_active_mode`, problem 3) — same mechanism.
        Both mutations already turn every `TestPutFile` test red too; this
        test adds `check_ftps_connection` itself to that coverage, which is
        the gap problem 1 named."""
        (ftps_root / "already-here.txt").write_bytes(b"x")

        check = check_ftps_connection(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            remote_root="",
            ssl_context=trusted_context,
        )

        assert check.result == "ok"
        assert "does not exist yet" not in check.message

    def test_a_stalling_server_is_timed_out(self) -> None:
        server = _StallingServer()
        try:
            check = check_ftps_connection(
                host="127.0.0.1",
                port=server.port,
                username="arichds",
                password=PASSWORD,
                remote_root="",
                connect_timeout=0.3,
            )

            assert check.result == "timed_out"
        finally:
            server.shutdown()


class TestNonCredentialErrorPermIsNotMisdiagnosed:
    """Reviewer finding, round 1, problem 4: every `ftplib.error_perm` used
    to collapse into `bad_credentials`, so a server refusing `PROT P` (a
    real, if uncommon, server policy — measured via `_ProtRefusingFtpsServer`
    above) told the operator to re-type a correct password. Only `530`/`532`
    may say that now; anything else names its own reply code instead."""

    def test_a_refused_prot_p_is_other_not_bad_credentials(
        self, ftps_root: Path, cert: tuple[Path, Path], trusted_context: ssl.SSLContext
    ) -> None:
        cert_path, key_path = cert
        server = _ProtRefusingFtpsServer(ftps_root, cert_path, key_path)
        try:
            check = check_ftps_connection(
                host="127.0.0.1",
                port=server.port,
                username="arichds",
                password=PASSWORD,
                remote_root="",
                ssl_context=trusted_context,
            )

            assert check.result == "other"
            assert "534" in check.message
            assert "refused the username or password" not in check.message
        finally:
            server.shutdown()


class TestClassifyExceptionByReplyCode:
    """Direct, deterministic proof of `_reply_code`/`_classify_exception`'s
    own branching (reviewer finding, round 1, problem 4) — no live server
    needed for the code-branch itself; `TestNonCredentialErrorPermIsNotMisdiagnosed`
    above is the live end-to-end proof."""

    def test_530_is_bad_credentials(self) -> None:
        import ftplib

        result, _ = ftps_transport_module._classify_exception(ftplib.error_perm("530 Authentication failed."))

        assert result == "bad_credentials"

    def test_532_is_bad_credentials(self) -> None:
        import ftplib

        result, _ = ftps_transport_module._classify_exception(ftplib.error_perm("532 Need account for storing files."))

        assert result == "bad_credentials"

    def test_another_5xx_is_other_not_bad_credentials(self) -> None:
        import ftplib

        result, _ = ftps_transport_module._classify_exception(
            ftplib.error_perm("534 Request denied for policy reasons.")
        )

        assert result == "other"

    def test_message_names_the_reply_code_for_other(self) -> None:
        message = ftps_transport_module._message_for("other", None, reply_code="534")

        assert "534" in message

    def test_reply_code_of_a_malformed_message_is_none(self) -> None:
        assert ftps_transport_module._reply_code(ValueError("not shaped like a reply")) is None


class TestSecretsNeverReachALog:
    """Mirrors `test_fileupload_sftp_transport.py`'s own proof: `cycle.py`
    logs only `type(exc).__name__` (always the bare `TransportError`
    wrapper class for a generically-classified failure — never the original
    exception's own class name, and never its message), so a wrong password
    never reaches a log line even indirectly."""

    @pytest.fixture(autouse=True)
    def _clear_status(self):
        set_last_cycle(None)
        yield
        set_last_cycle(None)
        set_current_license_service(None)

    def test_a_wrong_password_never_reaches_the_cycles_log_or_status(
        self, migrated_db, server: FakeFtpsServer, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        secret = "hunter2-do-not-log-me"
        set_current_license_service(_StubLicenseService(["file_upload_destination"]))
        with session_scope() as session:
            set_setting(session, FILEUPLOAD_ACTIVE_PROTOCOL_KEY, "ftps")
            set_setting(session, FILEUPLOAD_FTPS_HOST_KEY, "127.0.0.1")
            set_setting(session, FILEUPLOAD_FTPS_PORT_KEY, str(server.port))
            set_setting(session, FILEUPLOAD_FTPS_USERNAME_KEY, "arichds")
            set_setting(session, FILEUPLOAD_FTPS_PASSWORD_KEY, secret)
            set_setting(session, EXPORT_OUTPUT_DIR_KEY, str(tmp_path))

        caplog.handler.addFilter(CredentialRedactionFilter())
        with caplog.at_level(logging.DEBUG):
            file_upload_cycle()

        status = last_cycle()
        assert status is not None
        assert status.outcome == "skipped"
        assert status.error == "TransportError"
        assert secret not in caplog.text
        for record in caplog.records:
            assert secret not in record.getMessage()


class TestEndToEndThroughTheCycle:
    """No injected transport — `_build_transport` must build a real
    `FtpsTransport` for `active_protocol == "ftps"` and the file must
    actually land on the server. `test_fileupload_cycle.py` owns every
    other cycle behaviour against the in-memory transport; this is the one
    place that proves the wiring past `_build_transport` itself, mirroring
    `test_fileupload_https_transport.py`/`test_fileupload_sftp_transport.py`'s
    own `TestEndToEndThroughTheCycle`.

    `_build_transport` builds an `FtpsTransport` with no `ssl_context=` —
    production behaviour — so the fixture server's self-signed certificate
    would be refused unless trusted. `ssl.create_default_context` is
    monkeypatched *inside `ftps_transport`'s own module namespace only*
    (`_PatchedSsl` above) to answer with a pre-trusted context for the
    duration of this one test, since there is no other seam to inject a
    context through `_build_transport` (ADR 0025: no CA-file field).
    """

    @pytest.fixture(autouse=True)
    def _clear_status(self):
        set_last_cycle(None)
        yield
        set_last_cycle(None)
        set_current_license_service(None)

    def test_upload_now_style_cycle_reaches_the_real_server(
        self,
        migrated_db,
        server: FakeFtpsServer,
        ftps_root: Path,
        trusted_context: ssl.SSLContext,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(ftps_transport_module, "ssl", _PatchedSsl(trusted_context))
        set_current_license_service(_StubLicenseService(["file_upload_destination"]))
        export_dir = tmp_path / "export"
        export_dir.mkdir()
        local_file = export_dir / "SN0001.csv"
        local_file.write_bytes(b"a,b,c\n1,2,3\n")
        with session_scope() as session:
            device = Device(
                name="Meter A",
                brand="cewe",
                model="prometer100",
                site_name="Plant A",
                transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
                password="hunter2",
                meter_serial="SN0001",
            )
            session.add(device)
            set_setting(session, EXPORT_OUTPUT_DIR_KEY, str(export_dir))
            set_setting(session, FILEUPLOAD_ACTIVE_PROTOCOL_KEY, "ftps")
            set_setting(session, FILEUPLOAD_FTPS_HOST_KEY, "127.0.0.1")
            set_setting(session, FILEUPLOAD_FTPS_PORT_KEY, str(server.port))
            set_setting(session, FILEUPLOAD_FTPS_USERNAME_KEY, "arichds")
            set_setting(session, FILEUPLOAD_FTPS_PASSWORD_KEY, PASSWORD)
            set_setting(session, FILEUPLOAD_FTPS_REMOTE_ROOT_KEY, "")

        file_upload_cycle()  # no `transport=` — exercises `_build_transport` itself

        assert (ftps_root / "export" / "SN0001.csv").read_bytes() == local_file.read_bytes()
        status = last_cycle()
        assert status is not None
        assert status.outcome == "success"
        assert status.files_sent == 1


class TestClassifyExceptionUsesClassNameNotMessage:
    """A direct proof of the shared classifier's own contract
    (`TransportError`'s own docstring): whatever message the original
    exception carried never reaches `str()` on the wrapped error, matching
    `test_fileupload_sftp_transport.py`'s own equivalent assertion."""

    def test_a_message_carrying_a_password_is_discarded(self) -> None:
        import ftplib

        original = ftplib.error_perm("530 Login incorrect: password was hunter2-secret")

        _, wrapped = ftps_transport_module._classify_exception(original)

        assert str(wrapped) == "error_perm"
        assert "hunter2-secret" not in str(wrapped)
