"""``export.writer`` — the shared writer's two write paths (ticket 02, ADR
0023): the cheap append and the atomic whole-file replace, plus the
``head_changed`` check that tells a caller which one to use.

Judged on the bytes and files that reach disk, like every export-file test in
this codebase.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from arichds.export.writer import append_rows, head_changed, replace_rows

HEADER_BLOCK = [["Customer :", "TFTECH"], ["Site Name :", "Plant A"]]
HEADER_ROW = ["Date/Time", "Value"]
BOM = chr(65279)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


class TestReplaceRowsIsAtomic:
    def test_a_fresh_file_carries_the_bom_head_and_rows(self, tmp_path: Path) -> None:
        target = tmp_path / "out.csv"

        written = replace_rows(
            target,
            header_block=HEADER_BLOCK,
            header_row=HEADER_ROW,
            rows=[["2026-01-01", "1"]],
            allowlist=[tmp_path],
            label="test",
        )

        assert written
        raw = target.read_bytes().decode("utf-8")
        assert raw.startswith(BOM)
        assert "Site Name :,Plant A" in raw
        assert "Date/Time,Value" in raw
        assert "2026-01-01,1" in raw

    def test_no_temporary_file_is_left_behind_on_success(self, tmp_path: Path) -> None:
        target = tmp_path / "out.csv"

        replace_rows(
            target, header_block=HEADER_BLOCK, header_row=HEADER_ROW, rows=[], allowlist=[tmp_path], label="test"
        )

        assert list(tmp_path.iterdir()) == [target], "only the target file may exist afterward"

    def test_a_failure_injected_mid_write_leaves_the_previous_file_byte_for_byte_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The realistic shape of the failure this primitive exists to survive:
        something goes wrong after the temporary file has bytes in it (here, at
        the ``fsync`` that is supposed to guarantee they are durable) and the
        swap over the real file must never happen."""
        target = tmp_path / "out.csv"
        replace_rows(
            target,
            header_block=HEADER_BLOCK,
            header_row=HEADER_ROW,
            rows=[["2026-01-01", "1"]],
            allowlist=[tmp_path],
            label="test",
        )
        before = target.read_bytes()

        def raising_fsync(fd: int) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(os, "fsync", raising_fsync)

        written = replace_rows(
            target,
            header_block=HEADER_BLOCK,
            header_row=HEADER_ROW,
            rows=[["2026-02-02", "2"]],
            allowlist=[tmp_path],
            label="test",
        )

        assert not written
        assert target.read_bytes() == before, "the previous file must be untouched by the failed attempt"
        assert list(tmp_path.iterdir()) == [target], "the temporary file must not be left behind"

    def test_a_failure_at_the_swap_itself_leaves_no_temp_file_and_the_old_file_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other place a failure can land: the rename itself, after every
        byte has already reached the temporary file."""
        target = tmp_path / "out.csv"
        replace_rows(
            target,
            header_block=HEADER_BLOCK,
            header_row=HEADER_ROW,
            rows=[["2026-01-01", "1"]],
            allowlist=[tmp_path],
            label="test",
        )
        before = target.read_bytes()

        def raising_replace(*args: object, **kwargs: object) -> None:
            raise OSError("access denied")

        monkeypatch.setattr(os, "replace", raising_replace)

        written = replace_rows(
            target,
            header_block=HEADER_BLOCK,
            header_row=HEADER_ROW,
            rows=[["2026-02-02", "2"]],
            allowlist=[tmp_path],
            label="test",
        )

        assert not written
        assert target.read_bytes() == before
        assert list(tmp_path.iterdir()) == [target], "no `.tmp` file may survive a failed swap"

    def test_a_failure_creating_the_temporary_file_returns_false_and_touches_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The realistic shape: a folder that exists but is not writable. This
        failure lands before ``tmp_path`` is even bound, so it must not raise
        out of ``replace_rows`` — every caller (``export_device``,
        ``export_device_billing``, the "Save now" endpoints) documents that it
        never raises, only returns False and logs."""
        target = tmp_path / "out.csv"
        replace_rows(
            target,
            header_block=HEADER_BLOCK,
            header_row=HEADER_ROW,
            rows=[["2026-01-01", "1"]],
            allowlist=[tmp_path],
            label="test",
        )
        before = target.read_bytes()

        def raising_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
            raise OSError("permission denied")

        monkeypatch.setattr(tempfile, "mkstemp", raising_mkstemp)

        written = replace_rows(
            target,
            header_block=HEADER_BLOCK,
            header_row=HEADER_ROW,
            rows=[["2026-02-02", "2"]],
            allowlist=[tmp_path],
            label="test",
        )

        assert not written
        assert target.read_bytes() == before, "the previous file must be untouched"
        assert list(tmp_path.iterdir()) == [target], "no `.tmp` file may exist"

    def test_an_allowlist_rejection_writes_nothing_and_leaves_no_temp_file(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.csv"
        allowlist_root = tmp_path / "allowed"
        allowlist_root.mkdir()

        written = replace_rows(
            outside, header_block=HEADER_BLOCK, header_row=HEADER_ROW, rows=[], allowlist=[allowlist_root], label="t"
        )

        assert not written
        assert not outside.exists()
        assert list(tmp_path.iterdir()) == [allowlist_root]


class TestHeadChanged:
    def test_a_file_that_does_not_exist_yet_is_not_a_change(self, tmp_path: Path) -> None:
        assert head_changed(tmp_path / "missing.csv", HEADER_BLOCK, HEADER_ROW) is False

    def test_an_empty_file_is_not_a_change(self, tmp_path: Path) -> None:
        target = tmp_path / "empty.csv"
        target.touch()

        assert head_changed(target, HEADER_BLOCK, HEADER_ROW) is False

    def test_a_file_already_under_the_current_head_is_not_a_change(self, tmp_path: Path) -> None:
        target = tmp_path / "out.csv"
        replace_rows(target, header_block=HEADER_BLOCK, header_row=HEADER_ROW, rows=[], allowlist=[tmp_path], label="t")

        assert head_changed(target, HEADER_BLOCK, HEADER_ROW) is False

    def test_a_file_under_a_different_block_is_a_change(self, tmp_path: Path) -> None:
        target = tmp_path / "out.csv"
        old_block = [["Customer :", "TFTECH"], ["Site Name :", "Plant OLD"]]
        replace_rows(target, header_block=old_block, header_row=HEADER_ROW, rows=[], allowlist=[tmp_path], label="t")

        assert head_changed(target, HEADER_BLOCK, HEADER_ROW) is True

    def test_a_file_under_different_columns_is_a_change(self, tmp_path: Path) -> None:
        target = tmp_path / "out.csv"
        replace_rows(
            target, header_block=HEADER_BLOCK, header_row=["Old", "Columns"], rows=[], allowlist=[tmp_path], label="t"
        )

        assert head_changed(target, HEADER_BLOCK, HEADER_ROW) is True


class TestAppendRowsRefusesOnAHeadItDidNotCheck:
    """``append_rows`` trusts a caller to have checked :func:`head_changed`
    first. If it is called anyway against a file whose head has moved, it must
    refuse rather than put a row under a header that does not describe it —
    the exact failure this whole module exists to prevent."""

    def test_a_mismatched_head_is_refused_and_nothing_is_appended(self, tmp_path: Path) -> None:
        target = tmp_path / "out.csv"
        old_block = [["Customer :", "TFTECH"], ["Site Name :", "Plant OLD"]]
        replace_rows(
            target,
            header_block=old_block,
            header_row=HEADER_ROW,
            rows=[["2026-01-01", "1"]],
            allowlist=[tmp_path],
            label="t",
        )
        before = target.read_bytes()

        written = append_rows(
            target,
            header_block=HEADER_BLOCK,
            header_row=HEADER_ROW,
            rows=[["2026-02-02", "2"]],
            allowlist=[tmp_path],
            label="t",
        )

        assert not written
        assert target.read_bytes() == before, "a refused append must not touch the file at all"

    def test_a_matching_head_still_appends_exactly_as_before(self, tmp_path: Path) -> None:
        target = tmp_path / "out.csv"
        append_rows(
            target,
            header_block=HEADER_BLOCK,
            header_row=HEADER_ROW,
            rows=[["2026-01-01", "1"]],
            allowlist=[tmp_path],
            label="t",
        )

        written = append_rows(
            target,
            header_block=HEADER_BLOCK,
            header_row=HEADER_ROW,
            rows=[["2026-02-02", "2"]],
            allowlist=[tmp_path],
            label="t",
        )

        assert written
        lines = read(target).splitlines()
        assert lines[-2:] == ["2026-01-01,1", "2026-02-02,2"]

    def test_no_dated_edition_is_ever_created(self, tmp_path: Path) -> None:
        """The rename path that produced Closed Editions is gone: a head
        change must never leave a second file beside the target."""
        target = tmp_path / "out.csv"
        old_block = [["Customer :", "TFTECH"], ["Site Name :", "Plant OLD"]]
        replace_rows(
            target, header_block=old_block, header_row=HEADER_ROW, rows=[["x", "1"]], allowlist=[tmp_path], label="t"
        )

        append_rows(
            target, header_block=HEADER_BLOCK, header_row=HEADER_ROW, rows=[["y", "2"]], allowlist=[tmp_path], label="t"
        )

        assert list(tmp_path.iterdir()) == [target]
