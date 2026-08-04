"""The vendored Gurux frame trace must never reach disk.

Regression test for a credential leak inherited from v1: ``GXDLMSReader`` opens
``logFile.txt`` in the CWD and ``writeTrace`` writes to it **unconditionally**
(the trace-level check gates only the ``print``). The trace contains the raw
AARQ frame, so the DLMS password lands in a plaintext file that never passes the
credential redaction filter.

These tests pin the seam that closes it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from arichds.acquisition.drivers._gurux_trace import _RedactedTraceSink, silence_frame_trace

# A real association-request line as the vendored reader emits it. The password
# "ABCD0001" is the bare hex 41 42 43 44 30 30 30 31 — no `key=value` shape, so
# CredentialRedactionFilter cannot touch it. That is precisely why these lines
# must never be handed to the logger at all.
AARQ_FRAME_LINE = (
    "TX: 20:23:02\t00 01 00 20 00 01 00 38 60 36 A1 09 06 07 60 85 74 05 08 01 01 8A 02 07 80 "
    "8B 07 60 85 74 05 08 02 01 AC 0A 80 08 41 42 43 44 30 30 30 31 BE 10 04 0E 01 00 00 00\n"
)
PASSWORD_HEX = "41 42 43 44 30 30 30 31"


class FakeReader:
    """Stands in for GXDLMSReader: it owns an open trace file, nothing more."""

    def __init__(self, handle) -> None:  # noqa: ANN001
        self.logFile = handle


class TestSilenceFrameTrace:
    def test_replaces_the_file_handle_with_the_sink(self, tmp_path: Path) -> None:
        path = tmp_path / "logFile.txt"
        reader = FakeReader(path.open("w"))

        silence_frame_trace(reader)

        assert isinstance(reader.logFile, _RedactedTraceSink)

    def test_closes_the_real_file(self, tmp_path: Path) -> None:
        handle = (tmp_path / "logFile.txt").open("w")
        reader = FakeReader(handle)

        silence_frame_trace(reader)

        assert handle.closed

    def test_nothing_written_after_silencing_reaches_disk(self, tmp_path: Path) -> None:
        """The whole point: a password-bearing frame must not land in a file."""
        path = tmp_path / "logFile.txt"
        reader = FakeReader(path.open("w"))
        silence_frame_trace(reader)

        reader.logFile.write(AARQ_FRAME_LINE)

        assert path.read_text(encoding="utf-8") == ""
        assert PASSWORD_HEX not in path.read_text(encoding="utf-8")

    def test_survives_a_reader_with_no_log_file(self) -> None:
        """Never let cleanup break a connect."""

        class Bare:
            pass

        reader = Bare()
        silence_frame_trace(reader)
        assert isinstance(reader.logFile, _RedactedTraceSink)

    def test_removes_the_empty_stray_file_from_the_cwd(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        stray = tmp_path / "logFile.txt"
        reader = FakeReader(stray.open("w"))

        silence_frame_trace(reader)

        assert not stray.exists()

    def test_keeps_a_non_empty_stray_file(self, tmp_path: Path, monkeypatch) -> None:
        """Only the empty file this seam caused is cleaned up — never real data."""
        monkeypatch.chdir(tmp_path)
        stray = tmp_path / "logFile.txt"
        handle = stray.open("w")
        handle.write("pre-existing content someone may want\n")
        reader = FakeReader(handle)

        silence_frame_trace(reader)

        assert stray.exists()


class TestFrameLinesNeverReachAHandler:
    """The credential leak, closed rather than relocated.

    Forwarding frames to ``logger.debug`` looked safe but was not: the redaction
    filter matches ``password=…``, never bare hex. With
    ``ARICHDS_LOG_LEVEL=DEBUG`` — a documented knob — the password would reach
    ``logs/arichds.log``, NSSM's ``service.log`` and M7's App Log page.
    """

    @pytest.mark.parametrize("level", [logging.NOTSET, logging.DEBUG, logging.INFO, logging.WARNING])
    def test_aarq_frame_emits_no_log_record_at_any_level(self, level: int, caplog: pytest.LogCaptureFixture) -> None:
        sink = _RedactedTraceSink()
        with caplog.at_level(level, logger="arichds.acquisition.drivers._gurux_trace"):
            sink.write(AARQ_FRAME_LINE)

        assert caplog.records == [], "a raw frame reached a log handler"
        assert PASSWORD_HEX not in caplog.text

    def test_rx_frames_are_dropped_too(self, caplog: pytest.LogCaptureFixture) -> None:
        sink = _RedactedTraceSink()
        with caplog.at_level(logging.NOTSET, logger="arichds.acquisition.drivers._gurux_trace"):
            sink.write("RX: 20:23:02\t00 01 00 01 00 20 00 2B 61 29\n")
        assert caplog.records == []

    def test_the_escape_hatch_is_off_by_default(self) -> None:
        """It must take a source edit — never an env var — to log raw frames."""
        from arichds.acquisition.drivers import _gurux_trace

        assert _gurux_trace.ALLOW_FRAME_TRACE is False

    def test_frames_can_be_re_enabled_on_a_bench(self, monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
        """The diagnostic is recoverable when someone deliberately asks for it."""
        from arichds.acquisition.drivers import _gurux_trace

        monkeypatch.setattr(_gurux_trace, "ALLOW_FRAME_TRACE", True)
        sink = _RedactedTraceSink()
        with caplog.at_level(logging.DEBUG, logger="arichds.acquisition.drivers._gurux_trace"):
            sink.write("TX: 00 01 02\n")
        assert "TX: 00 01 02" in caplog.text


class TestRedactedTraceSink:
    def test_forwards_non_frame_diagnostics_at_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        """Profile/column diagnostics carry no association frame and stay useful."""
        sink = _RedactedTraceSink()
        with caplog.at_level(logging.DEBUG, logger="arichds.acquisition.drivers._gurux_trace"):
            sink.write("Index: 3 Value: 240.1\n")
        assert "Index: 3 Value: 240.1" in caplog.text

    def test_blank_lines_are_dropped(self, caplog: pytest.LogCaptureFixture) -> None:
        sink = _RedactedTraceSink()
        with caplog.at_level(logging.DEBUG, logger="arichds.acquisition.drivers._gurux_trace"):
            sink.write("\n")
        assert caplog.text == ""

    def test_write_returns_the_character_count(self) -> None:
        """File-like enough for the vendored caller."""
        assert _RedactedTraceSink().write("abc\n") == 4

    def test_dropped_frames_still_report_a_full_write(self) -> None:
        """A short write would look like a disk error to the vendored caller."""
        assert _RedactedTraceSink().write(AARQ_FRAME_LINE) == len(AARQ_FRAME_LINE)
