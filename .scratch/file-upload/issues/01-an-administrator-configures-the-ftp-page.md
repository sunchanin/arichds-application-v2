# 01: An administrator configures the FTP page, and nothing is sent yet

**What to build:** The **FTP** entry under Data-out Destination stops being a hidden shell. With a
licence that carries `file_upload_destination`, an administrator opens the page, sees three tabs —
**SFTP**, **FTPS**, **HTTPS** — each with a how-to for the server side, fills in one of them, and
saves. The tab saved last becomes the *active protocol*; the other two keep what was typed and send
nothing. The credential (password, key-file passphrase, token) is write-only: the page shows "set"
or "not set", never the value. A status card says no cycle has run yet. The page carries the
sentence "Nothing is sent while this page is empty." Nothing is uploaded by this ticket — ticket 02
adds the cycle, tickets 03–05 the transports — but the licence key is now sold, the menu is there,
and the configuration round-trips. Decision record: ADR 0025; spec: `.scratch/file-upload/spec.md`;
glossary: CONTEXT.md → *File Upload Destination*, *Upload Manifest*.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `file_upload_destination` leaves the reserved feature-key set and is sold exactly like
      `database_destination`: the vendor CLI accepts it, the License card tag it already shows is
      true, and the reserved set is empty (or gone) with its comment updated
- [ ] The nav entry becomes a licence-gated feature with that key and the on-screen label **FTP**
      (the glossary term stays *File Upload Destination* — ADR 0025 says the two disagree on
      purpose); `test_nav_feature_contract.py` stays green with the change
- [ ] Settings hold: the active protocol (one of `sftp` / `ftps` / `https`, or unset), and per
      protocol its own host + port (SFTP, FTPS), URL (HTTPS), username, password, key-file path +
      passphrase (SFTP only), token (HTTPS only), remote root, and the pinned SFTP host-key
      fingerprint (written by ticket 04, but the row exists). Every secret setting's key ends in
      `password`, `passphrase` or `token`, so the existing redaction filter covers it with no new
      pattern — a test captures the log output of a save and finds no secret
- [ ] Endpoints under settings, admin-only and gated by `require_feature("file_upload_destination")`:
      read the configuration, update one protocol's configuration (which makes it active), and
      read the last cycle's status. A licence without the key gets the same refusal the Database
      Destination endpoints give
- [ ] The configuration response reports each secret only as set / not set and never echoes it;
      an update that leaves a secret blank keeps the stored one (the Database Destination's rule)
- [ ] Saving the SFTP tab with neither a password nor a key-file path, or the HTTPS tab with no
      URL, is refused with a message naming the missing field; a port outside 1–65535 is refused
- [ ] Plain FTP and implicit FTPS (port 990) cannot be chosen: there is no such protocol value,
      and the FTPS how-to says so
- [ ] Until ticket 02 lands, the status endpoint reports that no cycle has run
- [ ] Web: the shell page and its "Not connected yet" banner are replaced by the real page under
      Data-out — three tabs, the active one marked, a form per tab with a write-only credential
      field and a "set" indicator, a status card, the how-to per tab (server-side prerequisites:
      user, folder, port, certificate; what the machine will create: `export/` and
      `captures/<Meter Serial>/` under the remote root and `arichds-manifest.json`; what is not
      supported: plain FTP, implicit FTPS, self-signed certificates, deleting), and the sentence
      "Nothing is sent while this page is empty." Toasts via `App.useApp()`, AntD tokens, English
      only
- [ ] CONTEXT.md's *File Upload Destination* and *Upload Manifest* entries still match what shipped;
      `CLAUDE.md` gains an ADR 0025 digest line recording what this ticket landed
- [ ] Every test above is mutation-probed: reverting the behaviour it names turns it red
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/`;
      `pnpm lint` + `pnpm build` in `web/`
