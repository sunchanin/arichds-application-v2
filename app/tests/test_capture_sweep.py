"""**Save all** and the **Capture Sweep** (capture-sweep ticket 04, grill
2026-09-23).

Driven through the endpoint pair and the slice function against a recording
stand-in for the Scheduler's one-shot lane (the `RecordingScheduler` pattern
``test_api_devices.py`` uses, here draining on demand so a slice's re-queue is
observable) with the suite's autouse fake meter and the PNG renderer stubbed
(``test_api_billing_captures.py``'s own stub), so every format the licence
allows is written cheaply and observably. Every test asserts on what an
operator can see: which files exist, that an existing one kept its bytes,
the status shape, the response codes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_api_billing import BASE, add_device, seed_closed
from test_api_billing_captures import stub_render_billing_png

import arichds.capture.sweep as sweep_module
from arichds.capture.service import capture_target_paths
from arichds.capture.sweep import (
    SweepStatus,
    reset_sweep_status,
    run_sweep_slice,
    start_capture_sweep,
    sweep_status,
)
from arichds.db.app_settings import CAPTURE_DIR_KEY, set_setting
from arichds.db.models import BillingReading, Device
from arichds.db.session import session_scope

pytestmark = pytest.mark.usefixtures("fake_meter")


class RecordingScheduler:
    """The one-shot lane, recorded: `run_soon` queues, `drain()` runs what is
    queued — including what a slice queues while running — until nothing is."""

    def __init__(self) -> None:
        self.pending: list[tuple[str, Callable[[], None]]] = []
        self.names: list[str] = []

    def run_soon(self, name: str, fn: Callable[[], None]) -> None:
        self.pending.append((name, fn))
        self.names.append(name)

    def drain_one(self) -> None:
        _name, fn = self.pending.pop(0)
        fn()

    def drain(self) -> None:
        while self.pending:
            self.drain_one()


@pytest.fixture(autouse=True)
def _fresh_sweep(monkeypatch: pytest.MonkeyPatch):
    stub_render_billing_png(monkeypatch)
    reset_sweep_status()
    yield
    reset_sweep_status()


def set_capture_dir(path: Path | None) -> None:
    with session_scope() as session:
        set_setting(session, CAPTURE_DIR_KEY, str(path) if path is not None else "")


def seed_two_devices(admin_client: TestClient, fake_meter, periods: int = 2) -> dict[str, list[int]]:
    """Two devices, *periods* closed periods each, newest at ``BASE``."""
    ids: dict[str, list[int]] = {}
    for serial, name in (("SN-1", "Main Incomer"), ("SN-2", "Feeder")):
        device_id = add_device(admin_client, fake_meter, serial=serial, name=name)
        ids[serial] = [
            seed_closed(
                device_id, BASE - timedelta(days=30 * i), meter_serial=serial, import_active_kwh_total=100.0 + i
            )
            for i in range(periods)
        ]
    return ids


def pdf_for(capture_dir: Path, reading_id: int) -> Path:
    with session_scope() as session:
        row = session.get(BillingReading, reading_id)
        assert row is not None
        return capture_target_paths(capture_dir, row.meter_serial, row.bill_date, sequence=row.sequence)[0]


def captured_at(reading_id: int) -> datetime | None:
    with session_scope() as session:
        row = session.get(BillingReading, reading_id)
        assert row is not None
        return row.captured_at


def press_save_all(admin_client: TestClient) -> tuple[RecordingScheduler, object]:
    scheduler = RecordingScheduler()
    admin_client.app.state.scheduler = scheduler
    response = admin_client.post("/api/billing/save-all")
    return scheduler, response


class TestSaveAllWritesEverything:
    def test_every_missing_pdf_and_every_billing_file_is_written(
        self, admin_client: TestClient, fake_meter, tmp_path: Path
    ) -> None:
        ids = seed_two_devices(admin_client, fake_meter)
        set_capture_dir(tmp_path)

        scheduler, response = press_save_all(admin_client)
        assert response.status_code == 200, response.text
        assert response.json()["data"] == {
            "started": True,
            "status": {
                "running": True,
                "started_at": response.json()["data"]["status"]["started_at"],
                "finished_at": None,
                "billing_files_written": 0,
                "captures_written": 0,
                "captures_left": 0,
                "captures_failed": 0,
            },
        }
        assert scheduler.names == ["capture_sweep"]
        scheduler.drain()

        for serial, reading_ids in ids.items():
            assert (tmp_path / serial / f"{serial}-billing.csv").exists()
            for reading_id in reading_ids:
                pdf = pdf_for(tmp_path, reading_id)
                assert pdf.exists() and pdf.with_suffix(".xlsx").exists() and pdf.with_suffix(".png").exists()
                assert captured_at(reading_id) is not None
        status = admin_client.get("/api/billing/save-all/status").json()["data"]
        assert status["running"] is False and status["finished_at"] is not None
        assert (status["billing_files_written"], status["captures_written"], status["captures_left"]) == (2, 4, 0)
        assert status["captures_failed"] == 0

    def test_a_pre_existing_pdf_keeps_its_bytes_and_its_period_is_not_stamped(
        self, admin_client: TestClient, fake_meter, tmp_path: Path
    ) -> None:
        """A file present is done, whatever wrote it (decision ข) — the sweep
        never rewrites, and *Captured* moves only when the sweep wrote."""
        ids = seed_two_devices(admin_client, fake_meter)
        set_capture_dir(tmp_path)
        existing = pdf_for(tmp_path, ids["SN-1"][0])
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"%PDF-handed-over")

        scheduler, _response = press_save_all(admin_client)
        scheduler.drain()

        assert existing.read_bytes() == b"%PDF-handed-over"
        assert captured_at(ids["SN-1"][0]) is None
        assert not existing.with_suffix(".png").exists()  # a PDF present is done; its PNG is the download path's
        status = sweep_status()
        assert status is not None
        # Not "3 written, 1 failed": an existing file is *done*, never an attempt
        # that the O_EXCL write then refuses (mutation: dropping the existence
        # check turns it into exactly that).
        assert (status.captures_written, status.captures_failed, status.captures_left) == (3, 0, 0)

    def test_writes_go_device_by_device_newest_first(
        self, admin_client: TestClient, fake_meter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seed_two_devices(admin_client, fake_meter, periods=3)
        set_capture_dir(tmp_path)
        order: list[tuple[str, datetime]] = []
        real = sweep_module.capture_reading

        def spy(row, device_name, capture_dir, **kwargs):  # noqa: ANN001, ANN202
            order.append((device_name, row.bill_date.replace(tzinfo=UTC)))
            return real(row, device_name, capture_dir, **kwargs)

        monkeypatch.setattr(sweep_module, "capture_reading", spy)

        scheduler, _response = press_save_all(admin_client)
        scheduler.drain()

        assert order == [
            ("Main Incomer", BASE),
            ("Main Incomer", BASE - timedelta(days=30)),
            ("Main Incomer", BASE - timedelta(days=60)),
            ("Feeder", BASE),
            ("Feeder", BASE - timedelta(days=30)),
            ("Feeder", BASE - timedelta(days=60)),
        ]

    def test_a_paused_device_is_swept_too(self, admin_client: TestClient, fake_meter, tmp_path: Path) -> None:
        ids = seed_two_devices(admin_client, fake_meter)
        set_capture_dir(tmp_path)
        with session_scope() as session:
            session.query(Device).filter(Device.meter_serial == "SN-2").one().enabled = False

        scheduler, _response = press_save_all(admin_client)
        scheduler.drain()

        assert pdf_for(tmp_path, ids["SN-2"][0]).exists()
        assert (tmp_path / "SN-2" / "SN-2-billing.csv").exists()

    def test_a_licence_without_captures_writes_the_billing_files_only(
        self, admin_client: TestClient, fake_meter, tmp_path: Path, relicense
    ) -> None:
        ids = seed_two_devices(admin_client, fake_meter)
        set_capture_dir(tmp_path)
        relicense(admin_client, features=["billing"])

        scheduler, response = press_save_all(admin_client)
        assert response.status_code == 200, response.text
        scheduler.drain()

        status = sweep_status()
        assert status is not None and status.running is False
        assert (status.billing_files_written, status.captures_written) == (2, 0)
        assert not pdf_for(tmp_path, ids["SN-1"][0]).exists()

    def test_a_second_sweep_after_a_folder_move_fills_the_new_folder_and_leaves_the_old(
        self, admin_client: TestClient, fake_meter, tmp_path: Path
    ) -> None:
        ids = seed_two_devices(admin_client, fake_meter)
        old, new = tmp_path / "old", tmp_path / "new"
        set_capture_dir(old)
        scheduler, _response = press_save_all(admin_client)
        scheduler.drain()
        old_bytes = pdf_for(old, ids["SN-1"][0]).read_bytes()

        set_capture_dir(new)
        scheduler, _response = press_save_all(admin_client)
        scheduler.drain()

        assert pdf_for(new, ids["SN-1"][0]).exists()
        assert pdf_for(old, ids["SN-1"][0]).read_bytes() == old_bytes
        status = sweep_status()
        assert status is not None and status.captures_written == 4


class TestFailuresAndSlices:
    def test_a_period_that_cannot_be_written_is_counted_and_the_rest_are_written(
        self, admin_client: TestClient, fake_meter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ids = seed_two_devices(admin_client, fake_meter)
        set_capture_dir(tmp_path)
        doomed = ids["SN-1"][1]
        real = sweep_module.capture_reading

        def flaky(row, device_name, capture_dir, **kwargs):  # noqa: ANN001, ANN202
            if row.id == doomed:
                raise OSError("disk full")
            return real(row, device_name, capture_dir, **kwargs)

        monkeypatch.setattr(sweep_module, "capture_reading", flaky)

        scheduler, _response = press_save_all(admin_client)
        scheduler.drain()

        status = sweep_status()
        assert status is not None and status.running is False
        assert (status.captures_written, status.captures_failed, status.captures_left) == (3, 1, 0)
        assert not pdf_for(tmp_path, doomed).exists() and captured_at(doomed) is None
        for reading_id in (ids["SN-1"][0], *ids["SN-2"]):
            assert pdf_for(tmp_path, reading_id).exists()

    def test_a_slice_stops_after_the_capture_that_crosses_the_budget_and_requeues_itself(
        self, admin_client: TestClient, fake_meter, tmp_path: Path
    ) -> None:
        """Budget zero: every slice writes exactly one capture, publishes what is
        left, and queues the next slice — the regular jobs run in between on
        the real Scheduler. Driven slice by slice so the re-queue is visible."""
        seed_two_devices(admin_client, fake_meter)
        set_capture_dir(tmp_path)
        scheduler = RecordingScheduler()
        assert start_capture_sweep(scheduler) == "started"
        scheduler.pending.clear()  # the product's own first slice — replaced by budget-zero slices below

        first = run_sweep_slice(scheduler, budget_sec=0.0)

        assert first.running is True
        assert (first.billing_files_written, first.captures_written, first.captures_left) == (2, 1, 3)
        assert [name for name, _fn in scheduler.pending] == ["capture_sweep"]

        seen: list[SweepStatus] = [first]
        while scheduler.pending:
            scheduler.pending.clear()
            seen.append(run_sweep_slice(scheduler, budget_sec=0.0))

        assert [s.captures_written for s in seen] == [1, 2, 3, 4]
        assert [s.captures_left for s in seen] == [3, 2, 1, 0]
        assert seen[-1].running is False and seen[-1].finished_at is not None
        assert seen[-1].billing_files_written == 2  # written once, on the first slice only

    def test_a_status_survives_only_until_restart(self, admin_client: TestClient, fake_meter, tmp_path: Path) -> None:
        seed_two_devices(admin_client, fake_meter)
        set_capture_dir(tmp_path)
        scheduler, _response = press_save_all(admin_client)
        scheduler.drain()
        assert admin_client.get("/api/billing/save-all/status").json()["data"]["captures_written"] == 4

        reset_sweep_status()  # what a service restart does (ADR 0008)

        assert admin_client.get("/api/billing/save-all/status").json()["data"] is None


class TestTheEndpointPair:
    def test_an_empty_billing_folder_is_422_and_queues_nothing(self, admin_client: TestClient, fake_meter) -> None:
        seed_two_devices(admin_client, fake_meter)
        set_capture_dir(None)

        scheduler, response = press_save_all(admin_client)

        assert response.status_code == 422, response.text
        assert "Billing folder is empty" in response.text and "capture_dir" in response.text
        assert scheduler.pending == [] and sweep_status() is None

    def test_a_second_press_while_running_is_409_and_queues_nothing(
        self, admin_client: TestClient, fake_meter, tmp_path: Path
    ) -> None:
        seed_two_devices(admin_client, fake_meter)
        set_capture_dir(tmp_path)
        scheduler, first = press_save_all(admin_client)
        assert first.status_code == 200

        second = admin_client.post("/api/billing/save-all")

        assert second.status_code == 409, second.text
        assert "already running" in second.text
        assert len(scheduler.pending) == 1
        scheduler.drain()
        assert admin_client.post("/api/billing/save-all").status_code == 200  # finished — may run again

    def test_status_is_none_before_the_first_save_all(self, admin_client: TestClient) -> None:
        assert admin_client.get("/api/billing/save-all/status").json()["data"] is None

    def test_a_user_reads_the_status_but_may_not_press(self, user_client: TestClient, tmp_path: Path) -> None:
        set_capture_dir(tmp_path)

        assert user_client.get("/api/billing/save-all/status").status_code == 200
        assert user_client.post("/api/billing/save-all").status_code == 403

    def test_an_anonymous_caller_is_refused(self, anon_client: TestClient) -> None:
        assert anon_client.post("/api/billing/save-all").status_code == 401
        assert anon_client.get("/api/billing/save-all/status").status_code == 401

    def test_the_old_per_device_export_endpoint_is_gone(self, admin_client: TestClient) -> None:
        assert admin_client.post("/api/billing/export?device_id=1").status_code in (404, 405)
