"""The SFTP File Upload Destination transport (ADR 0025, spec.md "SFTP
specifics", ticket 04) — driven against `FakeSftpServer`, a real in-process
paramiko server on an ephemeral port (`docs/lib-notes/paramiko-sftp.md` §6),
the same "a good test drives the cycle from the outside ... and asserts on
what the server holds afterwards" discipline spec.md's own Testing Decisions
section states, and `test_fileupload_https_transport.py` already follows
against its own fake.
"""

from __future__ import annotations

import datetime
import logging
import socket
from datetime import UTC
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fake_sftp_server import FakeSftpServer
from paramiko import Ed25519Key

from arichds.db.app_settings import (
    EXPORT_OUTPUT_DIR_KEY,
    FILEUPLOAD_ACTIVE_PROTOCOL_KEY,
    FILEUPLOAD_SFTP_HOST_KEY,
    FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_KEY,
    FILEUPLOAD_SFTP_KEY_PASSPHRASE_KEY,
    FILEUPLOAD_SFTP_KEY_PATH_KEY,
    FILEUPLOAD_SFTP_PASSWORD_KEY,
    FILEUPLOAD_SFTP_PORT_KEY,
    FILEUPLOAD_SFTP_REMOTE_ROOT_KEY,
    FILEUPLOAD_SFTP_USERNAME_KEY,
    get_setting,
    set_setting,
)
from arichds.db.models import Device
from arichds.db.session import session_scope
from arichds.fileupload.cycle import file_upload_cycle
from arichds.fileupload.manifest import Manifest, ManifestEntry
from arichds.fileupload.sftp_transport import (
    HostKeyMismatchError,
    HostKeyNotPinnedError,
    SftpTransport,
    check_sftp_connection,
)
from arichds.fileupload.status import last_cycle, set_last_cycle
from arichds.fileupload.transport import TransportError
from arichds.licensing.current import set_current_license_service
from arichds.licensing.service import LicenseState
from arichds.logging_config import CredentialRedactionFilter

TEST_MACHINE_ID = "b" * 64
PASSWORD = "hunter2"


class _StubLicenseService:
    def __init__(self, features: list[str] | None, *, machine_id: str = TEST_MACHINE_ID) -> None:
        self._features = features
        self.machine_id = machine_id

    def current_state(self) -> LicenseState:
        return LicenseState(state="active", reason=None, features=self._features)


@pytest.fixture
def sftp_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    return root


@pytest.fixture
def server(sftp_root: Path):
    s = FakeSftpServer(sftp_root, password=PASSWORD)
    yield s
    s.shutdown()


def _closed_port() -> int:
    """A port nothing listens on — bind, read the ephemeral port, close.
    Mirrors `test_fileupload_https_transport.py::_closed_port`'s own
    helper, adapted to a bare port number (SFTP has no URL scheme)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _ed25519_key_file(tmp_path: Path) -> tuple[Ed25519Key, Path]:
    """A throwaway Ed25519 private key file on disk — `Ed25519Key` itself has
    no `generate()` classmethod (unlike `RSAKey.generate(bits)`), so this
    generates through `cryptography` and serialises to OpenSSH format, the
    shape `PKey.from_path`/`Ed25519Key.from_private_key_file` both read."""
    cryptography_key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "id_ed25519"
    key_path.write_bytes(
        cryptography_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()
        )
    )
    return Ed25519Key.from_private_key_file(str(key_path)), key_path


def _encrypted_ed25519_key_file(tmp_path: Path, passphrase: str) -> tuple[Ed25519Key, Path]:
    """Like :func:`_ed25519_key_file` but encrypted with *passphrase* —
    reviewer finding, ticket 04 round 1, problem 1: no test exercised a
    passphrase at all, which is exactly why `PKey.from_path` requiring
    `bytes` (not the `str` its own `password: str | None` annotation
    promises) shipped unnoticed. `Ed25519Key.from_private_key_file` itself
    takes `password` as `str` (paramiko decodes it internally for its own
    legacy loader) — only `PKey.from_path`, what `sftp_transport.py` calls,
    has the bytes requirement."""
    cryptography_key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "id_ed25519_encrypted"
    key_path.write_bytes(
        cryptography_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.BestAvailableEncryption(passphrase.encode("utf-8")),
        )
    )
    return Ed25519Key.from_private_key_file(str(key_path), password=passphrase), key_path


class TestPutFile:
    def test_the_file_arrives_byte_equal_with_password_auth(
        self, server: FakeSftpServer, sftp_root: Path, tmp_path: Path
    ) -> None:
        local = tmp_path / "SN0001.csv"
        local.write_bytes(b"csv content\r\n1,2,3\r\n")
        transport = SftpTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint=server.fingerprint,
        )

        transport.put_file("export/SN0001.csv", local)

        assert (sftp_root / "export" / "SN0001.csv").read_bytes() == local.read_bytes()

    def test_the_file_arrives_byte_equal_with_key_file_auth(self, sftp_root: Path, tmp_path: Path) -> None:
        key, key_path = _ed25519_key_file(tmp_path)
        s = FakeSftpServer(sftp_root, password=None, authorized_key=key)
        try:
            local = tmp_path / "SN0001.csv"
            local.write_bytes(b"key-auth content")
            transport = SftpTransport(
                host="127.0.0.1",
                port=s.port,
                username="arichds",
                password="",
                key_path=str(key_path),
                key_passphrase="",
                remote_root="",
                pinned_fingerprint=s.fingerprint,
            )

            transport.put_file("export/SN0001.csv", local)

            assert (sftp_root / "export" / "SN0001.csv").read_bytes() == local.read_bytes()
        finally:
            s.shutdown()

    def test_nested_directories_are_created_on_demand(
        self, server: FakeSftpServer, sftp_root: Path, tmp_path: Path
    ) -> None:
        local = tmp_path / "2026-09-01.pdf"
        local.write_bytes(b"%PDF-fake")
        transport = SftpTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint=server.fingerprint,
        )

        transport.put_file("captures/SN0001/2026-09-01.pdf", local)

        assert (sftp_root / "captures" / "SN0001" / "2026-09-01.pdf").read_bytes() == local.read_bytes()

    def test_remote_root_is_folded_into_the_relative_path(
        self, server: FakeSftpServer, sftp_root: Path, tmp_path: Path
    ) -> None:
        local = tmp_path / "SN0001.csv"
        local.write_bytes(b"x")
        transport = SftpTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="/arichds",
            pinned_fingerprint=server.fingerprint,
        )

        transport.put_file("export/SN0001.csv", local)

        assert (sftp_root / "arichds" / "export" / "SN0001.csv").read_bytes() == b"x"


class TestEncryptedKeyPassphrase:
    """Reviewer finding, ticket 04 round 1, problem 1 — `PKey.from_path`
    (what `_authenticate` calls to load *key_path*) requires the passphrase
    as `bytes`, despite its own `password: str | None` annotation; passing
    the configured `str` passphrase raised `TypeError` before it ever
    reached the key material, so an encrypted key — the security-recommended
    case, and the ticket's own "passphrase optional" criterion — could never
    authenticate, correct passphrase or not. No test exercised a passphrase
    at all before this round, which is why it shipped green."""

    def test_the_file_arrives_byte_equal_with_the_correct_passphrase(self, sftp_root: Path, tmp_path: Path) -> None:
        key, key_path = _encrypted_ed25519_key_file(tmp_path, "rightpass")
        s = FakeSftpServer(sftp_root, password=None, authorized_key=key)
        try:
            local = tmp_path / "SN0001.csv"
            local.write_bytes(b"encrypted-key content")
            transport = SftpTransport(
                host="127.0.0.1",
                port=s.port,
                username="arichds",
                password="",
                key_path=str(key_path),
                key_passphrase="rightpass",
                remote_root="",
                pinned_fingerprint=s.fingerprint,
            )

            transport.put_file("export/SN0001.csv", local)

            assert (sftp_root / "export" / "SN0001.csv").read_bytes() == local.read_bytes()
        finally:
            s.shutdown()

    def test_a_wrong_passphrase_raises_a_transport_error_from_the_transport(
        self, sftp_root: Path, tmp_path: Path
    ) -> None:
        key, key_path = _encrypted_ed25519_key_file(tmp_path, "rightpass")
        s = FakeSftpServer(sftp_root, password=None, authorized_key=key)
        try:
            transport = SftpTransport(
                host="127.0.0.1",
                port=s.port,
                username="arichds",
                password="",
                key_path=str(key_path),
                key_passphrase="wrongpass",
                remote_root="",
                pinned_fingerprint=s.fingerprint,
            )

            with pytest.raises(TransportError):
                transport.read_manifest()
        finally:
            s.shutdown()

    def test_a_wrong_passphrase_is_bad_credentials_on_test_connection(self, sftp_root: Path, tmp_path: Path) -> None:
        key, key_path = _encrypted_ed25519_key_file(tmp_path, "rightpass")
        s = FakeSftpServer(sftp_root, password=None, authorized_key=key)
        try:
            check = check_sftp_connection(
                host="127.0.0.1",
                port=s.port,
                username="arichds",
                password="",
                key_path=str(key_path),
                key_passphrase="wrongpass",
                remote_root="",
                pinned_fingerprint=s.fingerprint,
            )

            assert check.result == "bad_credentials"
        finally:
            s.shutdown()

    def test_a_missing_passphrase_on_an_encrypted_key_is_bad_credentials(self, sftp_root: Path, tmp_path: Path) -> None:
        key, key_path = _encrypted_ed25519_key_file(tmp_path, "rightpass")
        s = FakeSftpServer(sftp_root, password=None, authorized_key=key)
        try:
            check = check_sftp_connection(
                host="127.0.0.1",
                port=s.port,
                username="arichds",
                password="",
                key_path=str(key_path),
                key_passphrase="",
                remote_root="",
                pinned_fingerprint=s.fingerprint,
            )

            assert check.result == "bad_credentials"
        finally:
            s.shutdown()

    def test_the_passphrase_never_reaches_the_cycles_log_or_status(
        self, migrated_db, sftp_root: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The mirror of `TestSecretsNeverReachALog::test_a_wrong_password_never_reaches_the_cycles_log_or_status`
        — a *wrong* passphrase drives the cycle's real failure path end to
        end (rather than hand-building a log line), and asserts the
        passphrase itself never reaches a captured record."""
        secret = "wrong-passphrase-do-not-log-me"
        key, key_path = _encrypted_ed25519_key_file(tmp_path, "rightpass")
        s = FakeSftpServer(sftp_root, password=None, authorized_key=key)
        try:
            set_current_license_service(_StubLicenseService(["file_upload_destination"]))
            with session_scope() as session:
                set_setting(session, FILEUPLOAD_ACTIVE_PROTOCOL_KEY, "sftp")
                set_setting(session, FILEUPLOAD_SFTP_HOST_KEY, "127.0.0.1")
                set_setting(session, FILEUPLOAD_SFTP_PORT_KEY, str(s.port))
                set_setting(session, FILEUPLOAD_SFTP_USERNAME_KEY, "arichds")
                set_setting(session, FILEUPLOAD_SFTP_KEY_PATH_KEY, str(key_path))
                set_setting(session, FILEUPLOAD_SFTP_KEY_PASSPHRASE_KEY, secret)
                set_setting(session, FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_KEY, s.fingerprint)
                set_setting(session, EXPORT_OUTPUT_DIR_KEY, str(tmp_path))

            caplog.handler.addFilter(CredentialRedactionFilter())
            with caplog.at_level(logging.DEBUG):
                file_upload_cycle()

            status = last_cycle()
            assert status is not None
            assert status.outcome == "skipped"
            assert secret not in caplog.text
            for record in caplog.records:
                assert secret not in record.getMessage()
        finally:
            s.shutdown()
            set_last_cycle(None)
            set_current_license_service(None)


class TestManifestRoundTrips:
    def test_a_fresh_root_reads_as_no_manifest(self, server: FakeSftpServer) -> None:
        transport = SftpTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint=server.fingerprint,
        )

        assert transport.read_manifest() is None

    def test_write_then_read_returns_the_same_manifest(self, server: FakeSftpServer) -> None:
        transport = SftpTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint=server.fingerprint,
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


class TestDescribe:
    def test_it_matches_check_sftp_connections_own_message(self, server: FakeSftpServer) -> None:
        transport = SftpTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint=server.fingerprint,
        )

        assert (
            transport.describe()
            == check_sftp_connection(
                host="127.0.0.1",
                port=server.port,
                username="arichds",
                password=PASSWORD,
                key_path="",
                key_passphrase="",
                remote_root="",
                pinned_fingerprint=server.fingerprint,
            ).message
        )


class TestHostKeyPinning:
    """ADR 0025/ticket 04's own criterion — "a cycle never pins on its own";
    a real transport refuses outright on a missing or mismatched pin,
    **never** authenticating past that point."""

    def test_first_contact_with_no_pin_is_refused_without_authenticating(self, server: FakeSftpServer) -> None:
        # A deliberately wrong password: if this were classified as
        # `bad_credentials` it would mean authentication was attempted
        # despite no pin — the mutation this guards against.
        transport = SftpTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password="wrong-password",
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint="",
        )

        with pytest.raises(HostKeyNotPinnedError):
            transport.read_manifest()

    def test_a_changed_host_key_is_refused_without_authenticating(
        self, server: FakeSftpServer, sftp_root: Path
    ) -> None:
        other = FakeSftpServer(sftp_root, password=PASSWORD)
        try:
            transport = SftpTransport(
                host="127.0.0.1",
                port=other.port,
                username="arichds",
                password="wrong-password",
                key_path="",
                key_passphrase="",
                remote_root="",
                pinned_fingerprint=server.fingerprint,
            )

            with pytest.raises(HostKeyMismatchError):
                transport.read_manifest()
        finally:
            other.shutdown()

    def test_a_matching_pin_authenticates_normally(self, server: FakeSftpServer) -> None:
        transport = SftpTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint=server.fingerprint,
        )

        assert transport.read_manifest() is None  # no exception — reached authentication and the SFTP session

    def test_a_cycle_never_pins_on_its_own(self, migrated_db, server: FakeSftpServer, tmp_path: Path) -> None:
        """The end-to-end proof of the ticket's own header claim: a whole
        cycle run against a server with no pinned fingerprint ends
        ``skipped`` (`HostKeyNotPinnedError`) and the stored fingerprint setting
        stays empty — nothing in this module or `cycle.py` ever writes it.
        Mutation: making the cycle (or `SftpTransport._open`) pin the
        observed fingerprint on its own turns this red.
        """
        set_current_license_service(_StubLicenseService(["file_upload_destination"]))
        try:
            with session_scope() as session:
                set_setting(session, FILEUPLOAD_ACTIVE_PROTOCOL_KEY, "sftp")
                set_setting(session, FILEUPLOAD_SFTP_HOST_KEY, "127.0.0.1")
                set_setting(session, FILEUPLOAD_SFTP_PORT_KEY, str(server.port))
                set_setting(session, FILEUPLOAD_SFTP_USERNAME_KEY, "arichds")
                set_setting(session, FILEUPLOAD_SFTP_PASSWORD_KEY, PASSWORD)
                set_setting(session, EXPORT_OUTPUT_DIR_KEY, str(tmp_path))
                # No FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_KEY row written — unpinned.

            file_upload_cycle()

            status = last_cycle()
            assert status is not None
            assert status.outcome == "skipped"
            assert status.error == "HostKeyNotPinnedError"
            with session_scope() as session:
                assert get_setting(session, FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_KEY, "") == ""
        finally:
            set_last_cycle(None)
            set_current_license_service(None)


class TestWrongPasswordIsBadCredentials:
    def test_read_manifest_raises_a_transport_error_named_authenticationexception(self, server: FakeSftpServer) -> None:
        transport = SftpTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password="wrong-password",
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint=server.fingerprint,
        )

        with pytest.raises(TransportError) as excinfo:
            transport.read_manifest()
        assert str(excinfo.value) == "AuthenticationException"


class TestMissingKeyFile:
    def test_a_missing_key_file_raises_a_transport_error_not_a_bare_filenotfounderror(
        self, server: FakeSftpServer, tmp_path: Path
    ) -> None:
        missing = tmp_path / "does-not-exist"
        transport = SftpTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password="",
            key_path=str(missing),
            key_passphrase="",
            remote_root="",
            pinned_fingerprint=server.fingerprint,
        )

        with pytest.raises(TransportError) as excinfo:
            transport.read_manifest()
        assert str(excinfo.value) == "FileNotFoundError"


class TestUnreachableHost:
    def test_read_manifest_raises_a_transport_error_not_typeerror(self) -> None:
        transport = SftpTransport(
            host="127.0.0.1",
            port=_closed_port(),
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint="",
            connect_timeout=2,
            read_timeout=2,
        )

        with pytest.raises(TransportError):
            transport.read_manifest()


class TestCheckSftpConnection:
    def test_ok_and_no_manifest(self, server: FakeSftpServer) -> None:
        check = check_sftp_connection(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint=server.fingerprint,
        )

        assert check.result == "ok"
        assert check.manifest_exists is False
        assert check.fingerprint == server.fingerprint

    def test_ok_and_manifest_present(self, server: FakeSftpServer) -> None:
        transport = SftpTransport(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint=server.fingerprint,
        )
        transport.write_manifest(Manifest(version=1, machine_id=TEST_MACHINE_ID, files={}))

        check = check_sftp_connection(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint=server.fingerprint,
        )

        assert check.result == "ok"
        assert check.manifest_exists is True

    def test_first_contact_is_host_key_not_pinned(self, server: FakeSftpServer) -> None:
        check = check_sftp_connection(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint="",
        )

        assert check.result == "host_key_not_pinned"
        assert check.fingerprint == server.fingerprint

    def test_a_changed_host_key_is_host_key_mismatch(self, server: FakeSftpServer, sftp_root: Path) -> None:
        """Mutation: dropping the fingerprint compare in
        `check_sftp_connection` (or `SftpTransport._open`) turns this red —
        the one named mutation ticket 04's own delegation prompt calls out."""
        other = FakeSftpServer(sftp_root, password=PASSWORD)
        try:
            check = check_sftp_connection(
                host="127.0.0.1",
                port=other.port,
                username="arichds",
                password=PASSWORD,
                key_path="",
                key_passphrase="",
                remote_root="",
                pinned_fingerprint=server.fingerprint,
            )

            assert check.result == "host_key_mismatch"
            assert check.fingerprint == other.fingerprint
        finally:
            other.shutdown()

    def test_wrong_password_is_bad_credentials(self, server: FakeSftpServer) -> None:
        check = check_sftp_connection(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password="wrong-password",
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint=server.fingerprint,
        )

        assert check.result == "bad_credentials"

    def test_a_missing_key_file_is_missing_key_file(self, server: FakeSftpServer, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        check = check_sftp_connection(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password="",
            key_path=str(missing),
            key_passphrase="",
            remote_root="",
            pinned_fingerprint=server.fingerprint,
        )

        assert check.result == "missing_key_file"

    def test_a_closed_port_is_unreachable_or_timed_out(self) -> None:
        check = check_sftp_connection(
            host="127.0.0.1",
            port=_closed_port(),
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint="",
            connect_timeout=2,
        )

        assert check.result in ("unreachable", "timed_out")
        assert check.fingerprint is None

    def test_a_blank_host_is_other_and_makes_no_request(self) -> None:
        check = check_sftp_connection(
            host="",
            port=22,
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint="",
        )

        assert check.result == "other"
        assert check.fingerprint is None

    def test_an_unset_remote_root_that_does_not_exist_yet_still_reports_ok(self, server: FakeSftpServer) -> None:
        """ADR 0025 decision 4 — "directories are created on demand" — Test
        connection must not fail just because the operator has not created
        the remote root folder yet, but the message still names it
        (reviewer finding, ticket 04 round 1, problem 6) rather than reading
        as if the root were confirmed present."""
        check = check_sftp_connection(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="/not-created-yet",
            pinned_fingerprint=server.fingerprint,
        )

        assert check.result == "ok"
        assert "does not exist yet" in check.message

    def test_an_existing_remote_root_gets_no_does_not_exist_clause(self, server: FakeSftpServer) -> None:
        check = check_sftp_connection(
            host="127.0.0.1",
            port=server.port,
            username="arichds",
            password=PASSWORD,
            key_path="",
            key_passphrase="",
            remote_root="",
            pinned_fingerprint=server.fingerprint,
        )

        assert check.result == "ok"
        assert "does not exist yet" not in check.message


class TestSecretsNeverReachALog:
    """Mirrors `test_fileupload_https_transport.py`'s own credential-safety
    proof but for the cycle's own logging: `cycle.py` logs only
    `type(exc).__name__` (never `str(exc)`), and every `TransportError` this
    module raises is itself class-name-only — so a wrong password never
    reaches a log line even indirectly."""

    @pytest.fixture(autouse=True)
    def _clear_status(self):
        set_last_cycle(None)
        yield
        set_last_cycle(None)
        set_current_license_service(None)

    def test_a_wrong_password_never_reaches_the_cycles_log_or_status(
        self, migrated_db, server: FakeSftpServer, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        secret = "hunter2-do-not-log-me"
        set_current_license_service(_StubLicenseService(["file_upload_destination"]))
        with session_scope() as session:
            set_setting(session, FILEUPLOAD_ACTIVE_PROTOCOL_KEY, "sftp")
            set_setting(session, FILEUPLOAD_SFTP_HOST_KEY, "127.0.0.1")
            set_setting(session, FILEUPLOAD_SFTP_PORT_KEY, str(server.port))
            set_setting(session, FILEUPLOAD_SFTP_USERNAME_KEY, "arichds")
            set_setting(session, FILEUPLOAD_SFTP_PASSWORD_KEY, secret)
            set_setting(session, FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_KEY, server.fingerprint)
            set_setting(session, EXPORT_OUTPUT_DIR_KEY, str(tmp_path))

        caplog.handler.addFilter(CredentialRedactionFilter())
        with caplog.at_level(logging.DEBUG):
            file_upload_cycle()

        status = last_cycle()
        assert status is not None
        assert status.outcome == "skipped"
        # `type(exc).__name__` is always the bare `TransportError` wrapper
        # class for a generically-classified failure — `test_fileupload_cycle.py`'s
        # own precedent (`status.error == "TransportError"`); only the two
        # host-key exceptions get their own distinct class name reported.
        assert status.error == "TransportError"
        assert secret not in caplog.text
        for record in caplog.records:
            assert secret not in record.getMessage()


class TestEndToEndThroughTheCycle:
    """No injected transport — `_build_transport` must build a real
    `SftpTransport` for `active_protocol == "sftp"` and the file must
    actually land on the server. `test_fileupload_cycle.py` owns every
    other cycle behaviour against the in-memory transport; this is the one
    place that proves the wiring past `_build_transport` itself, mirroring
    `test_fileupload_https_transport.py::TestEndToEndThroughTheCycle`."""

    @pytest.fixture(autouse=True)
    def _clear_status(self):
        set_last_cycle(None)
        yield
        set_last_cycle(None)
        set_current_license_service(None)

    def test_upload_now_style_cycle_reaches_the_real_server(
        self, migrated_db, server: FakeSftpServer, sftp_root: Path, tmp_path: Path
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
            set_setting(session, FILEUPLOAD_ACTIVE_PROTOCOL_KEY, "sftp")
            set_setting(session, FILEUPLOAD_SFTP_HOST_KEY, "127.0.0.1")
            set_setting(session, FILEUPLOAD_SFTP_PORT_KEY, str(server.port))
            set_setting(session, FILEUPLOAD_SFTP_USERNAME_KEY, "arichds")
            set_setting(session, FILEUPLOAD_SFTP_PASSWORD_KEY, PASSWORD)
            set_setting(session, FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_KEY, server.fingerprint)
            set_setting(session, FILEUPLOAD_SFTP_REMOTE_ROOT_KEY, "")

        file_upload_cycle()  # no `transport=` — exercises `_build_transport` itself

        assert (sftp_root / "export" / "SN0001.csv").read_bytes() == local_file.read_bytes()
        status = last_cycle()
        assert status is not None
        assert status.outcome == "success"
        assert status.files_sent == 1


class TestClassifyExceptionUsesClassNameNotMessage:
    """A direct proof of the shared classifier's own contract
    (`TransportError`'s own docstring): whatever message the original
    exception carried never reaches `str()` on the wrapped error, matching
    `test_fileupload_https_transport.py`'s own `TestHttpsBranchIsExercised`
    assertion shape."""

    def test_a_message_carrying_a_password_is_discarded(self) -> None:
        from arichds.fileupload.sftp_transport import _classify_exception

        exc = Exception("wrong password: hunter2-should-not-leak")
        _, error = _classify_exception(exc)

        assert str(error) == "Exception"
        assert "hunter2" not in str(error)
