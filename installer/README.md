# ARICHDS Installer

One `setup.exe` that takes a bare Windows machine to a running, LAN-reachable
ARICHDS install — with no database questions (SPEC §2: install in under
10 minutes).

## What it does

| Step | Detail |
|---|---|
| Program files | `C:\Program Files\ARICHDS` (the PyInstaller onedir build + `nssm.exe`) |
| Data | `C:\ProgramData\ARICHDS\` — `arichds.db`, `license\`, `logs\`, `backups\`, `captures\` |
| Service | `arichds`, wrapped by NSSM: auto-start, restart on exit, stdout/stderr to `logs\service.log` rotated at 50 MB |
| Port | TCP **8000**, bound on all interfaces |
| Firewall | Inbound allow rule `ARICHDS Web UI (TCP 8000)` so other machines on the site LAN can open `http://<ip>:8000` |
| Migrations | **None here.** The service runs `alembic upgrade head` itself before serving, so install and upgrade both converge with no extra step |
| Activation | **None here.** The machine boots into Limited Mode; the operator activates from the web page, and it applies live with no restart (ADR 0001) |

## Prerequisites

### 1. Build the app

```powershell
cd app
.\packaging\build.ps1
```

This builds the web UI and freezes the backend, producing `app\dist\arichds\`.

### 2. Drop in NSSM (vendor binary — never committed)

Download NSSM from <https://nssm.cc/download> and place the **64-bit** binary at:

```
installer\vendor\nssm.exe
```

`installer\vendor\` is gitignored on purpose: NSSM is third-party redistributable
and does not belong in this repository's history. Every machine that builds an
installer needs this drop, and the Inno compile fails with a clear
"file not found" if it is missing.

### 3. Install Inno Setup

Inno Setup **6** (6.7.x) from <https://jrsoftware.org/isdl.php>. The compiler is `iscc.exe`.

> **Deliberately v6, not v7.** Inno Setup 7 exists (7.0.x, first released 2026-07) but is a
> weeks-old major whose only new capabilities (64-bit compiler, long-path support) this
> installer doesn't use — and the installer is the one component that must be boring on
> unattended customer machines. `.iss` scripts are backward compatible and v6/v7 coexist,
> so revisit v7 after a few patch releases (sensible point: before the M10 pilot).

## Building the installer

```powershell
iscc installer\arichds.iss
```

Output: `installer\Output\arichds-setup-0.1.0.exe`.

## Upgrading

Run the newer `setup.exe` over the old install. It stops the service before
replacing files (`PrepareToInstall`), reinstalls, and starts it again. The
database, the license and the logs are untouched, and the service brings the
schema to head on its next start.

## Uninstalling

Uninstall stops and removes the service, deletes the firewall rule, and removes
`C:\Program Files\ARICHDS`.

**`C:\ProgramData\ARICHDS` is deliberately preserved.** Meter history, the
license and the logs survive an uninstall/reinstall cycle. Removing them would
be unrecoverable, so it is a manual decision — delete that folder by hand if you
really mean it.

## After installing

1. Open `http://localhost:8000/` (the installer offers this at the end).
2. The machine is in **Limited Mode**. The Activation page shows its
   **Machine ID** — copy it and send it to the vendor.
3. The vendor issues an Activation Code:
   ```
   python tools\arichds_vendor.py sign --customer "Customer Name" --machine-id <64-hex>
   ```
4. Paste the code into the Activation page. It takes effect immediately — the
   poller starts and the Monitor page appears with no service restart.

## Troubleshooting

| Symptom | Check |
|---|---|
| Service will not start | `C:\ProgramData\ARICHDS\logs\service.log` (NSSM's capture) and `arichds.log` (the app's own rotating, credential-redacted log) |
| Web UI unreachable from another machine | The firewall rule exists (`netsh advfirewall firewall show rule name="ARICHDS Web UI (TCP 8000)"`) and nothing else holds port 8000 |
| Uninstall hangs | An `nssm remove` without `confirm` opens a GUI dialog. The script always passes `confirm`; if you removed it by hand, put it back |
| Activation refused with `WRONG_MACHINE` | The Machine ID sent to the vendor does not match this machine. Re-copy it from the Activation page — it is bound to the hardware |
