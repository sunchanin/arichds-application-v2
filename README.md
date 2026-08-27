# ARICHDS Application v2

Windows-installed meter-monitoring app: reads electricity meters (DLMS/COSEM + Modbus,
9 models, 3 brands), stores readings locally in SQLite, serves a local web UI, and pushes
data to the team's central server. One process · one exe · one database · one license.

> Status: **M1–M3 complete** — install → first-run Setup → Login → offline activation →
> the Devices page, where a real CEWE Prometer100 is added (its serial read off the meter),
> paused, read on demand and deleted, with every API route behind a JWT and admin user
> management in the UI. v2 shows **no live electrical values** — the 60-second poll proves
> a meter answers, it is not a display (ADR 0007). Acquisition (M4) is next; the full
> module ladder is in [SPEC.md](SPEC.md) §5.

## Quick start (development)

Prerequisites: Python ≥3.13 (dev machine runs 3.14), Node + pnpm.

```powershell
# 1. Backend — terminal A  (creates DB in app/data, runs migrations, serves API on :8000)
cd app
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\fastapi.exe dev src\arichds\main.py

# 2. Frontend — terminal B  (dev server on :5173, proxies /api -> :8000)
cd web
pnpm install
pnpm dev
```

Open <http://localhost:5173> (or build once with `pnpm build` and use
<http://localhost:8000> — the backend serves the built SPA from the same origin).

## Using the app (first run)

The walk is **Setup → Login → Activation → Devices**. The app boots in **Limited
Mode** — everything except the auth endpoints and activation is locked until a
license is applied — and activating needs an administrator, so the account comes
first.

1. **Set up the administrator.** The Setup page appears while no account exists;
   choose a username and a password (8 characters minimum). It is shown once and
   never again — from then on the app opens on Login.
2. **Sign in** with that account.
3. **Get the Machine ID.** The Activation page shows it (copy button). It is derived
   from this machine's hardware and every license is bound to it.
4. **Issue an Activation Code** (vendor side — needs the private key, first run
   `keygen` once):

   ```powershell
   cd app
   .\.venv\Scripts\python.exe ..\tools\arichds_vendor.py keygen          # once, per vendor
   .\.venv\Scripts\python.exe ..\tools\arichds_vendor.py fingerprint     # prints THIS machine's ID
   .\.venv\Scripts\python.exe ..\tools\arichds_vendor.py sign --customer "Acme Co" --machine-id <64-hex>
   ```

5. **Paste the code** into the Activation page. It applies **immediately** — no service
   restart (ADR 0001). The Devices page appears and the Poller starts.

   Later, **renewing or replacing a license on a machine that is already active** happens on
   **Settings → License**, not here — the Activation page is a gate and stops being rendered the
   moment the machine is licensed. That card shows the current customer, mode, expiry,
   `max_meters`, the licensed meter models and the enabled features, plus this machine's
   Machine ID, and takes a new code (admin only). A rejected code changes nothing; the license
   file is never edited by hand.
6. **Add a meter** on the Devices page — a real CEWE Prometer100 over TCP. The form is
   in four groups: **Identity** (device name, site name, and the record-only labels),
   **Meter** (brand and model), **Connection** (IP address, port — default 4059 — and
   password, prefilled `ABCD0001` for CEWE) and **Billing** (the bill days, stored now
   and used by M6). Press **Create Device**.

   Adding **connects to the meter first** and reads its serial number off it (ADR 0005),
   so the button takes a few seconds and the meter has to be reachable — there is no
   "add it now, identify it later". A refusal says which problem it was (credentials
   rejected, timed out, unreachable) and writes no row at all.

   Once added, the meter is polled every 60 s and its status dot in the site tree follows
   what those polls prove. **Read now** asks it immediately instead of waiting for the
   next cycle.

To reset to a clean first run in development: stop the backend and delete `app/data/`.

## Quality gates

```powershell
# Backend (app/)
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest

# Frontend (web/)
pnpm lint
pnpm build
```

All four must pass before any module is considered done (see CLAUDE.md → workflow gates).

## Production install

Build the frozen exe + installer, then run `setup.exe` on the target machine — under
10 minutes, no database questions:

```powershell
powershell -File app\packaging\build.ps1   # PyInstaller onedir + built SPA (pwsh works too)
iscc installer\arichds.iss                 # needs Inno Setup 6 + installer\vendor\nssm.exe drop
```

**Updating an existing install** means running the newer `setup.exe` over it — the service
stops, the files are replaced, and `C:\ProgramData\ARICHDS` (database, license, logs,
backups) survives. Bump `AppVersion` in `installer\arichds.iss` first, or every release reports
itself as the same version. To re-test a build on your *own* machine without compiling an
installer, see [installer/README.md](installer/README.md) → Upgrading.

Full steps, prerequisites, upgrade/uninstall behavior, and troubleshooting:
[installer/README.md](installer/README.md). After installing, the usage flow is the same
as above, at `http://<machine-ip>:8000`.

## Repository map

| Path | What |
|---|---|
| `app/` | Python backend — FastAPI, SQLite, licensing, meter drivers, Poller ([app/README.md](app/README.md)) |
| `web/` | React + AntD v6 SPA (deep-teal re-theme), built output served by the backend |
| `installer/` | Inno Setup script + NSSM service wrapper ([installer/README.md](installer/README.md)) |
| `tools/` | Vendor-side CLI: keygen + Activation Code signing (private keys never committed) |
| `SPEC.md` | The baseline spec — scope, per-module requirements, milestones |
| `CONTEXT.md` | Glossary — the project's exact vocabulary |
| `docs/` | REMAKE-PLAN (rationale for every decision), ADRs, per-module lib notes |
| `mockups/` | Throwaway UI-library comparison that decided the AntD re-theme — do not extend |

New to the repo? Read `SPEC.md` first, then `CONTEXT.md` — `CLAUDE.md` carries the
working agreements (invariants, gates, module ladder).
