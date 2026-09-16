"""The All-Meters View — every meter's latest closed period on one screen
(`.scratch/capture-billing-energy/issues/01-all-meters-view.md`).

Mirrors ``test_api_billing.py``: the same HTTP seam, the same shared test
clients, the same ``add_device``/``seed_closed`` helper shapes. No new seam.

**Why this is its own module rather than more classes in
``test_api_billing.py``:** that module tests the paged list endpoint, whose
whole shape — a required ``status``, an optional device, an optional range,
paging — this endpoint deliberately does not have.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import mint_meter_activation_code
from fakes import FakeMeterState
from fastapi.testclient import TestClient
from sqlalchemy import select

from arichds.constants import BILLING_BEHIND_DAYS

pytestmark = pytest.mark.usefixtures("fake_meter")

DEVICE = {
    "name": "Main Incomer",
    "brand": "mitsu",
    "model": "smw110",
    "site_name": "Plant A",
    "transport": {"kind": "net", "host": "127.0.0.1", "port": 4059},
    "password": "hunter2",
}

#: "Now" for every case here — the real clock, read once at import.
#:
#: Every seeded ``bill_date`` is an offset from this, for two reasons. The
#: boundary cases move with :data:`~arichds.constants.BILLING_BEHIND_DAYS`
#: rather than being pinned to a literal date that would quietly stop testing
#: the boundary if the constant changed. And the endpoint deliberately takes
#: **no** ``now`` parameter — no endpoint in this API does, and adding public
#: query-string surface only a test would ever set is not worth a frozen
#: clock. Every offset here is at least an hour clear of a threshold, so the
#: seconds between this line and the request cannot decide an assertion.
NOW = datetime.now(UTC)


def add_device(
    client: TestClient,
    fake_meter: FakeMeterState,
    *,
    serial: str = "SN-1",
    name: str = "Main Incomer",
    **overrides: object,
) -> int:
    fake_meter.meter_serial = serial
    payload = {**DEVICE, "name": name, **overrides}
    payload.setdefault("meter_activation_code", mint_meter_activation_code(meter_serial=serial))
    response = client.post("/api/devices", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def seed_closed(device_id: int, bill_date: datetime, *, read_at: datetime | None = None, **columns: float) -> None:
    from arichds.db.models import BillingReading
    from arichds.db.session import session_scope

    with session_scope() as session:
        session.add(
            BillingReading(
                device_id=device_id,
                bill_date=bill_date,
                read_at=bill_date if read_at is None else read_at,
                record_status=None,
                source="dlms",
                meter_serial="1232002893",
                **columns,
            )
        )


def seed_open(device_id: int, bill_date: datetime) -> None:
    from arichds.db.models import BillingReading
    from arichds.db.session import session_scope

    with session_scope() as session:
        session.add(
            BillingReading(
                device_id=device_id,
                bill_date=bill_date,
                read_at=bill_date,
                record_status="open",
                source="dlms",
                meter_serial="1232002893",
            )
        )


def set_liveness(device_id: int, *, status: str, consecutive_failures: int = 0) -> None:
    """Write what a read last proved about this device, through the store —
    the same two columns ``acquisition/status.py`` writes."""
    from arichds.db.models import Device
    from arichds.db.session import session_scope

    with session_scope() as session:
        device = session.get(Device, device_id)
        assert device is not None
        device.status = status
        device.consecutive_failures = consecutive_failures


def set_capture_dir(value: str) -> None:
    from arichds.db.app_settings import CAPTURE_DIR_KEY, set_setting
    from arichds.db.session import session_scope

    with session_scope() as session:
        set_setting(session, CAPTURE_DIR_KEY, value)


def fetch(client: TestClient):
    return client.get("/api/billing/all-meters")


def rows(client: TestClient) -> list[dict]:
    response = fetch(client)
    assert response.status_code == 200, response.text
    return response.json()["data"]["items"]


class TestTheRowSetComesFromDevices:
    def test_a_device_that_has_never_billed_still_appears(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """The case the tab exists to surface. Building the row set from
        ``billing_readings`` would drop this device entirely."""
        device_id = add_device(admin_client, fake_meter)

        items = rows(admin_client)

        assert [row["device_id"] for row in items] == [device_id]
        assert items[0]["bill_date"] is None
        assert items[0]["status"] == "never_billed"

    def test_one_row_per_device_however_many_periods_it_has(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, NOW - timedelta(days=1))
        seed_closed(device_id, NOW - timedelta(days=32))
        seed_closed(device_id, NOW - timedelta(days=63))

        items = rows(admin_client)

        assert len(items) == 1

    def test_the_row_carries_the_latest_closed_period_not_the_oldest(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, NOW - timedelta(days=63), import_active_kwh_total=100.0)
        seed_closed(device_id, NOW - timedelta(days=1), import_active_kwh_total=300.0)
        seed_closed(device_id, NOW - timedelta(days=32), import_active_kwh_total=200.0)

        items = rows(admin_client)

        assert items[0]["bill_date"].startswith((NOW - timedelta(days=1)).strftime("%Y-%m-%d"))
        assert items[0]["import_active_kwh_total"] == 300.0

    def test_the_open_period_never_appears_even_when_it_is_the_newest_row(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """ADR 0018 — the Open Period's ``bill_date`` advances on every read,
        so letting it in would make every meter look freshly cut and destroy
        the staleness signal the Status column is."""
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, NOW - timedelta(days=40), import_active_kwh_total=100.0)
        seed_open(device_id, NOW)

        items = rows(admin_client)

        assert items[0]["bill_date"].startswith((NOW - timedelta(days=40)).strftime("%Y-%m-%d"))
        assert items[0]["import_active_kwh_total"] == 100.0
        assert items[0]["status"] == "behind"

    def test_a_device_whose_only_period_is_open_reads_as_never_billed(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_open(device_id, NOW)

        items = rows(admin_client)

        assert items[0]["bill_date"] is None
        assert items[0]["status"] == "never_billed"


class TestBehindIsTheNamedConstant:
    def test_the_threshold_is_thirty_five_days(self) -> None:
        """The assumption written into this number: **no customer runs a
        billing cycle longer than a month.** A quarterly cycle would report
        every healthy meter as Behind, and this constant is where it breaks."""
        assert BILLING_BEHIND_DAYS == 35

    def test_a_bill_date_just_inside_the_threshold_is_ok(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, NOW - timedelta(days=BILLING_BEHIND_DAYS) + timedelta(hours=1))

        items = rows(admin_client)

        assert items[0]["status"] == "ok"
        assert items[0]["status_value"] is None

    def test_a_bill_date_just_outside_the_threshold_is_behind(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, NOW - timedelta(days=BILLING_BEHIND_DAYS) - timedelta(hours=1))

        items = rows(admin_client)

        assert items[0]["status"] == "behind"

    def test_the_behind_chip_carries_how_many_days_behind(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, NOW - timedelta(days=50))

        items = rows(admin_client)

        assert items[0]["status"] == "behind"
        assert items[0]["status_value"] == 50


class TestStatusPrecedence:
    def test_unreachable_outranks_behind(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """Cause outranks symptom — an unreachable meter is also a behind
        meter, and the operator's action is to fix the connection."""
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, NOW - timedelta(days=90))
        set_liveness(device_id, status="offline", consecutive_failures=7)

        items = rows(admin_client)

        assert items[0]["status"] == "not_answering"
        assert items[0]["status_value"] == 7

    def test_unreachable_outranks_never_billed(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)
        set_liveness(device_id, status="offline", consecutive_failures=3)

        items = rows(admin_client)

        assert items[0]["status"] == "not_answering"

    def test_paused_outranks_unreachable(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """A paused device reports paused, not broken — nobody is reading it,
        so its stored status stopped being current the moment it was paused
        (``acquisition/status.py``'s own rule)."""
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, NOW - timedelta(days=90))
        set_liveness(device_id, status="offline", consecutive_failures=9)
        assert admin_client.post(f"/api/devices/{device_id}/pause").status_code == 200

        items = rows(admin_client)

        assert items[0]["status"] == "paused"

    def test_a_device_never_read_yet_is_never_billed_not_unreachable(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """``unknown`` means nothing has read it, which is not the claim "it
        did not answer" — a freshly added meter must not be reported as a
        connection fault."""
        device_id = add_device(admin_client, fake_meter)
        set_liveness(device_id, status="unknown")

        items = rows(admin_client)

        assert items[0]["status"] == "never_billed"


class TestTheAttentionCount:
    def test_it_counts_rows_that_are_neither_ok_nor_paused(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        healthy = add_device(admin_client, fake_meter, serial="SN-OK", name="A Healthy")
        seed_closed(healthy, NOW - timedelta(days=2))

        behind = add_device(admin_client, fake_meter, serial="SN-BEHIND", name="B Behind")
        seed_closed(behind, NOW - timedelta(days=60))

        add_device(admin_client, fake_meter, serial="SN-NEVER", name="C Never")

        offline = add_device(admin_client, fake_meter, serial="SN-OFF", name="D Offline")
        seed_closed(offline, NOW - timedelta(days=2))
        set_liveness(offline, status="offline", consecutive_failures=4)

        paused = add_device(admin_client, fake_meter, serial="SN-PAUSE", name="E Paused")
        seed_closed(paused, NOW - timedelta(days=200))
        admin_client.post(f"/api/devices/{paused}/pause")

        response = fetch(admin_client)

        assert response.status_code == 200, response.text
        assert response.json()["data"]["needs_attention"] == 3

    def test_a_paused_device_is_excluded_even_though_it_is_badly_behind(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        paused = add_device(admin_client, fake_meter, serial="SN-PAUSE", name="Paused")
        seed_closed(paused, NOW - timedelta(days=400))
        admin_client.post(f"/api/devices/{paused}/pause")

        response = fetch(admin_client)

        assert response.json()["data"]["needs_attention"] == 0

    def test_an_empty_system_needs_no_attention(self, admin_client: TestClient) -> None:
        response = fetch(admin_client)

        assert response.status_code == 200, response.text
        assert response.json()["data"] == {
            "items": [],
            "needs_attention": 0,
            "total_devices": 0,
            "devices_with_issues": 0,
            "complete": 0,
            "auto_interval_sec": 900,
            "auto_last_cycle_at": None,
        }


class TestOrdering:
    def test_worst_status_first_then_device_name(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """Three rows in three distinct statuses — two would leave several
        wrong orderings indistinguishable from the right one.

        The names are deliberately alphabetically **opposite** to the intended
        order, so a sort that ignores status and orders by name alone comes
        out exactly reversed rather than accidentally right.
        """
        ok = add_device(admin_client, fake_meter, serial="SN-A", name="A Fine")
        seed_closed(ok, NOW - timedelta(days=2))

        behind = add_device(admin_client, fake_meter, serial="SN-B", name="B Behind")
        seed_closed(behind, NOW - timedelta(days=60))

        offline = add_device(admin_client, fake_meter, serial="SN-C", name="C Offline")
        seed_closed(offline, NOW - timedelta(days=2))
        set_liveness(offline, status="offline", consecutive_failures=4)

        items = rows(admin_client)

        assert [row["status"] for row in items] == ["not_answering", "behind", "ok"]
        assert [row["device_name"] for row in items] == ["C Offline", "B Behind", "A Fine"]

    def test_never_billed_and_behind_both_outrank_ok(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        ok = add_device(admin_client, fake_meter, serial="SN-A", name="A Fine")
        seed_closed(ok, NOW - timedelta(days=2))
        behind = add_device(admin_client, fake_meter, serial="SN-B", name="B Behind")
        seed_closed(behind, NOW - timedelta(days=60))
        add_device(admin_client, fake_meter, serial="SN-C", name="C Never")

        items = rows(admin_client)

        assert items[-1]["status"] == "ok"
        assert {row["status"] for row in items[:2]} == {"behind", "never_billed"}

    def test_paused_sorts_below_ok(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """Paused is not a problem — it is a deliberate operator state, and it
        is excluded from the attention counter. Sorting it above real problems
        would push the counted rows below rows nobody needs to act on."""
        ok = add_device(admin_client, fake_meter, serial="SN-A", name="A Fine")
        seed_closed(ok, NOW - timedelta(days=2))

        paused = add_device(admin_client, fake_meter, serial="SN-Z", name="Z Paused")
        seed_closed(paused, NOW - timedelta(days=400))
        admin_client.post(f"/api/devices/{paused}/pause")

        items = rows(admin_client)

        assert [row["status"] for row in items] == ["ok", "paused"]

    def test_two_rows_of_the_same_status_order_by_device_name(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        second = add_device(admin_client, fake_meter, serial="SN-2", name="Zulu")
        seed_closed(second, NOW - timedelta(days=2))
        first = add_device(admin_client, fake_meter, serial="SN-1", name="Alpha")
        seed_closed(first, NOW - timedelta(days=2))

        items = rows(admin_client)

        assert [row["device_name"] for row in items] == ["Alpha", "Zulu"]


class TestTheToolbarCounters:
    """ui-audit ticket 10 — Total / Devices with Issues / Complete come from the
    same rows the tab shows, and always sum."""

    @pytest.fixture(autouse=True)
    def _forget_the_change_check(self):
        from arichds.acquisition.billing import reset_billing_change_check

        reset_billing_change_check()
        yield
        reset_billing_change_check()

    def test_one_behind_and_one_never_billed_count_two_issues(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        ok = add_device(admin_client, fake_meter, serial="SN-OK", name="Fine")
        seed_closed(ok, NOW - timedelta(days=2))
        behind = add_device(admin_client, fake_meter, serial="SN-B", name="Behind")
        seed_closed(behind, NOW - timedelta(days=400))
        add_device(admin_client, fake_meter, serial="SN-N", name="Never")

        data = fetch(admin_client).json()["data"]

        assert data["total_devices"] == 3
        assert data["devices_with_issues"] == 2
        assert data["complete"] == 1
        assert {row["status"] for row in data["items"]} == {"ok", "behind", "never_billed"}

    def test_a_paused_meter_is_an_issue_for_the_strip_even_though_it_needs_no_attention(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        paused = add_device(admin_client, fake_meter, serial="SN-P", name="Paused")
        seed_closed(paused, NOW - timedelta(days=2))
        admin_client.post(f"/api/devices/{paused}/pause")

        data = fetch(admin_client).json()["data"]

        assert data["needs_attention"] == 0
        assert (data["total_devices"], data["devices_with_issues"], data["complete"]) == (1, 1, 0)

    def test_auto_reads_none_until_the_change_check_has_run_then_its_instant(self, admin_client: TestClient) -> None:
        from arichds.acquisition.billing import mark_billing_change_check

        assert fetch(admin_client).json()["data"]["auto_last_cycle_at"] is None

        mark_billing_change_check(NOW)
        data = fetch(admin_client).json()["data"]

        assert datetime.fromisoformat(data["auto_last_cycle_at"]) == NOW
        assert data["auto_interval_sec"] == 900


class TestTheCaptureTimeColumn:
    """`captured_at` is the stored stamp the capture writers set when a
    document is actually written (ui-audit ticket 03) — never `read_at`, and
    never inferred from the capture folder being configured."""

    def test_a_period_read_but_never_captured_is_blank_even_with_a_capture_folder(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, NOW - timedelta(days=1), read_at=NOW - timedelta(days=1, hours=3))
        set_capture_dir("C:/Captures")

        items = rows(admin_client)

        assert items[0]["captured_at"] is None

    def test_it_is_the_stored_capture_stamp(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        from arichds.db.models import BillingReading
        from arichds.db.session import session_scope

        device_id = add_device(admin_client, fake_meter)
        seed_closed(device_id, NOW - timedelta(days=1), read_at=NOW - timedelta(days=1, hours=3))
        captured_at = NOW - timedelta(hours=2)
        with session_scope() as session:
            row = session.scalars(select(BillingReading).where(BillingReading.device_id == device_id)).one()
            row.captured_at = captured_at

        items = rows(admin_client)

        assert items[0]["captured_at"] is not None
        assert items[0]["captured_at"].startswith(captured_at.strftime("%Y-%m-%dT%H:%M"))

    def test_it_is_blank_for_a_device_that_has_never_billed(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        add_device(admin_client, fake_meter)
        set_capture_dir("C:/Captures")

        items = rows(admin_client)

        assert items[0]["captured_at"] is None


class TestAccess:
    def test_any_authenticated_role_may_read_it(
        self, user_client: TestClient, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        add_device(admin_client, fake_meter)

        assert fetch(user_client).status_code == 200

    def test_it_refuses_an_anonymous_caller(self, anon_client: TestClient) -> None:
        assert fetch(anon_client).status_code == 401

    def test_it_is_gated_by_the_billing_entitlement(
        self, admin_client: TestClient, fake_meter: FakeMeterState, relicense
    ) -> None:
        add_device(admin_client, fake_meter)
        relicense(admin_client, features=["load_profile"])

        assert fetch(admin_client).status_code == 403


class TestTheQueryIsReusableWithoutHttp:
    def test_the_database_layer_answers_the_same_row_set(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """The planned billing export needs "latest closed period per device"
        and must call this directly rather than issue HTTP against its own
        process."""
        from arichds.db.billing_query import latest_closed_per_device
        from arichds.db.session import session_scope

        billed = add_device(admin_client, fake_meter, serial="SN-1", name="Billed")
        seed_closed(billed, NOW - timedelta(days=63), import_active_kwh_total=100.0)
        seed_closed(billed, NOW - timedelta(days=1), import_active_kwh_total=300.0)
        seed_open(billed, NOW)
        never = add_device(admin_client, fake_meter, serial="SN-2", name="Never")

        with session_scope() as session:
            pairs = {device.id: reading for device, reading in session.execute(latest_closed_per_device()).all()}

            assert set(pairs) == {billed, never}
            assert pairs[never] is None
            assert pairs[billed] is not None
            assert pairs[billed].import_active_kwh_total == 300.0
