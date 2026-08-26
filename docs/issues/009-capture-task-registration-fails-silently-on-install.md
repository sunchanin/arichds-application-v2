# The capture browser's scheduled task is never registered, and the install reports success

**Type**: blocker · **Found**: owner hit it on a real install, 2026-08-25 · **Blocks**: shipping —
every install produced today has a Billing capture that cannot work

## What happens

The owner ran `arichds-setup-0.4.0.exe` on 2026-08-25 at 14:19. The install completed with no
error. Pressing **Capture image** on the Billing page then returned:

```
:8000/api/billing/captures/image?device_id=2   500 (Internal Server Error)
```

The scheduled task `ARICHDS Capture Browser` — the one ADR 0017 / issue #40 introduced so Edge
can run under `NT AUTHORITY\LOCAL SERVICE` while the service stays on LocalSystem — **does not
exist**, anywhere:

```
PS> Get-ScheduledTask | Where-Object { $_.TaskName -like "*ARICHDS*" -or $_.TaskPath -like "*ARICHDS*" }
(nothing)
PS> schtasks /query /fo LIST | Select-String ARICHDS
(nothing)
```

No task means no Edge, which means `BrowserCaptureError`, which the endpoint turns into a 500
whose message never mentions a scheduled task.

## The install was told it succeeded

From `%TEMP%\Setup Log 2026-08-25 #001.txt`, the [Run] entry at `installer/arichds.iss:181`:

```
2026-08-25 14:19:14.900   Filename:   C:\WINDOWS\system32\WindowsPowerShell\v1.0\powershell.exe
2026-08-25 14:19:14.900   Parameters: -NoProfile -ExecutionPolicy Bypass -File
                          "C:\Program Files\ARICHDS\register-capture-task.ps1"
                          -TaskName "ARICHDS Capture Browser" -ProfileDir "C:\ProgramData\ARICHDS\tmp"
2026-08-25 14:19:15.769   Process exit code: 0
```

Everything else the installer does landed correctly on this machine — `register-capture-task.ps1`
is in `Program Files\ARICHDS`, `%ProgramData%\ARICHDS\tmp` carries its
`NT AUTHORITY\LOCAL SERVICE` / Modify grant, the service is running as LocalSystem. Only the task
is missing, and the exit code says otherwise.

## Why the script cannot report the failure

`installer/register-capture-task.ps1:155-181` wraps the registration in `try { … } catch { exit 1 }`.
`Register-ScheduledTask` at `:176` carries **no `-ErrorAction Stop`**, and the script sets no
`$ErrorActionPreference`. A PowerShell **non-terminating** error therefore does not enter the
`catch`: execution falls through to `:178`

```powershell
Write-Output "register-capture-task.ps1: registered '$TaskName' -> $edgePath"
```

and the script exits 0. Reproduced directly — the failure and the success line print together:

```
Register-ScheduledTask : Access is denied.
register-capture-task.ps1: registered 'ARICHDS Capture Browser' -> C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
```

(That reproduction was from a non-elevated shell, so its *cause* is not the installer's cause —
see "What is still unknown". The point it proves is the reporting defect, which is
elevation-independent.)

**A second silence sits behind the first.** The script's own docstring (`:26-32`) records that
the installer never checks this script's exit code — deliberately, per ADR 0017 decision D12 — so
even the paths that *do* exit 1 correctly (Edge not found, `:137-138`) are invisible to the
install. Fixing only the `-ErrorAction` gets a message into the installer log that nothing reads.

## Why D12's reasoning did not hold

`installer/arichds.iss` (the comment above `:181`) states the intent:

> A failed registration must not fail the install (decision D12) — like every other [Run] entry
> here, its exit code is never checked, so a failure only shows up in SetupLogging's log and
> **leaves a capture failing loudly with `BrowserCaptureError` later**

Not failing the install is still the right call — a meter-reading service should install even if
one optional renderer cannot. What did not hold is "failing loudly". The failure surfaces as an
HTTP 500 whose detail is `Could not write the capture: <BrowserCaptureError text>`; nothing in it
names the scheduled task, points at `register-capture-task.ps1`, or tells the operator the
install left something undone. Loud is not the same as legible.

This cost the owner a real debugging session: the visible symptom was the *previous* defect
(render-on-miss serving a stale image, see below), and only after deleting the stale file did the
500 appear at all.

## What is still unknown — do not skip this

**Why the registration failed while the installer was elevated.** `arichds.iss:46` sets
`PrivilegesRequired=admin` and the Setup log records the entry as `Run as: Current user`, i.e.
the elevated context. `Access is denied` from a non-elevated shell is expected and is *not*
evidence about what happened at 14:19. Candidates not yet eliminated: something about
`New-ScheduledTaskPrincipal -UserId "LOCALSERVICE" -LogonType ServiceAccount` under Setup's
token, a security product blocking task creation, or a failure earlier in the script that left
`$action`/`$principal` unusable.

**Fixing the reporting without finding this only makes the breakage visible, not absent.** Both
are needed, and the root cause is the one that decides whether customers can install unattended.

### What the elevated manual run settled, and what it did not

Run by hand from an **elevated** PowerShell on the same machine, 2026-08-25, the same script with
the same arguments the installer used:

```
PS> & "C:\Program Files\ARICHDS\register-capture-task.ps1" -TaskName "ARICHDS Capture Browser" -ProfileDir "C:\ProgramData\ARICHDS\tmp"
register-capture-task.ps1: registered 'ARICHDS Capture Browser' -> C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe

PS> Get-ScheduledTask -TaskName "ARICHDS Capture Browser" | Select TaskName,State
TaskName                State
--------                -----
ARICHDS Capture Browser Ready
```

**Settled:** the script itself is correct — given enough privilege it registers the task, and its
Edge discovery works. There is no bug in what it builds.

**Not settled, and this is the whole open question:** why the *installer* did not achieve the same
result at 14:19, when `arichds.iss:46` sets `PrivilegesRequired=admin` and the Setup log records
the entry as `Run as: Current user` (the elevated context, not `Original user`). A script that
works elevated by hand and fails from an elevated installer means the two contexts differ in some
way not yet identified.

Note that the success line above is printed unconditionally (`:178`) — it is **not** evidence the
registration worked. Only the `Get-ScheduledTask` query is. That is the reporting defect
demonstrating itself even on the run that succeeded.

### The experiment that answers it

Not yet run. Delete the task, re-run `arichds-setup-0.4.0.exe`, then query for the task again:

```
Unregister-ScheduledTask -TaskName "ARICHDS Capture Browser" -Confirm:$false
# run arichds-setup-0.4.0.exe
Get-ScheduledTask -TaskName "ARICHDS Capture Browser" -ErrorAction SilentlyContinue
```

Absent afterwards ⇒ the installer path is genuinely broken and every customer install needs a
manual step until it is fixed. Present ⇒ the 14:19 failure was situational, and the reporting and
verification fixes above are what stop it being invisible next time. **Until this is run, whether
a customer must intervene is unknown, and the safe assumption is that they must.**

## What to do

1. **Make the script fail when it fails.** `-ErrorAction Stop` on `Register-ScheduledTask`
   (`:176`), or `$ErrorActionPreference = "Stop"` at the top. One line.
2. **Verify rather than trust.** After registering, re-query the task in the same script and exit
   non-zero if it is absent — a registration that returns without error but produces no task is
   exactly the case here, and `-ErrorAction Stop` alone would not catch it.
3. **Surface it to the operator.** D12 keeps the install succeeding; it does not require the
   install to stay *silent*. The installer should tell the person at the keyboard that the capture
   browser could not be registered and what to run, rather than leaving it to a 500 weeks later.
4. **Make the 500 legible.** When the capture fails because the task is missing,
   `capture/screenshot.py` / the endpoint's detail should say so by name — the operator seeing the
   error is the person who can fix it.
5. **Find the root cause** (see above) and record it, in this file or in ADR 0017 if it changes a
   decision.

## Acceptance criteria

- [ ] A registration that fails for any reason makes the script exit non-zero, and a test or a
      documented manual reproduction proves it (a non-terminating error must not pass)
- [ ] The script verifies the task exists after registering and fails if it does not
- [ ] A failed registration is visible to the person running the installer, without reading
      `%TEMP%\Setup Log*.txt`
- [ ] The capture failure caused by a missing task names the task in its message
- [ ] The root cause of the 2026-08-25 failure is identified and written down
- [ ] A clean install on a machine with no prior ARICHDS install ends with the task present —
      verified by `Get-ScheduledTask`, not by the installer reporting success
- [ ] ADR 0017 is amended in place if any of this changes D12 or the LocalSystem/LOCAL SERVICE
      split

## Related

- ADR 0017 / issues #38 and #40 — why the task exists at all.
- `docs/issues/008` — the flaky PDF test, found in the same session.
- The stale-capture behaviour that hid this one: `.png` is written render-on-miss
  (`api/billing.py:596`, ADR 0010 decision 14) but spans ten periods (ADR 0015) while being named
  after one, so a renderer change leaves a permanently stale image. **Not yet filed** — it needs
  its own issue and an owner decision between "always re-render" and "a separate Regenerate
  button".

## Blocked by

Nothing.
