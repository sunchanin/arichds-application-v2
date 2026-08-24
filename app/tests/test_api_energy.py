"""Energy API (M7-1, issue #28) — the Summary Report tab's TOU aggregation
and the Meter Registers tab's stored/read-now endpoints.

The TOU aggregation itself (weekend/annual/public holiday classification,
peak-window boundaries, the UTC-hour-vs-local-day translation traps) is
exercised through this HTTP surface — see ``TestOutputParityAndTranslationTraps``
below for the required behaviours, each with a comment naming the rule it
proves.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import mint_meter_activation_code
from fakes import FakeMeterState
from fastapi.testclient import TestClient

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


def add_device(client: TestClient, fake_meter: FakeMeterState, *, serial: str = "SN-1") -> int:
    fake_meter.meter_serial = serial
    payload = {**DEVICE, "meter_activation_code": mint_meter_activation_code(meter_serial=serial)}
    response = client.post("/api/devices", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def seed(device_id: int, rows: list[tuple[datetime, float | None, float | None]], *, logger_id: int = 1) -> None:
    """One Interval Reading per ``(read_at, import_active_kwh, export_active_kwh)``."""
    with session_scope() as session:
        session.add_all(
            LoadProfileReading(
                device_id=device_id,
                read_at=read_at,
                source="dlms",
                logger_id=logger_id,
                interval_sec=900,
                import_active_kwh=imp,
                export_active_kwh=exp,
            )
            for read_at, imp, exp in rows
        )


class TestDeviceValidation:
    def test_unknown_device_is_404(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/energy/summary?device_id=999&start_date=2026-08-01&end_date=2026-08-01")
        assert response.status_code == 404

    def test_end_before_start_is_422(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)
        response = admin_client.get(
            f"/api/energy/summary?device_id={device_id}&start_date=2026-08-05&end_date=2026-08-01"
        )
        assert response.status_code == 422

    def test_span_over_31_days_is_422(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter)
        response = admin_client.get(
            f"/api/energy/summary?device_id={device_id}&start_date=2026-07-01&end_date=2026-08-05"
        )
        assert response.status_code == 422


class TestOutputParityAndTranslationTraps:
    """Each test proves exactly one rule named in its docstring, computed by
    hand from v1's SQL rules (Output Parity)."""

    def test_saturday_ict_0030_is_holiday_not_peak_or_offpeak(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """Saturday ICT 00:30 = Friday 2026-08-07 17:30 UTC. If the local-day
        shift is dropped (weekend test done on the *UTC* date, a Friday),
        this interval would be classified Off-Peak — the case that dies if
        `ADDTIME`'s SQLite translation (`date(col, '+7 hours')`) is missing
        or wrong."""
        device_id = add_device(admin_client, fake_meter)
        # 2026-08-07 is a Friday; +7h -> 2026-08-08 00:30 ICT, a Saturday.
        seed(device_id, [(datetime(2026, 8, 7, 17, 30, tzinfo=UTC), 1.0, 0.0)])

        response = admin_client.get(
            f"/api/energy/summary?device_id={device_id}&start_date=2026-08-07&end_date=2026-08-08"
        )
        assert response.status_code == 200, response.text
        days = {d["date"]: d for d in response.json()["data"]["days"]}
        assert "2026-08-08" in days
        day = days["2026-08-08"]
        assert day["holiday_import_kwh"] == pytest.approx(1.0)
        assert day["peak_import_kwh"] == pytest.approx(0.0)
        assert day["offpeak_import_kwh"] == pytest.approx(0.0)
        assert day["total_import_kwh"] == pytest.approx(1.0)

    def test_a_saturday_interval_inside_the_peak_window_is_holiday_not_peak(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """CONTEXT.md — Energy Summary: "a Saturday inside the peak window
        is Holiday energy, not Peak energy". 2026-08-08 is a Saturday; UTC
        08:00 sits inside [02, 15) — the peak window."""
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, [(datetime(2026, 8, 8, 8, 0, tzinfo=UTC), 2.0, 0.0)])

        response = admin_client.get(
            f"/api/energy/summary?device_id={device_id}&start_date=2026-08-08&end_date=2026-08-08"
        )
        day = response.json()["data"]["days"][0]
        assert day["holiday_import_kwh"] == pytest.approx(2.0)
        assert day["peak_import_kwh"] == pytest.approx(0.0)

    def test_an_annual_holiday_matches_across_a_year_boundary(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """An `annual` row matching 13 April against readings in two
        different years — both years' 13 April must classify Holiday.

        Deliberately **not** 1 January (month == day): that fixture is
        invariant under a `%m`/`%d` transposition in the SQL, so it cannot
        tell a correct annual match from one that only works by accident of
        a swapped field order. 13 April is the asymmetric day the issue
        itself names for exactly this reason (finding 1's worked example).
        """
        device_id = add_device(admin_client, fake_meter)
        admin_client.post("/api/holidays", json={"kind": "annual", "name": "Songkran", "month": 4, "day": 13})
        # 2026-04-13 and 2027-04-13, both a weekday's worth of margin from the
        # weekend so only the annual rule can be responsible for Holiday.
        # 2026-04-13 is a Monday; 2027-04-13 is a Tuesday.
        seed(
            device_id,
            [
                (datetime(2026, 4, 13, 8, 0, tzinfo=UTC), 3.0, 0.0),
                (datetime(2027, 4, 13, 8, 0, tzinfo=UTC), 4.0, 0.0),
            ],
        )

        response = admin_client.get(
            f"/api/energy/summary?device_id={device_id}&start_date=2026-04-13&end_date=2026-04-13"
        )
        assert response.json()["data"]["days"][0]["holiday_import_kwh"] == pytest.approx(3.0)

        response = admin_client.get(
            f"/api/energy/summary?device_id={device_id}&start_date=2027-04-13&end_date=2027-04-13"
        )
        assert response.json()["data"]["days"][0]["holiday_import_kwh"] == pytest.approx(4.0)

    def test_a_public_holiday_matches_one_exact_date_only(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """A `public` row matching one exact date and NOT the same
        month/day in a different year — the discriminator against the
        annual test above."""
        device_id = add_device(admin_client, fake_meter)
        admin_client.post("/api/holidays", json={"kind": "public", "name": "One-off", "date": "2026-03-02"})
        # 2026-03-02 is a Monday; 2027-03-02 is a Tuesday — neither a weekend.
        seed(
            device_id,
            [
                (datetime(2026, 3, 2, 8, 0, tzinfo=UTC), 5.0, 0.0),
                (datetime(2027, 3, 2, 8, 0, tzinfo=UTC), 6.0, 0.0),
            ],
        )

        matched = admin_client.get(
            f"/api/energy/summary?device_id={device_id}&start_date=2026-03-02&end_date=2026-03-02"
        ).json()["data"]["days"][0]
        assert matched["holiday_import_kwh"] == pytest.approx(5.0)

        unmatched = admin_client.get(
            f"/api/energy/summary?device_id={device_id}&start_date=2027-03-02&end_date=2027-03-02"
        ).json()["data"]["days"][0]
        assert unmatched["holiday_import_kwh"] == pytest.approx(0.0)
        assert unmatched["peak_import_kwh"] == pytest.approx(6.0)

    def test_a_weekday_splits_correctly_at_both_peak_boundaries(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """A non-holiday weekday, split at `>= peak_start` and `< peak_end`
        — 2026-08-06 is a Thursday. UTC 01:59 is Off-Peak (< 02), UTC 02:00
        is Peak (>= 02, the boundary itself), UTC 14:59 is Peak (< 15, the
        boundary itself), UTC 15:00 is Off-Peak (>= 15)."""
        device_id = add_device(admin_client, fake_meter)
        seed(
            device_id,
            [
                (datetime(2026, 8, 6, 1, 59, tzinfo=UTC), 1.0, 0.0),
                (datetime(2026, 8, 6, 2, 0, tzinfo=UTC), 2.0, 0.0),
                (datetime(2026, 8, 6, 14, 59, tzinfo=UTC), 3.0, 0.0),
                (datetime(2026, 8, 6, 15, 0, tzinfo=UTC), 4.0, 0.0),
            ],
        )

        day = admin_client.get(
            f"/api/energy/summary?device_id={device_id}&start_date=2026-08-06&end_date=2026-08-06"
        ).json()["data"]["days"][0]
        assert day["offpeak_import_kwh"] == pytest.approx(1.0 + 4.0)
        assert day["peak_import_kwh"] == pytest.approx(2.0 + 3.0)
        assert day["holiday_import_kwh"] == pytest.approx(0.0)
        assert day["total_import_kwh"] == pytest.approx(10.0)

    def test_logger_2_energy_is_excluded_from_the_aggregate(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """Logger 1 only (decision 6) — a model that captures energy in two
        profiles must not have it double-counted. Seeds a Logger 2 row on
        the same device and day as an existing Logger 1 reading; the
        Logger 2 value (100.0, an order of magnitude away from anything
        else this day) must not reach any bucket."""
        device_id = add_device(admin_client, fake_meter)
        seed(device_id, [(datetime(2026, 8, 6, 8, 0, tzinfo=UTC), 5.0, 0.0)], logger_id=1)
        seed(device_id, [(datetime(2026, 8, 6, 8, 0, tzinfo=UTC), 100.0, 0.0)], logger_id=2)

        day = admin_client.get(
            f"/api/energy/summary?device_id={device_id}&start_date=2026-08-06&end_date=2026-08-06"
        ).json()["data"]["days"][0]
        assert day["total_import_kwh"] == pytest.approx(5.0)
        assert day["peak_import_kwh"] == pytest.approx(5.0)

    def test_output_parity_fixed_seeded_dataset(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """One fixed dataset, hand-computed by v1's SQL rules, asserted as
        literals (decision — "Output Parity" for this slice: v1 cannot be
        executed here, so this hand-computed set is the ground truth).

        v1 column mapping: `import_wh_total_active` -> `import_active_kwh`
        — the ÷1000 already happened at write time (decision 9), so this
        SQL sums kWh directly, with no divide-by-1000 on the read path.

        2026-08-06 (Thursday, non-holiday): one Off-Peak row (UTC 01:00,
        import 1.5) and one Peak row (UTC 10:00, import 2.5).
        2026-08-08 (Saturday, Holiday): one row at UTC 08:00 (inside the
        peak window, but Holiday wins), import 3.0, export 0.5.
        """
        device_id = add_device(admin_client, fake_meter)
        seed(
            device_id,
            [
                (datetime(2026, 8, 6, 1, 0, tzinfo=UTC), 1.5, 0.0),
                (datetime(2026, 8, 6, 10, 0, tzinfo=UTC), 2.5, 0.0),
                (datetime(2026, 8, 8, 8, 0, tzinfo=UTC), 3.0, 0.5),
            ],
        )

        response = admin_client.get(
            f"/api/energy/summary?device_id={device_id}&start_date=2026-08-06&end_date=2026-08-08"
        )
        days = {d["date"]: d for d in response.json()["data"]["days"]}

        assert days["2026-08-06"] == {
            "date": "2026-08-06",
            "peak_import_kwh": 2.5,
            "offpeak_import_kwh": 1.5,
            "holiday_import_kwh": 0.0,
            "total_import_kwh": 4.0,
            "peak_export_kwh": 0.0,
            "offpeak_export_kwh": 0.0,
            "holiday_export_kwh": 0.0,
            "total_export_kwh": 0.0,
        }
        assert days["2026-08-08"] == {
            "date": "2026-08-08",
            "peak_import_kwh": 0.0,
            "offpeak_import_kwh": 0.0,
            "holiday_import_kwh": 3.0,
            "total_import_kwh": 3.0,
            "peak_export_kwh": 0.0,
            "offpeak_export_kwh": 0.0,
            "holiday_export_kwh": 0.5,
            "total_export_kwh": 0.5,
        }


class TestEnergyRegisters:
    def test_read_now_stores_and_lists_a_row(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        from arichds.acquisition.drivers.base import EnergyRegisterReading

        device_id = add_device(admin_client, fake_meter)
        fake_meter.energy_registers_reading = EnergyRegisterReading(
            source="dlms", meter_serial="SN-1", import_active_kwh_total=1066.62
        )

        read_response = admin_client.post(f"/api/energy/registers/read?device_id={device_id}")
        assert read_response.status_code == 200, read_response.text
        body = read_response.json()["data"]
        assert body["error"] is None
        assert body["row"]["import_active_kwh_total"] == pytest.approx(1066.62)

        listing = admin_client.get(f"/api/energy/registers?device_id={device_id}")
        assert listing.status_code == 200
        assert len(listing.json()["data"]) == 1

    def test_read_now_on_an_unsupported_device_is_404(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.meter_serial = "SN-2"
        payload = {
            **DEVICE,
            "brand": "cewe",
            "model": "prometer100",
            "meter_activation_code": mint_meter_activation_code(meter_serial="SN-2"),
        }
        response = admin_client.post("/api/devices", json=payload)
        device_id = response.json()["data"]["id"]

        result = admin_client.post(f"/api/energy/registers/read?device_id={device_id}")
        assert result.status_code == 404

    def test_read_now_on_an_unknown_device_is_404_not_500(self, admin_client: TestClient) -> None:
        """Error-path audit finding: the job function raises `ValueError` for
        a missing device, which the router must translate to 404 — not let
        propagate into an unhandled 500."""
        response = admin_client.post("/api/energy/registers/read?device_id=999")
        assert response.status_code == 404

    def test_a_connect_failure_comes_back_as_a_payload_error_not_an_http_error(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """A live-read failure is a verdict on the payload, never an HTTP
        error status — mirrors Test Connection."""
        device_id = add_device(admin_client, fake_meter)
        fake_meter.connect_error = ConnectionError("boom")

        response = admin_client.post(f"/api/energy/registers/read?device_id={device_id}")
        assert response.status_code == 200, response.text
        body = response.json()["data"]
        assert body["row"] is None
        assert body["error"] is not None

    def test_registers_list_unknown_device_is_404(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/energy/registers?device_id=999")
        assert response.status_code == 404
