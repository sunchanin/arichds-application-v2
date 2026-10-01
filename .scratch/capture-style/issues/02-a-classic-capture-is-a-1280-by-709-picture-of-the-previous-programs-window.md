# 02: A Classic capture is written as a 1280×709 picture of the previous program's window

**What to build:** With the style set to Classic, every `.png` written from then on — the
automatic capture of a new closed period, the Capture image button, and the download of a missing
image — is a 1280×709 picture of the customer's previous program's window: the ten-icon toolbar,
*Save Path*, the *Data Billing* group (Group, Statistics Summary, the Billing tab selected and
Current not, Device, *Read Billing*), the *Auto Read Schedule* group as fixed text (`00` : `00`,
`Status: Running`, `Stop`), the *Data Table* with *Reload Table*, nine columns cut at the window's
right edge, both scrollbars, and the status line `Capture bill data <serial>...`. The image never
grows with its rows. With the style at Standard the image is the screenshot it was — the same
requests to Edge, the same page. The page that is photographed is reachable by no menu and no
URL a person would type; it is chosen only by the seeded capture request. Icons and every
measured distance, colour and column width live in one stylesheet and one icon folder — measured
from `capture_WP081200.png`, a 1280×709 PNG ARICHDS Meter itself wrote, with the icons cut from
the owner-supplied 514×54 icon strip (both in the owner's Downloads folder; the PNG stays out of
the repository, the icons go in). Decision record: ADR 0028, ADR 0017 (the mechanism, unchanged); spec:
`.scratch/capture-style/spec.md`; glossary: CONTEXT.md → *Capture Style*, *Capture*.

**Blocked by:** 01 (An admin chooses the Capture Style, and Classic has something to draw from);
`.scratch/billing-sequence/issues/02` (Both periods of a same-second pair get their own capture
documents) — the file name a pair's second period is written under

**Status:** done — 2026-09-22 (commit in the log). Evidence: `test_capture_screenshot_style.py`
(Classic viewport/clip/seed/selector, Standard request list pinned byte-identical, the style read
at write time and flipped between two captures), `test_capture_dom_contract.py` (the two new fields
and the Classic selector against `capture.ts`/`ClassicCapture.tsx`); a real-Edge Classic capture
of the reference's eight rows came back 1280×709, 53,592 bytes, in 2.4 s through
`scripts/probe_classic_overlay.py --launch direct` (the pytest integration file's Classic case
still needs an administrator terminal: `schtasks /run` on the LOCAL SERVICE task is Access
denied from an ordinary shell — `cd app && set ARICHDS_TEST_EDGE=1 && .venv\Scripts\python -m
pytest tests/test_capture_screenshot_integration.py -s`); full gate and `pnpm lint && pnpm build`
in the commit message. `AppVersion` bumped to 0.7.9; the build is reported with ticket 03.

- [x] The seeded capture request gains `style: "standard" | "classic"`; the web↔app contract
      module is the one place its name lives; the page treats an absent or unrecognised value as
      Standard (`test_capture_dom_contract.py` pins it beside the other fields)
- [x] The renderer reads `capture_style` at write time on every path (the same session it mints
      the capture token with) — a test flips the setting between two captures through the same
      entry point and the second seed says `classic`
- [x] Classic drive (fake CDP transport): viewport `Emulation.setDeviceMetricsOverride` 1280×709;
      the screenshot clip is exactly 1280×709 with no `captureBeyondViewport` and no
      layout-metrics growth; the row-id gate waits for the ids in `bill_date ASC, sequence DESC`
      order
- [x] Standard drive: the recorded request list to the fake transport is **identical** to the
      existing expectation, asserted against the existing test's list rather than a new one
- [x] `App.tsx` chooses the Classic page when the seeded request says `classic`, the Billing page
      when it says `standard` or nothing; no nav entry, no route a person can reach
- [x] The Classic page is plain HTML/CSS in a fixed 1280×709 box, no AntD components inside the
      frame; one stylesheet holds every measured distance, colour (Total/Complete blue, Issues
      red, `Status: Running` green), font size and column width with a header note "measured from
      ARICHDS Meter's own `capture_WP081200.png`, 2026-09-22"; the ten icons cut from the
      owner-supplied strip beside it, at their original pixel size; its rows carry `data-row-key` so the existing selector finds them, or a
      selector declared in the contract module — never hardcoded in the driver
- [x] The page draws everything from the ticket-01 endpoint and formats nothing itself; strings
      are exactly the old program's (spec, *The Classic page*); English only
- [x] Opt-in real-Edge test (`ARICHDS_TEST_EDGE=1`): a Classic capture of thirteen seeded closed
      rows returns a PNG whose header reads 1280×709; the Standard case still passes unchanged;
      both output lines in the evidence
- [x] A Classic capture that fails (no Edge, timeout) is logged and leaves the PDF untouched,
      exactly as Standard — the existing side-effect test covers Classic too
- [x] Docs in the same change: CLAUDE.md's ADR 0028 digest drops "decided, not implemented";
      CONTEXT.md *Capture* already names Classic — verify the sentence still holds; installer
      `AppVersion` bumped to a new number for the build that ships this
- [x] Gate: `ruff format --check`, `ruff check`, `pytest -n auto` (app); `pnpm lint`, `pnpm build`
      (web); build the installer with `build-exe` and report its hash
