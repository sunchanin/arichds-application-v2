"""``capture.screenshot`` — the Capture Style reaching the headless drive
(ADR 0028, capture-style ticket 02).

With the style at ``classic`` the seeded request says so, the viewport is
the previous program's fixed 1280×709 and the screenshot is exactly that
box — never grown to the content, never captured beyond the viewport. With
the style at ``standard`` every request the transport sees is the one it
saw before this ticket, pinned as a literal list rather than re-derived.
The style is read at write time on the same session the capture token is
minted with, proven by flipping the setting between two captures through
the same entry point.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_capture_screenshot_units import _TINY_PNG_B64, FakeTransport, _evaluate_result, _fake_close_browser_noop

import arichds.capture.screenshot as screenshot_module
from arichds.capture.dom import CAPTURE_REQUEST_GLOBAL, CLASSIC_TABLE_BODY_ROW_SELECTOR, TABLE_BODY_ROW_SELECTOR
from arichds.capture.screenshot import MintedToken, _drive_capture, _run_capture

BILL_DATE = datetime(2026, 7, 31, 17, 0, 0, tzinfo=UTC)


def _rows(*ids: int) -> list[SimpleNamespace]:
    """Newest first, as ``png_source_rows`` hands them over."""
    return [SimpleNamespace(id=row_id, device_id=7, meter_serial="SN-1", bill_date=BILL_DATE) for row_id in ids]


def _transport(page_ids: list[str]) -> FakeTransport:
    return FakeTransport(
        responses={
            "Runtime.evaluate": [_evaluate_result(page_ids)],
            "Page.getLayoutMetrics": [{"cssContentSize": {"height": 2400.0}}],
            "Page.captureScreenshot": [{"data": _TINY_PNG_B64}],
        }
    )


def _drive(transport: FakeTransport, rows: list[SimpleNamespace], style: str) -> None:
    minted = MintedToken("raw-token", "token-hash", 1, "admin", "admin")
    asyncio.run(_drive_capture(transport, rows, minted, 8000, time.monotonic() + 5, style=style))


def _seeded_request(transport: FakeTransport) -> dict[str, Any]:
    (params,) = [p for method, p in transport.calls if method == "Page.addScriptToEvaluateOnNewDocument"]
    source = params["source"]
    marker = f"window.{CAPTURE_REQUEST_GLOBAL} = "
    literal = source[source.index(marker) + len(marker) :].rstrip(";")
    return json.loads(literal)


class TestClassicDrive:
    def test_the_seeded_request_says_classic_and_names_the_anchor(self) -> None:
        transport = _transport(["1", "2", "3"])

        _drive(transport, _rows(3, 2, 1), "classic")

        request = _seeded_request(transport)
        assert request["style"] == "classic"
        assert request["anchorId"] == 3

    def test_the_viewport_is_the_previous_programs_fixed_1280_by_709(self) -> None:
        transport = _transport(["1"])

        _drive(transport, _rows(1), "classic")

        (params,) = [p for method, p in transport.calls if method == "Emulation.setDeviceMetricsOverride"]
        assert (params["width"], params["height"]) == (1280, 709)

    def test_the_screenshot_is_exactly_the_viewport_and_never_grows(self) -> None:
        transport = _transport(["1"])

        _drive(transport, _rows(1), "classic")

        (params,) = [p for method, p in transport.calls if method == "Page.captureScreenshot"]
        assert params["clip"] == {"x": 0, "y": 0, "width": 1280, "height": 709, "scale": 1}
        assert "captureBeyondViewport" not in params
        assert "Page.getLayoutMetrics" not in [method for method, _ in transport.calls]

    def test_the_row_gate_polls_the_classic_selector_and_waits_oldest_first(self) -> None:
        transport = _transport(["1", "2", "3"])

        _drive(transport, _rows(3, 2, 1), "classic")

        (params,) = [p for method, p in transport.calls if method == "Runtime.evaluate"]
        assert CLASSIC_TABLE_BODY_ROW_SELECTOR in params["expression"]
        assert TABLE_BODY_ROW_SELECTOR not in params["expression"]
        assert [method for method, _ in transport.calls].count("Page.captureScreenshot") == 1

    def test_a_page_answering_newest_first_never_satisfies_the_classic_gate(self) -> None:
        transport = _transport(["3", "2", "1"])

        with pytest.raises(screenshot_module.BrowserCaptureError, match="Classic page never rendered"):
            minted = MintedToken("raw-token", "token-hash", 1, "admin", "admin")
            asyncio.run(
                _drive_capture(transport, _rows(3, 2, 1), minted, 8000, time.monotonic() + 0.6, style="classic")
            )


class TestStandardDriveIsUnchanged:
    """The exact request list the fake transport recorded before this ticket
    (issue #38/#40's drive, ADR 0029's oldest-first gate) — a literal, so a
    Classic-only change that leaks into Standard moves this list."""

    def test_every_request_is_byte_identical_to_the_pre_style_drive(self) -> None:
        transport = _transport(["1", "2"])

        _drive(transport, _rows(2, 1), "standard")

        seed = _seeded_request(transport)
        assert seed == {
            "deviceId": 7,
            "meterSerial": "SN-1",
            "endIso": "2026-07-31T17:00:01+00:00",
            "pageSize": 2,
            "style": "standard",
            "anchorId": 2,
        }
        without_seed = [
            (method, params) for method, params in transport.calls if method != "Page.addScriptToEvaluateOnNewDocument"
        ]
        assert without_seed == [
            ("Page.enable", None),
            (
                "Emulation.setDeviceMetricsOverride",
                {"width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False},
            ),
            ("Page.navigate", {"url": "http://127.0.0.1:8000/"}),
            ("Runtime.evaluate", {"expression": screenshot_module.poll_script("standard"), "returnByValue": True}),
            ("Page.getLayoutMetrics", None),
            (
                "Page.captureScreenshot",
                {
                    "format": "png",
                    "captureBeyondViewport": True,
                    "clip": {"x": 0, "y": 0, "width": 1920, "height": 2400.0, "scale": 1},
                },
            ),
        ]


class TestTheStyleIsReadAtWriteTime:
    """`_run_capture` reads `capture_style` on the session it mints the token
    with — flipped between two captures through the same entry point, the
    second seed follows the flip (ADR 0001's never-cache rule)."""

    def _kwargs(self, tmp_path: Path, transport: FakeTransport, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        async def fake_connect(port: int, deadline: float) -> tuple[Any, FakeTransport]:
            return SimpleNamespace(close=_fake_close_browser_noop), transport

        monkeypatch.setattr(screenshot_module, "_close_browser_over_cdp", _fake_close_browser_noop)
        monkeypatch.setattr(screenshot_module, "_end_capture_task", lambda: None)
        return {
            "resolve_edge": lambda: tmp_path / "msedge.exe",
            "mint_token": lambda session: MintedToken("raw-token", "token-hash", 1, "admin", "admin"),
            "trigger_browser": lambda: None,
            "connect": fake_connect,
            "wait_for_port": lambda profile_dir, deadline: 12345,
        }

    def test_the_second_capture_follows_a_flip_of_the_setting(
        self, migrated_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from arichds.config import get_settings
        from arichds.db.app_settings import CAPTURE_STYLE_KEY, set_setting
        from arichds.db.session import session_scope

        get_settings().ensure_directories()

        first = _transport(["1"])
        asyncio.run(_run_capture(_rows(1), "Main Incomer", **self._kwargs(tmp_path, first, monkeypatch)))
        assert _seeded_request(first)["style"] == "standard"

        with session_scope() as session:
            set_setting(session, CAPTURE_STYLE_KEY, "classic")

        second = _transport(["1"])
        asyncio.run(_run_capture(_rows(1), "Main Incomer", **self._kwargs(tmp_path, second, monkeypatch)))
        assert _seeded_request(second)["style"] == "classic"
        (metrics,) = [p for method, p in second.calls if method == "Emulation.setDeviceMetricsOverride"]
        assert (metrics["width"], metrics["height"]) == (1280, 709)
