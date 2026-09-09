"""ADR 0013's boundary, asserted in **both** directions (M13, issue 07).

The rule: the machine-wide display-unit setting reaches anything rendered per
request, and never an appended file. Until this issue no column existed that
the boundary ran through in both directions — the file carried energy and the
setting converts energy, but the Load Profile page had no column the file also
carried and the setting touched in a way the file had to refuse. The four
average-power columns are the first, so this is the first time the rule is
testable rather than merely stated.

The file half is proven properly, against real bytes on disk, in
``test_csv_export.py`` — ``TestNeverFollowsTheDisplayUnitSetting`` exports the
same rows under both settings and compares the files byte for byte.

**This module is the page half, and it is a source-level tripwire, not a
proof.** There is no JavaScript test runner in this repository, so what is
checked is that the page's column definitions route the four power columns
through the conversion helpers. A grep can be fooled by a commented-out line;
the same caveat ``test_capture_dom_contract.py`` states about its own checks
applies here. It is still worth having: the failure it catches — someone adding
a fifth power column, or moving one out of the scaled tuple — is a silent
one-line edit that no other test in this repository would notice.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LOAD_PROFILE_PAGE = REPO_ROOT / "web" / "src" / "pages" / "LoadProfile.tsx"

#: The four columns the setting converts on the screen and never in the file.
POWER_COLUMNS = ("import_active_kw", "import_reactive_kvar", "export_active_kw", "export_reactive_kvar")

#: The three groups it must leave alone in both places — a phase angle in
#: degrees and a line-to-line voltage have no kilo/base form, and scaling one
#: would be a wrong number rather than a differently-labelled one.
UNSCALED_NEW_COLUMNS = (
    "phase_angle_a",
    "phase_angle_b",
    "phase_angle_c",
    "volt_l1_l2",
    "volt_l2_l3",
    "volt_l3_l1",
)


@pytest.fixture(scope="module")
def page_source() -> str:
    """``web/src`` is committed, so this never skips."""
    return LOAD_PROFILE_PAGE.read_text(encoding="utf-8")


def _scaled_tuple(source: str) -> str:
    """The body of ``SCALED_POWER_COLUMNS`` — the one declaration that decides
    which columns the page converts."""
    match = re.search(r"const SCALED_POWER_COLUMNS[^=]*=\s*\[(.*?)\n\];", source, re.DOTALL)
    assert match is not None, "SCALED_POWER_COLUMNS is gone or was renamed — the page half of the boundary moved"
    return match.group(1)


def _build_columns_body(source: str) -> str:
    """The body of ``buildColumns`` — what the table actually renders, as
    opposed to what is merely declared above it."""
    match = re.search(r"function buildColumns\([^)]*\)[^{]*\{(.*?)\n\}", source, re.DOTALL)
    assert match is not None, "buildColumns is gone or was renamed"
    return match.group(1)


class TestEveryNewColumnReachesThePage:
    """Issue 07 asks for all eleven on the Load Profile page, so that a number
    that looks wrong in the file can be checked without opening the file."""

    def test_all_eleven_are_rendered_columns(self, page_source: str) -> None:
        body = _build_columns_body(page_source)
        rendered = set(re.findall(r'key: "([a-z0-9_]+)"', body))
        # The four power columns arrive through the spread, not by literal key.
        rendered |= set(POWER_COLUMNS) if "...powerColumns," in body else set()
        expected = {*POWER_COLUMNS, *UNSCALED_NEW_COLUMNS, "interval_status"}
        assert expected <= rendered, f"missing from the page: {sorted(expected - rendered)}"

    def test_the_status_column_renders_the_decoded_wording_not_the_raw_word(self, page_source: str) -> None:
        """The decoding happens on the server (``arichds/interval_status.py``),
        so the page reads ``interval_status`` and never ``interval_status_flag``
        — one decoder, not a TypeScript twin of it."""
        body = _build_columns_body(page_source)
        assert 'dataIndex: "interval_status"' in body
        assert 'dataIndex: "interval_status_flag"' not in body


class TestThePageHalfConvertsTheFourPowerColumns:
    def test_every_power_column_is_declared_scale_aware(self, page_source: str) -> None:
        declared = _scaled_tuple(page_source)
        missing = [name for name in POWER_COLUMNS if f'"{name}"' not in declared]
        assert not missing, f"{missing} would render unconverted on the screen"

    def test_the_scale_aware_tuple_holds_nothing_else(self, page_source: str) -> None:
        """A column that has no kilo/base form must not be in here. Scaling a
        phase angle by a thousand is not a differently-labelled number, it is a
        wrong one."""
        declared = _scaled_tuple(page_source)
        offenders = [name for name in UNSCALED_NEW_COLUMNS if f'"{name}"' in declared]
        assert not offenders, f"{offenders} have no kilo/base form and must never be converted"

    def test_the_declaration_is_routed_through_the_conversion_helpers(self, page_source: str) -> None:
        """``scaleValue`` moves the number and ``unitLabel`` moves the header;
        the rule the feature must never break is that the two move together."""
        assert "scaleValue(value, scale)" in page_source
        assert "unitLabel(column.unit, scale)" in page_source
        assert "scaled(SCALED_POWER_COLUMNS)" in page_source

    def test_the_built_columns_actually_include_them(self, page_source: str) -> None:
        """Declaring a scale-aware tuple and never spreading it into the
        returned columns would leave the four off the page entirely, with the
        tests above all still green — a surviving mutation when this module was
        first written, which is why this assertion exists."""
        assert "...powerColumns," in _build_columns_body(page_source)

    def test_the_power_columns_declare_a_power_unit_kind(self, page_source: str) -> None:
        """``unitLabel`` keys on this: an active column labelled
        ``reactivePower`` would print ``kvar`` over watts."""
        declared = _scaled_tuple(page_source)
        for name, expected in (
            ("import_active_kw", "power"),
            ("export_active_kw", "power"),
            ("import_reactive_kvar", "reactivePower"),
            ("export_reactive_kvar", "reactivePower"),
        ):
            line = next(line for line in declared.splitlines() if f'"{name}"' in line)
            assert f'unit: "{expected}"' in line, f"{name} is declared as something other than {expected}"


class TestTheFileHalfNeverSeesTheSetting:
    """The mirror of the above, and the reason both live in one module: a
    reader who changes one half should be looking at the other.

    The substantive proof is ``test_csv_export.py``'s byte-for-byte comparison
    under both settings; this is the structural guard that keeps the export
    package unable to reach the machinery at all.
    """

    def test_the_export_package_imports_none_of_the_display_unit_machinery(self) -> None:
        export_dir = REPO_ROOT / "app" / "src" / "arichds" / "export"
        forbidden = ("display_unit_scale", "DISPLAY_UNIT_SCALE_KEY", "scale_value", "_render_shared")
        offenders = [
            (path.name, term)
            for path in export_dir.glob("*.py")
            for term in forbidden
            if term in path.read_text(encoding="utf-8")
        ]
        assert offenders == []
