# paramiko — API digest (v5.0.0, released 2026-05-09, fetched 2026-09-17)

> Not installed in `app/.venv` yet. Signatures read from paramiko's own source
> (`github.com/paramiko/paramiko`, `main` = 5.0.0) via Context7 (`/paramiko/paramiko`),
> cross-checked with `gh api repos/paramiko/paramiko/contents/…` where Context7's index didn't
> surface a file whole. **After `pip install`, verify against the installed version**
> (`pip show paramiko`) — installed source wins, per this repo's standing rule
> (`docs/lib-notes/m2-auth.md`).

## Why it is in the tree

ADR 0025 (decision 1: SFTP) and
`.scratch/file-upload/issues/04-files-reach-an-sftp-server-with-the-host-key-pinned.md` —
paramiko is **the one runtime dependency** the File Upload Destination adds; FTPS and HTTPS stay
on the standard library.

---

## 1. `Transport` vs `SSHClient` — pinning a host key ourselves

`SSHClient` is `known_hosts`-shaped: a `MissingHostKeyPolicy` decides what to do with an unknown
hostname, and its **default is `RejectPolicy`** (`SSHClient.__init__` sets
`self._policy = RejectPolicy()`, confirmed in `client.py`), which raises `SSHException` on first
contact. `AutoAddPolicy` is the demo-only opt-out the ticket forbids in production.

We store **one pinned fingerprint string** per server row, not a `known_hosts` file — so drive
`Transport` directly instead of wiring a `HostKeys` object through `SSHClient`:

```python
import socket
from paramiko import Transport

sock = socket.create_connection((host, port), timeout=connect_timeout)
sock.settimeout(connect_timeout)          # bounds banner/kex too — §5
t = Transport(sock)
t.start_client(timeout=connect_timeout)   # negotiates SSH2, no host-key check yet

server_key = t.get_remote_server_key()    # PKey — call BEFORE auth
fingerprint = server_key.fingerprint      # "SHA256:<base64, no padding>"

if pinned_fingerprint is not None and fingerprint != pinned_fingerprint:
    t.close()
    raise HostKeyMismatch()               # our own TransportError subclass
# else: first contact (Test connection reports `fingerprint` for the operator to accept)

# authenticate (§2), then SFTPClient.from_transport(t) — §3
```

### Use `PKey.fingerprint`, not manual hashing

`PKey` gained a **`fingerprint` property in 3.2** returning exactly the OpenSSH-comparable form:

```python
@property
def fingerprint(self):
    hashy = sha256(bytes(self))
    b64ed = encodebytes(hashy.digest())
    return f"{hashy.name.upper()}:{u(b64ed).strip().rstrip('=')}"
```

`server_key.fingerprint` **is** the string to store and display — not `key.get_fingerprint()`
(legacy **MD5**, raw 16 bytes, no `SHA256:` prefix) and not `get_base64()` (the whole public key).

`HostKeys` (`add(hostname, keytype, key)`, `check(...)`, `load`/`save`) backs a multi-host
`known_hosts` file — irrelevant to a one-fingerprint-per-row design; documented here only so
nobody reaches for it, or for `AutoAddPolicy`, out of habit.

---

## 2. Authentication — password or key file

```python
t.auth_password(username, password)
# — or —
from paramiko import RSAKey, Ed25519Key
key = RSAKey.from_private_key_file(key_path, password=passphrase)      # RSA
key = Ed25519Key.from_private_key_file(key_path, password=passphrase)  # Ed25519
t.auth_publickey(username, key)
```

`from_private_key_file(filename, password=None)` is a `PKey` classmethod, inherited by
`RSAKey`/`Ed25519Key`/`ECDSAKey`. 5.0.0 also ships `PKey.from_path(path, password=None)` (added
3.2; **its kwarg was renamed `passphrase` → `password` in 5.0.0**), which auto-detects the key
type — useful if the tab doesn't ask which key type was uploaded.

Read the key file **at connect time**, never at save time — spec.md: "the key file stays on this
machine" / "never enters the database". Only the path is persisted.

**Exceptions**: a wrong/missing passphrase raises `PasswordRequiredException` (⊂
`AuthenticationException` ⊂ `SSHException`); a malformed key blob raises plain `SSHException` —
both should collapse into the same "bad credentials" `TransportError`. A **missing key file**
raises stdlib `FileNotFoundError` — not a paramiko exception, needs its own `except OSError` arm
or it leaks past the wrapper.

---

## 3. `SFTPClient` — upload, write, mkdir, stat

```python
from paramiko import SFTPClient
sftp = SFTPClient.from_transport(t)                    # "sftp" subsystem channel, no shell
sftp.put(local_path, remote_path, confirm=True)         # copies by local path
sftp.putfo(file_obj, remote_path, confirm=True)          # copies an already-open file object
```

- **`from_transport(t, window_size=None, max_packet_size=None)`** — `t` must already be
  authenticated.
- **`put(localpath, remotepath, callback=None, confirm=True)`** — `remotepath` must include the
  filename. `confirm=True` (default) does a post-write `stat()` and raises `IOError` on a size
  mismatch.
- **`putfo(fl, remotepath, file_size=0, callback=None, confirm=True)`** — same contract from a
  file object; internally `sftp.open(remotepath, "wb")` + pipelined chunked copy. Use whichever
  shape suits the seam's `put_file(relative_path, local_path)` — likely `put()`.
- **`open(filename, mode="r", bufsize=-1)`** (alias `.file`) — for the manifest:
  `with sftp.open(path, "w") as f: f.write(json_bytes)`. The `"b"` mode flag is accepted but
  meaningless (SFTP is always binary on the wire); write UTF-8 bytes explicitly.
- **`mkdir(path, mode=0o777)` is NOT idempotent.** `_convert_status` (confirmed by reading
  `sftp_client.py`) only gives a real errno for two codes — `SFTP_NO_SUCH_FILE` →
  `IOError(errno.ENOENT, …)`, `SFTP_PERMISSION_DENIED` → `IOError(errno.EACCES, …)`. Every other
  server failure, including "directory already exists" on most real `sshd`s, falls into
  `raise IOError(text)` **with `errno=None`**. **Do not** write
  `except OSError as e: if e.errno == errno.EEXIST` — it will never match. `stat()` the directory
  first and skip `mkdir` if present.
- **`stat(path)`** — raises `IOError(errno.ENOENT, …)` when absent; use it to check existence
  before `mkdir`, and to answer Test connection's "does a manifest exist" question.

---

## 4. Exception hierarchy → the ticket's failure classes

All under `paramiko.ssh_exception` (read directly):

```
SSHException                          — protocol/logic errors, catch-all base
 ├─ AuthenticationException           — bad credentials
 │   ├─ PasswordRequiredException     — encrypted key needs a passphrase we lacked
 │   ├─ BadAuthenticationType / PartialAuthentication
 ├─ BadHostKeyException               — SSHClient-only path; we compare fingerprints ourselves (§1)
 ├─ ChannelException / ProxyCommandFailure / IncompatiblePeer / ConfigParseError / …
socket.error (OSError)
 └─ NoValidConnectionsError           — every address tried refused/unreachable; `.errors` dict
```

| Failure | What paramiko raises |
|---|---|
| refused / unreachable | `ConnectionRefusedError`/`OSError` from `socket.create_connection`, or `NoValidConnectionsError` |
| timed out | `socket.timeout` (`TimeoutError` on 3.10+) |
| bad credentials | `AuthenticationException` (incl. `PasswordRequiredException`) |
| host-key mismatch | not a paramiko exception — our own comparison in §1 |
| missing key file | stdlib `FileNotFoundError` |

Every case must be re-raised as `arichds.fileupload.transport.TransportError`, whose `str()` is
**the failure's class name alone** (`transport.py`'s own docstring) — key on `type(e).__name__`,
never `str(e)`, matching `centralpush.client.PushRequestError`.

---

## 5. Connect timeouts

`SSHClient.connect(..., timeout=, banner_timeout=, auth_timeout=, channel_timeout=)` offers four
separate timeouts but requires `SSHClient` (not used here, §1). Driving `Transport` directly:
`socket.create_connection((host, port), timeout=connect_timeout)` bounds TCP connect;
`sock.settimeout(connect_timeout)` before `Transport(sock)` bounds SSH2 banner/kex too (paramiko
reads off the raw socket during `start_client`); `t.start_client(timeout=connect_timeout)` is an
extra guard. Reuse the same constant the Database Destination's Test connection uses.

---

## 6. In-process SFTP server for tests

paramiko's own suite ships this at **`tests/_stub_sftp.py`** (confirmed by reading the file at
that path — older releases had it at `demos/stub_sftp.py`; the ticket's "demo `stub_sftp.py`"
phrasing describes this same file under its old location, cite the shapes below, not a stale path):

```python
from paramiko import (AUTH_SUCCESSFUL, OPEN_SUCCEEDED, SFTPAttributes, SFTPHandle,
                       SFTPServer, SFTPServerInterface, ServerInterface)

class StubServer(ServerInterface):
    def check_auth_password(self, username, password):
        return AUTH_SUCCESSFUL
    def check_channel_request(self, kind, chanid):
        return OPEN_SUCCEEDED

class StubSFTPHandle(SFTPHandle):
    def stat(self):
        try:
            return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

class StubSFTPServer(SFTPServerInterface):
    ROOT = os.getcwd()          # point at tmp_path in tests
    def _realpath(self, path):
        return self.ROOT + self.canonicalize(path)
    def open(self, path, flags, attr):
        ...  # override open/list_folder/stat/mkdir/remove similarly
```

Wiring onto a **real ephemeral port** (paramiko's own fixture uses an in-memory `LoopSocket`
pair, not a real socket; a real port matches this repo's `fake_central_push_receiver.py`
pattern):

```python
import socket, threading
from paramiko import RSAKey, Transport, SFTPServer

listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.bind(("127.0.0.1", 0)); listener.listen(1)
port = listener.getsockname()[1]

def _serve():
    conn, _ = listener.accept()
    ts = Transport(conn)
    ts.add_server_key(RSAKey.generate(2048))            # throwaway in-test host key
    ts.set_subsystem_handler("sftp", SFTPServer, StubSFTPServer)
    event = threading.Event()
    ts.start_server(event, StubServer())
    event.wait(5.0)

threading.Thread(target=_serve, daemon=True).start()
# client: socket.create_connection(("127.0.0.1", port)) -> Transport(sock) -> §1
```

`RSAKey.generate(bits)` makes a throwaway host key with no file on disk — generate a *second* one
for the "changed host key is refused" test. `add_server_key` may be called more than once.

---

## 7. PyNaCl

`pyproject.toml` on `main` (5.0.0) lists `pynacl>=1.5` as a **hard runtime dependency**, not an
`ed25519` extra — installing `paramiko` alone pulls it in; there is no `paramiko[ed25519]` to
remember. PyNaCl ships prebuilt wheels bundling libsodium (compiled `_sodium` cffi extension) —
no system libsodium needed, same "no native ext to worry about" property
`docs/lib-notes/pillow-imagedraw.md` records for Pillow.

## 8. PyInstaller hidden-import gotchas

Confirmed against this repo's installed `pyinstaller-hooks-contrib` 2026.6
(`app/.venv/Lib/site-packages/_pyinstaller_hooks_contrib/stdhooks/`): **`hook-nacl.py` already
ships** and collects PyNaCl's compiled cffi extension (`nacl/_lib/*_cffi_*`) as binaries — the
one thing that matters, since that binding is exactly what PyInstaller's static analysis misses.
**No `hook-paramiko.py` exists or is needed** — paramiko is pure Python; `cryptography`/`bcrypt`
already have their own hooks and are already bundled. **Unverified beyond inspection**: this is
"the hook exists and looks right", not "a onedir build with paramiko in it was produced and run"
— ticket 04's own acceptance criterion (record onedir size before/after a real build) is what
actually closes this.

---

## Gotchas

- **Never `AutoAddPolicy`** in production — an unpinned host key must be refused, not trusted.
- **`get_fingerprint()` ≠ `.fingerprint`** — method is legacy MD5 raw bytes; property is the
  `SHA256:…` string we want. Both exist on every `PKey`; easy to grab the wrong one.
- **`PKey.from_path`'s kwarg is `password`, not `passphrase`**, as of 5.0.0 — don't mix it with
  older snippets.
- **`mkdir` is not idempotent and its "exists" error has no errno** — `stat()` first (§3).
- **`SSHClient`'s default policy is `RejectPolicy`** — moot here (we bypass `SSHClient`), but
  don't "fix" a copied `SSHClient` example with `AutoAddPolicy`.
- **A missing key file is a stdlib `FileNotFoundError`**, not a paramiko exception — needs its
  own `except OSError` arm.
- **paramiko's classifiers stop at Python 3.13** (`requires-python = ">=3.9"` doesn't cap it, so
  pip installs fine under 3.14.6) — **unverified**: nothing confirms or denies 3.14 compatibility
  beyond "no version ceiling blocks the install"; do a real import smoke test once added.

---

## Sources

- Context7 `/paramiko/paramiko` — `Transport.connect`, `MissingHostKeyPolicy`/`RejectPolicy`,
  `HostKeys.add`, `RSAKey.from_private_key_file`, `SSHClient._auth` (auth priority order),
  `SFTPClient.from_transport`/`.putfo`/`.open`, `SFTPServerInterface`/`SFTPServer` wiring,
  changelog entries (`passphrase` kwarg, Ed25519 unicode-password fix).
- `github.com/paramiko/paramiko` (`main`/5.0.0) via `gh api repos/paramiko/paramiko/contents/…`:
  `pyproject.toml` (deps, `requires-python`, classifiers), `paramiko/ssh_exception.py` (full
  hierarchy), `paramiko/pkey.py` (`from_path`, `.fingerprint`, `.get_fingerprint()`),
  `paramiko/sftp_client.py` (`put`/`putfo`/`open`/`mkdir`/`_convert_status`), `paramiko/client.py`
  (`SSHClient.__init__` default policy, `connect()` signature), `tests/_stub_sftp.py` +
  `tests/conftest.py` (`sftp_server` fixture — `add_server_key`, `set_subsystem_handler`,
  `start_server`).
- `pypi.org/pypi/paramiko/json` and `.../5.0.0/json` — version `5.0.0`, uploaded 2026-05-09.
- This repo's `app/.venv/Lib/site-packages/_pyinstaller_hooks_contrib/` (2026.6) —
  `stdhooks/hook-nacl.py` read directly; confirmed no `hook-paramiko.py`.
- `app/pyproject.toml`, `app/.venv` — confirmed `paramiko`/`pynacl` not yet installed;
  `cryptography` 50.0.0 and Python 3.14.6 already in place.
