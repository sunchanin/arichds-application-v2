"""``capture.task`` — the installer/app contract for the LOCAL SERVICE
scheduled task that launches the headless capture browser (issue #40,
replacing #38's Part A).

Grep-based tripwires, modelled on ``test_capture_dom_contract.py`` — this is
the only automated check that exists for the installer half, since nothing
here can register a real scheduled task (Out of scope, issue #40: this
machine has a live ARICHDS install and must not be touched).
"""

from __future__ import annotations

import re
from pathlib import Path

from arichds.capture.screenshot import _EDGE_FALLBACK_PATHS
from arichds.capture.task import CAPTURE_TASK_NAME, EDGE_TASK_ARGUMENTS

REPO_ROOT = Path(__file__).resolve().parents[2]
ISS_PATH = REPO_ROOT / "installer" / "arichds.iss"
PS1_PATH = REPO_ROOT / "installer" / "register-capture-task.ps1"

ISS_TEXT = ISS_PATH.read_text(encoding="utf-8")
PS1_TEXT = PS1_PATH.read_text(encoding="utf-8")


class TestPs1IsSavedWithAUtf8Bom:
    def test_the_ps1_starts_with_a_utf8_bom(self) -> None:
        """Verified on this machine, not assumed: Windows PowerShell 5.1
        reads a BOM-less `.ps1` using the system's default codepage rather
        than UTF-8. Under codepage 1252 (this machine's), this file's
        em-dash comments decode to a curly quote (U+201D) that PowerShell's
        tokenizer accepts as an alternate string delimiter — which silently
        truncated the `Write-Error` message's double-quoted string and
        broke parsing of everything after it
        (`[System.Management.Automation.Language.Parser]::ParseFile()`
        reported the resulting error dozens of lines away from the real
        cause). The BOM forces UTF-8 regardless of the target machine's
        codepage — this ships to Thai-locale machines too (CLAUDE.md), where
        the default codepage differs again."""
        raw_bytes = PS1_PATH.read_bytes()
        assert raw_bytes[:3] == b"\xef\xbb\xbf", "register-capture-task.ps1 is missing its UTF-8 BOM"


class TestTaskNameConstant:
    def test_capture_task_name_is_the_decided_value(self) -> None:
        assert CAPTURE_TASK_NAME == "ARICHDS Capture Browser"


class TestTaskNameReachesTheInstaller:
    """The task name must not be hardcoded independently at the two places
    that need it — a drift between ``capture/task.py`` and either the
    registration or the deletion side would silently leave a stale task
    running under the old name, or fail to remove the real one."""

    def test_capture_task_name_appears_in_arichds_iss(self) -> None:
        assert CAPTURE_TASK_NAME in ISS_TEXT

    def test_the_iss_task_name_macro_is_used_at_registration(self) -> None:
        # `[Run]`'s call into register-capture-task.ps1 must pass the same
        # `{#CaptureTaskName}` macro the `#define` derives from
        # CAPTURE_TASK_NAME — not a second, independently hardcoded string.
        run_section = ISS_TEXT.split("[Run]", 1)[1].split("[UninstallRun]", 1)[0]
        assert "register-capture-task.ps1" in run_section
        assert "{#CaptureTaskName}" in run_section

    def test_the_iss_task_name_macro_is_used_at_deletion(self) -> None:
        uninstall_section = ISS_TEXT.split("[UninstallRun]", 1)[1].split("[UninstallDelete]", 1)[0]
        assert "schtasks" in uninstall_section.lower()
        assert "/delete" in uninstall_section
        assert "{#CaptureTaskName}" in uninstall_section

    def test_capture_task_name_appears_in_the_ps1(self) -> None:
        # The script itself is parameterised (`-TaskName`, decision D1) so it
        # never hardcodes the name functionally — but its documented example
        # invocation (the exact one arichds.iss makes) must still name it, so
        # a rename of CAPTURE_TASK_NAME cannot leave stale, misleading
        # documentation behind unnoticed.
        assert CAPTURE_TASK_NAME in PS1_TEXT


class TestEdgeArgumentsReachTheInstaller:
    def test_every_edge_task_argument_appears_in_the_ps1(self) -> None:
        for flag in EDGE_TASK_ARGUMENTS:
            assert flag in PS1_TEXT, f"{flag!r} from EDGE_TASK_ARGUMENTS is missing from register-capture-task.ps1"

    def test_no_sandbox_appears_nowhere_in_the_ps1(self) -> None:
        """Deliberately absent (capture/task.py's own docstring) — there is
        no evidence the sandbox needs disabling under
        `NT AUTHORITY\\LOCAL SERVICE`, and weakening it speculatively is not
        this issue's call to make."""
        assert "--no-sandbox" not in PS1_TEXT

    def test_both_edge_fallback_paths_appear_in_the_ps1(self) -> None:
        """`register-capture-task.ps1` resolves Edge with the same registry
        -> fallback order as `resolve_edge_path()` — pinned against the
        actual `_EDGE_FALLBACK_PATHS` tuple, not re-derived."""
        for candidate in _EDGE_FALLBACK_PATHS:
            assert str(candidate) in PS1_TEXT, f"{candidate} is missing from register-capture-task.ps1"


class TestServiceStaysLocalSystem:
    def test_arichds_iss_never_sets_the_service_objectname_to_localservice(self) -> None:
        """The *service's* `ObjectName` must never be pointed at LocalService
        again (issue #40 replaces #38's Part A: the service is LocalSystem,
        and no `nssm set ... ObjectName` line names any account at all any
        more — LocalSystem needs no `ObjectName`). `NT AUTHORITY\\LOCAL
        SERVICE` legitimately still appears elsewhere in this file, naming
        the *capture browser's* scheduled-task account (the `tmp` `[Dirs]`
        comment and the task-registration `[Run]` comment) — that is correct
        and this test does not forbid it."""
        assert "NT AUTHORITY\\LocalService" not in ISS_TEXT
        assert 'ObjectName ""NT AUTHORITY' not in ISS_TEXT

    def test_arichds_iss_resets_the_service_objectname_back_to_localsystem(self) -> None:
        """D3 — absence of the old LocalService form is not enough: an
        upgrade of an existing 0.2.0 install keeps whatever `ObjectName`
        `nssm install` found already configured (`nssm install` on an
        already-registered service is a no-op), so the `[Run]` section must
        actively `nssm reset <service> ObjectName` rather than merely never
        mention LocalService again. Code review round, problem 1."""
        run_section = ISS_TEXT.split("[Run]", 1)[1].split("[UninstallRun]", 1)[0]
        assert "reset {#ServiceName} ObjectName" in run_section

    def test_permissions_grant_appears_on_exactly_one_dirs_line_and_it_is_tmp(self) -> None:
        dirs_section = ISS_TEXT.split("[Dirs]", 1)[1].split("[Icons]", 1)[0]
        permissioned_lines = [
            line for line in dirs_section.splitlines() if line.strip().startswith("Name:") and "Permissions:" in line
        ]
        assert len(permissioned_lines) == 1, f"expected exactly one Permissions: line, found: {permissioned_lines!r}"
        assert r"{#AppName}\tmp" in permissioned_lines[0]


class TestCaptureTaskPrincipalAndBatterySettings:
    """Code review round, problem 1 — three acceptance criteria (issue #40's
    task principal, and finding F3's battery constraints) had no assertion
    at all; each is proven here to actually discriminate by mutating the
    `.ps1` and re-running this file."""

    def test_the_ps1_registers_a_serviceaccount_principal_for_localservice(self) -> None:
        """Issue criterion #2 — the task's principal must be
        `NT AUTHORITY\\LOCAL SERVICE` (`-UserId "LOCALSERVICE"` with
        `-LogonType ServiceAccount`, F4). Under any other account (SYSTEM,
        say) `msedge.exe` exits 1002 and every capture fails — the precise
        bug issue #40 exists to fix."""
        assert '-UserId "LOCALSERVICE"' in PS1_TEXT
        assert "-LogonType ServiceAccount" in PS1_TEXT

    def test_the_ps1_allows_starting_on_batteries(self) -> None:
        """F3 — `DisallowStartIfOnBatteries` defaults to True and blocks an
        on-demand `schtasks /run` outright, with no CLI switch to fix it
        after registration. This is the finding that drove the whole
        PowerShell-over-`schtasks /create` decision (D1)."""
        assert "-AllowStartIfOnBatteries" in PS1_TEXT

    def test_the_ps1_does_not_stop_on_batteries(self) -> None:
        assert "-DontStopIfGoingOnBatteries" in PS1_TEXT


class TestProfileDirIsTheTmpDirectory:
    def test_the_ps1_is_invoked_with_the_tmp_directory_as_the_profile_dir(self) -> None:
        run_section = ISS_TEXT.split("[Run]", 1)[1].split("[UninstallRun]", 1)[0]
        match = re.search(r"-ProfileDir\s+\"\"([^\"]+)\"\"", run_section)
        assert match is not None, "no -ProfileDir argument found in the [Run] powershell invocation"
        assert match.group(1).rstrip('"').endswith(r"{#AppName}\tmp")
