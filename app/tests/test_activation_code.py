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

from arichds.licensing import activation_code as ac
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

#: The Activation Code actually installed at
#: ``C:\ProgramData\ARICHDS\license\license.lic`` on this development machine,
#: read read-only on 2026-08-27 while auditing issue 015 (491 characters).
#: Decodes to: customer "ARICHDS Internal Test", mode "offline", expires_at
#: null, max_meters null, features ["load_profile","billing",
#: "database_destination"], issued_at "2026-08-26T08:20:10.305002+00:00",
#: machine_id "50aa2362cd5b283d67c09e0e0e94abf9f4104245f24cc372ed449c8e12fdbf3c",
#: v 2. It predates issue 015 — the payload carries no "models" key at all —
#: and is the one artifact in issue 015 that could not be reconstructed, so it
#: is pinned here as a literal rather than read from disk at test time (the
#: suite must pass on a machine with no ARICHDS install).
PRE_MODELS_LICENCE = (
    "eyJjdXN0b21lciI6IkFSSUNIRFMgSW50ZXJuYWwgVGVzdCIsImV4cGlyZXNfYXQiOm51bGwsImZlYXR1cmVzIjpbImxvYWRfcHJvZmlsZSIsImJp"
    "bGxpbmciLCJkYXRhYmFzZV9kZXN0aW5hdGlvbiJdLCJpc3N1ZWRfYXQiOiIyMDI2LTA4LTI2VDA4OjIwOjEwLjMwNTAwMiswMDowMCIsIm1hY2hp"
    "bmVfaWQiOiI1MGFhMjM2MmNkNWIyODNkNjdjMDllMGUwZTk0YWJmOWY0MTA0MjQ1ZjI0Y2MzNzJlZDQ0OWM4ZTEyZmRiZjNjIiwibWF4X21ldGVy"
    "cyI6bnVsbCwibW9kZSI6Im9mZmxpbmUiLCJwcm9kdWN0IjoiYXJpY2hkcyIsInYiOjJ9.3om_cHJAdduZUFGH27xyridN3H7G1-A2VegxucJeki"
    "_IjzJuDhR_0AYuabiIqIV548j38di88T9YHn5lraL-BA"
)
PRE_MODELS_LICENCE_MACHINE_ID = "50aa2362cd5b283d67c09e0e0e94abf9f4104245f24cc372ed449c8e12fdbf3c"


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
            "models",
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
        assert payload["models"] is None


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

    def test_models_survives_the_roundtrip(self, keypair) -> None:
        private_key, public_pem = keypair
        payload = build_payload(customer="Acme", machine_id=MACHINE_ID, models=["prometer100", "saral305"])
        code = sign_code(private_key, payload)

        result = verify_activation_code(code, machine_id=MACHINE_ID, public_key_pem=public_pem)

        assert result.valid
        assert result.models == ["prometer100", "saral305"]

    def test_a_null_models_verifies_and_carries_none(self, keypair) -> None:
        private_key, public_pem = keypair
        code = sign_code(private_key, build_payload(customer="Acme", machine_id=MACHINE_ID, models=None))

        result = verify_activation_code(code, machine_id=MACHINE_ID, public_key_pem=public_pem)

        assert result.valid
        assert result.models is None

    def test_a_non_list_models_is_malformed(self, keypair) -> None:
        private_key, public_pem = keypair
        payload = build_payload(customer="Acme", machine_id=MACHINE_ID)
        payload["models"] = "prometer100"  # a string, not a list — the type check must reject it
        code = sign_code(private_key, payload)

        result = verify_activation_code(code, machine_id=MACHINE_ID, public_key_pem=public_pem)

        assert not result.valid
        assert result.reason == MALFORMED

    def test_a_models_list_with_a_non_string_entry_is_malformed(self, keypair) -> None:
        private_key, public_pem = keypair
        payload = build_payload(customer="Acme", machine_id=MACHINE_ID)
        payload["models"] = ["prometer100", 5]
        code = sign_code(private_key, payload)

        result = verify_activation_code(code, machine_id=MACHINE_ID, public_key_pem=public_pem)

        assert not result.valid
        assert result.reason == MALFORMED


class TestAPreChangeLicenceStillVerifies:
    """Issue 015, step 1 — the real Activation Code installed on this dev
    machine before ``models`` existed must keep verifying after this change.

    ``_trust_vendor_key`` (``conftest.py``, autouse) replaces
    ``load_public_key_pem`` with a throwaway test key, so this licence — signed
    against the real bundled vendor key — would not verify under that default.
    ``public_key_pem=`` is passed explicitly, read straight from the module's
    own ``_PUBLIC_KEY_PATH``, to bypass the patched loader without disturbing
    it for any other test. ``machine_id=`` is the one decoded from the
    payload itself, not ``TEST_MACHINE_ID`` — this code was never issued for
    that machine. No ``now=`` pinning is needed: the licence is
    ``mode: offline`` with ``expires_at: null``.
    """

    def test_the_installed_licence_verifies_before_this_change(self) -> None:
        public_key_pem = ac._PUBLIC_KEY_PATH.read_bytes()

        result = verify_activation_code(
            PRE_MODELS_LICENCE,
            machine_id=PRE_MODELS_LICENCE_MACHINE_ID,
            public_key_pem=public_key_pem,
        )

        assert result.valid
        assert result.reason is None
        assert result.customer == "ARICHDS Internal Test"
        # The actual consequence of the absent `models` key — grandfathered,
        # not merely tolerated (code review, fix round 1). `payload.get`
        # makes this the same code path as an explicit `null`, but that is
        # the claim this test exists to prove, not something to assume.
        assert result.models is None
