# Spec — the File Upload Destination (menu: FTP)

**Status:** ready-for-agent · grilled 2026-09-16 (18 questions, 3 rounds) · owner decisions
recorded inline · ADR 0025 accompanies this spec · glossary: CONTEXT.md → *File Upload
Destination*, *Upload Manifest*.

## Problem Statement

The customer's requirement list names three Data-out Destinations in one breath — *"DATA
Base · FTP · API"* (W2 › Data base › P15–P17). Two ship: the Database Destination (issue #46)
and the Central Push (M14). The third has a menu entry that is hidden, a page that says "Not
connected yet", a licence key that is reserved and not for sale, and no code behind it at all.
A site whose team wants the machine's **files** — the export files the customer signs off on
and the Billing capture documents — on a server of their own has nothing to configure. The
Central Push cannot stand in: it carries rows as JSON, never the documents, and only to the
team's own contract.

## Solution

An operator opens **FTP** under Data-out Destination, picks one of three tabs — **SFTP**,
**FTPS** or **HTTPS** — fills in the server and its credential, presses **Test connection**,
and saves. From then on, at the end of every scheduler cycle, the machine copies every export
file and every capture document that is new or changed since the server last saw it into a
folder tree under a root the operator chose, and the page's status card says what went where
and when. The server remembers what it holds in an **Upload Manifest**; the machine remembers
nothing (ADR 0008 / 0024) and never deletes anything remotely (owner decision — this is not a
Mirror Window). Leaving the page unconfigured means nothing is sent, which is how a
confidentiality-bound site opts out.

## User Stories

1. As an operator, I want a menu entry named **FTP** under Data-out Destination, so that the
   feature is where the customer's own word for it says it is.
2. As an operator, I want the page to offer three tabs — SFTP, FTPS, HTTPS — so that I can
   use whichever server my team runs.
3. As an operator, I want only one tab to be active — the one I saved last — so that the
   status card can tell me where files go with one answer.
4. As an operator on the SFTP tab, I want to authenticate with either a password or a
   private-key file on this machine (with an optional passphrase), so that I can follow my
   team's server policy.
5. As an operator on the SFTP tab, I want the server's host-key fingerprint shown to me on
   first connection and remembered, and I want to be asked again if it ever changes, so that
   an impersonating server is caught rather than trusted.
6. As an operator on the FTPS tab, I want explicit TLS on port 21 with the certificate
   checked against the system's trust store, so that "encrypted" means encrypted.
7. As an operator, I want plain FTP to be impossible to select, so that no credential or
   reading ever crosses the wire in clear text (ADR 0016).
8. As an operator on the HTTPS tab, I want a URL and a token field of its own, so that I can
   point files at the push server (pasting the Push Token) or at a different one.
9. As a receiving-server developer, I want the HTTPS file endpoints published on the API page
   beside the push contract, marked optional, so that I can implement them from one document.
10. As an operator, I want a **remote root** field, so that several machines can share one
    server by choosing different roots.
11. As an operator, I want the server's folder tree to mirror what I see on this machine —
    `export/` with the three files per meter, `captures/<Meter Serial>/` with the documents —
    so that I recognise it without a manual.
12. As an operator, I want every export file (Load Profile CSV, billing file, Energy file)
    for every meter uploaded whenever it changes, so that the server always holds what the
    customer would see here.
13. As an operator, I want every capture document under the capture folder uploaded once and
    then left alone, so that the documents the Central Push cannot carry are archived off
    the machine.
14. As an operator, I want unchanged files never re-sent, so that a 15-minute cycle does not
    move megabytes that already arrived.
15. As an operator, I want a first upload against an empty server to complete over as many
    cycles as its time budget needs and then go quiet, so that a large capture history never
    stalls the scheduler.
16. As an operator, I want files never deleted from the server by this machine, so that the
    server is an archive, not a mirror.
17. As an operator, I want the upload to run after the other jobs in a cycle, so that the
    files it sends are the ones that cycle finished writing.
18. As an operator, I want a **Test connection** button per tab that logs in, lists the root
    and reports the server's identity (host-key fingerprint / certificate subject / HTTP
    status), so that I know a save will work before I save.
19. As an operator, I want an **Upload now** button, so that I can prove the folder on the
    server fills without waiting for a cycle.
20. As an operator, I want a status card — protocol, when the last cycle ran, files sent,
    bytes sent, files skipped and why, how long it took, and the last error — so that
    "did it go?" has an answer on the page.
21. As an operator, I want a cycle that fails at any point to end as "skipped" with the
    reason, and the next cycle to try again from the manifest, so that one outage costs one
    cycle and nothing is lost.
22. As an operator, I want a sentence on the page saying that an empty configuration sends
    nothing, so that a site that must not upload knows it is safe by doing nothing.
23. As an operator, I want a detailed how-to on each tab — what to create on the server, which
    port, what the folder will look like, what is not supported — so that I can set up a
    server without calling the vendor.
24. As an administrator, I want the credential (password, passphrase, token) never returned by
    the API and redacted in every log line, so that the page and the log cannot leak it.
25. As a vendor, I want `file_upload_destination` to be a sellable licence key that gates the
    menu and the endpoints like `database_destination` does, so that the tag on the License
    card means something.
26. As a support engineer, I want one INFO line per cycle in the App Log with the counts, and
    one WARNING per failing cycle naming the class of failure, so that the log explains the
    status card.
27. As a support engineer, I want the manifest to be plain JSON a human can open on the
    server, so that "what has arrived" can be answered without our software.
28. As the owner, I want the SFTP client to be the one third-party dependency this adds, and
    FTPS and HTTPS to stay on the standard library, so that the exe grows once and by a known
    amount.

## Implementation Decisions

**Module.** A new package beside `dataout/` and `centralpush/` — the third Destination, with
its own configuration loader, cycle, in-memory status and transports. It imports nothing from
`export/` (the ADR 0021 rule for `dataout/` applies for the same reason) and reads the export
and capture folders as folders: the file on disk is the contract.

**One seam: the transport.** The cycle talks to a small transport interface — *read the
manifest, put one file, write the manifest, describe yourself for Test connection* — and three
implementations sit behind it: SFTP (paramiko), FTPS (standard-library `FTP_TLS`, explicit,
passive, system trust store), HTTPS (standard-library `urllib`, the same split-timeout opener
the Central Push client already has). Everything the cycle decides — which files, in what
order, the budget, the status — is protocol-blind.

**Files in scope.** For every device with a Meter Serial: the three export files the export
folder holds for it. Every file under the capture folder. Nothing else — no database, no
logs, no backups.

**Remote layout.** `<remote_root>/export/<file name as on disk>` and
`<remote_root>/captures/<Meter Serial>/<file name as on disk>`. Directories are created on
demand. The manifest lives at `<remote_root>/arichds-manifest.json`.

**Upload Manifest.** JSON: manifest version, the machine's Machine ID (informational), and a
map of relative path → `{sha256, size, uploaded_at}`. Read at the start of a cycle; absent or
unreadable means "send everything". The machine computes sha256 of every local candidate every
cycle (a few megabytes of disk reads), sends the files whose digest is absent or differs, then
writes the manifest back **only for the files it actually sent this cycle plus what it read**,
so a cycle that ran out of budget records exactly what arrived. Nothing is ever removed from
the manifest and nothing is ever deleted on the server.

**Scheduling.** A new job registered **last**, after `central_push`, at the 15-minute interval,
with its own budget constant (same shape as the DB destination's); the deadline is checked
before every file, never only between groups (ticket 08's lesson). Any transport error ends the
cycle as `skipped` with the failure's class name; no retry inside the cycle.

**Configuration.** Settings rows: active protocol, and per protocol its host/port/URL,
username, password or key path + passphrase, token, remote root, and the pinned SFTP host-key
fingerprint. Password, passphrase and token are write-only: the API reports `set`/`not set`,
never the value, and the setting keys end in `password` / `passphrase` / `token` so the existing
redaction filter covers every log line with no new pattern. Saving a tab makes it the active
protocol; the other tabs keep their values and send nothing.

**Endpoints.** Under settings, gated by `require_feature("file_upload_destination")`: get/put
the configuration, post test-connection (per protocol, returns the server's identity), post
upload-now, get status. Test connection uses the short connect timeout the DB destination's
test already uses.

**HTTPS contract (additive, contract version stays 1).** `GET {url}/v1/files/manifest` returns
the manifest or 404; `PUT {url}/v1/files/{relative path}` with the file body and its sha256 in a
header, any 2xx means stored; `PUT {url}/v1/files/manifest` writes the manifest. Every request
carries `Authorization: Bearer <token>`. Published on the API page as "Files (optional)" from
the same models that build the requests, the way the push contract is.

**SFTP specifics.** paramiko, password *or* key-file auth (RSA/Ed25519 via paramiko's key
loaders), host key pinned on first connection and shown as a fingerprint on the page; a
changed host key fails the cycle and Test connection until the operator accepts the new one.
Key file path is read at connect time under the service account; the file never enters the
database.

**FTPS specifics.** Explicit `AUTH TLS` on the configured port (default 21), passive mode, data
channel protected (`PROT P`), certificate verified against the system store with hostname
check; a self-signed certificate is a failure, not a prompt. Implicit FTPS (990) is not offered.

**Licence & navigation.** `file_upload_destination` leaves the reserved set and is sold like
`database_destination`; the nav entry becomes `kind: "feature"` with that key and the label
**FTP**. The existing shell page is replaced by the real page; its "Not connected yet" banner
goes.

**Page copy.** Each tab carries a how-to section in English: server-side prerequisites (user,
folder, port, certificate), what the machine will create, what is not supported (plain FTP,
implicit FTPS, self-signed certificates, deleting), and the sentence "Nothing is sent while
this page is empty." Toasts via `App.useApp()`; AntD tokens; no Thai.

**Dependencies.** `paramiko` (and its PyNaCl) is the one runtime addition; `cryptography` and
`bcrypt` are already shipped. Dev-only: an in-process SFTP server (paramiko's own server
classes) and an in-process FTPS server for tests (`pyftpdlib`), so that no transport branch
ships untested (memory: *a transport branch no test reaches ships broken*).

## Testing Decisions

A good test drives the cycle from the outside — a folder of files and a server — and asserts
on what the server holds afterwards, never on how the cycle chose. Prior art:
`test_central_push_cycle.py` against `fake_central_push_receiver.py` (in-process server on an
ephemeral port, asserting only on what it received) and `test_dataout_sync.py`.

- **Cycle tests** run against an **in-memory transport** that records puts and serves a
  manifest: first cycle sends everything and writes a manifest naming every file; second cycle
  with no changes sends nothing (mutation: dropping the digest compare turns it red); a changed
  energy file is re-sent and its digest updated; a budget of near zero sends at most one file
  and the manifest names exactly the files sent (mutation: writing the full manifest turns it
  red); a transport error mid-cycle ends `skipped` and the manifest still names what arrived;
  nothing is ever deleted remotely (a stale manifest entry survives).
- **Transport tests**, one per protocol, each against a real in-process server: HTTPS against
  the fake receiver extended with the three file endpoints (verifying the Bearer token); SFTP
  against a paramiko in-process server with password and with key-file auth, plus a host-key
  change that is refused; FTPS against a `pyftpdlib` TLS server with a self-signed certificate
  that is **refused** and a trusted one that succeeds. Each asserts the file arrived byte-equal
  and that a connection failure surfaces as the transport error class, never `TypeError` or
  `AttributeError`.
- **API tests**: configuration round-trips with the credential reported as `set` and never
  echoed; test-connection returns the server identity; the feature gate refuses a licence
  without the key.
- **Log tests**: one INFO line per cycle; the redaction filter blanks a password/token that a
  transport error message might contain.
- **Web**: the page renders three tabs, the active one marked, the how-to present, and the
  build/lint gates pass; the nav entry appears only with the licence key.

## Out of Scope

Plain FTP. Implicit FTPS. A CA-file field. Pasting key material into the database. Deleting or
trimming files on the server. Several active protocols or destinations at once. Uploading
backups, logs or the database. Per-file retry inside a cycle. A Machine-ID folder layer. Any
change to the Central Push payloads or `contract_version`. Syncthing sites — they configure
nothing and are untouched.

## Further Notes

- The customer said "FTP"; the owner chose the reach ("the team's cloud server") and then
  widened it to any server over three protocols, with FTPS kept despite the recommendation to
  drop it. The menu name follows the customer's word; the glossary term does not.
- v1 had no file upload; there is no Output Parity to hold to here — the files themselves are
  the parity (M13/M14).
- The manifest is deliberately readable without our software: it doubles as the receiving
  team's inventory.
- The Battery legend and the Billing toolbar counters the customer's screenshots show were
  v1 mock UI (research 2026-09-16); they are handled in the ui-audit tickets, not here.
