"""Activation Code — format, canonicalization, and the Ed25519 verify primitive.

An Activation Code is the one-line, copy-paste-safe carrier of a vendor-signed
license (CONTEXT.md). Format, frozen alongside the fingerprint::

    base64url(canonical_payload_json) + "." + base64url(signature)

Both halves use base64url **without padding** so the code survives email, LINE
and URLs untouched.

Canonical payload bytes — the single source of the signature agreement between
issuer and verifier::

    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

``tools/arichds_vendor.py`` duplicates that rule verbatim; it must stay
byte-identical on both sides or nothing verifies.

This module is a standalone primitive, ported from
``cewe-worker/src/license/verify.py``: it never raises on bad input, never
imports FastAPI, and never touches the filesystem beyond loading the bundled
public key. Every failure path returns a :class:`ActivationVerification` with
``valid=False`` and a reason code — invalid input is a *value*, not an exception.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

# ─── Reason codes ─────────────────────────────────────────────────────────────
MALFORMED: Final[str] = "MALFORMED"  # not decodable / not JSON / missing fields
INVALID_SIGNATURE: Final[str] = "INVALID_SIGNATURE"  # well-formed, signature fails
WRONG_MACHINE: Final[str] = "WRONG_MACHINE"  # authentic but bound to another machine
EXPIRED: Final[str] = "EXPIRED"  # authentic but past the lease end
WRONG_PRODUCT: Final[str] = "WRONG_PRODUCT"  # another product, or a payload version we do not speak
NO_LICENSE: Final[str] = "NO_LICENSE"  # nothing activated yet (set by the service)

#: Payload schema version this build speaks. v2 = ARICHDS (v1 was CEWE's shape).
PAYLOAD_VERSION: Final[int] = 2
#: Product tag every ARICHDS payload carries.
PRODUCT: Final[str] = "arichds"

#: Modes a license can be issued in (SPEC §3.9).
MODE_OFFLINE: Final[str] = "offline"
MODE_LEASED: Final[str] = "leased"

_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "v",
    "product",
    "customer",
    "machine_id",
    "mode",
    "issued_at",
    "expires_at",
    "max_meters",
    "features",
)

# The vendor public key ships next to this module (not CWD-relative), so a
# frozen exe finds it wherever it was started from.
_PUBLIC_KEY_PATH: Final[Path] = Path(__file__).parent / "public_key.pem"


@dataclass(frozen=True)
class ActivationVerification:
    """Outcome of verifying an Activation Code.

    Attributes:
        valid: True only when the signature verifies, the product/version match,
            the code is bound to this Machine ID, and the lease has not lapsed.
        reason: ``None`` iff ``valid``; otherwise one of the reason codes above.
        payload: The decoded payload when it parsed, else ``None`` — populated
            even on failure so the UI can explain *which* machine a code is for.
        customer: Customer name from the payload, when parsed.
        machine_id: Machine ID the code is bound to, when parsed.
        mode: ``"offline"`` or ``"leased"``, when parsed.
        expires_at: Lease end (UTC), or ``None`` for a perpetual offline license.
        max_meters: Device quota, or ``None`` for unlimited.
        features: Licensed feature names, or ``None``.
        models: Licensed meter model keys (issue 015), or ``None``. ``None``
            grandfathers every catalogued model — the same ceiling shape
            ``features.py``'s ``effective_features`` already uses for
            *features*; an **empty list** is meaningfully different: it means
            the license permits no model at all.
    """

    valid: bool
    reason: str | None
    payload: dict[str, Any] | None = None
    customer: str | None = None
    machine_id: str | None = None
    mode: str | None = None
    expires_at: datetime | None = None
    max_meters: int | None = None
    features: list[str] | None = None
    models: list[str] | None = None


def canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    """Return the deterministic bytes that are signed and verified.

    The single source of truth for the signature agreement.
    ``tools/arichds_vendor.py`` duplicates this exact rule.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_payload(
    *,
    customer: str,
    machine_id: str,
    mode: str = MODE_OFFLINE,
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    max_meters: int | None = None,
    features: list[str] | None = None,
    models: list[str] | None = None,
) -> dict[str, Any]:
    """Build a well-formed v2 payload.

    Every optional field is present and explicitly ``null`` rather than omitted,
    so the canonical bytes have a fixed key set and a missing key always means a
    malformed code.

    ``models`` (issue 015) is deliberately **not** in ``_REQUIRED_FIELDS`` and
    ``PAYLOAD_VERSION`` is unchanged, so every license already issued — which
    carries no ``models`` key at all — keeps verifying. The consequence,
    recorded here because it is easy to miss: ``verify_activation_code``
    re-canonicalizes the payload it parsed and only checks that the required
    fields are *present*, so an *extra* key verifies cleanly on a build that
    predates this change — that build accepts the license and silently
    ignores the model lock. A model lock is therefore a **contractual**
    control, not a security boundary, exactly like ``max_meters``: an old exe
    defeats both (SPEC §3.9).

    Args:
        customer: Customer or company name recorded in the license.
        machine_id: The Machine ID this license binds to.
        mode: ``"offline"`` (permanent escape hatch) or ``"leased"``.
        issued_at: Issue time; defaults to now (UTC).
        expires_at: Lease end; ``None`` for a non-expiring offline license.
        max_meters: Device quota; ``None`` for unlimited.
        features: Licensed feature names; ``None`` for "not restricted here".
        models: Licensed meter model keys (issue 015); ``None`` grandfathers
            every catalogued model.

    Returns:
        The payload dict, ready to canonicalize and sign.
    """
    return {
        "v": PAYLOAD_VERSION,
        "product": PRODUCT,
        "customer": customer,
        "machine_id": machine_id,
        "mode": mode,
        "issued_at": _to_iso(issued_at or datetime.now(UTC)),
        "expires_at": _to_iso(expires_at),
        "max_meters": max_meters,
        "features": features,
        "models": models,
    }


def _to_iso(value: datetime | None) -> str | None:
    """Serialize a datetime as a UTC ISO-8601 string, or pass through None."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _b64url_encode(raw: bytes) -> str:
    """base64url without padding — URL/email/LINE safe."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    """Decode base64url, restoring the stripped padding.

    Raises:
        ValueError: If *text* is not valid base64url.
    """
    padding = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("not valid base64url") from exc


def encode_activation_code(payload: dict[str, Any], signature: bytes) -> str:
    """Assemble the one-line Activation Code from a payload and its signature."""
    return f"{_b64url_encode(canonical_payload_bytes(payload))}.{_b64url_encode(signature)}"


def load_public_key_pem() -> bytes:
    """Read the vendor public key bundled next to this module.

    Returns:
        PEM-encoded Ed25519 public key bytes.

    Raises:
        FileNotFoundError: If the build is missing its public key — a packaging
            bug, and one worth failing loudly on rather than silently refusing
            every valid code.
    """
    return _PUBLIC_KEY_PATH.read_bytes()


def _malformed() -> ActivationVerification:
    """Result for input we could not parse into a payload + signature."""
    return ActivationVerification(valid=False, reason=MALFORMED)


def _parse_expires_at(raw: Any) -> datetime | None | str:
    """Parse the ``expires_at`` field; returns the sentinel ``"bad"`` on garbage."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        return "bad"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return "bad"
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def verify_activation_code(
    code: str,
    *,
    machine_id: str,
    public_key_pem: bytes | None = None,
    now: datetime | None = None,
) -> ActivationVerification:
    """Verify an Activation Code against this machine.

    Never raises on bad input. Checks run in a deliberate order so the reason
    code is the most useful one: signature **before** expiry (an authentic but
    lapsed code reports ``EXPIRED``, not ``INVALID_SIGNATURE``), and machine
    binding before expiry (a code for the wrong machine is a wrong code, whether
    or not it also happens to be old).

    Args:
        code: The pasted Activation Code. Surrounding whitespace is tolerated.
        machine_id: This machine's Machine ID.
        public_key_pem: Vendor public key. Defaults to the bundled one.
        now: Reference time for the expiry check. Defaults to now (UTC).

    Returns:
        The verification result.
    """
    if public_key_pem is None:
        public_key_pem = load_public_key_pem()
    if now is None:
        now = datetime.now(UTC)

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
        payload_bytes = _b64url_decode(payload_b64)
        signature = _b64url_decode(signature_b64)
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

    customer = payload.get("customer")
    bound_machine_id = payload.get("machine_id")
    mode = payload.get("mode")
    if not isinstance(customer, str) or not isinstance(bound_machine_id, str) or not isinstance(mode, str):
        return _malformed()

    expires_at = _parse_expires_at(payload.get("expires_at"))
    if expires_at == "bad":
        return _malformed()
    assert expires_at is None or isinstance(expires_at, datetime)

    max_meters = payload.get("max_meters")
    if max_meters is not None and not isinstance(max_meters, int):
        return _malformed()
    features = payload.get("features")
    if features is not None and not (isinstance(features, list) and all(isinstance(f, str) for f in features)):
        return _malformed()
    models = payload.get("models")
    if models is not None and not (isinstance(models, list) and all(isinstance(m, str) for m in models)):
        return _malformed()

    details: dict[str, Any] = {
        "payload": payload,
        "customer": customer,
        "machine_id": bound_machine_id,
        "mode": mode,
        "expires_at": expires_at,
        "max_meters": max_meters,
        "features": features,
        "models": models,
    }

    # ── Signature, over the canonical bytes of the payload we just parsed ─────
    # Re-canonicalizing (rather than verifying the transmitted bytes) is what
    # makes tampering detectable even if the attacker re-encodes cleanly.
    try:
        public_key = load_pem_public_key(public_key_pem)
    except (ValueError, TypeError):
        return _malformed()
    if not isinstance(public_key, Ed25519PublicKey):
        return _malformed()

    try:
        public_key.verify(signature, canonical_payload_bytes(payload))
    except InvalidSignature:
        return ActivationVerification(valid=False, reason=INVALID_SIGNATURE, **details)

    # ── Product / schema version ─────────────────────────────────────────────
    if payload.get("product") != PRODUCT or payload.get("v") != PAYLOAD_VERSION:
        return ActivationVerification(valid=False, reason=WRONG_PRODUCT, **details)

    # ── Machine binding ──────────────────────────────────────────────────────
    if bound_machine_id != machine_id:
        return ActivationVerification(valid=False, reason=WRONG_MACHINE, **details)

    # ── Lease (valid through the expiry instant) ─────────────────────────────
    if expires_at is not None and now > expires_at:
        return ActivationVerification(valid=False, reason=EXPIRED, **details)

    return ActivationVerification(valid=True, reason=None, **details)
