---
description: Issue a Meter Activation Code for one meter on one customer machine (ADR 0019).
argument-hint: <meter-serial> [machine-id] [extra sign-meter flags...]
allowed-tools: Bash, Read, Glob
model: sonnet
---

Issue a Meter Activation Code via the vendor CLI (`tools/arichds_vendor.py sign-meter`). `$1` is the Meter Serial (required — read off the meter itself via `POST /test-connection`, ADR 0005; there is no local fallback for it). `$2`, if present and not itself a flag, is the 64-hex Machine ID; if omitted, fingerprint **this** machine for vendor-side self-testing, same as `/activate` Step 1. Any remaining arguments pass through to `sign-meter` verbatim.

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

Use its stdout (one line, 64 hex chars) as the machine ID — this issues a code for *this* machine, the one running the command.

If a machine ID **was** supplied, use it as given.

**Validate before signing**, regardless of source: it must be exactly 64 characters, all lowercase-or-uppercase hex (`0-9a-f`, case-insensitive). If it doesn't match — e.g. it looks truncated, has stray whitespace, or contains non-hex characters — stop and report clearly which check failed and the value received. Do not attempt to "fix" or pad it.

Also validate the Meter Serial (`$1`): must not be empty or whitespace-only, and must be 64 characters or fewer after stripping (the `devices.meter_serial` column ceiling). If it fails either check, stop and report which check failed.

## Step 2 — Pre-check: private key present

`tools/.arichds_private_key.pem` must exist (default `--private-key` path used by `sign-meter`). If it's missing:

- Explain that `keygen` generates it:
  ```
  app\.venv\Scripts\python.exe tools\arichds_vendor.py keygen
  ```
- **WARN loudly and stop — do not run `keygen` yourself.** Generating a *new* keypair invalidates every Activation Code and Meter Activation Code issued so far, and any exe already built bundles the *old* public key (`app/src/arichds/licensing/public_key.pem`) — codes signed with a new key won't verify against exes built with the old one. `keygen` is a once-per-vendor bootstrap act, never an automatic recovery step for a missing-key error. If the key is genuinely missing, ask the human how they want to proceed.

## Step 3 — Sign

Run from the repo root:

```powershell
app\.venv\Scripts\python.exe tools\arichds_vendor.py sign-meter --meter-serial "$1" --machine-id <resolved-id> <any extra flags passed through>
```

## Step 4 — Report

Print the full command output, making the `METER ACTIVATION CODE` block prominent (it's on stdout; the Meter Serial/Machine ID summary is on stderr — show both).

**Tell the operator where this goes.** The Add Device form's Identity card has a required Meter Activation Code field, shown on create only, right after the Meter Serial (ADR 0019, issue #42) — paste this code there before pressing Create Device. Note for the record: it is bound to this Meter Serial and Machine ID and does not expire on its own; a wrong serial, wrong machine, or unverifiable code is refused with 409 naming which.

## Never

- Never invoke bare `python`/`python3` — always the venv interpreter, repo-root-relative.
- Never run `keygen` automatically, under any error condition.
- Never commit anything (the private key must never be committed; codes/output files stay local).
