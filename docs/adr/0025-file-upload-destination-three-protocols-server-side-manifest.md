# 0025. The File Upload Destination speaks three protocols and keeps its state in a server-side manifest

**Status:** Accepted · 2026-09-16 · grilled with the owner (18 questions, 3 rounds)

## Context

The customer's requirement list names three Data-out Destinations — *"DATA Base · FTP ·
API"*. Two exist (ADR 0016/0020/0021 for the customer's database; ADR 0024 for the Central
Push). The third had a hidden menu, a shell page and a reserved licence key. ADR 0016 recorded
that plain FTP is never acceptable and left "FTPS or SFTP" open for M8.

What the customer wants moved is **files**: the export files they sign off on and the Billing
capture documents — the one thing the JSON push cannot carry. Where they go was widened by the
owner from "the team's cloud server only" to "the team's server or any other", and the protocol
from one to a choice.

Two facts shaped the shape: the machine already runs a Destination that keeps no state and asks
the server what it holds every cycle (ADR 0024), and this codebase has already shipped a
transport branch that no test reached and that was broken on every call (M14 ticket 08).

## Decision

1. **One Destination, three transports, one active at a time.** The page (menu label **FTP** —
   the customer's word, not the mechanism) has SFTP, FTPS and HTTPS tabs; the tab saved last is
   the one that sends. SFTP uses paramiko (password or key file, host key pinned on first
   contact); FTPS is explicit TLS on the standard library with the system trust store and no
   self-signed escape hatch; HTTPS is the standard-library client the push already has, with
   its own token, and its file endpoints are published on the API page beside the push
   contract without bumping the contract version.
2. **The server remembers; the machine does not.** An **Upload Manifest** — plain JSON of
   relative path → sha256 — lives at the remote root. Each cycle reads it, sends what is absent
   or different, and writes back what it actually sent. No watermark, no local queue, no
   persisted job state (ADR 0008). A missing manifest means "send everything".
3. **Never delete remotely.** Unlike the Database Destination (ADR 0020), whose deletes exist
   because the customer's disk is the constraint, this server is an archive: the machine adds
   and replaces, never removes. The capture folder is sent whole, once.
4. **Layout mirrors the machine** under one operator-chosen remote root: `export/` and
   `captures/<Meter Serial>/`. No Machine-ID layer; several machines share a server by
   choosing roots.
5. **Every transport branch has a test against a real in-process server** — a paramiko SFTP
   server, a `pyftpdlib` TLS server and the extended fake receiver — as dev-only dependencies.
   The cycle itself is tested once, against an in-memory transport.

## Consequences

- **The exe grows once**: paramiko and PyNaCl are the only runtime additions (`cryptography`
  and `bcrypt` already ship). FTPS and HTTPS add nothing.
- **Three surfaces to keep working.** FTPS was recommended for removal (passive-mode NAT
  trouble, no advantage over SFTP when we control the server) and kept by the owner; the price
  is a third credential shape and a third failure mode on the status card. If FTPS is never
  configured by a real site within a year, revisit.
- **The manifest is the receiving team's inventory too** — readable without our software —
  and a site that wipes its server folder simply gets everything again next cycle.
- **A first upload of a large capture history spans several cycles** under the budget; that is
  the design, not a stall, and the manifest makes each cycle's progress durable.
- **The glossary and the menu disagree on purpose**: *File Upload Destination* in CONTEXT.md,
  **FTP** on screen. Do not "fix" one to match the other.
- **`file_upload_destination` leaves the reserved set** (issue 013) and is sold like
  `database_destination`; the License card tag it already shows becomes true.
- Sites that forbid cloud upload configure nothing and are untouched; there is no switch
  because an empty page *is* the switch, the same rule the Central Push follows.
- **"Empty" holds for the whole life of the page, not only before the first save**
  (`docs/issues/022`, 2026-09-18): an empty host/URL on the *active* tab is the off state and is
  savable from the page — the cycle publishes `not_configured` and never builds a transport —
  exactly as the Central Push's empty URL already behaves and as the Database Destination's API
  already accepts (its *form* still carries the same `required` rule this issue removed here —
  `docs/issues/023`). Two guards keep the rule honest: only the *active* tab may be saved empty (an empty
  save on any other tab, including when nothing is active yet, is refused with the way out
  named, so a stray Save cannot silently stop uploads), and clearing the host keeps every other
  field — password, token, passphrase, key-file path, the pinned host key — so switching back
  on is one save. The first implementation had narrowed this rule to the fresh page (a
  required Host/URL on the form, a blank-URL refusal on the HTTPS tab); that was the bug, not
  the absence of a Stop button, which this ADR still does not have.
