---
description: Build the frozen arichds.exe (SPA + PyInstaller onedir); optionally also compile the Inno Setup installer.
argument-hint: [installer]
allowed-tools: Bash, Read, Glob
model: sonnet
---

Build the ARICHDS frozen exe. If `$1` is `installer`, also compile the setup.exe afterward.

## Step 0 — Pre-checks

1. **Venv.** Confirm `app\.venv\Scripts\python.exe` exists (repo-root-relative). If missing, stop and tell the user to create it:
   ```powershell
   cd app
   py -m venv .venv
   .venv\Scripts\pip install -e ".[dev]"
   ```
   Do not attempt to create the venv yourself.
2. **pnpm.** Confirm `pnpm` is on PATH (`where pnpm` / `pnpm --version`). If missing, stop and tell the user to install it — do not install it yourself.

## Step 1 — Build

Prefer PowerShell 7 (`pwsh`); not every machine has it installed (`where pwsh`) — fall back to
Windows PowerShell 5.1 (`powershell.exe`, always present) if it's missing. `build.ps1` uses only
5.1-compatible syntax, so either works:

```powershell
pwsh app/packaging/build.ps1
# or, if pwsh is not on PATH:
powershell -File app/packaging/build.ps1
```

Stream its output. It does two things: `pnpm install --frozen-lockfile` + `pnpm build` in `web/`, then `pyinstaller --noconfirm --clean packaging\arichds.spec` in `app/`.

**Known failure mode — `_rust.pyd` PermissionError.** If PyInstaller fails with a `PermissionError` (or "Access is denied") touching `_rust.pyd` (or similar files under `app\dist\arichds` / `app\build`), a stale `arichds.exe` process is still holding the file open. Recover once, automatically:

```powershell
Get-Process arichds -ErrorAction SilentlyContinue | Stop-Process -Force
```

Then re-run the same build command (`pwsh`/`powershell`, whichever you used) **once**. If it fails again with the same error, stop and report the exact error — do not loop.

Any other build failure (pnpm error, PyInstaller error unrelated to the lock, missing files): stop and report the exact error text. Do not guess a fix.

## Step 2 — Report the artifact

Confirm `app\dist\arichds\arichds.exe` exists. Report its full path, file size, and last-write time. If it is missing after a reported "success", that's a bug in the build — say so, don't paper over it.

## Step 3 — Installer (only if `$1` == `installer`)

Two prerequisites, both required:

1. `iscc` on PATH (`where iscc`). If absent: this machine does not have Inno Setup 6 installed. Print the remedy from `installer/README.md` and stop gracefully (do not attempt to install it):
   ```
   Download Inno Setup 6 (6.7.x) from https://jrsoftware.org/isdl.php and install it
   (adds iscc.exe to PATH). Deliberately v6, not v7 — see installer/README.md.
   ```
2. `installer\vendor\nssm.exe` exists. If absent: it's a vendor drop that is gitignored on purpose. Print the remedy from `installer/README.md` and stop gracefully:
   ```
   Download NSSM (64-bit) from https://nssm.cc/download and place it at
   installer\vendor\nssm.exe (installer\vendor\ is gitignored — every build
   machine needs its own drop).
   ```

If both are present, run from the repo root:

```powershell
iscc installer/arichds.iss
```

Report the resulting `installer\Output\arichds-setup-*.exe` path and size.

## Never

- Never commit anything (build outputs, vendor binaries, generated files).
- Never install Inno Setup, NSSM, or any package on the user's behalf — only report the exact remedy and stop.
- Never run `pnpm install` outside `--frozen-lockfile` (the build script owns exact install semantics).
