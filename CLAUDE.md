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
  no persisted scheduler state; **fully implemented**: the read path with issue #15 and the
  one-thread job-registry scheduler with issue #16) ·
  0009 (billing has **one** read path — every read reads the whole buffer, so "Backfill"
  dissolves as a concept; no backfill endpoint, no `billing_backfilled_at`, no is_latest
  reconciler — the invariant it healed becomes two partial unique indexes instead;
  **fully implemented**: the `billing_readings` schema, the 43-column span read, the read
  path and the read-only page all landed with issue #21/M6a) ·
  0010 (the capture directory is an operator setting while the backup directory is fixed —
  a capture is a document a human carries to a customer, a backup is not; **do not "make these
  consistent"**; **fully implemented**: the `settings` table, `capture_dir` API/form, path
  validation, the two renderers off one shared section module, the hardened write and the
  render-on-miss download all landed with issue #22/M6b).
- `.claude/skills/fastapi/` — **mandated API style** (Annotated params/deps, pyproject
  entrypoint, lifespan). Read before writing any FastAPI code.
- `.claude/skills/gurux-dlms/` — **mandated before touching any Gurux/DLMS code**: drivers,
  vendored `GX*.py`, the probe and poller read paths, anything importing `gurux_dlms` /
  `gurux_net` / `gurux_common`. Ported to v2 (2026-08-05) with every import verified against
  the installed `gurux_dlms 1.0.201`; patterns are marked *in v2 today* vs *v1-proven, not
  in v2 yet* so nobody cites v1 code as if it were ours.
- `docs/meter-notes/` — OBIS and capture-object maps **scanned off real meters**, not vendor
  datasheets: `load-profile-capture-objects.md` (CEWE ×3, 2026-08-05 — including the evidence
  that SPEC §3.5's Logger-1/2 merge is impossible), plus `tcc-obis-scan-partial.md` and
  `mitsu-obis-scan.md` ported from v1. The skill above says *how* to read a register; these
  say *which*. Each carries its own limitations section — read it before trusting a value.

## Layout

- `app/` — Python 3.14 backend (floor `>=3.13`; the dev/build machine runs 3.14.6)
  (`src/arichds/`): FastAPI (API + serves the built SPA, one origin, no CORS) ·
  **SQLAlchemy 2** ORM + SQLite WAL + one Alembic setup (`render_as_batch=True`) · poller ·
  job-registry scheduler · licensing · `auth/` (bcrypt + PyJWT, Role enum, token service —
  HTTP-free; the guard dependencies live in `api/deps.py`). Venv at `app/.venv`,
  `pyproject.toml` + pip.
- `web/` — Vite + React + TS + **AntD v6 re-themed** (deep teal `#0f766e`, compact, light,
  English-only UI). No Tailwind — AntD tokens + its layout primitives cover the UI. pnpm.
- `installer/` — Inno Setup script + NSSM service wrapper (`installer/vendor/nssm.exe` is a
  vendor drop, never committed). Installs to `Program Files\ARICHDS`, data at
  `%ProgramData%\ARICHDS` (`arichds.db`, `license\`, `logs\`, `backup\`, and
  `secret\jwt_secret.key` —
  generated on first run, ADR 0003; deleting it signs everyone out). Port 8000, firewall
  rule. Migration runs at service start — no installer migrate step.
- `tools/` — vendor-side CLI: Ed25519 keygen + Activation Code signing. Private keys are
  NEVER committed.
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
- **Auth is user JWT only** — no API keys, no inbound M2M surface. Data leaves the box via
  the push sync module only; nothing external reads our tables.
- **English-only UI** — no Thai strings in `web/` (v1 had them; do not carry them over).

## v1 as reference (read-only)

`C:\Users\HP\Documents\Work\cewe` is the proven baseline: **business logic is
customer-confirmed ground truth; internals are not.** Domain modules must reproduce v1's
numbers at v1's default settings (**Output Parity** — see CONTEXT.md), but never port v1's
load-once license pattern, per-module scheduler threads, dual-DB access, or table sprawl.
Real test meters reachable over TCP (read-only, normal 60s cadence, never write to them):
CEWE `203.170.151.152:4059` (password `ABCD0001`), CEWE `203.170.151.217`, SMART TCC
`203.170.148.103:4059` — connection patterns in `cewe/cewe-worker/scripts/probe_*.py`.

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
