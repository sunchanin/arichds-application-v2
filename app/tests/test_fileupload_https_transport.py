"""The HTTPS File Upload Destination transport (ADR 0025, spec.md "HTTPS
contract", ticket 03) — driven against `FakeCentralPushReceiver`'s three file
endpoints (extended for this ticket), the same "a good test drives the cycle
from the outside ... and asserts on what the server holds afterwards"
discipline spec.md's own Testing Decisions section states, and
`test_central_push_cycle.py` already follows against its own fake.
"""

from __future__ import annotations

import datetime
import socket
import ssl
import threading
from datetime import UTC
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from conftest import VENDOR_PUBLIC_KEY_PEM
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fake_central_push_receiver import FakeCentralPushReceiver

from arichds.db.app_settings import (
    EXPORT_OUTPUT_DIR_KEY,
    FILEUPLOAD_ACTIVE_PROTOCOL_KEY,
    FILEUPLOAD_HTTPS_REMOTE_ROOT_KEY,
    FILEUPLOAD_HTTPS_TOKEN_KEY,
    FILEUPLOAD_HTTPS_URL_KEY,
    set_setting,
)
from arichds.db.models import Device
from arichds.db.session import session_scope
from arichds.fileupload.cycle import file_upload_cycle
from arichds.fileupload.https_transport import HttpsTransport, check_https_connection
from arichds.fileupload.manifest import Manifest, ManifestEntry
from arichds.fileupload.status import last_cycle, set_last_cycle
from arichds.fileupload.transport import TransportError
from arichds.licensing.current import set_current_license_service
from arichds.licensing.service import LicenseState

TEST_MACHINE_ID = "a" * 64


class _StubLicenseService:
    """The same minimal stand-in `test_fileupload_cycle.py`/
    `test_central_push_cycle.py` use for the background-path licence gate."""

    def __init__(self, features: list[str] | None, *, machine_id: str = TEST_MACHINE_ID) -> None:
        self._features = features
        self.machine_id = machine_id

    def current_state(self) -> LicenseState:
        return LicenseState(state="active", reason=None, features=self._features)


@pytest.fixture
def receiver():
    r = FakeCentralPushReceiver(public_key_pem=VENDOR_PUBLIC_KEY_PEM)
    yield r
    r.shutdown()


def _closed_port(scheme: str = "http") -> str:
    """A URL naming a port nothing listens on — bind a socket, read the
    ephemeral port it got, close it, and use that port. Mirrors
    `test_central_push_cycle.py::TestFailure`'s own helper rather than a
    hardcoded low port, which is not reliably closed on every platform."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return f"{scheme}://127.0.0.1:{port}"


class TestPutFile:
    def test_the_file_arrives_byte_equal(self, receiver: FakeCentralPushReceiver, tmp_path: Path) -> None:
        local = tmp_path / "SN0001.csv"
        local.write_bytes(b"csv content\r\n1,2,3\r\n")
        transport = HttpsTransport(receiver.url, receiver.files_token)

        transport.put_file("export/SN0001.csv", local)

        assert receiver.files["export/SN0001.csv"] == local.read_bytes()

    def test_the_sha256_header_carries_the_files_own_digest(
        self, receiver: FakeCentralPushReceiver, tmp_path: Path
    ) -> None:
        import hashlib

        local = tmp_path / "SN0001.csv"
        local.write_bytes(b"some bytes")
        transport = HttpsTransport(receiver.url, receiver.files_token)

        transport.put_file("export/SN0001.csv", local)

        assert receiver.files_sha256_headers["export/SN0001.csv"] == hashlib.sha256(b"some bytes").hexdigest()

    def test_remote_root_is_folded_into_the_relative_path(
        self, receiver: FakeCentralPushReceiver, tmp_path: Path
    ) -> None:
        local = tmp_path / "SN0001.csv"
        local.write_bytes(b"x")
        transport = HttpsTransport(receiver.url, receiver.files_token, "/arichds")

        transport.put_file("export/SN0001.csv", local)

        assert "arichds/export/SN0001.csv" in receiver.files


class TestDescribe:
    """`Transport.describe()` — "the cycle itself never calls this"
    (`transport.py`'s own docstring); it is what `HttpsTransport` reports for
    Test connection instead of duplicating `check_https_connection`'s logic."""

    def test_it_matches_check_https_connections_own_message(self, receiver: FakeCentralPushReceiver) -> None:
        transport = HttpsTransport(receiver.url, receiver.files_token)

        assert transport.describe() == check_https_connection(receiver.url, receiver.files_token).message


class TestManifestRoundTrips:
    def test_a_fresh_root_reads_as_no_manifest(self, receiver: FakeCentralPushReceiver) -> None:
        transport = HttpsTransport(receiver.url, receiver.files_token)

        assert transport.read_manifest() is None

    def test_write_then_read_returns_the_same_manifest(self, receiver: FakeCentralPushReceiver) -> None:
        transport = HttpsTransport(receiver.url, receiver.files_token)
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


class TestWrongTokenIsUnauthorized:
    def test_put_file_raises_a_transport_error(self, receiver: FakeCentralPushReceiver, tmp_path: Path) -> None:
        local = tmp_path / "a.csv"
        local.write_text("x", encoding="utf-8")
        transport = HttpsTransport(receiver.url, "wrong-token")

        with pytest.raises(TransportError):
            transport.put_file("export/a.csv", local)
        assert receiver.unauthorized_requests == 1

    def test_read_manifest_raises_a_transport_error(self, receiver: FakeCentralPushReceiver) -> None:
        transport = HttpsTransport(receiver.url, "wrong-token")

        with pytest.raises(TransportError):
            transport.read_manifest()
        assert receiver.unauthorized_requests == 1

    def test_write_manifest_raises_a_transport_error(self, receiver: FakeCentralPushReceiver) -> None:
        transport = HttpsTransport(receiver.url, "wrong-token")
        manifest = Manifest(version=1, machine_id=TEST_MACHINE_ID, files={})

        with pytest.raises(TransportError):
            transport.write_manifest(manifest)
        assert receiver.unauthorized_requests == 1


class TestNonTwoXxResponse:
    def test_a_500_on_write_manifest_raises_a_transport_error_not_typeerror(
        self, receiver: FakeCentralPushReceiver
    ) -> None:
        receiver.fail_next_file_request = True
        transport = HttpsTransport(receiver.url, receiver.files_token)

        with pytest.raises(TransportError):
            transport.write_manifest(Manifest(version=1, machine_id=TEST_MACHINE_ID, files={}))


class TestUnreachableHost:
    def test_read_manifest_raises_a_transport_error_not_typeerror(self) -> None:
        transport = HttpsTransport(_closed_port(), "token", connect_timeout=2, read_timeout=2)

        with pytest.raises(TransportError):
            transport.read_manifest()


class TestTimeout:
    def test_a_stalling_receiver_raises_a_transport_error_not_typeerror(
        self, receiver: FakeCentralPushReceiver
    ) -> None:
        receiver.stall_seconds = 2.0
        transport = HttpsTransport(receiver.url, receiver.files_token, connect_timeout=5, read_timeout=0.2)

        with pytest.raises(TransportError):
            transport.read_manifest()


def _write_self_signed_cert(tmp_path: Path) -> tuple[Path, Path]:
    """A throwaway self-signed certificate for ``127.0.0.1`` — the "an
    untrusted default context fails with the transport error class, not
    TypeError" path the ticket names, since ``HttpsTransport`` never trusts
    it (there is no CA-file field, ADR 0025's own Out of Scope)."""
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


class _TlsWrappedServer:
    """A bare HTTPS server terminating TLS with a self-signed certificate —
    enough to make ``https_open`` actually run the TLS handshake, never
    reached by ``test_fileupload_config_api.py``/``test_fileupload_cycle.py``,
    which only ever speak plain ``http://`` against the in-memory/fake
    transports."""

    def __init__(self, cert_path: Path, key_path: Path) -> None:
        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                self.send_response(404)
                self.end_headers()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        self._server.socket = context.wrap_socket(self._server.socket, server_side=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        _, port = self._server.server_address
        return f"https://127.0.0.1:{port}"

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class TestHttpsBranchIsExercised:
    """Memory: *a transport branch no test reaches ships broken* — the exact
    hazard `centralpush.client`'s own `_SplitTimeoutHTTPSHandler` docstring
    names (a `check_hostname=` kwarg once made every `https://` request raise
    `TypeError` before connecting). This drives a real TLS handshake through
    `HttpsTransport`, not only `http://`."""

    def test_a_self_signed_certificate_is_refused_as_a_transport_error_not_a_typeerror(self, tmp_path: Path) -> None:
        cert_path, key_path = _write_self_signed_cert(tmp_path)
        server = _TlsWrappedServer(cert_path, key_path)
        try:
            transport = HttpsTransport(server.url, "any-token", connect_timeout=3, read_timeout=3)

            with pytest.raises(TransportError) as excinfo:
                transport.read_manifest()

            # `TransportError`'s own docstring: `str(self)` carries only the
            # failure's class name — this states that rule rather than a
            # tautological check `pytest.raises` above already made
            # (reviewer finding, ticket 03 round 1).
            assert str(excinfo.value) == "SSLCertVerificationError"
        finally:
            server.shutdown()


class TestCheckHttpsConnection:
    def test_ok_and_no_manifest(self, receiver: FakeCentralPushReceiver) -> None:
        check = check_https_connection(receiver.url, receiver.files_token)

        assert check.result == "ok"
        assert check.manifest_exists is False
        assert check.http_status == 404

    def test_ok_and_manifest_present(self, receiver: FakeCentralPushReceiver) -> None:
        transport = HttpsTransport(receiver.url, receiver.files_token)
        transport.write_manifest(Manifest(version=1, machine_id=TEST_MACHINE_ID, files={}))

        check = check_https_connection(receiver.url, receiver.files_token)

        assert check.result == "ok"
        assert check.manifest_exists is True
        assert check.http_status == 200

    def test_wrong_token_is_unauthorized(self, receiver: FakeCentralPushReceiver) -> None:
        check = check_https_connection(receiver.url, "wrong-token")

        assert check.result == "unauthorized"
        assert check.http_status == 401

    def test_a_closed_port_is_unreachable(self) -> None:
        check = check_https_connection(_closed_port(), "token", connect_timeout=2)

        # A closed loopback port is refused instantly on some networking
        # stacks (`ConnectionRefusedError`, "unreachable") and only after the
        # connect timeout on others — both are legitimately "could not
        # connect", so both are accepted here; `check_https_connection`
        # itself never lumps them into one string, so a caller can always
        # tell them apart when the platform does distinguish them.
        assert check.result in ("unreachable", "timed_out")
        assert check.http_status is None

    def test_a_stalling_receiver_is_timed_out(self, receiver: FakeCentralPushReceiver) -> None:
        receiver.stall_seconds = 2.0

        check = check_https_connection(receiver.url, receiver.files_token, connect_timeout=0.2)

        assert check.result == "timed_out"

    def test_a_blank_url_is_other_and_makes_no_request(self, receiver: FakeCentralPushReceiver) -> None:
        check = check_https_connection("", "token")

        assert check.result == "other"
        assert receiver.request_count == 0


class TestEndToEndThroughTheCycle:
    """The first end-to-end demo (ticket 03's own scope line): a cycle run
    with **no injected transport** — `_build_transport` must build a real
    `HttpsTransport` for `active_protocol == "https"` and the file must
    actually land on the server. `test_fileupload_cycle.py` owns every other
    cycle behaviour against the in-memory transport; this is the one place
    that proves the wiring past `_build_transport` itself."""

    @pytest.fixture(autouse=True)
    def _clear_status(self):
        set_last_cycle(None)
        yield
        set_last_cycle(None)
        set_current_license_service(None)

    def test_upload_now_style_cycle_reaches_the_real_server(
        self, migrated_db, receiver: FakeCentralPushReceiver, tmp_path: Path
    ) -> None:
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
            set_setting(session, FILEUPLOAD_ACTIVE_PROTOCOL_KEY, "https")
            set_setting(session, FILEUPLOAD_HTTPS_URL_KEY, receiver.url)
            set_setting(session, FILEUPLOAD_HTTPS_TOKEN_KEY, receiver.files_token)
            set_setting(session, FILEUPLOAD_HTTPS_REMOTE_ROOT_KEY, "")

        file_upload_cycle()  # no `transport=` — exercises `_build_transport` itself

        assert receiver.files.get("export/SN0001.csv") == local_file.read_bytes()
        status = last_cycle()
        assert status is not None
        assert status.outcome == "success"
        assert status.files_sent == 1
