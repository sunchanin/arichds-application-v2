"""``capture.screenshot`` — the headless-screenshot Billing PNG renderer
(ADR 0017, issue #38).

**No test here may launch Edge or need a running server** — every CDP
interaction is driven through a fake transport or mocked subprocess calls.
The one test that drives real Edge lives in
``test_capture_screenshot_integration.py`` and stays skipped unless
``ARICHDS_TEST_EDGE`` is set.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from arichds.capture.screenshot import BrowserCaptureError, resolve_edge_path


class TestResolveEdgePath:
    def test_reads_the_default_value_from_the_app_paths_registry_key(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        edge = tmp_path / "msedge.exe"
        edge.write_bytes(b"")
        reg_output = (
            "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\msedge.exe\r\n"
            f"    (Default)    REG_SZ    {edge}\r\n"
            f"    Path    REG_SZ    {tmp_path}\r\n"
        )

        def fake_check_output(args: list[str], **kwargs: object) -> str:
            assert args[:2] == ["reg", "query"]
            return reg_output

        monkeypatch.setattr(subprocess, "check_output", fake_check_output)

        assert resolve_edge_path() == edge

    def test_falls_back_to_the_well_known_program_files_location_when_the_registry_read_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import arichds.capture.screenshot as screenshot_module

        def fake_check_output(args: list[str], **kwargs: object) -> str:
            raise subprocess.CalledProcessError(1, args)

        monkeypatch.setattr(subprocess, "check_output", fake_check_output)

        fallback = tmp_path / "Fallback" / "msedge.exe"
        fallback.parent.mkdir(parents=True)
        fallback.write_bytes(b"")
        monkeypatch.setattr(screenshot_module, "_EDGE_FALLBACK_PATHS", (fallback,))

        assert resolve_edge_path() == fallback

    def test_returns_none_when_edge_is_nowhere_to_be_found(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import arichds.capture.screenshot as screenshot_module

        def fake_check_output(args: list[str], **kwargs: object) -> str:
            raise subprocess.CalledProcessError(1, args)

        monkeypatch.setattr(subprocess, "check_output", fake_check_output)
        monkeypatch.setattr(screenshot_module, "_EDGE_FALLBACK_PATHS", (tmp_path / "nope.exe",))

        assert resolve_edge_path() is None

    def test_a_stale_registry_value_pointing_at_a_missing_file_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The registry can point at a binary that no longer exists (an
        uninstall that left the key behind) — that must not be trusted over
        an existing fallback."""
        import arichds.capture.screenshot as screenshot_module

        missing = tmp_path / "gone" / "msedge.exe"
        reg_output = f"    (Default)    REG_SZ    {missing}\r\n"

        def fake_check_output(args: list[str], **kwargs: object) -> str:
            return reg_output

        monkeypatch.setattr(subprocess, "check_output", fake_check_output)

        fallback = tmp_path / "Fallback" / "msedge.exe"
        fallback.parent.mkdir(parents=True)
        fallback.write_bytes(b"")
        monkeypatch.setattr(screenshot_module, "_EDGE_FALLBACK_PATHS", (fallback,))

        assert resolve_edge_path() == fallback


class TestBrowserCaptureError:
    def test_is_a_plain_exception(self) -> None:
        assert issubclass(BrowserCaptureError, Exception)
