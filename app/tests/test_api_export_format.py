"""``GET``/``PUT /api/settings/export-format`` — the Export Format settings
page (M7 slice 3, issue #30, D-17).

``GET`` is any authenticated caller; ``PUT`` is admin-only and validates
before saving (D-13). Both are gated behind ``require_feature("load_profile")``
(D-14) — the CSV is Load Profile data, the same gate
``GET /api/load-profile`` already carries.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("fake_meter")

DEFAULTS = {
    "export_date_format": "yyyy-mm-dd HH:MM:SS",
    "export_csv_filename_tmpl": "[meter].csv",
    "export_auto_save_enabled": False,
    "export_output_dir": "",
}


class TestGetIsOpenToAnyAuthenticatedCaller:
    def test_a_fresh_database_answers_with_the_documented_defaults(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/settings/export-format")

        assert response.status_code == 200, response.text
        assert response.json()["data"] == DEFAULTS

    def test_a_plain_user_may_read_it(self, user_client: TestClient) -> None:
        assert user_client.get("/api/settings/export-format").status_code == 200

    def test_an_anonymous_caller_is_refused(self, anon_client: TestClient) -> None:
        assert anon_client.get("/api/settings/export-format").status_code == 401


class TestPutIsAdminOnly:
    def test_a_plain_user_is_refused(self, user_client: TestClient) -> None:
        response = user_client.put("/api/settings/export-format", json=DEFAULTS)
        assert response.status_code == 403

    def test_an_admin_may_save_all_four_values(self, admin_client: TestClient, tmp_path) -> None:
        body = {
            "export_date_format": "dd/mm/yyyy",
            "export_csv_filename_tmpl": "[serial]-[date].csv",
            "export_auto_save_enabled": True,
            "export_output_dir": str(tmp_path),
        }

        response = admin_client.put("/api/settings/export-format", json=body)

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["export_date_format"] == "dd/mm/yyyy"
        assert data["export_csv_filename_tmpl"] == "[serial]-[date].csv"
        assert data["export_auto_save_enabled"] is True
        assert data["export_output_dir"] == str(tmp_path.resolve())

        follow_up = admin_client.get("/api/settings/export-format")
        assert follow_up.json()["data"] == data

    def test_an_anonymous_caller_is_401_not_422(self, anon_client: TestClient) -> None:
        """The auth guard runs before body validation — matches
        `test_api_settings.py`'s own display-settings equivalent."""
        response = anon_client.put("/api/settings/export-format", json={"export_date_format": 1})
        assert response.status_code == 401, response.text


class TestDateFormatValidation:
    """Nit 3, code review — an empty format would silently blank the
    Date/Time column of every future export."""

    def test_an_empty_date_format_is_refused_with_422(self, admin_client: TestClient) -> None:
        body = {**DEFAULTS, "export_date_format": ""}
        response = admin_client.put("/api/settings/export-format", json=body)
        assert response.status_code == 422, response.text

    def test_a_whitespace_only_date_format_is_refused_with_422(self, admin_client: TestClient) -> None:
        body = {**DEFAULTS, "export_date_format": "   "}
        response = admin_client.put("/api/settings/export-format", json=body)
        assert response.status_code == 422, response.text

    def test_a_refused_date_format_never_reaches_the_stored_setting(self, admin_client: TestClient) -> None:
        admin_client.put("/api/settings/export-format", json=DEFAULTS)  # baseline
        body = {**DEFAULTS, "export_date_format": ""}

        admin_client.put("/api/settings/export-format", json=body)

        follow_up = admin_client.get("/api/settings/export-format")
        assert follow_up.json()["data"]["export_date_format"] == "yyyy-mm-dd HH:MM:SS"


class TestFilenameTemplateValidation:
    """D-13 — a filename, not a path."""

    def test_a_slash_is_refused_with_422(self, admin_client: TestClient) -> None:
        body = {**DEFAULTS, "export_csv_filename_tmpl": "sub/dir.csv"}
        response = admin_client.put("/api/settings/export-format", json=body)
        assert response.status_code == 422, response.text

    def test_a_backslash_is_refused_with_422(self, admin_client: TestClient) -> None:
        body = {**DEFAULTS, "export_csv_filename_tmpl": "sub\\dir.csv"}
        response = admin_client.put("/api/settings/export-format", json=body)
        assert response.status_code == 422, response.text

    def test_dotdot_is_refused_with_422(self, admin_client: TestClient) -> None:
        body = {**DEFAULTS, "export_csv_filename_tmpl": "../escape.csv"}
        response = admin_client.put("/api/settings/export-format", json=body)
        assert response.status_code == 422, response.text

    def test_empty_is_refused_with_422(self, admin_client: TestClient) -> None:
        body = {**DEFAULTS, "export_csv_filename_tmpl": ""}
        response = admin_client.put("/api/settings/export-format", json=body)
        assert response.status_code == 422, response.text

    def test_a_refused_template_never_reaches_the_stored_setting(self, admin_client: TestClient) -> None:
        admin_client.put("/api/settings/export-format", json=DEFAULTS)  # baseline
        body = {**DEFAULTS, "export_csv_filename_tmpl": "../escape.csv"}

        admin_client.put("/api/settings/export-format", json=body)

        follow_up = admin_client.get("/api/settings/export-format")
        assert follow_up.json()["data"]["export_csv_filename_tmpl"] == "[meter].csv"


class TestOutputDirValidation:
    def test_a_relative_output_dir_is_422(self, admin_client: TestClient) -> None:
        body = {**DEFAULTS, "export_output_dir": "relative/dir"}
        response = admin_client.put("/api/settings/export-format", json=body)
        assert response.status_code == 422, response.text

    def test_an_empty_output_dir_is_accepted_without_validation(self, admin_client: TestClient) -> None:
        response = admin_client.put("/api/settings/export-format", json=DEFAULTS)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["export_output_dir"] == ""


class TestEnablingAutoSaveRequiresAnOutputDir:
    """D-7 — a switch nothing can act on is a trap, not a stored preference."""

    def test_enabling_with_no_output_dir_is_422(self, admin_client: TestClient) -> None:
        body = {**DEFAULTS, "export_auto_save_enabled": True, "export_output_dir": ""}
        response = admin_client.put("/api/settings/export-format", json=body)
        assert response.status_code == 422, response.text

    def test_enabling_with_a_valid_output_dir_succeeds(self, admin_client: TestClient, tmp_path) -> None:
        body = {**DEFAULTS, "export_auto_save_enabled": True, "export_output_dir": str(tmp_path)}
        response = admin_client.put("/api/settings/export-format", json=body)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["export_auto_save_enabled"] is True


class TestFeatureGating:
    def test_get_is_gated_behind_load_profile(self, admin_client: TestClient, relicense) -> None:
        relicense(admin_client, features=["billing"])  # load_profile withheld
        response = admin_client.get("/api/settings/export-format")
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FEATURE_DISABLED"

    def test_put_is_gated_behind_load_profile(self, admin_client: TestClient, relicense) -> None:
        relicense(admin_client, features=["billing"])
        response = admin_client.put("/api/settings/export-format", json=DEFAULTS)
        assert response.status_code == 403, response.text
