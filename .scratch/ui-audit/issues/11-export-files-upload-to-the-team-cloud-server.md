# 11: Export files upload to the team's cloud server

**What to build:** The File Upload Destination stops being a shell: the machine uploads its
export files to **the team's own cloud server only** (owner decision 2026-09-16 — not to
arbitrary customer FTP hosts), over an encrypted transfer (ADR 0016 excludes plain FTP), on
the scheduler, mirroring the 90-day export window the way every other destination does
(ADR 0020/0023). The customer named it in one word — *"FTP"* (W2 › Data base › P16).

**Blocked by:** A spec. This is a new transport and the repo's workflow is
`/grill-with-docs → /to-spec → /to-tickets` before any issue is cut for an ungrilled module
(CLAUDE.md). The grill has to settle, at least:

- protocol — SFTP or FTPS, and which server the team actually runs;
- what is uploaded — the three export files, the capture documents, or both; whole-file
  replace versus append; folder layout on the server (per machine, per meter);
- credentials — where they live, how they are redacted, how they are rotated;
- how it relates to the central push (ADR 0024) — two transports carrying overlapping data
  to the same team, and whether that is wanted;
- the licence key `file_upload_destination`: leaves `RESERVED_FEATURE_KEYS`, and the nav
  entry leaves `kind: "never"`.

**Type**: HITL · **Status:** blocked — run `/grill-with-docs` for this feature first, then `/to-spec`, then
replace this file with the tickets that come out.

- [ ] (to be written by `/to-tickets` from the spec)
