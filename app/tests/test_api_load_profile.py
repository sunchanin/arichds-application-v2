"""Load Profile API — reading a device's stored Interval Readings (M5b-1).

The writer (#15) and the scheduler job (#16) already fill
``load_profile_readings``; this file covers the *reader* — the paged
``GET /api/load-profile`` the Load Profile page calls.

Three rules decide almost every assertion here:

* **The range is half-open** ``[start, end)`` — v1's own bounds
  (``cewe-worker/src/load_profile/repository.py:237-238``), which removes the
  "does 23:59:59.999 include the last row" question entirely.
* **D7** (``api/devices.py``) — a *client* fault gets an HTTP status. An unknown
  device is a 404 and an inverted range is a 422; a device that simply has no
  rows in the window is **not** an error, it is an empty page.
* **Owner ruling, 2026-08-11** — Logger 1 and Logger 2 merge into one row on
  this endpoint (read side only; storage keeps both as separate rows, ADR
  0008). Logger 1 is the spine, Logger 2 is left-joined on an exact
  ``read_at`` match, and every measurement column is
  ``COALESCE(logger1, logger2)`` — Logger 1 wins. ``logger_id`` is gone from
  the response.

``fake_meter`` swaps the driver registry for every test in this module, so
nothing here touches a real meter: devices are created through the real
probe-first API and their readings are seeded straight into the table.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fakes import FakeMeterState
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("fake_meter")

DEVICE = {
    "name": "Main Incomer",
    "brand": "cewe",
    "model": "prometer100",
    "site_name": "Plant A",
    "transport": {"kind": "net", "host": "127.0.0.1", "port": 4059},
    "password": "hunter2",
}

#: The instant every seeded row is offset from, so expected timestamps are
#: computable rather than "whatever now was".
BASE = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def add_device(client: TestClient, fake_meter: FakeMeterState, *, serial: str = "SN-1", **overrides: object) -> int:
    """Create a device through the real API and return its id."""
    fake_meter.meter_serial = serial
    response = client.post("/api/devices", json={**DEVICE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def seed(device_id: int, read_at: datetime, *, logger_id: int = 1, **columns: float) -> None:
    """Write one Interval Reading straight into the table.

    Follows ``test_api_devices.py``'s ``write_readings`` — a Session rather than
    an endpoint, because nothing in the API writes readings. Measurement columns
    not named in *columns* are left unset, which is exactly the state the only
    model in service leaves five of the twelve in.
    """
    from arichds.db.models import LoadProfileReading
    from arichds.db.session import session_scope

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


def seed_series(device_id: int, count: int, *, start: datetime = BASE, step_min: int = 15) -> list[datetime]:
    """Seed *count* rows at *step_min* apart from *start*, returning their times.

    ``(device_id, logger_id, read_at)`` is unique, so the timestamps must be
    distinct or the rows collapse into one.
    """
    times = [start + timedelta(minutes=step_min * index) for index in range(count)]
    for index, read_at in enumerate(times):
        seed(device_id, read_at, import_active_kwh=100.0 + index)
    return times


def fetch(client: TestClient, device_id: int, start: datetime, end: datetime, **params: object):
    """Call the endpoint with an ISO range."""
    query = {
        "device_id": device_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        **params,
    }
    return client.get("/api/load-profile", params=query)


def times_of(body: dict) -> list[datetime]:
    """The ``read_at`` values of a response page, in the order returned.

    Parsed rather than string-compared so the assertion pins the *instant*, not
    the spelling of the offset — but parsed **without** forcing a timezone, so a
    handler that let SQLite's naive datetime through would still fail: a naive
    result never equals an aware expectation.
    """
    return [datetime.fromisoformat(row["read_at"]) for row in body["data"]["items"]]


class TestRange:
    def test_returns_the_rows_in_range_newest_first(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)
        times = seed_series(device_id, 3)

        response = fetch(admin_client, device_id, BASE - timedelta(days=1), BASE + timedelta(days=1))

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is True
        assert times_of(body) == list(reversed(times))
        assert body["data"]["total"] == 3

    def test_the_range_is_half_open_start_included_end_excluded(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """``[start, end)`` — the row *at* ``start`` is in, the one at ``end`` is out."""
        device_id = add_device(admin_client, fake_meter)
        first, second, third = seed_series(device_id, 3)

        response = fetch(admin_client, device_id, second, third)

        assert response.status_code == 200, response.text
        body = response.json()
        assert times_of(body) == [second]
        assert body["data"]["total"] == 1
        assert first not in times_of(body)


class TestEmptyIsNotAnError:
    def test_a_range_with_no_rows_is_an_empty_page(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_series(device_id, 3)

        response = fetch(admin_client, device_id, BASE - timedelta(days=9), BASE - timedelta(days=8))

        assert response.status_code == 200, response.text
        assert response.json()["data"]["items"] == []
        assert response.json()["data"]["total"] == 0

    def test_a_device_that_has_never_been_read_is_an_empty_page(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)

        response = fetch(admin_client, device_id, BASE, BASE + timedelta(days=1))

        assert response.status_code == 200, response.text
        assert response.json()["data"]["items"] == []
        assert response.json()["data"]["total"] == 0


class TestClientFaults:
    def test_an_unknown_device_is_404(self, admin_client: TestClient) -> None:
        """D7 — the caller named something that does not exist; that is their fault."""
        response = fetch(admin_client, 4242, BASE, BASE + timedelta(days=1))

        assert response.status_code == 404, response.text

    def test_an_inverted_range_is_422(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)

        response = fetch(admin_client, device_id, BASE + timedelta(days=1), BASE)

        assert response.status_code == 422, response.text

    def test_an_empty_range_is_422(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """``end == start`` selects nothing under a half-open bound — say so, don't pretend."""
        device_id = add_device(admin_client, fake_meter)

        response = fetch(admin_client, device_id, BASE, BASE)

        assert response.status_code == 422, response.text

    def test_a_limit_above_the_cap_is_422(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """No caller may ask for the whole table."""
        device_id = add_device(admin_client, fake_meter)

        response = fetch(admin_client, device_id, BASE, BASE + timedelta(days=1), limit=501)

        assert response.status_code == 422, response.text


class TestPaging:
    def test_the_default_page_is_a_hundred_rows_of_a_larger_total(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed_series(device_id, 250)

        response = fetch(admin_client, device_id, BASE, BASE + timedelta(days=30))

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert len(data["items"]) == 100
        assert data["total"] == 250
        assert data["limit"] == 100
        assert data["offset"] == 0

    def test_an_offset_page_returns_exactly_the_rows_it_skipped_to(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """Rows 11-20 of the newest-first order — asserted by timestamp, not by count."""
        device_id = add_device(admin_client, fake_meter)
        times = seed_series(device_id, 30)
        newest_first = list(reversed(times))

        response = fetch(admin_client, device_id, BASE, BASE + timedelta(days=30), limit=10, offset=10)

        assert response.status_code == 200, response.text
        assert times_of(response.json()) == newest_first[10:20]
        assert response.json()["data"]["total"] == 30


#: The five of the twelve columns an SMW110W4 never fills. Four are the ones
#: SPEC §3.5 lists as "added at M4c"; ``freq`` is the fifth, and it is easy to
#: miss — the driver's own docstring (``smw110.py``) records that this model's
#: load profile has no frequency column at all.
UNSOURCED_ON_SMW110 = (
    "import_reactive_kvarh",
    "export_active_kwh",
    "export_reactive_kvarh",
    "avg_geo_pf",
    "freq",
)


class TestColumns:
    def test_unsourced_columns_arrive_as_null_and_are_still_present(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """``null``, not ``0`` and not missing — the page renders an em dash off this.

        A dropped key would make the frontend read ``undefined``, and a ``0``
        would render as a real measurement of zero. Both are wrong, and only
        asserting *both* halves catches both.
        """
        device_id = add_device(admin_client, fake_meter)
        seed(
            device_id,
            BASE,
            import_active_kwh=1234.5,
            volt_l1=230.1,
            volt_l2=230.2,
            volt_l3=230.3,
            current_l1=5.1,
            current_l2=5.2,
            current_l3=5.3,
        )

        response = fetch(admin_client, device_id, BASE, BASE + timedelta(days=1))

        assert response.status_code == 200, response.text
        row = response.json()["data"]["items"][0]
        for column in UNSOURCED_ON_SMW110:
            assert column in row, f"{column} must be present, not dropped"
            assert row[column] is None, f"{column} must be null, not {row[column]!r}"
        # The seven the meter does fill still arrive as numbers.
        assert row["import_active_kwh"] == 1234.5
        assert row["volt_l1"] == 230.1
        assert row["current_l3"] == 5.3

    def test_a_genuine_zero_is_not_confused_with_an_absent_column(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """A meter reading exactly 0 A must arrive as ``0.0``, never as ``null``."""
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, BASE, current_l1=0.0, import_active_kwh=0.0)

        response = fetch(admin_client, device_id, BASE, BASE + timedelta(days=1))

        row = response.json()["data"]["items"][0]
        assert row["current_l1"] == 0.0
        assert row["current_l1"] is not None
        assert row["import_active_kwh"] == 0.0

    def test_the_row_carries_nothing_the_page_does_not_render(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """``source``, ``interval_sec`` and ``id`` are not part of this contract (D4)."""
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, BASE, import_active_kwh=1.0)

        response = fetch(admin_client, device_id, BASE, BASE + timedelta(days=1))

        row = response.json()["data"]["items"][0]
        assert set(row) == {"read_at", *UNSOURCED_ON_SMW110} | {
            "import_active_kwh",
            "volt_l1",
            "volt_l2",
            "volt_l3",
            "current_l1",
            "current_l2",
            "current_l3",
        }


class TestIsolation:
    def test_another_devices_rows_never_appear(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        mine = add_device(admin_client, fake_meter, serial="SN-1")
        theirs = add_device(
            admin_client, fake_meter, serial="SN-2", name="Other", transport={**DEVICE["transport"], "port": 4060}
        )  # type: ignore[dict-item]
        my_times = seed_series(mine, 2)
        seed_series(theirs, 5)

        response = fetch(admin_client, mine, BASE, BASE + timedelta(days=1))

        assert response.status_code == 200, response.text
        assert times_of(response.json()) == list(reversed(my_times))
        assert response.json()["data"]["total"] == 2


class TestLoggerMerge:
    """Owner ruling, 2026-08-11 — Logger 1 and Logger 2 merge on this endpoint,
    read side only. v1's own rule, reproduced exactly: Logger 1 is the spine,
    Logger 2 is left-joined on an *exact* ``read_at`` match, and every column
    is ``COALESCE(logger1, logger2)`` — Logger 1 wins.
    """

    def test_logger_2_fills_a_column_logger_1_left_null(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, BASE, logger_id=1, import_active_kwh=11.0)
        seed(device_id, BASE, logger_id=2, volt_l1=230.5)

        response = fetch(admin_client, device_id, BASE, BASE + timedelta(days=1))

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["total"] == 1
        row = data["items"][0]
        assert row["import_active_kwh"] == 11.0
        assert row["volt_l1"] == 230.5

    def test_logger_1_wins_when_both_loggers_fill_the_same_column(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """Premier 550's own collision
        (``docs/meter-notes/load-profile-capture-objects.md:35-53``) — two
        different OBIS map onto one column; ``COALESCE`` must resolve it to
        Logger 1's value deterministically, never Logger 2's.
        """
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, BASE, logger_id=1, import_active_kwh=11.0)
        seed(device_id, BASE, logger_id=2, import_active_kwh=22.0)

        response = fetch(admin_client, device_id, BASE, BASE + timedelta(days=1))

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["import_active_kwh"] == 11.0

    def test_a_logger_2_row_with_no_exact_read_at_match_is_dropped(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """Prometer 100's own case — Logger 2 at 300s lands on a Logger 1
        (900s) boundary only one time in three.
        """
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, BASE, logger_id=1, import_active_kwh=11.0)
        seed(device_id, BASE + timedelta(minutes=5), logger_id=2, import_active_kwh=99.0)

        response = fetch(admin_client, device_id, BASE, BASE + timedelta(days=1))

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["import_active_kwh"] == 11.0

    def test_a_logger_2_only_instant_shows_nothing(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """Logger 1 is the spine — an instant with no Logger 1 row shows
        nothing at all, even though Logger 2 recorded one.
        """
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, BASE, logger_id=2, import_active_kwh=99.0)

        response = fetch(admin_client, device_id, BASE, BASE + timedelta(days=1))

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["total"] == 0
        assert data["items"] == []


class TestAccess:
    def test_an_anonymous_caller_is_refused(self, anon_client: TestClient) -> None:
        response = fetch(anon_client, 1, BASE, BASE + timedelta(days=1))

        assert response.status_code == 401, response.text

    def test_a_plain_user_may_read(
        self, user_client: TestClient, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """Reading device data is open to any authenticated role (D12)."""
        device_id = add_device(admin_client, fake_meter)
        times = seed_series(device_id, 2)

        response = fetch(user_client, device_id, BASE, BASE + timedelta(days=1))

        assert response.status_code == 200, response.text
        assert times_of(response.json()) == list(reversed(times))
