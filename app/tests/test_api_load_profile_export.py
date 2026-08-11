"""``POST /api/load-profile/export`` — "Save CSV now" (M7 slice 3, issue #30, D-17).

Any authenticated role, ignores ``export_auto_save_enabled`` (D-11),
requires ``export_output_dir`` to be configured (422 otherwise). This file
also carries **T1**, the headline acceptance criterion: the endpoint's
merged rows and the exported file's rows must agree, field by field, for
the same device and the same window.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeMeterState
from fastapi.testclient import TestClient

from arichds.db.app_settings import EXPORT_AUTO_SAVE_ENABLED_KEY, EXPORT_OUTPUT_DIR_KEY, set_setting
from arichds.db.models import LoadProfileReading
from arichds.db.session import session_scope

pytestmark = pytest.mark.usefixtures("fake_meter")

DEVICE = {
    "name": "Main Incomer",
    "brand": "mitsu",
    "model": "smw110",
    "site_name": "Plant A",
    "transport": {"kind": "net", "host": "127.0.0.1", "port": 4059},
    "password": "hunter2",
}

BASE = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def add_device(
    client: TestClient,
    fake_meter: FakeMeterState,
    *,
    serial: str = "SN-1",
    loggers: tuple[int, ...] = (1,),
    **overrides: object,
) -> int:
    fake_meter.meter_serial = serial
    fake_meter.load_profile_loggers = loggers
    response = client.post("/api/devices", json={**DEVICE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def seed(device_id: int, read_at: datetime, *, logger_id: int = 1, **columns: float) -> None:
    with session_scope() as session:
        session.add(
            LoadProfileReading(
                device_id=device_id,
                read_at=read_at,
                source="dlms",
                logger_id=logger_id,
                interval_sec=900,
                **columns,
            )
        )


def configure(session_client: TestClient, *, output_dir) -> None:  # noqa: ANN001
    with session_scope() as session:
        set_setting(session, EXPORT_OUTPUT_DIR_KEY, str(output_dir))
        set_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, "false")


class TestAnyAuthenticatedRoleMayExport:
    def test_a_plain_user_may_export(
        self, user_client: TestClient, admin_client: TestClient, fake_meter: FakeMeterState, tmp_path
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        configure(admin_client, output_dir=tmp_path)
        seed(device_id, BASE, import_active_kwh=1.0)

        response = user_client.post(f"/api/load-profile/export?device_id={device_id}")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["rows_written"] == 1

    def test_an_anonymous_caller_is_401(self, anon_client: TestClient) -> None:
        response = anon_client.post("/api/load-profile/export?device_id=1")
        assert response.status_code == 401, response.text


class TestIgnoresAutoSaveEnabled:
    def test_exports_even_when_auto_save_is_off(
        self, admin_client: TestClient, fake_meter: FakeMeterState, tmp_path
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        configure(admin_client, output_dir=tmp_path)  # auto-save is false in configure()
        seed(device_id, BASE, import_active_kwh=1.0)

        response = admin_client.post(f"/api/load-profile/export?device_id={device_id}")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["rows_written"] == 1


class TestOutputDirIsRequired:
    def test_an_unconfigured_output_dir_is_422(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, BASE, import_active_kwh=1.0)

        response = admin_client.post(f"/api/load-profile/export?device_id={device_id}")

        assert response.status_code == 422, response.text


class TestUnknownDevice:
    def test_a_missing_device_is_404(self, admin_client: TestClient) -> None:
        response = admin_client.post("/api/load-profile/export?device_id=4242")
        assert response.status_code == 404, response.text


class TestFeatureGating:
    def test_gated_behind_load_profile(self, admin_client: TestClient, fake_meter: FakeMeterState, relicense) -> None:
        device_id = add_device(admin_client, fake_meter)
        relicense(admin_client, features=["billing"])

        response = admin_client.post(f"/api/load-profile/export?device_id={device_id}")

        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FEATURE_DISABLED"


class TestEndpointAndFileAgree:
    """T1 — the headline acceptance criterion."""

    def test_the_files_data_cells_equal_the_endpoints_rows(
        self, admin_client: TestClient, fake_meter: FakeMeterState, tmp_path
    ) -> None:
        device_id = add_device(admin_client, fake_meter, loggers=(1, 2))
        other_device_id = add_device(admin_client, fake_meter, serial="SN-2", name="Other", loggers=(1, 2))
        configure(admin_client, output_dir=tmp_path)

        t0 = BASE
        t1 = BASE + timedelta(minutes=15)
        t2 = BASE + timedelta(minutes=30)
        t3 = BASE + timedelta(minutes=45)

        # (a) L1 at t0 with volt_l1=None, L2 at exactly t0 fills it.
        seed(device_id, t0, logger_id=1, volt_l1=None, import_active_kwh=1.0)
        seed(device_id, t0, logger_id=2, volt_l1=230.5)
        # (b) L1 wins the collision at t1.
        seed(device_id, t1, logger_id=1, volt_l1=231.0, import_active_kwh=2.0)
        seed(device_id, t1, logger_id=2, volt_l1=999.0)
        # (c) an L2-only row at t2 appears nowhere.
        seed(device_id, t2, logger_id=2, volt_l1=99.0)
        # (d) L1 at t3 plus an L2 row 300s later — the near miss fills nothing.
        seed(device_id, t3, logger_id=1, volt_l1=232.0, import_active_kwh=3.0)
        seed(device_id, t3 + timedelta(seconds=300), logger_id=2, volt_l1=999.0)
        # (e) a second device at the same timestamps, different values.
        seed(other_device_id, t0, logger_id=1, volt_l1=1.0, import_active_kwh=100.0)

        window_start = BASE - timedelta(days=1)
        window_end = BASE + timedelta(days=1)
        api_response = admin_client.get(
            "/api/load-profile",
            params={
                "device_id": device_id,
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
                "limit": 500,
            },
        )
        assert api_response.status_code == 200, api_response.text
        api_rows = {row["read_at"]: row for row in api_response.json()["data"]["items"]}
        assert len(api_rows) == 3, "the L2-only instant must not appear"

        export_response = admin_client.post(f"/api/load-profile/export?device_id={device_id}")
        assert export_response.status_code == 200, export_response.text
        assert export_response.json()["data"]["rows_written"] == 3

        file_path = tmp_path / "SN-1.csv"
        file_lines = file_path.read_text(encoding="utf-8-sig").splitlines()
        data_lines = file_lines[1:]  # skip header
        assert len(data_lines) == 3

        # Field-by-field: for each exported row, the volt_l1 cell (index 7,
        # after Name/Date/Time/4 energy/PF) must equal the endpoint's value
        # for the same read_at, formatted the same way (.3f, empty for None).
        for line in data_lines:
            cells = line.split(",")
            timestamp_ict = cells[1]
            # Reconstruct the UTC read_at from the ICT-shifted display string.
            local_dt = datetime.strptime(timestamp_ict, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            read_at_utc = (local_dt - timedelta(hours=7)).isoformat()
            matching_api_row = next((v for k, v in api_rows.items() if k.startswith(read_at_utc[:19])), None)
            assert matching_api_row is not None, f"{timestamp_ict} not found in the endpoint's rows"
            volt_l1_cell = cells[7]
            expected = "" if matching_api_row["volt_l1"] is None else format(matching_api_row["volt_l1"], ".3f")
            assert volt_l1_cell == expected
