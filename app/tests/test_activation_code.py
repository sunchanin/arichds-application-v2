"""Activation Code format + Ed25519 verification.

Format (SPEC §3.9, frozen with the fingerprint):

    base64url(canonical_payload_json) + "." + base64url(signature)

Canonical payload = JSON with sorted keys and compact separators. The issuer
(``tools/arichds_vendor.py``) and this verifier must produce byte-identical
bytes or nothing verifies.

Invalid input is a *value*, not an exception: every failure path returns a
result with ``valid=False`` and a reason code.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from arichds.licensing.activation_code import (
    EXPIRED,
    INVALID_SIGNATURE,
    MALFORMED,
    WRONG_MACHINE,
    WRONG_PRODUCT,
    build_payload,
    canonical_payload_bytes,
    encode_activation_code,
    verify_activation_code,
)

MACHINE_ID = "a" * 64
OTHER_MACHINE_ID = "b" * 64


@pytest.fixture
def keypair() -> tuple[Ed25519PrivateKey, bytes]:
    """A throwaway vendor signing keypair (private key, public key PEM)."""
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return private_key, public_pem


def sign_code(private_key: Ed25519PrivateKey, payload: dict) -> str:
    """Issue an Activation Code for *payload* the way the vendor CLI does."""
    signature = private_key.sign(canonical_payload_bytes(payload))
    return encode_activation_code(payload, signature)


class TestCanonicalBytes:
    """The signature agreement — must be deterministic and compact."""

    def test_keys_are_sorted_and_separators_compact(self) -> None:
        payload = {"b": 2, "a": 1}
        assert canonical_payload_bytes(payload) == b'{"a":1,"b":2}'

    def test_is_stable_regardless_of_insertion_order(self) -> None:
        assert canonical_payload_bytes({"x": 1, "y": 2}) == canonical_payload_bytes({"y": 2, "x": 1})


class TestBuildPayload:
    """`build_payload` produces the v2 payload shape (SPEC §3.9)."""

    def test_has_the_frozen_field_set(self) -> None:
        payload = build_payload(customer="Acme", machine_id=MACHINE_ID)
        assert set(payload) == {
            "v",
            "product",
            "customer",
            "machine_id",
            "mode",
            "issued_at",
            "expires_at",
            "max_meters",
            "features",
        }

    def test_defaults_to_offline_mode_version_2_arichds(self) -> None:
        payload = build_payload(customer="Acme", machine_id=MACHINE_ID)
        assert payload["v"] == 2
        assert payload["product"] == "arichds"
        assert payload["mode"] == "offline"

    def test_optional_fields_default_to_null(self) -> None:
        payload = build_payload(customer="Acme", machine_id=MACHINE_ID)
        assert payload["expires_at"] is None
        assert payload["max_meters"] is None
        assert payload["features"] is None


class TestVerifyActivationCode:
    def test_valid_code_activates(self, keypair) -> None:
        private_key, public_pem = keypair
        code = sign_code(private_key, build_payload(customer="Acme", machine_id=MACHINE_ID))

        result = verify_activation_code(code, machine_id=MACHINE_ID, public_key_pem=public_pem)

        assert result.valid
        assert result.reason is None
        assert result.customer == "Acme"
        assert result.mode == "offline"

    def test_code_for_another_machine_is_rejected(self, keypair) -> None:
        private_key, public_pem = keypair
        code = sign_code(private_key, build_payload(customer="Acme", machine_id=OTHER_MACHINE_ID))

        result = verify_activation_code(code, machine_id=MACHINE_ID, public_key_pem=public_pem)

        assert not result.valid
        assert result.reason == WRONG_MACHINE

    def test_tampered_payload_is_rejected(self, keypair) -> None:
        private_key, public_pem = keypair
        payload = build_payload(customer="Acme", machine_id=MACHINE_ID)
        signature = private_key.sign(canonical_payload_bytes(payload))
        # Re-issue the code with the *same* signature over a different payload.
        payload["customer"] = "Attacker"
        tampered = encode_activation_code(payload, signature)

        result = verify_activation_code(tampered, machine_id=MACHINE_ID, public_key_pem=public_pem)

        assert not result.valid
        assert result.reason == INVALID_SIGNATURE

    def test_code_signed_by_a_different_key_is_rejected(self, keypair) -> None:
        _, public_pem = keypair
        attacker_key = Ed25519PrivateKey.generate()
        code = sign_code(attacker_key, build_payload(customer="Acme", machine_id=MACHINE_ID))

        result = verify_activation_code(code, machine_id=MACHINE_ID, public_key_pem=public_pem)

        assert not result.valid
        assert result.reason == INVALID_SIGNATURE

    def test_expired_code_reports_expired_not_bad_signature(self, keypair) -> None:
        """Signature is checked BEFORE expiry, so an authentic old code says EXPIRED."""
        private_key, public_pem = keypair
        yesterday = datetime.now(UTC) - timedelta(days=1)
        payload = build_payload(customer="Acme", machine_id=MACHINE_ID, expires_at=yesterday)
        code = sign_code(private_key, payload)

        result = verify_activation_code(code, machine_id=MACHINE_ID, public_key_pem=public_pem)

        assert not result.valid
        assert result.reason == EXPIRED

    def test_unexpired_lease_is_valid(self, keypair) -> None:
        private_key, public_pem = keypair
        payload = build_payload(
            customer="Acme",
            machine_id=MACHINE_ID,
            mode="leased",
            expires_at=datetime.now(UTC) + timedelta(days=45),
        )
        code = sign_code(private_key, payload)

        result = verify_activation_code(code, machine_id=MACHINE_ID, public_key_pem=public_pem)

        assert result.valid
        assert result.mode == "leased"

    def test_wrong_product_is_rejected(self, keypair) -> None:
        private_key, public_pem = keypair
        payload = build_payload(customer="Acme", machine_id=MACHINE_ID)
        payload["product"] = "cewe"
        code = sign_code(private_key, payload)

        result = verify_activation_code(code, machine_id=MACHINE_ID, public_key_pem=public_pem)

        assert not result.valid
        assert result.reason == WRONG_PRODUCT

    def test_unknown_payload_version_is_rejected(self, keypair) -> None:
        private_key, public_pem = keypair
        payload = build_payload(customer="Acme", machine_id=MACHINE_ID)
        payload["v"] = 99
        code = sign_code(private_key, payload)

        result = verify_activation_code(code, machine_id=MACHINE_ID, public_key_pem=public_pem)

        assert not result.valid
        assert result.reason == WRONG_PRODUCT

    @pytest.mark.parametrize(
        "code",
        [
            "",
            "   ",
            "no-dot-separator",
            "too.many.dots",
            "!!!not-base64!!!.abc",
            base64.urlsafe_b64encode(b"not json").decode() + ".YWJj",
            base64.urlsafe_b64encode(b'["json but not an object"]').decode() + ".YWJj",
            base64.urlsafe_b64encode(b'{"missing":"fields"}').decode() + ".YWJj",
        ],
    )
    def test_malformed_input_is_a_value_not_an_exception(self, code: str, keypair) -> None:
        _, public_pem = keypair
        result = verify_activation_code(code, machine_id=MACHINE_ID, public_key_pem=public_pem)
        assert not result.valid
        assert result.reason == MALFORMED

    def test_whitespace_around_a_pasted_code_is_tolerated(self, keypair) -> None:
        """Users paste from email/LINE — leading/trailing whitespace is normal."""
        private_key, public_pem = keypair
        code = sign_code(private_key, build_payload(customer="Acme", machine_id=MACHINE_ID))

        result = verify_activation_code(f"\n  {code}  \n", machine_id=MACHINE_ID, public_key_pem=public_pem)

        assert result.valid

    def test_code_is_a_single_line(self, keypair) -> None:
        """The Activation Code must survive being pasted into one input box."""
        private_key, _ = keypair
        code = sign_code(private_key, build_payload(customer="Acme", machine_id=MACHINE_ID))
        assert "\n" not in code
        assert code.count(".") == 1

    def test_roundtrip_preserves_the_payload(self, keypair) -> None:
        private_key, public_pem = keypair
        payload = build_payload(customer="Acme", machine_id=MACHINE_ID, max_meters=30)
        code = sign_code(private_key, payload)

        result = verify_activation_code(code, machine_id=MACHINE_ID, public_key_pem=public_pem)

        assert result.valid
        assert result.payload is not None
        assert json.loads(canonical_payload_bytes(result.payload)) == payload
        assert result.max_meters == 30
