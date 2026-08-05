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
  import/startup) · 0002 (DLMS scaler read correctly) · 0003 (JWT secret generated per install).
- `.claude/skills/fastapi/` — **mandated API style** (Annotated params/deps, pyproject
  entrypoint, lifespan). Read before writing any FastAPI code.

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
  `%ProgramData%\ARICHDS` (`arichds.db`, `license\`, `logs\`, and `secret\jwt_secret.key` —
  generated on first run, ADR 0003; deleting it signs everyone out). Port 8000, firewall
  rule. Migration runs at service start — no installer migrate step.
- `tools/` — vendor-side CLI: Ed25519 keygen + Activation Code signing. Private keys are
  NEVER committed.
- `mockups/` — throwaway comparison app that decided D4 (AntD). Do not extend.
- `docs/` — REMAKE-PLAN + ADRs.

## Commands

```bash
# Backend (app/)
.venv\Scripts\activate            # Windows venv
fastapi dev                        # dev server (entrypoint in pyproject [tool.fastapi])
ruff format . && ruff check . --fix
pytest                             # full suite; pytest tests/<file>::<test> for one
python -m alembic upgrade head     # manual; app also auto-migrates at startup

# Frontend (web/)
pnpm dev                           # proxies /api -> localhost:8000
pnpm lint && pnpm build            # build fails on type errors

# Packaging
pwsh app/packaging/build.ps1       # PyInstaller onedir -> arichds.exe
iscc installer/arichds.iss         # Inno Setup (requires nssm.exe vendor drop)
```

## Invariants (load-bearing — violating these is a bug even if tests pass)

- **Interval Readings are UTC + kWh + COSEM column names, normalized at write time in the
  driver** — never at read time. No source-dependent branches on the read path; `source`
  is data, not control flow.
- **Concurrency locks key on the Transport Endpoint** (`host:port` / COM port), not
  `device_id` — devices sharing a serial line queue behind one lock.
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
`ruff format --check` + `ruff check` + `pytest` (app), `pnpm lint` + `pnpm build` (web),
**Output Parity vs v1** for LP/Billing/Energy, real-meter read for acquisition work.

Two rules that keep the pipeline honest — apply them when running `/to-issues`, not inside
`/run-issue` (fixing it there is the wrong layer):

- **Write the gate into every issue's acceptance criteria.** The per-module "เทสผ่าน" items
  above (parity, real-meter read, build/lint) belong *in the issue body* — the reviewer judges
  against the issue, so a gate that lives only here won't be enforced. `/to-issues` adds them.
- **Docs digest per module, not per issue.** If a module introduces a library the repo hasn't
  used yet, produce ONE current-API digest for it and commit it under `docs/lib-notes/` so every
  issue's delegation prompt can cite it — don't re-fetch docs per issue. **Context7 is NOT
  connected here** (verified — any "use context7" step silently degrades); use WebFetch on
  official docs + read installed package sources (`node_modules/*/…d.ts`, `site-packages/`).
  Skip the digest for modules that only reuse the established stack (FastAPI, SQLAlchemy 2,
  AntD v6 — those are covered by `.claude/skills/fastapi/` and `antd-ui`).

Issue tracker: GitHub `sunchanin/arichds-application-v2` via `gh` CLI. Triage labels follow
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
  no unrequested flexibility. Lean is a stated project goal (13 tables, 2 fixed threads).
- **Surgical changes.** Touch only what the task needs; match existing style; every changed
  line traces to the request.
- **Goal-driven.** Turn tasks into verifiable goals (failing test → make it pass).

## Definition of done

A change is not done until: the checks for every app you touched pass locally (see gates
above) · docs affected by the change are updated in the same change (`SPEC.md` for scope,
`CONTEXT.md` for vocabulary, `docs/adr/` for reversals of recorded decisions, this file for
layout/commands) · durable non-obvious learnings are saved to the memory system. Do not
commit or push unless the owner asks.
