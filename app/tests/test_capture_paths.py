"""``capture.paths`` — validation for the capture directory (ADR 0010).

Ported from v1 ``cewe-worker/src/billing/paths.py``, adapted to decision 17
(issue #22): the allowlist is optional (empty means no root restriction —
v2's ``capture_dir`` is an operator setting, not env-configured), and the
final-component symlink check is explicit rather than implied by
``resolve()`` alone, so a symlink *inside* the allowlist is still rejected.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from arichds.capture.paths import ensure_within_allowlist, sanitize_meter_serial, validate_capture_dir_setting


class TestEmptyAndRelative:
    def test_empty_string_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            validate_capture_dir_setting("", [])

    def test_whitespace_only_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            validate_capture_dir_setting("   ", [])

    def test_a_relative_path_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="absolute"):
            validate_capture_dir_setting("relative/dir", [])


class TestDotDotIsRejected:
    def test_a_dotdot_component_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match=r"\.\."):
            validate_capture_dir_setting(str(tmp_path / ".." / "escape"), [])


class TestFilesystemRoot:
    def test_a_drive_or_filesystem_root_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="root"):
            validate_capture_dir_setting(tmp_path_anchor(), [])


def tmp_path_anchor() -> str:
    """The filesystem/drive root of wherever pytest runs (`C:\\` on Windows, `/` on POSIX)."""
    return Path.cwd().resolve().anchor


class TestExistingFile:
    def test_a_capture_dir_that_is_already_a_file_is_rejected_at_save_time(self, tmp_path: Path) -> None:
        """A file (not a directory) at the exact `capture_dir` path would
        otherwise pass this check and only fail later, as an unhelpful 500,
        the moment the first write tries to `mkdir` through it."""
        existing_file = tmp_path / "not-a-directory"
        existing_file.write_text("I am a file, not a directory")

        with pytest.raises(ValueError, match="directory"):
            validate_capture_dir_setting(str(existing_file), [])


class TestAllowlist:
    def test_empty_allowlist_means_no_root_restriction(self, tmp_path: Path) -> None:
        """Decision 17 — v2's capture_dir is an operator setting, not
        env-configured, so defaulting the allowlist to it would be circular."""
        target = tmp_path / "anywhere"

        resolved = validate_capture_dir_setting(str(target), [])

        assert resolved == target.resolve()

    def test_resolution_within_the_allowlist_is_accepted(self, tmp_path: Path) -> None:
        allowed = tmp_path / "captures"
        allowlist = [allowed.resolve()]

        resolved = validate_capture_dir_setting(str(allowed / "site-a"), allowlist)

        assert resolved == (allowed / "site-a").resolve()

    def test_resolution_outside_every_allowlisted_root_is_rejected(self, tmp_path: Path) -> None:
        allowed = tmp_path / "captures"
        outside = tmp_path / "elsewhere"
        allowlist = [allowed.resolve()]

        with pytest.raises(ValueError, match="allowlist"):
            validate_capture_dir_setting(str(outside), allowlist)


class TestSymlinkedFinalComponent:
    """A symlinked capture_dir is rejected even when it points *inside* the
    allowlist — closing the TOCTOU window a later retarget could open."""

    def test_the_guard_itself_via_a_fabricated_lstat(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Drives the guard without creating a real symlink (which needs
        privilege on Windows) — a fabricated ``os.lstat`` result proves the
        check fires on its own, not just when `resolve()` happens to escape
        the allowlist."""
        target = tmp_path / "linked"

        class _FakeStat:
            st_mode = stat.S_IFLNK

        monkeypatch.setattr(os, "lstat", lambda _path: _FakeStat())

        with pytest.raises(ValueError, match="symlink"):
            validate_capture_dir_setting(str(target), [])

    def test_a_real_symlink_is_rejected_or_the_test_skips_on_a_privilege_error(self, tmp_path: Path) -> None:
        """Filesystem-level proof, skipping cleanly rather than silently when
        this OS/user cannot create a symlink (Windows needs admin or dev mode)."""
        real_target = tmp_path / "real"
        real_target.mkdir()
        link = tmp_path / "linked"
        try:
            link.symlink_to(real_target, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"cannot create a symlink on this OS/user: {exc}")

        with pytest.raises(ValueError, match="symlink"):
            validate_capture_dir_setting(str(link), [])


class TestSanitizeMeterSerial:
    def test_empty_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            sanitize_meter_serial("")

    def test_a_slash_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            sanitize_meter_serial("123/456")

    def test_a_dotdot_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"\.\."):
            sanitize_meter_serial("..")

    def test_a_plain_serial_passes_through_unchanged(self) -> None:
        assert sanitize_meter_serial("1232002893") == "1232002893"


class TestEnsureWithinAllowlist:
    def test_a_path_inside_the_root_passes(self, tmp_path: Path) -> None:
        ensure_within_allowlist(tmp_path / "SN-1" / "file.pdf", [tmp_path.resolve()])  # must not raise

    def test_a_path_outside_the_root_raises(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "somewhere-else" / "file.pdf"
        with pytest.raises(ValueError):
            ensure_within_allowlist(outside, [tmp_path.resolve()])
