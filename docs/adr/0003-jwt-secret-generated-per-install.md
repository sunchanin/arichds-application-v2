# The JWT signing secret is generated per install and persisted — not required from the environment

Status: accepted (2026-08-05, M2-1 implementation)

Reverses: v1 (`cewe`) `cewe-worker/src/auth/database.py` — `get_jwt_secret()` read
`AUTH_JWT_SECRET` from the environment and raised `ConfigurationError` when it was missing.

## What v1 did

v1 refused to start without an operator-supplied secret:

```python
secret = os.getenv("AUTH_JWT_SECRET", "").strip()
if not secret:
    raise ConfigurationError("AUTH_JWT_SECRET environment variable is not set. …")
```

That works when a human writes a `.env` before `docker compose up`, which is how v1 was
deployed. It does not survive our delivery model.

## Why it cannot be carried over

ARICHDS v2 installs from an Inno Setup `setup.exe` onto a customer's Windows machine and runs
as an NSSM-wrapped service (SPEC §3.1). The installer has nowhere to inject a per-machine
secret, and the stated goal is "install in under 10 minutes with no questions about the
database" — "now open a text editor and paste a random string" is exactly the friction that
goal rules out.

The obvious shortcut is worse: generating a fresh secret per process would invalidate every
Access Token whenever the service restarts, and NSSM is configured to restart on exit. Every
crash would silently sign every operator out mid-shift.

## Decision

`arichds.auth.security.get_jwt_secret()` resolves in this order:

1. `ARICHDS_JWT_SECRET` if set — the escape hatch for an operator who wants to control it.
2. `%DATA_DIR%\secret\jwt_secret.key` if it exists.
3. Otherwise generate `secrets.token_urlsafe(64)`, write it atomically (temp file +
   `os.replace`, so a half-written file can never lock everyone out), and use it.

The file is read **per call**, never cached in an `lru_cache` or a module global. It sits on
the login and token-verification paths only, where one bcrypt verification dominates the cost
of one small file read — and caching process-lifetime state derived from disk is the exact
pattern ADR 0001 forbids for license state, for the same reason: it makes the running process
disagree with the filesystem.

## Consequences

- **Deleting `jwt_secret.key` is the rotation mechanism.** Every issued Access Token stops
  verifying immediately and every user must sign in again. There is no other rotation
  command, and none is needed for a single-machine install.
- The file must be treated as a credential in backups and support bundles. It lives under
  `%ProgramData%\ARICHDS\secret\`, which the installer creates alongside the database and
  license, and it is never logged (the credential redaction filter already masks
  `secret=` and `*_key=`).
- Setting `ARICHDS_JWT_SECRET` on a machine that already has a key file silently supersedes
  it — the same "every issued token stops verifying" effect, which is intended.
