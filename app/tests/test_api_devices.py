"""Device Manager API — probe-first CRUD, catalog and quota (M3-1).

The machine is activated (Limited Mode is covered in
``test_license_roundtrip.py``) and the caller carries a token (the 401 side is
covered in ``test_auth_guard.py``). What is left for this file is the device
behaviour itself, plus the role boundary: managing meters is admin-only,
reading them is not.

Two rules decide almost every assertion here:

* **ADR 0005** — identity comes from the meter, so a failed probe writes no row
  at all, and a refused Update changes nothing.
* **D7** — a client fault gets an HTTP status code; a meter fault gets a failure
  envelope with 502, because the upstream device failed, not the request.

``fake_meter`` swaps the driver registry for every test in this module, so
nothing here touches a real meter.
"""

from __future__ import annotations

import logging

import pytest
from fakes import FakeMeterState
from fastapi.testclient import TestClient

from arichds.acquisition.probe import ProbeFailure

pytestmark = pytest.mark.usefixtures("fake_meter")

DEVICE = {
    "name": "Main Incomer",
    "brand": "cewe",
    "model": "prometer100",
    "site_name": "Plant A",
    "host": "127.0.0.1",
    "port": 4059,
    "password": "hunter2",
}


def add_device(client: TestClient, fake_meter: FakeMeterState, *, serial: str = "SN-1", **overrides: object):
    """Create a device whose meter reports *serial*."""
    fake_meter.meter_serial = serial
    return client.post("/api/devices", json={**DEVICE, **overrides})


class TestCreateDevice:
    def test_creates_and_returns_the_device(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        response = add_device(admin_client, fake_meter)

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["name"] == "Main Incomer"
        assert data["endpoint"] == "127.0.0.1:4059"
        assert data["enabled"] is True
        assert data["site_name"] == "Plant A"

    def test_the_serial_comes_from_the_meter(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """ADR 0005 — never typed by an operator."""
        data = add_device(admin_client, fake_meter, serial="SN-FROM-METER").json()["data"]
        assert data["meter_serial"] == "SN-FROM-METER"

    def test_it_probes_the_meter_before_inserting(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        add_device(admin_client, fake_meter)
        assert fake_meter.connects == 1
        assert fake_meter.disconnects == 1

    def test_never_returns_the_password(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        response = add_device(admin_client, fake_meter)
        assert "password" not in response.json()["data"]
        assert "hunter2" not in response.text

    def test_never_returns_the_cipher_keys(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        response = add_device(
            admin_client,
            fake_meter,
            block_cipher_key="0123456789ABCDEF",
            authentication_key="FEDCBA9876543210",
        )
        assert response.status_code == 201
        body = response.json()["data"]
        assert "block_cipher_key" not in body
        assert "authentication_key" not in body
        assert "0123456789ABCDEF" not in response.text
        assert "FEDCBA9876543210" not in response.text

    def test_duplicate_name_is_409(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        add_device(admin_client, fake_meter, serial="SN-1")
        response = add_device(admin_client, fake_meter, serial="SN-2")
        assert response.status_code == 409

    def test_a_duplicate_name_never_reaches_the_meter(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """Cheap checks come first — a person should not wait seconds for a typo."""
        add_device(admin_client, fake_meter, serial="SN-1")
        connects_after_first = fake_meter.connects
        add_device(admin_client, fake_meter, serial="SN-2")
        assert fake_meter.connects == connects_after_first

    def test_unknown_model_is_rejected(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        response = add_device(admin_client, fake_meter, model="not-a-meter")
        assert response.status_code == 422
        assert fake_meter.connects == 0

    def test_invalid_port_is_rejected(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        assert add_device(admin_client, fake_meter, port=0).status_code == 422

    def test_site_name_is_required(self, admin_client: TestClient) -> None:
        payload = {key: value for key, value in DEVICE.items() if key != "site_name"}
        assert admin_client.post("/api/devices", json=payload).status_code == 422

    def test_a_blank_site_name_is_rejected(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        assert add_device(admin_client, fake_meter, site_name="").status_code == 422

    def test_the_record_only_fields_round_trip(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        data = add_device(
            admin_client,
            fake_meter,
            site_code="PA-01",
            customer="Acme Co",
            meter_number="MN-778",
            group_name="Feeders",
        ).json()["data"]
        assert data["site_code"] == "PA-01"
        assert data["customer"] == "Acme Co"
        assert data["meter_number"] == "MN-778"
        assert data["group_name"] == "Feeders"


class TestCreateRefusedByTheMeter:
    """D7 — a meter fault is a 502 with a failure envelope, and writes nothing."""

    def test_no_row_is_written(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        fake_meter.connect_error = ConnectionRefusedError("refused")
        response = add_device(admin_client, fake_meter)

        assert response.json()["success"] is False
        assert admin_client.get("/api/devices").json()["data"] == []

    def test_the_status_is_502(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        fake_meter.connect_error = ConnectionRefusedError("refused")
        assert add_device(admin_client, fake_meter).status_code == 502

    def test_the_envelope_carries_a_code_and_a_message(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.connect_error = ConnectionRefusedError("refused")
        error = add_device(admin_client, fake_meter).json()["error"]
        assert error["code"] == "PROBE_FAILED"
        assert "127.0.0.1:4059" in error["message"]

    @pytest.mark.parametrize(
        ("knob", "error", "expected"),
        [
            ("connect_error", TimeoutError("slow"), ProbeFailure.TIMEOUT),
            ("connect_error", ConnectionRefusedError("refused"), ProbeFailure.UNREACHABLE),
            ("serial_error", None, ProbeFailure.NO_SERIAL),
        ],
        ids=["timeout", "unreachable", "no-serial"],
    )
    def test_each_reason_surfaces_distinctly(
        self,
        admin_client: TestClient,
        fake_meter: FakeMeterState,
        knob: str,
        error: Exception | None,
        expected: ProbeFailure,
    ) -> None:
        if error is None:
            fake_meter.meter_serial = None
            response = admin_client.post("/api/devices", json=DEVICE)
        else:
            setattr(fake_meter, knob, error)
            response = add_device(admin_client, fake_meter)

        assert response.json()["error"]["reason"] == expected.value

    def test_rejected_credentials_are_auth_failed(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        from gurux_dlms import GXDLMSException

        fake_meter.connect_error = GXDLMSException(1)
        response = add_device(admin_client, fake_meter)
        assert response.json()["error"]["reason"] == ProbeFailure.AUTH_FAILED.value


class TestDuplicateSerial:
    def test_a_second_device_on_the_same_meter_is_409(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        add_device(admin_client, fake_meter, serial="SN-SAME")
        response = add_device(admin_client, fake_meter, name="Copy", host="10.0.0.9", serial="SN-SAME")
        assert response.status_code == 409

    def test_the_message_names_the_existing_device(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """So the operator moves the existing row instead of creating a second."""
        add_device(admin_client, fake_meter, serial="SN-SAME")
        response = add_device(admin_client, fake_meter, name="Copy", host="10.0.0.9", serial="SN-SAME")
        assert "Main Incomer" in response.json()["detail"]

    def test_no_second_row_is_written(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        add_device(admin_client, fake_meter, serial="SN-SAME")
        add_device(admin_client, fake_meter, name="Copy", host="10.0.0.9", serial="SN-SAME")
        assert len(admin_client.get("/api/devices").json()["data"]) == 1

    def test_deleting_frees_the_serial(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """ADR 0005 — no tombstone: one mistyped meter must not block forever."""
        device_id = add_device(admin_client, fake_meter, serial="SN-SAME").json()["data"]["id"]
        assert admin_client.delete(f"/api/devices/{device_id}").status_code == 200

        again = add_device(admin_client, fake_meter, serial="SN-SAME")
        assert again.status_code == 201


class TestUpdateDevice:
    @pytest.fixture
    def device_id(self, admin_client: TestClient, fake_meter: FakeMeterState) -> int:
        return add_device(admin_client, fake_meter, serial="SN-1").json()["data"]["id"]

    def update(self, client: TestClient, device_id: int, **overrides: object):
        """PUT the full device payload with *overrides* applied."""
        return client.put(f"/api/devices/{device_id}", json={**DEVICE, **overrides})

    def test_edits_are_saved(self, admin_client: TestClient, device_id: int) -> None:
        data = self.update(admin_client, device_id, name="Renamed", site_name="Plant B").json()["data"]
        assert data["name"] == "Renamed"
        assert data["site_name"] == "Plant B"

    def test_it_always_re_probes(self, admin_client: TestClient, fake_meter: FakeMeterState, device_id: int) -> None:
        connects_after_create = fake_meter.connects
        self.update(admin_client, device_id, name="Renamed")
        assert fake_meter.connects == connects_after_create + 1

    def test_unknown_device_is_404(self, admin_client: TestClient) -> None:
        assert self.update(admin_client, 999).status_code == 404

    def test_brand_and_model_are_editable(self, admin_client: TestClient, device_id: int) -> None:
        data = self.update(admin_client, device_id, brand="CEWE Thailand").json()["data"]
        assert data["brand"] == "CEWE Thailand"

    def test_a_name_taken_by_another_device_is_409(
        self, admin_client: TestClient, fake_meter: FakeMeterState, device_id: int
    ) -> None:
        add_device(admin_client, fake_meter, name="Second", host="10.0.0.2", serial="SN-2")
        assert self.update(admin_client, device_id, name="Second").status_code == 409

    def test_keeping_its_own_name_is_fine(self, admin_client: TestClient, device_id: int) -> None:
        assert self.update(admin_client, device_id).status_code == 200


class TestUpdateRefusedOnSerialMismatch:
    """ADR 0005 — a different serial means the row is being pointed elsewhere."""

    @pytest.fixture
    def stored(self, admin_client: TestClient, fake_meter: FakeMeterState) -> dict:
        add_device(admin_client, fake_meter, serial="SN-1")
        return admin_client.get("/api/devices").json()["data"][0]

    def test_it_is_409(self, admin_client: TestClient, fake_meter: FakeMeterState, stored: dict) -> None:
        fake_meter.meter_serial = "SN-OTHER"
        response = admin_client.put(f"/api/devices/{stored['id']}", json={**DEVICE, "host": "10.0.0.5"})
        assert response.status_code == 409

    def test_the_message_names_both_serials(
        self, admin_client: TestClient, fake_meter: FakeMeterState, stored: dict
    ) -> None:
        fake_meter.meter_serial = "SN-OTHER"
        detail = admin_client.put(f"/api/devices/{stored['id']}", json={**DEVICE, "host": "10.0.0.5"}).json()["detail"]
        assert "SN-1" in detail
        assert "SN-OTHER" in detail

    def test_not_one_column_changes(self, admin_client: TestClient, fake_meter: FakeMeterState, stored: dict) -> None:
        fake_meter.meter_serial = "SN-OTHER"
        admin_client.put(
            f"/api/devices/{stored['id']}",
            json={**DEVICE, "name": "Renamed", "host": "10.0.0.5", "site_name": "Plant Z"},
        )
        assert admin_client.get("/api/devices").json()["data"][0] == stored

    def test_the_stored_password_is_untouched(
        self, admin_client: TestClient, fake_meter: FakeMeterState, stored: dict
    ) -> None:
        fake_meter.meter_serial = "SN-OTHER"
        admin_client.put(f"/api/devices/{stored['id']}", json={**DEVICE, "password": "changed-me"})
        assert stored_password(stored["id"]) == "hunter2"

    def test_a_serial_belonging_to_another_device_is_409(
        self, admin_client: TestClient, fake_meter: FakeMeterState, stored: dict
    ) -> None:
        """Two rows must never point at one physical meter, however they got there."""
        add_device(admin_client, fake_meter, name="Second", host="10.0.0.2", serial="SN-2")
        fake_meter.meter_serial = "SN-2"
        # The first device now answers with the second device's serial.
        response = admin_client.put(f"/api/devices/{stored['id']}", json={**DEVICE, "host": "10.0.0.2"})
        assert response.status_code == 409


class TestUpdateFillsInAMissingSerial:
    def test_a_null_serial_row_is_identified_by_the_update(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """The pre-M3 row's way out (SPEC §3.3)."""
        device_id = insert_unidentified_device()
        fake_meter.meter_serial = "SN-NEW"

        response = admin_client.put(f"/api/devices/{device_id}", json=DEVICE)

        assert response.status_code == 200
        assert response.json()["data"]["meter_serial"] == "SN-NEW"


class TestUpdateSecretsDefaultToKeep:
    """D10 / SPEC §3.3 — on edit, blank means keep."""

    @pytest.fixture
    def device_id(self, admin_client: TestClient, fake_meter: FakeMeterState) -> int:
        return add_device(
            admin_client,
            fake_meter,
            serial="SN-1",
            block_cipher_key="CIPHER-1",
            authentication_key="AUTH-1",
        ).json()["data"]["id"]

    def test_an_empty_password_keeps_the_stored_one(self, admin_client: TestClient, device_id: int) -> None:
        assert admin_client.put(f"/api/devices/{device_id}", json={**DEVICE, "password": ""}).status_code == 200
        assert stored_password(device_id) == "hunter2"

    def test_an_omitted_password_keeps_the_stored_one(self, admin_client: TestClient, device_id: int) -> None:
        payload = {key: value for key, value in DEVICE.items() if key != "password"}
        assert admin_client.put(f"/api/devices/{device_id}", json=payload).status_code == 200
        assert stored_password(device_id) == "hunter2"

    def test_a_new_password_replaces_it(self, admin_client: TestClient, device_id: int) -> None:
        admin_client.put(f"/api/devices/{device_id}", json={**DEVICE, "password": "new-secret"})
        assert stored_password(device_id) == "new-secret"

    def test_the_re_probe_uses_the_new_password_when_given(
        self, admin_client: TestClient, fake_meter: FakeMeterState, device_id: int
    ) -> None:
        admin_client.put(f"/api/devices/{device_id}", json={**DEVICE, "password": "new-secret"})
        assert stored_password(device_id) == "new-secret"

    def test_blank_cipher_keys_keep_the_stored_ones(self, admin_client: TestClient, device_id: int) -> None:
        admin_client.put(
            f"/api/devices/{device_id}",
            json={**DEVICE, "block_cipher_key": "", "authentication_key": ""},
        )
        assert stored_secret(device_id, "block_cipher_key") == "CIPHER-1"
        assert stored_secret(device_id, "authentication_key") == "AUTH-1"


class TestCatalog:
    def test_only_models_with_a_driver_are_listed(self, admin_client: TestClient) -> None:
        """SPEC §3.3 — M3 offers ``prometer100`` alone; the other eight land in M4."""
        data = admin_client.get("/api/devices/catalog").json()["data"]
        assert [entry["model"] for entry in data] == ["prometer100"]

    def test_it_carries_what_the_form_prefills(self, admin_client: TestClient) -> None:
        entry = admin_client.get("/api/devices/catalog").json()["data"][0]
        assert entry["ui_label"] == "Prometer 100"
        assert entry["default_port"] == 4059
        assert entry["fixed_password"] == "ABCD0001"
        assert entry["brand"] == "cewe"

    def test_it_carries_the_capability_flags(self, admin_client: TestClient) -> None:
        entry = admin_client.get("/api/devices/catalog").json()["data"][0]
        assert entry["supports_serial"] is False
        assert entry["supports_battery"] is True
        assert entry["supports_energy_summary"] is False
        assert entry["supports_special_days"] is False

    def test_the_old_models_endpoint_is_gone(self, admin_client: TestClient) -> None:
        """405, not 404: the path still matches ``/{device_id}``, which has no GET.

        Either way it no longer serves a model list, which is what the SPA's
        removed ``supportedModels()`` used to call.
        """
        response = admin_client.get("/api/devices/models")
        assert response.status_code != 200


class TestQuota:
    def test_unlimited_when_the_license_sets_no_max(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        add_device(admin_client, fake_meter, serial="SN-1")
        data = admin_client.get("/api/devices/quota").json()["data"]
        assert data == {"used": 1, "max_meters": None, "over_quota": False}

    def test_it_counts_devices(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        add_device(admin_client, fake_meter, serial="SN-1")
        add_device(admin_client, fake_meter, name="Second", host="10.0.0.2", serial="SN-2")
        assert admin_client.get("/api/devices/quota").json()["data"]["used"] == 2

    def test_a_full_quota_refuses_a_new_device(
        self, admin_client: TestClient, fake_meter: FakeMeterState, relicense
    ) -> None:
        relicense(admin_client, max_meters=1)
        add_device(admin_client, fake_meter, serial="SN-1")

        response = add_device(admin_client, fake_meter, name="Second", host="10.0.0.2", serial="SN-2")

        assert response.status_code == 409
        assert "1" in response.json()["detail"]

    def test_exactly_at_the_limit_refuses_but_is_not_over_quota(
        self, admin_client: TestClient, fake_meter: FakeMeterState, relicense
    ) -> None:
        """Two different questions, two different comparisons — on purpose.

        Creating is refused at ``used >= max_meters`` (the slot is gone), while
        ``over_quota`` is ``used > max_meters`` (SPEC §3.3's `10 / 5 — over
        quota` warning is about genuinely exceeding a *reduced* license). At
        exactly 1 / 1 a new device is refused and no warning is shown.
        """
        relicense(admin_client, max_meters=1)
        add_device(admin_client, fake_meter, serial="SN-1")

        assert add_device(admin_client, fake_meter, name="Second", serial="SN-2").status_code == 409
        assert admin_client.get("/api/devices/quota").json()["data"] == {
            "used": 1,
            "max_meters": 1,
            "over_quota": False,
        }

    def test_a_refused_create_never_reaches_the_meter(
        self, admin_client: TestClient, fake_meter: FakeMeterState, relicense
    ) -> None:
        relicense(admin_client, max_meters=1)
        add_device(admin_client, fake_meter, serial="SN-1")
        connects = fake_meter.connects

        add_device(admin_client, fake_meter, name="Second", host="10.0.0.2", serial="SN-2")

        assert fake_meter.connects == connects

    def test_over_quota_keeps_every_existing_device_working(
        self, admin_client: TestClient, fake_meter: FakeMeterState, relicense
    ) -> None:
        """SPEC §3.3 — cutting a customer off because a number changed is forbidden."""
        add_device(admin_client, fake_meter, serial="SN-1")
        add_device(admin_client, fake_meter, name="Second", host="10.0.0.2", serial="SN-2")
        relicense(admin_client, max_meters=1)

        listed = admin_client.get("/api/devices").json()["data"]
        assert len(listed) == 2
        for device in listed:
            assert admin_client.get(f"/api/devices/{device['id']}/readings/latest").status_code == 200

    def test_over_quota_is_reported(self, admin_client: TestClient, fake_meter: FakeMeterState, relicense) -> None:
        add_device(admin_client, fake_meter, serial="SN-1")
        add_device(admin_client, fake_meter, name="Second", host="10.0.0.2", serial="SN-2")
        relicense(admin_client, max_meters=1)

        assert admin_client.get("/api/devices/quota").json()["data"] == {
            "used": 2,
            "max_meters": 1,
            "over_quota": True,
        }

    def test_a_new_license_applies_without_a_restart(
        self, admin_client: TestClient, fake_meter: FakeMeterState, relicense
    ) -> None:
        """ADR 0001 — quota is read live, never cached at import or startup."""
        relicense(admin_client, max_meters=1)
        assert admin_client.get("/api/devices/quota").json()["data"]["max_meters"] == 1

        relicense(admin_client, max_meters=5)
        assert admin_client.get("/api/devices/quota").json()["data"]["max_meters"] == 5

    def test_deleting_frees_a_slot_immediately(
        self, admin_client: TestClient, fake_meter: FakeMeterState, relicense
    ) -> None:
        relicense(admin_client, max_meters=1)
        device_id = add_device(admin_client, fake_meter, serial="SN-1").json()["data"]["id"]
        admin_client.delete(f"/api/devices/{device_id}")

        assert add_device(admin_client, fake_meter, name="Second", serial="SN-2").status_code == 201


class TestTestConnection:
    BODY = {"model": "prometer100", "host": "127.0.0.1", "port": 4059, "password": "ABCD0001"}

    def test_a_reachable_meter_reports_its_serial(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        fake_meter.meter_serial = "SN-DIAG"
        response = admin_client.post("/api/devices/test-connection", json=self.BODY)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["reachable"] is True
        assert data["meter_serial"] == "SN-DIAG"
        assert data["reason"] is None

    def test_a_refusing_meter_is_still_a_200(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """A meter that refuses is a successful execution of a diagnostic."""
        fake_meter.connect_error = ConnectionRefusedError("refused")
        response = admin_client.post("/api/devices/test-connection", json=self.BODY)

        assert response.status_code == 200
        assert response.json()["success"] is True
        data = response.json()["data"]
        assert data["reachable"] is False
        assert data["meter_serial"] is None
        assert data["reason"] == ProbeFailure.UNREACHABLE.value
        assert "127.0.0.1:4059" in data["message"]

    def test_it_writes_no_row(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        admin_client.post("/api/devices/test-connection", json=self.BODY)
        assert admin_client.get("/api/devices").json()["data"] == []

    def test_an_unknown_model_is_422(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        response = admin_client.post("/api/devices/test-connection", json={**self.BODY, "model": "nope"})
        assert response.status_code == 422
        assert fake_meter.connects == 0

    def test_it_never_echoes_the_password(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        fake_meter.connect_error = ConnectionRefusedError("refused")
        response = admin_client.post("/api/devices/test-connection", json={**self.BODY, "password": "hunter2"})
        assert "hunter2" not in response.text


class TestListDevices:
    def test_empty_to_start(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/devices")
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_lists_created_devices(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        add_device(admin_client, fake_meter, serial="SN-1")
        add_device(admin_client, fake_meter, name="Second", port=4060, serial="SN-2")

        data = admin_client.get("/api/devices").json()["data"]
        assert [d["name"] for d in data] == ["Main Incomer", "Second"]


class TestDeleteDevice:
    def test_deletes(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter).json()["data"]["id"]

        assert admin_client.delete(f"/api/devices/{device_id}").status_code == 200
        assert admin_client.get("/api/devices").json()["data"] == []

    def test_unknown_id_is_404(self, admin_client: TestClient) -> None:
        assert admin_client.delete("/api/devices/999").status_code == 404


class TestLatestReading:
    def test_null_before_the_first_tick(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter).json()["data"]["id"]

        response = admin_client.get(f"/api/devices/{device_id}/readings/latest")

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["data"] is None

    def test_returns_the_newest_reading(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        import threading

        from arichds.acquisition.locks import EndpointLocks
        from arichds.acquisition.poller import poll_once
        from arichds.db.models import Device
        from arichds.db.session import session_scope

        device_id = add_device(admin_client, fake_meter).json()["data"]["id"]
        with session_scope() as session:
            device = session.get(Device, device_id)
            session.expunge(device)
        poll_once(device, EndpointLocks(), threading.Event())

        data = admin_client.get(f"/api/devices/{device_id}/readings/latest").json()["data"]

        assert data is not None
        assert data["device_id"] == device_id
        assert data["source"] == "dlms"
        assert data["interval"] == "60s"
        assert data["volt_l1"] > 200
        assert data["import_active_kwh"] > 0

    def test_unknown_device_is_404(self, admin_client: TestClient) -> None:
        assert admin_client.get("/api/devices/999/readings/latest").status_code == 404


class TestEnvelope:
    def test_every_response_uses_the_envelope(self, admin_client: TestClient) -> None:
        body = admin_client.get("/api/devices").json()
        assert set(body) == {"success", "data", "error"}
        assert body["success"] is True
        assert body["error"] is None


class TestSecretsNeverLeak:
    def test_no_log_line_carries_a_password_or_a_key(
        self, admin_client: TestClient, fake_meter: FakeMeterState, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            device_id = add_device(
                admin_client,
                fake_meter,
                block_cipher_key="CIPHER-1",
                authentication_key="AUTH-1",
            ).json()["data"]["id"]
            admin_client.put(f"/api/devices/{device_id}", json={**DEVICE, "password": "another-secret"})
            admin_client.post(
                "/api/devices/test-connection",
                json={"model": "prometer100", "host": "127.0.0.1", "port": 4059, "password": "diag-secret"},
            )

        for secret in ("hunter2", "CIPHER-1", "AUTH-1", "another-secret", "diag-secret"):
            assert secret not in caplog.text

    def test_the_list_never_carries_them(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        add_device(admin_client, fake_meter, block_cipher_key="CIPHER-1", authentication_key="AUTH-1")
        response = admin_client.get("/api/devices")
        for secret in ("hunter2", "CIPHER-1", "AUTH-1"):
            assert secret not in response.text


class TestRoleBoundary:
    """SPEC §3.2 — a ``user`` sees everything and changes nothing."""

    def test_a_user_cannot_create_a_device(self, user_client: TestClient) -> None:
        assert user_client.post("/api/devices", json=DEVICE).status_code == 403

    def test_a_user_cannot_update_a_device(
        self, admin_client: TestClient, user_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter).json()["data"]["id"]
        assert user_client.put(f"/api/devices/{device_id}", json=DEVICE).status_code == 403

    def test_a_user_cannot_delete_a_device(
        self, admin_client: TestClient, user_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter).json()["data"]["id"]

        assert user_client.delete(f"/api/devices/{device_id}").status_code == 403
        assert len(admin_client.get("/api/devices").json()["data"]) == 1

    def test_a_user_cannot_test_a_connection(self, user_client: TestClient) -> None:
        """D9 — the diagnostic half of an admin-only form, and it aims this
        machine's socket at an arbitrary host:port."""
        response = user_client.post(
            "/api/devices/test-connection",
            json={"model": "prometer100", "host": "127.0.0.1", "port": 4059, "password": ""},
        )
        assert response.status_code == 403

    def test_a_user_can_list_devices(
        self, admin_client: TestClient, user_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        add_device(admin_client, fake_meter)

        response = user_client.get("/api/devices")

        assert response.status_code == 200
        assert [d["name"] for d in response.json()["data"]] == ["Main Incomer"]

    def test_a_user_can_read_the_catalog(self, user_client: TestClient) -> None:
        assert user_client.get("/api/devices/catalog").status_code == 200

    def test_a_user_can_read_the_quota(self, user_client: TestClient) -> None:
        assert user_client.get("/api/devices/quota").status_code == 200

    def test_a_user_can_read_the_latest_reading(
        self, admin_client: TestClient, user_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter).json()["data"]["id"]

        assert user_client.get(f"/api/devices/{device_id}/readings/latest").status_code == 200

    def test_the_403_is_not_a_401(self, user_client: TestClient) -> None:
        """Authenticated-but-not-allowed is a different answer from unauthenticated."""
        response = user_client.post("/api/devices", json=DEVICE)

        assert response.status_code == 403
        assert "WWW-Authenticate" not in response.headers


# ─── Helpers that reach into the database ─────────────────────────────────────
#
# Passwords and cipher keys are never returned by any endpoint, so the only
# honest way to assert "the stored value is unchanged" is to read the column.


def stored_password(device_id: int) -> str:
    """Return the password column of *device_id*."""
    return stored_secret(device_id, "password")


def stored_secret(device_id: int, column: str) -> str:
    """Return one never-exposed column of *device_id*."""
    from arichds.db.models import Device
    from arichds.db.session import session_scope

    with session_scope() as session:
        return getattr(session.get(Device, device_id), column)


def insert_unidentified_device() -> int:
    """Insert a pre-M3 style row: no serial, placeholder site."""
    from arichds.db.models import Device
    from arichds.db.session import session_scope

    with session_scope() as session:
        device = Device(
            name="Main Incomer",
            brand="cewe",
            model="prometer100",
            site_name="Unknown site",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="hunter2",
            enabled=False,
        )
        session.add(device)
        session.flush()
        return device.id
