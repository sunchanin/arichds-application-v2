"""``capture.screenshot`` — unit coverage for the pieces below
``render_billing_png`` (ADR 0017, issue #38): the DevTools port reader, the
by-PID kill, the row-wait loop over a fake CDP transport, and the full
``_run_capture`` orchestration with every external dependency faked (no
real Edge, no real websocket, no real subprocess beyond what is mocked).
"""

from __future__ import annotations

import subprocess
import time
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
    _kill_process_tree,
    _run_capture,
    _run_capture_with_hard_deadline,
    _wait_for_devtools_port,
    _wait_for_rows,
)

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


# ── _launch_edge ─────────────────────────────────────────────────────────


class TestLaunchEdgeArgs:
    def test_includes_hide_scrollbars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Code review round, nit 6 — the Billing table scrolls
        horizontally, so an unhidden OS/browser scrollbar could land in the
        image; hiding it is chrome, not the column truncation ADR 0017
        decision 3 approved."""
        captured_args: list[list[str]] = []

        def fake_popen(args: list[str], **kwargs: object) -> SimpleNamespace:
            captured_args.append(args)
            return SimpleNamespace(pid=1)

        monkeypatch.setattr(subprocess, "Popen", fake_popen)

        screenshot_module._launch_edge(tmp_path / "msedge.exe", tmp_path / "profile")

        assert "--hide-scrollbars" in captured_args[0]

    def test_never_includes_no_sandbox(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Deliberately not added (see `_launch_edge`'s own docstring) —
        there is no evidence the sandbox needs disabling under
        `NT AUTHORITY\\LocalService`, and weakening it speculatively is not
        this issue's call to make."""
        captured_args: list[list[str]] = []

        def fake_popen(args: list[str], **kwargs: object) -> SimpleNamespace:
            captured_args.append(args)
            return SimpleNamespace(pid=1)

        monkeypatch.setattr(subprocess, "Popen", fake_popen)

        screenshot_module._launch_edge(tmp_path / "msedge.exe", tmp_path / "profile")

        assert "--no-sandbox" not in captured_args[0]


# ── _kill_process_tree ──────────────────────────────────────────────────────


class TestKillProcessTree:
    def test_kills_by_pid_never_by_image_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> None:
            calls.append(args)

        monkeypatch.setattr(subprocess, "run", fake_run)

        _kill_process_tree(4242)

        assert len(calls) == 1
        args = calls[0]
        assert args[:2] == ["taskkill", "/PID"]
        assert "4242" in args
        assert "/T" in args and "/F" in args
        assert not any("/IM" in arg for arg in args)
        assert not any("msedge" in arg.lower() for arg in args)

    def test_a_failed_kill_is_logged_and_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(args: list[str], **kwargs: object) -> None:
            raise OSError("no such process")

        monkeypatch.setattr(subprocess, "run", fake_run)

        _kill_process_tree(1)  # must not raise


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


class FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid


class TestRunCaptureOrchestration:
    def _base_kwargs(self, tmp_path: Path, transport: FakeTransport, kill_calls: list[int]) -> dict[str, Any]:
        async def fake_connect(port: int, deadline: float) -> tuple[Any, FakeTransport]:
            return SimpleNamespace(close=_record_close), transport

        def fake_wait_for_port(profile_dir: Path, deadline: float) -> int:
            return 12345

        def fake_mint_token(session: Any) -> MintedToken:
            return MintedToken("raw-token", "token-hash", 1, "admin", "admin")

        def fake_launch(edge_path: Path, profile_dir: Path) -> FakeProcess:
            return FakeProcess(pid=999)

        return {
            "resolve_edge": lambda: tmp_path / "msedge.exe",
            "mint_token": fake_mint_token,
            "launch_edge": fake_launch,
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
        kill_calls: list[int] = []
        monkeypatch.setattr(screenshot_module, "_kill_process_tree", kill_calls.append)

        kwargs = self._base_kwargs(tmp_path, transport, kill_calls)
        asyncio.run(_run_capture([_make_row(1)], "Main Incomer", **kwargs))

        methods = [method for method, _params in transport.calls]
        assert methods.index("Page.addScriptToEvaluateOnNewDocument") < methods.index("Page.navigate")
        # `Page.enable` before the seed registration — found empirically via
        # the real-Edge integration test (step 10): without it, the seed
        # script is silently never honoured and the SPA boots to Login with
        # an empty `localStorage`.
        assert methods.index("Page.enable") < methods.index("Page.addScriptToEvaluateOnNewDocument")

    def test_kill_is_called_with_the_launched_pid(
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
        kill_calls: list[int] = []
        monkeypatch.setattr(screenshot_module, "_kill_process_tree", kill_calls.append)

        kwargs = self._base_kwargs(tmp_path, transport, kill_calls)
        asyncio.run(_run_capture([_make_row(1)], "Main Incomer", **kwargs))

        assert kill_calls == [999]

    def test_profile_dir_is_removed_after_success(
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
        kill_calls: list[int] = []
        monkeypatch.setattr(screenshot_module, "_kill_process_tree", kill_calls.append)
        seen_dirs: list[Path] = []
        real_remove = screenshot_module._remove_profile_dir

        def spy_remove(profile_dir: Path) -> None:
            seen_dirs.append(profile_dir)
            real_remove(profile_dir)

        monkeypatch.setattr(screenshot_module, "_remove_profile_dir", spy_remove)

        kwargs = self._base_kwargs(tmp_path, transport, kill_calls)
        asyncio.run(_run_capture([_make_row(1)], "Main Incomer", **kwargs))

        assert len(seen_dirs) == 1
        assert not seen_dirs[0].exists()

    def test_profile_dir_and_token_are_still_cleaned_up_on_failure(
        self, migrated_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A timeout mid-capture must still run every cleanup step."""
        import asyncio

        from arichds.config import get_settings

        get_settings().ensure_directories()
        transport = FakeTransport(responses={"Runtime.evaluate": [_evaluate_result(["nope"])]})
        kill_calls: list[int] = []
        monkeypatch.setattr(screenshot_module, "_kill_process_tree", kill_calls.append)
        deleted_hashes: list[str] = []
        monkeypatch.setattr(screenshot_module, "_delete_capture_token", deleted_hashes.append)
        seen_dirs: list[Path] = []
        real_remove = screenshot_module._remove_profile_dir

        def spy_remove(profile_dir: Path) -> None:
            seen_dirs.append(profile_dir)
            real_remove(profile_dir)

        monkeypatch.setattr(screenshot_module, "_remove_profile_dir", spy_remove)

        kwargs = self._base_kwargs(tmp_path, transport, kill_calls)
        kwargs["budget_seconds"] = 0.4

        with pytest.raises(BrowserCaptureError):
            asyncio.run(_run_capture([_make_row(1)], "Main Incomer", **kwargs))

        assert kill_calls == [999]
        assert len(seen_dirs) == 1
        assert not seen_dirs[0].exists()
        assert deleted_hashes == ["token-hash"]

    def test_no_rows_raises_before_anything_is_launched(self, migrated_db: Any, tmp_path: Path) -> None:
        import asyncio

        with pytest.raises(BrowserCaptureError):
            asyncio.run(_run_capture([], "Main Incomer"))

    def test_missing_edge_raises_before_anything_else_happens(self, migrated_db: Any, tmp_path: Path) -> None:
        import asyncio

        with pytest.raises(BrowserCaptureError, match="Edge"):
            asyncio.run(_run_capture([_make_row(1)], "Main Incomer", resolve_edge=lambda: None))

    def test_the_token_is_still_deleted_when_the_profile_directory_cannot_be_created(
        self, migrated_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Self-check finding: minting the token and creating the profile
        directory both used to sit *before* the `try/finally`, so a failure
        between them (a real possibility — disk full, a permissions error)
        left the token minted with nothing to delete it. Both now live
        inside the same `try` as everything else `cleanup` owns."""
        import asyncio

        from arichds.config import get_settings

        settings = get_settings()
        settings.ensure_directories()
        # A regular file where `tmp_dir` should be a directory — `mkdir`
        # under it then fails with a real filesystem error, not a mock.
        (settings.data_dir.resolve() / "tmp").rmdir()
        (settings.data_dir.resolve() / "tmp").write_bytes(b"not a directory")

        deleted_hashes: list[str] = []
        monkeypatch.setattr(screenshot_module, "_delete_capture_token", deleted_hashes.append)

        def fake_mint_token(session: Any) -> MintedToken:
            return MintedToken("raw-token", "token-hash", 1, "admin", "admin")

        with pytest.raises((NotADirectoryError, FileExistsError, OSError)):
            asyncio.run(
                _run_capture(
                    [_make_row(1)],
                    "Main Incomer",
                    resolve_edge=lambda: tmp_path / "msedge.exe",
                    mint_token=fake_mint_token,
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
    """Code review round, problem 2 — a cancellation delivered *while*
    `_Cleanup.run()` is awaiting `connection.close()` must not skip the
    kill/remove/delete steps that follow it. Proven directly against
    `_Cleanup`, independent of `asyncio.wait_for`'s own cancel-once
    behaviour (the fake `close()` used elsewhere in this file never
    actually suspends, so it cannot exercise this path at all) — the task
    is cancelled by the test itself while it is genuinely suspended inside
    `close()`, which is exactly the scenario `asyncio.shield` in
    `_Cleanup.run()` exists for."""

    def test_a_cancellation_mid_close_still_runs_kill_and_delete(self) -> None:
        import asyncio

        close_started = asyncio.Event()

        class SlowConnection:
            async def close(self) -> None:
                close_started.set()
                await asyncio.sleep(999)  # cancelled mid-await by the test itself, below

        kill_calls: list[int] = []
        deleted_hashes: list[str] = []

        cleanup = screenshot_module._Cleanup()
        cleanup.connection = SlowConnection()
        cleanup.pid = 42
        cleanup.profile_dir = None  # keep this test focused on close/kill/delete ordering
        cleanup.token_hash = "token-hash"
        cleanup._kill_process_tree = kill_calls.append
        cleanup._delete_token = deleted_hashes.append

        async def scenario() -> None:
            task = asyncio.ensure_future(cleanup.run())
            await close_started.wait()  # wait until `run()` is genuinely suspended inside close()
            task.cancel()
            await task  # must complete normally — run() swallows the cancellation itself

        asyncio.run(scenario())

        assert kill_calls == [42]
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

        kill_calls: list[int] = []
        monkeypatch.setattr(screenshot_module, "_kill_process_tree", kill_calls.append)
        deleted_hashes: list[str] = []
        monkeypatch.setattr(screenshot_module, "_delete_capture_token", deleted_hashes.append)
        seen_dirs: list[Path] = []
        real_remove = screenshot_module._remove_profile_dir

        def spy_remove(profile_dir: Path) -> None:
            seen_dirs.append(profile_dir)
            real_remove(profile_dir)

        monkeypatch.setattr(screenshot_module, "_remove_profile_dir", spy_remove)

        async def fake_connect(port: int, deadline: float) -> tuple[Any, HangingTransport]:
            return SimpleNamespace(close=_record_close), transport

        def fake_wait_for_port(profile_dir: Path, deadline: float) -> int:
            return 12345

        def fake_mint_token(session: Any) -> MintedToken:
            return MintedToken("raw-token", "token-hash", 1, "admin", "admin")

        def fake_launch(edge_path: Path, profile_dir: Path) -> FakeProcess:
            return FakeProcess(pid=555)

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
                    launch_edge=fake_launch,
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
        assert kill_calls == [555]
        assert len(seen_dirs) == 1
        assert not seen_dirs[0].exists()
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
        kill_calls: list[int] = []
        monkeypatch.setattr(screenshot_module, "_kill_process_tree", kill_calls.append)

        async def fake_connect(port: int, deadline: float) -> tuple[Any, FakeTransport]:
            return SimpleNamespace(close=_record_close), transport

        def fake_wait_for_port(profile_dir: Path, deadline: float) -> int:
            return 12345

        def fake_mint_token(session: Any) -> MintedToken:
            return MintedToken("raw-token", "token-hash", 1, "admin", "admin")

        def fake_launch(edge_path: Path, profile_dir: Path) -> FakeProcess:
            return FakeProcess(pid=321)

        png_bytes = asyncio.run(
            _run_capture_with_hard_deadline(
                [_make_row(1)],
                "Main Incomer",
                resolve_edge=lambda: tmp_path / "msedge.exe",
                mint_token=fake_mint_token,
                launch_edge=fake_launch,
                connect=fake_connect,
                wait_for_port=fake_wait_for_port,
            )
        )

        assert png_bytes  # the real capture succeeded, not swallowed by the wrapper
        assert kill_calls == [321]


class TestTmpDir:
    def test_ensure_directories_creates_tmp_dir(self, settings: Any) -> None:
        """`Settings.tmp_dir` (issue #38, step 4) — the per-capture Edge
        profile directories live under here, inside `%ProgramData%\\ARICHDS`
        and therefore covered by the installer's `[Dirs] Permissions:`
        grant by construction, unlike `%TEMP%`."""
        settings.ensure_directories()

        assert settings.tmp_dir == settings.data_dir.resolve() / "tmp"
        assert settings.tmp_dir.is_dir()


async def _record_close() -> None:
    return None


#: The smallest possible valid PNG (1x1, transparent) — signature + IHDR +
#: IDAT + IEND, base64-encoded. Used only as canned CDP screenshot data.
_TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
