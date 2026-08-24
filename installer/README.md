# ARICHDS Installer

One `setup.exe` that takes a bare Windows machine to a running, LAN-reachable
ARICHDS install — with no database questions (SPEC §2: install in under
10 minutes).

## What it does

| Step | Detail |
|---|---|
| Program files | `C:\Program Files\ARICHDS` (the PyInstaller onedir build + `nssm.exe`) |
| Data | `C:\ProgramData\ARICHDS\` — `arichds.db`, `license\`, `logs\`, `secret\` (the generated JWT signing key — ADR 0003; deleting it signs every user out), `backup\` (seven daily `VACUUM INTO` copies, M5c), `captures\`, `tmp\` (the capture browser's one reused Edge profile directory — issue #40) |
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

Output: `installer\Output\arichds-setup-0.3.0.exe`.

## Upgrading

### On a customer machine — the only supported path

Run the newer `setup.exe` over the old install. It stops the service before
replacing files (`PrepareToInstall`), reinstalls, and starts it again. The
database, the license and the logs are untouched, and the service brings the
schema to head on its next start.

**Bump `AppVersion` in `arichds.iss` before every release.** It is hardcoded
(`#define AppVersion "0.3.0"`) and drives both the output filename and what
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

## The service account and the capture browser task (issue #40)

The service runs as **`LocalSystem`** — NSSM's default, so the installer
sets no `ObjectName` at all for it. This reverses an earlier build (0.2.0),
which pointed the whole service at `NT AUTHORITY\LocalService`; that turned
out to be the wrong fix (see below), and this installer actively resets
`ObjectName` back on an upgrade (`nssm reset arichds ObjectName`) so a
machine that ran 0.2.0 does not silently keep the old account.

**Only the capture browser leaves LocalSystem.** The Billing capture `.png`
(ADR 0017) is a headless screenshot of the running Billing page, taken by
driving the already-installed Microsoft Edge over the Chrome DevTools
Protocol. `msedge.exe` exits **1002** immediately under `nt authority\system`
— for any argument, including `--version` — so Edge cannot run under the
account the *service* uses. #38's first attempt moved the whole service to
`NT AUTHORITY\LocalService` to work around that, and on the first real
install that broke a `capture_dir` (ADR 0010) or a Load Profile export
folder (issue #30) pointed at a path under `C:\Users\…` — LocalService
cannot write there, and `capture_reading()` swallowed the failure silently.

**issue #40 replaces that**: Edge is launched through a Windows scheduled
task, `ARICHDS Capture Browser`, registered at install time
(`register-capture-task.ps1`, installed alongside `nssm.exe`) to run under
`NT AUTHORITY\LOCAL SERVICE`. The service — still LocalSystem — triggers it
with `schtasks /run` (`capture/screenshot.py`) rather than launching Edge
itself. Edge only renders and hands bytes back over CDP; the service (as
LocalSystem, administrator-equivalent) is the one that writes the capture
file, so an operator-chosen `capture_dir` under `C:\Users\…` stays writable.
The one thing `NT AUTHORITY\LOCAL SERVICE` needs write access to is Edge's
own reused profile directory, `C:\ProgramData\ARICHDS\tmp` — the *only*
`[Dirs]` entry in `arichds.iss` that still carries a `Permissions:` grant.

### What the owner must verify after installing or upgrading

```powershell
sc qc arichds
```
Expect `SERVICE_START_NAME : LocalSystem`.

```powershell
schtasks /query /TN "ARICHDS Capture Browser" /V /FO LIST
```
Expect the task to exist, `Run As User` to read `NT AUTHORITY\LOCAL SERVICE`
(Task Scheduler and `schtasks` may display the same well-known account as
`NT AUTHORITY\LocalService` or `.\LocalService` — NSSM has nothing to do
with this display, only with the *service's* own account, `sc qc` above),
and `Status` to read `Ready` — never stuck `Running` (that would mean every
subsequent capture is refused; see Troubleshooting).

```powershell
icacls C:\ProgramData\ARICHDS\tmp
```
Expect an ACE for `NT AUTHORITY\LOCAL SERVICE` carrying **`(OI)(CI)`** and
`(M)` (modify) — scoped to this one subfolder now, not the whole
`C:\ProgramData\ARICHDS` tree (LocalSystem needs no grant on the rest of
it). **The `(OI)(CI)` inheritance flags are the thing to check.** Inno
Setup 6's `[Dirs] Permissions:` docs state the permission is applied
"regardless of whether the directory existed prior to installation," but
say nothing about whether the ACE it writes is flagged inheritable —
verified against the published docs 2026-08-22, no primary source either
way. If `(OI)(CI)` is missing, the one-time fix is:
```powershell
icacls C:\ProgramData\ARICHDS\tmp /grant "NT AUTHORITY\LOCAL SERVICE":(OI)(CI)M /T
```
This command is documentation only — **do not run it** unless `icacls`
above actually shows the flags missing.

**Residue on a machine upgraded from an earlier build (decision D4):** an
install that ever ran 0.2.0 (which granted `Permissions:` on the *whole*
`C:\ProgramData\ARICHDS` tree to `NT AUTHORITY\LOCAL SERVICE`) keeps those
ACEs — removing `Permissions:` from `arichds.iss` does not revoke ACEs
already written to disk. This is harmless (an unused grant, not a missing
one) and left as a manual cleanup if it is ever worth doing:
```powershell
icacls C:\ProgramData\ARICHDS /remove "NT AUTHORITY\LOCAL SERVICE" /T
```
This command is documentation only — **do not run it** as part of a normal
upgrade.

- The **Activation page still shows a Machine ID** after install — this is
  the proof the `MachineGuid` registry read
  (`HKLM\SOFTWARE\Microsoft\Cryptography`, `licensing/fingerprint.py`)
  succeeded under LocalSystem, which it always has (LocalSystem is
  administrator-equivalent). If it instead shows an error, the machine has
  dropped into Limited Mode (ADR 0001).
- A **Billing capture `.png` appears under `capture_dir`** for a device
  with a closed period (wait for the next scheduled billing read, or use
  the Billing page's "Capture image" button) — including when `capture_dir`
  is set to a path under `C:\Users\…`, the exact case that failed on the
  first 0.2.0 install.

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
6. Run the checks under **The service account** above.

## Troubleshooting

| Symptom | Check |
|---|---|
| Service will not start | `C:\ProgramData\ARICHDS\logs\service.log` (NSSM's capture) and `arichds.log` (the app's own rotating, credential-redacted log) |
| Web UI unreachable from another machine | The firewall rule exists (`netsh advfirewall firewall show rule name="ARICHDS Web UI (TCP 8000)"`) and nothing else holds port 8000 |
| Uninstall hangs | An `nssm remove` without `confirm` opens a GUI dialog. The script always passes `confirm`; if you removed it by hand, put it back |
| Activation refused with `WRONG_MACHINE` | The Machine ID sent to the vendor does not match this machine. Re-copy it from the Activation page — it is bound to the hardware |
| A Billing capture `.png` fails with a 500 naming Edge | `resolve_edge_path()` (`capture/screenshot.py`) could not find `msedge.exe` via the registry or either well-known Program Files location — Edge was uninstalled or is at a non-standard path |
| A Billing capture `.png` fails with a 500 naming `schtasks`, or every capture after the first one fails | The `ARICHDS Capture Browser` scheduled task is missing (registration failed at install — check `SetupLogging`'s log) or stuck `Running` (a hard-killed service left it that way; `schtasks /query /TN "ARICHDS Capture Browser"` shows `Status`). `capture/screenshot.py` runs `schtasks /end` before every `/run` as a self-heal, so a *stuck* task should clear itself on the next capture attempt; a *missing* task needs `register-capture-task.ps1` re-run by hand (see **The service account and the capture browser task** above) |
| A Billing capture `.png` fails with "Edge never wrote DevToolsActivePort", and this worked before | If `C:\ProgramData\ARICHDS\tmp` was ever deleted by hand (it is just a folder named `tmp`, easy to mistake for disposable), `Settings.ensure_directories()` silently recreates it on the next service start — but **without** the `NT AUTHORITY\LOCAL SERVICE` ACE, because that grant now comes only from the installer's `[Dirs] Permissions:` line (the service itself is LocalSystem and never re-applies it). Edge then cannot write its profile there and every capture fails the same way. Fix: `icacls C:\ProgramData\ARICHDS\tmp /grant "NT AUTHORITY\LOCAL SERVICE":(OI)(CI)M /T` (same command as the `(OI)(CI)` check above) |
