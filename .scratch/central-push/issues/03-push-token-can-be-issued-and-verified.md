# 03: A Push Token can be issued and verified

**What to build:** The vendor can issue a Push Token for one machine with the same signing key
used for Activation Codes, and the application can verify one. A Push Token can never pass as an
Activation Code or a Meter Activation Code, and neither of those can pass as a Push Token.
Decision record: ADR 0024; spec: `.scratch/central-push/spec.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

> **Never run `arichds_vendor.py keygen`, for any reason.** A new keypair invalidates every
> Activation Code and Meter Activation Code ever issued. If a key looks missing, find it; never
> generate one. Tests use an ephemeral keypair and never read the real private key.

- [ ] The vendor tool gains `sign-push --machine-id <64-hex>`, which prints exactly one line: a
      JWT signed `EdDSA` with the existing Ed25519 private key, carrying `sub` (the Machine ID),
      `product` = `arichds-push`, `v` = 1 and `iat`, and **no** `exp`
- [ ] `sign-push` loads the private key exactly as `sign` does, and never generates one
- [ ] A malformed Machine ID is refused with a non-zero exit, and nothing is printed to stdout
- [ ] The application gains a Push Token verifier. It accepts a valid token and returns its Machine
      ID. It refuses, with a distinct reason for each: a bad signature, a token signed by another
      key, a wrong `product`, an unsupported `v`, anything that is not a JWT, and an Activation Code
- [ ] **Domain separation, both ways**: the Activation Code verifier and the Meter Activation Code
      verifier each refuse a Push Token, and the Push Token verifier refuses both of them
- [ ] **Round trip through the real tool**: a token printed by `sign-push`, run through the
      existing `vendor_cli` fixture, is accepted by the application verifier for that Machine ID
- [ ] `sign-push`'s help text and the vendor tool's module docstring describe the command
- [ ] No new dependency: PyJWT and `cryptography` are already pinned
- [ ] Every test above is mutation-probed: reverting the behaviour it names turns it red
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/`
