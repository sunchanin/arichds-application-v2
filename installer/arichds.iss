; ─────────────────────────────────────────────────────────────────────────────
; ARICHDS Application — Inno Setup installer (SPEC §3.1)
;
; One setup.exe with wizard, upgrade and uninstall built in. It installs the
; frozen onedir build to Program Files\ARICHDS, creates the data tree under
; %ProgramData%\ARICHDS, registers arichds.exe as a Windows service via NSSM,
; and opens TCP 8000 so other machines on the site LAN can reach the web UI.
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
#define AppVersion     "0.1.0"
#define AppPublisher   "ARICHDS"
#define ServiceName    "arichds"
#define AppPort        "8000"
#define FirewallRule   "ARICHDS Web UI (TCP 8000)"

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

[Dirs]
; All runtime data lives here and SURVIVES UNINSTALL (see [UninstallDelete] —
; which deliberately lists nothing under {commonappdata}).
Name: "{commonappdata}\{#AppName}"
Name: "{commonappdata}\{#AppName}\logs"
Name: "{commonappdata}\{#AppName}\license"
; Singular: the daily backup job writes here (SPEC §5, M5c) and resolves it from
; Settings.backup_dir, which is `<data>\backup`.
Name: "{commonappdata}\{#AppName}\backup"
Name: "{commonappdata}\{#AppName}\captures"

[Icons]
Name: "{group}\{#AppName} Web UI"; Filename: "http://localhost:{#AppPort}/"
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
Filename: "{app}\nssm.exe"; Parameters: "set {#ServiceName} AppEnvironmentExtra ARICHDS_DATA_DIR={commonappdata}\{#AppName} ARICHDS_PORT={#AppPort}"; \
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
Filename: "{app}\nssm.exe"; Parameters: "set {#ServiceName} Description ""Reads electricity meters, stores readings locally, and serves the {#AppName} web UI on port {#AppPort}."""; \
    Flags: runhidden waituntilterminated

; ── Firewall: let other machines on the site LAN reach the web UI ────────────
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""{#FirewallRule}"""; \
    Flags: runhidden waituntilterminated; StatusMsg: "Configuring the firewall..."
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""{#FirewallRule}"" dir=in action=allow protocol=TCP localport={#AppPort}"; \
    Flags: runhidden waituntilterminated

; ── Start ────────────────────────────────────────────────────────────────────
Filename: "{app}\nssm.exe"; Parameters: "start {#ServiceName}"; \
    Flags: runhidden waituntilterminated; StatusMsg: "Starting the {#AppName} service..."
Filename: "http://localhost:{#AppPort}/"; Description: "Open the {#AppName} web UI to activate this machine"; \
    Flags: postinstall shellexec nowait

[UninstallRun]
; Stop and remove the service before files go. `nssm remove ... confirm` is the
; non-interactive form — without `confirm` it opens a GUI dialog and the
; uninstall hangs forever.
Filename: "{app}\nssm.exe"; Parameters: "stop {#ServiceName}"; Flags: runhidden waituntilterminated; RunOnceId: "StopService"
Filename: "{app}\nssm.exe"; Parameters: "remove {#ServiceName} confirm"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveService"
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""{#FirewallRule}"""; Flags: runhidden waituntilterminated; RunOnceId: "RemoveFirewallRule"

[UninstallDelete]
; Only the program directory. NOTHING under {commonappdata}\ARICHDS is listed:
; the database, the license and the logs must survive an uninstall/reinstall
; cycle (SPEC §3.1). Removing customer data on uninstall would be unrecoverable.
Type: filesandordirs; Name: "{app}"

[Code]

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
