"""A minimal, in-process HTTP receiver implementing Central Push contract
version 1 (ADR 0024) — for tests only.

Same role `fakes.py` plays for a meter: the real thing, never a mock of
`arichds.centralpush.cycle`'s internals. It binds ``127.0.0.1`` on an
**ephemeral port** (port 0), so parallel `pytest -n auto` workers never
collide on a fixed one, verifies the Push Token against a caller-supplied
public key exactly as a real server would, answers holdings from what it has
actually stored, and upserts every pushed item on the contract's own natural
key (``arichds.centralpush.contract.NATURAL_KEYS``). Tests assert only on
what this receiver holds — never on `cycle.py`'s internals — the same
discipline `test_dataout_mysql.py` uses against a real MariaDB.

**Ticket 03 (ADR 0025)** grew the same in-process server with the File
Upload Destination's three HTTPS endpoints — ``GET``/``PUT
.../v1/files/manifest`` and ``PUT .../v1/files/{relative path}`` — reusing
this receiver rather than a second in-process server, exactly as
`test_fileupload_https_transport.py` (the transport tests) and
`arichds.fileupload.https_transport` (the transport itself) expect. These
three endpoints check a plain Bearer string (``.files_token``), never
`verify_push_token` — the HTTPS tab's own token "may be the Push Token or a
different one" (spec.md story 8).
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from arichds.licensing.push_token import verify_push_token


class FakeCentralPushReceiver:
    """One in-process fake server.

    Construct it, read ``.url``, drive a cycle against it, then call
    ``.shutdown()`` — always from a fixture finalizer, never left running
    past its test.
    """

    def __init__(self, *, public_key_pem: bytes, files_token: str = "test-files-token") -> None:
        self.public_key_pem = public_key_pem

        #: Current contents, keyed by each kind's own natural key — a plain
        #: `dict` upsert is exactly what "the server upserts" (ADR 0024)
        #: means for a fake standing in for a real one.
        self.meters: dict[str, dict[str, Any]] = {}
        self.billing: dict[tuple[str, str], dict[str, Any]] = {}
        self.energy_summary: dict[tuple[str, str], dict[str, Any]] = {}
        self.load_profile: dict[tuple[str, int, str], dict[str, Any]] = {}

        #: Every HTTP request received, of any kind — what the "opt-out"
        #: test asserts is zero.
        self.request_count = 0
        #: Every accepted envelope, in arrival order — what a "no retry"
        #: test counts pushes by.
        self.pushes: list[dict[str, Any]] = []
        #: How many requests failed the Authorization check.
        self.unauthorized_requests = 0
        #: When set to a kind name, the NEXT push for that kind returns 500
        #: without storing anything, and this resets to None — the "no
        #: retry within a cycle" probe.
        self.fail_next_push_for_kind: str | None = None
        #: When set (seconds), every request sleeps this long before
        #: responding at all — the "receiver that stalls" probe.
        self.stall_seconds: float | None = None

        # ── the three File Upload Destination endpoints (ADR 0025, ticket 03) ──
        #: The Bearer token the file endpoints accept — a plain string
        #: comparison, never `verify_push_token`: spec.md story 8 says this
        #: tab's token "may be the Push Token or a different one", so a
        #: receiving server for files has no reason to know about Push
        #: Tokens at all.
        self.files_token = files_token
        #: `relative path` (e.g. `"export/SN0001.csv"`) -> the body last
        #: `PUT` there.
        self.files: dict[str, bytes] = {}
        #: `relative path` -> the `X-ARICHDS-File-Sha256` header that PUT
        #: carried — what a "the header names the right digest" test reads.
        self.files_sha256_headers: dict[str, str] = {}
        #: The manifest's raw bytes as last `PUT`, or `None` before the
        #: first write — `GET .../v1/files/manifest` answers 404 while this
        #: is `None`, exactly like a fresh remote root.
        self.files_manifest: bytes | None = None
        #: When `True`, the NEXT file-endpoint request (any of the three)
        #: returns 500 without storing anything, and this resets to
        #: `False` — the "a non-2xx response raises TransportError" probe.
        self.fail_next_file_request: bool = False

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._build_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, name="fake-central-push", daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        _, port = self._server.server_address
        return f"http://127.0.0.1:{port}"

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    # ── holdings — "the newest X the server holds" (ADR 0024) ─────────────

    def _holdings(self) -> dict[str, Any]:
        lp_newest: dict[tuple[str, int], datetime] = {}
        for meter_serial, logger_id, read_at in self.load_profile:
            key = (meter_serial, logger_id)
            parsed = datetime.fromisoformat(read_at)
            if key not in lp_newest or parsed > lp_newest[key]:
                lp_newest[key] = parsed

        billing_newest: dict[str, datetime] = {}
        for (meter_serial, _bill_date), item in self.billing.items():
            parsed = datetime.fromisoformat(item["updated_at"])
            if meter_serial not in billing_newest or parsed > billing_newest[meter_serial]:
                billing_newest[meter_serial] = parsed

        energy_newest: dict[str, datetime] = {}
        for (meter_serial, _local_date), item in self.energy_summary.items():
            parsed = datetime.fromisoformat(item["updated_at"])
            if meter_serial not in energy_newest or parsed > energy_newest[meter_serial]:
                energy_newest[meter_serial] = parsed

        return {
            "contract_version": 1,
            "load_profile": [
                {"meter_serial": serial, "logger_id": logger_id, "newest_read_at": newest.isoformat()}
                for (serial, logger_id), newest in lp_newest.items()
            ],
            "billing": [
                {"meter_serial": serial, "newest_updated_at": newest.isoformat()}
                for serial, newest in billing_newest.items()
            ],
            "energy_summary": [
                {"meter_serial": serial, "newest_updated_at": newest.isoformat()}
                for serial, newest in energy_newest.items()
            ],
        }

    # ── push — upsert on the contract's own natural key ────────────────────

    def _store(self, envelope: dict[str, Any]) -> None:
        kind = envelope["kind"]
        items = envelope["items"]
        self.pushes.append(envelope)
        if kind == "meters":
            # A full snapshot every cycle (ADR 0024) — replace, never merge.
            self.meters = {item["meter_serial"]: item for item in items}
        elif kind == "billing":
            for item in items:
                self.billing[(item["meter_serial"], item["bill_date"])] = item
        elif kind == "energy_summary":
            for item in items:
                self.energy_summary[(item["meter_serial"], item["local_date"])] = item
        elif kind == "load_profile":
            for item in items:
                self.load_profile[(item["meter_serial"], item["logger_id"], item["read_at"])] = item

    # ── HTTP plumbing ────────────────────────────────────────────────────

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args: object) -> None:  # silence the test console
                return

            def _authorized(self) -> bool:
                auth = self.headers.get("Authorization", "")
                if not auth.startswith("Bearer "):
                    return False
                result = verify_push_token(auth[len("Bearer ") :], public_key_pem=receiver.public_key_pem)
                return result.valid

            def _authorized_files(self) -> bool:
                """The three file endpoints (ADR 0025, ticket 03) accept
                whatever Bearer token the operator configured on the HTTPS
                tab — a plain string compare, never `verify_push_token`:
                spec.md story 8 says this token "may be the Push Token or a
                different one", so a receiving server for files has no
                reason to know a Push Token's own wire format."""
                auth = self.headers.get("Authorization", "")
                return auth == f"Bearer {receiver.files_token}"

            def _reply(self, status: int, body: dict[str, Any] | None = None) -> None:
                if receiver.stall_seconds is not None:
                    time.sleep(receiver.stall_seconds)
                payload = json.dumps(body if body is not None else {}).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _reply_raw(self, status: int, payload: bytes, *, content_type: str = "application/json") -> None:
                if receiver.stall_seconds is not None:
                    time.sleep(receiver.stall_seconds)
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's own naming
                receiver.request_count += 1
                if self.path == "/v1/holdings":
                    if not self._authorized():
                        receiver.unauthorized_requests += 1
                        self._reply(401)
                        return
                    self._reply(200, receiver._holdings())
                    return
                if self.path == "/v1/files/manifest":
                    if not self._authorized_files():
                        receiver.unauthorized_requests += 1
                        self._reply(401)
                        return
                    if receiver.files_manifest is None:
                        self._reply(404)
                        return
                    self._reply_raw(200, receiver.files_manifest)
                    return
                self._reply(404)

            def do_POST(self) -> None:  # noqa: N802
                receiver.request_count += 1
                if self.path != "/v1/push":
                    self._reply(404)
                    return
                if not self._authorized():
                    receiver.unauthorized_requests += 1
                    self._reply(401)
                    return
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                envelope = json.loads(raw)

                if receiver.fail_next_push_for_kind == envelope.get("kind"):
                    receiver.fail_next_push_for_kind = None
                    self._reply(500)
                    return

                receiver._store(envelope)
                self._reply(200, {"accepted": True})

            def do_PUT(self) -> None:  # noqa: N802
                """The other two of the three file endpoints (ADR 0025,
                ticket 03): `PUT .../v1/files/manifest` and
                `PUT .../v1/files/{relative path}`."""
                receiver.request_count += 1
                if not self.path.startswith("/v1/files/"):
                    self._reply(404)
                    return
                if not self._authorized_files():
                    receiver.unauthorized_requests += 1
                    self._reply(401)
                    return
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""

                if receiver.fail_next_file_request:
                    receiver.fail_next_file_request = False
                    self._reply(500)
                    return

                relative_path = self.path[len("/v1/files/") :]
                if relative_path == "manifest":
                    receiver.files_manifest = body
                else:
                    receiver.files[relative_path] = body
                    receiver.files_sha256_headers[relative_path] = self.headers.get("X-ARICHDS-File-Sha256", "")
                self._reply(200, {"stored": True})

        return Handler


__all__ = ["FakeCentralPushReceiver"]
