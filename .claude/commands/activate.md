---
description: Issue an Activation Code for a customer machine, defaulting to this machine's fingerprint.
argument-hint: <customer-name> [machine-id] [extra sign flags...]
allowed-tools: Bash, Read, Glob
model: sonnet
---

Issue an Activation Code via the vendor CLI (`tools/arichds_vendor.py`). `$1` is the customer name (required). `$2`, if present and not itself a flag, is the 64-hex machine ID; if omitted, fingerprint **this** machine and activate it. Any remaining arguments (`$ARGUMENTS` after the first one or two positionals — e.g. `--mode leased --lease-days 45 --max-meters 30`) pass through to `sign` verbatim.

## Step 0 — Pre-check: venv

Confirm `app\.venv\Scripts\python.exe` exists (repo-root-relative). **Always invoke the CLI through this interpreter — never bare `python` or `python3`.** `tools/arichds_vendor.py` imports `cryptography`, which lives only in `app/.venv`; running it with the system Python fails with `ModuleNotFoundError: No module named 'cryptography'`.

If the venv is missing, stop and tell the user to create it:
```powershell
cd app
py -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

## Step 1 — Resolve the machine ID

If `$1` was given but no machine ID was supplied as `$2`, run from the repo root:

```powershell
app\.venv\Scripts\python.exe tools\arichds_vendor.py fingerprint
```

Use its stdout (one line, 64 hex chars) as the machine ID — this activates *this* machine, the one running the command.

If a machine ID **was** supplied, use it as given.

**Validate before signing**, regardless of source: it must be exactly 64 characters, all lowercase-or-uppercase hex (`0-9a-f`, case-insensitive). If it doesn't match — e.g. it looks truncated, has stray whitespace, or contains non-hex characters — stop and report clearly which check failed and the value received. Do not attempt to "fix" or pad it.

## Step 2 — Pre-check: private key present

`tools/.arichds_private_key.pem` must exist (default `--private-key` path used by `sign`). If it's missing:

- Explain that `keygen` generates it:
  ```
  app\.venv\Scripts\python.exe tools\arichds_vendor.py keygen
  ```
- **WARN loudly and stop — do not run `keygen` yourself.** Generating a *new* keypair invalidates every Activation Code issued so far, and any exe already built bundles the *old* public key (`app/src/arichds/licensing/public_key.pem`) — codes signed with a new key won't verify against exes built with the old one. `keygen` is a once-per-vendor bootstrap act, never an automatic recovery step for a missing-key error. If the key is genuinely missing, ask the human how they want to proceed.

## Step 3 — Sign

Run from the repo root:

```powershell
app\.venv\Scripts\python.exe tools\arichds_vendor.py sign --customer "$1" --machine-id <resolved-id> <any extra flags passed through>
```

(e.g. `--mode leased --lease-days 45 --max-meters 30` if the caller supplied them.)

## Step 4 — Report

Print the full command output, making the `ACTIVATION CODE` block prominent (it's on stdout; the customer/machine/mode/expiry summary is on stderr — show both). Remind the user:

- Paste the one-line code into the machine's **Activation** page (first-run / Limited Mode screen).
- It applies **live, with no service restart** (ADR 0001) — the poller starts and the Monitor page appears immediately on a valid code.

## Never

- Never invoke bare `python`/`python3` — always the venv interpreter, repo-root-relative.
- Never run `keygen` automatically, under any error condition.
- Never commit anything (the private key must never be committed; codes/output files stay local).
