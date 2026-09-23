# 04: Save all — every device's billing file, and a Capture Sweep of every missing document

**What to build:** The Billing page's *Save billing file now* becomes **Save all**, an admin-only
button in the same place. Pressing it answers at once: 422 "Billing folder is empty — set it on
this page" when the Billing Folder is empty, 409 "already running" while a sweep is in flight,
otherwise `started` with the status below. The work runs on the scheduler's one-shot lane in
slices of at most sixty seconds (a named constant, not a setting): for devices in id order —
including Paused ones — the slice rewrites that device's Billing Export File once, then for each
closed period newest first (bill date descending, sequence ascending) whose PDF does not exist in
the current Billing Folder it writes the Capture through the existing per-reading function (PDF,
then xlsx and PNG per the licence flags, the eager path's own three gates), stamps *Captured* only
when the write succeeded, and after the capture that crosses the budget re-queues itself so the
regular jobs (load profile every fifteen minutes) run between slices; a pass that finds nothing
missing finishes. A file that exists is never rewritten, whatever wrote it. A period that cannot
be written is logged with device and reading id, counted `failed`, and skipped; nothing about
which periods were swept is persisted — the folder is the state, and after a restart the status
reads "not run since start". A read-only status endpoint serves the page: `running`,
`started_at`, `finished_at`, `billing_files_written`, `captures_written`, `captures_left`,
`captures_failed`, `None` until the first Save all since start. The page shows the button loading
while running and a progress line beneath it that every role can read; the Captured column fills
in as the sweep goes.

**Blocked by:** 01 (the `_2.png` of a pair must render, or the sweep fails ninety seconds per pair
every run), 03 (the billing file's path and the 422 wording it shares)

**Status:** ready-for-agent

- [ ] The per-device export endpoint is replaced by the admin-only Save all endpoint and its status
      endpoint (any authenticated role reads status); the page's button reads **Save all**, is
      rendered for an admin only, and the progress line is visible to a `user`
- [ ] Tests through the endpoint and the slice function with the fake meter and the screenshot
      fake trigger: two devices with N closed periods and an empty folder end with N PDFs (and the
      xlsx/PNG the licence allows) after the slices run; a pre-existing PDF keeps its bytes and its
      period is not counted written; `captured_at` is stamped only for written periods; writes
      happen newest first; a Paused device is swept; 422 with the folder empty; 409 on a second
      press while running; a period made unwritable is counted `failed` and the rest are written;
      with the budget constant shrunk a slice stops and re-queues, and the regular jobs' hook runs
      between slices; status is `None` after a scheduler restart
- [ ] Mutation checks recorded in the report: dropping the existence check rewrites or raises on a
      pre-existing file; reversing the order; dropping the re-queue leaves `captures_left` non-zero
- [ ] The sweep's PNG writes go through the same capture lock as a hand-pressed download
- [ ] CONTEXT.md's *Save all* / *Capture Sweep* entries hold; CLAUDE.md's 0010/0015/0028 digests
      mention Save all and the sweep in one sentence each
- [ ] Gate: `ruff format --check`, `ruff check`, `pytest -n auto` (app), `pnpm lint && pnpm build`
      (web); the real-Edge integration test handed to the owner for an administrator shell
