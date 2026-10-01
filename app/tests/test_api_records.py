"""Records API — is the stored load-profile data complete? (M5b-2)

``GET /api/records`` answers one question per ``(meter, logger, local day)``:
how many Interval Readings are stored against how many the meter's own capture
period says there should be. Four rules decide almost every assertion here:

* **A complete day is ``86400 // interval_sec``, read off the stored rows** —
  never the constant 96 (SPEC §3.5: *"ห้ามสมมติว่า capture period คือ 900 วิ"*,
  and §3.5's Records paragraph naming 96 = 86400÷900 as that same forbidden
  assumption). A Prometer 100's Logger 2 runs at 300 s, so its complete day is
  **288**.
* **Completeness is per logger, not per device.** That same Prometer 100 runs
  Logger 1 at 900 s and Logger 2 at 300 s *at the same time*, so a per-device
  grouping would find two periods on every single day and flag every day as a
  period change forever.
* **Every ``(row, date)`` pair gets an explicit cell.** A day with no rows is
  ``missing`` with a null ``expected`` — genuinely distinct from ``short``,
  because with no rows there is no capture period to compute an expectation
  from.
* **The counts are computed live.** There is no materialised table and no
  counter job: a page whose only job is to say whether the data is complete must
  not read that answer from a copy that can drift (SPEC §3.5 — v1's
  ``records_96`` is named after the hardcoded 96 and is not the model).

``fake_meter`` swaps the driver registry for every test in this module, so
nothing here touches a real meter: devices are created through the real
probe-first API and their readings are seeded straight into the table.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import mint_meter_activation_code
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

#: The local day every seeded row is placed in, so expected cells are computable
#: rather than "whatever today is".
DAY = "2026-08-01"

#: The day after :data:`DAY`, used wherever a second column is needed.
NEXT_DAY = "2026-08-02"

#: Midnight of :data:`DAY` in UTC — the start of that day when the caller's
#: offset is 0.
DAY_START = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def add_device(client: TestClient, fake_meter: FakeMeterState, *, serial: str = "SN-1", **overrides: object) -> int:
    """Create a device through the real API and return its id."""
    fake_meter.meter_serial = serial
    payload = {**DEVICE, **overrides}
    payload.setdefault("meter_activation_code", mint_meter_activation_code(meter_serial=serial))
    response = client.post("/api/devices", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def seed(
    device_id: int,
    times: list[datetime],
    *,
    logger_id: int = 1,
    interval_sec: int = 900,
) -> None:
    """Write one Interval Reading per instant in *times*, all at *interval_sec*.

    Written here rather than imported from ``test_api_load_profile.py``: that
    helper hardcodes ``interval_sec=900``, and the capture period is the one
    thing every assertion in this module turns on. One Session for the whole
    batch, because a complete day at 300 s is 288 rows.
    """
    from arichds.db.models import LoadProfileReading
    from arichds.db.session import session_scope

    with session_scope() as session:
        session.add_all(
            LoadProfileReading(
                device_id=device_id,
                read_at=read_at,
                source="dlms",
                logger_id=logger_id,
                interval_sec=interval_sec,
            )
            for read_at in times
        )


def grid_of(count: int, *, interval_sec: int, start: datetime = DAY_START) -> list[datetime]:
    """The first *count* instants of a day on an *interval_sec* grid."""
    return [start + timedelta(seconds=interval_sec * index) for index in range(count)]


def fetch(client: TestClient, start_date: str, end_date: str, **params: object):
    """Call the endpoint over a range of local calendar dates."""
    return client.get(
        "/api/records",
        params={"start_date": start_date, "end_date": end_date, **params},
    )


def cell_of(body: dict, device_id: int, date: str) -> dict:
    """The one cell for *device_id* on *date*, asserting the grid's shape holds.

    Also asserts the device has exactly **one** row — every test using it seeds
    a single logger, so a second row appearing would be the per-logger grouping
    breaking apart, not a detail to skip past.
    """
    rows = [row for row in body["data"]["rows"] if row["device_id"] == device_id]
    assert len(rows) == 1, f"expected exactly one row for device {device_id}, got {len(rows)}"
    return cell_in(body, rows[0], date)


def cell_in(body: dict, row: dict, date: str) -> dict:
    """The cell of *row* on *date*, pinning that the grid stays dense.

    Every ``(row, date)`` pair gets a cell and the cells are positional, so this
    checks ``cells`` and ``dates`` stay the same length and order — the contract
    the frontend's column-per-date table rests on.
    """
    dates = body["data"]["dates"]
    assert len(row["cells"]) == len(dates)
    assert [cell["date"] for cell in row["cells"]] == dates
    return row["cells"][dates.index(date)]


def row_of(body: dict, device_id: int, logger_id: int | None) -> dict:
    """The one row for a ``(device, logger)`` pair."""
    rows = [row for row in body["data"]["rows"] if row["device_id"] == device_id and row["logger_id"] == logger_id]
    assert len(rows) == 1, f"expected one row for device {device_id} logger {logger_id}, got {len(rows)}"
    return rows[0]


class TestCompleteness:
    def test_a_full_day_at_900_seconds_is_complete(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """96 = 86400 ÷ 900, computed from the stored period rather than assumed."""
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, grid_of(96, interval_sec=900), interval_sec=900)

        response = fetch(admin_client, DAY, DAY)

        assert response.status_code == 200, response.text
        cell = cell_of(response.json(), device_id, DAY)
        assert cell["status"] == "complete"
        assert cell["count"] == 96
        assert cell["expected"] == 96
        assert cell["interval_sec"] == 900

    def test_a_full_day_at_300_seconds_is_complete_at_288(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """The test that kills a hardcoded 96.

        A Prometer 100's Logger 2 really does run at 300 s
        (``docs/meter-notes/load-profile-capture-objects.md``, scanned off real
        meters). 288 rows is a *complete* day for it, and an endpoint that
        assumed 96 would call this day complete for the wrong reason — and would
        call a 100-row day complete too.
        """
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, grid_of(288, interval_sec=300), interval_sec=300)

        response = fetch(admin_client, DAY, DAY)

        assert response.status_code == 200, response.text
        cell = cell_of(response.json(), device_id, DAY)
        assert cell["expected"] == 288
        assert cell["interval_sec"] == 300
        assert cell["count"] == 288
        assert cell["status"] == "complete"

    def test_a_day_missing_eight_intervals_is_short(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, grid_of(88, interval_sec=900), interval_sec=900)

        response = fetch(admin_client, DAY, DAY)

        assert response.status_code == 200, response.text
        cell = cell_of(response.json(), device_id, DAY)
        assert cell["status"] == "short"
        assert cell["count"] == 88
        assert cell["expected"] == 96

    def test_a_day_with_more_rows_than_expected_is_still_complete(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """A surplus day is complete, never `short` by a negative amount.

        An off-grid entry — a power-fail or demand-reset marker lands with its
        own timestamp and survives the `(device_id, logger_id, read_at)` unique
        key — gives 97 rows on a 900 s day. Under `==` that renders as `97 (1)`
        and reads as "short by one", which is the opposite of the truth.
        """
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, [*grid_of(96, interval_sec=900), DAY_START + timedelta(seconds=37)])

        response = fetch(admin_client, DAY, DAY)

        assert response.status_code == 200, response.text
        cell = cell_of(response.json(), device_id, DAY)
        assert cell["status"] == "complete"
        assert cell["count"] == 97
        assert cell["expected"] == 96

    def test_a_day_with_no_rows_is_missing_and_not_merely_short(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """Asserted *against* the short day, so the two provably do not merge.

        ``expected`` is null because with no rows there is no capture period to
        compute one from — which is why "nothing at all" is a different answer
        from "short by everything", in the response body itself and not only in
        the UI.
        """
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, grid_of(88, interval_sec=900), interval_sec=900)

        response = fetch(admin_client, DAY, NEXT_DAY)

        assert response.status_code == 200, response.text
        body = response.json()
        short, missing = cell_of(body, device_id, DAY), cell_of(body, device_id, NEXT_DAY)
        assert missing["status"] == "missing"
        assert missing["count"] == 0
        assert missing["expected"] is None
        assert missing["interval_sec"] is None
        assert short["status"] == "short"
        assert short["expected"] == 96


class TestPeriodChange:
    def test_two_periods_in_one_day_on_one_logger_is_a_period_change(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """SPEC §3.5: expect the day's *modal* period and mark the day.

        The data is not missing — it is just at a different cadence for part of
        the day, so reporting `short` against either period would accuse the
        acquisition path of losing rows it never lost.
        """
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, grid_of(40, interval_sec=900), interval_sec=900)
        seed(device_id, grid_of(20, interval_sec=300, start=DAY_START + timedelta(hours=12)), interval_sec=300)

        response = fetch(admin_client, DAY, DAY)

        assert response.status_code == 200, response.text
        cell = cell_of(response.json(), device_id, DAY)
        assert cell["status"] == "period_changed"
        assert cell["interval_sec"] == 900
        assert cell["expected"] == 96
        assert cell["count"] == 60

    def test_two_loggers_at_different_periods_are_two_independent_rows(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """A Prometer 100 doing its normal job, which is *not* a period change.

        Logger 1 at 900 s and Logger 2 at 300 s run on one physical meter at the
        same time. Grouping by device alone would see two periods on every
        single day and mark every day `period_changed` forever; per logger, each
        is judged against its own capture period.
        """
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, grid_of(96, interval_sec=900), logger_id=1, interval_sec=900)
        seed(device_id, grid_of(200, interval_sec=300), logger_id=2, interval_sec=300)

        response = fetch(admin_client, DAY, DAY)

        assert response.status_code == 200, response.text
        body = response.json()
        first = cell_in(body, row_of(body, device_id, 1), DAY)
        second = cell_in(body, row_of(body, device_id, 2), DAY)
        assert (first["status"], first["count"], first["expected"]) == ("complete", 96, 96)
        assert (second["status"], second["count"], second["expected"]) == ("short", 200, 288)

    def test_a_tie_on_row_count_picks_the_smaller_period(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """Any deterministic rule would do; this is the one that is pinned.

        What matters is that the same stored rows always produce the same cell,
        rather than whatever order the database happened to return the groups in.
        """
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, grid_of(20, interval_sec=900), interval_sec=900)
        seed(device_id, grid_of(20, interval_sec=300, start=DAY_START + timedelta(hours=12)), interval_sec=300)

        response = fetch(admin_client, DAY, DAY)

        assert response.status_code == 200, response.text
        cell = cell_of(response.json(), device_id, DAY)
        assert cell["status"] == "period_changed"
        assert cell["interval_sec"] == 300
        assert cell["expected"] == 288
        assert cell["count"] == 40


class TestComputedLive:
    def test_deleting_a_reading_moves_the_cell_from_complete_to_short(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """No materialised copy, no counter job, no refresh step.

        This is the whole reason SPEC §3.5 refuses v1's `records_96`: a page
        whose only job is to say whether the data is complete must not read that
        answer from something that can disagree with the rows.
        """
        from sqlalchemy import select

        from arichds.db.models import LoadProfileReading
        from arichds.db.session import session_scope

        device_id = add_device(admin_client, fake_meter)
        seed(device_id, grid_of(96, interval_sec=900), interval_sec=900)

        assert cell_of(fetch(admin_client, DAY, DAY).json(), device_id, DAY)["status"] == "complete"

        with session_scope() as session:
            session.delete(session.scalars(select(LoadProfileReading).limit(1)).one())

        cell = cell_of(fetch(admin_client, DAY, DAY).json(), device_id, DAY)
        assert cell["status"] == "short"
        assert cell["count"] == 95


class TestLocalDays:
    def test_the_same_row_lands_in_a_different_column_per_offset(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """`utc_offset_minutes` is minutes to **add to UTC** — ICT is +420.

        17:30 UTC on the 5th is 00:30 ICT on the **6th**. Bucketing by UTC date
        would put every reading between local midnight and 07:00 in the previous
        column, so a real gap would be reported on the wrong date — on the one
        page whose entire job is telling you which date is missing data.
        """
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, [datetime(2026, 8, 5, 17, 30, tzinfo=UTC)])

        in_ict = fetch(admin_client, "2026-08-05", "2026-08-06", utc_offset_minutes=420).json()
        assert cell_of(in_ict, device_id, "2026-08-06")["count"] == 1
        assert cell_of(in_ict, device_id, "2026-08-05")["status"] == "missing"

        in_utc = fetch(admin_client, "2026-08-05", "2026-08-06", utc_offset_minutes=0).json()
        assert cell_of(in_utc, device_id, "2026-08-05")["count"] == 1
        assert cell_of(in_utc, device_id, "2026-08-06")["status"] == "missing"

    def test_the_last_local_evening_of_the_range_is_still_counted(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """The UTC window must cover the whole of the last *local* day.

        23:30 ICT on the 6th is 16:30 UTC on the 6th; a window that stopped at
        UTC midnight of the 6th would drop it and report the operator's evening
        as missing data.
        """
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, [datetime(2026, 8, 6, 16, 30, tzinfo=UTC)])

        body = fetch(admin_client, "2026-08-05", "2026-08-06", utc_offset_minutes=420).json()

        assert cell_of(body, device_id, "2026-08-06")["count"] == 1


class TestEveryDeviceAppears:
    def test_a_device_with_no_rows_in_the_range_still_gets_a_row(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """A completeness page that drops the silent meter is broken exactly where it matters.

        There is no logger to name — the meter has recorded nothing in the
        window — so the row carries `logger_id: null` and every cell is
        `missing`.
        """
        seeded = add_device(admin_client, fake_meter, serial="SN-1")
        silent = add_device(admin_client, fake_meter, serial="SN-2", name="Silent Feeder")
        seed(seeded, grid_of(96, interval_sec=900), interval_sec=900)

        response = fetch(admin_client, DAY, NEXT_DAY)

        assert response.status_code == 200, response.text
        body = response.json()
        row = row_of(body, silent, None)
        assert [cell["status"] for cell in row["cells"]] == ["missing", "missing"]
        assert all(cell["expected"] is None for cell in row["cells"])
        assert cell_in(body, row_of(body, seeded, 1), DAY)["status"] == "complete"

    def test_rows_are_ordered_by_meter_name_then_logger(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """A stable order, so the grid does not reshuffle between refreshes."""
        zulu = add_device(admin_client, fake_meter, serial="SN-Z", name="Zulu Feeder")
        alpha = add_device(admin_client, fake_meter, serial="SN-A", name="Alpha Feeder")
        seed(alpha, grid_of(2, interval_sec=900), logger_id=2)
        seed(alpha, grid_of(2, interval_sec=900), logger_id=1)
        seed(zulu, grid_of(2, interval_sec=900), logger_id=1)

        body = fetch(admin_client, DAY, DAY).json()

        assert [(row["device_id"], row["logger_id"]) for row in body["data"]["rows"]] == [
            (alpha, 1),
            (alpha, 2),
            (zulu, 1),
        ]


class TestClientFaults:
    def test_an_inverted_range_is_422(self, admin_client: TestClient) -> None:
        response = fetch(admin_client, NEXT_DAY, DAY)

        assert response.status_code == 422, response.text

    def test_a_thirty_one_day_span_is_accepted(self, admin_client: TestClient) -> None:
        """The bound is inclusive of both ends, so a calendar month fits."""
        response = fetch(admin_client, "2026-08-01", "2026-08-31")

        assert response.status_code == 200, response.text
        assert len(response.json()["data"]["dates"]) == 31

    def test_a_thirty_two_day_span_is_422(self, admin_client: TestClient) -> None:
        response = fetch(admin_client, "2026-08-01", "2026-09-01")

        assert response.status_code == 422, response.text


class TestAccess:
    def test_an_anonymous_caller_is_refused(self, anon_client: TestClient) -> None:
        response = fetch(anon_client, DAY, DAY)

        assert response.status_code == 401, response.text

    def test_a_plain_user_may_read(
        self, user_client: TestClient, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """Reading device data is open to any authenticated role — no admin gate."""
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, grid_of(96, interval_sec=900), interval_sec=900)

        response = fetch(user_client, DAY, DAY)

        assert response.status_code == 200, response.text
        assert cell_of(response.json(), device_id, DAY)["status"] == "complete"
