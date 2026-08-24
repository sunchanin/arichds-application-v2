"""Headless-screenshot renderer for the Billing capture PNG (ADR 0017,
issue #38).

Retires :mod:`arichds.capture.png`'s Pillow drawing (ADR 0014, reversed) in
favour of driving the **already-installed** Microsoft Edge over the Chrome
DevTools Protocol against our own Billing page — nobody signed in on screen,
no window on screen, no bundled browser (``pyproject.toml``'s "pure Python,
no native ext" is untouched: this launches the operating system's own copy,
it bundles none).

One capture, start to finish:

1. Resolve Edge's install path from the registry (:func:`resolve_edge_path`).
2. Mint a five-minute Access Token for the lowest-``id`` admin
   (:func:`_mint_capture_token`) — the same code path login uses.
3. Launch Edge headless with a fresh, uniquely-named profile directory under
   ``<data_dir>/tmp`` (:func:`_launch_edge`) — never ``%TEMP%``, which
   resolves somewhere unwritable under the service account this ADR installs
   (ADR 0017), and never a fixed name, which two concurrent captures would
   collide on.
4. Read the DevTools port Chromium wrote to ``DevToolsActivePort``
   (:func:`_wait_for_devtools_port`) and connect over CDP.
5. Seed the session and the capture request into ``localStorage`` /
   ``window.__ARICHDS_CAPTURE__`` *before* navigating
   (:mod:`arichds.capture.dom`), then navigate and poll until the rendered
   row ids exactly match ``_png_source_rows()``'s own selection
   (:func:`~arichds.capture.dom.ids_match`) — the readiness signal and the
   correctness gate in one comparison (decision 6).
6. Screenshot at 1920 CSS px wide, height grown to fit every row.
7. **Always**, in this order: close the CDP connection, kill the Edge
   process tree **by PID** (never by image name — a name-resolved kill has
   already caused a real incident on the machine this runs on), remove the
   profile directory, delete the ``UserToken`` row. A failure in any one
   step must not prevent the others.

**Every failure raises :class:`BrowserCaptureError`** — callers
(:func:`arichds.capture.service.write_png_capture`,
:func:`arichds.api.billing.download_billing_image`) catch one thing.

The 90-second budget is an **enforced ceiling**
(:func:`_run_capture_with_hard_deadline`), not just a value the loops
between CDP calls happen to check — a single CDP call that never returns
(a renderer wedged in JS) cannot block the Scheduler thread past the
budget plus a small margin.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import subprocess
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple, Protocol

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from arichds.auth.roles import Role
from arichds.auth.security import create_access_token, hash_token
from arichds.capture.dom import build_seed_script, ids_match, poll_script
from arichds.config import get_settings
from arichds.db.models import User, UserToken
from arichds.db.session import session_scope

logger = logging.getLogger(__name__)


class BrowserCaptureError(Exception):
    """Anything that stops the headless-screenshot renderer.

    The single type every caller catches — a missing Edge install, no admin
    to mint a token for, a launch/connect failure, a capture budget
    exceeded, or the rendered rows never matching :func:`_png_source_rows`'s
    selection all raise this and nothing else.
    """


#: Hard overall budget (issue #38, step 4) — the eager path runs on the
#: single-threaded job-registry Scheduler (ADR 0008), so a stuck capture
#: delays every other scheduled job by exactly this long. Nine meters on a
#: day when every one of them is broken is ~13 minutes; the normal path is
#: around ten seconds each.
CAPTURE_BUDGET_SECONDS = 90.0

#: Safety margin on top of :data:`CAPTURE_BUDGET_SECONDS` for the hard,
#: enforced ceiling `_run_capture_with_hard_deadline` wraps around the
#: whole capture (code review round, problem 2) — the inner deadline is
#: only checked *between* CDP calls, so a single wedged call needs this
#: outer, unconditional backstop.
_HARD_TIMEOUT_MARGIN_SECONDS = 15.0

#: The token lifetime (decision 9) — short because a hard-killed process
#: should leave a credential that dies fast, not the login page's 8 hours.
_TOKEN_LIFETIME = timedelta(minutes=5)

_VIEWPORT_WIDTH = 1920
_VIEWPORT_HEIGHT = 1080

#: How often :func:`_wait_for_rows` re-polls the page.
_POLL_INTERVAL_SECONDS = 0.25

#: A CDP frame carrying a multi-megabyte base64 PNG comfortably exceeds
#: `websockets`' 1 MiB default (Findings) — 32 MiB covers the largest
#: plausible ten-row, sixty-column table with headroom.
_MAX_FRAME_SIZE = 32 * 1024 * 1024

# ── Edge resolution (step 4) ───────────────────────────────────────────────

_EDGE_APP_PATHS_KEY = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
_EDGE_DEFAULT_VALUE_RE = re.compile(r"\(Default\)\s+REG_SZ\s+(.+)")

#: The two well-known locations Edge installs to (Findings: this machine's
#: copy is under the x86 root; never assume which). Checked in order only
#: when the registry read fails or points at a file that no longer exists.
_EDGE_FALLBACK_PATHS: tuple[Path, ...] = (
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)


def _read_edge_path_from_registry() -> Path | None:
    """``reg query`` the App Paths key for Edge's ``(Default)`` value.

    Same shape as ``licensing/fingerprint.py:126-140``'s ``reg query`` for
    ``MachineGuid`` — a subprocess call, a regex over its stdout, any
    failure becomes ``None`` rather than raising (the caller falls back).
    """
    try:
        output = subprocess.check_output(  # noqa: S603
            ["reg", "query", _EDGE_APP_PATHS_KEY],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    match = _EDGE_DEFAULT_VALUE_RE.search(output)
    if match is None:
        return None
    return Path(match.group(1).strip())


def resolve_edge_path() -> Path | None:
    """Resolve the installed Microsoft Edge binary.

    Registry first (Edge's install root differs across machines — never a
    hardcoded path), falling back to the two well-known Program Files
    locations. A registry value pointing at a file that no longer exists
    (a stale key left by an old uninstall) is not trusted over an existing
    fallback.

    Returns:
        The resolved path, or ``None`` if Edge could not be found anywhere.
    """
    from_registry = _read_edge_path_from_registry()
    if from_registry is not None and from_registry.is_file():
        return from_registry

    for candidate in _EDGE_FALLBACK_PATHS:
        if candidate.is_file():
            return candidate

    return None


# ── Token lifecycle (decision 9) ────────────────────────────────────────────


class MintedToken(NamedTuple):
    """What :func:`_mint_capture_token` hands back — everything
    :func:`_drive_capture` needs to seed a session, plus the hash
    :func:`_delete_capture_token` looks the row up by."""

    raw_token: str
    token_hash: str
    user_id: int
    username: str
    role: str


def _mint_capture_token(session: Session) -> MintedToken:
    """Issue a five-minute Access Token for the lowest-``id`` admin.

    Same calls the login path uses (``auth/service.py:156-159``) —
    :func:`~arichds.auth.security.create_access_token`,
    :func:`~arichds.auth.security.hash_token`, then a ``UserToken`` row.
    Deterministic: a machine that can run a capture has activated a license,
    so it has an admin (decision 9) — but if it somehow does not, this
    raises rather than capturing as nobody.

    Args:
        session: Open session; the ``UserToken`` insert is committed here so
            the row is visible to the request the renderer is about to make
            (a fresh connection per SQLite/WAL, per the rest of this
            codebase's session-per-unit-of-work pattern).

    Raises:
        BrowserCaptureError: No admin account exists.
    """
    admin = session.scalar(select(User).where(User.role == Role.ADMIN).order_by(User.id).limit(1))
    if admin is None:
        raise BrowserCaptureError("No admin account exists to mint a capture token for.")

    expires_at = datetime.now(UTC) + _TOKEN_LIFETIME
    raw_token = create_access_token(user_id=admin.id, role=admin.role.value, expires_at=expires_at)
    token_hash = hash_token(raw_token)
    session.add(UserToken(user_id=admin.id, token_hash=token_hash, expires_at=expires_at))
    session.commit()
    return MintedToken(raw_token, token_hash, admin.id, admin.username, admin.role.value)


def _delete_capture_token(token_hash: str) -> None:
    """Delete the ``UserToken`` row minted for one capture — never revoked
    (decision 9): this token is never issued to a person, so a revoked row
    per meter per month is landfill with no audit value.

    Swallows its own failure (logged) — cleanup must not mask whatever the
    capture itself raised, and a lingering row simply expires in five
    minutes on its own.
    """
    try:
        with session_scope() as session:
            session.execute(delete(UserToken).where(UserToken.token_hash == token_hash))
    except Exception:  # noqa: BLE001 — cleanup; must never mask the real error.
        logger.exception("Could not delete the capture token (hash prefix %s…)", token_hash[:8])


# ── Process lifecycle (step 4) ──────────────────────────────────────────────


def _launch_edge(edge_path: Path, profile_dir: Path) -> subprocess.Popen[bytes]:
    """Start headless Edge with a fresh profile directory and
    ``--remote-debugging-port=0`` (an OS-assigned free port — a fixed port
    collides between concurrent captures and needlessly opens a known
    listener).

    Two flag decisions worth recording explicitly rather than leaving to
    guesswork the next time someone diffs this list against a prototype
    (code review round, nit 6):

    * ``--hide-scrollbars`` — added. The Billing table renders under
      ``scroll={{ x: tableWidth }}``, so an unhidden scrollbar could land
      in the image. That is chrome the browser adds, not part of the page
      ADR 0017 decision 3 approved truncating — hiding it is not the same
      decision as widening the viewport, which stays untouched.
    * ``--no-sandbox`` — **deliberately not added.** It weakens Chromium's
      process sandbox and there is no evidence it is needed: the sandbox
      is a low-privilege-process concern, and ``NT AUTHORITY\\LocalService``
      is already a low-privilege account, unlike the root/administrative
      contexts that usually force this flag. Nothing in this codebase can
      test under the real service account (Out of Scope — this machine's
      install is not ours to touch), so the honest answer is "unverified,
      not assumed necessary." If the owner's install review shows Edge
      failing to launch specifically under the service account (distinct
      from a missing-Edge or wrong-account failure — see
      ``installer/README.md``), that is the evidence to revisit this.
    """
    args = [
        str(edge_path),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile_dir}",
        "--remote-debugging-port=0",
        "about:blank",
    ]
    return subprocess.Popen(args)  # noqa: S603


def _kill_process_tree(pid: int) -> None:
    """Kill *pid* and every child it spawned — **by PID, never by image
    name**. ``--headless=new`` spawns renderer children that
    ``Popen.kill()`` alone leaves behind; ``taskkill /IM msedge.exe`` would
    kill the operator's own browser on a real machine (a name-resolved kill
    has already caused a real incident here).

    Swallows its own failure (logged) — a process already gone (e.g. it
    crashed on its own) is not a capture failure.
    """
    try:
        subprocess.run(  # noqa: S603
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    except OSError:
        logger.exception("Could not kill the Edge process tree (pid %s)", pid)


def _wait_for_devtools_port(profile_dir: Path, deadline: float) -> int:
    """Poll ``<profile_dir>/DevToolsActivePort`` until Chromium writes it —
    the port is on line 1 (Findings).

    Raises:
        BrowserCaptureError: The file never appeared before *deadline*
            (``time.monotonic()`` seconds).
    """
    port_file = profile_dir / "DevToolsActivePort"
    while time.monotonic() < deadline:
        if port_file.is_file():
            text = port_file.read_text(encoding="utf-8")
            first_line = text.splitlines()[0].strip() if text else ""
            if first_line.isdigit():
                return int(first_line)
        time.sleep(0.05)
    raise BrowserCaptureError(f"Edge never wrote {port_file} within the capture budget.")


# ── CDP transport ────────────────────────────────────────────────────────────


class CdpTransport(Protocol):
    """What :func:`_drive_capture` needs from a CDP connection — narrow on
    purpose so tests can supply a fake with no real websocket at all."""

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...


class _WebSocketCdpTransport:
    """The real transport — one JSON-RPC-shaped request per call, ignoring
    any event notification that arrives before the matching response."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._next_id = 1

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        message_id = self._next_id
        self._next_id += 1
        await self._connection.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            raw = await self._connection.recv()
            data = json.loads(raw)
            if data.get("id") == message_id:
                if "error" in data:
                    raise BrowserCaptureError(f"CDP {method} failed: {data['error']}")
                return data.get("result", {})
            # Anything else is an event notification for a different id — keep waiting.


async def _fetch_first_page_ws_url(port: int, deadline: float) -> str:
    """``GET http://127.0.0.1:<port>/json/list`` and return the first page
    target's ``webSocketDebuggerUrl`` — headless Edge already opens one
    (``about:blank``) tab on launch.

    Uses the stdlib ``urllib`` rather than a new HTTP dependency, with
    proxying explicitly disabled (Findings: `websockets`'s own ``proxy``
    default is ``True`` for the same reason — a customer machine's
    ``HTTP_PROXY``/``ALL_PROXY`` env vars must never route a loopback call).
    """
    import urllib.error
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://127.0.0.1:{port}/json/list"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=2) as response:
                targets = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            await asyncio.sleep(0.1)
            continue
        for target in targets:
            ws_url = target.get("webSocketDebuggerUrl")
            if target.get("type") == "page" and ws_url:
                return str(ws_url)
        await asyncio.sleep(0.1)
    raise BrowserCaptureError(f"Edge never exposed a page target on port {port}: {last_error}")


async def _connect_transport(port: int, deadline: float) -> tuple[Any, CdpTransport]:
    """Fetch the first page target and connect a real CDP transport to it.

    Returns:
        ``(connection, transport)`` — the caller owns closing *connection*.
    """
    from websockets.asyncio.client import connect

    ws_url = await _fetch_first_page_ws_url(port, deadline)
    connection = await connect(ws_url, proxy=None, max_size=_MAX_FRAME_SIZE)
    return connection, _WebSocketCdpTransport(connection)


# ── Driving the capture over an already-connected transport (step 5) ───────


def _content_height(metrics: dict[str, Any]) -> float:
    """Read ``cssContentSize.height`` off a ``Page.getLayoutMetrics``
    result, falling back to ``contentSize`` if the CDP build omits the CSS
    variant."""
    css_content = metrics.get("cssContentSize") or metrics.get("contentSize") or {}
    height = css_content.get("height")
    return float(height) if height is not None else float(_VIEWPORT_HEIGHT)


async def _wait_for_rows(transport: CdpTransport, expected_ids: list[str], deadline: float) -> None:
    """Poll :func:`~arichds.capture.dom.poll_script` until the rendered row
    ids exactly match *expected_ids* (decision 6) — the readiness signal and
    the correctness gate in one comparison.

    Raises:
        BrowserCaptureError: Naming both lists, if the match never happens
            before *deadline*.
    """
    script = poll_script()
    observed: list[str] = []
    mounted = False
    while time.monotonic() < deadline:
        result = await transport.request("Runtime.evaluate", {"expression": script, "returnByValue": True})
        value = result.get("result", {}).get("value") or {}
        observed = list(value.get("ids") or [])
        mounted = bool(value.get("mounted"))
        if ids_match(expected_ids, observed):
            return
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    raise BrowserCaptureError(
        f"Billing page never rendered the expected rows within the capture budget "
        f"(shell mounted: {mounted}; expected {expected_ids!r}, last observed {observed!r})."
    )


async def _drive_capture(
    transport: CdpTransport,
    rows: Sequence[Any],
    minted: MintedToken,
    app_port: int,
    deadline: float,
) -> bytes:
    """Seed, navigate, wait for the exact rows, then screenshot — the whole
    on-page part of a capture, over an already-connected *transport*.

    Kept independent of how *transport* was obtained so it is unit-testable
    with a fake — no real websocket, no real Edge.
    """
    anchor = rows[0]
    end_bound = _as_utc(anchor.bill_date) + timedelta(seconds=1)  # inclusive of the anchor (decision, step 6)
    capture_request = {
        "deviceId": anchor.device_id,
        "meterSerial": anchor.meter_serial,
        "endIso": end_bound.isoformat(),
        # Exactly `len(rows)` (code review round, problem 1) — NOT a padded
        # constant. `_png_source_rows()` already truncated to at most ten;
        # the page's own query (same device_id/meter_serial, the same
        # `bill_date DESC` order, `endIso` matching this function's own
        # inclusive bound) selects the identical row set, so the first page
        # of exactly `len(rows)` rows *is* the selection. A padded value
        # (e.g. "50, comfortably larger than ten") asks the page for every
        # closed period up to the anchor — for an eleventh-plus closed
        # period, more rows than `expected_ids` holds, so `ids_match` can
        # never be true and every capture times out after the full budget.
        # This is a visible change from the prototype the owner approved:
        # `total > pageSize` now shows AntD's pager and `showTotal`'s full
        # count instead of a single unpaginated page — left visible on
        # purpose rather than hidden without the owner seeing it.
        "pageSize": len(rows),
    }
    session_payload = {
        "id": minted.user_id,
        "token": minted.raw_token,
        "username": minted.username,
        "role": minted.role,
    }
    seed_script = build_seed_script(session_payload, capture_request)

    # `Page.enable` first — confirmed empirically (integration test, step 10):
    # without it, `Page.addScriptToEvaluateOnNewDocument` is silently not
    # honoured on the next navigation and the seed never reaches the page at
    # all (the SPA boots straight to Login with an empty `localStorage`).
    await transport.request("Page.enable")
    await transport.request("Page.addScriptToEvaluateOnNewDocument", {"source": seed_script})
    await transport.request(
        "Emulation.setDeviceMetricsOverride",
        {"width": _VIEWPORT_WIDTH, "height": _VIEWPORT_HEIGHT, "deviceScaleFactor": 1, "mobile": False},
    )
    await transport.request("Page.navigate", {"url": f"http://127.0.0.1:{app_port}/"})

    expected_ids = [str(row.id) for row in rows]
    await _wait_for_rows(transport, expected_ids, deadline)

    metrics = await transport.request("Page.getLayoutMetrics")
    height = max(_VIEWPORT_HEIGHT, _content_height(metrics))

    result = await transport.request(
        "Page.captureScreenshot",
        {
            "format": "png",
            "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": _VIEWPORT_WIDTH, "height": height, "scale": 1},
        },
    )
    data = result.get("data")
    if not data:
        raise BrowserCaptureError("Page.captureScreenshot returned no data.")
    return base64.b64decode(data)


def _as_utc(moment: datetime) -> datetime:
    """Re-attach UTC to a naive datetime — SQLite hands one back for a
    ``DateTime(timezone=True)`` column, same trap every ``_ensure_utc``
    field validator in this codebase works around."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


# ── Orchestration ────────────────────────────────────────────────────────────


class _Cleanup:
    """Accumulates the teardown steps a capture attempt has actually
    started, run in the fixed order the ADR requires — a failure in one
    step must not prevent the others (step 4)."""

    def __init__(self) -> None:
        self.connection: Any | None = None
        self.pid: int | None = None
        self.profile_dir: Path | None = None
        self.token_hash: str | None = None
        self._kill_process_tree: Callable[[int], None] = _kill_process_tree
        self._delete_token: Callable[[str], None] = _delete_capture_token

    async def run(self) -> None:
        """Run every step that was actually started, in order — **and
        finish all four even when this coroutine itself is running because
        the capture was cancelled** (code review round, problem 2).

        ``_run_capture``'s own ``finally: await cleanup.run()`` is exactly
        the case: when the hard timeout in :func:`_run_capture_with_hard_deadline`
        fires, ``asyncio.wait_for`` cancels the in-flight capture, and this
        method is what runs while that cancellation is unwinding. ``await
        self.connection.close()`` is the one truly async step here, so it
        is the one place a *second* cancellation delivered mid-cleanup
        could cut things short — ``asyncio.shield`` stops the shielded
        awaitable itself from being cancelled, and the explicit
        ``CancelledError`` catch (a ``BaseException``, not caught by
        ``except Exception``) means a cancellation raised at this specific
        await point is swallowed rather than skipping the kill/remove/
        delete steps below.
        """
        if self.connection is not None:
            try:
                await asyncio.shield(self.connection.close())
            except asyncio.CancelledError:
                logger.warning("CDP connection close was interrupted by cancellation; continuing cleanup")
            except Exception:  # noqa: BLE001 — cleanup; every step below must still run.
                logger.exception("Could not close the CDP connection cleanly")
        if self.pid is not None:
            self._kill_process_tree(self.pid)
        if self.profile_dir is not None:
            _remove_profile_dir(self.profile_dir)
        if self.token_hash is not None:
            self._delete_token(self.token_hash)


def _remove_profile_dir(profile_dir: Path) -> None:
    import shutil

    try:
        shutil.rmtree(profile_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001 — cleanup; must never mask the real error.
        logger.exception("Could not remove the capture profile directory %s", profile_dir)


async def _run_capture(
    rows: Sequence[Any],
    device_name: str,  # noqa: ARG001 — accepted for signature symmetry with the retired renderer; not yet used in the header (the page draws its own).
    *,
    resolve_edge: Callable[[], Path | None] = resolve_edge_path,
    mint_token: Callable[[Session], MintedToken] = _mint_capture_token,
    launch_edge: Callable[[Path, Path], subprocess.Popen[bytes]] = _launch_edge,
    connect: Callable[[int, float], Awaitable[tuple[Any, CdpTransport]]] = _connect_transport,
    wait_for_port: Callable[[Path, float], int] = _wait_for_devtools_port,
    cleanup_cls: type[_Cleanup] = _Cleanup,
    budget_seconds: float = CAPTURE_BUDGET_SECONDS,
) -> bytes:
    """The full lifecycle: mint → launch → connect → drive → cleanup.

    Every dependency above defaults to the real implementation; tests
    override ``launch_edge``/``connect`` (and sometimes ``mint_token``) with
    fakes so no real Edge process or websocket is ever needed.
    """
    if not rows:
        raise BrowserCaptureError("render_billing_png was given no rows to capture.")

    deadline = time.monotonic() + budget_seconds
    cleanup = cleanup_cls()

    edge_path = resolve_edge()
    if edge_path is None:
        raise BrowserCaptureError("Microsoft Edge was not found on this machine.")

    settings = get_settings()

    # Everything from here on acquires a resource `cleanup` must release, so
    # it all lives inside one `try/finally` — a failure creating the profile
    # directory (say) right after a successful mint must still delete the
    # token, not just a failure later in the launch/connect/drive chain.
    try:
        with session_scope() as session:
            minted = mint_token(session)
        cleanup.token_hash = minted.token_hash

        profile_dir = (settings.tmp_dir / f"capture-{uuid.uuid4().hex}").resolve()
        profile_dir.mkdir(parents=True, exist_ok=False)
        cleanup.profile_dir = profile_dir

        process = launch_edge(edge_path, profile_dir)
        cleanup.pid = process.pid

        port = wait_for_port(profile_dir, deadline)
        connection, transport = await connect(port, deadline)
        cleanup.connection = connection

        return await _drive_capture(transport, rows, minted, settings.port, deadline)
    finally:
        await cleanup.run()


async def _run_capture_with_hard_deadline(
    rows: Sequence[Any],
    device_name: str,
    *,
    budget_seconds: float = CAPTURE_BUDGET_SECONDS,
    hard_margin: float = _HARD_TIMEOUT_MARGIN_SECONDS,
    **kwargs: Any,
) -> bytes:
    """Enforce :data:`CAPTURE_BUDGET_SECONDS` as a hard ceiling, not merely
    an advisory one consulted between CDP calls (code review round,
    problem 2).

    ``_wait_for_rows`` / ``_wait_for_devtools_port`` / ``_fetch_first_page_ws_url``
    all check their own deadline *between* calls, but
    ``_WebSocketCdpTransport.request`` has no deadline of its own — it
    loops on ``recv()`` until a matching response id arrives, discarding
    every other frame. A renderer wedged in JS keeps the browser process
    itself alive (it keeps answering CDP pings, so ``websockets``'s own
    ``ping_interval``/``ping_timeout`` never fire), so nothing below this
    wrapper ever notices on its own. ``hard_margin`` gives the inner,
    more specific errors (naming the expected/observed row ids, the
    missing ``DevToolsActivePort`` file, etc.) a head start to fire first
    in the common case — this wrapper is the backstop, not the primary
    signal.

    ``_run_capture``'s own ``finally: await cleanup.run()`` still runs
    when ``asyncio.wait_for`` cancels it here — see
    :meth:`_Cleanup.run`'s docstring for why that survives the
    cancellation itself.
    """
    try:
        return await asyncio.wait_for(
            _run_capture(rows, device_name, budget_seconds=budget_seconds, **kwargs),
            timeout=budget_seconds + hard_margin,
        )
    except TimeoutError as exc:
        raise BrowserCaptureError(
            f"Capture exceeded the hard {budget_seconds + hard_margin:.0f}s ceiling — "
            "a CDP call likely never returned (a wedged renderer)."
        ) from exc


def render_billing_png(rows: Sequence[Any], device_name: str) -> bytes:
    """Render the Billing History table (up to ten closed periods) as a PNG
    by driving our own Billing page in headless Edge (ADR 0017).

    Never touches the filesystem itself — the caller
    (:mod:`arichds.capture.write`) is responsible for the hardened write,
    exactly like the retired :func:`arichds.capture.png.render_billing_png`.

    Args:
        rows: Already ordered newest-``bill_date``-first and already limited
            to at most ten (:func:`~arichds.capture.service._png_source_rows`)
            — this function does not query, sort, or truncate. Anything
            exposing ``id``/``device_id``/``bill_date``/``meter_serial`` as
            attributes (a real ``BillingReading``, since the row ids are
            what the on-page verification compares against — a
            ``SimpleNamespace`` test double has no ``id`` and cannot pass
            that check against a real page).
        device_name: Accepted for parity with the retired Pillow renderer's
            signature; the page draws its own device name from the API, so
            this is unused here (the caller passes it as a positional
            regardless — see ``capture/service.py``).

    Returns:
        Complete PNG bytes.

    Raises:
        BrowserCaptureError: Edge could not be found, no admin exists to
            mint a token for, the browser failed to launch or connect, or
            the rendered rows never matched *rows* within the capture
            budget.
    """
    return asyncio.run(_run_capture_with_hard_deadline(rows, device_name))
