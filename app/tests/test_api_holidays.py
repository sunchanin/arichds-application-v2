"""Holidays API (M7-1, issue #28) — CRUD, JSON export/import, and the
meter-import replace-the-whole-set path.
"""

from __future__ import annotations

import logging

import pytest
from conftest import mint_meter_activation_code
from fakes import FakeMeterState
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("fake_meter")

DEVICE = {
    "name": "Main Incomer",
    "brand": "mitsu",
    "model": "smw110",
    "site_name": "Plant A",
    "transport": {"kind": "net", "host": "127.0.0.1", "port": 4059},
    "password": "hunter2",
}


def add_device(client: TestClient, fake_meter: FakeMeterState, *, serial: str = "SN-1") -> int:
    fake_meter.meter_serial = serial
    payload = {**DEVICE, "meter_activation_code": mint_meter_activation_code(meter_serial=serial)}
    response = client.post("/api/devices", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def holiday_changes(client: TestClient) -> list[dict]:
    """The Holiday Change record's first page (ADR 0022, M14 ticket 06) — a
    server-paginated list (antd-ui: any list that can grow pages
    server-side), so tests read ``data["items"]``, never a bare list."""
    response = client.get("/api/holidays/changes")
    assert response.status_code == 200, response.text
    return response.json()["data"]["items"]


class TestListIsOpenToAnyRole:
    def test_user_can_list(self, user_client: TestClient) -> None:
        response = user_client.get("/api/holidays")
        assert response.status_code == 200, response.text
        assert response.json()["data"] == []


class TestCreateIsAdminOnly:
    def test_user_cannot_create(self, user_client: TestClient) -> None:
        response = user_client.post("/api/holidays", json={"kind": "annual", "name": "New Year", "month": 1, "day": 1})
        assert response.status_code == 403

    def test_admin_can_create_annual(self, admin_client: TestClient) -> None:
        response = admin_client.post("/api/holidays", json={"kind": "annual", "name": "New Year", "month": 1, "day": 1})
        assert response.status_code == 201, response.text
        # M13 issue 03 — the row now rides alongside the stale-file count.
        body = response.json()["data"]["holiday"]
        assert body["kind"] == "annual"
        assert body["month"] == 1
        assert body["day"] == 1
        assert body["date"] is None

    def test_admin_can_create_public(self, admin_client: TestClient) -> None:
        response = admin_client.post(
            "/api/holidays", json={"kind": "public", "name": "Makha Bucha", "date": "2026-02-12"}
        )
        assert response.status_code == 201, response.text
        body = response.json()["data"]["holiday"]
        assert body["kind"] == "public"
        assert body["date"] == "2026-02-12"
        assert body["month"] is None


class Test29FebRefusal:
    def test_29_february_annual_is_refused_on_create(self, admin_client: TestClient) -> None:
        response = admin_client.post("/api/holidays", json={"kind": "annual", "name": "Leap", "month": 2, "day": 29})
        assert response.status_code == 422

    def test_29_february_public_in_a_leap_year_is_fine(self, admin_client: TestClient) -> None:
        response = admin_client.post("/api/holidays", json={"kind": "public", "name": "Leap Day", "date": "2028-02-29"})
        assert response.status_code == 201, response.text


class TestShapeValidation:
    def test_annual_with_a_date_is_refused(self, admin_client: TestClient) -> None:
        response = admin_client.post(
            "/api/holidays", json={"kind": "annual", "name": "Bad", "month": 1, "day": 1, "date": "2026-01-01"}
        )
        assert response.status_code == 422

    def test_public_without_a_date_is_refused(self, admin_client: TestClient) -> None:
        response = admin_client.post("/api/holidays", json={"kind": "public", "name": "Bad"})
        assert response.status_code == 422

    def test_public_with_extraneous_month_day_is_refused(self, admin_client: TestClient) -> None:
        """The symmetric partner of `test_annual_with_a_date_is_refused` —
        `_validate_holiday_shape`'s public branch had no test pinning its
        own `month is not None or day is not None` check."""
        response = admin_client.post(
            "/api/holidays", json={"kind": "public", "name": "Bad", "date": "2026-01-01", "month": 1, "day": 1}
        )
        assert response.status_code == 422


class TestUniqueCollision:
    def test_two_public_holidays_on_the_same_date_is_422_never_500(self, admin_client: TestClient) -> None:
        first = admin_client.post("/api/holidays", json={"kind": "public", "name": "A", "date": "2026-01-01"})
        assert first.status_code == 201

        second = admin_client.post("/api/holidays", json={"kind": "public", "name": "B", "date": "2026-01-01"})
        assert second.status_code == 422


class TestDelete:
    def test_admin_can_delete(self, admin_client: TestClient) -> None:
        created = admin_client.post(
            "/api/holidays", json={"kind": "annual", "name": "New Year", "month": 1, "day": 1}
        ).json()["data"]["holiday"]

        response = admin_client.delete(f"/api/holidays/{created['id']}")
        assert response.status_code == 200

        listing = admin_client.get("/api/holidays").json()["data"]
        assert listing == []


class TestExportImportRoundTrip:
    def test_export_then_import_reproduces_the_same_set(self, admin_client: TestClient) -> None:
        admin_client.post("/api/holidays", json={"kind": "annual", "name": "New Year", "month": 1, "day": 1})
        admin_client.post("/api/holidays", json={"kind": "public", "name": "Makha Bucha", "date": "2026-02-12"})

        exported = admin_client.get("/api/holidays/export")
        assert exported.status_code == 200, exported.text
        document = exported.json()["data"]
        assert document["version"] == 1
        assert len(document["holidays"]) == 2

        imported = admin_client.post("/api/holidays/import", json=document)
        assert imported.status_code == 200, imported.text
        assert len(imported.json()["data"]) == 2

        listing = admin_client.get("/api/holidays").json()["data"]
        assert len(listing) == 2

    def test_import_replaces_the_whole_set(self, admin_client: TestClient) -> None:
        admin_client.post("/api/holidays", json={"kind": "annual", "name": "Old", "month": 5, "day": 5})

        document = {"version": 1, "holidays": [{"kind": "annual", "name": "New Year", "month": 1, "day": 1}]}
        response = admin_client.post("/api/holidays/import", json=document)
        assert response.status_code == 200, response.text

        listing = admin_client.get("/api/holidays").json()["data"]
        assert len(listing) == 1
        assert listing[0]["name"] == "New Year"

    def test_import_user_cannot(self, user_client: TestClient) -> None:
        document = {"version": 1, "holidays": []}
        response = user_client.post("/api/holidays/import", json=document)
        assert response.status_code == 403

    def test_import_with_a_duplicate_key_refuses_the_whole_document(self, admin_client: TestClient) -> None:
        document = {
            "version": 1,
            "holidays": [
                {"kind": "public", "name": "A", "date": "2026-01-01"},
                {"kind": "public", "name": "B", "date": "2026-01-01"},
            ],
        }
        response = admin_client.post("/api/holidays/import", json=document)
        assert response.status_code == 422

        # Refused wholesale — nothing was written.
        listing = admin_client.get("/api/holidays").json()["data"]
        assert listing == []

    def test_import_with_29_february_annual_is_refused(self, admin_client: TestClient) -> None:
        document = {"version": 1, "holidays": [{"kind": "annual", "name": "Bad", "month": 2, "day": 29}]}
        response = admin_client.post("/api/holidays/import", json=document)
        assert response.status_code == 422


class TestHolidayChanges:
    """ADR 0022, M14 ticket 06 — every one of the five ways a Holiday moves
    records exactly one Holiday Change, in the same transaction as the
    mutation, readable by any signed-in role. A refused mutation records
    nothing.
    """

    def test_create_records_one_change_readable_by_a_non_admin(
        self, admin_client: TestClient, user_client: TestClient
    ) -> None:
        response = admin_client.post("/api/holidays", json={"kind": "annual", "name": "New Year", "month": 1, "day": 1})
        assert response.status_code == 201, response.text

        rows = holiday_changes(user_client)
        assert len(rows) == 1
        assert rows[0]["action"] == "add"
        assert rows[0]["username"] == "admin"
        assert rows[0]["holiday_kind"] == "annual"
        assert rows[0]["holiday_month"] == 1
        assert rows[0]["holiday_day"] == 1
        assert rows[0]["count"] is None

    def test_created_at_is_an_aware_utc_instant(self, admin_client: TestClient) -> None:
        """ui-audit ticket 02 — the drawer formats the instant browser-local, so
        the string must carry its offset (`docs/issues/006`)."""
        from datetime import UTC, datetime

        admin_client.post("/api/holidays", json={"kind": "annual", "name": "New Year", "month": 1, "day": 1})

        created_at = datetime.fromisoformat(holiday_changes(admin_client)[0]["created_at"])
        assert created_at.tzinfo is not None
        assert created_at.utcoffset() == UTC.utcoffset(None)

    def test_edit_records_one_change_with_the_new_day(self, admin_client: TestClient) -> None:
        created = admin_client.post(
            "/api/holidays", json={"kind": "annual", "name": "Old", "month": 5, "day": 5}
        ).json()["data"]["holiday"]

        response = admin_client.patch(
            f"/api/holidays/{created['id']}",
            json={"kind": "public", "name": "New", "date": "2026-03-03"},
        )
        assert response.status_code == 200, response.text

        changes = holiday_changes(admin_client)
        edit_rows = [row for row in changes if row["action"] == "edit"]
        assert len(edit_rows) == 1
        assert edit_rows[0]["holiday_kind"] == "public"
        assert edit_rows[0]["holiday_date"] == "2026-03-03"

    def test_delete_records_one_change_with_the_deleted_holidays_day(self, admin_client: TestClient) -> None:
        created = admin_client.post(
            "/api/holidays", json={"kind": "public", "name": "Gone", "date": "2026-04-04"}
        ).json()["data"]["holiday"]

        response = admin_client.delete(f"/api/holidays/{created['id']}")
        assert response.status_code == 200

        changes = holiday_changes(admin_client)
        delete_rows = [row for row in changes if row["action"] == "delete"]
        assert len(delete_rows) == 1
        assert delete_rows[0]["holiday_date"] == "2026-04-04"
        assert delete_rows[0]["holiday_name"] == "Gone"

    def test_json_import_records_one_change_with_the_count_not_one_per_holiday(self, admin_client: TestClient) -> None:
        document = {
            "version": 1,
            "holidays": [
                {"kind": "annual", "name": "A", "month": 1, "day": 1},
                {"kind": "annual", "name": "B", "month": 2, "day": 2},
            ],
        }
        response = admin_client.post("/api/holidays/import", json=document)
        assert response.status_code == 200, response.text

        changes = holiday_changes(admin_client)
        import_rows = [row for row in changes if row["action"] == "import_csv"]
        assert len(import_rows) == 1
        assert import_rows[0]["count"] == 2
        assert import_rows[0]["holiday_name"] is None

    def test_import_from_meter_records_one_change_with_the_count(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        from arichds.acquisition.drivers.base import SpecialDayEntry

        device_id = add_device(admin_client, fake_meter)
        fake_meter.special_days_entries = [
            SpecialDayEntry(index=1, day_id=7, year=None, month=1, day=1),
            SpecialDayEntry(index=2, day_id=9, year=2026, month=3, day=3),
        ]

        response = admin_client.post(f"/api/holidays/import-from-meter?device_id={device_id}")
        assert response.status_code == 200, response.text

        changes = holiday_changes(admin_client)
        import_rows = [row for row in changes if row["action"] == "import_meter"]
        assert len(import_rows) == 1
        assert import_rows[0]["count"] == 2

    @pytest.mark.parametrize(
        ("action", "expected_subject"),
        [
            ("add", "1/1"),
            ("edit", "2026-03-03"),
            ("delete", "2026-04-04"),
            ("import_csv", "1 holiday"),
            ("import_meter", "2 holiday"),
        ],
    )
    def test_each_mutation_writes_exactly_one_app_log_line(
        self,
        action: str,
        expected_subject: str,
        admin_client: TestClient,
        fake_meter: FakeMeterState,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """One parametrized test per mutation path (ADR 0022, M14 ticket 06)
        — covers all five, not just create and JSON import. Setup requests
        (creating the row an edit/delete acts on, adding the device an
        import-from-meter reads) run **before** ``caplog.at_level`` opens, so
        the capture holds only the action under test. Filtered to this
        module's own logger name (``record.name``), so an unrelated INFO
        line elsewhere (httpx's request log, alembic's migration log) cannot
        satisfy a bare substring match by accident, and "exactly one" is
        pinned rather than assumed from ``caplog.text`` alone.
        """
        if action == "edit":
            created = admin_client.post(
                "/api/holidays", json={"kind": "annual", "name": "Old", "month": 5, "day": 5}
            ).json()["data"]["holiday"]
        elif action == "delete":
            created = admin_client.post(
                "/api/holidays", json={"kind": "public", "name": "Gone", "date": "2026-04-04"}
            ).json()["data"]["holiday"]
        elif action == "import_meter":
            from arichds.acquisition.drivers.base import SpecialDayEntry

            device_id = add_device(admin_client, fake_meter)
            fake_meter.special_days_entries = [
                SpecialDayEntry(index=1, day_id=7, year=None, month=1, day=1),
                SpecialDayEntry(index=2, day_id=9, year=2026, month=3, day=3),
            ]

        # The app's own default log level is already INFO, so a setup request
        # above (the create an edit/delete acts on) is captured too unless
        # discarded here — `caplog.at_level` only adjusts the level filter,
        # it does not clear what is already in `caplog.records`.
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="arichds.api.holidays"):
            if action == "add":
                response = admin_client.post(
                    "/api/holidays", json={"kind": "annual", "name": "New Year", "month": 1, "day": 1}
                )
            elif action == "edit":
                response = admin_client.patch(
                    f"/api/holidays/{created['id']}",
                    json={"kind": "public", "name": "New", "date": "2026-03-03"},
                )
            elif action == "delete":
                response = admin_client.delete(f"/api/holidays/{created['id']}")
            elif action == "import_csv":
                document = {"version": 1, "holidays": [{"kind": "annual", "name": "A", "month": 1, "day": 1}]}
                response = admin_client.post("/api/holidays/import", json=document)
            else:
                response = admin_client.post(f"/api/holidays/import-from-meter?device_id={device_id}")

        assert response.status_code in (200, 201), response.text

        records = [record for record in caplog.records if record.name == "arichds.api.holidays"]
        assert len(records) == 1, (
            f"expected exactly one App Log line for {action!r}, got {[r.getMessage() for r in records]}"
        )
        message = records[0].getMessage()
        assert action in message
        assert "admin" in message
        assert expected_subject in message

    def test_changes_are_newest_first(self, admin_client: TestClient) -> None:
        admin_client.post("/api/holidays", json={"kind": "annual", "name": "First", "month": 1, "day": 1})
        admin_client.post("/api/holidays", json={"kind": "annual", "name": "Second", "month": 2, "day": 2})

        changes = holiday_changes(admin_client)
        assert [row["holiday_name"] for row in changes] == ["Second", "First"]

    def test_changes_page_server_side_with_the_unpaged_total(self, admin_client: TestClient) -> None:
        """antd-ui: a list that can grow pages server-side, mirroring
        `GET /api/devices/{id}/events` — `total` is the unpaged count, and
        `limit`/`offset` slice the same newest-first ordering."""
        for month in (1, 2, 3):
            admin_client.post("/api/holidays", json={"kind": "annual", "name": f"H{month}", "month": month, "day": 1})

        first_page = admin_client.get("/api/holidays/changes?limit=2&offset=0").json()["data"]
        assert first_page["total"] == 3
        assert first_page["limit"] == 2
        assert first_page["offset"] == 0
        assert [row["holiday_name"] for row in first_page["items"]] == ["H3", "H2"]

        second_page = admin_client.get("/api/holidays/changes?limit=2&offset=2").json()["data"]
        assert [row["holiday_name"] for row in second_page["items"]] == ["H1"]

    def test_a_refused_collision_on_create_records_nothing(self, admin_client: TestClient) -> None:
        admin_client.post("/api/holidays", json={"kind": "public", "name": "A", "date": "2026-01-01"})
        refused = admin_client.post("/api/holidays", json={"kind": "public", "name": "B", "date": "2026-01-01"})
        assert refused.status_code == 422

        changes = holiday_changes(admin_client)
        assert [row["action"] for row in changes] == ["add"]  # only the first, successful create

    def test_a_refused_29_february_import_from_meter_records_nothing(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        from arichds.acquisition.drivers.base import SpecialDayEntry

        device_id = add_device(admin_client, fake_meter)
        fake_meter.special_days_entries = [SpecialDayEntry(index=1, day_id=1, year=None, month=2, day=29)]

        response = admin_client.post(f"/api/holidays/import-from-meter?device_id={device_id}")
        assert response.status_code == 422

        assert holiday_changes(admin_client) == []

    def test_a_commit_failure_leaves_neither_the_holiday_nor_its_change_record(
        self, admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed commit persists nothing, with a **real injected
        failure**, not by reading the code: if ``session.commit()`` blows up
        after both rows were staged, neither survives.

        This does **not** by itself prove the two rows share one
        transaction — a version of ``create_holiday`` split into two
        separate commits would still pass here, because the *first* commit
        already raises before the second is ever reached.
        :func:`test_a_change_record_write_failure_rolls_back_the_holiday_too`
        below is the test that proves the shared transaction: it fails a
        write that happens *before* the (first and only) commit, so a
        two-commit version would let the Holiday row survive and that test
        would catch it.
        """
        from sqlalchemy.orm import Session

        original_commit = Session.commit

        def boom(self: Session) -> None:
            raise RuntimeError("simulated commit failure")

        monkeypatch.setattr(Session, "commit", boom)
        try:
            with pytest.raises(RuntimeError, match="simulated commit failure"):
                admin_client.post("/api/holidays", json={"kind": "annual", "name": "Boom", "month": 6, "day": 6})
        finally:
            monkeypatch.setattr(Session, "commit", original_commit)

        assert admin_client.get("/api/holidays").json()["data"] == []
        assert holiday_changes(admin_client) == []

    def test_a_change_record_write_failure_rolls_back_the_holiday_too(
        self, admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other direction of the same proof: if building the Holiday
        Change row itself blows up — before ``session.commit()`` is ever
        reached — the already-flushed Holiday row must not survive either.
        A version that committed the Holiday in its own transaction before
        attempting the change record would fail this."""
        import arichds.db.models as models_module

        original_init = models_module.HolidayChange.__init__

        def boom(self: object, *args: object, **kwargs: object) -> None:
            raise RuntimeError("simulated change-record failure")

        monkeypatch.setattr(models_module.HolidayChange, "__init__", boom)
        try:
            with pytest.raises(RuntimeError, match="simulated change-record failure"):
                admin_client.post("/api/holidays", json={"kind": "annual", "name": "Boom2", "month": 7, "day": 7})
        finally:
            monkeypatch.setattr(models_module.HolidayChange, "__init__", original_init)

        assert admin_client.get("/api/holidays").json()["data"] == []


class TestImportFromMeter:
    def test_replaces_the_whole_set_and_deduplicates(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        from arichds.acquisition.drivers.base import SpecialDayEntry

        device_id = add_device(admin_client, fake_meter)
        admin_client.post("/api/holidays", json={"kind": "annual", "name": "Old", "month": 5, "day": 5})

        fake_meter.special_days_entries = [
            SpecialDayEntry(index=1, day_id=7, year=None, month=1, day=1),
            SpecialDayEntry(index=2, day_id=7, year=None, month=1, day=1),  # duplicate key -> skipped
            SpecialDayEntry(index=3, day_id=9, year=2026, month=3, day=3),
        ]

        response = admin_client.post(f"/api/holidays/import-from-meter?device_id={device_id}")
        assert response.status_code == 200, response.text
        body = response.json()["data"]
        assert body["skipped"] == 1
        assert len(body["imported"]) == 2
        assert {row["name"] for row in body["imported"]} == {"Meter day ID 7", "Meter day ID 9"}

        listing = admin_client.get("/api/holidays").json()["data"]
        assert len(listing) == 2  # "Old" is gone — replace-the-whole-set

    def test_a_29_february_annual_entry_refuses_the_whole_import(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        from arichds.acquisition.drivers.base import SpecialDayEntry

        device_id = add_device(admin_client, fake_meter)
        admin_client.post("/api/holidays", json={"kind": "annual", "name": "Kept", "month": 5, "day": 5})
        fake_meter.special_days_entries = [SpecialDayEntry(index=1, day_id=1, year=None, month=2, day=29)]

        response = admin_client.post(f"/api/holidays/import-from-meter?device_id={device_id}")
        assert response.status_code == 422

        listing = admin_client.get("/api/holidays").json()["data"]
        assert len(listing) == 1
        assert listing[0]["name"] == "Kept"  # untouched — the whole import was refused

    def test_a_device_with_no_special_days_table_is_404(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.meter_serial = "SN-2"
        response = admin_client.post(
            "/api/devices",
            json={
                **DEVICE,
                "brand": "cewe",
                "model": "prometer100",
                "meter_activation_code": mint_meter_activation_code(meter_serial="SN-2"),
            },
        )
        assert response.status_code == 201, response.text
        device_id = response.json()["data"]["id"]

        result = admin_client.post(f"/api/holidays/import-from-meter?device_id={device_id}")
        assert result.status_code == 404

    def test_user_cannot_import_from_meter(
        self, user_client: TestClient, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        response = user_client.post(f"/api/holidays/import-from-meter?device_id={device_id}")
        assert response.status_code == 403

    def test_an_unknown_device_is_404_not_500(self, admin_client: TestClient) -> None:
        """Error-path audit finding: the job function raises `ValueError`
        for a missing device, which the router must translate to 404 —
        never let propagate into an unhandled 500."""
        response = admin_client.post("/api/holidays/import-from-meter?device_id=999")
        assert response.status_code == 404
