"""``GET /api/logs`` — the App Log endpoint (M7-4, issue #31).

Mirrors ``test_api_battery.py``'s class layout. This module makes no v1
output-matching claim of any kind — v1's App Log page is an unwired shell
with nothing to compare against (SPEC §3.7).
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from arichds.config import get_settings


class TestReadsTheLiveLogFile:
    def test_the_last_entry_matches_a_marker_logged_during_the_test(self, admin_client: TestClient) -> None:
        logging.getLogger("arichds.test").error("marker-abc123")

        response = admin_client.get("/api/logs")

        assert response.status_code == 200, response.text
        last = response.json()["data"]["items"][-1]
        assert last["level"] == "ERROR"
        assert last["logger"] == "arichds.test"
        assert last["message"] == "marker-abc123"
        assert last["timestamp"]


class TestRedactionIsNeitherIntroducedNorUndone:
    def test_a_written_secret_comes_back_exactly_redacted(self, admin_client: TestClient) -> None:
        logging.getLogger("arichds.test").info("connecting password=hunter2 token=abc123")

        response = admin_client.get("/api/logs")

        last = response.json()["data"]["items"][-1]
        assert last["message"] == "connecting password=[REDACTED] token=[REDACTED]"
        assert "hunter2" not in response.text
        assert "abc123" not in response.text


class TestRefreshReReadsFromDisk:
    def test_a_second_call_after_a_second_log_line_sees_one_more_entry(self, admin_client: TestClient) -> None:
        # httpx logs its own "HTTP Request: GET ... 200 OK" line into the same
        # root logger *after* the response is built — that line would land in
        # the file between the two reads below and inflate the count by one
        # more than the marker being tested, which has nothing to do with
        # whether /api/logs itself re-reads from disk. Silenced for this test
        # only, so the count that moves is exactly the one this test is about.
        httpx_logger = logging.getLogger("httpx")
        previous_level = httpx_logger.level
        httpx_logger.setLevel(logging.WARNING)
        try:
            logging.getLogger("arichds.test").info("first-marker")
            first = admin_client.get("/api/logs").json()["data"]["items"]
            n = len(first)

            logging.getLogger("arichds.test").info("second-marker")
            second = admin_client.get("/api/logs").json()["data"]["items"]
        finally:
            httpx_logger.setLevel(previous_level)

        assert len(second) == n + 1
        assert second[-1]["message"] == "second-marker"


class TestOpsOnly:
    def test_an_empty_sellable_license_still_serves_200(self, admin_client: TestClient, relicense) -> None:
        relicense(admin_client, features=[])

        response = admin_client.get("/api/logs")

        assert response.status_code == 200, response.text

    def test_env_omitting_app_log_answers_feature_disabled(
        self, admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ARICHDS_FEATURES", "billing")
        get_settings.cache_clear()

        response = admin_client.get("/api/logs")

        assert response.status_code == 403, response.text
        body = response.json()
        assert body["error"]["code"] == "FEATURE_DISABLED"
        assert body["error"]["reason"] == "app_log"


class TestRoles:
    def test_anon_gets_401(self, anon_client: TestClient) -> None:
        assert anon_client.get("/api/logs").status_code == 401

    def test_user_gets_403(self, user_client: TestClient) -> None:
        assert user_client.get("/api/logs").status_code == 403

    def test_admin_gets_200(self, admin_client: TestClient) -> None:
        assert admin_client.get("/api/logs").status_code == 200

    def test_user_with_app_log_disabled_gets_feature_disabled_not_admin_message(
        self, user_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ARICHDS_FEATURES", "billing")
        get_settings.cache_clear()

        response = user_client.get("/api/logs")

        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FEATURE_DISABLED"


class TestBoundsAndValidation:
    def test_lines_zero_is_422(self, admin_client: TestClient) -> None:
        assert admin_client.get("/api/logs", params={"lines": 0}).status_code == 422

    def test_lines_over_max_is_422(self, admin_client: TestClient) -> None:
        assert admin_client.get("/api/logs", params={"lines": 5001}).status_code == 422

    def test_an_unknown_level_is_422(self, admin_client: TestClient) -> None:
        assert admin_client.get("/api/logs", params={"min_level": "LOUD"}).status_code == 422


class TestNoParameterNamesAFile:
    def test_the_openapi_document_lists_exactly_lines_and_min_level(self, admin_client: TestClient) -> None:
        response = admin_client.get("/openapi.json")

        assert response.status_code == 200, response.text
        parameters = response.json()["paths"]["/api/logs"]["get"]["parameters"]
        names = {p["name"] for p in parameters}
        assert names == {"lines", "min_level"}


class TestEmptyStateOverHttp:
    def test_a_level_nothing_logged_at_returns_an_empty_list(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/logs", params={"min_level": "CRITICAL"})

        assert response.status_code == 200, response.text
        assert response.json()["data"]["items"] == []


class TestLinesParameterIsWired:
    def test_lines_equal_one_returns_exactly_the_last_marker(self, admin_client: TestClient) -> None:
        logger = logging.getLogger("arichds.test")
        logger.info("marker-one")
        logger.info("marker-two")
        logger.info("marker-three")

        response = admin_client.get("/api/logs", params={"lines": 1})

        assert response.status_code == 200, response.text
        items = response.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["message"] == "marker-three"
