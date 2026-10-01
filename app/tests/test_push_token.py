"""Push Token — claims shape, issuer/verifier agreement, rejections.

ADR 0024, M14 ticket 03: the vendor-side half of central-push authentication.
Mirrors ``test_meter_activation_code.py``'s pattern of driving the real
``tools/arichds_vendor.py`` through the ``vendor_cli`` fixture, and its
domain-separation tests, but for a Push Token — a real JWT rather than the
licence's one-dot custom format.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from arichds.licensing import activation_code as ac
from arichds.licensing import meter_activation_code as mac
from arichds.licensing import push_token as pt

TEST_MACHINE_ID = "c" * 64


@pytest.fixture
def vendor_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Generate a throwaway vendor keypair and make the app trust it.

    Same pattern as ``test_meter_activation_code.py``'s fixture of the same
    name: ``push_token.verify_push_token`` defaults to
    ``ac.load_public_key_pem()`` (ADR 0019 — one vendor key signs every wire
    format), so patching that one attribute is enough for every verifier.
    """
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    private_path = tmp_path / "vendor_private.pem"
    private_path.write_bytes(private_pem)
    monkeypatch.setattr(ac, "load_public_key_pem", lambda: public_pem)
    return private_path


def issue_push_token(vendor_cli, private_path: Path, *, machine_id: str, **kwargs) -> str:
    """Sign a Push Token using the real vendor CLI module's claims builder."""
    claims = vendor_cli.build_push_token_claims(machine_id=machine_id, **kwargs)
    return jwt.encode(claims, private_path.read_bytes(), algorithm=vendor_cli.PUSH_TOKEN_ALGORITHM)


class TestClaimsShape:
    def test_claims_have_exactly_four_keys(self) -> None:
        claims = pt.build_push_token_claims(machine_id=TEST_MACHINE_ID)

        assert set(claims) == {"sub", "product", "v", "iat"}

    def test_claims_literal_values(self) -> None:
        claims = pt.build_push_token_claims(machine_id=TEST_MACHINE_ID)

        assert claims["sub"] == TEST_MACHINE_ID
        assert claims["product"] == "arichds-push"
        assert claims["v"] == 1
        # Distinct from the licence's product tag — the whole point of the
        # separate claim (ADR 0024).
        assert claims["product"] != ac.PRODUCT

    def test_no_expiry_claim(self, vendor_cli, vendor_keys: Path) -> None:
        """ADR 0024: revocation is the server's denylist, never a client exp."""
        token = issue_push_token(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID)

        unverified = jwt.decode(token, options={"verify_signature": False})

        assert "exp" not in unverified

    def test_signed_with_eddsa(self, vendor_cli, vendor_keys: Path) -> None:
        token = issue_push_token(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID)

        assert jwt.get_unverified_header(token)["alg"] == "EdDSA"


class TestIssuerVerifierAgreement:
    """The duplicated claims builder must stay byte-identical on both sides."""

    def test_claims_shapes_match(self, vendor_cli) -> None:
        cli_claims = vendor_cli.build_push_token_claims(machine_id=TEST_MACHINE_ID)
        app_claims = pt.build_push_token_claims(machine_id=TEST_MACHINE_ID)

        assert set(cli_claims) == set(app_claims)
        assert cli_claims["product"] == app_claims["product"] == pt.PUSH_TOKEN_PRODUCT
        assert cli_claims["v"] == app_claims["v"] == pt.CURRENT_PUSH_TOKEN_VERSION

    def test_cli_signed_token_verifies_in_the_app(self, vendor_cli, vendor_keys: Path) -> None:
        token = issue_push_token(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID)

        result = pt.verify_push_token(token)

        assert result.valid is True
        assert result.machine_id == TEST_MACHINE_ID


class TestClockSkew:
    """``iat`` is informational only — a customer clock behind the vendor's
    must not refuse a genuine token (blocker fix, round 1)."""

    def test_iat_an_hour_in_the_future_still_verifies(self, vendor_cli, vendor_keys: Path) -> None:
        future_iat = datetime.now(UTC) + timedelta(hours=1)
        token = issue_push_token(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID, issued_at=future_iat)

        result = pt.verify_push_token(token)

        assert result.valid is True
        assert result.machine_id == TEST_MACHINE_ID


class TestRejection:
    """Each rejection path, one behaviour per test."""

    def test_bad_signature_is_invalid_signature(self, vendor_cli, vendor_keys: Path) -> None:
        token = issue_push_token(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID)
        header, payload, signature = token.split(".")
        tampered = f"{header}.{payload}.{signature[:-4]}xxxx"

        result = pt.verify_push_token(tampered)

        assert result.reason == pt.INVALID_SIGNATURE

    def test_token_signed_by_another_key_is_invalid_signature(self, vendor_cli, vendor_keys: Path) -> None:
        other_key = Ed25519PrivateKey.generate()
        other_pem = other_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        claims = vendor_cli.build_push_token_claims(machine_id=TEST_MACHINE_ID)
        token = jwt.encode(claims, other_pem, algorithm=pt.PUSH_TOKEN_ALGORITHM)

        # vendor_keys fixture already made the app trust a *different* key.
        result = pt.verify_push_token(token)

        assert result.reason == pt.INVALID_SIGNATURE

    def test_wrong_product_is_wrong_product(self, vendor_cli, vendor_keys: Path) -> None:
        claims = {"sub": TEST_MACHINE_ID, "product": "arichds", "v": 1, "iat": 0}
        token = jwt.encode(claims, vendor_keys.read_bytes(), algorithm=pt.PUSH_TOKEN_ALGORITHM)

        result = pt.verify_push_token(token)

        assert result.reason == pt.WRONG_PRODUCT

    def test_unsupported_version_is_unsupported_version(self, vendor_cli, vendor_keys: Path) -> None:
        claims = {"sub": TEST_MACHINE_ID, "product": "arichds-push", "v": 2, "iat": 0}
        token = jwt.encode(claims, vendor_keys.read_bytes(), algorithm=pt.PUSH_TOKEN_ALGORITHM)

        result = pt.verify_push_token(token)

        assert result.reason == pt.UNSUPPORTED_VERSION

    @pytest.mark.parametrize("bad_input", [None, 12345, "", "not-a-jwt", "a.b", "a.b.c.d", "x" * 10_000])
    def test_not_a_jwt_is_malformed(self, bad_input) -> None:
        result = pt.verify_push_token(bad_input)

        assert result.valid is False
        assert result.reason == pt.MALFORMED

    def test_activation_code_is_refused_by_push_verifier(self, vendor_cli, vendor_keys: Path) -> None:
        """A distinct reason from the generic ``MALFORMED`` (major fix, round 1) —
        spec story 8 wants an operator told which secret they pasted."""
        code = vendor_cli.sign_payload(
            vendor_keys.read_bytes(),
            vendor_cli.build_payload(customer="Acme Co", machine_id=TEST_MACHINE_ID),
        )

        result = pt.verify_push_token(code)

        assert result.valid is False
        assert result.reason == pt.LICENCE_CODE_NOT_PUSH_TOKEN

    def test_meter_activation_code_is_refused_by_push_verifier(self, vendor_cli, vendor_keys: Path) -> None:
        payload = vendor_cli.build_meter_payload(meter_serial="ABC123", machine_id=TEST_MACHINE_ID)
        code = vendor_cli.sign_payload(vendor_keys.read_bytes(), payload)

        result = pt.verify_push_token(code)

        assert result.valid is False
        assert result.reason == pt.LICENCE_CODE_NOT_PUSH_TOKEN


class TestDomainSeparationTheOtherWay:
    """The licence verifiers must each refuse a Push Token (ADR 0024)."""

    def test_activation_code_verifier_refuses_a_push_token(self, vendor_cli, vendor_keys: Path) -> None:
        token = issue_push_token(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID)

        result = ac.verify_activation_code(token, machine_id=TEST_MACHINE_ID)

        assert result.valid is False
        assert result.reason == ac.MALFORMED

    def test_meter_activation_code_verifier_refuses_a_push_token(self, vendor_cli, vendor_keys: Path) -> None:
        token = issue_push_token(vendor_cli, vendor_keys, machine_id=TEST_MACHINE_ID)

        result = mac.verify_meter_activation_code(token, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        assert result.valid is False
        assert result.reason == ac.MALFORMED


class TestSignPushCli:
    """Drives ``main()`` in-process, ``test_meter_activation_code.py``'s pattern.

    Every test passes an explicit ``--private-key`` into ``tmp_path`` — the
    default ``tools/.arichds_private_key.pem`` exists on this dev machine and
    is never touched by these tests.
    """

    def _keypair(self, tmp_path: Path) -> tuple[Path, bytes]:
        """Generate a throwaway keypair; return (private key path, public PEM)."""
        private_key = Ed25519PrivateKey.generate()
        private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
        path = tmp_path / "vendor_private.pem"
        path.write_bytes(private_pem)
        return path, public_pem

    def test_missing_key_returns_1_and_stdout_is_empty(self, vendor_cli, tmp_path: Path, capsys) -> None:
        missing_key = tmp_path / "does-not-exist.pem"

        exit_code = vendor_cli.main(["sign-push", "--machine-id", TEST_MACHINE_ID, "--private-key", str(missing_key)])

        assert exit_code == 1
        assert capsys.readouterr().out == ""

    def test_machine_id_not_64_hex_returns_1_and_stdout_is_empty(self, vendor_cli, tmp_path: Path, capsys) -> None:
        key_path, _ = self._keypair(tmp_path)

        exit_code = vendor_cli.main(["sign-push", "--machine-id", "not-hex", "--private-key", str(key_path)])

        assert exit_code == 1
        assert capsys.readouterr().out == ""

    def test_happy_path_prints_one_line_that_verifies(self, vendor_cli, tmp_path: Path, capsys) -> None:
        key_path, public_pem = self._keypair(tmp_path)

        exit_code = vendor_cli.main(["sign-push", "--machine-id", TEST_MACHINE_ID, "--private-key", str(key_path)])

        out = capsys.readouterr().out
        assert exit_code == 0
        lines = out.strip("\n").split("\n")
        assert len(lines) == 1
        token = lines[0]

        result = pt.verify_push_token(token, public_key_pem=public_pem)
        assert result.valid is True
        assert result.machine_id == TEST_MACHINE_ID

        # What the command itself prints, not the copied test helper (minor
        # fix, round 1): an ``exp`` added inside ``cmd_sign_push`` must turn
        # this red.
        assert "exp" not in jwt.decode(token, options={"verify_signature": False})
        assert jwt.get_unverified_header(token)["alg"] == "EdDSA"

    def test_uppercase_machine_id_is_signed_lowercased_and_still_verifies(
        self, vendor_cli, tmp_path: Path, capsys
    ) -> None:
        key_path, public_pem = self._keypair(tmp_path)

        exit_code = vendor_cli.main(
            ["sign-push", "--machine-id", TEST_MACHINE_ID.upper(), "--private-key", str(key_path)]
        )

        token = capsys.readouterr().out.strip("\n")
        assert exit_code == 0

        result = pt.verify_push_token(token, public_key_pem=public_pem)
        assert result.valid is True
        assert result.machine_id == TEST_MACHINE_ID


class TestHelpText:
    def test_sign_push_help_describes_the_command(self, vendor_cli, capsys) -> None:
        with pytest.raises(SystemExit):
            vendor_cli.main(["sign-push", "--help"])

        assert "Push Token" in capsys.readouterr().out
