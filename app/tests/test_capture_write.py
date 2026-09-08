"""``capture.write`` — the hardened write (decision 3c, ADR 0010, issue #22).

Ported from v1 ``billing/service.py:1089-1291``'s ordered sequence: validate
the constructed path -> render bytes -> stepwise `mkdir` -> `lstat`
the parent -> atomic `O_EXCL|O_NOFOLLOW|O_BINARY` write. The mkdir carries
no mode since issue 017 -- see `TestTheOperatorCanReadWhatWasWrittenForThem`. The orphan-prevention
invariant this whole module exists for: a render failure or a write failure
must leave **nothing** on disk.

Every test writes under `tmp_path` — none may touch a real `capture_dir`.
"""

from __future__ import annotations

import getpass
import os
import stat
import subprocess
from pathlib import Path

import pytest

from arichds.capture.write import write_capture


class TestHappyPath:
    def test_the_file_is_written_with_the_rendered_bytes(self, tmp_path: Path) -> None:
        target = tmp_path / "SN-1" / "2026-07-31_170000.pdf"

        write_capture(target, lambda: b"hello capture", [tmp_path.resolve()])

        assert target.read_bytes() == b"hello capture"

    def test_missing_ancestors_are_created(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c" / "file.pdf"

        write_capture(target, lambda: b"x", [tmp_path.resolve()])

        assert target.exists()

    def test_render_runs_before_any_filesystem_mutation(self, tmp_path: Path) -> None:
        """Render happens first, deep inside a directory that does not exist
        yet — proving the order isn't merely "render succeeded before the
        assertion ran" but that no mkdir/write occurred before render."""
        target = tmp_path / "not-yet-created" / "file.pdf"
        calls: list[str] = []

        def render() -> bytes:
            calls.append("render")
            assert not target.parent.exists()  # nothing created yet
            return b"data"

        write_capture(target, render, [tmp_path.resolve()])

        assert calls == ["render"]
        assert target.read_bytes() == b"data"


class TestOutsideAllowlist:
    def test_rejected_before_rendering(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "elsewhere" / "file.pdf"
        rendered = []

        def render() -> bytes:
            rendered.append(True)
            return b"x"

        with pytest.raises(ValueError, match="allowlist"):
            write_capture(outside, render, [tmp_path.resolve()])

        assert rendered == []  # render must never run for a rejected path
        assert not outside.exists()


class TestRenderFailureLeavesNoFile:
    def test_a_renderer_that_raises_leaves_no_file_and_no_directory_debris(self, tmp_path: Path) -> None:
        target = tmp_path / "SN-1" / "file.pdf"

        def boom() -> bytes:
            raise RuntimeError("render blew up")

        with pytest.raises(RuntimeError, match="render blew up"):
            write_capture(target, boom, [tmp_path.resolve()])

        assert not target.exists()
        assert not target.parent.exists()  # no mkdir happened before the render raised


class TestWriteFailureLeavesNoPartialFile:
    def test_a_write_that_fails_partway_unlinks_the_partial_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os as os_module

        target = tmp_path / "SN-1" / "file.pdf"
        real_fdopen = os_module.fdopen

        def boom_fdopen(fd, mode, **kwargs):  # noqa: ANN001, ANN003
            handle = real_fdopen(fd, mode, **kwargs)

            class _BoomHandle:
                def write(self, data):  # noqa: ANN001, ANN201
                    raise OSError("disk full")

                def __enter__(self):  # noqa: ANN204
                    return self

                def __exit__(self, *exc_info):  # noqa: ANN002
                    handle.close()
                    return False

            return _BoomHandle()

        monkeypatch.setattr(os_module, "fdopen", boom_fdopen)

        with pytest.raises(OSError, match="disk full"):
            write_capture(target, lambda: b"data", [tmp_path.resolve()])

        assert not target.exists()


class TestSymlinkedParentIsRejected:
    def test_a_symlinked_parent_directory_via_fabricated_lstat(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os as os_module

        target = tmp_path / "SN-1" / "file.pdf"
        target.parent.mkdir()
        real_lstat = os_module.lstat

        class _FakeLinkStat:
            st_mode = stat.S_IFLNK

        def fake_lstat(path):  # noqa: ANN001, ANN201
            if str(path) == str(target.parent):
                return _FakeLinkStat()
            return real_lstat(path)

        monkeypatch.setattr(os_module, "lstat", fake_lstat)

        with pytest.raises(ValueError, match="symlink"):
            write_capture(target, lambda: b"data", [tmp_path.resolve()])

        assert not target.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL semantics are the entire subject")
class TestTheOperatorCanReadWhatWasWrittenForThem:
    """Issue 017 -- a customer's Syncthing could not scan a capture folder:
    ``Access is denied``. ``os.mkdir``'s own docstring says the mode is ignored
    on Windows, but ``0o700`` is the one value CPython special-cases: it
    replaces inheritance with an ACL granting SYSTEM, Administrators and OWNER
    RIGHTS. The service runs as LocalSystem (ADR 0017), so the operator whose
    folder it is was not on that list.

    The assertion is on the ACL of a directory the code really created, never
    on the argument handed to ``os.mkdir`` -- an argument assertion restates
    the implementation and would pass just as happily if Windows behaved the
    way the docstring claims.

    **The parent is built with an explicit grant rather than used as pytest
    supplies it.** ``tmp_path`` lives under ``pytest-of-<user>``, which pytest
    itself creates with ``0o700``, so a child inheriting it correctly still
    shows the restrictive ACL and the test could not tell the two cases apart.
    """

    @staticmethod
    def _acl(path: Path) -> str:
        return subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=True, timeout=30).stdout

    def test_a_created_capture_folder_still_grants_the_operator(self, tmp_path: Path) -> None:
        user = getpass.getuser()
        capture_dir = tmp_path / "capture_dir"
        os.mkdir(capture_dir)
        subprocess.run(
            ["icacls", str(capture_dir), "/grant", f"{user}:(OI)(CI)F"],
            capture_output=True,
            check=True,
            timeout=30,
        )
        granted = "\\" + user.lower() + ":"
        assert granted in self._acl(capture_dir).lower(), "arrange failed: parent does not grant the user"

        target = capture_dir / "SN-ACL" / "2026-08-31_170000.pdf"
        write_capture(target, lambda: b"x", [tmp_path.resolve()])

        acl = self._acl(target.parent)
        assert granted in acl.lower(), (
            f"{user} is not on the created folder's ACL -- a sync agent or the operator's own "
            f"login is denied it:\n{acl}"
        )

    def test_the_written_file_is_readable_too(self, tmp_path: Path) -> None:
        """The folder is what the scan opens, but the file is what gets shipped.
        On Windows a file's ACL comes from its directory, so this passes once
        the directory does -- pinned because that is the claim the ``0o600`` in
        ``_atomic_write`` is allowed to stay on."""
        user = getpass.getuser()
        capture_dir = tmp_path / "capture_dir"
        os.mkdir(capture_dir)
        subprocess.run(
            ["icacls", str(capture_dir), "/grant", f"{user}:(OI)(CI)F"],
            capture_output=True,
            check=True,
            timeout=30,
        )

        target = capture_dir / "SN-FILE" / "2026-08-31_170000.pdf"
        write_capture(target, lambda: b"payload", [tmp_path.resolve()])

        assert "\\" + user.lower() + ":" in self._acl(target).lower(), self._acl(target)
        assert target.read_bytes() == b"payload"
