"""Meter Activation Code — payload shape, issuer/verifier agreement, rejections.

ADR 0019 / issue #41: the vendor-side half of per-meter licensing. Mirrors
``test_license_roundtrip.py``'s pattern of driving the real
``tools/arichds_vendor.py`` through the ``vendor_cli`` fixture, so the
duplicated canonical-payload rule is what actually gets exercised.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

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

TEST_MACHINE_ID = "c" * 64
OTHER_MACHINE_ID = "d" * 64


@pytest.fixture
def vendor_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Generate a throwaway vendor keypair and make the app trust it.

    Same pattern as ``test_license_roundtrip.py``'s fixture of the same name
    — kept local rather than shared, since each module patches a different
    verifier's ``load_public_key_pem``.
    """
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    private_path = tmp_path / "vendor_private.pem"
    private_path.write_bytes(private_pem)
    monkeypatch.setattr(ac, "load_public_key_pem", lambda: public_pem)
    return private_path


def issue_meter_code(vendor_cli, private_path: Path, *, meter_serial: str, machine_id: str, **kwargs) -> str:
    """Sign a Meter Activation Code using the real vendor CLI module."""
    payload = vendor_cli.build_meter_payload(meter_serial=meter_serial, machine_id=machine_id, **kwargs)
    return vendor_cli.sign_payload(private_path.read_bytes(), payload)


class TestPayloadShape:
    def test_payload_has_exactly_six_keys(self) -> None:
        payload = mac.build_meter_payload(meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        assert set(payload) == {"v", "product", "type", "meter_serial", "machine_id", "issued_at"}

    def test_payload_literal_values(self) -> None:
        payload = mac.build_meter_payload(meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        assert payload["v"] == 1
        assert payload["product"] == "arichds"
        assert payload["type"] == "meter"

    def test_issued_at_is_utc_iso8601_and_naive_treated_as_utc(self) -> None:
        naive = datetime(2026, 8, 24, 12, 0, 0)  # noqa: DTZ001 — deliberately naive input

        payload = mac.build_meter_payload(meter_serial="ABC123", machine_id=TEST_MACHINE_ID, issued_at=naive)

        parsed = datetime.fromisoformat(payload["issued_at"])
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)
        assert parsed.replace(tzinfo=None) == naive


class TestIssuerVerifierAgreement:
    """The duplicated payload builder must stay byte-identical on both sides."""

    def test_payload_shapes_match(self, vendor_cli) -> None:
        cli = vendor_cli.build_meter_payload(meter_serial="ABC123", machine_id=TEST_MACHINE_ID)
        app_side = mac.build_meter_payload(meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        assert set(cli) == set(app_side)
        assert cli["v"] == app_side["v"] == mac.METER_PAYLOAD_VERSION
        assert cli["product"] == app_side["product"] == ac.PRODUCT
        assert cli["type"] == app_side["type"] == mac.METER_TYPE

    def test_cli_signed_code_verifies_in_the_app(self, vendor_cli, vendor_keys: Path) -> None:
        code = issue_meter_code(vendor_cli, vendor_keys, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        result = mac.verify_meter_activation_code(code, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        assert result.valid is True
        assert result.meter_serial == "ABC123"
        assert result.machine_id == TEST_MACHINE_ID


class TestRejection:
    """Each rejection path, one behaviour per test (D5's check order)."""

    def test_tampered_serial_is_invalid_signature(self, vendor_cli, vendor_keys: Path) -> None:
        """Tamper the payload that was actually signed, not a freshly-rebuilt one.

        A rebuilt payload carries a new ``issued_at`` timestamp, which alone
        makes the canonical bytes differ — that would make the signature check
        fail regardless of which field is "tampered", so the test would not
        actually be exercising tamper detection on ``meter_serial``.
        """
        code = issue_meter_code(vendor_cli, vendor_keys, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)
        payload_b64, signature_b64 = code.split(".")
        payload = json.loads(ac._b64url_decode(payload_b64))
        payload["meter_serial"] = "TAMPERED"
        tampered = ac.encode_activation_code(payload, ac._b64url_decode(signature_b64))

        result = mac.verify_meter_activation_code(tampered, meter_serial="TAMPERED", machine_id=TEST_MACHINE_ID)

        assert result.reason == ac.INVALID_SIGNATURE

    def test_tampered_machine_id_is_invalid_signature(self, vendor_cli, vendor_keys: Path) -> None:
        """Same technique as above — tamper the signed payload, not a rebuild."""
        code = issue_meter_code(vendor_cli, vendor_keys, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)
        payload_b64, signature_b64 = code.split(".")
        payload = json.loads(ac._b64url_decode(payload_b64))
        payload["machine_id"] = OTHER_MACHINE_ID
        tampered = ac.encode_activation_code(payload, ac._b64url_decode(signature_b64))

        result = mac.verify_meter_activation_code(tampered, meter_serial="ABC123", machine_id=OTHER_MACHINE_ID)

        assert result.reason == ac.INVALID_SIGNATURE

    def test_signed_by_a_different_key_is_invalid_signature(self, vendor_cli, tmp_path: Path) -> None:
        wrong_key = Ed25519PrivateKey.generate()
        wrong_pem = wrong_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        wrong_path = tmp_path / "wrong.pem"
        wrong_path.write_bytes(wrong_pem)
        code = issue_meter_code(vendor_cli, wrong_path, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        result = mac.verify_meter_activation_code(code, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        assert result.reason == ac.INVALID_SIGNATURE

    def test_wrong_type_is_wrong_product(self, vendor_cli, vendor_keys: Path) -> None:
        """Pins the ``type`` half of D3's discriminator (:178-183), signed *after* mutation.

        Signing the mutated payload — rather than tampering post-signature —
        is what makes this reach the product/type/v check instead of dying at
        the signature check first: the code is authentic, just for the wrong type.
        """
        payload = mac.build_meter_payload(meter_serial="ABC123", machine_id=TEST_MACHINE_ID)
        payload["type"] = "machine"
        code = vendor_cli.sign_payload(vendor_keys.read_bytes(), payload)

        result = mac.verify_meter_activation_code(code, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        assert result.reason == ac.WRONG_PRODUCT

    def test_wrong_version_is_wrong_product(self, vendor_cli, vendor_keys: Path) -> None:
        """Pins the ``v`` half of D3's discriminator (:178-183), same technique."""
        payload = mac.build_meter_payload(meter_serial="ABC123", machine_id=TEST_MACHINE_ID)
        payload["v"] = 2
        code = vendor_cli.sign_payload(vendor_keys.read_bytes(), payload)

        result = mac.verify_meter_activation_code(code, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        assert result.reason == ac.WRONG_PRODUCT

    def test_authentic_code_for_a_different_serial_is_wrong_meter(self, vendor_cli, vendor_keys: Path) -> None:
        code = issue_meter_code(vendor_cli, vendor_keys, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        result = mac.verify_meter_activation_code(code, meter_serial="OTHER-SERIAL", machine_id=TEST_MACHINE_ID)

        assert result.reason == mac.WRONG_METER

    def test_authentic_code_for_a_different_machine_is_wrong_machine(self, vendor_cli, vendor_keys: Path) -> None:
        code = issue_meter_code(vendor_cli, vendor_keys, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        result = mac.verify_meter_activation_code(code, meter_serial="ABC123", machine_id=OTHER_MACHINE_ID)

        assert result.reason == ac.WRONG_MACHINE

    def test_wrong_on_both_reports_wrong_machine(self, vendor_cli, vendor_keys: Path) -> None:
        """Pins D5's order: machine binding is checked before serial binding."""
        code = issue_meter_code(vendor_cli, vendor_keys, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        result = mac.verify_meter_activation_code(code, meter_serial="OTHER-SERIAL", machine_id=OTHER_MACHINE_ID)

        assert result.reason == ac.WRONG_MACHINE

    def test_truncated_code_is_malformed(self, vendor_cli, vendor_keys: Path) -> None:
        code = issue_meter_code(vendor_cli, vendor_keys, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        result = mac.verify_meter_activation_code(code[:10], meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        assert result.reason == ac.MALFORMED

    @pytest.mark.parametrize(
        "bad_code",
        [
            "no-dot-here",
            "one.two.three",
            ".signature",
            "payload.",
            "not-base64url!!!.also-not!!!",
        ],
    )
    def test_malformed_shapes(self, bad_code: str) -> None:
        result = mac.verify_meter_activation_code(bad_code, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        assert result.reason == ac.MALFORMED

    def test_valid_base64_that_is_not_json_is_malformed(self) -> None:
        import base64

        payload_b64 = base64.urlsafe_b64encode(b"not json at all").decode("ascii").rstrip("=")
        sig_b64 = base64.urlsafe_b64encode(b"sig").decode("ascii").rstrip("=")

        result = mac.verify_meter_activation_code(
            f"{payload_b64}.{sig_b64}", meter_serial="ABC123", machine_id=TEST_MACHINE_ID
        )

        assert result.reason == ac.MALFORMED

    def test_json_that_is_not_a_dict_is_malformed(self) -> None:
        import base64

        payload_b64 = base64.urlsafe_b64encode(b"[1,2,3]").decode("ascii").rstrip("=")
        sig_b64 = base64.urlsafe_b64encode(b"sig").decode("ascii").rstrip("=")

        result = mac.verify_meter_activation_code(
            f"{payload_b64}.{sig_b64}", meter_serial="ABC123", machine_id=TEST_MACHINE_ID
        )

        assert result.reason == ac.MALFORMED

    def test_dict_missing_a_required_key_is_malformed(self) -> None:
        import base64
        import json as jsonlib

        payload = mac.build_meter_payload(meter_serial="ABC123", machine_id=TEST_MACHINE_ID)
        del payload["type"]
        payload_bytes = jsonlib.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
        sig_b64 = base64.urlsafe_b64encode(b"x" * 64).decode("ascii").rstrip("=")

        result = mac.verify_meter_activation_code(
            f"{payload_b64}.{sig_b64}", meter_serial="ABC123", machine_id=TEST_MACHINE_ID
        )

        assert result.reason == ac.MALFORMED

    def test_meter_serial_not_a_string_is_malformed(self) -> None:
        import base64
        import json as jsonlib

        payload = mac.build_meter_payload(meter_serial="ABC123", machine_id=TEST_MACHINE_ID)
        payload["meter_serial"] = 12345
        payload_bytes = jsonlib.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
        sig_b64 = base64.urlsafe_b64encode(b"x" * 64).decode("ascii").rstrip("=")

        result = mac.verify_meter_activation_code(
            f"{payload_b64}.{sig_b64}", meter_serial="ABC123", machine_id=TEST_MACHINE_ID
        )

        assert result.reason == ac.MALFORMED

    @pytest.mark.parametrize("bad_input", [None, 12345, "", "...", "x" * 10_000])
    def test_verifier_never_raises(self, bad_input) -> None:
        result = mac.verify_meter_activation_code(bad_input, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        assert result.valid is False


class TestCrossFormatSubstitution:
    """D3's ``type`` discriminator — both signed with the same valid key."""

    def test_machine_code_does_not_verify_as_meter_code(self, vendor_cli, vendor_keys: Path) -> None:
        code = vendor_cli.sign_payload(
            vendor_keys.read_bytes(),
            vendor_cli.build_payload(customer="Acme Co", machine_id=TEST_MACHINE_ID),
        )

        result = mac.verify_meter_activation_code(code, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        assert result.valid is False

    def test_meter_code_does_not_verify_as_machine_code(self, vendor_cli, vendor_keys: Path) -> None:
        code = issue_meter_code(vendor_cli, vendor_keys, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        result = ac.verify_activation_code(code, machine_id=TEST_MACHINE_ID)

        assert result.valid is False


class TestSerialNormalization:
    """D4 — ``.strip()`` both sides, then compare case-sensitively."""

    def test_padded_serial_verifies_against_trimmed(self, vendor_cli, vendor_keys: Path) -> None:
        code = issue_meter_code(vendor_cli, vendor_keys, meter_serial="  ABC123  ", machine_id=TEST_MACHINE_ID)

        result = mac.verify_meter_activation_code(code, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        assert result.valid is True

    def test_case_mismatch_does_not_verify(self, vendor_cli, vendor_keys: Path) -> None:
        code = issue_meter_code(vendor_cli, vendor_keys, meter_serial="abc123", machine_id=TEST_MACHINE_ID)

        result = mac.verify_meter_activation_code(code, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        assert result.reason == mac.WRONG_METER


class TestFailurePopulatesResult:
    def test_wrong_machine_result_still_exposes_the_bound_machine_id(self, vendor_cli, vendor_keys: Path) -> None:
        code = issue_meter_code(vendor_cli, vendor_keys, meter_serial="ABC123", machine_id=TEST_MACHINE_ID)

        result = mac.verify_meter_activation_code(code, meter_serial="ABC123", machine_id=OTHER_MACHINE_ID)

        assert result.reason == ac.WRONG_MACHINE
        assert result.machine_id == TEST_MACHINE_ID


class TestSignMeterCli:
    """Drives ``main()`` in-process, the ``test_probe_meter_script.py:80`` pattern.

    Every test passes an explicit ``--private-key`` into ``tmp_path`` — the
    default ``tools/.arichds_private_key.pem`` exists on this dev machine and
    is never touched by these tests.
    """

    def test_missing_key_returns_1_and_stdout_is_empty(self, vendor_cli, tmp_path: Path, capsys) -> None:
        missing_key = tmp_path / "does-not-exist.pem"

        exit_code = vendor_cli.main(
            [
                "sign-meter",
                "--meter-serial",
                "ABC123",
                "--machine-id",
                TEST_MACHINE_ID,
                "--private-key",
                str(missing_key),
            ]
        )

        assert exit_code == 1
        assert capsys.readouterr().out == ""

    def _keypath(self, vendor_cli, tmp_path: Path) -> Path:
        return self._keypair(tmp_path)[0]

    def _keypair(self, tmp_path: Path) -> tuple[Path, bytes]:
        """Generate a throwaway keypair; return (private key path, public PEM)."""
        private_key = Ed25519PrivateKey.generate()
        private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
        path = tmp_path / "vendor_private.pem"
        path.write_bytes(private_pem)
        return path, public_pem

    def test_empty_serial_returns_1_and_stdout_is_empty(self, vendor_cli, tmp_path: Path, capsys) -> None:
        key_path = self._keypath(vendor_cli, tmp_path)

        exit_code = vendor_cli.main(
            [
                "sign-meter",
                "--meter-serial",
                "   ",
                "--machine-id",
                TEST_MACHINE_ID,
                "--private-key",
                str(key_path),
            ]
        )

        assert exit_code == 1
        assert capsys.readouterr().out == ""

    def test_serial_of_65_chars_returns_1_and_stdout_is_empty(self, vendor_cli, tmp_path: Path, capsys) -> None:
        key_path = self._keypath(vendor_cli, tmp_path)

        exit_code = vendor_cli.main(
            [
                "sign-meter",
                "--meter-serial",
                "S" * 65,
                "--machine-id",
                TEST_MACHINE_ID,
                "--private-key",
                str(key_path),
            ]
        )

        assert exit_code == 1
        assert capsys.readouterr().out == ""

    def test_serial_of_64_chars_succeeds(self, vendor_cli, tmp_path: Path, capsys) -> None:
        key_path = self._keypath(vendor_cli, tmp_path)

        exit_code = vendor_cli.main(
            [
                "sign-meter",
                "--meter-serial",
                "S" * 64,
                "--machine-id",
                TEST_MACHINE_ID,
                "--private-key",
                str(key_path),
            ]
        )

        assert exit_code == 0
        assert capsys.readouterr().out.strip() != ""

    def test_machine_id_not_64_hex_returns_1_and_stdout_is_empty(self, vendor_cli, tmp_path: Path, capsys) -> None:
        key_path = self._keypath(vendor_cli, tmp_path)

        exit_code = vendor_cli.main(
            [
                "sign-meter",
                "--meter-serial",
                "ABC123",
                "--machine-id",
                "not-hex",
                "--private-key",
                str(key_path),
            ]
        )

        assert exit_code == 1
        assert capsys.readouterr().out == ""

    def test_happy_path_prints_one_line_that_verifies(self, vendor_cli, tmp_path: Path, capsys) -> None:
        key_path, public_pem = self._keypair(tmp_path)

        exit_code = vendor_cli.main(
            [
                "sign-meter",
                "--meter-serial",
                "ABC123",
                "--machine-id",
                TEST_MACHINE_ID,
                "--private-key",
                str(key_path),
            ]
        )

        out = capsys.readouterr().out
        assert exit_code == 0
        lines = out.strip("\n").split("\n")
        assert len(lines) == 1
        code = lines[0]

        result = mac.verify_meter_activation_code(
            code, meter_serial="ABC123", machine_id=TEST_MACHINE_ID, public_key_pem=public_pem
        )
        assert result.valid is True

    def test_uppercase_machine_id_is_signed_lowercased_and_still_verifies(
        self, vendor_cli, tmp_path: Path, capsys
    ) -> None:
        """Pins ``.lower()`` on the Machine ID (D11's reuse of ``:183-187``'s shape).

        The verifier compares ``machine_id`` case-sensitively (there is no
        ``.lower()`` in ``verify_meter_activation_code``, unlike the serial's
        ``.strip()``) and Machine IDs are always lowercase hex in practice
        (``hashlib.hexdigest()`` never uppercases). Without normalizing the
        CLI input, an operator pasting an uppercased Machine ID would sign a
        code that can never verify against the machine it names.
        """
        key_path, public_pem = self._keypair(tmp_path)

        exit_code = vendor_cli.main(
            [
                "sign-meter",
                "--meter-serial",
                "ABC123",
                "--machine-id",
                TEST_MACHINE_ID.upper(),
                "--private-key",
                str(key_path),
            ]
        )

        code = capsys.readouterr().out.strip("\n")
        assert exit_code == 0

        result = mac.verify_meter_activation_code(
            code, meter_serial="ABC123", machine_id=TEST_MACHINE_ID, public_key_pem=public_pem
        )
        assert result.valid is True

    def test_out_flag_writes_the_code_to_a_file(self, vendor_cli, tmp_path: Path, capsys) -> None:
        """Pins ``--out`` (D11), which had no test — deleting it left 37/37 green."""
        key_path, public_pem = self._keypair(tmp_path)
        out_path = tmp_path / "issued-code.txt"

        exit_code = vendor_cli.main(
            [
                "sign-meter",
                "--meter-serial",
                "ABC123",
                "--machine-id",
                TEST_MACHINE_ID,
                "--private-key",
                str(key_path),
                "--out",
                str(out_path),
            ]
        )

        stdout_code = capsys.readouterr().out.strip("\n")
        assert exit_code == 0
        assert out_path.read_text(encoding="utf-8") == stdout_code

        result = mac.verify_meter_activation_code(
            out_path.read_text(encoding="utf-8"),
            meter_serial="ABC123",
            machine_id=TEST_MACHINE_ID,
            public_key_pem=public_pem,
        )
        assert result.valid is True
