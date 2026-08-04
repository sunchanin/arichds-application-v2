# Lib notes — M2 Auth (PyJWT + bcrypt)

> Current-API digest per CLAUDE.md's per-module docs-digest rule. Sources: pypi.org project
> pages, fetched 2026-08-04. **After `pip install`, verify against the installed version**
> (`pip show pyjwt bcrypt`) — installed source wins over this note.

## Decision: PyJWT (not python-jose)

v1 used `python-jose` (`from jose import jwt`). v2 uses **PyJWT** — jose is effectively
unmaintained with known CVE history; PyJWT is the maintained standard. API differences are
minor for our use:

- **PyJWT 2.13.0** (2026-05-21) · supports Python 3.9–3.14 ✓ (we run 3.14)
- `jwt.encode(payload: dict, key, algorithm="HS256") -> str`
- `jwt.decode(token, key, algorithms=["HS256"])` — **`algorithms` is plural and required**
  (omitting it is the classic PyJWT pitfall; jose called it `algorithms` too, low porting risk)
- Expiry: put `exp` (unix ts / datetime) in the payload; `decode` raises
  `jwt.ExpiredSignatureError` (jose: `jose.ExpiredSignatureError` — rename on port)
- Base error: `jwt.InvalidTokenError` (jose: `JWTError`)

## bcrypt 5.0.0 — one breaking change that affects our schema

- **bcrypt 5.0.0** (2025-09) · CPython 3.8–3.14 ✓ · direct API, no passlib wrapper needed:
  - `bcrypt.hashpw(password: bytes, bcrypt.gensalt())` (gensalt default 12 rounds — fine)
  - `bcrypt.checkpw(password: bytes, hashed: bytes) -> bool`
- ⚠️ **Passwords > 72 bytes now raise `ValueError`** (previously silently truncated).
  → Pydantic schema must enforce `min_length=8, max_length=72` on password fields, so the
  API returns a clean 422 instead of a 500 from the hash call. Constant-time dummy-hash
  path (v1 INV-AUTH-02) must use a dummy that also respects this.
- Encode passwords to UTF-8 bytes before hashing; store the hash as `str` (utf-8 decode).

## Carried v1 mechanics (read the originals when porting)

`cewe/cewe-worker/src/auth/` — `auth_service.py` (constant-time login INV-AUTH-02/03,
token-hash storage INV-AUTH-04, revoke-on-password-change), `router_auth.py`
(`check-setup`/`setup` one-shot bootstrap), `router_users.py` (admin-only guards).
Port the mechanics; rename jose→PyJWT per above.
