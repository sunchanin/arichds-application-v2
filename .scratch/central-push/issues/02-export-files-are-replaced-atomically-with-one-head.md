# 02: Export files are replaced in one step and carry exactly one head

**What to build:** When an export file's head — the header block or the column header row —
no longer matches what the program would write today, the file is rewritten in place under the
current head, instead of being renamed to a dated copy. Every rewrite happens in one step, so the
customer's tools and Syncthing never see half a file, and a failure leaves the previous file
exactly as it was. This is the prefactor that makes tickets 04 and 05 small: each export file
learns to render its whole current content. Decision record: ADR 0023 (supersedes the M13
amendment to ADR 0013); spec: `.scratch/central-push/spec.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] The shared export writer can replace a whole file atomically: the complete file (BOM,
      header block, header row, rows) is written to a temporary file in the same directory,
      flushed and synced, then swapped over the target in one operation
- [ ] **Atomicity**: a failure injected mid-write leaves the previous file byte-for-byte intact
      and leaves no temporary file behind
- [ ] Each of the three export files can render its whole current content:
  - [ ] Load Profile CSV — the 90-day window through the same merged Logger 1/Logger 2 query the
        append uses (skew cap and all-invalid exclusion included), setting its watermark to the
        newest row written
  - [ ] Billing Export File — every closed period, Open Period excluded, `Record No` unchanged
  - [ ] Energy Export File — the days the program can still produce, from the Energy Summary as
        it is computed at the time
- [ ] **A head mismatch rewrites the file in place.** Changing the head leaves exactly one file
      for that meter in the folder, carrying the current head, and no dated file is ever created
- [ ] The rename path that produced Closed Editions is deleted, with nothing left referring to it
- [ ] When the head matches, appending behaves exactly as today — the existing export tests stay
      green without being rewritten
- [ ] The auto-save switch still governs all three files: off writes nothing
- [ ] Every test above is mutation-probed: reverting the behaviour it names turns it red
- [ ] `CLAUDE.md`'s Layout entry for `export/` and its ADR 0013 digest stop describing Closed
      Editions as current behaviour
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/`
- [ ] No real-meter read is required: no driver changes
