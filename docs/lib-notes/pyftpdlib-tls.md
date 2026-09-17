# pyftpdlib — API digest (v2.2.0, released 2026-02-07, fetched 2026-09-17)

> **Installed and measured** (ticket 05, 2026-09-17): `pyftpdlib` 2.2.0, `PyOpenSSL` 26.4.0,
> `pyasynchat`/`pyasyncore` 1.0.5 (resolved automatically via pyftpdlib's own conditional
> `requires_dist` for Python 3.12+ — nothing declared for them explicitly), all dev-only in
> `app/.venv` — never a runtime dependency. The production client is the standard library's
> `ftplib.FTP_TLS` (§5-§7 below). Every exception in §6's table was re-measured against a real
> in-process `pyftpdlib` `TLS_FTPHandler` and matched exactly; the one correction ticket 04's own
> paramiko sibling forced (an unmeasured exception-behaviour claim shipping a blocker) did **not**
> repeat there. **§3's `passive_ports` claim was wrong, though, and was corrected in round 1** of
> this ticket's own review (reviewer finding, problem 5) — see §3 itself for the correction; the
> lesson generalises: a claim about *addressing* is not the same claim as one about *exception
> classes*, and getting the latter right measured did not make the former right by association.
> Sourced from Context7 (`/websites/pyftpdlib_readthedocs_io_en`) and, where Context7's index
> didn't surface a file whole, `github.com/giampaolo/pyftpdlib` via `gh api`.

## Why it is in the tree

ADR 0025 (decision 1: FTPS) and
`.scratch/file-upload/issues/05-files-reach-an-ftps-server-over-explicit-tls.md` — the FTPS
transport is standard-library-only in production; pyftpdlib exists solely so the "Transport
tests against a `pyftpdlib` TLS server **in-process**" (ticket 05's own criterion) can run
without a real FTPS host.

---

## 1. Server setup — `FTPServer` + `TLS_FTPHandler`

```python
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import TLS_FTPHandler
from pyftpdlib.servers import FTPServer

authorizer = DummyAuthorizer()
authorizer.add_user("user", "12345", homedir, perm="elradfmwMT")

handler = TLS_FTPHandler
handler.certfile = "/path/to/cert.pem"
handler.keyfile = "/path/to/key.pem"     # may be omitted if certfile already holds the key
handler.authorizer = authorizer

server = FTPServer(("127.0.0.1", 0), handler)   # port 0 = ephemeral, §3
server.serve_forever()
```

`TLS_FTPHandler` **requires `pyOpenSSL`** — confirmed on PyPI: the `ssl` extra
(`pyftpdlib[ssl]`) pulls `PyOpenSSL`; it is not a hard dependency of the base install. The dev
dependency must be **`pyftpdlib[ssl]`**, or `PyOpenSSL` listed alongside it.

### `TLS_FTPHandler` configurable attributes (class-level, set before instantiating `FTPServer`)

| Attribute | Meaning | Default |
|---|---|---|
| `certfile` | PEM certificate path | `None` — **required**; `get_ssl_context()` raises `ValueError` if unset |
| `keyfile` | PEM private-key path; omit if `certfile` holds both | `None` |
| `ssl_protocol` | OpenSSL protocol constant | `SSL.TLS_SERVER_METHOD` |
| `ssl_options` | OpenSSL context options | `SSL.OP_NO_SSLv2 \| SSL.OP_NO_SSLv3` (+`OP_NO_COMPRESSION` where available) |
| `ssl_context` | pre-built `SSL.Context`, bypasses the two above | `None` |
| `tls_control_required` | refuse commands before `AUTH TLS` | `False` |
| `tls_data_required` | refuse data-channel commands before `PROT P` | `False` |

Confirmed by reading `pyftpdlib/handlers/ftps/control.py::TLS_FTPHandler` directly. **The
package layout changed**: `handlers.py` is now a package (`pyftpdlib/handlers/`), and
`TLS_FTPHandler` lives at `pyftpdlib/handlers/ftps/control.py` — the public import
`from pyftpdlib.handlers import TLS_FTPHandler` is unaffected; don't look for a flat file.

### `DummyAuthorizer`

```python
authorizer.add_user(username, password, homedir, perm="elradfmwMT")
```

`perm` is a string of letters, not a bitmask: `e`=cwd, `l`=list, `r`=retrieve; `a`=append,
`d`=delete, `f`=rename, `m`=mkdir, `w`=store, `M`=chmod, `T`=mtime. Needs at least `elradfmw` to
exercise `STOR`/`MKD`/`LIST`/`CWD`. `validate_authentication` raises
`pyftpdlib.exceptions.AuthenticationFailed` for a wrong username/password (not a bool — changed
in 1.0.0), driving the "wrong password surfaces as the transport error class" test.

---

## 2. `FTPServer` construction and lifecycle

```python
server = FTPServer(("127.0.0.1", 0), TLS_FTPHandler)
server.max_cons, server.max_cons_per_ip = 256, 5
```

- `FTPServer(address_or_socket, handler, ioloop=None, backlog=100)` — address tuple or a
  pre-existing `socket.socket`.
- **`serve_forever(timeout=None, blocking=True, handle_exit=True, worker_processes=1)`** — runs
  the asyncore-style IO loop; run it on a background thread for a test:
  ```python
  thread = threading.Thread(target=server.serve_forever, daemon=True)
  thread.start()
  ...
  server.close_all()      # disconnects all clients, stops the loop, blocks until stopped
  thread.join(timeout=5)
  ```
  `close()` (no `_all`) only stops accepting *new* connections — existing clients stay connected;
  not what teardown wants. `close_all()` is the documented stop-everything call.
- **`ThreadedFTPServer`** spawns a thread per connection — only needed if a handler blocks; plain
  `FTPServer` on one background thread is enough for a single-client fixture, matching this
  repo's `fake_central_push_receiver.py` shape.

---

## 3. Ephemeral port

`("127.0.0.1", 0)` — the OS picks a free port. Read it back before starting the loop:

```python
port = server.socket.getsockname()[1]
```

**Confirmed** (ticket 05, against the installed 2.2.0): `FTPServer.socket` is a real attribute —
`server.socket.getsockname()[1]` works exactly as the tutorial idiom implies, used in
`tests/fake_ftps_server.py` and this ticket's own measurement scripts with no surprises.

**Corrected, ticket 05 round 1 (reviewer finding, problem 5).** `passive_ports` narrows only the
**port** PASV offers — the *address* PASV advertises is always the control connection's own local
address (`pyftpdlib/handlers/ftp/dispatchers.py:45`, `local_ip =
self.cmd_channel.socket.getsockname()[0]`, used building the `227` reply), which is already
`127.0.0.1` the moment the server itself binds `("127.0.0.1", 0)`. A loopback-only test needs no
`passive_ports` pin at all — there was never a real interface IP to advertise in the first place,
and `masquerade_address` (NAT-only) is not needed for the same reason. `tests/fake_ftps_server.py`
carried a fixed `passive_ports = range(60200, 60400)` on the strength of this section's original
(wrong) claim; combined with pyftpdlib's own `set_reuse_addr()` before each bind
(`dispatchers.py:63-90`), a fixed range made a 16-worker `pytest -n auto` run strictly worse on
Windows than the default — the fixture now leaves it unset (`None`, kernel-picked, self-healing on
`EADDRINUSE`).

---

## 4. Self-signed certificate for the test — `cryptography` recipe

Already shipped (`cryptography` 50.0.0 confirmed installed). Exact fluent API, via Context7
(`/pyca/cryptography`):

```python
import datetime, ipaddress
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
now = datetime.datetime.now(datetime.timezone.utc)

cert = (
    x509.CertificateBuilder()
    .subject_name(name).issuer_name(name)          # self-signed: issuer == subject
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - datetime.timedelta(days=1))
    .not_valid_after(now + datetime.timedelta(days=1))
    .add_extension(
        x509.SubjectAlternativeName(
            [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
        ),
        critical=False,
    )
    .sign(key, hashes.SHA256())
)
cert_pem = cert.public_bytes(serialization.Encoding.PEM)
key_pem = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),   # throwaway test key
)
# write cert_pem / key_pem to temp files for handler.certfile / handler.keyfile
```

`x509.IPAddress(...)` needs an `ipaddress` object, not a bare string — a string SAN entry becomes
a `DNSName`, and the test client connects to the literal IP `127.0.0.1`, so hostname checking
needs the IP form present (§7).

---

## 5. Client side — standard library only (`ftplib.FTP_TLS`)

Confirmed against the Python 3.14 `ftplib` docs (this project's floor is 3.13+, dev machine
3.14.6):

```python
ftplib.FTP_TLS(host='', user='', passwd='', acct='', *, context=None,
                timeout=None, source_address=None, encoding='utf-8')
```

**`keyfile`/`certfile` constructor kwargs were removed in Python 3.12** — only `context=`
remains. Nothing to port around here since the floor is 3.13+; just never pass `keyfile=`/
`certfile=` to `FTP_TLS(...)`.

```python
context = ssl.create_default_context()            # system trust store, hostname checking ON
ftps = ftplib.FTP_TLS(context=context, timeout=connect_timeout)
ftps.connect(host, port, timeout=connect_timeout)
ftps.login(user=username, passwd=password)          # AUTH TLS happens inside login()
ftps.prot_p()                                        # protect the data channel
ftps.set_pasv(True)                                  # passive mode, required by spec.md
with open(local_path, "rb") as fh:
    ftps.storbinary(f"STOR {remote_name}", fh)
ftps.retrbinary(f"RETR {remote_name}", callback)
ftps.mkd(remote_dir)                                 # NOT idempotent — §6
ftps.cwd(remote_dir)
names = ftps.nlst()
```

`login(user='anonymous', passwd='', acct='', secure=True)` issues `AUTH TLS` automatically before
sending credentials when `secure=True` (the default) — no separate manual `auth()` call needed;
`auth()`/`ccc()` exist for upgrade-then-defer-login or revert-to-plaintext use cases, unused here.

---

## 6. `mkd` and the exception hierarchy

- **`mkd` on an existing directory is refused, not a no-op** — a compliant server answers `550`,
  which `ftplib` raises as `error_perm`. Same shape as paramiko's SFTP `mkdir` (paramiko digest
  §3) — neither protocol treats "create if missing" as built in. `try: ftps.mkd(...) except
  ftplib.error_perm: pass`, or check existence first, rather than assume it's safe unconditionally.
- **`ftplib` hierarchy**, all under `ftplib.Error` (`Exception`, not `OSError`): `error_reply`
  (unexpected reply), `error_temp` (`4xx`), `error_perm` (`5xx` — bad credentials, `550` for a
  missing/conflicting path), `error_proto` (reply doesn't start with a digit).
  `ftplib.all_errors = (Error, OSError, EOFError, ssl.SSLError)` is the module's own
  "catch anything" tuple.

| Failure | What `ftplib`/`ssl` raises |
|---|---|
| refused / unreachable | `ConnectionRefusedError`/`OSError` from `connect()` |
| timed out | `socket.timeout` (`TimeoutError` on 3.10+) — pass `timeout=` to `connect()` itself, not just the constructor |
| untrusted/self-signed cert | `ssl.SSLCertVerificationError` (⊂ `ssl.SSLError` ⊂ `OSError`), raised during the `AUTH TLS` handshake |
| bad credentials | `ftplib.error_perm` (`"530 …"`) |
| missing/conflicting remote directory | `ftplib.error_perm` (`"550 …"`) |

---

## 7. Certificate verification, and what does NOT exist

- **`ssl.create_default_context()`** gives system trust store + hostname checking
  (`CERT_REQUIRED`) — a self-signed cert fails with `ssl.SSLCertVerificationError`, the
  "failure, not a prompt" spec.md asks for.
- **The test trusts its own cert without touching the machine trust store** via
  `context.load_verify_locations(cafile=cert_pem_path)` on a normally-built context (or
  `ssl.create_default_context(cafile=cert_pem_path)` in one call) — the "trusted" half of ticket
  05's two transport tests.
- **No TLS session reuse in `ftplib`, in any version checked — the brief's premise about a
  Python 3.12+ change here could not be confirmed, and I looked specifically.** I read
  `Lib/ftplib.py` directly off CPython's `3.12`, `3.13`, `3.14`, and default branches (`gh api
  repos/python/cpython/contents/Lib/ftplib.py?ref=<branch>`) and grepped every occurrence of
  `session` — **zero** in all four. `FTP_TLS.ntransfercmd()` wraps the data socket with
  `self.context.wrap_socket(conn, server_hostname=self.host)` and nothing else; no
  `session=self.sock.session` anywhere. pyftpdlib's TLS handler
  (`pyftpdlib/handlers/ftps/{control,data}.py`) shows no session-reuse enforcement either — it
  builds a plain pyOpenSSL `SSL.Context` and doesn't inspect resumption. **Treat the "3.12+
  session reuse" claim as false for this pairing.** It names a real, separately-documented FTPS
  interoperability hazard (some servers refuse a data-channel handshake that isn't a resumption
  of the control session, as an anti-hijack measure) whose usual workaround is a hand-rolled
  `FTP_TLS` subclass passing `session=` into `wrap_socket` — but neither side of this specific
  pairing needs or implements it. Do not build for a requirement that isn't there.
- **Implicit FTPS (port 990) is not offered by `ftplib`.** `FTP_TLS` always does the *explicit*
  `AUTH TLS` upgrade over a plaintext connect; nothing special-cases port 990. Matches spec.md
  and ticket 05 verbatim — there is nothing to build because the stdlib has nothing to call.

---

## Gotchas

- **`TLS_FTPHandler` needs `pyOpenSSL`** — install `pyftpdlib[ssl]`, or the fixture fails at
  `get_ssl_context()` with a message that doesn't obviously say "missing extra".
- **pyftpdlib 2.x needs `pyasynchat`/`pyasyncore` on Python 3.12+** (stdlib `asynchat`/`asyncore`
  were removed) — confirmed via PyPI's conditional `requires_dist` for 2.2.0. If a lockfile ever
  pins pyftpdlib without letting these resolve, the import fails at
  `from pyftpdlib.servers import FTPServer` with `ModuleNotFoundError: asyncore`, not anything
  FTPS-specific.
- **`close()` ≠ `close_all()`** — only `close_all()` disconnects live test clients; `close()`
  alone hangs a thread-join teardown.
- **`mkd` is not idempotent** (§6) — same shape as paramiko's SFTP `mkdir`; check-then-create.
- **`x509.IPAddress` needs an `ipaddress` object**, not a string (§4) — a bare string becomes a
  `DNSName`, and the "trusted" test connecting to a literal IP will fail hostname checking.
- **Do not build TLS session-reuse handling** (§7) — verified absent from both sides of this
  pairing; speculative code for a hazard neither party's source exhibits.
- **`getpeercert()` only works after `auth()`, not after `connect()`** — new, measured in ticket
  05: `ftps.sock` is a bare `socket.socket` until `auth()` wraps it in `ssl.SSLSocket`;
  `ftps.sock.getpeercert()` right after `connect()` raises `AttributeError` ("'socket' object has
  no attribute 'getpeercert'"). Call `auth()` explicitly first (§5's own note that `login()` does
  this internally when `secure=True`, but that is too late to read the certificate before sending
  credentials), then read the certificate off `ftps.sock`.
- **`SIZE` is refused in ASCII mode** — new, measured in ticket 05: `ftplib`'s default transfer
  type is ASCII, and a real server (pyftpdlib included) answers `550 SIZE not allowed in ASCII
  mode` for `ftps.size(...)` before any `TYPE I` has been sent — even though `storbinary`/
  `retrbinary` each switch to `TYPE I` internally per call, that switch does not outlive the call.
  Send `ftps.voidcmd("TYPE I")` once, right after login, before relying on `size()` to check
  whether a file exists.
- **`ftplib.FTP.nlst()`/`retrlines()` send `TYPE A` unconditionally** — new, measured in ticket 05
  round 1 (reviewer finding, problem 1): `nlst()` is implemented as `retrlines('NLST ...')`, and
  `retrlines()` always does `self.sendcmd('TYPE A')` before transferring, with **no restore
  afterward**. A `SIZE` call right after an `NLST` fails the same way an `NLST` before any `TYPE I`
  does (previous bullet) — re-send `ftps.voidcmd("TYPE I")` after any `NLST`/`LIST`/`RETR` in
  ASCII mode, before the next `SIZE`/`STOR`/`RETR` that needs binary.
- **An accepted `socket.socket` with no held reference is garbage-collected (and closed)
  almost immediately** — new, measured in ticket 05 round 1 while building a stalling-server test
  fixture: `sock.accept()` called for its side effect alone, with the returned connection object
  never assigned to anything, sends the client an instant `EOFError` rather than the intended
  stall — a test fixture that wants to hold a connection open and silent must keep a live reference
  to it (a list, an instance attribute) for as long as it wants the client to keep waiting.

---

## Sources

- Context7 `/websites/pyftpdlib_readthedocs_io_en` — `TLS_FTPHandler` tutorial + attribute table,
  `DummyAuthorizer.add_user`/`validate_authentication`, `FTPServer` constructor,
  `serve_forever`/`close`/`close_all`, `ThreadedFTPServer`, `masquerade_address`/`passive_ports`.
- `github.com/giampaolo/pyftpdlib` (`master`) via `gh api repos/giampaolo/pyftpdlib/contents/…` —
  confirmed package layout (`pyftpdlib/handlers/ftps/control.py`) and `TLS_FTPHandler` defaults /
  `get_ssl_context()`.
- `pypi.org/pypi/pyftpdlib/json` and `.../2.2.0/json` — version `2.2.0`, uploaded 2026-02-07;
  `requires_dist` (`ssl` extra → `PyOpenSSL`; `python_version>=3.12` → `pyasynchat`/`pyasyncore`).
- `docs.python.org/3/library/ftplib.html` (live, Python 3.14.7 docs) — `FTP_TLS` signature, the
  3.12 keyfile/certfile removal, no implicit-FTPS confirmation.
- `github.com/python/cpython` `Lib/ftplib.py` off `3.12`/`3.13`/`3.14`/default branches via
  `gh api repos/python/cpython/contents/Lib/ftplib.py?ref=<branch>` — zero `session` occurrences
  in any; used to correct the TLS-session-reuse premise in §7.
- Context7 `/pyca/cryptography` — `x509.CertificateBuilder` fluent API,
  `rsa.generate_private_key`, `SubjectAlternativeName`.
- This repo's `app/.venv` — confirmed `cryptography` 50.0.0 installed; `pyftpdlib` 2.2.0 /
  `PyOpenSSL` 26.4.0 / `pyasynchat` 1.0.5 / `pyasyncore` 1.0.5 installed and measured 2026-09-17
  (ticket 05): every row of §6's exception table re-run against a real in-process
  `TLS_FTPHandler` and confirmed unchanged; `getpeercert()`-after-`auth()` and the ASCII-mode
  `SIZE` refusal (both in Gotchas above) were found during this pass and were not in the
  original digest.
