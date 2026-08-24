<#
.SYNOPSIS
    Register (or re-register) the ARICHDS Capture Browser scheduled task.

.DESCRIPTION
    Only the `msedge.exe` launch has to leave the SYSTEM account — the ARICHDS
    service itself stays LocalSystem (issue #40, replacing #38's Part A: the
    service moving to LocalService cost it write access to an operator-chosen
    `capture_dir` under `C:\Users\...`). Edge is instead started through a
    Windows scheduled task registered to `NT AUTHORITY\LOCAL SERVICE`, and the
    service triggers it with `schtasks /run` (capture/screenshot.py).

    Called from `installer\arichds.iss`'s `[Run]` section on both a fresh
    install and an upgrade — `-Force` on `Register-ScheduledTask` below makes
    a re-run converge rather than error on an already-registered task.

    A registered task with `-Force` is created "regardless of whether it
    existed prior" (mirrors the `[Dirs] Permissions:` behaviour this repo
    already relies on for the same reason), so no separate "does it already
    exist" branch is needed.

    Deliberately does NOT set `ExecutionTimeLimit` (F5, issue #40 prompt) —
    every start of this task is on-demand (`schtasks /run`), and
    `ExecutionTimeLimit` is documented to be bypassed for on-demand starts, so
    it would be dead configuration, not a safety net. `CAPTURE_BUDGET_SECONDS`
    plus its hard-timeout margin (capture/screenshot.py) is the real ceiling.

    A failed registration must not fail the install (D12) — the install
    itself never checks this script's exit code (none of the other `[Run]`
    entries in `arichds.iss` do either), so this script only needs to leave a
    clear message in the installer log; it does not need to guarantee the
    install continues by suppressing its own non-zero exit.

.PARAMETER TaskName
    The scheduled task's name — passed in rather than hardcoded so
    `capture/task.py`'s `CAPTURE_TASK_NAME` stays the single source of truth
    (the contract test greps this file for it, it does not import this
    script).

.PARAMETER ProfileDir
    Edge's reused profile directory — `Settings.tmp_dir`
    (`%ProgramData%\ARICHDS\tmp`), the one directory carrying the installer's
    `[Dirs] Permissions:` grant (decision D2, issue #40). The task's action is
    fixed at registration time, so this is no longer a fresh directory per
    capture the way the retired `subprocess.Popen` launch made one.

.EXAMPLE
    .\register-capture-task.ps1 -TaskName "ARICHDS Capture Browser" -ProfileDir "C:\ProgramData\ARICHDS\tmp"

    The exact invocation `installer\arichds.iss`'s [Run] section makes —
    `"ARICHDS Capture Browser"` is `arichds.capture.task.CAPTURE_TASK_NAME`'s
    value, pinned by `tests/test_capture_task_contract.py` so this example
    (and the `.iss`) cannot drift from it silently.

.NOTES
    PowerShell 5.1 compatible (this build machine has no `pwsh`) — see
    `app\packaging\build.ps1` for the same constraint.

    SAVED WITH A UTF-8 BOM — DO NOT STRIP IT. Verified on this machine:
    without the BOM, Windows PowerShell 5.1 reads a script file with no BOM
    using the system's default codepage (here, 1252) rather than UTF-8. The
    em-dash characters this file's comments use decode under that codepage
    to a curly quote (U+201D), which PowerShell's tokenizer accepts as an
    alternate string-closing delimiter — so the `Write-Error` message a few
    lines below, which contains an em-dash inside a double-quoted string,
    silently truncated the string and broke parsing of everything after it
    (confirmed with
    `[System.Management.Automation.Language.Parser]::ParseFile()`, which
    reported "Missing closing '}'" dozens of lines away from the real
    cause). A UTF-8 BOM makes Windows PowerShell 5.1 read this file as UTF-8
    regardless of the target machine's codepage — this ships to Thai-locale
    machines too (CLAUDE.md), where the default codepage differs again.
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$TaskName,

    [Parameter(Mandatory = $true)]
    [string]$ProfileDir
)

# The two well-known Edge install locations (mirrors
# `capture/screenshot.py`'s `_EDGE_FALLBACK_PATHS` — this machine's own copy
# is under the x86 root; never assume which one applies).
$EdgeFallbackPaths = @(
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)

# The fixed Edge flags this task's action carries — must match
# `capture/task.py`'s `EDGE_TASK_ARGUMENTS` exactly; the contract test
# (`tests/test_capture_task_contract.py`) greps this file for each one.
$EdgeArguments = @(
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    "--remote-debugging-port=0",
    "about:blank"
)

function Resolve-EdgePath {
    <#
        Registry first — Edge's install root differs across machines, never
        a hardcoded path — falling back to the two well-known Program Files
        locations. A registry value pointing at a file that no longer exists
        (a stale key left by an old uninstall) is not trusted over an
        existing fallback. Mirrors `capture/screenshot.py`'s
        `resolve_edge_path()`.
    #>
    $appPathsKey = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
    $fromRegistry = $null
    try {
        $item = Get-ItemProperty -LiteralPath $appPathsKey -ErrorAction Stop
        $fromRegistry = $item.'(default)'
    } catch {
        $fromRegistry = $null
    }

    if ($fromRegistry -and (Test-Path -LiteralPath $fromRegistry -PathType Leaf)) {
        return $fromRegistry
    }

    foreach ($candidate in $EdgeFallbackPaths) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    return $null
}

$edgePath = Resolve-EdgePath
if (-not $edgePath) {
    Write-Error "register-capture-task.ps1: Microsoft Edge was not found (registry and both well-known Program Files locations checked). The '$TaskName' task was NOT registered — a capture will fail with BrowserCaptureError until Edge is installed and this script is re-run."
    exit 1
}

# `--user-data-dir` is inserted before the last element of $EdgeArguments
# (always "about:blank", the URL Chromium opens) rather than at a fixed
# index (code review round, nit 2) — an index-splice like
# `$EdgeArguments[0..4] + ... + $EdgeArguments[5..6]` silently drops any
# flag appended to $EdgeArguments/EDGE_TASK_ARGUMENTS past index 6, and the
# contract test greps this file's text so it cannot see a dropped flag
# either. Quoted defensively in case ProfileDir ever contains a space; none
# of the other flags take a value that could.
$actionArguments = (
    $EdgeArguments[0..($EdgeArguments.Count - 2)] +
    "--user-data-dir=`"$ProfileDir`"" +
    $EdgeArguments[-1]
) -join " "

try {
    $action = New-ScheduledTaskAction -Execute $edgePath -Argument $actionArguments

    # F4: a ServiceAccount principal for LOCALSERVICE, no triggers — this
    # task is only ever started on demand via `schtasks /run`
    # (capture/screenshot.py), never on a schedule.
    $principal = New-ScheduledTaskPrincipal -UserId "LOCALSERVICE" -LogonType ServiceAccount

    # F3: `DisallowStartIfOnBatteries` defaults to True and blocks an
    # on-demand `schtasks /run` outright, with no CLI switch to override it
    # after the fact — so it must be disabled at registration time.
    # F6: `IgnoreNew` stated explicitly even though it is the settings
    # default, for intent — this is what makes `schtasks /run` refuse a task
    # still marked Running rather than starting a second Edge instance.
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew

    # -Force overwrites an existing registration so an upgrade converges
    # (D1) — no separate "does it already exist" branch needed.
    Register-ScheduledTask -TaskName $TaskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null

    Write-Output "register-capture-task.ps1: registered '$TaskName' -> $edgePath"
} catch {
    Write-Error "register-capture-task.ps1: failed to register the '$TaskName' scheduled task: $_"
    exit 1
}
