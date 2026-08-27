#!/usr/bin/env python3
"""ARICHDS Vendor CLI — Ed25519 keypair generation and Activation Code signing.

This is the **vendor's** tool, not the customer's. It holds the private key that
signs Activation Codes; customers only ever hold the matching public key (bundled
into ``arichds.exe``) and can verify but never issue. Until portal v2 exists
(M9), this is how every license is issued (SPEC §3.1).

Commands
--------
``keygen``
    Generate a fresh Ed25519 keypair. Writes the PRIVATE key to the path given
    by ``--private-out`` (**never commit it**) and the PUBLIC key both next to
    it and — unless ``--no-bundle`` — into the app package at
    ``app/src/arichds/licensing/public_key.pem``, which is what the built exe
    verifies against.

``sign``
    Sign an Activation Code for one machine::

        python tools/arichds_vendor.py sign --customer "Acme Co" --machine-id <64-hex>

    Prints the one-line Activation Code on stdout. That single line is what the
    customer pastes into the first-run Activation page.

    ``--features`` is validated against ``SELLABLE_FEATURE_KEYS``, imported
    from the app: an unrecognised name — a misspelling, or the ops-only
    ``app_log``, which no license ever governs — refuses the run before
    anything is signed rather than producing a valid code for a feature that
    does not exist. Omit the flag entirely to grandfather every sellable
    feature; that is not the same as passing an empty list.

    Some sellable names are **reserved** (``RESERVED_FEATURE_KEYS``, also
    imported): signable, so a license cut today already carries them, but
    nothing implements them yet. Naming one *warns* and keeps signing — it is
    never refused, because being signable early is the entire point of
    reserving it. **Do not put a reserved name on an invoice.**

    ``--models``/``--brands`` (issue 015) lock which meter models the
    machine may add. Both are validated against the app's own catalog,
    imported the same way ``--features`` is: an unrecognised model or brand
    name refuses the run before anything is signed. They may be combined;
    the result is the union, deduplicated and sorted (unlike ``--features``,
    deliberately — naming a brand and naming every one of its models must
    produce byte-identical payloads). Omitting **both** grandfathers every
    catalogued model; that is not the same as either resolving to an empty
    set.

``sign-meter``
    Sign a Meter Activation Code for one meter on one machine (ADR 0019)::

        python tools/arichds_vendor.py sign-meter --meter-serial <serial> --machine-id <64-hex>

    Prints the one-line Meter Activation Code on stdout. Bound to both the
    Meter Serial and the Machine ID — a separate wire format from the
    Activation Code above, verified by
    ``app/src/arichds/licensing/meter_activation_code.py``.

``fingerprint``
    Print *this* machine's Machine ID — for vendor-side testing, so you can sign
    a code for your own dev box without asking anyone for their ID.

The canonical payload rule below is duplicated **verbatim** from
``app/src/arichds/licensing/activation_code.py``. It must stay byte-identical on
both sides or nothing verifies; the golden-roundtrip test in
``app/tests/test_license_roundtrip.py`` imports this file and would fail loudly
if they ever drift.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent

DEFAULT_PRIVATE_KEY_PATH = TOOLS_DIR / ".arichds_private_key.pem"
DEFAULT_PUBLIC_KEY_PATH = TOOLS_DIR / "arichds_public_key.pem"
#: Where the app looks for the key it verifies Activation Codes against.
BUNDLED_PUBLIC_KEY_PATH = REPO_ROOT / "app" / "src" / "arichds" / "licensing" / "public_key.pem"

PAYLOAD_VERSION = 2
PRODUCT = "arichds"
#: Default lease length for a leased license (SPEC §3.9 — a kill-switch, not a
#: subscription). Offline licenses default to no expiry at all.
DEFAULT_LEASE_DAYS = 45
#: In ``FEATURE_KEYS`` but deliberately outside ``SELLABLE_FEATURE_KEYS`` — the
#: customer's ``.env`` governs it and no license ever does, so it must not be
#: signed into one.
OPS_ONLY_FEATURE_KEY = "app_log"


# ─── Signature agreement (duplicated verbatim from the app) ───────────────────


def canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic bytes that are signed and verified.

    MUST match ``arichds.licensing.activation_code.canonical_payload_bytes``.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def b64url_encode(raw: bytes) -> str:
    """base64url without padding — URL/email/LINE safe."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def build_payload(
    *,
    customer: str,
    machine_id: str,
    mode: str = "offline",
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    max_meters: int | None = None,
    features: list[str] | None = None,
    models: list[str] | None = None,
) -> dict[str, Any]:
    """Build the v2 payload. Mirrors the app's ``build_payload`` field-for-field."""
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


#: Meter Activation Code payload version. This format has no predecessor.
METER_PAYLOAD_VERSION = 1
METER_TYPE = "meter"


def build_meter_payload(
    *,
    meter_serial: str,
    machine_id: str,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a Meter Activation Code payload. Mirrors the app's field-for-field.

    MUST match ``arichds.licensing.meter_activation_code.build_meter_payload``.
    """
    return {
        "v": METER_PAYLOAD_VERSION,
        "product": PRODUCT,
        "type": METER_TYPE,
        "meter_serial": meter_serial,
        "machine_id": machine_id,
        "issued_at": _to_iso(issued_at or datetime.now(UTC)),
    }


def sign_payload(private_pem: bytes, payload: dict[str, Any]) -> str:
    """Sign *payload* and return the one-line Activation Code.

    Args:
        private_pem: PEM-encoded Ed25519 private key.
        payload: A payload from :func:`build_payload`.

    Returns:
        ``base64url(payload).base64url(signature)`` — a single line.

    Raises:
        TypeError: If the PEM does not hold an Ed25519 private key.
    """
    private_key = load_pem_private_key(private_pem, password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("private key is not an Ed25519 key")
    signature = private_key.sign(canonical_payload_bytes(payload))
    return f"{b64url_encode(canonical_payload_bytes(payload))}.{b64url_encode(signature)}"


# ─── Commands ─────────────────────────────────────────────────────────────────


def cmd_keygen(args: argparse.Namespace) -> int:
    """Generate a fresh Ed25519 keypair."""
    private_path = Path(args.private_out)
    public_path = Path(args.public_out)

    if private_path.exists() and not args.force:
        print(f"ERROR: {private_path} already exists. Refusing to overwrite.", file=sys.stderr)
        print("       Signing with a new key invalidates every license issued with the old one.", file=sys.stderr)
        print("       Pass --force only if you are certain.", file=sys.stderr)
        return 1

    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_bytes(private_pem)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.write_bytes(public_pem)

    print(f"Private key written to {private_path}")
    print("  *** NEVER COMMIT OR SHARE THIS FILE. It is the only thing stopping anyone")
    print("      from issuing their own Activation Codes. ***")
    print(f"Public key  written to {public_path}")

    if not args.no_bundle:
        BUNDLED_PUBLIC_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        BUNDLED_PUBLIC_KEY_PATH.write_bytes(public_pem)
        print(f"Public key bundled into the app at {BUNDLED_PUBLIC_KEY_PATH}")
    return 0


def sellable_feature_keys() -> frozenset[str]:
    """The feature names ``--features`` accepts, from the app's own constant.

    Imported rather than restated: a second copy of the list in ``tools/`` goes
    stale the next time a key is added, which is exactly what
    ``database_destination`` did to a nine-key world. The ``sys.path`` insert is
    lazy, matching :func:`cmd_fingerprint` — importing app code at module scope
    would make every use of this tool depend on the app package resolving.
    """
    sys.path.insert(0, str(REPO_ROOT / "app" / "src"))
    from arichds.constants import SELLABLE_FEATURE_KEYS

    return SELLABLE_FEATURE_KEYS


def reserved_feature_keys() -> frozenset[str]:
    """Sellable names that are not actually for sale yet, from the app's constant.

    Imported, never restated, for exactly the reason
    :func:`sellable_feature_keys` is: a literal here is a second copy that
    someone has to remember to delete the day the feature ships, and nothing
    would fail if they forgot. Emptying the set in ``constants.py`` is then the
    single edit that un-reserves a key.
    """
    sys.path.insert(0, str(REPO_ROOT / "app" / "src"))
    from arichds.constants import RESERVED_FEATURE_KEYS

    return RESERVED_FEATURE_KEYS


def _reserved_warning(names: list[str], reserved: frozenset[str]) -> list[str]:
    """Stderr lines for any *names* that are reserved — or empty when none are.

    A warning, not an error: the code still signs. Refusing would break the
    thing reserving a key is for, which is that a license signed before the
    feature exists already carries it.
    """
    named = sorted({name for name in names if name in reserved})
    if not named:
        return []
    return [
        f"WARNING: reserved feature name(s): {', '.join(named)}",
        "         Signable, and signed. But nothing implements them yet, so a",
        "         customer who pays for one gets nothing. Do NOT put them on an",
        "         invoice or quote them. (See RESERVED_FEATURE_KEYS in the app's",
        "         constants.py for when each becomes real.)",
    ]


def model_catalog() -> dict[str, Any]:
    """The app's own meter-model catalog, from its own object (issue 015, D8/H).

    Imported rather than restated — the same reason :func:`sellable_feature_keys`
    is: a literal model list or brand table in ``tools/`` goes stale the day a
    tenth model is added. ``CATALOG`` (not ``supported_models()``): only the
    catalog carries brands, which ``--brands`` needs to expand, and it is the
    cheap import — ``acquisition/catalog.py`` imports nothing from
    ``drivers/`` (its own module docstring), while the driver factory's
    registry imports every driver and drags the Gurux stack into a tool that
    only signs. The ``sys.path`` insert is lazy, matching
    :func:`sellable_feature_keys` — importing app code at module scope would
    make every use of this tool depend on the app package resolving.
    """
    sys.path.insert(0, str(REPO_ROOT / "app" / "src"))
    from arichds.acquisition.catalog import CATALOG

    return CATALOG


def _resolve_models(models_arg: str | None, brands_arg: str | None) -> tuple[list[str] | None, list[str]]:
    """Resolve ``--models``/``--brands`` into a sorted, deduped model list.

    Neither flag named → ``(None, [])``: omitting both grandfathers every
    catalogued model (D2), which this function must not be able to confuse
    with "the union happened to be empty" — that state is unreachable from
    valid input, since a name that resolves to nothing is caught as
    unrecognised below.

    Gated on **presence**, not truthiness, by the caller (``cmd_sign``) —
    ``--models ""``/``--brands ""`` must be hard errors, exactly the
    ``--features ""`` trap issue 014 records for the sibling flag (D13).

    Returns:
        A ``(resolved, errors)`` pair. ``errors`` is empty iff *resolved* is
        usable; when non-empty, the run must be refused before signing.
    """
    if models_arg is None and brands_arg is None:
        return None, []

    catalog = model_catalog()
    valid_models = frozenset(catalog)
    valid_brands = frozenset(spec.brand.value for spec in catalog.values())

    named_models = [name.strip() for name in models_arg.split(",")] if models_arg is not None else []
    named_brands = [name.strip() for name in brands_arg.split(",")] if brands_arg is not None else []

    errors: list[str] = []
    if any(not name for name in named_models):
        errors.append(
            "ERROR: empty model name in --models (an entry between two commas, or a"
            " trailing comma). Nothing is guessed here; type the list again."
        )
    if any(not name for name in named_brands):
        errors.append(
            "ERROR: empty brand name in --brands (an entry between two commas, or a"
            " trailing comma). Nothing is guessed here; type the list again."
        )
    unrecognised_models = sorted({name for name in named_models if name and name not in valid_models})
    if unrecognised_models:
        errors.append(f"ERROR: unrecognised model name(s): {', '.join(unrecognised_models)}")
    unrecognised_brands = sorted({name for name in named_brands if name and name not in valid_brands})
    if unrecognised_brands:
        errors.append(f"ERROR: unrecognised brand name(s): {', '.join(unrecognised_brands)}")

    if errors:
        errors.append(f"       Valid model names: {', '.join(sorted(valid_models))}")
        errors.append(f"       Valid brand names: {', '.join(sorted(valid_brands))}")
        return None, errors

    resolved = {name for name in named_models if name}
    for brand in named_brands:
        resolved.update(model for model, spec in catalog.items() if spec.brand.value == brand)
    return sorted(resolved), []


def models_summary_text(models: list[str] | None) -> str:
    """The stderr summary phrase for a resolved model list (issue 015, D8).

    Prints what was **signed**, never the flags as typed — a seller reading
    the summary must see the outcome of ``--brands`` expanding, not the
    brand name they happened to type.
    """
    if models is None:
        return "every catalogued model"
    if not models:
        return "none"
    return ", ".join(models)


def _feature_errors(names: list[str], valid: frozenset[str], reserved: frozenset[str]) -> list[str]:
    """Every problem with *names*, as stderr lines — or empty when all are sellable."""
    unrecognised = [name for name in names if name and name not in valid and name != OPS_ONLY_FEATURE_KEY]
    errors: list[str] = []
    if unrecognised:
        errors.append(f"ERROR: unrecognised feature name(s): {', '.join(unrecognised)}")
    if OPS_ONLY_FEATURE_KEY in names:
        errors.append(
            f"ERROR: {OPS_ONLY_FEATURE_KEY!r} is ops-only and not sellable. It is governed by"
            " the customer's .env, never by a license."
        )
    if any(not name for name in names):
        errors.append(
            "ERROR: empty feature name in --features (an entry between two commas, or a"
            " trailing comma). Nothing is guessed here; type the list again."
        )
    if errors:
        errors.append(f"       Valid feature names: {', '.join(sorted(valid))}")
        # The line above is a menu to choose from, so it has to say which
        # entries are not on sale. Appended rather than annotated inline: the
        # plain sorted list is asserted verbatim by two tests that are still
        # right — every sellable name *is* offered.
        if reserved:
            errors.append(f"       Of those, reserved and NOT for sale: {', '.join(sorted(reserved))}")
    return errors


def cmd_sign(args: argparse.Namespace) -> int:
    """Sign an Activation Code for one machine."""
    private_path = Path(args.private_key)
    if not private_path.exists():
        print(f"ERROR: Private key not found at {private_path}.", file=sys.stderr)
        print("       Run: python tools/arichds_vendor.py keygen", file=sys.stderr)
        return 1

    machine_id = args.machine_id.strip().lower()
    if len(machine_id) != 64 or not all(c in "0123456789abcdef" for c in machine_id):
        print("ERROR: --machine-id must be the 64-character hex Machine ID shown on the", file=sys.stderr)
        print("       Activation page (or from `arichds_vendor.py fingerprint`).", file=sys.stderr)
        return 1

    expires_at: datetime | None = None
    if args.expires:
        try:
            expires_at = datetime.combine(date.fromisoformat(args.expires), datetime.min.time(), tzinfo=UTC)
        except ValueError:
            print(f"ERROR: Invalid --expires date {args.expires!r}. Use YYYY-MM-DD.", file=sys.stderr)
            return 1
    elif args.mode == "leased":
        # A leased license with no explicit end still needs one — that is what
        # makes it a kill-switch rather than a perpetual grant.
        expires_at = datetime.now(UTC) + timedelta(days=args.lease_days)

    features: list[str] | None = None
    if args.features:
        # Stripped: a space after a comma is shell quoting, not a typo. An entry
        # that is *empty* after stripping still fails below — we do not guess.
        features = [name.strip() for name in args.features.split(",")]
        reserved = reserved_feature_keys()
        errors = _feature_errors(features, sellable_feature_keys(), reserved)
        if errors:
            for line in errors:
                print(line, file=sys.stderr)
            return 1
        # Only when a name was *typed*. Omitting --features grandfathers every
        # sellable key including the reserved ones, and that path is accepted
        # deliberately (issue 013, D2) — warning there would fire on every
        # default sale and teach the reader to ignore the warning.
        for line in _reserved_warning(features, reserved):
            print(line, file=sys.stderr)

    # Gated on presence (`is not None`), not truthiness — `--models ""` and
    # `--brands ""` must be hard errors, exactly the `--features ""` trap
    # issue 014 records for the sibling flag (D13). Do NOT change the
    # `--features` branch above to match: 014 is a separate open issue and
    # its own test asserts the current (different) behaviour stays put.
    models: list[str] | None = None
    if args.models is not None or args.brands is not None:
        resolved, errors = _resolve_models(args.models, args.brands)
        if errors:
            for line in errors:
                print(line, file=sys.stderr)
            return 1
        models = resolved

    payload = build_payload(
        customer=args.customer,
        machine_id=machine_id,
        mode=args.mode,
        expires_at=expires_at,
        max_meters=args.max_meters,
        features=features,
        models=models,
    )
    code = sign_payload(private_path.read_bytes(), payload)

    print(f"Customer   : {payload['customer']}", file=sys.stderr)
    print(f"Machine ID : {payload['machine_id']}", file=sys.stderr)
    print(f"Mode       : {payload['mode']}", file=sys.stderr)
    print(f"Expires    : {payload['expires_at'] or 'never'}", file=sys.stderr)
    print(f"Max meters : {payload['max_meters'] if payload['max_meters'] is not None else 'unlimited'}", file=sys.stderr)
    print(f"Models     : {models_summary_text(payload['models'])}", file=sys.stderr)
    print("\nACTIVATION CODE (send this single line to the customer):\n", file=sys.stderr)
    print(code)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(code, encoding="utf-8")
        print(f"\nAlso written to {out_path}", file=sys.stderr)
    return 0


def cmd_sign_meter(args: argparse.Namespace) -> int:
    """Sign a Meter Activation Code for one meter on one machine (ADR 0019)."""
    private_path = Path(args.private_key)
    if not private_path.exists():
        print(f"ERROR: Private key not found at {private_path}.", file=sys.stderr)
        print("       Run: python tools/arichds_vendor.py keygen", file=sys.stderr)
        return 1

    meter_serial = args.meter_serial.strip()
    if not meter_serial:
        print("ERROR: --meter-serial must not be empty or whitespace-only.", file=sys.stderr)
        return 1
    if len(meter_serial) > 64:
        print("ERROR: --meter-serial must be 64 characters or fewer after stripping.", file=sys.stderr)
        return 1

    machine_id = args.machine_id.strip().lower()
    if len(machine_id) != 64 or not all(c in "0123456789abcdef" for c in machine_id):
        print("ERROR: --machine-id must be the 64-character hex Machine ID shown on the", file=sys.stderr)
        print("       Activation page (or from `arichds_vendor.py fingerprint`).", file=sys.stderr)
        return 1

    payload = build_meter_payload(meter_serial=meter_serial, machine_id=machine_id)
    code = sign_payload(private_path.read_bytes(), payload)

    print(f"Meter Serial : {payload['meter_serial']}", file=sys.stderr)
    print(f"Machine ID   : {payload['machine_id']}", file=sys.stderr)
    print("\nMETER ACTIVATION CODE (send this single line to the customer):\n", file=sys.stderr)
    print(code)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(code, encoding="utf-8")
        print(f"\nAlso written to {out_path}", file=sys.stderr)
    return 0


def cmd_fingerprint(args: argparse.Namespace) -> int:
    """Print this machine's Machine ID (vendor-side testing)."""
    sys.path.insert(0, str(REPO_ROOT / "app" / "src"))
    from arichds.licensing.fingerprint import FingerprintError, machine_id

    try:
        print(machine_id())
    except FingerprintError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        prog="arichds_vendor",
        description="ARICHDS vendor tool — generate signing keys and issue Activation Codes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/arichds_vendor.py keygen
  python tools/arichds_vendor.py fingerprint
  python tools/arichds_vendor.py sign --customer "Acme Co" --machine-id <64-hex>
  python tools/arichds_vendor.py sign --customer "Acme Co" --machine-id <64-hex> \\
      --mode leased --lease-days 45 --max-meters 30
  python tools/arichds_vendor.py sign-meter --meter-serial <serial> --machine-id <64-hex>
""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    keygen = sub.add_parser("keygen", help="Generate a new Ed25519 signing keypair.")
    keygen.add_argument("--private-out", default=str(DEFAULT_PRIVATE_KEY_PATH), help="Private key output path.")
    keygen.add_argument("--public-out", default=str(DEFAULT_PUBLIC_KEY_PATH), help="Public key output path.")
    keygen.add_argument(
        "--no-bundle",
        action="store_true",
        help="Do not copy the public key into the app package.",
    )
    keygen.add_argument("--force", action="store_true", help="Overwrite an existing private key.")
    keygen.set_defaults(func=cmd_keygen)

    sign = sub.add_parser("sign", help="Sign an Activation Code for one machine.")
    sign.add_argument("--customer", required=True, help="Customer or company name recorded in the license.")
    sign.add_argument("--machine-id", required=True, help="The customer's 64-hex Machine ID.")
    sign.add_argument("--mode", choices=["offline", "leased"], default="offline", help="License mode.")
    sign.add_argument("--expires", default=None, help="Explicit expiry date, YYYY-MM-DD.")
    sign.add_argument(
        "--lease-days",
        type=int,
        default=DEFAULT_LEASE_DAYS,
        help=f"Lease length when --mode leased and no --expires (default {DEFAULT_LEASE_DAYS}).",
    )
    sign.add_argument("--max-meters", type=int, default=None, help="Device quota. Omit for unlimited.")
    sign.add_argument(
        "--features",
        default=None,
        help="Comma-separated licensed feature names, validated against the sellable set "
        "(an unrecognised name is refused, not signed). Some sellable names are reserved "
        "and not for sale yet: naming one warns but still signs. Omit for every sellable "
        "feature.",
    )
    sign.add_argument(
        "--models",
        default=None,
        help="Comma-separated licensed meter model keys, validated against the app's own "
        "catalog (an unrecognised name is refused, not signed). May be combined with "
        "--brands; the result is the union, deduplicated and sorted. Omitting both "
        "--models and --brands grandfathers every catalogued model.",
    )
    sign.add_argument(
        "--brands",
        default=None,
        help="Comma-separated meter brand names, expanded to every catalogued model of "
        "that brand, validated against the app's own catalog. May be combined with "
        "--models. Omitting both --models and --brands grandfathers every catalogued "
        "model.",
    )
    sign.add_argument("--private-key", default=str(DEFAULT_PRIVATE_KEY_PATH), help="Signing private key path.")
    sign.add_argument("--out", default=None, help="Also write the code to this file.")
    sign.set_defaults(func=cmd_sign)

    sign_meter = sub.add_parser("sign-meter", help="Sign a Meter Activation Code for one meter on one machine.")
    sign_meter.add_argument("--meter-serial", required=True, help="The Meter Serial read off the meter.")
    sign_meter.add_argument("--machine-id", required=True, help="The customer's 64-hex Machine ID.")
    sign_meter.add_argument("--private-key", default=str(DEFAULT_PRIVATE_KEY_PATH), help="Signing private key path.")
    sign_meter.add_argument("--out", default=None, help="Also write the code to this file.")
    sign_meter.set_defaults(func=cmd_sign_meter)

    fingerprint = sub.add_parser("fingerprint", help="Print this machine's Machine ID.")
    fingerprint.set_defaults(func=cmd_fingerprint)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
