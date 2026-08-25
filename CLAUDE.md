# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

**ARICHDS Application v2** — a Windows-installed meter-monitoring app (DLMS/COSEM + Modbus,
9 models, 3 brands): reads meters, stores locally, serves a local web UI, pushes data to the
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
  correspondence for all three flags instead of a hardcoded list) ·
  0012 (the Energy Summary is **derived on every request and deliberately not reproducible** —
  adding a Holiday today changes what last January reports tomorrow, and that is the point,
  because holidays are rules a human enters late; no summary table, no cache; the peak window
  stays a constant so there is only ever **one** retroactive knob and it tracks reality;
  **fully implemented** with issue #28/M7-1: `GET /api/energy/summary` aggregates
  `load_profile_readings` live, bounded to 31 local days) ·
  0013 (display units are a **view**, an appended file is a **contract** — the machine-wide
  kW/W setting reaches anything rendered per request, and never the Load Profile CSV, which
  appends for months under a header written once; **reverses** v1's `divide_by_1000`, which
  write-time normalization already made vacuous; the setting itself shipped in `bbdd6b7`;
  **fully implemented** with issue #30/M7 slice 3: the boundary landed on the Load Profile CSV
  — `export/` never imports the render-time scale machinery, and the mixed-unit capture folder
  stays a **recorded shipped gap** needing its own issue, unchanged by this issue) ·
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
  presentation-only pages landed with issue #37. **Two transports, do not conflate them**:
  the **Database Destination** (the customer's own MariaDB/MySQL, SPEC §3.10) **landed with
  issue #46** — `dataout/`, the `dbdest_sync` scheduler job, the three
  `/api/settings/database-destination` endpoints and a working
  `web/src/pages/DatabaseDestination.tsx`; the **central-server push** (SPEC §3.8, JSON + JWT
  + an ACK-driven watermark) is still **M8 and unbuilt**, on its own queue, and
  `FileUploadDestination.tsx` remains a presentation-only shell) ·
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
  `licensing/meter_activation_code.py`, `tools/arichds_vendor.py sign-meter`, and
  `/activate-meter` — the product half landed with issue #42: the nullable `devices.
  meter_activation_code` column (migration 0013), the gate wired into `create_device` between
  `_reject_duplicate_serial` and the row write, and the Add-device form field. **Update needs no
  code check** — the ADR's own text originally described one ("re-checked at Update when the
  serial changes"), but the shipped `_reject_changed_serial` (ADR 0005) already refuses *any*
  Update whose probed serial differs from the stored one, unconditionally, which is stricter than
  a re-check would be; adding one would only re-open the bypass by loosening that refusal. The
  ADR's "When it is checked" section is amended in place to say so. ·
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
  gets none).
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
  that SPEC §3.5's Logger-1/2 merge is impossible), plus `tcc-obis-scan.md` and
  `mitsu-obis-scan.md` ported from v1. The skill above says *how* to read a register; these
  say *which*. Each carries its own limitations section — read it before trusting a value.

## Layout

- `app/` — Python 3.14 backend (floor `>=3.13`; the dev/build machine runs 3.14.6)
  (`src/arichds/`): FastAPI (API + serves the built SPA, one origin, no CORS) ·
  **SQLAlchemy 2** ORM + SQLite WAL + one Alembic setup (`render_as_batch=True`) · poller ·
  job-registry scheduler · licensing · `auth/` (bcrypt + PyJWT, Role enum, token service —
  HTTP-free; the guard dependencies live in `api/deps.py`) · `export/` (the Load Profile CSV
  auto-export — row/filename formatting and the exporter itself, issue #30) · `dataout/` (the
  **Database Destination** — the customer's own MariaDB/MySQL written through SQLAlchemy Core +
  PyMySQL on the `dbdest_sync` job, issue #46; deliberately **not** part of `export/`, which
  ADR 0021 forbids it from sharing a local-time helper with). Venv at
  `app/.venv`, `pyproject.toml` + pip.
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
pytest -n auto                     # full suite in parallel (~17s across 16 cores)
pytest tests/<file>::<test>        # one file/test — plain, NEVER -n auto (workers cost 4s, the run costs 0.05s)
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
- **Credential redaction filter on every log handler** — keys like `password=`, `*_key=`,
  `token=` become `[REDACTED]`.
- **Auth is user JWT only** — no API keys, no inbound M2M surface. Data leaves the box only
  through a **Data-out Destination we drive outbound** — the Database Destination
  (ADR 0016/0020/0021, issue #46, `dataout/`) and the central-server push (SPEC §3.8, still
  unbuilt), which are **two transports and two contracts, not one** (SPEC §3.10). Nothing
  external reads our tables.
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
modules away). It costs ~17s, so there is nothing to buy by skipping it. Use plain scoped runs
inside the red→green loop and `-n auto` for the gate.

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
