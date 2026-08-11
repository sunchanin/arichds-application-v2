"""``GET``/``PUT /api/settings/display`` — the machine-wide display-unit
setting (kW/kWh vs W/Wh; a CR, not part of any milestone's original shape).

``GET`` is any authenticated caller (reading a setting is not admin-only,
mirroring ``GET /api/billing/settings``); ``PUT`` is admin-only. The value is
one of exactly two literals — anything else is refused with 422, and pydantic
does the rejecting (no hand-rolled validation to drift from the model).
"""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestGetIsOpenToAnyAuthenticatedCaller:
    def test_a_fresh_database_answers_with_the_documented_default(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/settings/display")

        assert response.status_code == 200, response.text
        assert response.json()["data"] == {"display_unit_scale": "kilo"}

    def test_a_plain_user_may_read_it(self, user_client: TestClient) -> None:
        assert user_client.get("/api/settings/display").status_code == 200

    def test_an_anonymous_caller_is_refused(self, anon_client: TestClient) -> None:
        assert anon_client.get("/api/settings/display").status_code == 401


class TestPutIsAdminOnly:
    def test_a_plain_user_is_refused(self, user_client: TestClient) -> None:
        response = user_client.put("/api/settings/display", json={"display_unit_scale": "base"})
        assert response.status_code == 403

    def test_an_admin_may_save_base(self, admin_client: TestClient) -> None:
        response = admin_client.put("/api/settings/display", json={"display_unit_scale": "base"})

        assert response.status_code == 200, response.text
        assert response.json()["data"] == {"display_unit_scale": "base"}

        follow_up = admin_client.get("/api/settings/display")
        assert follow_up.json()["data"] == {"display_unit_scale": "base"}

    def test_an_admin_may_save_kilo_back(self, admin_client: TestClient) -> None:
        admin_client.put("/api/settings/display", json={"display_unit_scale": "base"})

        response = admin_client.put("/api/settings/display", json={"display_unit_scale": "kilo"})

        assert response.status_code == 200, response.text
        assert response.json()["data"] == {"display_unit_scale": "kilo"}

    def test_an_unknown_value_is_422(self, admin_client: TestClient) -> None:
        response = admin_client.put("/api/settings/display", json={"display_unit_scale": "mega"})
        assert response.status_code == 422, response.text

    def test_an_anonymous_caller_is_401_not_422(self, anon_client: TestClient) -> None:
        """The auth guard must run before body validation — an unauthenticated
        PUT with a bad body is still a 401, not a 422 (matches the
        `require_admin` guard's own docs)."""
        response = anon_client.put("/api/settings/display", json={"display_unit_scale": "mega"})
        assert response.status_code == 401, response.text
