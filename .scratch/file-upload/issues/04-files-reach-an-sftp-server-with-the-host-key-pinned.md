# 04: Files reach an SFTP server, with the host key pinned

**What to build:** An administrator saves the SFTP tab with the server, a username and either a
password or the path of a private-key file on this machine (with an optional passphrase). The
first **Test connection** shows the server's host-key fingerprint and remembers it; from then on
a server presenting a different key is refused — by Test connection and by every cycle — until
the administrator accepts the new fingerprint on the page. **Upload now** then fills the remote
root over SFTP. paramiko (with PyNaCl) is the one runtime dependency this feature adds; the exe
grows once and the size is recorded. Decision record: ADR 0025 (decision 1, SFTP; Consequences);
spec: `.scratch/file-upload/spec.md` → SFTP specifics.

**Blocked by:** 02 (the cycle and the transport seam)

**Status:** ready-for-agent

- [ ] The SFTP transport implements the ticket 02 seam with paramiko: password auth or key-file
      auth (RSA and Ed25519 through paramiko's own key loaders, passphrase optional). The key file
      is read at connect time under the service account; its content never enters the database
      or a log line (a test captures the log)
- [ ] **Host key pinning**: on first contact with no pinned fingerprint, Test connection reports
      the fingerprint and the page offers to pin it; a pinned fingerprint that no longer matches
      fails Test connection and ends a cycle `skipped` with a failure class that names the host-key
      mismatch, never the key itself; accepting the new fingerprint on the page replaces the pin.
      A cycle never pins on its own
- [ ] Every paramiko failure (refused, timed out, bad credentials, host-key mismatch, missing key
      file) surfaces as the transport's own error class carrying only the failure's class name —
      never a paramiko exception, never the host, never a credential
- [ ] **Test connection** on the SFTP tab logs in, lists the remote root, and reports the
      fingerprint and whether a manifest exists, with the short connect timeout the Database
      Destination's test uses
- [ ] Transport tests against a paramiko **in-process** SFTP server on an ephemeral port: upload
      with a password and with a key file (each byte-equal), the manifest round-trips, a changed
      host key is refused, a wrong password surfaces as the transport error class
- [ ] paramiko and PyNaCl are declared runtime dependencies with a comment saying why they are
      the one addition; the PyInstaller build includes them (a one-dir build is made and the
      onedir size before/after is recorded in the ticket's evidence); `cryptography` and
      `bcrypt` are not re-declared
- [ ] Web: the SFTP tab's key-file path + passphrase fields, the fingerprint display with its
      accept action, **Test connection** and its result sentence; the how-to names what to create
      on the server (user, folder, port 22) and that the key file stays on this machine; English
      only
- [ ] `CLAUDE.md`'s ADR 0025 digest records what landed; `installer/README.md` gains a
      troubleshooting row for a host-key mismatch
- [ ] Every test above is mutation-probed: reverting the behaviour it names turns it red
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/`;
      `pnpm lint` + `pnpm build` in `web/`
