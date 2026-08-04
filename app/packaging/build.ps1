# Build arichds.exe — the frozen, single-process Windows delivery.
#
# Steps, in order:
#   1. Build the React SPA. It is served by FastAPI from the same origin, so
#      there is no API base URL to configure — the app always calls /api
#      relative to wherever it is served from.
#   2. Freeze the backend with PyInstaller (one-folder; see arichds.spec).
#
# Run from app/:  ./packaging/build.ps1
# Output: app/dist/arichds/arichds.exe
#
# Out of scope: code signing (the installer is unsigned for now).

$ErrorActionPreference = "Stop"

$Packaging = $PSScriptRoot
$AppRoot = Split-Path -Parent $Packaging
$Repo = Split-Path -Parent $AppRoot
$WebDir = Join-Path $Repo "web"

Write-Host "=== [1/2] Building the web UI ===" -ForegroundColor Cyan
Push-Location $WebDir
try {
    pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw "pnpm install failed (exit $LASTEXITCODE)" }
    pnpm build
    if ($LASTEXITCODE -ne 0) { throw "pnpm build failed (exit $LASTEXITCODE)" }
}
finally {
    Pop-Location
}

Write-Host "=== [2/2] Freezing the backend with PyInstaller ===" -ForegroundColor Cyan
Push-Location $AppRoot
try {
    & ".\.venv\Scripts\pyinstaller.exe" --noconfirm --clean "packaging\arichds.spec"
    # $ErrorActionPreference does NOT cover native-exe exit codes. Check
    # explicitly, or a failed freeze still prints "Build complete" and the
    # caller ships a stale exe from a previous build.
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed (exit $LASTEXITCODE). If it failed while removing build\, close anything holding those files and delete app\build\ before retrying."
    }
}
finally {
    Pop-Location
}

$ExePath = Join-Path $AppRoot "dist\arichds\arichds.exe"
if (-not (Test-Path $ExePath)) { throw "PyInstaller reported success but $ExePath is missing." }

Write-Host ""
Write-Host "=== Build complete ===" -ForegroundColor Green
Write-Host "Output: $ExePath"
Write-Host "Run:    $ExePath"
Write-Host ""
Write-Host "Next: build the installer with Inno Setup:" -ForegroundColor Yellow
Write-Host "  iscc $(Join-Path $Repo 'installer\arichds.iss')"
