# 02: The cycle sends what the Upload Manifest lacks, against an in-memory transport

**What to build:** At the end of every scheduler pass, the machine copies every export file and
every capture document that the server does not yet hold — or holds in an older form — into the
folder tree under the remote root, and the FTP page's status card says what went where and when.
The server remembers what it holds in an **Upload Manifest** (plain JSON at the remote root:
manifest version, this Machine ID for information, and relative path → `{sha256, size,
uploaded_at}`); the machine remembers nothing and never deletes anything remotely. An **Upload
now** button runs one cycle on demand. This ticket lands the whole cycle behind **one transport
seam** — read the manifest, put one file, write the manifest, describe yourself — and proves it
against an in-memory transport; the three real transports are tickets 03–05, so after this ticket
a configured page still moves no bytes. Decision record: ADR 0025 (decisions 2–4); spec:
`.scratch/file-upload/spec.md` → Implementation Decisions, Testing Decisions.

**Blocked by:** 01 (the configuration and the page)

**Status:** ready-for-agent

- [ ] A new package beside `dataout/` and `centralpush/` holds the transport interface, the
      manifest model, the cycle and an in-memory status. It imports nothing from `export/` or
      `capture/` — it reads the export folder and the capture folder as folders (a test asserts the
      import boundary, the way `test_dataout_sync.py` does for `dataout/`)
- [ ] Files in scope, and nothing else: for every device with a Meter Serial, the three export
      files the export folder holds for it; every file under the capture folder. Backups, logs and
      the database are never candidates
- [ ] Remote layout: `<remote_root>/export/<file name as on disk>`,
      `<remote_root>/captures/<Meter Serial>/<file name as on disk>`,
      `<remote_root>/arichds-manifest.json`; directories are created on demand by the transport
- [ ] The cycle reads the manifest first; a missing or unreadable manifest means "send everything".
      It computes sha256 of every local candidate every cycle, sends the files whose digest is
      absent or differs, and writes the manifest back naming **only what it read plus what it
      actually sent this cycle** — never a full local inventory. Nothing is ever removed from the
      manifest and nothing is ever deleted on the server
- [ ] A time budget of its own (a constant with the shape of the Database Destination's) is
      checked **before every file**, never only between the export and capture groups; a cycle
      that runs out of budget ends with the manifest naming exactly the files that arrived, and
      the next cycle continues from it
- [ ] Any transport error ends the cycle as `skipped` carrying only the failure's class name — no
      URL, no host, no credential — with no retry inside the cycle; the manifest still names what
      arrived before the failure
- [ ] An unset active protocol, or an active protocol with no host/URL, means the cycle does
      nothing and reports that it was not configured
- [ ] The job is registered **last**, one behind `central_push`, at the 15-minute interval, with
      its own job-name and interval constants (not aliased to the load-profile interval — the same
      reason the Database Destination's is not)
- [ ] Status is one in-memory frozen record that resets on restart (ADR 0008): protocol, when the
      last cycle ran, outcome, files sent, bytes sent, files skipped and why (unchanged / budget /
      no Meter Serial), duration, last error class. The status endpoint from ticket 01 now returns it
- [ ] **Upload now**: an admin-only endpoint gated by the feature key runs one cycle immediately
      through the scheduler's one-shot path (the way the Database Destination's test uses it),
      returns that cycle's status, and the page gets the button beside Test connection
- [ ] App Log: one INFO line per cycle with the counts, one WARNING per failing cycle naming the
      failure class; a secret that a transport error message might contain is redacted (a test
      captures the log)
- [ ] Cycle tests against an **in-memory transport** that records puts and serves a manifest, each
      asserting only on what the transport holds afterwards: first cycle sends everything and the
      manifest names every file; a second cycle with no changes sends nothing (mutation: dropping
      the digest compare turns it red); a changed Energy file is re-sent and its digest updated; a
      budget near zero sends at most one file and the manifest names exactly the files sent
      (mutation: writing the full manifest turns it red); a transport error mid-cycle ends
      `skipped` and the manifest still names what arrived; a stale manifest entry for a file that
      no longer exists locally survives (nothing is deleted); a device without a Meter Serial is
      skipped and counted
- [ ] Web: the status card shows every field above, "Not yet run since start" before the first
      cycle, and the **Upload now** button; English only
- [ ] `CLAUDE.md`'s ADR 0025 digest records what landed
- [ ] Every test above is mutation-probed: reverting the behaviour it names turns it red
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/`;
      `pnpm lint` + `pnpm build` in `web/`
