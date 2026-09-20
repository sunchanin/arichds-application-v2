# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

**ARICHDS Application v2** — a Windows-installed meter-monitoring app (DLMS/COSEM only — Modbus
stays in the owner's separate Go program, ADR 0026 — 9 models, 3 brands): reads meters, stores locally, serves a local web UI, pushes data to the
team's central server. A ground-up remake of v1 (`C:\Users\HP\Documents\Work\cewe`) with one
process · one exe · one SQLite DB · one license — replacing v1's two services (Python + Go),
MySQL, and ~30 tables.

> **New session?** Read `SPEC.md` first — it is the baseline (grilled + scrutinized
> 2026-08-03). Then `CONTEXT.md` for the glossary. `docs/REMAKE-PLAN.md` holds the full
> rationale/evidence behind every decision; `docs/adr/` holds decisions that reverse v1
> patterns.

## Authoritative standards (read these first)

- `SPEC.md` — scope, functional requirements per module (§3), stack (§4), milestones +
  open questions (§5). **SPEC wins over v1 code when they conflict.**
- `CONTEXT.md` — the glossary. Use these exact terms in code, comments, and UI
  (Interval Reading, Source, Transport Endpoint, Machine ID, Activation Code, Limited
  Mode, Output Parity …).
- `docs/adr/` — 0001 (license applies live, no restart — never cache license-derived state at
  import/startup) · 0002 (DLMS scaler read correctly) · 0003 (JWT secret generated per install) ·
  0004 (device status derived from the Poller — no health-check loop, no heartbeat table) ·
  0005 (meter identity comes from the meter — probe before the row exists) ·
  0006 (Manual Reads outrank background polling on the Transport Endpoint lock) ·
  0007 (the Poller tick proves liveness, not data — no live-value display, nothing
  instantaneous persisted; **fully implemented**: item 1 with issue #6 — Monitor and
  `/readings/latest` are gone; items 2/3/5/6 with issue #8 — the tick reads the Meter Serial and
  discards it, and `interval_readings` became `load_profile_readings`, empty until M5) ·
  0008 (the load-profile watermark is the data, not a job record — no job table, no `read_end`,
  no persisted scheduler state; **fully implemented**: the read path with issue #15, the
  one-thread job-registry scheduler with issue #16, and the watermark becoming **per
  `(device, logger)`** with issue #24 — which *implements* the ADR's own Decision rather than
  reversing it; the shipped code had been taking the MIN across loggers, which stalled one
  logger behind another) ·
  0009 (billing has **one** read path — every read reads the whole buffer, so "Backfill"
  dissolves as a concept; no backfill endpoint, no `billing_backfilled_at`, no is_latest
  reconciler — the invariant it healed becomes two partial unique indexes instead;
  **fully implemented**: the `billing_readings` schema, the 43-column span read, the read
  path and the read-only page all landed with issue #21/M6a · extended at M4c (#24/#25):
  the column key became **`(OBIS, attribute)`** because a max-demand value and its capture
  time share one OBIS, the 43-column span became a **driver attribute** rather than a module
  constant, and the profile OBIS / bill-date candidates / reset-reason key / cumulative-demand
  COSEM class all became per-driver declarations) ·
  0010 (the capture directory is an operator setting while the backup directory is fixed —
  a capture is a document a human carries to a customer, a backup is not; **do not "make these
  consistent"**; **fully implemented**: the `settings` table, `capture_dir` API/form, path
  validation, the two renderers off one shared section module, the hardened write and the
  render-on-miss download all landed with issue #22/M6b) ·
  0011 (a model's capabilities come from its **driver**, not the catalog — **reverses** the
  "catalog copied from v1 verbatim, locked" rule for the three capability booleans only, because
  v1's flags claimed 9/6/6 models against drivers that implement 3/1/1; keys, brands, order and
  fixed passwords stay locked; a flag turns on from a meter, never a datasheet; **fully
  implemented**: issue #28/M7-1 landed `supports_energy_registers()`/`read_energy_registers()`
  and `supports_special_days()`/`read_special_days()` on `MeterDriver` — the
  `supports_energy_summary`/`supports_special_days` *values* already matched what this ADR
  proposes, confirmed on real ST-3CL hardware 2026-08-11, so no flag flip was needed for those
  two — and issue #29/M7-2 landed the third: `supports_battery()`/`read_battery_status()` on
  `MeterDriver`, implemented on the three CEWE models, with `supports_battery` corrected from
  all nine models to exactly those three; `test_catalog.py` now asserts the driver-catalog
  correspondence for all three flags instead of a hardcoded list. **Narrowed again 2026-09-16, ui-audit
  ticket 04**: the register is "undefined object" on both Prometer 100 units and the Saral 305 and answers
  only on the Premier 550 (`docs/meter-notes/cewe-battery-scan.md`, `scripts/probe_battery.py`), so
  `supports_battery` is now true for **Premier 550 alone**; a flagged meter whose read still fails is one
  WARNING per device per day kept in memory, and the Battery page names that failure instead of an empty
  table) ·
  0012 (**SUPERSEDED by ADR 0022** — `GET /api/energy/summary` no longer aggregates
  `load_profile_readings` live; the paragraph below records what 0012 decided and why, kept for
  history rather than because it is still the shipped read path. The Energy Export File and Save to
  file followed it onto `energy_summary_days` with M14 ticket 04 (ADR 0023), so the only live caller
  of `db/energy_query.py::energy_summary_rows()` left is the recompute job itself) (the
  Energy Summary was **derived on every request and deliberately not reproducible** — adding a
  Holiday today changed what last January reported tomorrow, and that was the point, because
  holidays are rules a human enters late; no summary table, no cache; the peak window stays a
  constant so there is only ever **one** retroactive knob and it tracks reality;
  **fully implemented** with issue #28/M7-1, bounded to 31 local days, until M14 ticket 01
  replaced the read path — see 0022 below) ·
  0013 (display units are a **view**, an appended file is a **contract** — the machine-wide
  kW/W setting reaches anything rendered per request, and never the Load Profile CSV, which
  appends for months under a header written once; **reverses** v1's `divide_by_1000`, which
  write-time normalization already made vacuous; the setting itself shipped in `bbdd6b7`;
  **fully implemented** with issue #30/M7 slice 3: the boundary landed on the Load Profile CSV
  — `export/` never imports the render-time scale machinery, and the mixed-unit capture folder
  stays a **recorded shipped gap** — now filed as `docs/issues/019`, because GitHub #32 was
  filed for it and closed without the fix; the code is still unchanged, so believe the ADR's
  Outstanding section over the tracker.
  **Amended at M13 (issue 01, `19b68ac`), and that amendment is SUPERSEDED by ADR 0023**
  (2026-09-14): M13 closed a file under a dated name when its head changed and let those Closed
  Editions accumulate; ADR 0023 makes every export file mirror our 90-day window instead
  (billing: every closed period), rewritten atomically, one head per file, no editions — because
  the customer's stated constraint is disk space (ADR 0020). The core rule above — units never
  reach a file — stands. **Closed Editions are gone as of M14 ticket 02**: `export/writer.py`'s
  `_roll` is deleted, `head_changed()` tells a caller when the on-disk head no longer matches, and
  `replace_rows()` swaps a temp file over the target in one `os.replace` — a head change now
  rewrites the whole file in place (each of the three files' own "whole current content" query)
  instead of opening a dated edition, and a caller that skips the `head_changed` check gets a
  refused append rather than a corrupted file. M14 tickets 04 and 05 then made the rewrite the
  normal path — Energy and Billing are rewritten every cycle, the Load Profile CSV is trimmed
  daily; see ADR 0023 below) ·
  0014 (the capture image is **drawn, never screenshotted** — Pillow as a third renderer over
  `_render_shared`; shipped with issue #35 and **REVERSED by ADR 0017** — read 0017 first, and do
  not cite 0014's "no screen to photograph" premise or its 250 MB browser costing, both of which
  a working prototype disproved on 2026-08-22) ·
  0015 (**three capture formats share one filename stem while only the `.png` spans ten
  periods** — `<capture_dir>/<serial>/<bill_date>.{pdf,xlsx,png}`, where the pdf and xlsx hold
  that one period and the png holds the ten most recent; it looks like a bug and is a decision
  the owner made explicitly, so **do not "fix" it** by renaming, suffixing or foldering;
  **fully implemented** with issue #35) ·
  0016 (a customer's database is a **destination, not our store** — MySQL cannot express the
  partial unique indexes ADR 0009's invariant rests on, and making their database the store
  would make their downtime our downtime; FTP upload, a customer MySQL and a replicated folder
  are all the same shape, a **Data-out Destination**, which is SPEC §3.8's surface; the
  presentation-only pages landed with issue #37. **Three transports, do not conflate them**:
  the **Database Destination** (the customer's own MariaDB/MySQL, SPEC §3.10) **landed with
  issue #46** — `dataout/`, the `dbdest_sync` scheduler job, the three
  `/api/settings/database-destination` endpoints and a working
  `web/src/pages/DatabaseDestination.tsx` — whose Host and Database fields are **not** required as
  of `docs/issues/023` (2026-09-18): an empty host or database is the off state the page's own
  "sync is off while Host is empty" sentence always promised and the API always accepted, and the
  form no longer blocks it (the same class of gap `docs/issues/022` closed on the FTP page; no
  "only the active tab" guard here, since this page has one tab); the **central-server push** (SPEC §3.8, JSON + JWT,
  no watermark — each cycle asks the server what it holds, ADR 0024) **landed with M14 ticket
  08**, its own queue, separate contract, separate module (`centralpush/`); the **File Upload
  Destination** (menu **FTP**, SPEC §3.8, ADR 0025) had its configuration land with ticket 01 —
  `fileupload/`, `api/file_upload.py` and a working `web/src/pages/FileUploadDestination.tsx`
  with its three protocol tabs — and the upload cycle itself, the Upload Manifest model and the
  one transport seam landed with ticket 02, registered as the `file_upload` scheduler job, last
  and one behind `central_push`; proven against an in-memory transport only at first — the three
  real transports (SFTP/FTPS/HTTPS, tickets 03-05) all landed, so every protocol the page offers
  now moves real bytes. **HTTPS landed with ticket 03**:
  `fileupload/https_transport.py`'s `HttpsTransport` implements the seam over `urllib` alone
  (no `httpx`/`requests`), reusing the Central Push client's own split-timeout opener — factored
  out first, in its own commit, into `arichds/split_timeout_http.py` (the neutral module both
  now import, parametrised by timeout rather than each hand-copying the connect/read-split
  recipe) — `_build_transport()` in `cycle.py` returns a real `HttpsTransport` for
  `active_protocol == "https"`, so a page saved
  on the HTTPS tab genuinely moves bytes; `POST .../https/test` (mirroring
  `database-destination/test`'s "HTTP 200 on every outcome") reports `ok` /
  `unreachable` / `timed_out` / `unauthorized` / `other` from a manifest `GET` on the short
  connect timeout (`FILEUPLOAD_HTTPS_TEST_CONNECT_TIMEOUT_SEC`); the three endpoints are
  published on the API page's **Files (optional)** section, rendered by
  `centralpush/contract.py::render_contract()` from the same
  `MANIFEST_PATH`/`FILE_PATH_PREFIX`/`SHA256_HEADER` (`X-ARICHDS-File-Sha256`) constants the
  transport itself builds requests from, contract version unchanged at 1. **Remote root reaches
  the wire only through `PUT .../v1/files/{relative path}`, decided rather than left open**: the
  two manifest endpoints (`GET`/`PUT {url}/v1/files/manifest`) are deliberately un-prefixed,
  because a receiving server scopes a manifest by the token/URL it issued — each machine gets its
  own — not by a path segment; spec.md story 10 ("several machines share one server by choosing
  different roots") is satisfied because it is the *files* that collide when several machines
  write under one root, and Remote root is exactly what keeps their relative paths apart. A
  receiving team joining a manifest key to a stored object path must still know the manifest's
  own keys are the **un-prefixed** relative path — see `_render_files_contract()`'s notes) ·
  0017 (the capture image is a **headless screenshot of our own page** — **reverses 0014**:
  Edge ships with Windows and `websockets` already arrives via `uvicorn[standard]`, so driving
  the installed browser over CDP costs **0 MB** and makes fidelity an identity rather than an
  approximation; the price is that Edge itself cannot run as LocalSystem (`msedge.exe` exits
  1002 under `nt authority\system`) and that the image is truncated exactly as the screen is,
  which the owner chose; 0015 and 0010 are untouched; **fully implemented** with issue #38 —
  `capture/screenshot.py` drives Edge over CDP against a seeded `web/src/capture.ts` request
  (`app/` decides which ten periods, never the page's own defaults), the DOM/JS contract lives
  in `capture/dom.py`, and `capture/png.py`'s Pillow renderer is gone — **corrected by issue
  #40**, which replaced #38's own fix: #38 read "the service can no longer run as LocalSystem"
  too widely and moved the *whole service* to `NT AUTHORITY\LocalService`, which broke a
  `capture_dir` (ADR 0010) or export folder (issue #30) under `C:\Users\…` on the first real
  install (LocalService cannot write there); #40 puts the service back on **LocalSystem** and
  launches only Edge through a Windows scheduled task, `ARICHDS Capture Browser`
  (`installer/register-capture-task.ps1`), registered to `NT AUTHORITY\LOCAL SERVICE` and
  triggered with `schtasks /run` — `capture/task.py` is the installer↔app contract for that
  task, the same shape `capture/dom.py` is for the web↔app one; `%ProgramData%\ARICHDS\tmp`
  is the only directory carrying a `[Dirs] Permissions:` grant, and it is now Edge's one
  reused profile directory rather than a fresh one per capture, so captures are serialised by
  a process-wide lock) ·
  0018 (billing has **two read shapes but still one write path** — a fifteen-minute *change
  check* rides the **Load Profile cycle's existing connection** and triggers the unchanged
  whole-buffer read only when the newest bill_date it finds actually changed; ADR 0009's "one
  read path" is about how rows are *produced*, and that is untouched. **Not `entriesInUse`** —
  a full ring saturates it (`smw110w4-scan.md:71`), which would be silent after about a year.
  `BILLING_INTERVAL_SEC` stays daily as a **backstop**, deliberately, so do not "fix" it to
  900. Measured, because the first draft guessed: the saving is 33–73 % of a cycle, not 13x,
  and the real cost is the association — Premier 550 was seen at **95.5 s** to connect;
  **fully implemented, with two corrections, by issue #43**: the ADR's own literal steps 2–3
  were wrong on real hardware and are amended in the ADR text itself rather than silently
  overridden — the newest *entry* is the Open Period on every model shipped today and its
  `bill_date` advances on every single read (CONTEXT.md — Open Period), so comparing against
  it would have fired the whole-buffer read on every tick; the actual signal is the newest
  **closed** period, found by reading two entries and classifying them with the driver's own
  `_classify_open`. And the comparison keys on `device_id` alone, not `(device, meter_serial)`
  — both driver read paths already store `meter_serial=None` when the serial register read
  fails after the buffer was read, which would have made the filtered `MAX` come back `NULL`
  forever and fired a full read every cycle. `MeterDriver.billing_newest_closed_bill_date()` /
  `BILLING_NEWEST_ENTRY_FIRST` (base default `True`, entry ordering is a property of the
  profile per the gurux-dlms skill) landed on `base.py`, `_dlms_profile.py` and `smw110.py`;
  `billing_change_check()` landed on `billing.py`; the wiring inside
  `load_profile.py::_read_while_holding` runs the check **after** the logger walk and
  **before** `disconnect()`, gated to the background path only (a Manual Read must not grow a
  whole billing read on a path someone is waiting on), and fires
  `read_and_store_billing(device_id, background=True)` **after** the Transport Endpoint lock
  block has exited — `PriorityEndpointLock` is not reentrant, so calling it from inside that
  lock would return `skipped=True` silently while every fake-lock unit test stayed green) ·
  0019 (a meter is **licensed individually, not just counted** — `max_meters` already gates the
  *count*; a **Meter Activation Code** is signed per meter and bound to **Meter Serial + Machine
  ID**, checked once at Create, grandfathering devices that predate it and stacking with
  `max_meters` rather than replacing it; the price is that an RMA and a hardware migration both
  cost new codes; the vendor half landed with issue #41 —
  `licensing/meter_activation_code.py` and `tools/arichds_vendor.py sign-meter` (**there is no
  `/activate-meter` endpoint** — this digest named one until 2026-09-11 and none was ever
  specified: #41's own criteria ask only that a code can be issued and verified, and the
  verification happens at Create, in `api/devices.py:785-809`) — the product half landed with
  issue #42: the nullable `devices.
  meter_activation_code` column (migration 0013), the gate wired into `create_device` between
  `_reject_duplicate_serial` and the row write, and the Add-device form field. **Update needs no
  code check** — the ADR's own text originally described one ("re-checked at Update when the
  serial changes"), but the shipped `_reject_changed_serial` (ADR 0005) already refuses *any*
  Update whose probed serial differs from the stored one, unconditionally, which is stricter than
  a re-check would be; adding one would only re-open the bypass by loosening that refusal. The
  ADR's "When it is checked" section is amended in place to say so.
  **Amended again (full-version licence, issue 01): whether the gate applies at all is now
  decided by the machine's own Activation Code** — `require_meter_activation`, a field on the
  signed payload beside `max_meters` and `models`, where **unstated means not required**, so the
  full version is sold by saying nothing and adds meters with no code. Deliberately **not** a
  feature key: `features` names what the product may *do*, this names what the operator must
  *supply*, and a `features: null` licence would otherwise have picked it up automatically. A
  supplied code is still verified either way, switching it never disturbs a device already added,
  and there is still no check at Update (the licensed-model list *is* checked at both, because a
  device can be edited onto another model but cannot be moved onto another meter). ·
  0020 (a destination **mirrors our window, it never archives** — the customer's MySQL holds
  exactly the 90 days our own store holds, so the sync **deletes from their database** as well as
  writing to it; the owner chose this against the grill's recommendation, and it is why a
  `DELETE` fired into someone else's database is deliberate rather than a bug. It dissolves the
  silent data-loss window an append-only destination would have past day 90. **Do not "fix" the
  asymmetry it creates**: deleting a device erases its billing from the destination on the next
  cycle but leaves its load profile for up to 90 days, because billing is replaced wholesale and
  load profile is appended; **fully implemented with issue #46**: `dataout/sync.py`'s
  `_purge_destination` deletes past `RETENTION_DAYS` from the customer's
  `load_profile_readings` in `DELETE … LIMIT` batches, `_replace_billing` writes billing
  wholesale inside one transaction and **never purges it**, and the purge runs even when the
  append hit its budget so the window cannot drift. One correction the implementation forced,
  in the ADR's favour: the ADR says nothing records that a purge ran, and nothing persisted
  does — but the page needs a status, so the counts live in one in-memory frozen dataclass
  (`dataout/status.py`) that resets on restart, which is ADR 0008-clean) ·
  0021 (a destination **speaks local time** — UTC stops at our boundary; the store stays UTC and
  the invariant above is untouched, but the Database Destination receives
  `METER_LOCAL_UTC_OFFSET_HOURS`-shifted values in `DATETIME` (never `TIMESTAMP`, whose
  conversion depends on the customer's `my.cnf`). This names a rule that already held —
  `export/format.py:162` and the web pages both convert — rather than inventing one; the hazard
  is that the load-profile watermark now compares local against UTC, absorbed by one shared
  conversion plus `INSERT … ON DUPLICATE KEY UPDATE` on a rewound watermark — **not `INSERT
  IGNORE`**, which dedups the same way but swallows data errors even under `STRICT_TRANS_TABLES`,
  measured on MariaDB 10.4.32; **fully implemented with issue #46**: `dataout/sync.py`'s
  `_to_local` / `_from_local` are the one pair the row write, the watermark read and the purge
  cutoff all go through, and `dataout/schema.py` maps every `DateTime(timezone=True)` to a naive
  `DATETIME`. `dataout/` imports nothing from `export/`, as this ADR's Consequences require, and
  `test_dataout_sync.py` asserts that rather than trusting it. Two corrections the real server
  forced, both about the *implementation's* research rather than the ADR's own text: PyMySQL
  reports **2003** for an unresolvable host as well as for a refused connection — not 2005, and
  not the C client's 2002 — so the Test connection check keys on neither; and SQLAlchemy's
  `CreateTable` renders a `UniqueConstraint` inline but emits a plain `Index` as a **separate**
  statement, so `reconcile` must create the secondary indexes itself or the destination silently
  gets none) ·
  0022 (the Energy Summary is **stored and recomputed over the whole 90-day window every cycle** —
  **supersedes 0012**: one row per meter per local day that the page, the Energy Export File and
  the central push all read, so the three cannot disagree; a Holiday change and a late Interval
  Reading both land within one cycle with no trigger for either; `updated_at` moves only when
  values change; a **Holiday Change** log (who/when/which day, all five paths) kept 90 days;
  measured at ~0.07 s per meter for the full window, and the owner's largest site is under 20
  meters. **The stored table and the recompute landed with M14 ticket 01**
  (`.scratch/central-push/issues/01-energy-summary-is-stored-and-recomputed.md`): migration 0017
  creates `energy_summary_days` (device, local date, the eight buckets, `updated_at`, unique on
  device+local date, cascades with the device); `db/energy_summary_store.py`'s
  `energy_summary_recompute_cycle()` is the `energy_summary_recompute` scheduler job, registered
  immediately behind `load_profile` at the same interval — it re-runs the **unchanged**
  `db/energy_query.py::energy_summary_rows()` aggregation over the whole retention window per
  device and upserts only the days whose buckets actually differ, so `updated_at` stays quiet on
  a repeat recompute — and a stored day *inside* the window that the live aggregation no longer
  produces (its readings deleted, or a re-read reclassified every interval all-invalid) is deleted
  in the same pass, never left to linger until Retention; `GET /api/energy/summary` now reads that
  table (`stored_energy_summary_rows()`) instead of aggregating live, with its response shape and
  31-day bound unchanged; `db/retention.py::purge_expired()` drops rows past the same
  local-day-shifted `RETENTION_DAYS` window the recompute maintains. **The Energy Export File and
  Save to file moved onto the stored table with M14 ticket 04**: both now call
  `stored_energy_summary_rows()` instead of the live `energy_summary_rows()` aggregation — see
  0023 below for the file's own every-cycle rewrite — and the Holidays page's per-change
  computation is retired with it: `HolidayMutationOut` dropped `affected_date`/
  `energy_files_written_past`, `db/energy_query.py::most_recent_occurrence`/
  `energy_files_written_past` are deleted, and the page shows one fixed "will be recalculated
  within 15 minutes" notice on every Holiday change instead. **The Holiday Change log itself
  landed with M14 ticket 06**: migration 0019's `holiday_changes` (no `device_id`, machine-wide
  like `holidays`) is written in the same transaction as each of the five mutation paths —
  `api/holidays.py`'s `_record_holiday_change`/`_record_import_change`, called before the one
  `session.commit()` each handler already had, so a refused mutation (a collision, a 29 February
  annual) records nothing and a commit failure rolls both writes back together — and also logged
  to the App Log; `GET /api/holidays/changes` reads it newest-first under the router's existing
  `energy_summary` gate, open to any signed-in role; `db/retention.py` purges it on `created_at`
  alongside `device_events`; the recalculation notice now also fires after both imports, which
  ticket 04 had left out) ·
  0023 (export files **mirror our window and are rewritten, never archived** — **supersedes 0013's
  M13 amendment**, extends 0020 to the export folder: Load Profile CSV and Energy file hold 90
  days, the Billing file every closed period; LP appends and is trimmed daily with retention, the
  two small files are rewritten whole every cycle; every rewrite is temp-then-replace; Closed
  Editions are gone. **The atomic-replace primitive and the in-place head-change rewrite landed
  with M14 ticket 02**: `export/writer.py::replace_rows()` is the temp-file-then-`os.replace`
  swap, `head_changed()` is what a caller checks before choosing it over the cheap
  `append_rows()`, and each of the three files gained its own "whole current content" query
  (Load Profile: the 90-day merged query, same skew cap and all-invalid exclusion; Billing:
  every closed period, unfiltered; Energy: the live `energy_summary_rows()` 90-day window at that
  point). `append_rows()` no longer rolls a mismatched head to a dated file; it refuses, on the
  assumption a caller has already checked `head_changed()`. **Energy and Billing rewritten whole
  every cycle landed with M14 ticket 04**: `export/energy_csv.py::export_device_energy` and
  `export/billing_csv.py::export_device_billing` call `replace_rows()` unconditionally now —
  `head_changed()` is gone from both, because a normal cycle already does what a head change used
  to trigger specially; Energy reads `energy_summary_days` (today inclusive, so a wrong partial-day
  number is corrected next cycle rather than held back) and Billing reads every closed period,
  unfiltered — both drop their `_exported_through` watermark (migration 0018 removes
  `devices.billing_exported_through`/`devices.energy_exported_through`, and nothing in the
  application reads or writes either column any more); a device with nothing stored in its window
  still holds quietly rather than writing an empty file, the same choice the Load Profile CSV
  already makes, with the one residual gap flagged rather than silently fixed: a device that stops
  reporting for a whole retention window leaves its last Energy file in place rather than being
  emptied (Billing cannot hit this — a closed period is never deleted, ADR 0009). **The Load
  Profile CSV's own daily 90-day trim landed with M14 ticket 05**: `export/csv_export.py` gained
  `trim_device_load_profile_csv()` / `csv_trim_cycle()`, the Scheduler's `lp_csv_trim` job
  (`constants.py::JOB_LP_CSV_TRIM` / `LP_CSV_TRIM_INTERVAL_SEC`, aliased to
  `RETENTION_INTERVAL_SEC` the way `ENERGY_SUMMARY_RECOMPUTE_INTERVAL_SEC` aliases
  `LOAD_PROFILE_INTERVAL_SEC`), registered immediately behind `retention`. It reuses ticket 02's
  whole-window rewrite (`_replace_whole_window`, factored out of the head-change branch into a
  helper both paths now share) **unconditionally**, every day, rather than only on a head change —
  the fifteen-minute `csv_export` cycle still only ever appends or rewrites on an actual head
  change, never to trim the window on its own. The file may still hold up to 91 days between
  trims, exactly as ADR 0023's own Consequences section says) ·
  0024 (the **central push holds no state and is signed** — customer requirement E4: billing, load
  profile, energy summary and the meter roster, JSON every 15 min; **our** versioned contract,
  published on the in-app API page from the same models that serialize the payload; no
  `sync_state` — each cycle asks the server what it holds; Meter Serial not `device_id`; ISO 8601
  with offset; a **Push Token** JWT signed EdDSA with the existing vendor key, domain-separated from
  an Activation Code, verified by public key with a server-side denylist — **never run `keygen`**;
  no URL configured = no push. **The Push Token issue/verify primitive landed with M14 ticket
  03**: `tools/arichds_vendor.py sign-push --machine-id <64-hex>` prints a real JWT — unlike
  `sign`/`sign-meter`'s one-dot custom format — signed EdDSA with the same private key, loaded
  exactly as `sign` loads it; `app/src/arichds/licensing/push_token.py`'s `verify_push_token()`
  accepts it and returns the Machine ID, or refuses with `MALFORMED` / `INVALID_SIGNATURE` /
  `WRONG_PRODUCT` / `UNSUPPORTED_VERSION` / `LICENCE_CODE_NOT_PUSH_TOKEN`. Domain separation
  needed no code in the two licence verifiers: a JWT has two dots and an Activation Code's/Meter
  Activation Code's own format has exactly one, so `activation_code.py`'s and
  `meter_activation_code.py`'s existing dot-count guard already refuses a Push Token as
  `MALFORMED`. The other direction gets its own reason: the Push Token verifier recognises
  either licence format by its shape (one dot, a JSON payload naming `arichds`) and refuses it as
  `LICENCE_CODE_NOT_PUSH_TOKEN`, without checking its signature, so an operator who pastes the
  wrong secret into the Push Token field is told which mistake they made.
  **The configuration, the admin endpoints and the published contract landed with M14 ticket
  07**: `app/src/arichds/api/central_push.py` is the first caller of `verify_push_token` —
  `GET`/`PUT /api/settings/central-push` (config: URL + write-only Push Token, `token_set`
  rather than the token itself, never returned — `CentralPushOut` has no `token` field, and
  `central_push_token` ends in the literal `token` so the existing redaction filter pattern
  already covers it with no new pattern), `GET .../status` (always `None` until ticket 08) and
  `GET .../contract`, all `AdminDep` and gated by **no licence feature key** — ADR 0024's own
  text, "no separate licence key". `GET .../status` reads `None` until a first cycle has run,
  which ticket 08 below makes true again after a fresh install/restart (ADR 0008: it resets).
  Saving a token verifies it and additionally requires its
  Machine ID to equal `LicenseService.machine_id` (never a new derivation); a rejected token
  changes nothing and the response names which check failed (`MALFORMED` /
  `INVALID_SIGNATURE` / `WRONG_PRODUCT` / `UNSUPPORTED_VERSION` /
  `LICENCE_CODE_NOT_PUSH_TOKEN` / this endpoint's own `WRONG_MACHINE`). `app/src/arichds/
  centralpush/` is the new module ADR 0024 asks for, separate from `dataout/`: `contract.py`
  declares contract version 1 as Pydantic models — `LoadProfileItem`/`BillingItem`/
  `EnergySummaryItem`'s measurement columns are built by walking the ORM model's own columns
  (`LoadProfileReading`/`BillingReading`/`EnergySummaryDay`) rather than typed out by hand, so
  "every measured column" cannot go stale — and `render_contract()` renders the published
  document from `model_fields`, never a hand-written duplicate list, so a field added to a
  model reaches the API page with no other edit; `status.py`'s in-memory `CycleStatus` slot is
  populated by ticket 08 below (ADR 0008: no persisted job state). Web: an
  **API** page under the Data-out group (`web/src/pages/CentralPush.tsx`), admin-only like its
  two siblings but `kind: "always"` in `features.ts` (no licence key), which also means the
  Data-out group header no longer disappears on a licence lacking `database_destination` — this
  entry alone now holds it up. **The cycle itself — the scheduler job, the holdings/push HTTP
  client, and everything that writes `centralpush/status.py` — landed with M14 ticket 08**:
  `centralpush/client.py` is the stdlib-`urllib`-only transport (hard constraint — no
  `httpx`/`requests` in the product) — `GET /v1/holdings` and `POST /v1/push`, every request
  carrying `Authorization: Bearer <Push Token>`, with **separate connect and read timeouts**
  (`CENTRAL_PUSH_CONNECT_TIMEOUT_SEC`/`CENTRAL_PUSH_READ_TIMEOUT_SEC`) that plain
  `urlopen(timeout=)` cannot express — a small `http.client.HTTPConnection` subclass fixes the
  connect timeout before `connect()` and re-`settimeout`s the live socket for reads, wired into
  `urllib.request` through a custom opener; a non-2xx, a timeout or an unreachable host all
  collapse into one `PushRequestError` carrying only the failure's class name, never the URL or
  the token. `centralpush/cycle.py`'s `central_push_cycle()` is the `central_push` Scheduler job
  (`jobs/scheduler.py`), registered **last**, one behind `dbdest_sync` — the cycle asks holdings
  first, sends the meter roster as a full snapshot every time (`send_when_empty=True`, the only
  way the server learns every device is gone), then billing/Energy Summary/load profile gated
  per kind by `feature_enabled` (background-path shape, no `Request`) and each kind's own
  `updated_at`/`read_at` watermark from the holdings answer — load profile's is rewound by
  `CENTRAL_PUSH_LOAD_PROFILE_REWIND_SEC` (60 s, ADR 0024's "small safety margin"; deliberately
  smaller than `DBDEST_WATERMARK_REWIND_SEC`'s 3600 s, which exists for a timezone-crossing
  hazard — ADR 0021 — this wire, carrying an explicit UTC offset, does not have). A device with
  no known Meter Serial is skipped and counted, for every kind including the roster; any HTTP
  failure — the holdings read or a push — ends the whole cycle `"skipped"` right there, with no
  retry inside the cycle (the next cycle's holdings answer is the retry) — `CycleOutcome` is now
  `Literal["success", "skipped"]` (renamed from ticket 07's `"unreachable"`/`"timed_out"`, its
  own reviewer's nit, to match this wording). Tests (`test_central_push_cycle.py`) run against
  `fake_central_push_receiver.py`, an in-process `ThreadingHTTPServer` implementing contract
  version 1 on `127.0.0.1:0` — an ephemeral port so `pytest -n auto` workers never collide —
  verifying the Push Token with `verify_push_token` and upserting on the contract's own natural
  keys; every test asserts only on what it holds. ·
  0025 (the **File Upload Destination speaks three protocols and keeps its state in a
  server-side manifest** — menu label **FTP**, the customer's own word (CONTEXT.md's glossary
  term stays *File Upload Destination*; the two disagree on purpose) — a third Data-out
  Destination beside the customer's database (ADR 0016/0020/0021) and the Central Push (ADR
  0024): SFTP (paramiko, ticket 04), FTPS (explicit TLS, standard library, ticket 05) and HTTPS
  (the push's own split-timeout `urllib` client, ticket 03) copy the export files and the Billing
  capture documents to a server the operator names, one protocol active at a time, and an
  **Upload Manifest** — plain JSON on the *server*, not this machine (ADR 0008) — is what lets a
  cycle send only what changed; nothing is ever deleted remotely, unlike the Database
  Destination's Mirror Window (ADR 0020). **Ticket 01 landed the configuration only**: `fileupload/`
  (`config.py`'s settings loader, `status.py`'s in-memory last-cycle slot, always `None` until
  ticket 02 lands a cycle) and `api/file_upload.py` — `GET`/`PUT .../sftp`/`PUT .../ftps`/
  `PUT .../https`/`GET .../status`, all admin-only and gated by `require_feature`
  (`"file_upload_destination"`), the same shape `database-destination`'s endpoints use; saving a
  tab makes it the active protocol and the other two keep what they hold; a password/passphrase/
  token is write-only (`…_set` booleans only, never echoed) and an omitted or `null` one keeps
  the stored value the same way `db_dest_password` does; the SFTP tab is refused when its host is
  non-empty and neither a password nor a key-file path would be configured after the save —
  checked against the *effective* value, not just what the request sent. **An empty host/URL on
  the active tab is the off state and is savable** (`docs/issues/022`, 2026-09-18, amending the
  ADR's Consequences in place): the cycle publishes `not_configured` and builds no transport,
  every other field is kept, and an empty save on a tab that is *not* the active one — including
  when nothing is active yet — is a 422 naming the way out (`_refuse_empty_unless_active`, the one
  helper the three `PUT`s share); ticket 01's unconditional "HTTPS tab refused with no URL" is
  gone, and the three page buttons read **Test saved connection** because the test endpoints take
  no body.
  `file_upload_destination` left `RESERVED_FEATURE_KEYS` (now empty) and is sold exactly like
  `database_destination`; `web/src/features.ts` gates the page `kind: "feature"` on that key with
  on-screen label **FTP**, and `AppShell`'s nav entry follows. **One correction the
  implementation forced**: the ticket's own text claimed the existing credential redaction filter
  already covered a key ending in `passphrase` "with no new pattern" — false, because
  `passphrase` does not contain the substring `password`, the only thing the filter's `password`
  pattern matches; `logging_config.py` gained a dedicated `passphrase` pattern in this same
  change, proven by `test_fileupload_config_api.py`'s `TestSecretsNeverReachALog`. **HTTPS landed
  with ticket 03**: `fileupload/https_transport.py::HttpsTransport` fills the transport seam for
  `active_protocol == "https"` — `GET`/`PUT {url}/v1/files/manifest` and `PUT
  {url}/v1/files/{relative path}` (the file body plus its sha256 in the `X-ARICHDS-File-Sha256`
  header), every request carrying `Authorization: Bearer <token>`, over the Central Push client's
  own split-timeout `urllib` opener — factored out first into `arichds/split_timeout_http.py` so
  neither module hand-copies the connect/read-timeout-split recipe (or its `check_hostname`
  hazard) a second time. `POST .../https/test` mirrors `database-destination/test`: HTTP 200 on
  every outcome (`ok`/`unreachable`/`timed_out`/`unauthorized`/`other`), the short connect timeout
  (`FILEUPLOAD_HTTPS_TEST_CONNECT_TIMEOUT_SEC`, 5s). The three endpoints are published on the API
  page (`central-push`) as a **Files (optional)** Collapse panel, rendered from the same
  path/header constants the transport itself uses — contract version unchanged at 1. Remote root
  reaches the wire only through the file-put path, never the two manifest endpoints — a receiving
  server scopes a manifest by the token/URL it was issued, not by a path segment. **SFTP landed
  with ticket 04**: `fileupload/sftp_transport.py::SftpTransport` fills the transport seam for
  `active_protocol == "sftp"`, driving `paramiko.Transport` directly rather than `SSHClient` —
  one pinned fingerprint per server row, not a `known_hosts` file, so `SSHClient`'s
  `MissingHostKeyPolicy` (and the demo-only `AutoAddPolicy` this product must never reach for)
  never enters the picture; `Transport.get_remote_server_key().fingerprint` is read immediately
  after the handshake, **before** any authentication attempt, so the fingerprint is always
  observable whether or not the connection goes on to authenticate. **Host key pinning is
  asymmetric by design**: a real transport (what the cycle builds) refuses outright —
  `HostKeyNotPinnedError`/`HostKeyMismatchError`, both `TransportError` subclasses whose class
  name alone reaches the cycle's status/log — the moment a fingerprint is missing or wrong,
  never authenticating against an unverified server; `check_sftp_connection` (`POST
  .../sftp/test`) is the one place allowed to *observe* an unpinned or changed fingerprint and
  report it, still without authenticating past that point. **`POST .../sftp/host-key` is the
  only write path for the pinned row** — nothing in `sftp_transport.py` or `cycle.py` ever
  writes it, proven by `test_fileupload_sftp_transport.py::TestHostKeyPinning::test_a_cycle_never_pins_on_its_own`
  driving a whole cycle against an unpinned fake server and asserting the stored fingerprint
  setting stays empty. Password or key-file authentication (key file wins when both are
  configured); the key is read from disk at connect time under the service account, never at
  save time, via `PKey.from_path` (paramiko 5.0.0 — auto-detects RSA vs Ed25519 from the file's
  own contents, no manual "try Ed25519 then RSA" needed). `mkdir` is walked one path segment at
  a time with a `stat()` first, since a real `sshd`'s "already exists" mkdir failure carries no
  errno to test (`docs/lib-notes/paramiko-sftp.md` §3). Every paramiko/OS-level failure collapses
  through one shared classifier (`_classify_exception`, mirroring `https_transport.py`'s own
  single classifier) into a bare `TransportError` carrying only the original exception's class
  name — never a host, a credential, or a paramiko message that might carry one. Tests
  (`tests/fake_sftp_server.py`, an in-process paramiko server — `tests/_stub_sftp.py`'s shapes
  reimplemented locally, since that file ships with paramiko's source checkout, not the
  installed package) cover password and key-file auth, the manifest round trip, a changed host
  key being refused by both the transport and Test connection, and a wrong password surfacing as
  `TransportError("AuthenticationException")`, never a bare paramiko exception. paramiko and
  PyNaCl (paramiko 5's own hard runtime dependency, not an extra) are the one runtime addition
  this whole feature makes — `pyinstaller-hooks-contrib`'s `hook-nacl.py` already collects
  PyNaCl's compiled `_sodium` cffi extension with no hook of our own needed; a onedir build grew
  by ~1.07 MiB (75,894,788 → 77,018,224 bytes, measured 2026-09-17). **FTPS landed with ticket
  05, the last of the three transports**: `fileupload/ftps_transport.py::FtpsTransport` fills
  the seam over the standard library's `ftplib.FTP_TLS` alone — explicit `AUTH TLS` (called
  directly, ahead of `login()`, so the certificate can be read before any credential is sent),
  passive mode, `PROT P`, `TYPE I` fixed for the whole session (measured: `SIZE`, used to test
  whether the manifest exists, is refused in ASCII mode — `550 SIZE not allowed in ASCII mode`
  — on a real server). **No CA-file field** (ADR 0025 Out of Scope): `FtpsTransport` and
  `check_ftps_connection` both take a keyword-only `ssl_context: ssl.SSLContext | None = None`
  that defaults to `ssl.create_default_context()` at call time — a constructor seam for tests
  only, never a setting; the product (the cycle, `POST .../ftps/test`) never passes one, so a
  self-signed certificate is refused in production exactly as measured against a real
  `pyftpdlib` `TLS_FTPHandler` (`docs/lib-notes/pyftpdlib-tls.md`): `ssl.SSLCertVerificationError`.
  Every other measured failure matched the digest's own table without correction: wrong
  credentials raise `ftplib.error_perm` (`530`), a missing remote directory or manifest the same
  class (`550`), a refused port `ConnectionRefusedError` — all collapse through one shared
  classifier (`_classify_exception`, the `https_transport.py`/`sftp_transport.py` shape) into a
  bare `TransportError` carrying only the original exception's class name. `mkd` is walked one
  path segment at a time, each `error_perm` swallowed (not idempotent on a real server, the same
  shape SFTP's `mkdir` has, `docs/lib-notes/pyftpdlib-tls.md` §6). Certificate subject for
  `POST .../ftps/test` is read off `ftp.sock.getpeercert()["subject"]` right after `auth()`, and
  rendered as a `CN=…` readable string. Tests (`tests/fake_ftps_server.py`, an in-process
  `pyftpdlib` `TLS_FTPHandler` with `tls_data_required=True`) cover a self-signed certificate
  refused, the same certificate trusted through the test's own `load_verify_locations`
  succeeding byte-equal with the manifest round-tripping, a wrong password surfacing as
  `TransportError("error_perm")`, and nested `captures/<serial>/` directory creation — no
  runtime dependency added; `pyftpdlib[ssl]` (PyOpenSSL, plus `pyasynchat`/`pyasyncore` resolved
  automatically for Python 3.12+) is dev-only. No PyInstaller build was needed for this ticket
  (nothing runtime changed). **Corrected in round 1 (five reviewer findings)**: Test connection
  now actually lists the remote root over the *protected, passive* data channel (`ftps.nlst(...)`,
  never `ftps.cwd(...)`, which is control-channel-only and so never caught a blocked/NAT-broken
  passive channel — exactly ADR 0025's own reason FTPS was nearly dropped); `ftps.timeout` (not
  only the socket's own `settimeout`) is set to `FILEUPLOAD_FTPS_READ_TIMEOUT_SEC`, since
  `ftplib.FTP.ntransfercmd` reads the former, not the latter, for every passive data connection it
  opens; `_classify_exception` now reads the 3-digit reply code off an `error_perm` and only
  `530`/`532` become `bad_credentials` — a server refusing `PROT P`/`PBSZ` used to be misreported
  as a wrong password; `tests/fake_ftps_server.py` refuses `PORT`/`EPRT` outright, so a dropped
  `set_pasv(True)` is now caught (it previously traced correct but was pinned by no test — a
  loopback fake tolerates active mode); the same fixture's `passive_ports` pin is gone (it rested
  on a false premise about what the port range controls, `docs/lib-notes/pyftpdlib-tls.md` §3,
  corrected in the same round) since the default already binds `127.0.0.1` for both control and
  data.) ·
  0026 (**Modbus stays in the owner's separate Go program — v2 reads DLMS/COSEM only**, 2026-09-18:
  M4b is dropped, reversing REMAKE-PLAN D1 "port the Go program to Python" and SPEC's
  one-process goal for Modbus sites; all 9 models keep a DLMS driver, so coverage is unchanged;
  the `source` column and `SOURCE_MODBUS` stay as a reserved value no code writes, never a
  read-path branch; no integration with the Go program — an assumption to revisit the first time a
  site needs one UI or one push for both)
  **Note**: `SPEC.md` also cites an "ADR 0016" in several places that is **v1's** numbering —
  TOU buckets, holidays, `showDirectoryPicker` — and is unrelated; those now read "ADR 0016 (v1)".
- `.claude/skills/fastapi/` — **mandated API style** (Annotated params/deps, pyproject
  entrypoint, lifespan). Read before writing any FastAPI code.
- `.claude/skills/gurux-dlms/` — **mandated before touching any Gurux/DLMS code**: drivers,
  vendored `GX*.py`, the probe and poller read paths, anything importing `gurux_dlms` /
  `gurux_net` / `gurux_common`. Ported to v2 (2026-08-05) with every import verified against
  the installed `gurux_dlms 1.0.201`; patterns are marked *in v2 today* vs *v1-proven, not
  in v2 yet* so nobody cites v1 code as if it were ours.
- `docs/meter-notes/` — OBIS and capture-object maps **scanned off real meters**, not vendor
  datasheets: `load-profile-capture-objects.md` (CEWE ×3, 2026-08-05 — including the evidence
  that SPEC §3.5's Logger-1/2 merge is impossible), `lp-new-columns-scan.md` (the M13
  columns read off the Prometer 100, 2026-09-09 — every scaler resolved, `export_reactive_kvar`
  cross-checked 12/12, and the two things measurement could **not** close),
  `prometer100-load-profile-access.md` (2026-09-20, lab + customer site — the Prometer 100
  **refuses every entry-access read** of its load profile and answers a range holding no entries
  with `Data Block Unavailable` rather than `[]`; together they kept a two-day-old buffer at zero
  stored rows, fixed by `load_profile_oldest_reading` falling back to
  `now − (entries_in_use + 1) × capture_period`, measured 10–20 min early against the true oldest
  row; the mid-buffer gap stall stays open as `docs/issues/024`; the HDLC-framed Prometer 100
  (`docs/issues/025`) is **resolved**: **Framing** (CONTEXT.md) is a field of the `net` transport —
  `ConnectionParams.framing`, stored only when chosen, never part of the Transport Endpoint — and
  a driver *declares* what it was measured on (`MeterDriver.SUPPORTED_FRAMINGS`, empty = no
  choice; `Prometer100Driver` = `("wrapper", "hdlc")`, its HDLC argument list being the Premier
  550's flag for flag, proven against the lab HDLC meter); `factory.supported_framings()` feeds
  the catalog's `framings`, the Devices form shows the field only when there is a choice, and
  `_require_supported_framing` answers 422 before any socket opens;
  `scripts/probe_lp_buffer.py` / `dist/probe_lp_buffer.exe` is the carry-to-site probe that found it), plus
  `tcc-obis-scan.md` and `mitsu-obis-scan.md` ported from v1. The skill above says *how* to read a register; these
  say *which*. Each carries its own limitations section — read it before trusting a value.

## Layout

- `app/` — Python 3.14 backend (floor `>=3.13`; the dev/build machine runs 3.14.6)
  (`src/arichds/`): FastAPI (API + serves the built SPA, one origin, no CORS) ·
  **SQLAlchemy 2** ORM + SQLite WAL + one Alembic setup (`render_as_batch=True`) · poller ·
  job-registry scheduler · licensing · `auth/` (bcrypt + PyJWT, Role enum, token service —
  HTTP-free; the guard dependencies live in `api/deps.py`) · `export/` (the three
  **export files** — Load Profile CSV (issue #30), billing CSV and Energy Summary file (M13) —
  behind **one shared writer**, `export/writer.py`, which owns the file-head rule — a head change
  rewrites the file in place under an atomic `os.replace` swap (`replace_rows()`), never M13's
  dated edition (ADR 0023, M14 ticket 02 — `_roll` is gone); `format.py` holds row/filename
  formatting. A fourth export file means a new renderer *over that writer*, never a second
  writer) · `dataout/` (the
  **Database Destination** — the customer's own MariaDB/MySQL written through SQLAlchemy Core +
  PyMySQL on the `dbdest_sync` job, issue #46; deliberately **not** part of `export/`, which
  ADR 0021 forbids it from sharing a local-time helper with) · `fileupload/` (the **File Upload
  Destination**, menu **FTP** — SPEC §3.8, ADR 0025; `config.py`'s settings loader and
  `status.py`'s in-memory last-cycle slot landed with ticket 01, imports nothing from `export/`
  for the same reason `dataout/` does not; the **Upload Manifest** model (`manifest.py`), the one
  transport seam (`transport.py`'s `Transport` Protocol + `TransportError`, carrying only a
  failure's class name — never its message, since `logger.exception` would otherwise leak it
  through `exc_info`, which the redaction filter does not scrub) and the `file_upload_cycle`
  itself (`cycle.py`) landed with ticket 02, registered **last** in the scheduler, one job behind
  `central_push` — proven against an in-memory transport only; HTTPS (ticket 03), SFTP
  (ticket 04) and FTPS (ticket 05) now all move real bytes — `_build_transport()` builds a real
  transport for every protocol the page offers.
  **Corrected at ticket 02 round 1** (reviewer findings): the export group is found by
  **listing** `export_dir` and matching each entry against the three filename templates —
  never by predicting a name and hoping it exists, which a mutation to `render_filename`
  proved could drift silently and which permanently hid an earlier day's `[date]`-templated
  file; `POST .../upload-now` returns `{finished, status}` rather than a bare status, since the
  one-shot lane can outlast the endpoint's own wait (a load-profile pass alone can exceed it,
  ADR 0018); an unconfigured cycle now publishes an explicit `"not_configured"` outcome instead
  of leaving the status `None`; and a quiet cycle (the manifest read back intact, nothing to
  send) skips the manifest write entirely rather than re-writing an identical copy every fifteen
  minutes)
  · `filename_tokens.py` (the one place the `[meter]`/`[serial]`/`[date]` export-filename tokens
  are defined — landed at ticket 02 round 1, at the package top for the same reason
  `interval_status.py` is: `fileupload/cycle.py` must not import `export/`, so
  `export/format.py::render_filename` delegates to it instead of duplicating the substitution)
  · `https_transport.py` (the **HTTPS transport**, landed with ticket 03 — `HttpsTransport` fills
  the `Transport` seam over `urllib` alone; `check_https_connection()` is `POST .../https/test`'s
  own check, sharing the same request logic; `cycle.py::_build_transport()` returns it for
  `active_protocol == "https"`, so the scheduler job and `Upload now` genuinely move bytes)
  · `sftp_transport.py` (the **SFTP transport**, landed with ticket 04 — `SftpTransport` fills
  the `Transport` seam over paramiko, driving `paramiko.Transport` directly rather than
  `SSHClient` for one-fingerprint-per-row host-key pinning; `check_sftp_connection()` is `POST
  .../sftp/test`'s own check and `describe()`'s own shared classifier, the same split
  `https_transport.py` uses; `cycle.py::_build_transport()` returns it for `active_protocol
  == "sftp"`; `POST .../sftp/host-key` (`api/file_upload.py`) is the only write path for the
  pinned fingerprint row — see the ADR 0025 digest above for the host-key asymmetry and the
  onedir size delta)
  · `ftps_transport.py` (the **FTPS transport**, landed with ticket 05, the last of the three —
  `FtpsTransport` fills the `Transport` seam over the standard library's `ftplib.FTP_TLS` alone;
  `check_ftps_connection()` is `POST .../ftps/test`'s own check and `describe()`'s own shared
  classifier, the same split `https_transport.py`/`sftp_transport.py` use;
  `cycle.py::_build_transport()` returns it for `active_protocol == "ftps"` — every protocol the
  page offers now moves real bytes; see the ADR 0025 digest above for the measured exception
  classes and the no-CA-file test seam)
  · `interval_status.py` (the one
  Interval Status decoder, at the package top because `api/` must not import `export/` — that
  direction closes a cycle through `api/deps` -> `jobs/scheduler` -> `export/csv_export`).
  `split_timeout_http.py` (the package top, ticket 03's own prefactor) is the one place the
  connect/read-timeout-split `urllib` opener recipe lives — `centralpush/client.py` and
  `fileupload/https_transport.py` both call `build_split_timeout_opener()` with their own
  timeout constants rather than each carrying a hand-copied connection-subclass pair.
  Venv at `app/.venv`, `pyproject.toml` + pip.
- `app/scripts/` — read-only hardware probes, run by hand. **They are acceptance criteria, not
  scratch work**: `fake_meter` is autouse in the suite, so no automated test can prove a driver
  change against a real meter. `probe_lp_new_column_scalers.py` and `probe_lp_column_fill.py`
  derive their targets from `LOAD_PROFILE_COLUMN_MAP`, so they cannot go stale the way the
  first hand-written version of the scaler probe already had.
- `web/` — Vite + React + TS + **AntD v6 re-themed** (deep teal `#0f766e`, compact, light,
  English-only UI). No Tailwind — AntD tokens + its layout primitives cover the UI. pnpm.
- `installer/` — Inno Setup script (`arichds.iss`) + NSSM service wrapper
  (`installer/vendor/nssm.exe` is a vendor drop, never committed) +
  `register-capture-task.ps1` (registers the `NT AUTHORITY\LOCAL SERVICE`
  scheduled task the capture browser runs under, ADR 0017, issues #38/#40).
  Installs to `Program Files\ARICHDS`, data at
  `%ProgramData%\ARICHDS` (`arichds.db`, `license\`, `logs\`, `backup\`,
  `tmp\` (the capture browser's one **reused** Edge profile directory, ADR 0017, issue #40 —
  never `%TEMP%`, and the only `[Dirs] Permissions:` grant in the tree), and
  `secret\jwt_secret.key` —
  generated on first run, ADR 0003; deleting it signs everyone out). Port 8000, firewall
  rule. Migration runs at service start — no installer migrate step. The service itself runs
  as **LocalSystem**; only the capture browser's scheduled task runs as
  `NT AUTHORITY\LOCAL SERVICE` (ADR 0017, issue #40 — corrects issue #38's own fix, which had
  moved the whole service there) — see `installer/README.md`.
- `tools/` — vendor-side CLI: Ed25519 keygen + Activation Code + Meter Activation Code
  signing. Private keys are NEVER committed.
- `mockups/` — throwaway comparison app that decided D4 (AntD). Do not extend.
- `docs/` — REMAKE-PLAN + ADRs, plus `lib-notes/` (per-module API digests), `meter-notes/`
  (register maps scanned off real meters) and `issues/` (local issue files for work that does
  not warrant a GitHub issue — `/run-issue docs/issues/NNN-*.md` runs them without touching `gh`).

## Commands

```bash
# Backend (app/)
.venv\Scripts\activate            # Windows venv
fastapi dev                        # dev server (entrypoint in pyproject [tool.fastapi])
ruff format . && ruff check . --fix
pytest -n auto                     # full suite in parallel — 190–290s across 16 workers (2464 tests, measured 2026-09-17; 143s/2163 on 2026-09-11)
pytest tests/<file>::<test>        # one file/test — plain, NEVER -n auto (workers cost 6.4s, the run costs 0.1s)
python -m alembic upgrade head     # manual; app also auto-migrates at startup

# Frontend (web/)
pnpm dev                           # proxies /api -> localhost:8000
pnpm lint && pnpm build            # build fails on type errors

# Packaging  (this machine has no pwsh — PowerShell 5.1 only; build.ps1 is 5.1-compatible)
powershell -File app/packaging/build.ps1   # PyInstaller onedir -> arichds.exe
iscc installer/arichds.iss                 # Inno Setup 6 (requires nssm.exe vendor drop)
```

Updating an install = run the newer `setup.exe` over it (bump `AppVersion` in
`installer/arichds.iss` first — it is hardcoded and drives what Programs and Features
reports). Re-testing a build locally needs no installer: stop the service, `robocopy` the
onedir over `Program Files\ARICHDS` excluding `nssm.exe`, start it again —
`installer/README.md` → Upgrading has the exact commands.

## Invariants (load-bearing — violating these is a bug even if tests pass)

- **The product only ever READS a meter — it never writes to one** (owner, grill M6 2026-08-09).
  No register write, no clock set, no MD-reset, no configuration push, on any transport, in any
  module, ever. The meter is the authority; we are an observer. This is stated separately from
  the read-only rule for the *test* meters below because it is a property of the shipped
  product, not a lab courtesy — and it is the reason billing periods are read as the meter cut
  them rather than cut by us.
- **Interval Readings are UTC + kWh + COSEM column names, normalized at write time in the
  driver** — never at read time. No source-dependent branches on the read path; `source`
  is data, not control flow.
- **Concurrency locks key on the Transport Endpoint** (`host:port` / COM port), not
  `device_id` — devices sharing a serial line queue behind one lock.
- **Manual Reads outrank background ticks on that lock** (ADR 0006) — a background tick
  that cannot have the endpoint is *skipped*, never queued, and never preempts one in
  flight. The registry lives in `acquisition/locks.py` and is **process-wide**, never
  Poller-private: a probe must take the same lock with the Poller switched off and
  across `poller.restart()`.
- **License state is read through the re-evaluatable license service** (ADR 0001) — never
  cached at import/startup. Activation takes effect without a restart.
- **No `if/elif` on meter model in generic code** — model differences live behind
  `MeterDriver` capability methods (v1 ADR 0004 principle).
- **OBIS/register maps and vendored Gurux (`GX*.py`) are copied from v1 verbatim** — they
  are field-proven; never "improve", rename, or reformat their APIs.
- **Credential redaction filter on every log handler** — keys like `password=`, `passphrase=`,
  `*_key=`, `token=` become `[REDACTED]`.
- **Auth is user JWT only** — no API keys, no inbound M2M surface. Data leaves the box only
  through a **Data-out Destination we drive outbound** — the Database Destination
  (ADR 0016/0020/0021, issue #46, `dataout/`), the central-server push (SPEC §3.8, ADR
  0024, `centralpush/`, M14 ticket 08) and the File Upload Destination (menu **FTP**, SPEC
  §3.8, ADR 0025, `fileupload/`, ticket 01 for configuration, ticket 02 for the cycle itself,
  ticket 03 for the first real transport (HTTPS), ticket 04 for the second (SFTP, host-key
  pinned) and ticket 05 for the third (FTPS, explicit TLS, no CA-file field) — every protocol
  the page offers now moves real bytes), which are **three transports
  and three contracts, not one** (SPEC §3.10). Nothing external reads our tables.
- **English-only UI** — no Thai strings in `web/` (v1 had them; do not carry them over).

## v1 as reference (read-only)

`C:\Users\HP\Documents\Work\cewe` is the proven baseline: **business logic is
customer-confirmed ground truth; internals are not.** Domain modules must reproduce v1's
numbers at v1's default settings (**Output Parity** — see CONTEXT.md), but never port v1's
load-once license pattern, per-module scheduler threads, dual-DB access, or table sprawl.
Real test meters (read-only, normal 60s cadence, **never write to them**) — models confirmed
from v1's own driver comments, TCP reachability re-tested 2026-08-09:

| Model | Endpoint | |
|---|---|---|
| CEWE **Prometer 100** | `203.170.151.152:4059` (password `ABCD0001`) | ✅ open |
| CEWE **Saral 305** | `203.170.151.217:4059` | ✅ open |
| CEWE **Premier 550** | `49.229.159.44:`**`50001`** | ✅ open — **note the non-default port**; transport is a property of the install, not the model |
| **SMART TCC** (3CL) | `203.170.148.103:4059` | ❌ timeout on 4059 *and* 50001 — no response at all, so this is a link/firewall problem we cannot fix from here. **5 of the 9 supported models sit behind it** |

Connection patterns in `cewe/cewe-worker/scripts/probe_*.py`.

## Workflow — module ladder with test gates

Milestones M2–M8 run **one module at a time** (SPEC §5): a module = backend + its FE pages
+ tests, gate passed before the next starts. Per-module cadence:

```
/grill-with-docs M(n)  →  docs digest (once, if new libs)  →  /to-issues (that module only)  →  /run-issue per issue
```

Do NOT create issues for modules that have not been grilled. "เทสผ่าน" per module =
`ruff format --check` + `ruff check` + `pytest -n auto` (app), `pnpm lint` + `pnpm build` (web),
**Output Parity vs v1** for LP/Billing/Energy, real-meter read for acquisition work.

The full suite is the gate — **never narrow it to "the tests for what I changed"**, because the
party choosing the subset is the one with an incentive to under-scope, and this codebase's changes
cross layers routinely (a base-class rename touched 7 files; an `endpoint` fix broke a lock key two
modules away). It costs 143s with `-n auto`, so there is nothing to buy by skipping it. Use plain
scoped runs inside the red→green loop and `-n auto` for the gate — **and never the bare `pytest`
for the gate**, which was 428s when last measured against 1910 tests. That has happened repeatedly (`634 passed in
407.27s`, `659 passed in 299.09s` in the run logs), and it is ~5.7 minutes of the owner's wall clock
per occurrence, spent proving nothing the parallel run does not prove. The split is why there is no
`addopts` in `pyproject.toml`: a config default would fix the gate and tax every scoped run in the
loop by 6.4s, so the command has to be chosen per run, not baked in.

Two rules that keep the pipeline honest — apply them when running `/to-issues`, not inside
`/run-issue` (fixing it there is the wrong layer):

- **Write the gate into every issue's acceptance criteria.** The per-module "เทสผ่าน" items
  above (parity, real-meter read, build/lint) belong *in the issue body* — the reviewer judges
  against the issue, so a gate that lives only here won't be enforced. `/to-issues` adds them.
- **Docs digest per module, not per issue.** If a module introduces a library the repo hasn't
  used yet, produce ONE current-API digest for it and commit it under `docs/lib-notes/` so every
  issue's delegation prompt can cite it — don't re-fetch docs per issue. **Context7 IS connected
  now** (re-verified 2026-08-06 from both the main session and a subagent; the earlier "not
  connected" finding was wrong because its tools are *deferred* — they never appear in the initial
  tool list and must be loaded with `ToolSearch` before the first call). For a library this repo
  already pins, still prefer the installed source (`node_modules/*/…d.ts`, `site-packages/`) —
  it matches the pinned version and Context7 may not; use Context7 for standards and protocols
  with nothing local to read.
  Skip the digest for modules that only reuse the established stack (FastAPI, SQLAlchemy 2,
  AntD v6 — those are covered by `.claude/skills/fastapi/` and `antd-ui`).
- **A ticket that waits on a human is typed, not just labelled.** `/run-batch` and `/run-issue`
  skip a local ticket only on `Type: HITL` or a `Status:` other than `ready-for-agent` (the
  local status gate, added 2026-09-16). A placeholder written to hold a slot — "blocked until
  the grill", "needs the customer's answer" — must carry `Type: HITL` and a non-ready
  `Status:`; prose alone ("do not run this yet") is invisible to the pipeline, which would lint
  it, fail it, and hand it to Job A to invent a prompt from. And when several
  `.scratch/*/issues/` folders exist, always pass the feature slug — the batch now refuses to
  guess between them.

Issue tracker: GitHub `sunchanin/arichds-application-v2` via `gh` CLI — with `docs/issues/NNN-*.md`
as the local alternative for small leftovers (a nit an audit log parked for the owner), which
`/run-issue` and `/run-batch` accept directly. Triage labels follow
v1's five: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`.

### Branch naming — name the work, never the ticket

`<prefix>/<kebab-slug>` where the slug says what the branch *does*, in 1–4 words, ≤40 chars,
with **no issue numbers, no dates, no milestone codes**:

| Prefix | Use when | Example |
|---|---|---|
| `feature/` | new capability (module slices off the ladder) | `feature/authentication` |
| `fix/` | correcting broken behavior | `fix/poller-worker-leak` |
| `hotfix/` | an urgent break the owner flagged as such | `hotfix/license-lockout` |
| `cr/` | change request — altering agreed behavior that is not a defect | `cr/change-username-to-phone` |
| `refactor/` | internal restructuring, no behavior change | `refactor/driver-registry` |
| `chore/` | tooling, deps, packaging, CI | `chore/packaging` |
| `docs/` | documentation only | `docs/install-guide` |

Never `batch/issues-1-2`, `feature/m2`, or `feature/issue-3`. The issue number belongs in the
commit message (`feat: add login (#1)`), not in the branch name — a branch is read by humans
scanning `git branch`, and a number tells them nothing.

## Coding behavior

- **Think before coding.** State assumptions; if several interpretations exist, surface
  them. If something is unclear, stop and ask — never guess on domain behavior.
- **Simplicity first.** Minimum code that solves the problem. No speculative abstractions,
  no unrequested flexibility. Lean is a stated project goal (12 tables, 2 fixed threads).
- **Surgical changes.** Touch only what the task needs; match existing style; every changed
  line traces to the request.
- **Goal-driven.** Turn tasks into verifiable goals (failing test → make it pass).

## Definition of done

A change is not done until: the checks for every app you touched pass locally (see gates
above) · docs affected by the change are updated in the same change (`SPEC.md` for scope,
`CONTEXT.md` for vocabulary, `docs/adr/` for reversals of recorded decisions, this file for
layout/commands) · durable non-obvious learnings are saved to the memory system. Do not
commit or push unless the owner asks.
