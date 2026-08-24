"""Opt-in integration test — real Edge, real server (ADR 0017, issue #38,
step 10).

**Skipped by default.** Every other test in this repo drives
``capture.screenshot`` through a fake CDP transport or a fake process
handle; this is the one test whose evidence cannot come from a fixture — it
is the only automated proof the CDP driver actually works end to end
against a real Microsoft Edge and a real running ARICHDS server.

Run it explicitly:

    ARICHDS_TEST_EDGE=1 python -m pytest app/tests/test_capture_screenshot_integration.py -v

It starts uvicorn in-process on an ephemeral port against a seeded temp
database (the ``data_dir`` fixture's ``get_settings.cache_clear()`` pattern,
``conftest.py:120-131``, plus ``ARICHDS_PORT`` so the renderer's own
``get_settings().port`` navigates to the same server this test started),
walks the real Setup → Login → Activation flow over HTTP, seeds **thirteen**
closed Billing Readings directly through the session (code review round,
problem 1/3 — every other test in this file used to seed exactly one, which
is why the seeded-``pageSize`` bug reached this point without a single test
catching it: at one row, an over-wide ``pageSize`` and the correct one
request an identical page), selects the real ten-row window through the
real :func:`~arichds.capture.service._png_source_rows`, then calls the real
``render_billing_png`` — no fakes anywhere in this file.
"""

from __future__ import annotations

import os
import socket
import struct
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import uvicorn
from fakes import FakeMeterState

from arichds.config import get_settings

pytestmark = pytest.mark.skipif(
    not os.environ.get("ARICHDS_TEST_EDGE"),
    reason="set ARICHDS_TEST_EDGE=1 to run the real-Edge integration test",
)

ADMIN = {"username": "admin", "password": "admin-password"}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_reachable(client: httpx.Client, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            if client.get("/api/health").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise TimeoutError("The in-process test server never became reachable.")


def _png_dimensions(data: bytes) -> tuple[int, int]:
    """Width/height from the IHDR chunk — bytes 16-24, big-endian (no
    Pillow, per this issue's own verification rule)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


class TestRealHeadlessCapture:
    def test_render_billing_png_against_a_real_server_and_a_real_edge(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_meter: FakeMeterState,
        vendor_cli,
    ) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

        # ── Boot a real server on an ephemeral port, in this same process ──
        port = _free_port()
        data_dir = tmp_path / "data"
        monkeypatch.setenv("ARICHDS_DATA_DIR", str(data_dir))
        monkeypatch.setenv("ARICHDS_PORT", str(port))
        monkeypatch.setenv("ARICHDS_POLL_ENABLED", "false")
        get_settings.cache_clear()

        test_machine_id = "f" * 64
        monkeypatch.setattr("arichds.licensing.service.machine_id", lambda: test_machine_id)

        from arichds.licensing import activation_code as ac

        private_key = Ed25519PrivateKey.generate()
        private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
        monkeypatch.setattr(ac, "load_public_key_pem", lambda: public_pem)

        from arichds.main import create_app

        app = create_app()
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
                _wait_until_reachable(client, time.monotonic() + 20)

                setup_response = client.post("/api/auth/setup", json=ADMIN)
                assert setup_response.status_code == 201, setup_response.text

                login_response = client.post("/api/auth/login", json=ADMIN)
                assert login_response.status_code == 200, login_response.text
                token = login_response.json()["data"]["access_token"]
                client.headers["Authorization"] = f"Bearer {token}"

                payload = vendor_cli.build_payload(customer="Integration Test", machine_id=test_machine_id)
                code = vendor_cli.sign_payload(private_pem, payload)
                activate_response = client.post("/api/license/activate", json={"code": code})
                assert activate_response.status_code == 200, activate_response.text
                assert activate_response.json()["success"] is True

                fake_meter.meter_serial = "INTEGRATION-SN-1"
                meter_code_payload = vendor_cli.build_meter_payload(
                    meter_serial="INTEGRATION-SN-1", machine_id=test_machine_id
                )
                meter_code = vendor_cli.sign_payload(private_pem, meter_code_payload)
                device_response = client.post(
                    "/api/devices",
                    json={
                        "name": "Main Incomer",
                        "brand": "mitsu",
                        "model": "smw110",
                        "site_name": "Plant A",
                        "transport": {"kind": "net", "host": "127.0.0.1", "port": 4059},
                        "password": "hunter2",
                        "meter_activation_code": meter_code,
                    },
                )
                assert device_response.status_code == 201, device_response.text
                device_id = device_response.json()["data"]["id"]

            # ── Seed thirteen closed Billing Readings directly — same DB,
            # same process — one more than the twelve `test_t4` in
            # `test_billing_eager_capture.py` uses for the same reason:
            # thirteen closed periods is the smallest count that both
            # exceeds `_png_source_rows()`'s ten-row cap AND leaves the
            # anchor (the newest) with three periods excluded, so the
            # window's *boundary* is exercised, not just its existence. ──
            from arichds.db.models import BillingReading
            from arichds.db.session import session_scope

            anchor_bill_date = datetime(2026, 7, 31, 17, 0, 0, tzinfo=UTC)
            with session_scope() as session:
                for i in range(13):
                    bill_date = anchor_bill_date - timedelta(days=31 * i)
                    session.add(
                        BillingReading(
                            device_id=device_id,
                            bill_date=bill_date,
                            read_at=bill_date,
                            record_status=None,
                            source="dlms",
                            meter_serial="INTEGRATION-SN-1",
                            import_active_kwh_total=198685.030 - i * 1000,
                        )
                    )

            with session_scope() as session:
                # ── The real row selection AND the real renderer — no fakes
                # anywhere in this file. ──
                from sqlalchemy import select

                from arichds.capture.screenshot import render_billing_png
                from arichds.capture.service import _png_source_rows

                anchor = session.scalars(
                    select(BillingReading)
                    .where(BillingReading.device_id == device_id)
                    .order_by(BillingReading.bill_date.desc())
                    .limit(1)
                ).first()
                assert anchor is not None
                rows = _png_source_rows(session, anchor)
                assert len(rows) == 10, "the ten-row cap itself — proves this test seeded enough to exercise it"

                png_bytes = render_billing_png(rows, "Main Incomer")

            width, height = _png_dimensions(png_bytes)
            print(f"\nIntegration capture: {width}x{height} px, {len(png_bytes)} bytes, {len(rows)} rows")  # noqa: T201

            assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
            assert width == 1920
        finally:
            server.should_exit = True
            thread.join(timeout=10)
