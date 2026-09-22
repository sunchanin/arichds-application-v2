# 03: The Classic image is laid over ARICHDS Meter's own PNG

**What to build:** Nothing is reported as "identical" until this ticket closes. The reference is
`capture_WP081200.png` — a 1280×709 PNG ARICHDS Meter itself wrote (owner's Downloads folder,
kept out of the repository: real serial, group and readings). Seed a device and eight closed
periods that reproduce that image's rows exactly (serial `WP081200`, group `PWA Phase.2 Days1`,
the eight bill dates and cells as pictured; the `billing.csv` rows for that meter carry every
value), a capture folder whose Save Path reads `C:/CEWE DATA Billing_`, and a group of 212
devices whose Poller statuses give `212 / 36 / 176`. Capture in Classic, then lay our PNG over
theirs: every position, size, colour and string agrees, glyph edges may differ, and the
differences — with their fixes — are listed here. Decision record: ADR 0028 (acceptance); spec:
`.scratch/capture-style/spec.md`.

**Blocked by:** 02 (A Classic capture is written as a 1280×709 picture of the previous program's
window)

**Status:** ready-for-agent

- [ ] A script under the scripts folder (a probe, not a test — it needs a real Edge and the
      reference file) seeds the data above into a throw-away data directory, captures in Classic
      and writes a diff image: our PNG, theirs, and an absolute-difference heat map side by side;
      the script takes the reference path as an argument and never embeds it
- [ ] Overlay result recorded here: a table of every region that differs by more than glyph
      anti-aliasing (toolbar, Save Path box, Data Billing group, Statistics, tabs, Device row,
      Auto Read Schedule, Data Table header, each column's x-range, scrollbars, status line), each
      with "fixed in stylesheet" or "accepted — glyph rendering"; the *Auto Read Schedule* time
      differs by design (`00 : 00` vs the reference's `00 : 10`) unless the owner chose otherwise
- [ ] The eight data rows match cell for cell as strings (`9667.7793`, `2/1/2026 00:00`,
      `1/10/2026 12:30`, …), which is also the end-to-end proof of ticket 01's column mapping
- [ ] Statistics `212 / 36 / 176` reproduced from Poller statuses alone (36 Offline, none Paused
      counted), in the reference's colours
- [ ] CLAUDE.md's ADR 0028 digest drops the "do not report identical" warning and records the
      overlay date and the accepted differences in one line
- [ ] Gate, if code changed: `ruff format --check`, `ruff check`, `pytest -n auto` (app);
      `pnpm lint`, `pnpm build` (web); a new installer number if a hash was already reported
