"""``capture.dom`` — the DOM/JS contract between ``web/`` and ``app/`` (ADR
0017, issue #38).

Two independent things are tested here:

* :func:`~arichds.capture.dom.ids_match` — the pure comparison the
  verification gate (step 5) is built on. No browser needed.
* The contract itself — that our own strings (``web/src`` is committed, so
  this half never skips) and AntD's own selectors (skipped when
  ``web/node_modules`` is absent) still match what :mod:`arichds.capture.dom`
  declares. A grep can be fooled by a commented-out line — this is a cheap
  tripwire, not a proof the string is *live* in the running page.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arichds.capture.dom import (
    APP_SHELL_SELECTOR,
    CAPTURE_REQUEST_GLOBAL,
    ROW_KEY_ATTRIBUTE,
    SESSION_STORAGE_KEY,
    TABLE_BODY_ROW_SELECTOR,
    build_seed_script,
    ids_match,
    poll_script,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_SRC = REPO_ROOT / "web" / "src"


class TestIdsMatch:
    """T-gate (step 5) — the ordering check must genuinely discriminate: a
    test that passes with a reversed ``observed`` list is not a test."""

    def test_exact_match_passes(self) -> None:
        assert ids_match(["3", "2", "1"], ["3", "2", "1"]) is True

    def test_a_missing_row_fails(self) -> None:
        assert ids_match(["3", "2", "1"], ["3", "2"]) is False

    def test_an_extra_row_fails(self) -> None:
        assert ids_match(["3", "2"], ["3", "2", "1"]) is False

    def test_same_ids_different_order_fails(self) -> None:
        assert ids_match(["3", "2", "1"], ["1", "2", "3"]) is False

    def test_both_empty_matches(self) -> None:
        """No rows expected (an edge case the caller should not hit in
        practice — see ``render_billing_png``'s own docstring) is still a
        well-defined comparison: nothing rendered is the correct match for
        nothing expected."""
        assert ids_match([], []) is True


class TestBuildSeedScript:
    def test_session_is_written_as_a_json_string_not_an_object_literal(self) -> None:
        """``localStorage.setItem`` always stores a string — the seed script
        must call it with a JSON *string*, matching ``auth.ts``'s own
        ``JSON.parse(raw)`` on read, not a bare object literal it cannot
        parse."""
        script = build_seed_script({"id": 1, "token": "tok", "username": "admin", "role": "admin"}, {})

        assert 'localStorage.setItem("arichds.session", "{' in script

    def test_capture_request_is_a_plain_object_literal_on_the_global(self) -> None:
        script = build_seed_script(
            {}, {"deviceId": 7, "meterSerial": "ABC", "endIso": "2026-01-01T00:00:00+00:00", "pageSize": 50}
        )

        assert f'window.{CAPTURE_REQUEST_GLOBAL} = {{"deviceId": 7' in script


class TestPollScript:
    def test_references_the_declared_selectors(self) -> None:
        script = poll_script()

        assert TABLE_BODY_ROW_SELECTOR in script
        assert ROW_KEY_ATTRIBUTE in script
        assert APP_SHELL_SELECTOR in script


class TestOurOwnContract:
    """Grep-based, never skipped — ``web/src`` is committed."""

    def test_session_storage_key_matches_auth_ts(self) -> None:
        text = (WEB_SRC / "auth.ts").read_text(encoding="utf-8")
        assert f'"{SESSION_STORAGE_KEY}"' in text

    def test_capture_request_global_matches_capture_ts(self) -> None:
        text = (WEB_SRC / "capture.ts").read_text(encoding="utf-8")
        assert CAPTURE_REQUEST_GLOBAL in text

    def test_row_key_reads_the_row_id_in_billing_tsx(self) -> None:
        text = (WEB_SRC / "pages" / "Billing.tsx").read_text(encoding="utf-8")
        assert "rowKey={(row) => row.id}" in text


def _rc_table_body_dir() -> Path | None:
    pnpm_dir = REPO_ROOT / "web" / "node_modules" / ".pnpm"
    if not pnpm_dir.exists():
        return None
    for candidate in pnpm_dir.glob("@rc-component+table@*/node_modules/@rc-component/table/es/Body"):
        if candidate.is_dir():
            return candidate
    return None


@pytest.mark.skipif(_rc_table_body_dir() is None, reason="web/node_modules is not installed")
class TestAntDContract:
    """Skipped when ``web/node_modules`` is absent — this is what catches an
    AntD upgrade; it cannot run on an install without the frontend deps."""

    def test_body_row_sets_the_row_key_attribute(self) -> None:
        body_dir = _rc_table_body_dir()
        assert body_dir is not None
        text = (body_dir / "BodyRow.js").read_text(encoding="utf-8")
        assert '"data-row-key"' in text

    def test_tbody_carries_the_declared_class(self) -> None:
        body_dir = _rc_table_body_dir()
        assert body_dir is not None
        text = (body_dir / "index.js").read_text(encoding="utf-8")
        assert "-tbody" in text
        assert TABLE_BODY_ROW_SELECTOR == ".ant-table-tbody tr[data-row-key]"

    def test_measure_row_carries_no_row_key_attribute(self) -> None:
        body_dir = _rc_table_body_dir()
        assert body_dir is not None
        text = (body_dir / "MeasureRow.js").read_text(encoding="utf-8")
        assert "measure-row" in text
        assert "data-row-key" not in text
