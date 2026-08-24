"""``GET``/``PUT /api/billing/settings`` — the ``capture_dir`` setting (M6b,
issue #22).

``GET`` is any authenticated caller (reading a setting is not admin-only,
mirroring the rest of this router); ``PUT`` is admin-only and validates
before saving (ADR 0010). ``capture_count`` is the number of **closed**
billing rows, computed from the database — the warning it feeds is the
frontend's job, never the backend's (decision 2d: "warns, never blocks").
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import mint_meter_activation_code
from fakes import DEFAULT_FAKE_SERIAL
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("fake_meter")

BASE = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def seed_closed(device_id: int, bill_date: datetime) -> None:
    from arichds.db.models import BillingReading
    from arichds.db.session import session_scope

    with session_scope() as session:
        session.add(
            BillingReading(
                device_id=device_id,
                bill_date=bill_date,
                read_at=bill_date,
                record_status=None,
                source="dlms",
                meter_serial="SN-1",
            )
        )


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


class TestGetIsOpenToAnyAuthenticatedCaller:
    def test_a_fresh_database_answers_with_the_documented_default(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/billing/settings")

        assert response.status_code == 200, response.text
        assert response.json()["data"] == {"capture_dir": "", "capture_count": 0}

    def test_a_plain_user_may_read_it(self, user_client: TestClient) -> None:
        assert user_client.get("/api/billing/settings").status_code == 200

    def test_an_anonymous_caller_is_refused(self, anon_client: TestClient) -> None:
        assert anon_client.get("/api/billing/settings").status_code == 401

    def test_capture_count_is_the_number_of_closed_rows_only(self, admin_client: TestClient) -> None:
        device_id = make_device(admin_client)
        seed_closed(device_id, BASE)
        seed_closed(device_id, BASE.replace(month=9))

        response = admin_client.get("/api/billing/settings")

        assert response.json()["data"]["capture_count"] == 2


class TestPutIsAdminOnly:
    def test_a_plain_user_is_refused(self, user_client: TestClient, tmp_path) -> None:
        response = user_client.put("/api/billing/settings", json={"capture_dir": str(tmp_path)})
        assert response.status_code == 403

    def test_an_admin_may_save_a_valid_absolute_path(self, admin_client: TestClient, tmp_path) -> None:
        response = admin_client.put("/api/billing/settings", json={"capture_dir": str(tmp_path)})

        assert response.status_code == 200, response.text
        assert response.json()["data"]["capture_dir"] == str(tmp_path.resolve())

        follow_up = admin_client.get("/api/billing/settings")
        assert follow_up.json()["data"]["capture_dir"] == str(tmp_path.resolve())

    def test_a_relative_path_is_422(self, admin_client: TestClient) -> None:
        response = admin_client.put("/api/billing/settings", json={"capture_dir": "relative/dir"})
        assert response.status_code == 422, response.text

    def test_an_empty_string_disables_capture_without_validation(self, admin_client: TestClient) -> None:
        response = admin_client.put("/api/billing/settings", json={"capture_dir": ""})

        assert response.status_code == 200, response.text
        assert response.json()["data"]["capture_dir"] == ""
