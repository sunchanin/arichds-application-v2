# Spec — Save all: the Capture Sweep, and each export file only in its own folder

**Status:** done 2026-09-23 (tickets 01–05, installer 0.8.4) · grilled with the owner 2026-09-23 (grill-with-docs, nine questions over
three rounds, every branch settled) · amends `.scratch/export-folders/spec.md` (the folder fallback
is withdrawn) and 0.8.3's one-folder decision ก (the Billing Export File moves into the meter's
subfolder). Tracker: local (`.scratch/capture-sweep/issues/` once `/to-tickets` runs); no GitHub
issue. Glossary: CONTEXT.md → *Billing Folder*, *Capture Sweep*, *Save all*, *Capture*, *Captured*,
*Billing Export File*, *Energy Export File*, *Load Profile CSV*, *File Upload Destination*,
*Upload Manifest*, *Billing Sequence* — all written during the grill; use those words.

## Problem Statement

A Capture is written once, the moment a closed billing period is stored. If the Billing Folder is
set *after* the first read, or moved later, every period already in the store has no document in
the folder the operator now looks at — and nothing writes them: the only way to get one is to open
the Billing page and download each period by hand, twenty meters times thirteen periods at site TC.
The owner remembers v1 helping here; it did not — v1's Backfill captured only newly inserted rows
(exactly today's eager path) and its Regenerate was one period at a time. The customer also keeps a
meter's billing documents together: the Billing Export File sits at the top of the Billing Folder
while the captures sit inside `WP081200\`, and they want the file in that subfolder too. Finally,
0.8.2 made an empty folder fall back to the Load Profile CSV's folder — the owner does not want a
file ever written into another file's folder: an empty folder should say so, not improvise.

## Solution

The Billing page's *Save billing file now* becomes **Save all**, an admin action for the whole
machine: it rewrites every device's Billing Export File and runs a **Capture Sweep** — every closed
period with no document in the current Billing Folder gets one, newest first, every format the
licence allows, never over a file that exists. It runs in short slices between the scheduler's
regular jobs, answers at once, and the page shows how far it has got; pressed while running it says
so. The page also tells an admin how many closed periods have no document in this folder yet, so
they know to press it after an install or a move. The Billing Export File lives inside the meter's
own subfolder of the Billing Folder, beside its captures. And every export file is written only
into its own folder: an empty Billing Folder means no captures and no billing file, an empty Energy
file folder means no Energy file — the Save button on each page answers "folder is empty" instead
of writing somewhere else.

## User Stories

**Save all**

1. As an admin, I want one **Save all** button on the Billing page, so that after installing
   ARICHDS or moving the Billing Folder I get every meter's billing documents without visiting each
   period.
2. As an admin, I want Save all to rewrite every device's Billing Export File, so that the file in
   the new folder is current the moment I press it rather than at the next 15-minute cycle.
3. As an admin, I want Save all to write the Capture (PDF, and xlsx/PNG when the licence allows)
   for every closed period of every device that has none in the current Billing Folder, so that the
   folder is complete.
4. As an admin, I want Save all to cover every device that has a closed period in the store —
   including a Paused one — so that a meter I stopped reading still has its history on disk.
5. As an admin, I want Save all to answer at once and keep working in the background, so that a
   site with hundreds of PNGs does not time out my browser.
6. As an admin, I want the Billing page to show Save all's progress — billing files written,
   captures written, captures left, failures — and the Captured column to fill in as it goes, so
   that I know when it is done.
7. As an admin, I want pressing Save all while one is already running to be told "already
   running" and queue nothing, so that two presses cannot double the work.
8. As an admin, I want Save all to be refused with a clear sentence when the Billing Folder is
   empty, so that I set the folder instead of wondering where the files went.
9. As a `user`, I want to see Save all's progress but not the button, so that I know what the
   admin started without being able to start one myself.
10. As an operator, I want the load-profile read every fifteen minutes to keep its time while a
    sweep runs, so that filling a folder never costs interval readings.
11. As an admin, I want the sweep to survive a restart with nothing to clean up — the next Save
    all simply writes what is still missing — so that a service restart mid-sweep is harmless.

**The sweep's rules**

12. As an operator, I want a Capture that already exists in the folder to be left exactly as it
    is, whatever style or version wrote it, so that a document I already handed over never
    changes under me (delete it to re-issue it, as decided 2026-09-22).
13. As an operator, I want the sweep to write the newest periods first, so that the periods
    someone is waiting for arrive before last year's.
14. As an operator, I want a period whose document cannot be written to be logged and counted,
    not to stop the sweep, so that one bad row does not hold the other nineteen meters.
15. As an operator, I want the older member of a same-second pair (`_2`) to get its Standard
    PNG like any other period, so that the sweep does not spend ninety seconds failing on each
    of site TC's six pairs every time it runs.
16. As an operator, I want a swept Classic image's Statistics Summary and a swept PDF's print
    time to be the moment of writing, so that every value in the document is true (it is what a
    download-time render already does).

**The warning**

17. As an admin, I want the Billing page to say "N closed period(s) have no document in this
    folder yet — press Save all", so that a fresh install or a moved folder does not sit
    silently incomplete.
18. As an admin, I want that count to include periods captured *before* the folder was last
    changed, so that a move shows the right number rather than zero.
19. As an admin, I want the warning to disappear once the sweep has written them, so that it is
    not noise on a complete folder.

**Where the billing file lives**

20. As a customer, I want a meter's Billing Export File inside that meter's subfolder of the
    Billing Folder, beside its PDF/xlsx/PNG captures, so that everything about one meter's billing
    is in one place.
21. As an operator, I want the 15-minute rewrite and Save all to write the file to that same
    place, so that there is one billing file per meter, not one per path.
22. As an operator, I want the Load Profile CSV and the Energy Export File to stay flat in their
    own folders, so that nothing else moves.
23. As an operator, I want the old billing file left at the folder's top level to be left alone,
    so that the program never deletes a file I may have handed over (the owner removes it).
24. As a File Upload Destination server, I want the Billing Export File to keep arriving as
    `export/<name>` in the Upload Manifest, so that the published contract does not change
    because the file moved on disk.
25. As an operator, I want the File Upload Destination to send the billing file once — as an
    export, never a second time as a capture — so that the server does not hold duplicates.

**Each file only in its own folder**

26. As an operator, I want an empty Billing Folder to mean no captures and no billing file, so
    that a billing file never lands in the Load Profile CSV's folder.
27. As an operator, I want an empty Energy file folder to mean no Energy Export File, so that it
    never lands in the Load Profile CSV's folder either.
28. As an operator, I want *Save to file* on the Energy Summary page to answer "Energy file
    folder is empty" when it is, so that I set the folder rather than search another one.
29. As an operator, I want each page's help text to say "leave empty to turn this file off"
    rather than promising a fallback, so that the three pages tell one story.
30. As an operator upgrading from 0.8.2/0.8.3 with only the Load Profile folder set, I want the
    release note to say the billing file and Energy file stop until their folders are set, so that
    I am not surprised.

## Implementation Decisions

**One rule for the three export folders — no fallback.**
- The Load Profile CSV writes only to the Load Profile page's *Output folder*, the Billing
  Export File only to the Billing Folder, the Energy Export File only to the *Energy file folder*.
  An empty folder means that file is off; the 15-minute writers hold quietly (as they already do
  for a missing folder), and each page's Save button answers 422 with a sentence naming the
  empty folder on *that* page. The two fallback readers introduced 2026-09-23 are reduced to
  "the folder as stored"; the File Upload Destination reads the same three values and needs no
  fallback of its own.
- Help texts on the Load Profile, Billing, Energy Summary and Export Format pages say each file
  goes only to its own folder; the Load Profile page no longer claims the other two use it.

**The Billing Export File lives in the meter's subfolder.**
- Path: `<Billing Folder>/<sanitised Meter Serial>/<name from the billing filename template>`.
  The serial token is the same sanitised one the capture paths already use, so the subfolder is
  the capture subfolder. The writer creates the subfolder when missing. A device with no Meter
  Serial keeps holding quietly, as today.
- Nothing deletes or moves the file 0.8.2/0.8.3 wrote at the folder's top level.
- The File Upload Destination lists the billing file inside each device's subfolder against the
  billing template (the export listing becomes "folder per file, and for billing, the device's
  subfolder"); its manifest key stays `export/<name>`. The capture walk excludes any file in a
  device subfolder that matches the billing template, and the writer's temp files, so the billing
  file is never sent twice. A stale top-level billing file is not listed at all.

**Save all replaces Save billing file now.**
- One admin-only endpoint under the billing router replaces the per-device export endpoint:
  it validates that the Billing Folder is set (422 "Billing folder is empty — set it on this
  page" otherwise), refuses with 409 "already running" while a sweep is in flight, queues the
  first slice on the scheduler's one-shot lane, and answers at once with the status shape below.
  A read-only status endpoint beside it serves the page's polling; any authenticated role reads it.
- The page's button reads **Save all**, sits where *Save billing file now* sat, is rendered for an
  admin only, shows loading while the status says running, and the progress line beneath it is
  visible to every role.

**The Capture Sweep.**
- A service-level function does one *slice*: for devices in id order and, within a device,
  closed periods newest first (bill date descending, sequence ascending — the same order the
  PNG window uses), it rewrites the device's Billing Export File once, then for each period whose
  PDF target does not exist writes the capture through the existing per-reading capture function
  (PDF, then xlsx and PNG per the licence flags — the same three gates the eager path checks),
  stamps *Captured* only when the write succeeded, and stops after the capture that crosses a
  60-second budget (a named constant, not a setting). If anything is left it re-queues itself on
  the one-shot lane, so the regular jobs run between slices; when a pass finds nothing missing it
  finishes.
- "Missing" is judged by the PDF's existence in the current folder, exactly as the download
  path's render-on-miss does; a period whose PDF exists is done even if its xlsx or PNG is not
  (the download path handles those one at a time, as today). Existing files are never rewritten
  (the O_EXCL write stays).
- **Review round (2026-09-23):** a period whose PDF is already present has *Captured* set from
  that file's own write time when the stamp is empty or older than the file — *Captured* means
  "when a document was last written" and the file is the fact; without it an upgraded site's
  pre-stamp documents would keep the "no document yet" count non-zero through every Save all.
  And a slice that fails outside the per-capture guard ends the sweep (status finished) rather
  than leaving it `running` and every later Save all at 409.
- A failed period is logged with the device and reading id, counted as `failed`, and skipped;
  nothing persists which periods were swept or failed (ADR 0008 — the folder is the state).
- Progress lives in one in-memory frozen dataclass, the same shape the File Upload Destination's
  status uses: `running`, `started_at`, `finished_at`, `billing_files_written`,
  `captures_written`, `captures_left`, `captures_failed`; `None` until the first Save all since
  start. The page polls it while `running`.
- Prerequisite, first ticket: the Standard capture of the older member of a same-second pair
  (`_2.png`) must render. The Billing page gains an optional anchor (the reading id the capture
  request already seeds) that applies the PNG window's own predicate — every period up to and
  including the anchor, excluding the newer member — so the driver's row wait can be satisfied.
  Classic is unaffected (its endpoint is already keyed by the anchor).

**The warning count.**
- The billing settings response gains `captures_missing`: the number of closed periods whose
  `captured_at` is null or earlier than the Billing Folder setting's own `updated_at` (the
  settings row already carries one). Zero when the folder is empty. The page renders the sentence
  in story 17 above the Save all button when it is non-zero, and re-reads it when a sweep finishes.
  This is a hint, not a folder walk: a document deleted by hand is not counted, and a period
  captured after the folder change but then removed is not either — the sweep itself judges by the
  folder.

**Docs.**
- ADR 0023 gains an amendment: the fallback is withdrawn, each file only in its own folder;
  ADR 0015 gains one: the Billing Export File shares the meter's capture subfolder. SPEC §3.6 and
  the CLAUDE.md digests follow. `.scratch/export-folders/spec.md` is marked amended. The
  installer version moves to 0.8.4 with the whole batch.

## Testing Decisions

- A good test drives an endpoint or a service function and asserts on what an operator can
  see: which path a file landed at, that a file that existed still holds its old bytes, the
  response body, the status shape, the manifest keys a fake transport received. No test asserts
  on how a slice was scheduled internally.
- **Folders**: `test_export_folders_per_file.py` is rewritten to the no-fallback rule — each of the
  three writers with its own folder set and the others empty lands only in its own folder; with
  its own folder empty it writes nothing and the Save buttons answer 422 naming that page's
  folder. The billing file's path is asserted inside the serial subfolder, and a stale top-level
  file is asserted untouched.
- **Upload cycle**: against `InMemoryTransport` (prior art `test_fileupload_cycle.py`): the
  billing file inside the subfolder arrives once as `export/<name>` beside the captures
  `captures/<serial>/…`; a stale top-level billing file is not sent; the writer's temp file is not.
- **Save all / sweep**: through the endpoint and the slice function with the suite's autouse fake
  meter and the existing screenshot test seam (`test_capture_screenshot_style.py`'s fake trigger,
  which makes a PNG write cheap and observable): a store with N closed periods across two devices
  and an empty folder ends with N PDFs after the slices run; a pre-existing PDF keeps its bytes;
  `captured_at` is stamped only for written periods; order of writes is newest first; a 409 on a
  second press while running; a 422 with the folder empty; a period made unwritable is counted
  `failed` and the rest are written; a slice stops on the budget and re-queues (budget shrunk
  through its constant, as `test_fileupload_api.py` shrinks the upload-now wait); status is
  `None` after restart. Mutation checks: drop the existence check (a pre-existing file must
  raise/skip, never be rewritten), reverse the order, drop the re-queue.
- **`_2.png` prerequisite**: extend `test_capture_screenshot_style.py`/the billing list tests: the
  list endpoint with the anchor returns the older member's window without the newer one; the
  Standard drive of an older member completes against the fake trigger.
- **Warning count**: `test_api_billing_settings.py`: null `captured_at` counts; a `captured_at`
  older than the folder's `updated_at` counts after the folder is saved again; newer does not;
  zero with the folder empty.
- Gate as always: `ruff format --check`, `ruff check`, `pytest -n auto`, `pnpm lint && pnpm build`;
  the real-Edge integration test (`ARICHDS_TEST_EDGE=1`) run by the owner from an admin shell.

## Out of Scope

- Any automatic sweep (daily job, on folder save) — the owner chose the button (grill Q1); the
  eager capture of a newly stored period is unchanged.
- Sweeping the Energy Export File or the Load Profile CSV; Save all is the Billing page's.
- Re-issuing an existing document on a style change or version change (decision ข stands).
- Deleting or moving the old top-level billing file (the owner removes it by hand).
- A per-period Regenerate button (v1 ADR 0009) — the download path's render-on-miss covers it.
- Changing the Upload Manifest contract or its version.
- Marking a swept document as written retroactively.

## Further Notes

- Site TC has twenty meters and up to thirteen periods each; a full first sweep with PNG is many
  minutes of Edge time — the 60-second slices are what keep the load-profile cycle on time. The
  capture lock already serialises Edge, so a slice and a hand-pressed download cannot collide.
- The warning count and the sweep judge "missing" differently on purpose (timestamp vs folder);
  the sentence says "yet" and the sweep is the authority.
- Upgrade note for the release: an install that set only the Load Profile folder loses its
  billing file and Energy file until their folders are set (owner accepted 2026-09-23).
