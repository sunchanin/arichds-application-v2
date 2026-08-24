"""``capture.screenshot`` — unit coverage for the pieces below
``render_billing_png`` (ADR 0017, issue #38; the browser launch mechanism
reworked by issue #40): the DevTools port reader, the scheduled-task
trigger, the browser-level `Browser.close`, the row-wait loop over a fake
CDP transport, the capture serialisation lock, and the full ``_run_capture``
orchestration with every external dependency faked (no real Edge, no real
websocket, no real subprocess beyond what is mocked).
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import arichds.capture.screenshot as screenshot_module
from arichds.capture.screenshot import (
    BrowserCaptureError,
    MintedToken,
    _content_height,
    _drive_capture,
    _end_capture_task,
    _run_capture,
    _run_capture_with_hard_deadline,
    _trigger_capture_browser,
    _wait_for_devtools_port,
    _wait_for_rows,
    render_billing_png,
)
from arichds.capture.task import CAPTURE_TASK_NAME, EDGE_TASK_ARGUMENTS

# ── _wait_for_devtools_port ─────────────────────────────────────────────────


class TestWaitForDevtoolsPort:
    def test_reads_the_port_from_line_one(self, tmp_path: Path) -> None:
        (tmp_path / "DevToolsActivePort").write_text("54321\n/devtools/browser/abc\n", encoding="utf-8")

        assert _wait_for_devtools_port(tmp_path, time.monotonic() + 5) == 54321

    def test_polls_until_the_file_appears(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"n": 0}
        real_sleep = time.sleep

        def fake_sleep(seconds: float) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                (tmp_path / "DevToolsActivePort").write_text("9999\n", encoding="utf-8")
            real_sleep(0)  # yield without actually waiting, keeps the test fast

        monkeypatch.setattr(time, "sleep", fake_sleep)

        assert _wait_for_devtools_port(tmp_path, time.monotonic() + 5) == 9999
        assert calls["n"] >= 2

    def test_raises_browsercaptureerror_when_the_deadline_passes(self, tmp_path: Path) -> None:
        with pytest.raises(BrowserCaptureError):
            _wait_for_devtools_port(tmp_path, time.monotonic() - 1)  # already expired


# ── EDGE_TASK_ARGUMENTS (capture.task) ──────────────────────────────────────


class TestEdgeTaskArguments:
    def test_includes_hide_scrollbars(self) -> None:
        """Code review round, nit 6 (issue #38) — the Billing table scrolls
        horizontally, so an unhidden OS/browser scrollbar could land in the
        image; hiding it is chrome, not the column truncation ADR 0017
        decision 3 approved. Now a fixed installer-time constant
        (`capture/task.py`, issue #40) rather than a per-launch argument
        list, but the same rule still applies to it."""
        assert "--hide-scrollbars" in EDGE_TASK_ARGUMENTS

    def test_never_includes_no_sandbox(self) -> None:
        """Deliberately not added (see `capture/task.py`'s own docstring) —
        there is no evidence the sandbox needs disabling under
        `NT AUTHORITY\\LOCAL SERVICE`, and weakening it speculatively is not
        this issue's call to make."""
        assert "--no-sandbox" not in EDGE_TASK_ARGUMENTS


# ── No subprocess call this module makes may target an image name ─────────


class TestNoImageNameKill:
    def test_no_subprocess_call_targets_taskkill_im_or_msedge(
        self, settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stronger form of #38's `test_kills_by_pid_never_by_image_name`
        (issue #40) — there is no PID any more to kill by, so the rule this
        test now enforces is that **nothing** this module runs targets
        `taskkill`, `/IM`, or `msedge` at all: every process stop goes
        through the named scheduled task (`schtasks /end`), never a direct
        process kill. The operator's own browser shares the `msedge.exe`
        image name."""
        settings.ensure_directories()
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
            calls.append(list(args))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        popen_calls: list[Any] = []
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: popen_calls.append((a, k)))

        _trigger_capture_browser()
        _end_capture_task()

        assert popen_calls == []  # nothing launches a raw process any more
        assert len(calls) >= 2
        for args in calls:
            joined = " ".join(str(arg) for arg in args).lower()
            assert "taskkill" not in joined
            assert "/im" not in joined
            assert "msedge" not in joined


# ── _end_capture_task ────────────────────────────────────────────────────


class TestEndCaptureTask:
    def test_runs_schtasks_end_naming_the_task(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
            calls.append(list(args))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        _end_capture_task()

        assert len(calls) == 1
        assert calls[0][:2] == ["schtasks", "/end"]
        assert CAPTURE_TASK_NAME in calls[0]

    def test_a_missing_schtasks_is_logged_and_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(args: list[str], **kwargs: object) -> None:
            raise OSError("schtasks not found")

        monkeypatch.setattr(subprocess, "run", fake_run)

        _end_capture_task()  # must not raise

    def test_a_nonzero_exit_is_not_raised_and_not_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D8 — `/end`'s exit code and status text are never informative
        (a task already `Ready`, F7) and are never checked, only ever
        run-and-forget."""

        def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(returncode=1, stdout="ERROR: The task is not currently running.", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        _end_capture_task()  # must not raise despite the non-zero exit


# ── _trigger_capture_browser ─────────────────────────────────────────────


class TestTriggerCaptureBrowser:
    """Each test proves one of decisions D7/D8 discriminates against the
    reversed behaviour, not merely that `_trigger_capture_browser` runs."""

    def test_end_is_issued_before_run(self, settings: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """D7 — assert the recorded call *order*, not just that both calls
        happened; a reversed order would leave a task marked `Running` from
        the previous capture unhealed before the new `/run`."""
        settings.ensure_directories()
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
            calls.append(list(args))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        _trigger_capture_browser()

        assert len(calls) == 2
        assert calls[0][:2] == ["schtasks", "/end"]
        assert calls[1][:2] == ["schtasks", "/run"]

    def test_the_stale_devtools_port_is_gone_at_the_moment_run_is_issued(
        self, settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not merely gone *afterwards* — the fake `subprocess.run` checks
        the file's existence *at the instant* the `/run` call is made,
        which fails if the deletion were reordered to after `/run` (or
        dropped) rather than between `/end` and `/run`."""
        settings.ensure_directories()
        port_file = settings.tmp_dir / "DevToolsActivePort"
        port_file.write_text("54321\n/devtools/browser/stale\n", encoding="utf-8")

        observed_at_run: list[bool] = []

        def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
            if "/run" in args:
                observed_at_run.append(port_file.exists())
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        _trigger_capture_browser()

        assert observed_at_run == [False]

    def test_a_nonzero_run_exit_code_raises_browsercaptureerror_with_the_output(
        self, settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings.ensure_directories()

        def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
            if "/run" in args:
                return SimpleNamespace(
                    returncode=1, stdout="ERROR: distinctive-stdout-marker", stderr="distinctive-stderr-marker"
                )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(BrowserCaptureError) as excinfo:
            _trigger_capture_browser()

        assert "distinctive-stdout-marker" in str(excinfo.value)
        assert "distinctive-stderr-marker" in str(excinfo.value)
        assert "1" in str(excinfo.value)

    def test_schtasks_missing_entirely_raises_browsercaptureerror_not_a_leaked_oserror(
        self, settings: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings.ensure_directories()

        def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
            if "/run" in args:
                raise FileNotFoundError("[WinError 2] The system cannot find the file specified: 'schtasks'")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(BrowserCaptureError):
            _trigger_capture_browser()


# ── _content_height ──────────────────────────────────────────────────────


class TestContentHeight:
    def test_reads_css_content_size(self) -> None:
        assert _content_height({"cssContentSize": {"height": 2400.0}}) == 2400.0

    def test_falls_back_to_content_size(self) -> None:
        assert _content_height({"contentSize": {"height": 1500.0}}) == 1500.0

    def test_falls_back_to_the_viewport_height_when_absent(self) -> None:
        assert _content_height({}) == 1080.0


# ── _connect_transport — proxy/max_size kwargs ─────────────────────────────


class TestConnectTransportKwargs:
    """Code review round, nit 8 — `proxy=None` and `max_size=_MAX_FRAME_SIZE`
    are the two `websockets.asyncio.client.connect` defaults the Findings
    section flagged as wrong for this use (proxy defaults to `True`, which
    could route a loopback call through a customer's `HTTP_PROXY`;
    `max_size` defaults to 1 MiB, too small for a multi-megabyte base64
    screenshot). Pinned against the actual call, not re-derived."""

    def test_connect_is_called_with_proxy_none_and_the_large_max_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        import websockets.asyncio.client as ws_client_module

        from arichds.capture.screenshot import _MAX_FRAME_SIZE, _connect_transport

        calls: list[dict[str, Any]] = []

        class FakeConnection:
            pass

        async def fake_connect(uri: str, **kwargs: Any) -> FakeConnection:
            calls.append({"uri": uri, **kwargs})
            return FakeConnection()

        monkeypatch.setattr(ws_client_module, "connect", fake_connect)

        async def fake_fetch(port: int, deadline: float) -> str:
            return "ws://127.0.0.1:9999/devtools/page/abc"

        monkeypatch.setattr(screenshot_module, "_fetch_first_page_ws_url", fake_fetch)

        asyncio.run(_connect_transport(9999, time.monotonic() + 5))

        assert len(calls) == 1
        assert calls[0]["proxy"] is None
        assert calls[0]["max_size"] == _MAX_FRAME_SIZE


# ── Fake CDP transport, used by both _wait_for_rows and the orchestration ──


class FakeTransport:
    """Records every ``request()`` call (method name, in order) and answers
    from a per-method queue of canned results — a fresh queue entry consumed
    per call, the last one repeated once exhausted."""

    def __init__(self, responses: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self._responses = responses or {}
        self._closed = False

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((method, params))
        queue = self._responses.get(method)
        if not queue:
            return {}
        return queue.pop(0) if len(queue) > 1 else queue[0]

    async def close(self) -> None:
        self._closed = True


def _evaluate_result(ids: list[str], mounted: bool = True) -> dict[str, Any]:
    return {"result": {"value": {"mounted": mounted, "ids": ids}}}


# ── _wait_for_rows ───────────────────────────────────────────────────────


class TestWaitForRows:
    async def _run(self, transport: FakeTransport, expected: list[str], budget: float) -> None:
        await _wait_for_rows(transport, expected, time.monotonic() + budget)

    def test_returns_as_soon_as_the_ids_match(self) -> None:
        import asyncio

        transport = FakeTransport(responses={"Runtime.evaluate": [_evaluate_result(["3", "2", "1"])]})

        asyncio.run(self._run(transport, ["3", "2", "1"], 5))

        assert transport.calls[-1][0] == "Runtime.evaluate"

    def test_a_reversed_observed_list_never_satisfies_the_wait(self) -> None:
        """The ordering check must genuinely discriminate — proven here at
        the wait-loop level, not just at `ids_match` in isolation."""
        import asyncio

        transport = FakeTransport(responses={"Runtime.evaluate": [_evaluate_result(["1", "2", "3"])]})

        with pytest.raises(BrowserCaptureError):
            asyncio.run(self._run(transport, ["3", "2", "1"], 0.6))

    def test_times_out_naming_both_lists(self) -> None:
        import asyncio

        transport = FakeTransport(responses={"Runtime.evaluate": [_evaluate_result(["1"])]})

        with pytest.raises(BrowserCaptureError) as excinfo:
            asyncio.run(self._run(transport, ["1", "2"], 0.4))

        assert "['1', '2']" in str(excinfo.value)
        assert "['1']" in str(excinfo.value)


# ── _drive_capture's seeded capture request — the end-bound inclusivity ────


class TestDriveCaptureSeedRequest:
    """Step 6 — the seeded ``endIso`` is exclusive (matching the API's own
    ``end`` bound), so it must be chosen to include the anchor row's own
    ``bill_date`` exactly, since ``_png_source_rows()`` is inclusive
    (``<=``). Proven by inspecting the actual seed script sent over the
    fake transport, not by re-deriving the value and comparing it to
    itself."""

    def test_the_seeded_end_bound_includes_the_anchor_bill_date(self) -> None:
        import asyncio

        anchor_bill_date = datetime(2026, 7, 31, 17, 0, 0, tzinfo=UTC)
        row = SimpleNamespace(id=1, device_id=7, meter_serial="SN-1", bill_date=anchor_bill_date)
        transport = FakeTransport(
            responses={
                "Runtime.evaluate": [_evaluate_result(["1"])],
                "Page.captureScreenshot": [{"data": _TINY_PNG_B64}],
            }
        )
        minted = MintedToken("raw-token", "token-hash", 1, "admin", "admin")

        asyncio.run(_drive_capture(transport, [row], minted, 8000, time.monotonic() + 5))

        seed_calls = [params for method, params in transport.calls if method == "Page.addScriptToEvaluateOnNewDocument"]
        assert len(seed_calls) == 1
        seed_script = seed_calls[0]["source"]

        # The exact ISO string a naive test would expect a `+1 second`
        # bound to produce — asserted against the actual script text, so a
        # regression to an exclusive (unmodified) bound is caught.
        assert "2026-07-31T17:00:01" in seed_script
        assert "2026-07-31T17:00:00+00:00" not in seed_script  # the exclusive (wrong) bound would read this

    def test_the_seeded_page_size_is_exactly_the_row_count_not_a_padded_constant(self) -> None:
        """Code review round, problem 1 (blocker) — `_png_source_rows()`
        already truncated to at most ten; the page must be asked for
        exactly that many, or a device with an eleventh closed period gets
        more rows on the page than `expected_ids` holds and every capture
        times out silently. Reproduces the reviewer's own proof at twelve
        rows (more than the ten-row cap), pinned against the actual
        recorded seed script — not re-derived and compared to itself."""
        import asyncio

        rows = [
            SimpleNamespace(
                id=row_id,
                device_id=7,
                meter_serial="SN-1",
                bill_date=datetime(2026, 7, 31, 17, 0, 0, tzinfo=UTC),
            )
            for row_id in range(12, 0, -1)  # 12 rows — one more than _png_source_rows()'s cap
        ]
        assert len(rows) == 12
        transport = FakeTransport(
            responses={
                "Runtime.evaluate": [_evaluate_result([str(row.id) for row in rows])],
                "Page.captureScreenshot": [{"data": _TINY_PNG_B64}],
            }
        )
        minted = MintedToken("raw-token", "token-hash", 1, "admin", "admin")

        asyncio.run(_drive_capture(transport, rows, minted, 8000, time.monotonic() + 5))

        seed_calls = [params for method, params in transport.calls if method == "Page.addScriptToEvaluateOnNewDocument"]
        seed_script = seed_calls[0]["source"]

        assert '"pageSize": 12' in seed_script
        assert '"pageSize": 50' not in seed_script  # the old padded constant


class TestDriveCaptureScreenshotGeometry:
    """Code review round, problem 3 — the id gate proves the ten rows are
    in the DOM, not that they are in the *pixels*. Three properties of the
    `Page.captureScreenshot` call carry that: the clip width matches the
    owner-approved 1920px truncation (ADR 0017 decision 3),
    `captureBeyondViewport` is set so a tall table is not itself clipped,
    and the clip height actually grows to the reported content height
    rather than staying pinned at the viewport."""

    def _run(self, transport: FakeTransport) -> dict[str, Any]:
        import asyncio

        row = SimpleNamespace(
            id=1, device_id=7, meter_serial="SN-1", bill_date=datetime(2026, 7, 31, 17, 0, 0, tzinfo=UTC)
        )
        minted = MintedToken("raw-token", "token-hash", 1, "admin", "admin")

        asyncio.run(_drive_capture(transport, [row], minted, 8000, time.monotonic() + 5))

        shots = [params for method, params in transport.calls if method == "Page.captureScreenshot"]
        assert len(shots) == 1
        return shots[0]

    def test_clip_width_is_the_owner_approved_viewport_width(self) -> None:
        transport = FakeTransport(
            responses={
                "Runtime.evaluate": [_evaluate_result(["1"])],
                "Page.getLayoutMetrics": [{"cssContentSize": {"height": 1080.0}}],
                "Page.captureScreenshot": [{"data": _TINY_PNG_B64}],
            }
        )

        params = self._run(transport)

        assert params["clip"]["width"] == 1920

    def test_capture_beyond_viewport_is_set(self) -> None:
        transport = FakeTransport(
            responses={
                "Runtime.evaluate": [_evaluate_result(["1"])],
                "Page.getLayoutMetrics": [{"cssContentSize": {"height": 1080.0}}],
                "Page.captureScreenshot": [{"data": _TINY_PNG_B64}],
            }
        )

        params = self._run(transport)

        assert params["captureBeyondViewport"] is True

    def test_clip_height_grows_past_the_viewport_when_the_content_is_taller(self) -> None:
        """`_content_height`'s own unit tests prove the parsing; this
        proves the parsed value actually reaches the clip that determines
        what lands in the file — the case where `ids_match` passes but a
        fixed-height clip would silently crop rows ten wide out of the
        image."""
        transport = FakeTransport(
            responses={
                "Runtime.evaluate": [_evaluate_result(["1"])],
                "Page.getLayoutMetrics": [{"cssContentSize": {"height": 2400.0}}],
                "Page.captureScreenshot": [{"data": _TINY_PNG_B64}],
            }
        )

        params = self._run(transport)

        assert params["clip"]["height"] == 2400.0

    def test_clip_height_never_shrinks_below_the_viewport(self) -> None:
        transport = FakeTransport(
            responses={
                "Runtime.evaluate": [_evaluate_result(["1"])],
                "Page.getLayoutMetrics": [{"cssContentSize": {"height": 200.0}}],  # shorter than the viewport
                "Page.captureScreenshot": [{"data": _TINY_PNG_B64}],
            }
        )

        params = self._run(transport)

        assert params["clip"]["height"] == 1080


# ── _run_capture orchestration — every external dependency faked ──────────


def _make_row(row_id: int, **overrides: object) -> SimpleNamespace:
    fields = {
        "id": row_id,
        "device_id": 7,
        "meter_serial": "SN-1",
        "bill_date": datetime(2026, 7, 31, 17, 0, 0, tzinfo=UTC),
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


async def _fake_close_browser_noop(port: int) -> None:
    """Every orchestration test below supplies its own fake `connect`, so
    `cleanup.port` never names a real Edge process — patched in so
    `_Cleanup.run()`'s best-effort `Browser.close` step never attempts a
    real network call against a port nothing is listening on (which would
    otherwise retry for the full `_BROWSER_CLOSE_TIMEOUT_SECONDS` every
    time). `_Cleanup.__init__` looks `_close_browser_over_cdp` up by name at
    construction time, so patching the module attribute before `_run_capture`
    constructs its `_Cleanup()` is enough — the same pattern issue #38 used
    for `_kill_process_tree`."""


class TestRunCaptureOrchestration:
    def _base_kwargs(self, tmp_path: Path, transport: FakeTransport, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        async def fake_connect(port: int, deadline: float) -> tuple[Any, FakeTransport]:
            return SimpleNamespace(close=_record_close), transport

        def fake_wait_for_port(profile_dir: Path, deadline: float) -> int:
            return 12345

        def fake_mint_token(session: Any) -> MintedToken:
            return MintedToken("raw-token", "token-hash", 1, "admin", "admin")

        def fake_trigger() -> None:
            return None

        monkeypatch.setattr(screenshot_module, "_close_browser_over_cdp", _fake_close_browser_noop)

        return {
            "resolve_edge": lambda: tmp_path / "msedge.exe",
            "mint_token": fake_mint_token,
            "trigger_browser": fake_trigger,
            "connect": fake_connect,
            "wait_for_port": fake_wait_for_port,
        }

    def test_seed_script_is_registered_before_navigation(
        self, migrated_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from arichds.config import get_settings

        get_settings().ensure_directories()
        transport = FakeTransport(
            responses={
                "Runtime.evaluate": [_evaluate_result(["1"])],
                "Page.captureScreenshot": [{"data": _TINY_PNG_B64}],
            }
        )
        monkeypatch.setattr(screenshot_module, "_end_capture_task", lambda: None)

        kwargs = self._base_kwargs(tmp_path, transport, monkeypatch)
        asyncio.run(_run_capture([_make_row(1)], "Main Incomer", **kwargs))

        methods = [method for method, _params in transport.calls]
        assert methods.index("Page.addScriptToEvaluateOnNewDocument") < methods.index("Page.navigate")
        # `Page.enable` before the seed registration — found empirically via
        # the real-Edge integration test (step 10): without it, the seed
        # script is silently never honoured and the SPA boots to Login with
        # an empty `localStorage`.
        assert methods.index("Page.enable") < methods.index("Page.addScriptToEvaluateOnNewDocument")

    def test_schtasks_end_runs_after_a_successful_capture(
        self, migrated_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Replaces #38's `test_kill_is_called_with_the_launched_pid` — there
        is no PID any more to kill; the equivalent unconditional teardown
        step (decision D6) is `schtasks /end`."""
        import asyncio

        from arichds.config import get_settings

        get_settings().ensure_directories()
        transport = FakeTransport(
            responses={
                "Runtime.evaluate": [_evaluate_result(["1"])],
                "Page.captureScreenshot": [{"data": _TINY_PNG_B64}],
            }
        )
        end_calls: list[bool] = []
        monkeypatch.setattr(screenshot_module, "_end_capture_task", lambda: end_calls.append(True))

        kwargs = self._base_kwargs(tmp_path, transport, monkeypatch)
        asyncio.run(_run_capture([_make_row(1)], "Main Incomer", **kwargs))

        assert end_calls == [True]

    def test_browser_close_is_invoked_with_the_launched_port(
        self, migrated_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Code review round, problem 2 — `Browser.close` was only ever
        proven correct in isolation (`TestCloseBrowserOverCdp`) or settable
        by hand on a bare `_Cleanup` instance
        (`TestCleanupRunsEndEvenWhenBrowserCloseRaises`); neither covers the
        orchestration seam between `_run_capture` and `_Cleanup` — that
        `cleanup.port` is actually set from the port `wait_for_port`
        returned, and that `_Cleanup.run()` actually calls `_close_browser`
        with it. Two mutations that leave every other test in this file
        green must both fail this one: dropping `cleanup.port = port` in
        `_run_capture`, and `if self.port is not None:` -> `if False:` in
        `_Cleanup.run()`."""
        import asyncio

        from arichds.config import get_settings

        get_settings().ensure_directories()
        transport = FakeTransport(
            responses={
                "Runtime.evaluate": [_evaluate_result(["1"])],
                "Page.captureScreenshot": [{"data": _TINY_PNG_B64}],
            }
        )
        monkeypatch.setattr(screenshot_module, "_end_capture_task", lambda: None)

        close_browser_calls: list[int] = []

        async def recording_close_browser(port: int) -> None:
            close_browser_calls.append(port)

        class RecordingCleanup(screenshot_module._Cleanup):
            def __init__(self) -> None:
                super().__init__()
                self._close_browser = recording_close_browser

        kwargs = self._base_kwargs(tmp_path, transport, monkeypatch)
        kwargs["cleanup_cls"] = RecordingCleanup
        asyncio.run(_run_capture([_make_row(1)], "Main Incomer", **kwargs))

        # `fake_wait_for_port` in `_base_kwargs` always returns 12345 — the
        # exact port `Browser.close` must be sent to.
        assert close_browser_calls == [12345]

    def test_the_profile_directory_still_exists_after_a_successful_capture(
        self, migrated_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Inverted from #38's `test_profile_dir_is_removed_after_success`
        (decision D2, issue #40): the profile directory is now fixed and
        reused between captures — the service never creates or removes it,
        so it must still be there afterwards, not gone."""
        import asyncio

        from arichds.config import get_settings

        settings = get_settings()
        settings.ensure_directories()
        transport = FakeTransport(
            responses={
                "Runtime.evaluate": [_evaluate_result(["1"])],
                "Page.captureScreenshot": [{"data": _TINY_PNG_B64}],
            }
        )
        monkeypatch.setattr(screenshot_module, "_end_capture_task", lambda: None)

        kwargs = self._base_kwargs(tmp_path, transport, monkeypatch)
        asyncio.run(_run_capture([_make_row(1)], "Main Incomer", **kwargs))

        assert settings.tmp_dir.is_dir()

    def test_token_and_schtasks_end_still_run_on_failure(
        self, migrated_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A timeout mid-capture must still run every cleanup step."""
        import asyncio

        from arichds.config import get_settings

        get_settings().ensure_directories()
        transport = FakeTransport(responses={"Runtime.evaluate": [_evaluate_result(["nope"])]})
        end_calls: list[bool] = []
        monkeypatch.setattr(screenshot_module, "_end_capture_task", lambda: end_calls.append(True))
        deleted_hashes: list[str] = []
        monkeypatch.setattr(screenshot_module, "_delete_capture_token", deleted_hashes.append)

        kwargs = self._base_kwargs(tmp_path, transport, monkeypatch)
        kwargs["budget_seconds"] = 0.4

        with pytest.raises(BrowserCaptureError):
            asyncio.run(_run_capture([_make_row(1)], "Main Incomer", **kwargs))

        assert end_calls == [True]
        assert deleted_hashes == ["token-hash"]

    def test_no_rows_raises_before_anything_is_launched(self, migrated_db: Any, tmp_path: Path) -> None:
        import asyncio

        with pytest.raises(BrowserCaptureError):
            asyncio.run(_run_capture([], "Main Incomer"))

    def test_missing_edge_raises_before_anything_else_happens(self, migrated_db: Any, tmp_path: Path) -> None:
        import asyncio

        with pytest.raises(BrowserCaptureError, match="Edge"):
            asyncio.run(_run_capture([_make_row(1)], "Main Incomer", resolve_edge=lambda: None))

    def test_the_token_is_still_deleted_when_the_trigger_raises(
        self, migrated_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Re-points #38's `..._when_the_profile_directory_cannot_be_created`
        regression (issue #40): there is no `mkdir` any more (decision D2),
        so the equivalent failure point between a successful mint and the
        rest of the capture is the trigger itself (`schtasks` missing, the
        task failing to start) — a failure there must still delete the
        already-minted token."""
        import asyncio

        from arichds.config import get_settings

        get_settings().ensure_directories()

        deleted_hashes: list[str] = []
        monkeypatch.setattr(screenshot_module, "_delete_capture_token", deleted_hashes.append)

        def fake_mint_token(session: Any) -> MintedToken:
            return MintedToken("raw-token", "token-hash", 1, "admin", "admin")

        def failing_trigger() -> None:
            raise BrowserCaptureError("schtasks /run failed")

        with pytest.raises(BrowserCaptureError):
            asyncio.run(
                _run_capture(
                    [_make_row(1)],
                    "Main Incomer",
                    resolve_edge=lambda: tmp_path / "msedge.exe",
                    mint_token=fake_mint_token,
                    trigger_browser=failing_trigger,
                )
            )

        assert deleted_hashes == ["token-hash"]


class HangingTransport:
    """A CDP transport whose `request()` never returns for one named
    method — simulates a renderer wedged in JS (code review round,
    problem 2): the browser process itself stays alive (it would keep
    answering CDP pings in reality), so nothing below
    `_run_capture_with_hard_deadline` notices on its own."""

    def __init__(self, hang_on: str) -> None:
        self.hang_on = hang_on
        self.calls: list[str] = []

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        import asyncio

        self.calls.append(method)
        if method == self.hang_on:
            await asyncio.sleep(999)  # never actually reached in a passing test
        return {}


class TestCleanupSurvivesCancellationDuringClose:
    """Code review round, problem 2 (issue #38) — a cancellation delivered
    *while* `_Cleanup.run()` is awaiting `connection.close()` must not skip
    the `schtasks /end`/delete steps that follow it (reworked for the
    scheduled-task teardown, issue #40, decision D6). Proven directly
    against `_Cleanup`, independent of `asyncio.wait_for`'s own cancel-once
    behaviour (the fake `close()` used elsewhere in this file never
    actually suspends, so it cannot exercise this path at all) — the task
    is cancelled by the test itself while it is genuinely suspended inside
    `close()`, which is exactly the scenario `asyncio.shield` in
    `_Cleanup.run()` exists for."""

    def test_a_cancellation_mid_close_still_runs_end_and_delete(self) -> None:
        import asyncio

        close_started = asyncio.Event()

        class SlowConnection:
            async def close(self) -> None:
                close_started.set()
                await asyncio.sleep(999)  # cancelled mid-await by the test itself, below

        end_calls: list[bool] = []
        deleted_hashes: list[str] = []

        cleanup = screenshot_module._Cleanup()
        cleanup.connection = SlowConnection()
        cleanup.port = None  # keep this test focused on close/end/delete ordering
        cleanup.token_hash = "token-hash"
        cleanup._end_capture_task = lambda: end_calls.append(True)
        cleanup._delete_token = deleted_hashes.append

        async def scenario() -> None:
            task = asyncio.ensure_future(cleanup.run())
            await close_started.wait()  # wait until `run()` is genuinely suspended inside close()
            task.cancel()
            await task  # must complete normally — run() swallows the cancellation itself

        asyncio.run(scenario())

        assert end_calls == [True]
        assert deleted_hashes == ["token-hash"]


class TestCleanupRunsEndEvenWhenBrowserCloseRaises:
    """D6 — `schtasks /end` is unconditional: a failing `Browser.close`
    must not prevent it (or the token delete after it) from running."""

    def test_schtasks_end_still_runs_when_browser_close_raises(self) -> None:
        import asyncio

        async def failing_close_browser(port: int) -> None:
            raise RuntimeError("CDP connection refused")

        end_calls: list[bool] = []
        deleted_hashes: list[str] = []

        cleanup = screenshot_module._Cleanup()
        cleanup.port = 9999
        cleanup.token_hash = "token-hash"
        cleanup._close_browser = failing_close_browser
        cleanup._end_capture_task = lambda: end_calls.append(True)
        cleanup._delete_token = deleted_hashes.append

        asyncio.run(cleanup.run())

        assert end_calls == [True]
        assert deleted_hashes == ["token-hash"]


class TestHardTimeoutCeiling:
    """Code review round, problem 2 (major) — the capture budget must be an
    enforced ceiling, not just a value the loops between CDP calls happen
    to check. A single wedged `Runtime.evaluate` (the polling call inside
    `_wait_for_rows`) never lets that loop's own deadline check run again,
    so only an outer, unconditional timeout can end it."""

    def test_a_wedged_cdp_call_is_killed_by_the_hard_ceiling_and_cleanup_still_runs(
        self, migrated_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from arichds.config import get_settings

        get_settings().ensure_directories()
        transport = HangingTransport(hang_on="Runtime.evaluate")

        end_calls: list[bool] = []
        monkeypatch.setattr(screenshot_module, "_end_capture_task", lambda: end_calls.append(True))
        deleted_hashes: list[str] = []
        monkeypatch.setattr(screenshot_module, "_delete_capture_token", deleted_hashes.append)
        monkeypatch.setattr(screenshot_module, "_close_browser_over_cdp", _fake_close_browser_noop)

        async def fake_connect(port: int, deadline: float) -> tuple[Any, HangingTransport]:
            return SimpleNamespace(close=_record_close), transport

        def fake_wait_for_port(profile_dir: Path, deadline: float) -> int:
            return 12345

        def fake_mint_token(session: Any) -> MintedToken:
            return MintedToken("raw-token", "token-hash", 1, "admin", "admin")

        def fake_trigger() -> None:
            return None

        start = time.monotonic()
        with pytest.raises(BrowserCaptureError, match="hard"):
            asyncio.run(
                _run_capture_with_hard_deadline(
                    [_make_row(1)],
                    "Main Incomer",
                    budget_seconds=0.3,
                    hard_margin=0.3,
                    resolve_edge=lambda: tmp_path / "msedge.exe",
                    mint_token=fake_mint_token,
                    trigger_browser=fake_trigger,
                    connect=fake_connect,
                    wait_for_port=fake_wait_for_port,
                )
            )
        elapsed = time.monotonic() - start

        # Nowhere near the real 90s budget, let alone the 999s the fake hangs for.
        assert elapsed < 5.0
        # Every cleanup step still ran despite the cancellation the hard
        # ceiling forced — this is the exact regression `_Cleanup.run()`'s
        # `asyncio.shield` guards against.
        assert end_calls == [True]
        assert deleted_hashes == ["token-hash"]

    def test_a_normal_capture_under_the_hard_ceiling_is_unaffected(
        self, migrated_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The wrapper must not interfere with an ordinary, fast capture —
        proven by driving it through `_run_capture_with_hard_deadline`
        exactly like `render_billing_png` does."""
        import asyncio

        from arichds.config import get_settings

        get_settings().ensure_directories()
        transport = FakeTransport(
            responses={
                "Runtime.evaluate": [_evaluate_result(["1"])],
                "Page.captureScreenshot": [{"data": _TINY_PNG_B64}],
            }
        )
        end_calls: list[bool] = []
        monkeypatch.setattr(screenshot_module, "_end_capture_task", lambda: end_calls.append(True))
        monkeypatch.setattr(screenshot_module, "_close_browser_over_cdp", _fake_close_browser_noop)

        async def fake_connect(port: int, deadline: float) -> tuple[Any, FakeTransport]:
            return SimpleNamespace(close=_record_close), transport

        def fake_wait_for_port(profile_dir: Path, deadline: float) -> int:
            return 12345

        def fake_mint_token(session: Any) -> MintedToken:
            return MintedToken("raw-token", "token-hash", 1, "admin", "admin")

        def fake_trigger() -> None:
            return None

        png_bytes = asyncio.run(
            _run_capture_with_hard_deadline(
                [_make_row(1)],
                "Main Incomer",
                resolve_edge=lambda: tmp_path / "msedge.exe",
                mint_token=fake_mint_token,
                trigger_browser=fake_trigger,
                connect=fake_connect,
                wait_for_port=fake_wait_for_port,
            )
        )

        assert png_bytes  # the real capture succeeded, not swallowed by the wrapper
        assert end_calls == [True]


# ── Browser-level Browser.close (Findings F1, issue #40) ───────────────────


class FakeHTTPResponse:
    """A urllib-compatible fake response — supports the `with opener.open(...)
    as response:` context-manager protocol :func:`_fetch_browser_ws_url` and
    :func:`_fetch_first_page_ws_url` both use."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


class TestFetchBrowserWsUrl:
    def test_hits_json_version_not_json_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """F1 — `Browser.close` needs the *browser-level* ws URL from
        `/json/version`, never `/json/list` (the page-level endpoint
        `_fetch_first_page_ws_url` uses, which `Browser.close` rejects with
        JSON-RPC -32601 when sent over a page-level connection)."""
        import asyncio

        requested_urls: list[str] = []

        class FakeOpener:
            def open(self, url: str, timeout: float | None = None) -> FakeHTTPResponse:
                requested_urls.append(url)
                payload = json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1:9999/devtools/browser/abc"}).encode(
                    "utf-8"
                )
                return FakeHTTPResponse(payload)

        monkeypatch.setattr(urllib.request, "build_opener", lambda *args, **kwargs: FakeOpener())

        result = asyncio.run(screenshot_module._fetch_browser_ws_url(9999, time.monotonic() + 5))

        assert result == "ws://127.0.0.1:9999/devtools/browser/abc"
        assert len(requested_urls) == 1
        assert "/json/version" in requested_urls[0]
        assert "/json/list" not in requested_urls[0]


class TestCloseBrowserOverCdp:
    def test_sends_browser_close_over_the_fetched_browser_level_connection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        import websockets.asyncio.client as ws_client_module

        connected_urls: list[str] = []

        class FakeBrowserConnection:
            async def close(self) -> None:
                return None

        async def fake_connect(uri: str, **kwargs: Any) -> FakeBrowserConnection:
            connected_urls.append(uri)
            return FakeBrowserConnection()

        monkeypatch.setattr(ws_client_module, "connect", fake_connect)

        async def fake_fetch(port: int, deadline: float) -> str:
            return "ws://127.0.0.1:9999/devtools/browser/abc-browser-level"

        monkeypatch.setattr(screenshot_module, "_fetch_browser_ws_url", fake_fetch)

        sent_requests: list[str] = []
        real_transport_cls = screenshot_module._WebSocketCdpTransport

        class RecordingTransport(real_transport_cls):
            async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
                sent_requests.append(method)
                return {}

        monkeypatch.setattr(screenshot_module, "_WebSocketCdpTransport", RecordingTransport)

        asyncio.run(screenshot_module._close_browser_over_cdp(9999))

        assert connected_urls == ["ws://127.0.0.1:9999/devtools/browser/abc-browser-level"]
        assert sent_requests == ["Browser.close"]

    def test_a_connection_closed_by_edge_mid_response_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Code review round, nit 1 — Edge tearing the socket down *is* what
        a successful `Browser.close` looks like; `_WebSocketCdpTransport`'s
        `recv()` loop raises `ConnectionClosed` in exactly that case, and it
        must not propagate as a failure (`_Cleanup.run()` would otherwise
        log a full traceback on every ordinary, successful close)."""
        import asyncio

        import websockets.asyncio.client as ws_client_module
        from websockets.exceptions import ConnectionClosedOK

        class FakeBrowserConnection:
            async def close(self) -> None:
                return None

        async def fake_connect(uri: str, **kwargs: Any) -> FakeBrowserConnection:
            return FakeBrowserConnection()

        monkeypatch.setattr(ws_client_module, "connect", fake_connect)

        async def fake_fetch(port: int, deadline: float) -> str:
            return "ws://127.0.0.1:9999/devtools/browser/abc"

        monkeypatch.setattr(screenshot_module, "_fetch_browser_ws_url", fake_fetch)

        real_transport_cls = screenshot_module._WebSocketCdpTransport

        class ClosesMidResponseTransport(real_transport_cls):
            async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
                raise ConnectionClosedOK(None, None)

        monkeypatch.setattr(screenshot_module, "_WebSocketCdpTransport", ClosesMidResponseTransport)

        asyncio.run(screenshot_module._close_browser_over_cdp(9999))  # must not raise


# ── Capture serialisation (decision D9, issue #40) ─────────────────────────


class TestCaptureLockSerialisesRenderBillingPng:
    def test_two_concurrent_calls_do_not_overlap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The second caller must wait for the first rather than running
        alongside it — proven by recording how many fake captures are
        in flight at once, not merely that both eventually complete."""
        import asyncio

        active = {"count": 0, "max_seen": 0}
        guard = threading.Lock()

        async def fake_run_capture(rows: Any, device_name: str, **kwargs: Any) -> bytes:
            with guard:
                active["count"] += 1
                active["max_seen"] = max(active["max_seen"], active["count"])
            await asyncio.sleep(0.2)
            with guard:
                active["count"] -= 1
            return b"png-bytes"

        monkeypatch.setattr(screenshot_module, "_run_capture_with_hard_deadline", fake_run_capture)

        results: list[bytes] = []
        results_guard = threading.Lock()

        def worker() -> None:
            png_bytes = render_billing_png([_make_row(1)], "Main Incomer")
            with results_guard:
                results.append(png_bytes)

        first = threading.Thread(target=worker)
        second = threading.Thread(target=worker)
        first.start()
        time.sleep(0.05)  # let `first` acquire the lock before `second` starts
        second.start()
        first.join(timeout=5)
        second.join(timeout=5)

        assert len(results) == 2
        assert active["max_seen"] == 1  # never both in flight at once

    def test_a_lock_held_past_the_timeout_raises_naming_contention(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A wedged capture must not hang the *other* caller's HTTP request
        forever — the wait is bounded, and the failure names contention
        rather than surfacing as an opaque hang or timeout deep inside the
        capture machinery."""
        monkeypatch.setattr(screenshot_module, "_CAPTURE_LOCK_TIMEOUT_SECONDS", 0.2)
        acquired = screenshot_module._CAPTURE_LOCK.acquire(timeout=1)
        assert acquired
        try:
            with pytest.raises(BrowserCaptureError, match="[Cc]apture"):
                render_billing_png([_make_row(1)], "Main Incomer")
        finally:
            screenshot_module._CAPTURE_LOCK.release()


class TestTmpDir:
    def test_ensure_directories_creates_tmp_dir(self, settings: Any) -> None:
        """`Settings.tmp_dir` (issue #38, step 4; the capture browser's one
        **reused** Edge profile directory rather than a fresh one per
        capture, issue #40 decision D2) — lives under
        `%ProgramData%\\ARICHDS` and is the only directory covered by the
        installer's `[Dirs] Permissions:` grant, unlike `%TEMP%`."""
        settings.ensure_directories()

        assert settings.tmp_dir == settings.data_dir.resolve() / "tmp"
        assert settings.tmp_dir.is_dir()


async def _record_close() -> None:
    return None


#: The smallest possible valid PNG (1x1, transparent) — signature + IHDR +
#: IDAT + IEND, base64-encoded. Used only as canned CDP screenshot data.
_TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
