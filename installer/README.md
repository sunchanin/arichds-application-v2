# ARICHDS Installer

One `setup.exe` that takes a bare Windows machine to a running, LAN-reachable
ARICHDS install — with no database questions (SPEC §2: install in under
10 minutes).

## What it does

| Step | Detail |
|---|---|
| Program files | `C:\Program Files\ARICHDS` (the PyInstaller onedir build + `nssm.exe`) |
| Data | `C:\ProgramData\ARICHDS\` — `arichds.db`, `license\`, `logs\`, `secret\` (the generated JWT signing key — ADR 0003; deleting it signs every user out), `backup\` (seven daily `VACUUM INTO` copies, M5c), `captures\` |
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

### On a customer machine — the only supported path

Run the newer `setup.exe` over the old install. It stops the service before
replacing files (`PrepareToInstall`), reinstalls, and starts it again. The
database, the license and the logs are untouched, and the service brings the
schema to head on its next start.

**Bump `AppVersion` in `arichds.iss` before every release.** It is hardcoded
(`#define AppVersion "0.1.0"`) and drives both the output filename and what
"Programs and Features" reports. Ship two different builds under one number and
nobody on site can tell which one a machine is running.

### On a build machine — testing a fresh build without Inno Setup

Compiling `setup.exe` just to re-test your own build is not worth the round trip.
Stop the service, overwrite the program directory, start it again:

```powershell
net stop arichds
robocopy app\dist\arichds "C:\Program Files\ARICHDS" /MIR /XF nssm.exe /NFL /NDL
net start arichds
```

`/XF nssm.exe` stops `/MIR` from deleting the NSSM binary the installer placed in
the program directory — the uninstaller needs it to remove the service, so losing
it leaves an install that cannot be uninstalled cleanly. Runtime data is
unaffected (it all lives in `C:\ProgramData\ARICHDS`) and migrations run at
service start, exactly as they would after a real upgrade.

## Uninstalling

Uninstall stops and removes the service, deletes the firewall rule, and removes
`C:\Program Files\ARICHDS`.

**`C:\ProgramData\ARICHDS` is deliberately preserved.** Meter history, the
license, the logs and the daily backups survive an uninstall/reinstall cycle.
Removing them would
be unrecoverable, so it is a manual decision — delete that folder by hand if you
really mean it.

## After installing

1. Open `http://localhost:8000/` (the installer offers this at the end).
2. The **Setup** page appears while the machine has no accounts. Create the
   administrator (username + password, 8 characters minimum), then sign in.
   Setup closes permanently once that account exists.
3. The machine is in **Limited Mode**. The Activation page shows its
   **Machine ID** — copy it and send it to the vendor.
4. The vendor issues an Activation Code:
   ```
   python tools\arichds_vendor.py sign --customer "Customer Name" --machine-id <64-hex>
   ```
5. Paste the code into the Activation page (an administrator account is required
   to do this). It takes effect immediately — the poller starts and the Devices
   page appears with no service restart.

## Troubleshooting

| Symptom | Check |
|---|---|
| Service will not start | `C:\ProgramData\ARICHDS\logs\service.log` (NSSM's capture) and `arichds.log` (the app's own rotating, credential-redacted log) |
| Web UI unreachable from another machine | The firewall rule exists (`netsh advfirewall firewall show rule name="ARICHDS Web UI (TCP 8000)"`) and nothing else holds port 8000 |
| Uninstall hangs | An `nssm remove` without `confirm` opens a GUI dialog. The script always passes `confirm`; if you removed it by hand, put it back |
| Activation refused with `WRONG_MACHINE` | The Machine ID sent to the vendor does not match this machine. Re-copy it from the Activation page — it is bound to the hardware |
