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

**Status:** done — 2026-09-22. `app/scripts/probe_classic_overlay.py --reference <png> --out <dir>
[--launch direct]` seeds WP081200's eight rows (from `billing.csv`), the 212-device group (36
Offline) and `C:\CEWE DATA Billing_`, captures in Classic through the real renderer and writes
`ours.png`, `overlay.png` (reference | ours | heat map) and `blend.png`; `--launch direct` starts
Edge from the shell because the scheduled task needs an administrator. Images:
`C:\Users\HP\Downloads\arichds-classic-overlay\` (kept out of the repository — real serial and group).

**Overlay result, 2026-09-22 (three rounds; rounds 1–2 fixed in the stylesheet):**

| Region | Result |
|---|---|
| Toolbar (body edges, ten icons) | agrees to the pixel (mean diff 1.8, 0.5 % of pixels > 40) |
| Save Path box, field, Browse | agrees; the field's 2px sunken edge is drawn as 1px — accepted (a 254-grey inner line) |
| Data Billing group, Group combo | agrees; text starts agree — glyph widths differ by 1–2 px, accepted — glyph rendering |
| Statistics Summary | positions and colours agree (blue/red/green); `212 / 36 / 176` reproduced from Poller statuses alone |
| Tabs (Billing selected, Current) | agrees after round 2 (Current's baseline) |
| Device row, Read Billing | agrees; `CEWE - WP081200` 2 px wider — accepted — glyph rendering |
| Auto Read Schedule | agrees; `00 : 00` against the reference's `00 : 10` **by design** (spec, Further Notes); spinner digits 1 px left — accepted |
| Data Table header | separators at x 222/372/492/612/732/852/992/1132 exact; baseline fixed in round 2 |
| Each column's x-range | cell text starts agree to the pixel in all nine columns; digit strings 2–5 px wider over ~80 px — accepted — glyph rendering (Chromium/DirectWrite vs GDI) |
| Scrollbars | vertical bar, its two arrows and the horizontal thumb agree to the pixel after round 2 |
| Status line | start and baseline agree; 4 px wider — accepted — glyph rendering |

The eight data rows match cell for cell as strings (`9667.7793`, `2/1/2026 00:00`, `1/10/2026
12:30`, `12091.533`, `50.863`, `61249.94`, …) — the end-to-end proof of ticket 01's column mapping.

- [x] A script under the scripts folder (a probe, not a test — it needs a real Edge and the
      reference file) seeds the data above into a throw-away data directory, captures in Classic
      and writes a diff image: our PNG, theirs, and an absolute-difference heat map side by side;
      the script takes the reference path as an argument and never embeds it
- [x] Overlay result recorded here: a table of every region that differs by more than glyph
      anti-aliasing (toolbar, Save Path box, Data Billing group, Statistics, tabs, Device row,
      Auto Read Schedule, Data Table header, each column's x-range, scrollbars, status line), each
      with "fixed in stylesheet" or "accepted — glyph rendering"; the *Auto Read Schedule* time
      differs by design (`00 : 00` vs the reference's `00 : 10`) unless the owner chose otherwise
- [x] The eight data rows match cell for cell as strings (`9667.7793`, `2/1/2026 00:00`,
      `1/10/2026 12:30`, …), which is also the end-to-end proof of ticket 01's column mapping
- [x] Statistics `212 / 36 / 176` reproduced from Poller statuses alone (36 Offline, none Paused
      counted), in the reference's colours
- [x] CLAUDE.md's ADR 0028 digest drops the "do not report identical" warning and records the
      overlay date and the accepted differences in one line
- [x] Gate, if code changed: `ruff format --check`, `ruff check`, `pytest -n auto` (app);
      `pnpm lint`, `pnpm build` (web); a new installer number if a hash was already reported
