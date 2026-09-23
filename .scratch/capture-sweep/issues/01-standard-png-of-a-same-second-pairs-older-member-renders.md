# 01: The Standard PNG of a same-second pair's older member renders

**What to build:** A period that shares its bill date with a newer one (Billing Sequence 1, the
`_2` document) gets its Standard-style `.png` like any other period — on the eager path after a
read and on the render-on-miss download — instead of failing after the ninety-second budget every
time. The Billing page, when opened by the capture driver, receives the anchor it already seeds
(the reading id) and lists exactly the PNG window for that anchor: every closed period up to and
including it, the newer member of its pair excluded, the same rows the image is defined to hold.
Site TC's six pairs are the case that fails today. The Classic style is untouched — its own
endpoint is already keyed by the anchor.

**Blocked by:** None (can start immediately)

**Status:** done (2026-09-23)

- [x] The billing list endpoint accepts an optional anchor reading id and, when given, applies the
      PNG window's own rule (one shared predicate, never a second copy): periods up to and
      including the anchor, the newer member of the anchor's pair excluded, newest first, ten at
      most — page one reversed as today so the table reads oldest first
- [x] Without the anchor the endpoint's behaviour and response are byte-for-byte what they are
      today (existing tests unchanged and green)
- [x] The Billing page in capture mode passes the seeded anchor; the Standard drive's request list
      for a period alone on its bill date is pinned unchanged, and for the older member of a pair
      the driver's row wait is satisfied against the fake trigger
- [x] A test seeds a same-second pair, requests the older member's Standard image through the
      download path with the fake trigger, and gets a `_2.png`; mutation check: dropping the pair
      exclusion makes the row wait fail again
- [x] Gate: `ruff format --check`, `ruff check`, `pytest -n auto` (app), `pnpm lint && pnpm build`
      (web); the real-Edge integration test (`ARICHDS_TEST_EDGE=1`) is handed to the owner to run
      from an administrator shell, with the exact command in the report

**Evidence:** `png_window_filters()` in `capture/service.py` is the one predicate; `png_source_rows` and
`GET /api/billing?anchor_id=` both apply it; `TestAnchorWindow` (6 tests) in `test_api_billing.py` — the
page's rows equal `png_source_rows` reversed for both members of a pair; mutation `sequence >= 0` failed 2.
Standard seed pinned byte-identical (`TestStandardDriveIsUnchanged`). Real-Edge run: owner, admin shell:
`cd app && set ARICHDS_TEST_EDGE=1 && .venv\Scripts\python -m pytest tests/test_capture_screenshot_integration.py -s`.
