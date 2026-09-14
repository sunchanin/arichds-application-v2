"""The Central Push HTTP client — stdlib ``urllib`` only (ADR 0024, hard
constraint: no ``httpx``/``requests`` in the product; ``httpx`` is dev-only).

Same transport choice v1's licence renewal client made
(``cewe-worker/src/license/renewal.py``): no new runtime dependency and
nothing extra for PyInstaller to collect. Every request carries
``Authorization: Bearer <Push Token>`` and **separate, explicit connect and
read timeouts** — something plain ``urllib.request.urlopen(..., timeout=)``
cannot express, since its one ``timeout`` covers the whole call. The split is
implemented the way the standard library documents for exactly this need: a
:class:`http.client.HTTPConnection` subclass that fixes ``self.timeout``
before :meth:`connect` (the connect timeout) and then calls the live
socket's own ``settimeout`` again immediately after (the read timeout), wired into
:mod:`urllib.request` through a custom opener — never a second HTTP library.

Every failure this module can raise collapses into one exception,
:class:`PushRequestError`, carrying only the failure's **class name** —
never the URL (which may embed credentials on some scheme) and never the
Push Token. :mod:`arichds.centralpush.cycle` is the only caller; it stores
``str(exc)`` on :class:`~arichds.centralpush.status.CycleStatus.error` and
ends the cycle right there — there is no retry within a cycle (ADR 0024).
"""

from __future__ import annotations

import http.client
import json
import logging
import time
from datetime import datetime
from typing import Any
from urllib.error import URLError
from urllib.request import HTTPHandler, HTTPSHandler, Request, build_opener

from arichds.centralpush.contract import CONTRACT_VERSION, ITEM_KINDS, HoldingsResponse, ItemKind, PushEnvelope
from arichds.constants import CENTRAL_PUSH_CONNECT_TIMEOUT_SEC, CENTRAL_PUSH_ITEM_CAP, CENTRAL_PUSH_READ_TIMEOUT_SEC

logger = logging.getLogger(__name__)

_HOLDINGS_PATH = "/v1/holdings"
_PUSH_PATH = "/v1/push"


class PushRequestError(Exception):
    """One HTTP call to the receiving server did not succeed — unreachable,
    timed out (connect or read), or a non-2xx response. ``str(self)`` is the
    failure's class name (or an ``"HTTP <status>"`` line for a non-2xx
    reply), and is the only detail ever kept — never the URL, never the
    token."""


class _SplitTimeoutHTTPConnection(http.client.HTTPConnection):
    """A plain HTTP connection with a connect timeout distinct from its read
    timeout. ``self.timeout`` (read by :meth:`connect` when it creates the
    socket) is set immediately before calling up, then the live socket's
    timeout is changed for every read that follows — the recipe the
    standard library itself documents for a connect/read split, since
    neither :mod:`http.client` nor :mod:`urllib.request` offers one directly.
    """

    def connect(self) -> None:
        self.timeout = CENTRAL_PUSH_CONNECT_TIMEOUT_SEC
        super().connect()
        if self.sock is not None:
            self.sock.settimeout(CENTRAL_PUSH_READ_TIMEOUT_SEC)


class _SplitTimeoutHTTPSConnection(http.client.HTTPSConnection):
    """The HTTPS counterpart of :class:`_SplitTimeoutHTTPConnection` — same
    split, applied after the TLS handshake `HTTPSConnection.connect` already
    performs."""

    def connect(self) -> None:
        self.timeout = CENTRAL_PUSH_CONNECT_TIMEOUT_SEC
        super().connect()
        if self.sock is not None:
            self.sock.settimeout(CENTRAL_PUSH_READ_TIMEOUT_SEC)


class _SplitTimeoutHTTPHandler(HTTPHandler):
    def http_open(self, req):  # noqa: ANN001, ANN201 — matches urllib.request's own untyped signature.
        return self.do_open(_SplitTimeoutHTTPConnection, req)


class _SplitTimeoutHTTPSHandler(HTTPSHandler):
    """Matches the installed :class:`urllib.request.HTTPSHandler.https_open`
    exactly (read via ``inspect.getsource`` against this build's stdlib,
    3.14): only ``context=self._context`` goes to :meth:`do_open` —
    ``check_hostname`` is not a ``do_open``/``HTTPSConnection`` keyword
    argument (removed in 3.12) and is instead applied to ``self._context``
    by ``HTTPSHandler.__init__`` before this method ever runs. Passing it
    here made every ``https://`` request raise ``TypeError`` before
    connecting — a blocker a review caught, since the real server is HTTPS
    (SPEC §3.8) and that ``TypeError`` is not an ``OSError``/``URLError``,
    so it escaped `_round_trip` uncaught."""

    def https_open(self, req):  # noqa: ANN001, ANN201 — matches urllib.request's own untyped signature.
        return self.do_open(_SplitTimeoutHTTPSConnection, req, context=self._context)


def _opener():
    """A fresh opener per call — stateless, thread-safe, and cheap enough at
    a fifteen-minute cadence that there is nothing to gain from caching one."""
    return build_opener(_SplitTimeoutHTTPHandler(), _SplitTimeoutHTTPSHandler())


def _round_trip(url: str, path: str, *, method: str, token: str, body: bytes | None) -> bytes:
    """One request/response round trip against ``{url}{path}``.

    Raises :class:`PushRequestError` on any transport failure, either
    timeout, or a non-2xx response (``urllib``'s own default error processor
    already raises :class:`~urllib.error.HTTPError` for anything outside
    ``200 <= status < 300`` — "any 2xx means accepted", Contract v1).
    """
    full_url = f"{url.rstrip('/')}{path}"
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(full_url, data=body, headers=headers, method=method)

    try:
        with _opener().open(request) as response:
            return response.read()
    except URLError as exc:
        # Covers both urllib.error.HTTPError (a non-2xx response — it IS a
        # URLError) and a transport-level failure (refused/unresolvable
        # host). An HTTPError's `.code` gives the operator a sharper reason
        # than the bare class name.
        code = getattr(exc, "code", None)
        raise PushRequestError(f"HTTP {code}" if code is not None else type(exc).__name__) from exc
    except (OSError, http.client.HTTPException) as exc:
        # A stalled connection surfaces here directly (TimeoutError, an
        # OSError subclass) — urllib only wraps the connect/request phase in
        # URLError, not `getresponse()`'s own read.
        raise PushRequestError(type(exc).__name__) from exc


def fetch_holdings(url: str, token: str) -> HoldingsResponse:
    """``GET {url}/v1/holdings`` — what the server already holds (ADR 0024,
    "No state on our side"). Raises :class:`PushRequestError` on any
    failure; the caller ends the whole cycle skipped."""
    payload = _round_trip(url, _HOLDINGS_PATH, method="GET", token=token, body=None)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PushRequestError(type(exc).__name__) from exc
    return HoldingsResponse.model_validate(data)


def push_kind(
    url: str,
    token: str,
    *,
    machine_id: str,
    kind: ItemKind,
    items: list[Any],
    sent_at: datetime,
    send_when_empty: bool = False,
    deadline: float | None = None,
) -> int:
    """``POST {url}/v1/push`` for one *kind*, chunked to at most
    :data:`~arichds.constants.CENTRAL_PUSH_ITEM_CAP` items per request.

    Every request body is built through :data:`~arichds.centralpush.contract.PushEnvelope`
    parametrised with *kind*'s own item model (looked up in
    :data:`~arichds.centralpush.contract.ITEM_KINDS`, never inferred from
    the first item) — the payload is always serialised through the contract
    models, never a second, hand-written shape.

    Args:
        items: Already-built item model instances of *kind*'s own type.
        send_when_empty: When True and *items* is empty, one request with
            ``items: []`` is still sent — the meter roster is a **full
            snapshot every cycle** (ADR 0024): the only way the server learns
            every device is gone is an empty roster arriving. The other
            three kinds are the opposite: nothing new means no request at
            all (`"the second [cycle] sends only the roster"`).
        deadline: A :func:`time.monotonic` timestamp (the cycle's own
            budget). Checked **before every chunk**, including the first —
            a review measured a probe (budget 0.6s, a 0.25s/request
            receiver, item cap 1, 8 rows) running 2.69s and sending all 8
            before this existed, because the budget was only ever checked
            once, before the whole kind. ``None`` (the roster's own call)
            means no budget check at all — the meter roster is sent
            regardless of the budget (ADR 0024: "the roster is always
            sent").

    Returns:
        How many items were actually sent (0 when *items* was empty and
        *send_when_empty* was False, or when *deadline* had already passed
        before the first chunk).

    Raises:
        PushRequestError: on the first failing request — the caller ends
            the whole cycle right there. Items already accepted by the
            server in an earlier chunk of this same call stay accepted;
            there is no rollback and no retry (ADR 0024).
    """
    if not items:
        if send_when_empty and (deadline is None or time.monotonic() < deadline):
            _post_chunk(url, token, machine_id=machine_id, kind=kind, items=[], sent_at=sent_at)
        return 0

    sent = 0
    for start in range(0, len(items), CENTRAL_PUSH_ITEM_CAP):
        if deadline is not None and time.monotonic() >= deadline:
            break
        chunk = items[start : start + CENTRAL_PUSH_ITEM_CAP]
        _post_chunk(url, token, machine_id=machine_id, kind=kind, items=chunk, sent_at=sent_at)
        sent += len(chunk)
    return sent


def _post_chunk(url: str, token: str, *, machine_id: str, kind: ItemKind, items: list[Any], sent_at: datetime) -> None:
    item_model = ITEM_KINDS[kind]
    envelope_cls = PushEnvelope[item_model]
    envelope = envelope_cls(
        contract_version=CONTRACT_VERSION, machine_id=machine_id, sent_at=sent_at, kind=kind, items=items
    )
    body = envelope.model_dump_json().encode("utf-8")
    _round_trip(url, _PUSH_PATH, method="POST", token=token, body=body)


__all__ = ["PushRequestError", "fetch_holdings", "push_kind"]
