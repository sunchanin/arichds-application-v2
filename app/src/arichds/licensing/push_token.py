"""Push Token — the JWT a machine presents to the team's central server.

ADR 0024 / SPEC §3.8: the central push authenticates with a **Push Token**, a
real JWT (``header.payload.signature``) signed **EdDSA** with the vendor's
existing Ed25519 key — the same key that signs an Activation Code and a Meter
Activation Code (ADR 0019, "The decision"). It is deliberately a *different
wire format* from those two: an Activation Code is
``base64url(payload).base64url(signature)`` (one dot), never a JWT, so a
genuine JWT already fails the sibling verifiers' dot-count check in
``activation_code.py``/``meter_activation_code.py`` before either ever looks
at a claim — and a Push Token here refuses anything that is not a
two-dot JWT with the right ``product`` claim, which an Activation Code or a
Meter Activation Code can never be. Neither format needs to know the other
exists for this separation to hold. The reverse case gets its own reason,
:data:`LICENCE_CODE_NOT_PUSH_TOKEN`, rather than the generic
:data:`MALFORMED` — an operator who pastes an Activation Code into the Push
Token field is told which secret they pasted (spec story 8).

Claims: ``sub`` (the Machine ID), ``product`` (:data:`PUSH_TOKEN_PRODUCT`,
distinct from the licence's ``"arichds"``), ``v`` (token version) and ``iat``.
**Deliberately no ``exp``** — revocation is the receiving server's own
denylist by Machine ID, not a client-side expiry (ADR 0024).

This module is the *verify* half, used by the app. ``tools/arichds_vendor.py``
holds the *issue* half (``sign-push``) and duplicates :func:`build_push_token_claims`
verbatim, the same agreement ``activation_code.py``'s canonical-payload rule
keeps with the CLI — the app never issues a Push Token itself.

Same standalone-primitive rule as the sibling modules: never raises on bad
input, never touches the filesystem beyond the bundled public key. Every
failure path returns a :class:`PushTokenVerification` with ``valid=False``
and a reason code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import jwt

from arichds.licensing import activation_code as ac

#: Token version this build issues and accepts.
CURRENT_PUSH_TOKEN_VERSION: Final[int] = 1
#: Versions this build's verifier accepts. A future version bump adds to this
#: set rather than replacing it, the same ceiling shape the licence's
#: ``models``/``features`` grandfathering uses.
SUPPORTED_PUSH_TOKEN_VERSIONS: Final[frozenset[int]] = frozenset({CURRENT_PUSH_TOKEN_VERSION})
#: Distinct from the licence's ``ac.PRODUCT`` ("arichds") — this is the claim
#: that makes a Push Token unable to pass as an Activation Code even if some
#: future change ever made the two formats structurally similar.
PUSH_TOKEN_PRODUCT: Final[str] = "arichds-push"
#: The one algorithm a Push Token is signed and verified with.
PUSH_TOKEN_ALGORITHM: Final[str] = "EdDSA"

# ─── Reason codes ─────────────────────────────────────────────────────────────
#: Not a JWT at all, undecodable, or missing/malformed required claims.
MALFORMED: Final[str] = ac.MALFORMED
#: The signature does not verify. Covers both a tampered token and a token
#: genuinely signed by a different key — the two are cryptographically
#: indistinguishable to a verifier holding only the public key, exactly the
#: reasoning ``activation_code.INVALID_SIGNATURE`` already documents for the
#: sibling format.
INVALID_SIGNATURE: Final[str] = ac.INVALID_SIGNATURE
#: Authentic signature, but ``product`` is not :data:`PUSH_TOKEN_PRODUCT`.
WRONG_PRODUCT: Final[str] = "WRONG_PRODUCT"
#: Authentic signature and product, but ``v`` is not one this build speaks.
UNSUPPORTED_VERSION: Final[str] = "UNSUPPORTED_VERSION"
#: Shaped like an Activation Code or a Meter Activation Code (one dot, first
#: segment a JSON object naming the licence's own ``ac.PRODUCT``) rather than
#: a JWT — a more specific reason than :data:`MALFORMED` so an operator who
#: pastes the wrong secret into the Push Token field is told which mistake
#: they made (spec story 8). A shape check only: it never verifies the
#: licence code's own signature, so it adds no authentication path, only a
#: better reason.
LICENCE_CODE_NOT_PUSH_TOKEN: Final[str] = "LICENCE_CODE_NOT_PUSH_TOKEN"


@dataclass(frozen=True)
class PushTokenVerification:
    """Outcome of verifying a Push Token.

    Attributes:
        valid: True only when the signature verifies and the ``product``/``v``
            claims match what this build issues.
        reason: ``None`` iff ``valid``; otherwise one of the reason codes above.
        machine_id: The ``sub`` claim, populated only when ``valid`` — unlike
            the sibling verifiers, nothing here needs to explain a rejected
            token's origin to a user, so an unverified claim is never surfaced.
    """

    valid: bool
    reason: str | None
    machine_id: str | None = None


def build_push_token_claims(*, machine_id: str, issued_at: datetime | None = None) -> dict[str, Any]:
    """Build the claims signed into a Push Token.

    The app never issues one — this exists as the shape-of-record the
    issuer/verifier agreement test compares the vendor CLI's duplicate
    against, exactly as ``meter_activation_code.build_meter_payload`` is
    (that module's own docstring at :5-8).

    Args:
        machine_id: The Machine ID this token is bound to.
        issued_at: ``iat``; defaults to now (UTC). PyJWT converts a
            ``datetime`` to a Unix timestamp at encode time.

    Returns:
        The claims dict, ready to hand to ``jwt.encode``.
    """
    return {
        "sub": machine_id,
        "product": PUSH_TOKEN_PRODUCT,
        "v": CURRENT_PUSH_TOKEN_VERSION,
        "iat": issued_at or datetime.now(UTC),
    }


def _malformed() -> PushTokenVerification:
    """Result for input we could not parse into a well-formed JWT."""
    return PushTokenVerification(valid=False, reason=MALFORMED)


def _looks_like_licence_code(cleaned: str) -> bool:
    """True when *cleaned* has the Activation Code / Meter Activation Code shape.

    One dot, and the first segment decodes to a JSON object naming the
    licence's own product (``ac.PRODUCT``, never :data:`PUSH_TOKEN_PRODUCT`).
    Reuses ``activation_code``'s own base64url helper rather than duplicating
    it. A shape check only — it never verifies the licence code's signature,
    so a string that merely *looks* like one still gets this reason even if
    it is garbage past the first segment; that is fine, since the reason is
    about which secret was pasted, not whether that secret is genuine.

    ``UnicodeDecodeError`` is a ``ValueError`` subclass, so one except clause
    covers both a broken base64 payload and one that decodes to non-UTF-8
    bytes.
    """
    if cleaned.count(".") != 1:
        return False
    payload_b64, _, _ = cleaned.partition(".")
    if not payload_b64:
        return False
    try:
        payload = json.loads(ac._b64url_decode(payload_b64))
    except ValueError:
        return False
    return isinstance(payload, dict) and payload.get("product") == ac.PRODUCT


def verify_push_token(token: str, *, public_key_pem: bytes | None = None) -> PushTokenVerification:
    """Verify a Push Token.

    Never raises on bad input. Check order mirrors the sibling verifiers:
    shape (is this even JWT-shaped, or does it look like the *other* wire
    format) before authenticity (does the signature verify) before meaning
    (``product``, then ``v``) — ``jwt.decode`` folds "is this a JWT" and
    "does the signature verify" into one call, so those two both surface
    through the same exception handling below.

    ``verify_iat=False``: PyJWT otherwise refuses a token whose ``iat`` is
    even one second ahead of the verifying clock (``ImmatureSignatureError``).
    ``sign-push`` stamps ``iat`` from the vendor's clock; verification runs on
    the customer's — a customer clock running even slightly behind would
    refuse a perfectly genuine token as malformed. Nothing in ADR 0024 or the
    contract uses ``iat`` for validity, only for a human reading when a token
    was issued, so there is nothing to check it against.

    Args:
        token: The pasted Push Token. Surrounding whitespace is tolerated.
        public_key_pem: Vendor public key. Defaults to the same bundled key
            the licence verifiers use (``activation_code.load_public_key_pem``)
            — one vendor key signs every wire format (ADR 0019).

    Returns:
        The verification result.
    """
    if public_key_pem is None:
        public_key_pem = ac.load_public_key_pem()

    if not isinstance(token, str):
        return _malformed()
    cleaned = token.strip()
    if not cleaned:
        return _malformed()

    if _looks_like_licence_code(cleaned):
        return PushTokenVerification(valid=False, reason=LICENCE_CODE_NOT_PUSH_TOKEN)

    try:
        claims = jwt.decode(
            cleaned,
            public_key_pem,
            algorithms=[PUSH_TOKEN_ALGORITHM],
            options={"verify_iat": False},
        )
    except jwt.InvalidSignatureError:
        return PushTokenVerification(valid=False, reason=INVALID_SIGNATURE)
    except jwt.InvalidTokenError:
        # Every other PyJWT decode failure: not enough/too many segments, not
        # valid base64url, not valid JSON, wrong algorithm header, and so on —
        # all "this was never a Push Token".
        return _malformed()

    machine_id = claims.get("sub")
    if not isinstance(machine_id, str) or not machine_id:
        return _malformed()

    if claims.get("product") != PUSH_TOKEN_PRODUCT:
        return PushTokenVerification(valid=False, reason=WRONG_PRODUCT)
    if claims.get("v") not in SUPPORTED_PUSH_TOKEN_VERSIONS:
        return PushTokenVerification(valid=False, reason=UNSUPPORTED_VERSION)

    return PushTokenVerification(valid=True, reason=None, machine_id=machine_id)
