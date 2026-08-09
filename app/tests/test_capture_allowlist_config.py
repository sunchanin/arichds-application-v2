"""``Settings.capture_allowlist_roots`` — ``ARICHDS_CAPTURE_ALLOWLIST`` parsing
(decision 17, issue #22).
"""

from __future__ import annotations

import os
from pathlib import Path

from arichds.config import Settings


class TestUnsetMeansNoRestriction:
    def test_unset_returns_an_empty_list(self, data_dir: Path) -> None:
        assert Settings().capture_allowlist_roots() == []


class TestParsing:
    def test_a_single_root_resolves(self, tmp_path: Path, monkeypatch, data_dir: Path) -> None:
        monkeypatch.setenv("ARICHDS_CAPTURE_ALLOWLIST", str(tmp_path))

        assert Settings().capture_allowlist_roots() == [tmp_path.resolve()]

    def test_pathsep_separated_multiple_roots(self, tmp_path: Path, monkeypatch, data_dir: Path) -> None:
        first = tmp_path / "a"
        second = tmp_path / "b"
        monkeypatch.setenv("ARICHDS_CAPTURE_ALLOWLIST", os.pathsep.join([str(first), str(second)]))

        assert Settings().capture_allowlist_roots() == [first.resolve(), second.resolve()]
