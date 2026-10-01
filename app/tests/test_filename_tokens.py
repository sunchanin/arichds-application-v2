"""``arichds.filename_tokens`` — the one place the ``[meter]``/``[serial]``/
``[date]`` filename tokens are defined (reviewer finding, File Upload
Destination ticket 02 round 1, problem 1).

``export/format.py::render_filename`` delegates to
:func:`~arichds.filename_tokens.render_filename_tokens` rather than
reimplementing the substitution. ``TestRenderFilenameDelegates`` is the test
the reviewer's fix direction asked for: one that fails if the two disagree
— proven by mutating the shared function and confirming
``export.format.render_filename`` reflects the mutation, i.e. that the
correspondence is real delegation, not two functions that merely happen to
agree today.
"""

from __future__ import annotations

from arichds.export import format as export_format
from arichds.filename_tokens import export_filename_pattern, render_filename_tokens


class TestRenderFilenameTokens:
    def test_meter_and_serial_tokens_both_become_the_meter_token(self) -> None:
        assert render_filename_tokens("[meter]-[serial].csv", "SN0001") == "SN0001-SN0001.csv"

    def test_date_token_becomes_todays_iso_date(self) -> None:
        import datetime

        result = render_filename_tokens("[meter]-[date].csv", "SN0001")

        assert result == f"SN0001-{datetime.date.today().isoformat()}.csv"

    def test_a_template_with_no_tokens_is_unchanged(self) -> None:
        assert render_filename_tokens("static.csv", "SN0001") == "static.csv"


class TestExportFilenamePattern:
    def test_it_matches_what_render_filename_tokens_produces_today(self) -> None:
        template = "[meter]-energy.csv"
        rendered = render_filename_tokens(template, "SN0001")

        assert export_filename_pattern(template, "SN0001").match(rendered)

    def test_the_date_token_matches_any_iso_date_not_only_today(self) -> None:
        pattern = export_filename_pattern("[meter]-[date].csv", "SN0001")

        assert pattern.match("SN0001-2026-01-01.csv")
        assert pattern.match("SN0001-2099-12-31.csv")

    def test_it_does_not_match_a_different_devices_file(self) -> None:
        pattern = export_filename_pattern("[meter].csv", "SN0001")

        assert not pattern.match("SN0002.csv")

    def test_a_meter_token_with_a_regex_metacharacter_is_matched_literally(self) -> None:
        """A meter-supplied serial is device identity, not operator input
        (ADR 0005) — a serial containing `.` or `*` must not silently widen
        the match."""
        pattern = export_filename_pattern("[meter].csv", "SN.001")

        assert pattern.match("SN.001.csv")
        assert not pattern.match("SNX001.csv"), "the '.' in the serial matched any character instead of a literal dot"

    def test_it_is_fully_anchored(self) -> None:
        pattern = export_filename_pattern("[meter].csv", "SN0001")

        assert not pattern.match("prefix-SN0001.csv")
        assert not pattern.match("SN0001.csv-suffix")


class TestRenderFilenameDelegates:
    """The test the reviewer's fix direction named explicitly: one that
    fails if ``export/format.py::render_filename`` and the shared helper
    disagree."""

    def test_render_filename_calls_through_to_the_shared_helper(self, monkeypatch) -> None:  # noqa: ANN001
        monkeypatch.setattr(export_format, "render_filename_tokens", lambda _template, _meter_token: "MUTATED.csv")

        assert export_format.render_filename("[meter].csv", "SN0001") == "MUTATED.csv"
