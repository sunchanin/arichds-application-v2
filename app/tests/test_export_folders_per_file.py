"""Each export file has its own folder (customer request, 2026-09-23;
`.scratch/export-folders/spec.md`).

``export_output_dir`` stays the Load Profile CSV's folder; the billing file and
the Energy file gain ``export_billing_output_dir`` / ``export_energy_output_dir``,
each set on its own page's endpoint, and an **empty** one means "use the Load
Profile CSV folder" — so an install that set one folder before this change
keeps writing exactly where it did. Every test seeds two distinct folders and
asserts which one the file landed in, so a reader that forgot the fallback,
or one that read the wrong key, moves a path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import mint_meter_activation_code
from fakes import DEFAULT_FAKE_SERIAL
from fastapi.testclient import TestClient
from test_billing_csv_export import JAN
from test_billing_csv_export import seed as seed_billing
from test_energy_csv_export import seed_summary_day
from test_fileupload_cycle import (
    InMemoryTransport,
    _configure_sftp,
    license_features,  # noqa: F401 — a fixture that module defines; pytest finds it by name
)

from arichds.constants import METER_LOCAL_UTC_OFFSET_HOURS
from arichds.db.app_settings import (
    CAPTURE_DIR_KEY,
    EXPORT_AUTO_SAVE_ENABLED_KEY,
    EXPORT_BILLING_FILENAME_TMPL_KEY,
    EXPORT_BILLING_OUTPUT_DIR_KEY,
    EXPORT_CSV_FILENAME_TMPL_KEY,
    EXPORT_ENERGY_FILENAME_TMPL_KEY,
    EXPORT_ENERGY_OUTPUT_DIR_KEY,
    EXPORT_OUTPUT_DIR_KEY,
    set_setting,
)
from arichds.db.session import session_scope

pytestmark = pytest.mark.usefixtures("fake_meter")


def local_today():
    return (datetime.now(UTC) + timedelta(hours=METER_LOCAL_UTC_OFFSET_HOURS)).date()


def set_folders(*, load_profile: Path | None, billing: Path | None = None, energy: Path | None = None) -> None:
    with session_scope() as session:
        set_setting(session, EXPORT_OUTPUT_DIR_KEY, str(load_profile) if load_profile else "")
        set_setting(session, EXPORT_BILLING_OUTPUT_DIR_KEY, str(billing) if billing else "")
        set_setting(session, EXPORT_ENERGY_OUTPUT_DIR_KEY, str(energy) if energy else "")
        set_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, "true")
        set_setting(session, EXPORT_CSV_FILENAME_TMPL_KEY, "[serial].csv")
        set_setting(session, EXPORT_BILLING_FILENAME_TMPL_KEY, "[serial]-billing.csv")
        set_setting(session, EXPORT_ENERGY_FILENAME_TMPL_KEY, "[serial]-energy.csv")


def make_device(admin_client: TestClient) -> int:
    response = admin_client.post(
        "/api/devices",
        json={
            "name": "Main Incomer",
            "brand": "mitsu",
            "model": "smw110",
            "site_name": "Plant A",
            "transport": {"kind": "net", "host": "127.0.0.1", "port": 4059},
            "password": "hunter2",
            "meter_activation_code": mint_meter_activation_code(meter_serial=DEFAULT_FAKE_SERIAL),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


class TestTheBillingPageSetting:
    def test_a_fresh_database_answers_empty(self, admin_client: TestClient) -> None:
        assert admin_client.get("/api/billing/settings").json()["data"]["export_billing_output_dir"] == ""

    def test_an_admin_round_trips_the_folder_beside_the_capture_folder(
        self, admin_client: TestClient, tmp_path: Path
    ) -> None:
        response = admin_client.put(
            "/api/billing/settings", json={"capture_dir": "", "export_billing_output_dir": str(tmp_path)}
        )

        assert response.status_code == 200, response.text
        data = admin_client.get("/api/billing/settings").json()["data"]
        assert data["export_billing_output_dir"] == str(tmp_path.resolve())
        assert data["capture_dir"] == ""

    def test_a_relative_folder_is_422_and_nothing_is_saved(self, admin_client: TestClient) -> None:
        response = admin_client.put(
            "/api/billing/settings", json={"capture_dir": "", "export_billing_output_dir": "rel/dir"}
        )

        assert response.status_code == 422, response.text
        assert "export_billing_output_dir" in response.text
        assert admin_client.get("/api/billing/settings").json()["data"]["export_billing_output_dir"] == ""

    def test_omitting_the_folder_keeps_the_stored_value(self, admin_client: TestClient, tmp_path: Path) -> None:
        admin_client.put("/api/billing/settings", json={"capture_dir": "", "export_billing_output_dir": str(tmp_path)})

        response = admin_client.put("/api/billing/settings", json={"capture_dir": ""})

        assert response.status_code == 200, response.text
        assert response.json()["data"]["export_billing_output_dir"] == str(tmp_path.resolve())

    def test_an_empty_string_clears_it(self, admin_client: TestClient, tmp_path: Path) -> None:
        admin_client.put("/api/billing/settings", json={"capture_dir": "", "export_billing_output_dir": str(tmp_path)})

        response = admin_client.put("/api/billing/settings", json={"capture_dir": "", "export_billing_output_dir": ""})

        assert response.json()["data"]["export_billing_output_dir"] == ""

    def test_a_plain_user_reads_and_is_refused_on_write(self, user_client: TestClient, tmp_path: Path) -> None:
        assert user_client.get("/api/billing/settings").status_code == 200
        response = user_client.put(
            "/api/billing/settings", json={"capture_dir": "", "export_billing_output_dir": str(tmp_path)}
        )
        assert response.status_code == 403


class TestTheEnergyPageSetting:
    def test_a_fresh_database_answers_empty(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/energy/settings")

        assert response.status_code == 200, response.text
        assert response.json()["data"] == {"export_energy_output_dir": ""}

    def test_an_admin_round_trips_the_folder(self, admin_client: TestClient, tmp_path: Path) -> None:
        response = admin_client.put("/api/energy/settings", json={"export_energy_output_dir": str(tmp_path)})

        assert response.status_code == 200, response.text
        assert admin_client.get("/api/energy/settings").json()["data"]["export_energy_output_dir"] == str(
            tmp_path.resolve()
        )

    def test_a_relative_folder_is_422_and_nothing_is_saved(self, admin_client: TestClient) -> None:
        response = admin_client.put("/api/energy/settings", json={"export_energy_output_dir": "rel/dir"})

        assert response.status_code == 422, response.text
        assert "export_energy_output_dir" in response.text
        assert admin_client.get("/api/energy/settings").json()["data"]["export_energy_output_dir"] == ""

    def test_a_plain_user_reads_and_is_refused_on_write(self, user_client: TestClient, tmp_path: Path) -> None:
        assert user_client.get("/api/energy/settings").status_code == 200
        assert (
            user_client.put("/api/energy/settings", json={"export_energy_output_dir": str(tmp_path)}).status_code == 403
        )

    def test_requires_the_energy_summary_feature(self, admin_client: TestClient, relicense) -> None:
        relicense(admin_client, features=["billing"])

        assert admin_client.get("/api/energy/settings").status_code == 403


class TestTheBillingFileFolder:
    def test_the_billing_file_lands_in_its_own_folder_not_the_load_profile_one(
        self, admin_client: TestClient, tmp_path: Path
    ) -> None:
        from arichds.export.billing_csv import export_device_billing

        lp, bill = tmp_path / "lp", tmp_path / "bill"
        set_folders(load_profile=lp, billing=bill)
        device_id = make_device(admin_client)
        seed_billing(device_id, JAN, import_active_kwh_total=100.0)

        result = export_device_billing(device_id, require_auto_save=False)

        assert result.path is not None and result.path.parent == bill.resolve()
        assert not (lp / result.path.name).exists()

    def test_an_empty_billing_folder_falls_back_to_the_load_profile_folder(
        self, admin_client: TestClient, tmp_path: Path
    ) -> None:
        from arichds.export.billing_csv import export_device_billing

        lp = tmp_path / "lp"
        set_folders(load_profile=lp, billing=None)
        device_id = make_device(admin_client)
        seed_billing(device_id, JAN, import_active_kwh_total=100.0)

        result = export_device_billing(device_id, require_auto_save=False)

        assert result.path is not None and result.path.parent == lp.resolve()

    def test_save_billing_file_now_needs_no_load_profile_folder_when_its_own_is_set(
        self, admin_client: TestClient, tmp_path: Path
    ) -> None:
        bill = tmp_path / "bill"
        set_folders(load_profile=None, billing=bill)
        device_id = make_device(admin_client)
        seed_billing(device_id, JAN, import_active_kwh_total=100.0)

        response = admin_client.post(f"/api/billing/export?device_id={device_id}")

        assert response.status_code == 200, response.text
        assert Path(response.json()["data"]["path"]).parent == bill.resolve()

    def test_save_billing_file_now_names_the_field_on_its_own_page_when_neither_is_set(
        self, admin_client: TestClient
    ) -> None:
        set_folders(load_profile=None, billing=None)
        device_id = make_device(admin_client)
        seed_billing(device_id, JAN, import_active_kwh_total=100.0)

        response = admin_client.post(f"/api/billing/export?device_id={device_id}")

        assert response.status_code == 422, response.text
        assert "Billing file folder" in response.text
        assert "export_billing_output_dir" in response.text


class TestTheEnergyFileFolder:
    def test_the_energy_file_lands_in_its_own_folder(self, admin_client: TestClient, tmp_path: Path) -> None:
        from arichds.export.energy_csv import export_device_energy

        lp, energy = tmp_path / "lp", tmp_path / "energy"
        set_folders(load_profile=lp, energy=energy)
        device_id = make_device(admin_client)
        seed_summary_day(device_id, local_today() - timedelta(days=2))

        result = export_device_energy(device_id, require_auto_save=False)

        assert result.path is not None and result.path.parent == energy.resolve()
        assert not (lp / result.path.name).exists()

    def test_an_empty_energy_folder_falls_back_to_the_load_profile_folder(
        self, admin_client: TestClient, tmp_path: Path
    ) -> None:
        from arichds.export.energy_csv import export_device_energy

        lp = tmp_path / "lp"
        set_folders(load_profile=lp, energy=None)
        device_id = make_device(admin_client)
        seed_summary_day(device_id, local_today() - timedelta(days=2))

        result = export_device_energy(device_id, require_auto_save=False)

        assert result.path is not None and result.path.parent == lp.resolve()

    def test_save_to_file_uses_the_energy_folder(self, admin_client: TestClient, tmp_path: Path) -> None:
        energy = tmp_path / "energy"
        set_folders(load_profile=None, energy=energy)
        device_id = make_device(admin_client)
        day = local_today() - timedelta(days=2)
        seed_summary_day(device_id, day)

        response = admin_client.post(f"/api/energy/export?device_id={device_id}&start_date={day}&end_date={day}")

        assert response.status_code == 200, response.text
        assert Path(response.json()["data"]["path"]).parent == energy.resolve()

    def test_save_to_file_names_the_field_on_its_own_page_when_neither_is_set(self, admin_client: TestClient) -> None:
        set_folders(load_profile=None, energy=None)
        device_id = make_device(admin_client)
        day = local_today() - timedelta(days=2)
        seed_summary_day(device_id, day)

        response = admin_client.post(f"/api/energy/export?device_id={device_id}&start_date={day}&end_date={day}")

        assert response.status_code == 422, response.text
        assert "Energy file folder" in response.text


class TestTheUploadCycleReadsEachFolder:
    def test_three_folders_three_files_one_export_group(
        self,
        admin_client: TestClient,
        license_features,  # noqa: F811 — the fixture imported above
        tmp_path: Path,
    ) -> None:
        from arichds.fileupload.cycle import file_upload_cycle

        license_features(["file_upload_destination"])
        _configure_sftp()
        lp, bill, energy = tmp_path / "lp", tmp_path / "bill", tmp_path / "energy"
        for folder in (lp, bill, energy):
            folder.mkdir()
        set_folders(load_profile=lp, billing=bill, energy=energy)
        with session_scope() as session:
            set_setting(session, CAPTURE_DIR_KEY, "")
        make_device(admin_client)
        serial = DEFAULT_FAKE_SERIAL
        (lp / f"{serial}.csv").write_bytes(b"lp\n")
        (bill / f"{serial}-billing.csv").write_bytes(b"bill\n")
        (energy / f"{serial}-energy.csv").write_bytes(b"energy\n")
        # A billing file left behind in the Load Profile folder is not the billing file any more.
        (lp / f"{serial}-billing.csv").write_bytes(b"stale\n")
        transport = InMemoryTransport(manifest=None)

        file_upload_cycle(transport=transport)

        assert set(transport.puts) == {
            f"export/{serial}.csv",
            f"export/{serial}-billing.csv",
            f"export/{serial}-energy.csv",
        }
        assert transport.puts[f"export/{serial}-billing.csv"] == b"bill\n"

    def test_an_empty_billing_folder_means_the_billing_file_comes_from_the_load_profile_folder(
        self,
        admin_client: TestClient,
        license_features,  # noqa: F811 — the fixture imported above
        tmp_path: Path,
    ) -> None:
        from arichds.fileupload.cycle import file_upload_cycle

        license_features(["file_upload_destination"])
        _configure_sftp()
        lp = tmp_path / "lp"
        lp.mkdir()
        set_folders(load_profile=lp, billing=None, energy=None)
        with session_scope() as session:
            set_setting(session, CAPTURE_DIR_KEY, "")
        make_device(admin_client)
        serial = DEFAULT_FAKE_SERIAL
        (lp / f"{serial}-billing.csv").write_text("bill\n")
        transport = InMemoryTransport(manifest=None)

        file_upload_cycle(transport=transport)

        assert set(transport.puts) == {f"export/{serial}-billing.csv"}
