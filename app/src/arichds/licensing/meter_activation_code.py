"""Meter Activation Code — payload, canonicalization, and the verify primitive.

ADR 0019 / issue #41: a Meter Activation Code is signed per meter and bound to
**both** the Meter Serial and the Machine ID it is claimed for. It is a
separate wire format from the Activation Code in ``activation_code.py``
(CONTEXT.md: *Meter Activation Code* — _Avoid_: "per-meter Activation Code"),
kept in its own module so the two never share a required-field set or a
verify branch.

Deliberately **no expiry field**. ADR 0019's "When it is checked" section
records that this is an entitlement checked at the moment of entitlement —
Create, and Update when the serial changes — never re-evaluated
continuously the way ADR 0001 requires of the machine licence. A nullable
``expires_at`` key here would be an invitation to implement the continuous
check the ADR explicitly rejects.

This module reuses the sibling module's primitives (``canonical_payload_bytes``,
``load_public_key_pem``, ``encode_activation_code``, ``_b64url_decode``) rather
than duplicating them — one vendor key signs both formats (ADR 0019, "The
decision"). Same standalone-primitive rule as ``activation_code.py``: never
raises on bad input, never touches the filesystem beyond the bundled public
key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from arichds.licensing import activation_code as ac

_REQUIRED_FIELDS: Final[tuple[str, ...]] = ("v", "product", "type", "meter_serial", "machine_id", "issued_at")

#: This format has no predecessor — v1 is not CEWE's shape the way the
#: Activation Code's v2 is, it is simply the first Meter Activation Code.
METER_PAYLOAD_VERSION: Final[int] = 1
METER_TYPE: Final[str] = "meter"

#: Authentic code, bound to a different Meter Serial than the one presented.
WRONG_METER: Final[str] = "WRONG_METER"


@dataclass(frozen=True)
class MeterActivationVerification:
    """Outcome of verifying a Meter Activation Code."""

    valid: bool
    reason: str | None
    payload: dict[str, Any] | None = None
    meter_serial: str | None = None
    machine_id: str | None = None


def build_meter_payload(
    *,
    meter_serial: str,
    machine_id: str,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the payload signed into a Meter Activation Code.

    The app never issues one — this exists here as the shape-of-record the
    issuer/verifier agreement test compares the CLI's duplicate against,
    exactly as ``activation_code.build_payload`` is used at
    ``test_license_roundtrip.py:78-83``.
    """
    return {
        "v": METER_PAYLOAD_VERSION,
        "product": ac.PRODUCT,
        "type": METER_TYPE,
        "meter_serial": meter_serial,
        "machine_id": machine_id,
        "issued_at": _to_iso(issued_at or datetime.now(UTC)),
    }


def _to_iso(value: datetime) -> str:
    """Serialize a datetime as a UTC ISO-8601 string. Naive input is treated as UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _malformed() -> MeterActivationVerification:
    """Result for input we could not parse into a payload + signature."""
    return MeterActivationVerification(valid=False, reason=ac.MALFORMED)


def verify_meter_activation_code(
    code: str,
    *,
    meter_serial: str,
    machine_id: str,
    public_key_pem: bytes | None = None,
) -> MeterActivationVerification:
    """Verify a Meter Activation Code against a claimed Meter Serial + Machine ID.

    Never raises on bad input. Check order (deliberate, mirrors
    ``activation_code.verify_activation_code``'s reasoning at :226-231):
    malformed -> signature -> product/type/version -> machine binding ->
    serial binding. Authenticity is checked before meaning, and machine
    binding before serial binding — a code wrong on both reports
    ``WRONG_MACHINE``, the more systemic and more actionable error.

    ``meter_serial`` and ``machine_id`` on the result are populated whenever
    the payload parsed, including on failure, so a caller can explain which
    meter a rejected code was actually for — same rule as
    ``ActivationVerification`` (``activation_code.py:82-84``).

    Args:
        code: The pasted Meter Activation Code. Surrounding whitespace is tolerated.
        meter_serial: The Meter Serial this code is being claimed for.
        machine_id: This machine's Machine ID.
        public_key_pem: Vendor public key. Defaults to the bundled one.

    Returns:
        The verification result.
    """
    if public_key_pem is None:
        public_key_pem = ac.load_public_key_pem()

    # ── Split and decode ─────────────────────────────────────────────────────
    if not isinstance(code, str):
        return _malformed()
    cleaned = code.strip()
    if cleaned.count(".") != 1:
        return _malformed()
    payload_b64, signature_b64 = cleaned.split(".")
    if not payload_b64 or not signature_b64:
        return _malformed()

    try:
        payload_bytes = ac._b64url_decode(payload_b64)
        signature = ac._b64url_decode(signature_b64)
    except ValueError:
        return _malformed()

    try:
        payload = json.loads(payload_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _malformed()
    if not isinstance(payload, dict):
        return _malformed()
    if any(field not in payload for field in _REQUIRED_FIELDS):
        return _malformed()

    bound_serial = payload.get("meter_serial")
    bound_machine_id = payload.get("machine_id")
    if not isinstance(bound_serial, str) or not isinstance(bound_machine_id, str):
        return _malformed()

    details: dict[str, Any] = {
        "payload": payload,
        "meter_serial": bound_serial,
        "machine_id": bound_machine_id,
    }

    # ── Signature, over the canonical bytes of the payload we just parsed ─────
    try:
        public_key = load_pem_public_key(public_key_pem)
    except (ValueError, TypeError):
        return _malformed()
    if not isinstance(public_key, Ed25519PublicKey):
        return _malformed()

    try:
        public_key.verify(signature, ac.canonical_payload_bytes(payload))
    except InvalidSignature:
        return MeterActivationVerification(valid=False, reason=ac.INVALID_SIGNATURE, **details)

    # ── Product / type / schema version ──────────────────────────────────────
    if (
        payload.get("product") != ac.PRODUCT
        or payload.get("type") != METER_TYPE
        or payload.get("v") != METER_PAYLOAD_VERSION
    ):
        return MeterActivationVerification(valid=False, reason=ac.WRONG_PRODUCT, **details)

    # ── Machine binding ───────────────────────────────────────────────────────
    if bound_machine_id != machine_id:
        return MeterActivationVerification(valid=False, reason=ac.WRONG_MACHINE, **details)

    # ── Serial binding ────────────────────────────────────────────────────────
    if bound_serial.strip() != meter_serial.strip():
        return MeterActivationVerification(valid=False, reason=WRONG_METER, **details)

    return MeterActivationVerification(valid=True, reason=None, **details)
