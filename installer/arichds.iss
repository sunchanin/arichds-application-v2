; ─────────────────────────────────────────────────────────────────────────────
; ARICHDS Application — Inno Setup installer (SPEC §3.1)
;
; One setup.exe with wizard, upgrade and uninstall built in. It installs the
; frozen onedir build to Program Files\ARICHDS, creates the data tree under
; %ProgramData%\ARICHDS, registers arichds.exe as a Windows service via NSSM,
; and opens the chosen TCP port (default 8000) so other machines on the site LAN
; can reach the web UI. The port is a wizard page: a site where another program
; already holds 8000 (a WCF service was found on one, 2026-09-16) picks a free one
; without a rebuild, and the choice is remembered for the next upgrade.
;
; What it deliberately does NOT do:
;   * No database questions. SQLite lives in %ProgramData%\ARICHDS and needs no
;     setup at all — that was the whole point of dropping MySQL.
;   * No migrate step. The service runs `alembic upgrade head` itself before
;     serving, so install and upgrade both converge with no extra action.
;   * No activation step. The machine boots into Limited Mode and the operator
;     activates from the web page, which applies live (ADR 0001).
;
; Build:
;   1. app\packaging\build.ps1        (produces app\dist\arichds\)
;   2. Drop nssm.exe at installer\vendor\nssm.exe  (see installer\README.md)
;   3. iscc installer\arichds.iss     (produces installer\Output\arichds-setup.exe)
; ─────────────────────────────────────────────────────────────────────────────

#define AppName        "ARICHDS"
#define AppVersion     "0.7.2"
#define AppPublisher   "ARICHDS"
#define ServiceName    "arichds"
; Default only — the effective port is {code:GetPort}, chosen on the wizard page
; (or remembered from the previous install), and the firewall rule is named after it.
#define DefaultPort    "8000"
#define FirewallPrefix "ARICHDS Web UI (TCP "
; Must match arichds.capture.task.CAPTURE_TASK_NAME exactly — pinned by
; tests/test_capture_task_contract.py (issue #40).
#define CaptureTaskName "ARICHDS Capture Browser"

[Setup]
AppId={{8E2B4C1A-7D3F-4A56-9B0E-3C6D5A1F2E70}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={commonpf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=arichds-setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
; The service, Program Files and the firewall rule all require elevation.
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
WizardStyle=modern
UninstallDisplayName={#AppName}
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; The whole PyInstaller onedir output, including the bundled SPA.
Source: "..\app\dist\arichds\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; NSSM is a vendor binary dropped in at package time and never committed
; (see installer\README.md). It must survive uninstall long enough to remove
; the service, so it is installed rather than used from a temp directory.
Source: "vendor\nssm.exe"; DestDir: "{app}"; Flags: ignoreversion
; The scheduled-task registration script (issue #40) — installed alongside
; nssm.exe so it is present for troubleshooting and is removed by the
; existing [UninstallDelete] of {app}.
Source: "register-capture-task.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
; All runtime data lives here and SURVIVES UNINSTALL (see [UninstallDelete] —
; which deliberately lists nothing under {commonappdata}). The service itself
; runs as LocalSystem (see [Run] below — issue #40, replacing #38's Part A),
; which needs no `Permissions:` grant at all: LocalSystem is already
; administrator-equivalent. Only `tmp\` carries one, and it names
; `NT AUTHORITY\LOCAL SERVICE` rather than LocalSystem — that is the account
; the capture browser's scheduled task runs under
; (register-capture-task.ps1), and Edge's reused profile directory
; (Settings.tmp_dir, decision D2) is the one thing that account writes.
; Applied "regardless of whether the directory existed prior to installation"
; (Inno Setup 6 docs), which is what makes this work on an upgrade of an
; existing install too — see installer/README.md for the inheritance caveat.
Name: "{commonappdata}\{#AppName}"
Name: "{commonappdata}\{#AppName}\logs"
Name: "{commonappdata}\{#AppName}\license"
; Singular: the daily backup job writes here (SPEC §5, M5c) and resolves it from
; Settings.backup_dir, which is `<data>\backup`.
Name: "{commonappdata}\{#AppName}\backup"
Name: "{commonappdata}\{#AppName}\captures"
; Edge's reused profile directory (issue #40, decision D2) — the *only*
; directory in this tree the capture browser's `NT AUTHORITY\LOCAL SERVICE`
; scheduled task needs to write to. Inside {commonappdata}\ARICHDS rather
; than %TEMP%, which resolves somewhere outside this grant under that
; account (see Settings.tmp_dir's docstring).
Name: "{commonappdata}\{#AppName}\tmp"; Permissions: service-modify

[Icons]
Name: "{group}\{#AppName} Web UI"; Filename: "http://localhost:{code:GetPort}/"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Run]
; ── Stop any previous service before files are replaced (upgrade path) ───────
; Ordering note: Inno runs [Run] after [Files], so the stop that matters for an
; upgrade happens in PrepareToInstall (see [Code]).

; ── Register the service ─────────────────────────────────────────────────────
Filename: "{app}\nssm.exe"; Parameters: "install {#ServiceName} ""{app}\arichds.exe"""; \
    Flags: runhidden waituntilterminated; StatusMsg: "Registering the {#AppName} service..."
Filename: "{app}\nssm.exe"; Parameters: "set {#ServiceName} AppDirectory ""{app}"""; \
    Flags: runhidden waituntilterminated
; The service reads its configuration from the environment. Setting it on the
; service (rather than machine-wide) keeps a dev checkout on the same box
; independent of the installed instance.
Filename: "{app}\nssm.exe"; Parameters: "set {#ServiceName} AppEnvironmentExtra ARICHDS_DATA_DIR={commonappdata}\{#AppName} ARICHDS_PORT={code:GetPort}"; \
    Flags: runhidden waituntilterminated
; ── Run as LocalSystem, not LocalService (issue #40, replaces #38's Part A) ──
; #38 concluded the whole *service* had to leave LocalSystem because
; `msedge.exe` exits 1002 under `nt authority\system` — that conclusion was
; too wide (ADR 0017's Correction, 2026-08-22): Edge only renders and hands
; bytes back over CDP, the *service* writes the capture file, and moving the
; service to LocalService cost it write access to any operator-chosen
; directory outside %ProgramData%\ARICHDS (a real 422 on the first real
; install, `capture_dir` under C:\Users\...). Only the msedge.exe launch now
; leaves SYSTEM — via the scheduled task registered below.
;
; `nssm set <service> ObjectName LocalSystem` is NOT a documented command:
; https://nssm.cc/commands's only documented `set ObjectName` form takes a
; username AND a password argument (an intentionally blank password must be
; the explicit `""`, never omitted), with no carve-out for well-known
; accounts — so `set` was ruled out rather than guessed at. `nssm reset
; <service> ObjectName` is used instead, and its correctness rests on more
; than nssm.cc's own page: nssm.cc's general wording for `reset` is
; "equivalent to removing the associated registry entry", which reads
; alarming for a parameter this load-bearing (a future maintainer who only
; reads nssm.cc could take that to mean the account is left blank with
; nothing to fall back on). The decisive evidence is in NSSM's own source
; (code review round, 2026-08-24):
; `settings.cpp`'s parameter table declares `ObjectName`'s default as
; `NSSM_LOCALSYSTEM_ACCOUNT`, which `account.h` defines as `_T("LocalSystem")`,
; and `ObjectName` is marked as a **native** SCM parameter in that same table
; (not an NSSM-only setting) — so `reset` drives `ChangeServiceConfig`
; straight to LocalSystem rather than deleting a registry value with no
; fallback. This must run unconditionally, exactly like every other `nssm
; set`/`reset` line here, because `nssm install` on an already-registered
; service is a no-op (decision D3): a machine that ran 0.2.0's LocalService
; ObjectName (this repo shipped that build once) would otherwise keep it
; silently across this upgrade.
Filename: "{app}\nssm.exe"; Parameters: "reset {#ServiceName} ObjectName"; \
    Flags: runhidden waituntilterminated
Filename: "{app}\nssm.exe"; Parameters: "set {#ServiceName} AppStdout ""{commonappdata}\{#AppName}\logs\service.log"""; \
    Flags: runhidden waituntilterminated
Filename: "{app}\nssm.exe"; Parameters: "set {#ServiceName} AppStderr ""{commonappdata}\{#AppName}\logs\service.log"""; \
    Flags: runhidden waituntilterminated
; Cap the stdout/stderr capture. NSSM leaves rotation OFF by default, which let
; a v1 install grow service.log to 836 MB in two days. Rotate online (the
; service rarely restarts) once the file crosses 50 MB.
Filename: "{app}\nssm.exe"; Parameters: "set {#ServiceName} AppRotateFiles 1"; Flags: runhidden waituntilterminated
Filename: "{app}\nssm.exe"; Parameters: "set {#ServiceName} AppRotateOnline 1"; Flags: runhidden waituntilterminated
Filename: "{app}\nssm.exe"; Parameters: "set {#ServiceName} AppRotateBytes 52428800"; Flags: runhidden waituntilterminated
Filename: "{app}\nssm.exe"; Parameters: "set {#ServiceName} Start SERVICE_AUTO_START"; Flags: runhidden waituntilterminated
Filename: "{app}\nssm.exe"; Parameters: "set {#ServiceName} AppExit Default Restart"; Flags: runhidden waituntilterminated
Filename: "{app}\nssm.exe"; Parameters: "set {#ServiceName} DisplayName ""{#AppName} Meter Monitoring"""; \
    Flags: runhidden waituntilterminated
Filename: "{app}\nssm.exe"; Parameters: "set {#ServiceName} Description ""Reads electricity meters, stores readings locally, and serves the {#AppName} web UI on port {code:GetPort}."""; \
    Flags: runhidden waituntilterminated

; ── Firewall: let other machines on the site LAN reach the web UI ────────────
; The rule is named after the port, so an upgrade that changes the port must
; drop the rule of the PREVIOUS port too, or the old hole stays open.
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""{#FirewallPrefix}{code:GetPreviousPort})"""; \
    Flags: runhidden waituntilterminated; StatusMsg: "Configuring the firewall..."
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""{#FirewallPrefix}{code:GetPort})"""; \
    Flags: runhidden waituntilterminated
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""{#FirewallPrefix}{code:GetPort})"" dir=in action=allow protocol=TCP localport={code:GetPort}"; \
    Flags: runhidden waituntilterminated

; ── Register the capture browser scheduled task (issue #40) ─────────────────
; Runs Edge under `NT AUTHORITY\LOCAL SERVICE` so the headless-screenshot
; Billing capture (capture/screenshot.py) still works with the service back
; on LocalSystem above. `-Force` inside the script converges an upgrade with
; no separate "does it already exist" branch. A failed registration must not
; fail the install (decision D12) — like every other [Run] entry here, its
; exit code is never checked. It is no longer *silent*, though: VerifyCaptureTask
; in [Code] queries the task at ssPostInstall and tells the person at the keyboard
; if it is missing (issue 009). D12 asks the install to succeed, not to hide.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\register-capture-task.ps1"" -TaskName ""{#CaptureTaskName}"" -ProfileDir ""{commonappdata}\{#AppName}\tmp"""; \
    Flags: runhidden waituntilterminated; StatusMsg: "Registering the capture browser task..."

; ── Start ────────────────────────────────────────────────────────────────────
Filename: "{app}\nssm.exe"; Parameters: "start {#ServiceName}"; \
    Flags: runhidden waituntilterminated; StatusMsg: "Starting the {#AppName} service..."
Filename: "http://localhost:{code:GetPort}/"; Description: "Open the {#AppName} web UI to activate this machine"; \
    Flags: postinstall shellexec nowait

[UninstallRun]
; Stop and remove the service before files go. `nssm remove ... confirm` is the
; non-interactive form — without `confirm` it opens a GUI dialog and the
; uninstall hangs forever.
Filename: "{app}\nssm.exe"; Parameters: "stop {#ServiceName}"; Flags: runhidden waituntilterminated; RunOnceId: "StopService"
Filename: "{app}\nssm.exe"; Parameters: "remove {#ServiceName} confirm"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveService"
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""{#FirewallPrefix}{code:GetPort})"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveFirewallRule"
Filename: "{sys}\schtasks.exe"; Parameters: "/delete /TN ""{#CaptureTaskName}"" /F"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveCaptureTask"

[UninstallDelete]
; Only the program directory. NOTHING under {commonappdata}\ARICHDS is listed:
; the database, the license and the logs must survive an uninstall/reinstall
; cycle (SPEC §3.1). Removing customer data on uninstall would be unrecoverable.
Type: filesandordirs; Name: "{app}"

[Code]

var
  { The web UI port page (InitializeWizard). Nil in the uninstaller, where
    GetPort falls back to the value the installer remembered. }
  PortPage: TInputQueryWizardPage;

{ The port the previous install chose, or the default on a fresh machine.
  Inno keeps it under the app's uninstall key (SetPreviousData below). }
function GetPreviousPort(Param: String): String;
begin
  Result := GetPreviousData('Port', '{#DefaultPort}');
end;

{ The effective port — what NSSM's ARICHDS_PORT, the firewall rule, the Start
  Menu shortcut and the post-install URL all read. One function, so the four
  can never disagree. }
function GetPort(Param: String): String;
begin
  if Assigned(PortPage) then
    Result := Trim(PortPage.Values[0])
  else
    Result := GetPreviousPort('');
end;

{ Remember the port for the next upgrade (and for the uninstaller's firewall
  rule delete). }
procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'Port', GetPort(''));
end;

procedure InitializeWizard();
begin
  PortPage := CreateInputQueryPage(wpSelectDir,
    'Web UI port',
    'Which TCP port should the {#AppName} web UI listen on?',
    'Other machines on the site open http://<this machine>:<port>/. Keep {#DefaultPort} unless ' +
    'another program on this machine already uses it — then choose a free port (1024–65535). ' +
    'The firewall rule and the Start Menu shortcut follow this choice.');
  PortPage.Add('TCP port:', False);
  PortPage.Values[0] := GetPreviousPort('');
end;

{ True when something on this machine is already LISTENING on the port. A
  `netstat` line ending in LISTENING with ":<port> " is that something; the
  exit code of findstr says whether one exists. }
function PortInUse(const Port: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'),
                 '/C netstat -ano -p TCP | findstr /R /C:":' + Port + ' .*LISTENING"', '',
                 SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

{ True when a service of this name is registered. Uses `sc query`, which needs
  no extra dependency and returns a non-zero exit code for an unknown service.
  Declared before its caller — Pascal Script resolves top to bottom. }
function ServiceExists(const ServiceName: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\sc.exe'), 'query ' + ServiceName, '',
                 SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

{ True when the capture browser's scheduled task exists. `schtasks /query`
  returns non-zero for an unknown task — the same shape as ServiceExists above. }
function CaptureTaskExists(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\schtasks.exe'), '/query /TN "{#CaptureTaskName}"', '',
                 SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

{ Issue 009: on 2026-08-25 a real install registered no task and reported
  success. A non-terminating PowerShell error skipped the script's own catch,
  and a [Run] entry's exit code is not checked anyway. The script now fails
  loudly, but the install must still not fail (D12) — so the outcome is checked
  HERE, against Windows rather than against the script's report, and the person
  at the keyboard is told while they are still standing there.

  Deliberately a query and not an exit code: a call that returns quietly and
  leaves no task behind is the exact failure being guarded, and an exit code
  cannot see it. }
procedure VerifyCaptureTask();
begin
  if CaptureTaskExists() then
    Exit;
  Log('Capture browser task "{#CaptureTaskName}" is MISSING after registration.');
  MsgBox('ARICHDS is installed and will run, but the capture browser task' + #13#10 +
         '"{#CaptureTaskName}" could not be registered.' + #13#10 + #13#10 +
         'Billing capture images will fail until it exists. Everything else works.' + #13#10 + #13#10 +
         'To fix it, from an elevated PowerShell:' + #13#10 +
         '  & "' + ExpandConstant('{app}') + '\register-capture-task.ps1" -TaskName "{#CaptureTaskName}" -ProfileDir "' +
         ExpandConstant('{commonappdata}\{#AppName}') + '\tmp"' + #13#10 + #13#10 +
         'then confirm with:' + #13#10 +
         '  Get-ScheduledTask -TaskName "{#CaptureTaskName}"',
         mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    VerifyCaptureTask();
end;

{ Validate the port page: an integer in 1..65535, and a warning — not a
  refusal — when another program already listens there. On an upgrade the
  previous {#AppName} service is still running at this point (PrepareToInstall
  stops it later), so its own port is not reported as a conflict. }
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Port: Integer;
  PortText: String;
begin
  Result := True;
  if CurPageID <> PortPage.ID then
    Exit;
  PortText := Trim(PortPage.Values[0]);
  Port := StrToIntDef(PortText, -1);
  if (Port < 1) or (Port > 65535) then
  begin
    MsgBox('Enter a TCP port between 1 and 65535 (default {#DefaultPort}).', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if ServiceExists('{#ServiceName}') and (PortText = GetPreviousPort('')) then
    Exit;
  if PortInUse(PortText) then
    Result := MsgBox('Port ' + PortText + ' is already in use by another program on this machine.' + #13#10 + #13#10 +
                     'If {#AppName} is installed on it, the web UI will not be reachable — the other program ' +
                     'answers instead (or {#AppName} fails to start).' + #13#10 + #13#10 +
                     'Use this port anyway?', mbConfirmation, MB_YESNO) = IDYES;
end;

{ Stop an existing service BEFORE [Files] replaces the exe. Without this an
  upgrade fails with "file in use" on a machine where the service is running. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  NeedsRestart := False;
  if ServiceExists('{#ServiceName}') then
  begin
    Log('Existing {#ServiceName} service found - stopping it before upgrade.');
    Exec(ExpandConstant('{sys}\net.exe'), 'stop {#ServiceName}', '',
         SW_HIDE, ewWaitUntilTerminated, ResultCode);
    { Give Windows a moment to release the exe's file handles. }
    Sleep(2000);
  end;
end;
