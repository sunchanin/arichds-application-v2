"""``log_reader`` — the reader counterpart to ``logging_config`` (M7-4, issue #31).

Every test writes its own file(s) under ``tmp_path`` — never routed through the
``logging`` module (root level is INFO, so a ``logger.debug(...)`` would never
reach the file and a DEBUG test would silently test nothing).
"""

from __future__ import annotations

from pathlib import Path

from arichds.log_reader import LogEntry, read_tail


class TestExactParse:
    def test_one_header_line_parses_into_all_four_fields(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "arichds.log").write_text(
            "2026-08-11T10:00:00+0700 | INFO     | arichds.api.auth | Login failed for 'admin'\n",
            encoding="utf-8",
        )

        result = read_tail(log_dir, lines=500, min_level=None)

        assert result == [LogEntry("2026-08-11T10:00:00+0700", "INFO", "arichds.api.auth", "Login failed for 'admin'")]

    def test_a_message_containing_the_pipe_separator_survives_intact(self, tmp_path: Path) -> None:
        """``maxsplit=3`` (D4) means a message that itself contains ``" | "``
        must not be chopped up or misread as more header fields — this is the
        realistic case for a forwarded vendored-library trace line
        (``_gurux_trace.py:95`` forwards Gurux trace text verbatim at DEBUG,
        and that text is column-listing output shaped like
        ``Index: 1 | Value: 42``)."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "arichds.log").write_text(
            "2026-08-11T10:00:00+0700 | DEBUG    | arichds.test | dlms trace: Index: 1 | Value: 42 | Unit: kWh\n",
            encoding="utf-8",
        )

        result = read_tail(log_dir, lines=500, min_level=None)

        assert result == [
            LogEntry(
                "2026-08-11T10:00:00+0700",
                "DEBUG",
                "arichds.test",
                "dlms trace: Index: 1 | Value: 42 | Unit: kWh",
            )
        ]


def _write_entries(log_dir: Path, messages: list[str], *, level: str = "INFO") -> None:
    """Write one header-line entry per message, in order."""
    log_dir.mkdir(exist_ok=True)
    lines = [f"2026-08-11T10:00:00+0700 | {level:<8} | arichds.test | {msg}\n" for msg in messages]
    (log_dir / "arichds.log").write_text("".join(lines), encoding="utf-8")


class TestFileOrder:
    def test_entries_come_back_in_file_order_newest_last(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        _write_entries(log_dir, ["1", "2", "3", "4", "5"])

        result = read_tail(log_dir, lines=500, min_level=None)

        assert [e.message for e in result] == ["1", "2", "3", "4", "5"]


class TestTailIsTheLastN:
    def test_lines_bound_keeps_only_the_last_n_entries(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        _write_entries(log_dir, [str(n) for n in range(1, 11)])

        result = read_tail(log_dir, lines=3, min_level=None)

        assert [e.message for e in result] == ["8", "9", "10"]


class TestContinuationJoinsThePreviousEntry:
    def test_non_header_lines_are_appended_to_the_preceding_entrys_message(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "arichds.log").write_text(
            "2026-08-11T10:00:00+0700 | ERROR    | arichds.test | boom\n"
            "Traceback (most recent call last):\n"
            '  File "x", line 1\n'
            "2026-08-11T10:00:01+0700 | INFO     | arichds.test | after\n",
            encoding="utf-8",
        )

        result = read_tail(log_dir, lines=500, min_level=None)

        assert len(result) == 2
        assert result[0].message == 'boom\nTraceback (most recent call last):\n  File "x", line 1'
        assert result[1].message == "after"


class TestLeadingOrphanIsKept:
    def test_a_line_before_any_header_becomes_its_own_entry(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "arichds.log").write_text(
            '  File "x", line 1\n2026-08-11T10:00:00+0700 | INFO     | arichds.test | after\n',
            encoding="utf-8",
        )

        result = read_tail(log_dir, lines=500, min_level=None)

        assert len(result) == 2
        assert result[0] == LogEntry(None, None, None, '  File "x", line 1')


class TestMinLevelKeepsAtOrAbove:
    def test_a_line_per_level_filters_to_the_exact_absolute_lists(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        lines = [
            f"2026-08-11T10:00:0{i}+0700 | {level:<8} | arichds.test | msg\n"
            for i, level in enumerate(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        ]
        (log_dir / "arichds.log").write_text("".join(lines), encoding="utf-8")

        warning_up = read_tail(log_dir, lines=500, min_level="WARNING")
        unfiltered = read_tail(log_dir, lines=500, min_level=None)

        assert [e.level for e in warning_up] == ["WARNING", "ERROR", "CRITICAL"]
        assert [e.level for e in unfiltered] == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class TestFilterRunsBeforeTail:
    def test_the_tail_bound_applies_after_filtering_not_before(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        messages = ["e1", "e2", "e3"] + [f"i{n}" for n in range(197)]
        levels = ["ERROR"] * 3 + ["INFO"] * 197
        log_dir.mkdir()
        lines = [
            f"2026-08-11T10:00:{i:02d}+0700 | {level:<8} | arichds.test | {msg}\n"
            for i, (level, msg) in enumerate(zip(levels, messages, strict=True))
        ]
        (log_dir / "arichds.log").write_text("".join(lines), encoding="utf-8")

        result = read_tail(log_dir, lines=10, min_level="ERROR")

        assert len(result) == 3


class TestNoneLevelSurvivesAnyFilter:
    def test_an_orphan_entry_is_kept_alongside_a_matching_level(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "arichds.log").write_text(
            "orphan line before any header\n"
            "2026-08-11T10:00:00+0700 | INFO     | arichds.test | info-msg\n"
            "2026-08-11T10:00:01+0700 | ERROR    | arichds.test | error-msg\n",
            encoding="utf-8",
        )

        result = read_tail(log_dir, lines=500, min_level="ERROR")

        assert len(result) == 2
        assert result[0].level is None
        assert result[1].level == "ERROR"


class TestNothingThereIsNotAnError:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        assert read_tail(log_dir, lines=500, min_level=None) == []

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "arichds.log").write_text("", encoding="utf-8")

        assert read_tail(log_dir, lines=500, min_level=None) == []

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "does-not-exist"

        assert read_tail(log_dir, lines=500, min_level=None) == []


class TestRotatedSiblingsAreNeverRead:
    def test_only_the_current_log_file_is_read(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "arichds.log").write_text(
            "2026-08-11T10:00:00+0700 | INFO     | arichds.test | current\n", encoding="utf-8"
        )
        (log_dir / "arichds.log.1").write_text(
            "2026-08-11T09:00:00+0700 | INFO     | arichds.test | rotated\n", encoding="utf-8"
        )

        result = read_tail(log_dir, lines=500, min_level=None)

        assert [e.message for e in result] == ["current"]


class TestUndecodableBytesDoNotRaiseOrTruncate:
    def test_a_stray_invalid_byte_does_not_stop_the_read(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        with (log_dir / "arichds.log").open("wb") as handle:
            handle.write(b"2026-08-11T10:00:00+0700 | INFO     | arichds.test | bad-\xff-byte\n")
            handle.write(b"2026-08-11T10:00:01+0700 | INFO     | arichds.test | after\n")

        result = read_tail(log_dir, lines=500, min_level=None)

        assert len(result) == 2
        assert result[1].message == "after"


class TestReaderAgreesWithTheWriterOnEncoding:
    def test_non_ascii_text_round_trips_exactly(self, tmp_path: Path) -> None:
        """The writer pins UTF-8 (``logging_config.py:115``); the reader must
        read the same encoding rather than falling back to Python's
        locale-dependent default (still live in 3.14, and this ships to
        Windows, where the locale encoding is typically cp1252 — not UTF-8).
        A Thai site name is the realistic non-ASCII case (SPEC/CONTEXT.md —
        the product is deployed to Thai customer sites)."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "arichds.log").write_text(
            "2026-08-11T10:00:00+0700 | INFO     | arichds.test | site เชียงใหม่ variety\n",
            encoding="utf-8",
        )

        result = read_tail(log_dir, lines=500, min_level=None)

        assert result == [LogEntry("2026-08-11T10:00:00+0700", "INFO", "arichds.test", "site เชียงใหม่ variety")]
