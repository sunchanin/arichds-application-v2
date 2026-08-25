"""Device Manager API — probe-first CRUD, catalog and quota (M3-1); status,
history, Pause/Resume, Read now and Delete all data (M3-2).

The machine is activated (Limited Mode is covered in
``test_license_roundtrip.py``) and the caller carries a token (the 401 side is
covered in ``test_auth_guard.py``). What is left for this file is the device
behaviour itself, plus the role boundary: managing meters is admin-only,
reading them and Read now are not.

Three rules decide almost every assertion here:

* **ADR 0005** — identity comes from the meter, so a failed probe writes no row
  at all, and a refused Update changes nothing.
* **D7** — a client fault gets an HTTP status code; a meter fault gets a failure
  envelope with 502, because the upstream device failed, not the request. Read
  now is the deliberate exception (D10): it always answers 200 and reports the
  meter's refusal inside the payload, exactly as Test connection does.
* **ADR 0004** — status is whatever the last read proved, and ``paused`` is
  computed from ``enabled`` rather than stored.

``fake_meter`` swaps the driver registry for every test in this module, so
nothing here touches a real meter.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from conftest import mint_meter_activation_code
from fakes import FakeMeterState
from fastapi.testclient import TestClient

from arichds.acquisition.locks import EndpointLocks
from arichds.acquisition.poller import Poller, TickOutcome
from arichds.acquisition.probe import ProbeFailure
from arichds.licensing import activation_code as ac

pytestmark = pytest.mark.usefixtures("fake_meter")

DEVICE = {
    "name": "Main Incomer",
    "brand": "cewe",
    "model": "prometer100",
    "site_name": "Plant A",
    "transport": {"kind": "net", "host": "127.0.0.1", "port": 4059},
    "password": "hunter2",
}


def with_transport_overrides(payload: dict, overrides: dict) -> dict:
    """Merge *overrides* into *payload*, one payload for the whole file.

    Translates the test suite's long-standing flat ``host=``/``port=``
    override convention into the nested ``transport`` shape the API now
    requires (issue #9), so most of this file's call sites needed no change —
    only this function and the handful of places that built the payload dict
    by hand rather than through it.
    """
    overrides = dict(overrides)
    host = overrides.pop("host", None)
    port = overrides.pop("port", None)
    merged = {**payload, **overrides}
    if host is not None or port is not None:
        transport = dict(merged.get("transport", {}))
        if host is not None:
            transport["host"] = host
        if port is not None:
            transport["port"] = port
        merged["transport"] = transport
    return merged


def add_device(client: TestClient, fake_meter: FakeMeterState, *, serial: str = "SN-1", **overrides: object):
    """Create a device whose meter reports *serial*.

    Defaults ``meter_activation_code`` to one minted for *serial* (ADR 0019,
    issue #42) — an explicit override in *overrides* (a deliberately wrong or
    missing code, say) takes precedence.
    """
    fake_meter.meter_serial = serial
    payload = with_transport_overrides(DEVICE, overrides)
    payload.setdefault("meter_activation_code", mint_meter_activation_code(meter_serial=serial))
    return client.post("/api/devices", json=payload)


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

    def test_returns_the_password(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """Owner ruling, 2026-08-11 — passwords are not a security boundary."""
        response = add_device(admin_client, fake_meter)
        assert response.json()["data"]["password"] == "hunter2"

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


class RecordingScheduler:
    """A stand-in for the process Scheduler that records ``run_soon`` calls
    without running them — the same pattern ``RestartCountingPoller``/the raw
    ``Poller`` swap-in below already use for ``app.state.poller``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Callable[[], None]]] = []

    def run_soon(self, name: str, fn: Callable[[], None]) -> None:
        self.calls.append((name, fn))


class TestCreateEnqueuesTheFirstLoadProfileRead:
    """Issue #44, D1/D4/D5 — a new device's first load-profile read is queued
    on the Scheduler's one-shot lane, not run inline, and reads only the load
    profile, on the Manual path."""

    def test_it_enqueues_exactly_one_one_shot(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        scheduler = RecordingScheduler()
        admin_client.app.state.scheduler = scheduler

        add_device(admin_client, fake_meter, brand="mitsu", model="smw110")

        assert len(scheduler.calls) == 1

    def test_the_meter_is_not_read_a_second_time_during_the_request(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """D5 — ``POST /devices`` must return as fast as it does today: only
        the Create probe itself talks to the meter, not the queued one-shot."""
        scheduler = RecordingScheduler()
        admin_client.app.state.scheduler = scheduler

        add_device(admin_client, fake_meter, brand="mitsu", model="smw110")

        assert fake_meter.connects == 1, "something read the meter beyond the Create probe itself"
        assert fake_meter.disconnects == 1

    def test_the_queued_one_shot_reads_the_load_profile_on_the_manual_path(
        self, admin_client: TestClient, fake_meter: FakeMeterState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """D4 — never ``background=True``: the Poller worker's own immediate
        first tick (``poller.restart()``) predictably holds the endpoint, and
        a background acquisition would silently skip (ADR 0006) — the exact
        failure #43's review caught by mutation."""
        from arichds.acquisition.load_profile import LoadProfileReadResult

        scheduler = RecordingScheduler()
        admin_client.app.state.scheduler = scheduler
        calls: list[dict[str, object]] = []

        def spy(device_id: int, **kwargs: object) -> LoadProfileReadResult:
            calls.append({"device_id": device_id, **kwargs})
            return LoadProfileReadResult(supported=True, stored=0, through=None, budget_exhausted=False, error=None)

        monkeypatch.setattr("arichds.api.devices.read_and_store_load_profile", spy)

        data = add_device(admin_client, fake_meter, brand="mitsu", model="smw110").json()["data"]
        assert len(scheduler.calls) == 1
        _name, fn = scheduler.calls[0]
        fn()

        assert len(calls) == 1, "the queued one-shot did not call the load-profile reader exactly once"
        assert calls[0]["device_id"] == data["id"]
        assert calls[0].get("background") is not True, "the one-shot took the background path, not Manual"

    def test_the_queued_one_shot_never_calls_the_billing_reader(
        self, admin_client: TestClient, fake_meter: FakeMeterState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """D1 — billing already arrives within one Load Profile cycle through
        #43's Billing Change Check; the one-shot must call
        ``read_and_store_load_profile`` and nothing else."""
        scheduler = RecordingScheduler()
        admin_client.app.state.scheduler = scheduler
        billing_calls: list[int] = []
        monkeypatch.setattr(
            "arichds.api.devices.read_and_store_billing",
            lambda device_id, **kwargs: billing_calls.append(device_id),
        )

        add_device(admin_client, fake_meter, brand="mitsu", model="smw110")
        _name, fn = scheduler.calls[0]
        fn()

        assert billing_calls == [], "the one-shot called the billing reader — D1 forbids this"

    def test_a_raising_reader_does_not_escape_the_one_shot(
        self, admin_client: TestClient, fake_meter: FakeMeterState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The one-shot itself must never raise (Scheduler's own try/except is
        a second line of defence, not the only one)."""

        def boom(device_id: int, **kwargs: object) -> None:
            raise RuntimeError("the meter blew up")

        scheduler = RecordingScheduler()
        admin_client.app.state.scheduler = scheduler
        monkeypatch.setattr("arichds.api.devices.read_and_store_load_profile", boom)

        add_device(admin_client, fake_meter, brand="mitsu", model="smw110")
        _name, fn = scheduler.calls[0]
        fn()  # must not raise


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
            # The probe fails before the code is ever checked, so any
            # well-formed code clears Pydantic's required-field validation.
            payload = {**DEVICE, "meter_activation_code": mint_meter_activation_code(meter_serial="unused")}
            response = admin_client.post("/api/devices", json=payload)
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
        return client.put(f"/api/devices/{device_id}", json=with_transport_overrides(DEVICE, overrides))

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
        response = admin_client.put(
            f"/api/devices/{stored['id']}", json=with_transport_overrides(DEVICE, {"host": "10.0.0.5"})
        )
        assert response.status_code == 409

    def test_the_message_names_both_serials(
        self, admin_client: TestClient, fake_meter: FakeMeterState, stored: dict
    ) -> None:
        fake_meter.meter_serial = "SN-OTHER"
        detail = admin_client.put(
            f"/api/devices/{stored['id']}", json=with_transport_overrides(DEVICE, {"host": "10.0.0.5"})
        ).json()["detail"]
        assert "SN-1" in detail
        assert "SN-OTHER" in detail

    def test_not_one_column_changes(self, admin_client: TestClient, fake_meter: FakeMeterState, stored: dict) -> None:
        fake_meter.meter_serial = "SN-OTHER"
        admin_client.put(
            f"/api/devices/{stored['id']}",
            json=with_transport_overrides(DEVICE, {"name": "Renamed", "host": "10.0.0.5", "site_name": "Plant Z"}),
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
        response = admin_client.put(
            f"/api/devices/{stored['id']}", json=with_transport_overrides(DEVICE, {"host": "10.0.0.2"})
        )
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


SERIAL_DEVICE = {
    "name": "Serial Meter",
    "brand": "mitsu",
    "model": "smw110",
    "site_name": "Plant A",
    "transport": {
        "kind": "serial",
        "serial_port": "COM4",
        "baud_rate": 19200,
        "data_bits": 8,
        "parity": "None",
        "stop_bits": 1,
    },
    "password": "00000000000000000003",
}


class TestCreateAndUpdateOverSerial:
    """Probe-first identity on the serial transport (issue #9), exactly as the
    TCP path already proves in ``TestCreateDevice``/``TestCreateRefusedByTheMeter``/
    ``TestUpdateRefusedOnSerialMismatch`` above — same rules (ADR 0005), a
    different Transport Endpoint shape.
    """

    def add(self, client: TestClient, fake_meter: FakeMeterState, *, serial: str = "SN-SERIAL-1", **overrides: object):
        fake_meter.meter_serial = serial
        payload = {**SERIAL_DEVICE, **overrides}
        payload.setdefault("meter_activation_code", mint_meter_activation_code(meter_serial=serial))
        return client.post("/api/devices", json=payload)

    def test_creates_over_serial_and_the_endpoint_is_the_bare_com_port(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        response = self.add(admin_client, fake_meter)

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["endpoint"] == "COM4"
        assert data["transport"] == SERIAL_DEVICE["transport"]

    def test_a_refused_probe_writes_no_row(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        fake_meter.connect_error = ConnectionRefusedError("refused")
        response = self.add(admin_client, fake_meter)

        assert response.json()["success"] is False
        assert admin_client.get("/api/devices").json()["data"] == []

    def test_no_serial_refuses_the_create(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        fake_meter.meter_serial = None
        # The probe fails before the code is ever checked, so any well-formed
        # code clears Pydantic's required-field validation.
        payload = {**SERIAL_DEVICE, "meter_activation_code": mint_meter_activation_code(meter_serial="unused")}
        response = admin_client.post("/api/devices", json=payload)

        assert response.json()["error"]["reason"] == ProbeFailure.NO_SERIAL.value
        assert admin_client.get("/api/devices").json()["data"] == []

    def test_update_over_serial_re_probes(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = self.add(admin_client, fake_meter).json()["data"]["id"]
        connects_after_create = fake_meter.connects

        response = admin_client.put(f"/api/devices/{device_id}", json={**SERIAL_DEVICE, "name": "Renamed"})

        assert response.status_code == 200
        assert fake_meter.connects == connects_after_create + 1

    def test_update_over_serial_refuses_a_changed_serial(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = self.add(admin_client, fake_meter, serial="SN-SERIAL-1").json()["data"]["id"]
        fake_meter.meter_serial = "SN-OTHER"

        response = admin_client.put(f"/api/devices/{device_id}", json=SERIAL_DEVICE)

        assert response.status_code == 409


class TestTransportSchema:
    """The API requires only the fields the chosen transport needs — by
    schema, before any socket is opened (issue #9, Decision 7)."""

    def test_a_serial_request_needs_no_host_or_port(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        fake_meter.meter_serial = "SN-1"
        payload = {**SERIAL_DEVICE, "meter_activation_code": mint_meter_activation_code(meter_serial="SN-1")}
        assert admin_client.post("/api/devices", json=payload).status_code == 201

    def test_serial_missing_serial_port_is_422(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        transport = {k: v for k, v in SERIAL_DEVICE["transport"].items() if k != "serial_port"}
        response = admin_client.post("/api/devices", json={**SERIAL_DEVICE, "transport": transport})

        assert response.status_code == 422
        assert fake_meter.connects == 0

    def test_net_missing_host_is_422(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        response = admin_client.post("/api/devices", json={**DEVICE, "transport": {"kind": "net", "port": 4059}})

        assert response.status_code == 422
        assert fake_meter.connects == 0

    def test_an_unresolvable_parity_is_422(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        transport = {**SERIAL_DEVICE["transport"], "parity": "Weird"}
        response = admin_client.post("/api/devices", json={**SERIAL_DEVICE, "transport": transport})

        assert response.status_code == 422
        assert fake_meter.connects == 0

    def test_a_recognised_parity_is_accepted_case_insensitively(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.meter_serial = "SN-1"
        transport = {**SERIAL_DEVICE["transport"], "parity": "even"}
        payload = {
            **SERIAL_DEVICE,
            "transport": transport,
            "meter_activation_code": mint_meter_activation_code(meter_serial="SN-1"),
        }
        response = admin_client.post("/api/devices", json=payload)

        assert response.status_code == 201
        assert response.json()["data"]["transport"]["parity"] == "Even"


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
        """SPEC §3.3/§3.4 — M3 offered ``prometer100`` alone; issue #9 (M4a)
        added ``smw110``. The other seven land in M4c. Dropdown order, not
        insertion order into the driver registry, decides the order here —
        ``smw110`` sorts before ``prometer100`` in the catalog (Mitsubishi
        before CEWE)."""
        data = admin_client.get("/api/devices/catalog").json()["data"]
        assert [entry["model"] for entry in data] == ["smw110", "prometer100"]

    def test_it_carries_what_the_form_prefills(self, admin_client: TestClient) -> None:
        data = admin_client.get("/api/devices/catalog").json()["data"]
        entry = next(e for e in data if e["model"] == "prometer100")
        assert entry["ui_label"] == "Prometer 100"
        assert entry["fixed_password"] == "ABCD0001"
        assert entry["brand"] == "cewe"

    def test_it_carries_no_transport_information(self, admin_client: TestClient) -> None:
        """Issue #9 — transport is a property of the installation, not of the
        model; the catalog entry must not offer either field."""
        data = admin_client.get("/api/devices/catalog").json()["data"]
        for entry in data:
            assert "default_port" not in entry
            assert "supports_serial" not in entry

    def test_it_carries_the_capability_flags(self, admin_client: TestClient) -> None:
        data = admin_client.get("/api/devices/catalog").json()["data"]
        entry = next(e for e in data if e["model"] == "prometer100")
        assert entry["supports_battery"] is True
        assert entry["supports_energy_summary"] is False
        assert entry["supports_special_days"] is False

    def test_smw110_does_not_support_battery(self, admin_client: TestClient) -> None:
        """M7-2, issue #29 — pins the flag in the direction that changed:
        `smw110` has no `read_battery_status()` driver behind it, unlike the
        three CEWE models above."""
        data = admin_client.get("/api/devices/catalog").json()["data"]
        entry = next(e for e in data if e["model"] == "smw110")
        assert entry["supports_battery"] is False

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
            assert admin_client.get(f"/api/devices/{device['id']}/events").status_code == 200

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


class TestMeterActivationCode:
    """ADR 0019, issue #42 — the per-meter licensing gate.

    Checked once, at Create, against the **probed** serial and this
    machine's Machine ID (:data:`conftest.TEST_MACHINE_ID`, since every
    ``admin_client`` fixture patches ``LicenseService.machine_id`` to it).
    Update never re-checks it (Decision 3): ``_reject_changed_serial``
    (``TestUpdateRefusedOnSerialMismatch`` above) already refuses any Update
    whose probed serial differs from the stored one, unconditionally, which
    is stricter than a re-check would be.
    """

    def test_a_valid_code_creates_and_is_stored(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        code = mint_meter_activation_code(meter_serial="SN-1")
        response = add_device(admin_client, fake_meter, serial="SN-1", meter_activation_code=code)

        assert response.status_code == 201
        device_id = response.json()["data"]["id"]
        assert stored_secret(device_id, "meter_activation_code") == code

    def test_a_code_for_a_different_serial_is_refused_and_names_it(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        code = mint_meter_activation_code(meter_serial="SN-DIFFERENT")
        response = add_device(admin_client, fake_meter, serial="SN-1", meter_activation_code=code)

        assert response.status_code == 409
        assert "SN-DIFFERENT" in response.json()["detail"]
        assert admin_client.get("/api/devices").json()["data"] == []

    def test_a_code_for_a_different_machine_is_refused(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """A code bound to ``machine_id=""`` is "a different machine" from
        :data:`conftest.TEST_MACHINE_ID` — chosen deliberately: it is the one
        value that would *wrongly* validate if the handler ever hardcoded an
        empty string instead of reading ``license_service.machine_id``."""
        code = mint_meter_activation_code(meter_serial="SN-1", machine_id="")
        response = add_device(admin_client, fake_meter, serial="SN-1", meter_activation_code=code)

        assert response.status_code == 409
        assert "machine" in response.json()["detail"].lower()
        assert admin_client.get("/api/devices").json()["data"] == []

    def test_a_tampered_code_is_refused_and_does_not_echo_its_payload(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """The signature check fails before the serial in the payload can be
        trusted — so that serial must never reach the response, however
        distinctive it is."""
        code = mint_meter_activation_code(meter_serial="SN-1")
        payload_b64, signature_b64 = code.split(".")
        payload = json.loads(ac._b64url_decode(payload_b64))
        payload["meter_serial"] = "ATTACKER-CONTROLLED-SERIAL"
        tampered = ac.encode_activation_code(payload, ac._b64url_decode(signature_b64))

        response = add_device(admin_client, fake_meter, serial="SN-1", meter_activation_code=tampered)

        assert response.status_code == 409
        assert "ATTACKER-CONTROLLED-SERIAL" not in response.text
        assert admin_client.get("/api/devices").json()["data"] == []

    def test_a_missing_code_is_422_and_writes_nothing(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.meter_serial = "SN-1"
        response = admin_client.post("/api/devices", json=DEVICE)

        assert response.status_code == 422
        assert admin_client.get("/api/devices").json()["data"] == []

    def test_a_blank_code_is_422(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        fake_meter.meter_serial = "SN-1"
        response = admin_client.post("/api/devices", json={**DEVICE, "meter_activation_code": ""})

        assert response.status_code == 422
        assert admin_client.get("/api/devices").json()["data"] == []

    def test_a_full_quota_refuses_even_a_valid_code_without_probing(
        self, admin_client: TestClient, fake_meter: FakeMeterState, relicense
    ) -> None:
        relicense(admin_client, max_meters=1)
        add_device(admin_client, fake_meter, serial="SN-1")
        connects_before = fake_meter.connects

        code = mint_meter_activation_code(meter_serial="SN-2")
        response = add_device(admin_client, fake_meter, name="Second", serial="SN-2", meter_activation_code=code)

        assert response.status_code == 409
        assert fake_meter.connects == connects_before
        assert len(admin_client.get("/api/devices").json()["data"]) == 1

    def test_spare_quota_still_requires_a_valid_code(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        fake_meter.meter_serial = "SN-1"
        response = admin_client.post("/api/devices", json={**DEVICE, "meter_activation_code": "garbage"})

        assert response.status_code == 409
        assert admin_client.get("/api/devices/quota").json()["data"]["used"] == 0

    def test_update_refusing_a_changed_serial_leaves_the_stored_code_untouched(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        code = mint_meter_activation_code(meter_serial="SN-1")
        device_id = add_device(admin_client, fake_meter, serial="SN-1", meter_activation_code=code).json()["data"]["id"]

        fake_meter.meter_serial = "SN-OTHER"
        response = admin_client.put(f"/api/devices/{device_id}", json=DEVICE)

        assert response.status_code == 409
        assert stored_secret(device_id, "meter_activation_code") == code

    def test_update_fills_in_a_null_serial_without_a_code(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = insert_unidentified_device()
        fake_meter.meter_serial = "SN-NEW"

        response = admin_client.put(f"/api/devices/{device_id}", json=DEVICE)

        assert response.status_code == 200
        assert response.json()["data"]["meter_serial"] == "SN-NEW"

    def test_update_that_keeps_the_serial_needs_no_code_and_keeps_the_stored_one(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        code = mint_meter_activation_code(meter_serial="SN-1")
        device_id = add_device(admin_client, fake_meter, serial="SN-1", meter_activation_code=code).json()["data"]["id"]

        response = admin_client.put(f"/api/devices/{device_id}", json=DEVICE)

        assert response.status_code == 200
        assert stored_secret(device_id, "meter_activation_code") == code

    def test_a_null_code_row_is_served_normally_by_list_and_read_now(self, admin_client: TestClient) -> None:
        """Regression guard for grandfathering — a pre-gate row has no code
        and must keep working exactly as before."""
        device_id = insert_unidentified_device()
        from arichds.db.models import Device
        from arichds.db.session import session_scope

        with session_scope() as session:
            session.get(Device, device_id).meter_serial = "SN-REGRESSION"

        listed = admin_client.get("/api/devices").json()["data"][0]
        assert listed["meter_serial"] == "SN-REGRESSION"
        assert "meter_activation_code" not in listed

        assert admin_client.post(f"/api/devices/{device_id}/read-now").status_code == 200

    def test_device_out_has_no_meter_activation_code_field(self) -> None:
        from arichds.api.devices import DeviceOut

        assert "meter_activation_code" not in schema_property_names(DeviceOut)


class TestTestConnection:
    BODY = {
        "model": "prometer100",
        "transport": {"kind": "net", "host": "127.0.0.1", "port": 4059},
        "password": "ABCD0001",
    }

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


class TestMalformedStoredTransportNeverLies:
    """Code review (issue #9) — the response degrade path for a malformed or
    incomplete stored transport must never assert a `kind` different from
    what is actually stored.

    Neither Create nor Update can write a row like this (both validate by
    schema first), so it only happens to data this module did not write —
    but ``web/src/pages/Devices.tsx``'s ``toFormValues`` switches the whole
    form on ``transport.kind`` alone, so a serial row mislabeled `net` here
    would have its next Update save silently rewrite it to a TCP device.
    """

    def test_a_malformed_serial_row_reports_serial_not_net(self, admin_client: TestClient) -> None:
        device_id = insert_device_with_transport({"kind": "serial", "baud_rate": 19200})

        listed = admin_client.get("/api/devices").json()["data"][0]

        assert listed["id"] == device_id
        assert listed["transport"]["kind"] == "serial"

    def test_a_malformed_net_row_still_reports_net(self, admin_client: TestClient) -> None:
        """The other direction — an empty/legacy net row is not relabelled either."""
        device_id = insert_device_with_transport({})

        listed = admin_client.get("/api/devices").json()["data"][0]

        assert listed["id"] == device_id
        assert listed["transport"]["kind"] == "net"

    def test_it_never_500s(self, admin_client: TestClient) -> None:
        insert_device_with_transport({"kind": "serial"})
        assert admin_client.get("/api/devices").status_code == 200


class TestDeleteDevice:
    def test_deletes(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter).json()["data"]["id"]

        assert admin_client.delete(f"/api/devices/{device_id}").status_code == 200
        assert admin_client.get("/api/devices").json()["data"] == []

    def test_unknown_id_is_404(self, admin_client: TestClient) -> None:
        assert admin_client.delete("/api/devices/999").status_code == 404


class TestStatusIsReportedByTheList:
    """ADR 0004 — status comes from the Poller, and the list carries it (4a).

    Issue #6 draws the whole Devices tree from ``GET /api/devices``, so every
    status field has to be in that one response: an N+1 per device would make
    the tree's first paint scale with the meter count.
    """

    def test_a_created_device_is_online_immediately(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """The probe held a conversation with the meter seconds ago (ADR 0004)."""
        data = add_device(admin_client, fake_meter).json()["data"]
        assert data["status"] == "online"
        assert data["status_detail"] is None
        assert data["status_checked_at"] is not None

    def test_the_list_carries_all_three_fields_for_every_device(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        add_device(admin_client, fake_meter, serial="SN-1")
        add_device(admin_client, fake_meter, name="Second", host="10.0.0.2", serial="SN-2")

        listed = admin_client.get("/api/devices").json()["data"]

        assert len(listed) == 2
        for device in listed:
            assert {"status", "status_detail", "status_checked_at"} <= set(device)
            assert device["status"] == "online"

    def test_the_check_time_carries_an_explicit_utc_offset(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """D15 — SQLite hands back a naive datetime; the client must not guess."""
        checked_at = add_device(admin_client, fake_meter).json()["data"]["status_checked_at"]
        assert datetime.fromisoformat(checked_at).tzinfo is not None

    def test_a_pre_m3_row_reads_unknown(self, admin_client: TestClient) -> None:
        """Nothing has ever reported on it, so nothing is claimed about it."""
        insert_unidentified_device()
        device = admin_client.get("/api/devices").json()["data"][0]
        assert device["status"] == "paused"  # it is parked, and pause wins
        assert stored_status(device["id"]) == "unknown"


class TestOperatorActionsAreRecorded:
    """CONTEXT.md — a Device Event is written when something *changes* (4b)."""

    def test_creating_records_a_created_event_with_the_actor(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        device_id = add_device(admin_client, fake_meter).json()["data"]["id"]
        items = admin_client.get(f"/api/devices/{device_id}/events").json()["data"]["items"]

        assert [item["kind"] for item in items] == ["created"]
        assert items[0]["actor"] == "admin"

    def test_updating_records_an_updated_event(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter).json()["data"]["id"]
        admin_client.put(f"/api/devices/{device_id}", json={**DEVICE, "site_name": "Plant B"})

        kinds = [item["kind"] for item in events_of(admin_client, device_id)]
        assert kinds == ["updated", "created"]  # newest first

    def test_a_refused_create_records_nothing(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """No row, so no event about a row (ADR 0005)."""
        fake_meter.connect_error = ConnectionRefusedError("refused")
        add_device(admin_client, fake_meter)
        assert admin_client.get("/api/devices").json()["data"] == []


class TestPauseAndResume:
    """CONTEXT.md — Pause stops every *background* read of one device (4c)."""

    @pytest.fixture
    def device_id(self, admin_client: TestClient, fake_meter: FakeMeterState) -> int:
        return add_device(admin_client, fake_meter).json()["data"]["id"]

    def test_pausing_reports_paused(self, admin_client: TestClient, device_id: int) -> None:
        response = admin_client.post(f"/api/devices/{device_id}/pause")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["enabled"] is False
        assert data["status"] == "paused"

    def test_paused_is_computed_not_stored(self, admin_client: TestClient, device_id: int) -> None:
        """The stored column still says what the last read proved."""
        admin_client.post(f"/api/devices/{device_id}/pause")

        assert stored_status(device_id) == "online"
        assert admin_client.get("/api/devices").json()["data"][0]["status"] == "paused"

    @pytest.mark.parametrize("storable", ["online", "offline", "unknown"])
    def test_a_disabled_device_never_reads_online(
        self, admin_client: TestClient, device_id: int, storable: str
    ) -> None:
        admin_client.post(f"/api/devices/{device_id}/pause")
        set_stored_status(device_id, storable)

        assert admin_client.get("/api/devices").json()["data"][0]["status"] == "paused"

    def test_pausing_records_an_event_with_the_actor(self, admin_client: TestClient, device_id: int) -> None:
        admin_client.post(f"/api/devices/{device_id}/pause")

        event = events_of(admin_client, device_id)[0]
        assert event["kind"] == "paused"
        assert event["actor"] == "admin"

    def test_resuming_goes_back_to_unknown(self, admin_client: TestClient, device_id: int) -> None:
        """ADR 0004 — while paused nobody talked to the meter, so nobody knows."""
        admin_client.post(f"/api/devices/{device_id}/pause")
        data = admin_client.post(f"/api/devices/{device_id}/resume").json()["data"]

        assert data["enabled"] is True
        assert data["status"] == "unknown"
        assert data["status_detail"] is not None

    def test_resuming_clears_the_stale_check_time(self, admin_client: TestClient, device_id: int) -> None:
        """Reporting a pre-pause check time as current presents a stale fact as fresh."""
        admin_client.post(f"/api/devices/{device_id}/pause")
        data = admin_client.post(f"/api/devices/{device_id}/resume").json()["data"]

        assert data["status_checked_at"] is None

    def test_resuming_clears_the_strike_counter(self, admin_client: TestClient, device_id: int) -> None:
        admin_client.post(f"/api/devices/{device_id}/pause")
        admin_client.post(f"/api/devices/{device_id}/resume")

        assert stored_secret(device_id, "consecutive_failures") == 0

    def test_resuming_records_an_event(self, admin_client: TestClient, device_id: int) -> None:
        admin_client.post(f"/api/devices/{device_id}/pause")
        admin_client.post(f"/api/devices/{device_id}/resume")

        assert [event["kind"] for event in events_of(admin_client, device_id)] == ["resumed", "paused", "created"]

    def test_an_unknown_device_is_404(self, admin_client: TestClient) -> None:
        assert admin_client.post("/api/devices/999/pause").status_code == 404
        assert admin_client.post("/api/devices/999/resume").status_code == 404


class TestPauseAndResumeAreIdempotent:
    """D13 — a Device Event is recorded when something *changes*."""

    @pytest.fixture
    def device_id(self, admin_client: TestClient, fake_meter: FakeMeterState) -> int:
        return add_device(admin_client, fake_meter).json()["data"]["id"]

    def test_pausing_twice_is_still_a_200(self, admin_client: TestClient, device_id: int) -> None:
        admin_client.post(f"/api/devices/{device_id}/pause")
        response = admin_client.post(f"/api/devices/{device_id}/pause")

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "paused"

    def test_pausing_twice_records_one_event(self, admin_client: TestClient, device_id: int) -> None:
        admin_client.post(f"/api/devices/{device_id}/pause")
        admin_client.post(f"/api/devices/{device_id}/pause")

        assert [event["kind"] for event in events_of(admin_client, device_id)].count("paused") == 1

    def test_resuming_a_running_device_records_nothing(self, admin_client: TestClient, device_id: int) -> None:
        admin_client.post(f"/api/devices/{device_id}/resume")

        assert [event["kind"] for event in events_of(admin_client, device_id)] == ["created"]

    def test_a_no_op_resume_does_not_disturb_the_status(self, admin_client: TestClient, device_id: int) -> None:
        """It must not reset an online device to unknown for nothing."""
        admin_client.post(f"/api/devices/{device_id}/resume")

        assert stored_status(device_id) == "online"

    def test_a_no_op_never_respawns_every_worker_on_the_site(self, admin_client: TestClient, device_id: int) -> None:
        poller = RestartCountingPoller()
        admin_client.app.state.poller = poller

        admin_client.post(f"/api/devices/{device_id}/pause")
        assert poller.restarts == 1

        admin_client.post(f"/api/devices/{device_id}/pause")
        assert poller.restarts == 1


class TestPauseStopsTheBackgroundWorker:
    """Trap 1 — writing ``enabled = False`` alone stops nothing.

    ``Device.enabled`` is read in exactly one place, ``_enabled_devices()``,
    which only ``start()`` calls. A worker loops over a snapshot and never
    re-reads it, so without the restart the meter keeps being read forever.
    """

    @pytest.fixture
    def device_id(self, admin_client: TestClient, fake_meter: FakeMeterState) -> int:
        return add_device(admin_client, fake_meter).json()["data"]["id"]

    def test_a_running_worker_stops_ticking(self, admin_client: TestClient, device_id: int) -> None:
        ticks: list[float] = []
        poller = Poller(interval_sec=0.05, poll_fn=count_tick(ticks), locks=EndpointLocks())
        admin_client.app.state.poller = poller
        try:
            poller.start()
            assert wait_for(lambda: len(ticks) >= 1), "the poller never ticked before the pause"

            assert admin_client.post(f"/api/devices/{device_id}/pause").status_code == 200

            # A tick already inside poll_fn when stop() was signalled is allowed
            # to finish — that is stop()'s designed behaviour — so sample after
            # the call rather than asserting zero ticks since it.
            settled = len(ticks)
            time.sleep(0.5)
            assert len(ticks) == settled
        finally:
            poller.stop()

    def test_resume_brings_the_worker_back(self, admin_client: TestClient, device_id: int) -> None:
        ticks: list[float] = []
        poller = Poller(interval_sec=0.05, poll_fn=count_tick(ticks), locks=EndpointLocks())
        admin_client.app.state.poller = poller
        try:
            poller.start()
            admin_client.post(f"/api/devices/{device_id}/pause")
            time.sleep(0.2)
            settled = len(ticks)

            assert admin_client.post(f"/api/devices/{device_id}/resume").status_code == 200

            assert wait_for(lambda: len(ticks) > settled), "no tick was recorded after the resume"
        finally:
            poller.stop()

    def test_the_pause_survives_a_process_restart(self, admin_client: TestClient, device_id: int) -> None:
        """It is a persisted column, not an in-memory flag (CONTEXT.md — Pause)."""
        admin_client.post(f"/api/devices/{device_id}/pause")

        fresh = Poller(interval_sec=0.05, locks=EndpointLocks())
        try:
            fresh.start()
            assert fresh._threads == []
        finally:
            fresh.stop()


class TestReadNow:
    """SPEC §3.3 — the Manual Read behind the Read now button (4d).

    At M3 the list holds one job, ``liveness``: an identity read that proves the
    meter answers a real register read and writes no Interval Reading (ADR 0007).
    """

    @pytest.fixture
    def device_id(self, admin_client: TestClient, fake_meter: FakeMeterState) -> int:
        return add_device(admin_client, fake_meter).json()["data"]["id"]

    def test_a_reachable_meter_answers_ok(self, admin_client: TestClient, device_id: int) -> None:
        response = admin_client.post(f"/api/devices/{device_id}/read-now")

        assert response.status_code == 200
        data = response.json()["data"]
        # Three entries from M6a on: the load-profile and billing jobs both
        # report that this model has neither rather than silently leaving the
        # list short (D12). ``TestReadNowRunsTheLoadProfileJob`` owns those
        # entries.
        assert data["results"][0] == {
            "job": "liveness",
            "ok": True,
            "detail": "The meter answered at 127.0.0.1:4059.",
        }
        assert [result["job"] for result in data["results"]] == ["liveness", "load_profile", "billing"]
        assert data["status"] == "online"
        assert data["checked_at"] is not None

    def test_it_reads_the_meter(self, admin_client: TestClient, fake_meter: FakeMeterState, device_id: int) -> None:
        connects = fake_meter.connects
        admin_client.post(f"/api/devices/{device_id}/read-now")
        assert fake_meter.connects == connects + 1

    def test_a_refusing_meter_is_still_a_200(
        self, admin_client: TestClient, fake_meter: FakeMeterState, device_id: int
    ) -> None:
        """D10 — from M5 the list can be partially successful, which no single
        HTTP status can express."""
        fake_meter.connect_error = ConnectionRefusedError("refused")
        response = admin_client.post(f"/api/devices/{device_id}/read-now")

        assert response.status_code == 200
        assert response.json()["success"] is True
        result = response.json()["data"]["results"][0]
        assert result["ok"] is False
        assert "127.0.0.1:4059" in result["detail"]

    def test_it_writes_no_interval_reading(self, admin_client: TestClient, device_id: int) -> None:
        """ADR 0007 — a liveness read is not a data read."""
        admin_client.post(f"/api/devices/{device_id}/read-now")
        assert count_readings(device_id) == 0

    def test_it_never_puts_the_serial_in_the_detail(
        self, admin_client: TestClient, fake_meter: FakeMeterState, device_id: int
    ) -> None:
        """D9 — Read now never re-identifies the meter; that is Update's job."""
        fake_meter.meter_serial = "SN-SOMETHING-ELSE"
        response = admin_client.post(f"/api/devices/{device_id}/read-now")

        assert response.status_code == 200
        assert "SN-SOMETHING-ELSE" not in response.text

    def test_it_carries_no_electrical_value_at_all(self) -> None:
        """Asserted against the schema, not one example (ADR 0007).

        Derived from ``IntervalReading`` rather than hardcoded, so a
        measurement added later is covered without anyone remembering to.
        """
        from dataclasses import fields

        from arichds.acquisition.drivers.base import IntervalReading
        from arichds.api.devices import ReadNowOut

        measurements = {f.name for f in fields(IntervalReading)} - {
            "read_at",
            "source",
            "logger_id",
            "interval_sec",
        }
        assert measurements, "the measurement set must not be empty, or this test proves nothing"
        assert schema_property_names(ReadNowOut) & measurements == set()

    def test_the_results_are_a_list(self, admin_client: TestClient, device_id: int) -> None:
        """M5 adds ``load_profile`` and M6 ``billing`` to this same list."""
        data = admin_client.post(f"/api/devices/{device_id}/read-now").json()["data"]
        assert isinstance(data["results"], list)

    def test_it_works_on_a_paused_device(self, admin_client: TestClient, device_id: int) -> None:
        """Pause governs background reads only (CONTEXT.md — Pause)."""
        admin_client.post(f"/api/devices/{device_id}/pause")

        response = admin_client.post(f"/api/devices/{device_id}/read-now")

        assert response.status_code == 200
        assert response.json()["data"]["results"][0]["ok"] is True
        # The device is still paused, and the API still says so.
        assert response.json()["data"]["status"] == "paused"

    def test_three_failures_take_it_offline(
        self, admin_client: TestClient, fake_meter: FakeMeterState, device_id: int
    ) -> None:
        """A Manual Read is a real read, so it is real evidence (ADR 0004)."""
        fake_meter.connect_error = ConnectionRefusedError("refused")
        for _ in range(3):
            response = admin_client.post(f"/api/devices/{device_id}/read-now")

        assert response.json()["data"]["status"] == "offline"
        assert stored_status(device_id) == "offline"

    def test_the_offline_transition_has_no_actor(
        self, admin_client: TestClient, fake_meter: FakeMeterState, device_id: int
    ) -> None:
        """D11 — a person pressed the button, but nobody changed the meter."""
        fake_meter.connect_error = ConnectionRefusedError("refused")
        for _ in range(3):
            admin_client.post(f"/api/devices/{device_id}/read-now")

        offline = [event for event in events_of(admin_client, device_id) if event["kind"] == "offline"]
        assert len(offline) == 1
        assert offline[0]["actor"] is None

    def test_a_success_after_that_comes_back_online(
        self, admin_client: TestClient, fake_meter: FakeMeterState, device_id: int
    ) -> None:
        fake_meter.connect_error = ConnectionRefusedError("refused")
        for _ in range(3):
            admin_client.post(f"/api/devices/{device_id}/read-now")
        fake_meter.connect_error = None

        assert admin_client.post(f"/api/devices/{device_id}/read-now").json()["data"]["status"] == "online"

    def test_a_model_with_no_driver_is_not_a_strike(self, admin_client: TestClient) -> None:
        """A configuration problem, not a meter failure — it must not reach offline."""
        device_id = insert_undrivable_device()

        for _ in range(3):
            response = admin_client.post(f"/api/devices/{device_id}/read-now")

        result = response.json()["data"]["results"][0]
        assert response.status_code == 200
        assert result["ok"] is False
        assert "sim" in result["detail"]
        assert response.json()["data"]["status"] != "offline"
        assert stored_status(device_id) == "unknown"

    def test_an_unknown_device_is_404(self, admin_client: TestClient) -> None:
        assert admin_client.post("/api/devices/999/read-now").status_code == 404

    def test_it_never_echoes_the_password(
        self, admin_client: TestClient, fake_meter: FakeMeterState, device_id: int
    ) -> None:
        fake_meter.connect_error = ConnectionRefusedError("refused")
        assert "hunter2" not in admin_client.post(f"/api/devices/{device_id}/read-now").text


class TestMoreHistoryRemainsSentence:
    """D10, issue #44 — the "More history remains" invitation gates on
    ``LoadProfileReadResult.history_remains``, not ``budget_exhausted`` alone.
    Pressing Read now again after a call that stored nothing re-walks the
    identical empty window (the property's own docstring) — provably not
    progress — so the sentence must not appear in that case, the v1 symptom
    recorded at SPEC.md:457."""

    def test_absent_when_the_walk_stored_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from arichds.acquisition.load_profile import LoadProfileReadResult
        from arichds.api.devices import _read_load_profile_job

        monkeypatch.setattr(
            "arichds.api.devices.read_and_store_load_profile",
            lambda device_id, **kwargs: LoadProfileReadResult(
                supported=True, stored=0, through=None, budget_exhausted=True, error=None
            ),
        )

        result = _read_load_profile_job(1, "smw110")

        assert "More history remains" not in result.detail

    def test_present_when_the_walk_stored_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from arichds.acquisition.load_profile import LoadProfileReadResult
        from arichds.api.devices import _read_load_profile_job

        monkeypatch.setattr(
            "arichds.api.devices.read_and_store_load_profile",
            lambda device_id, **kwargs: LoadProfileReadResult(
                supported=True,
                stored=5,
                through=datetime(2026, 8, 7, tzinfo=UTC),
                budget_exhausted=True,
                error=None,
                advanced=True,
            ),
        )

        result = _read_load_profile_job(1, "smw110")

        assert "More history remains" in result.detail


class TestReadNowRunsTheLoadProfileJob:
    """M5a-1 (issue #15), D12 — ``results`` holds one entry per job Read now
    **considered**, not per job that ran.

    The Read-now modal renders a row per entry and nothing at all for an absent
    one (``web/src/pages/Devices.tsx:632``), so a job that silently did not run
    tells the operator nothing. ``ok=False`` for a job that could not run is
    already this handler's established meaning — the unknown-model branch
    reports the liveness job that way having touched no meter.

    Every assertion is on the **whole** job list: ``results[0]`` would pass just
    as happily with the second entry missing.
    """

    @pytest.fixture
    def prometer_id(self, admin_client: TestClient, fake_meter: FakeMeterState) -> int:
        """A model whose driver has no load profile — the default payload."""
        return add_device(admin_client, fake_meter).json()["data"]["id"]

    @pytest.fixture
    def smw110_id(self, admin_client: TestClient, fake_meter: FakeMeterState) -> int:
        """The one model that can read a load profile today."""
        response = add_device(admin_client, fake_meter, brand="mitsu", model="smw110", name="Mitsu Feeder")
        assert response.status_code == 201, response.text
        return response.json()["data"]["id"]

    def one_recent_interval(self) -> list:
        """One Interval Reading an hour old, so it lands inside the walk's window."""
        from datetime import UTC, timedelta

        from arichds.acquisition.drivers.base import IntervalReading

        return [
            IntervalReading(
                read_at=(datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=0),
                source="dlms",
                logger_id=1,
                interval_sec=900,
                volt_l1=228.188,
                import_active_kwh=13.130,
            )
        ]

    def jobs(self, response) -> list[str]:
        return [result["job"] for result in response.json()["data"]["results"]]

    def test_a_model_without_a_load_profile_still_gets_an_entry(
        self, admin_client: TestClient, prometer_id: int
    ) -> None:
        response = admin_client.post(f"/api/devices/{prometer_id}/read-now")

        assert self.jobs(response) == ["liveness", "load_profile", "billing"]
        results = response.json()["data"]["results"]
        assert results[0]["ok"] is True
        assert results[1]["ok"] is False
        assert "no load profile in this build" in results[1]["detail"]
        assert results[2]["ok"] is False
        assert "no billing profile in this build" in results[2]["detail"]
        assert count_readings(prometer_id) == 0

    def test_a_supported_model_stores_its_intervals(
        self, admin_client: TestClient, fake_meter: FakeMeterState, smw110_id: int
    ) -> None:
        fake_meter.load_profile_rows = self.one_recent_interval()

        response = admin_client.post(f"/api/devices/{smw110_id}/read-now")

        assert self.jobs(response) == ["liveness", "load_profile", "billing"]
        load_profile = response.json()["data"]["results"][1]
        assert load_profile["ok"] is True
        assert "Stored 1 Interval Readings up to" in load_profile["detail"]
        assert count_readings(smw110_id) == 1

    def test_a_supported_model_with_nothing_new_says_so(self, admin_client: TestClient, smw110_id: int) -> None:
        response = admin_client.post(f"/api/devices/{smw110_id}/read-now")

        assert self.jobs(response) == ["liveness", "load_profile", "billing"]
        load_profile = response.json()["data"]["results"][1]
        assert load_profile["ok"] is True
        assert load_profile["detail"] == "The meter had no new intervals to store."

    def test_a_meter_that_refuses_the_liveness_read_skips_the_load_profile_and_billing(
        self, admin_client: TestClient, fake_meter: FakeMeterState, smw110_id: int
    ) -> None:
        fake_meter.connect_error = ConnectionRefusedError("refused")

        response = admin_client.post(f"/api/devices/{smw110_id}/read-now")

        assert self.jobs(response) == ["liveness", "load_profile", "billing"]
        results = response.json()["data"]["results"]
        assert results[0]["ok"] is False
        assert results[1] == {
            "job": "load_profile",
            "ok": False,
            "detail": "Skipped — the meter did not answer the liveness read.",
        }
        assert results[2] == {
            "job": "billing",
            "ok": False,
            "detail": "Skipped — the meter did not answer the liveness read.",
        }
        # Skipped means skipped: the endpoint was never asked for a second time.
        assert fake_meter.load_profile_windows == []
        assert fake_meter.billing_reads == 0

    def test_a_supported_model_stores_its_billing_periods(
        self, admin_client: TestClient, fake_meter: FakeMeterState, smw110_id: int
    ) -> None:
        from arichds.acquisition.drivers.base import BillingReading

        fake_meter.billing_rows = [
            BillingReading(
                bill_date=datetime(2026, 8, 7, 4, 37, 58, tzinfo=UTC),
                source="dlms",
                is_open=True,
                import_active_kwh_total=200464.501,
            ),
            BillingReading(
                bill_date=datetime(2026, 7, 31, 17, 0, 0, tzinfo=UTC),
                source="dlms",
                is_open=False,
                import_active_kwh_total=198685.030,
            ),
        ]

        response = admin_client.post(f"/api/devices/{smw110_id}/read-now")

        assert self.jobs(response) == ["liveness", "load_profile", "billing"]
        billing = response.json()["data"]["results"][2]
        assert billing["ok"] is True
        assert "1 closed billing period" in billing["detail"]
        assert "Open Period" in billing["detail"]

    def test_a_failed_billing_read_reports_the_sentence(
        self, admin_client: TestClient, fake_meter: FakeMeterState, smw110_id: int
    ) -> None:
        fake_meter.billing_error = TimeoutError("the meter went away")

        response = admin_client.post(f"/api/devices/{smw110_id}/read-now")

        billing = response.json()["data"]["results"][2]
        assert billing["ok"] is False
        assert "TimeoutError" in billing["detail"]

    def test_a_failed_billing_read_is_not_a_strike(
        self, admin_client: TestClient, fake_meter: FakeMeterState, smw110_id: int
    ) -> None:
        """ADR 0004 — only ``liveness`` touches device status."""
        fake_meter.billing_error = TimeoutError("the meter went away")

        response = admin_client.post(f"/api/devices/{smw110_id}/read-now")

        assert response.json()["data"]["status"] == "online"
        assert stored_status(smw110_id) == "online"

    def test_a_failed_load_profile_read_reports_what_it_stored(
        self, admin_client: TestClient, fake_meter: FakeMeterState, smw110_id: int
    ) -> None:
        fake_meter.load_profile_error = TimeoutError("the meter went away")

        response = admin_client.post(f"/api/devices/{smw110_id}/read-now")

        assert response.status_code == 200
        load_profile = response.json()["data"]["results"][1]
        assert load_profile["ok"] is False
        assert "Stored 0 Interval Readings before the read stopped" in load_profile["detail"]

    def test_a_failed_load_profile_read_is_not_a_strike(
        self, admin_client: TestClient, fake_meter: FakeMeterState, smw110_id: int
    ) -> None:
        """D11 / ADR 0004 — status comes from the Poller's evidence, and the
        liveness read is that evidence. A load profile that failed afterwards
        must not undo an Online the meter just earned."""
        fake_meter.load_profile_error = TimeoutError("the meter went away")

        response = admin_client.post(f"/api/devices/{smw110_id}/read-now")

        assert response.json()["data"]["status"] == "online"
        assert stored_status(smw110_id) == "online"

    def test_a_model_with_no_driver_reports_the_liveness_job_alone(self, admin_client: TestClient) -> None:
        """There is no driver to ask whether it has a load profile."""
        device_id = insert_undrivable_device()

        response = admin_client.post(f"/api/devices/{device_id}/read-now")

        assert self.jobs(response) == ["liveness"]

    def test_an_unusable_transport_reports_the_liveness_job_alone(self, admin_client: TestClient) -> None:
        """Same reason: nothing can be built to ask."""
        device_id = insert_device_with_transport({"kind": "net"})

        response = admin_client.post(f"/api/devices/{device_id}/read-now")

        assert self.jobs(response) == ["liveness"]


class TestClearReadings:
    """SPEC §3.3 — Delete all data keeps the evidence of who deleted it (4f)."""

    @pytest.fixture
    def device_id(self, admin_client: TestClient, fake_meter: FakeMeterState) -> int:
        device_id = add_device(admin_client, fake_meter).json()["data"]["id"]
        write_readings(device_id, 3)
        return device_id

    def clear(self, client: TestClient, device_id: int, name: str):
        """POST the typed-confirmation body."""
        return client.post(f"/api/devices/{device_id}/readings/clear", json={"confirm_name": name})

    def test_it_deletes_the_readings_and_says_how_many(self, admin_client: TestClient, device_id: int) -> None:
        response = self.clear(admin_client, device_id, "Main Incomer")

        assert response.status_code == 200
        assert response.json()["data"] == 3
        assert count_readings(device_id) == 0

    def test_the_device_row_survives(self, admin_client: TestClient, device_id: int) -> None:
        self.clear(admin_client, device_id, "Main Incomer")
        assert len(admin_client.get("/api/devices").json()["data"]) == 1

    def test_the_history_survives_and_records_who_did_it(self, admin_client: TestClient, device_id: int) -> None:
        """The events are kept precisely as evidence of the deletion."""
        self.clear(admin_client, device_id, "Main Incomer")

        event = events_of(admin_client, device_id)[0]
        assert event["kind"] == "data_cleared"
        assert event["actor"] == "admin"
        assert event["detail"] == "Deleted 3 interval readings and 0 billing periods."

    def test_a_wrong_name_is_a_409(self, admin_client: TestClient, device_id: int) -> None:
        assert self.clear(admin_client, device_id, "main incomer").status_code == 409

    def test_a_wrong_name_deletes_nothing(self, admin_client: TestClient, device_id: int) -> None:
        self.clear(admin_client, device_id, "Wrong Name")
        assert count_readings(device_id) == 3

    def test_the_message_does_not_echo_the_correct_name(self, admin_client: TestClient, device_id: int) -> None:
        """D14 — echoing it turns the typed confirmation into copy-paste."""
        detail = self.clear(admin_client, device_id, "Wrong Name").json()["detail"]
        assert "Main Incomer" not in detail
        assert detail == "The confirmation name does not match this device. Nothing was deleted."

    def test_clearing_an_empty_device_reports_zero(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        device_id = add_device(admin_client, fake_meter, name="Second", host="10.0.0.2", serial="SN-2").json()["data"][
            "id"
        ]
        response = self.clear(admin_client, device_id, "Second")

        assert response.json()["data"] == 0
        assert events_of(admin_client, device_id)[0]["detail"] == "Deleted 0 interval readings and 0 billing periods."

    def test_it_deletes_billing_periods_too_and_counts_them_in_the_total(
        self, admin_client: TestClient, device_id: int
    ) -> None:
        write_billing_rows(device_id, 2)

        response = self.clear(admin_client, device_id, "Main Incomer")

        assert response.json()["data"] == 5  # 3 interval readings + 2 billing periods
        assert count_readings(device_id) == 0
        assert count_billing_rows(device_id) == 0

    def test_the_device_event_names_both_counts(self, admin_client: TestClient, device_id: int) -> None:
        write_billing_rows(device_id, 2)

        self.clear(admin_client, device_id, "Main Incomer")

        event = events_of(admin_client, device_id)[0]
        assert event["detail"] == "Deleted 3 interval readings and 2 billing periods."

    def test_a_wrong_name_deletes_no_billing_periods_either(self, admin_client: TestClient, device_id: int) -> None:
        write_billing_rows(device_id, 2)

        self.clear(admin_client, device_id, "Wrong Name")

        assert count_billing_rows(device_id) == 2

    def test_it_leaves_another_device_alone(
        self, admin_client: TestClient, fake_meter: FakeMeterState, device_id: int
    ) -> None:
        other = add_device(admin_client, fake_meter, name="Second", host="10.0.0.2", serial="SN-2").json()["data"]["id"]
        write_readings(other, 2)

        self.clear(admin_client, device_id, "Main Incomer")

        assert count_readings(other) == 2

    def test_an_unknown_device_is_404(self, admin_client: TestClient) -> None:
        assert self.clear(admin_client, 999, "whatever").status_code == 404


class TestDeviceHistory:
    """The History drawer's page (4e)."""

    @pytest.fixture
    def device_id(self, admin_client: TestClient, fake_meter: FakeMeterState) -> int:
        device_id = add_device(admin_client, fake_meter).json()["data"]["id"]
        admin_client.post(f"/api/devices/{device_id}/pause")
        admin_client.post(f"/api/devices/{device_id}/resume")
        return device_id

    def test_newest_first(self, admin_client: TestClient, device_id: int) -> None:
        """The id tiebreak carries this: SQLite's clock has one-second resolution."""
        assert [event["kind"] for event in events_of(admin_client, device_id)] == ["resumed", "paused", "created"]

    def test_total_is_the_unpaged_count(self, admin_client: TestClient, device_id: int) -> None:
        page = admin_client.get(f"/api/devices/{device_id}/events?limit=1").json()["data"]

        assert page["total"] == 3
        assert len(page["items"]) == 1
        assert page["limit"] == 1
        assert page["offset"] == 0

    def test_offset_pages_through(self, admin_client: TestClient, device_id: int) -> None:
        page = admin_client.get(f"/api/devices/{device_id}/events?limit=1&offset=2").json()["data"]

        assert [event["kind"] for event in page["items"]] == ["created"]
        assert page["offset"] == 2

    def test_an_automatic_transition_has_no_actor(
        self, admin_client: TestClient, fake_meter: FakeMeterState, device_id: int
    ) -> None:
        fake_meter.connect_error = ConnectionRefusedError("refused")
        for _ in range(3):
            admin_client.post(f"/api/devices/{device_id}/read-now")

        events = events_of(admin_client, device_id)
        assert events[0]["kind"] == "offline"
        assert events[0]["actor"] is None
        assert all(event["actor"] == "admin" for event in events[1:])

    def test_the_timestamp_carries_an_explicit_utc_offset(self, admin_client: TestClient, device_id: int) -> None:
        created_at = events_of(admin_client, device_id)[0]["created_at"]
        assert datetime.fromisoformat(created_at).tzinfo is not None

    def test_a_device_with_no_history_pages_cleanly(self, admin_client: TestClient) -> None:
        device_id = insert_unidentified_device()
        page = admin_client.get(f"/api/devices/{device_id}/events").json()["data"]

        assert page == {"items": [], "total": 0, "limit": 50, "offset": 0}

    def test_the_page_size_is_bounded(self, admin_client: TestClient, device_id: int) -> None:
        assert admin_client.get(f"/api/devices/{device_id}/events?limit=201").status_code == 422
        assert admin_client.get(f"/api/devices/{device_id}/events?limit=0").status_code == 422
        assert admin_client.get(f"/api/devices/{device_id}/events?offset=-1").status_code == 422

    def test_an_unknown_device_is_404(self, admin_client: TestClient) -> None:
        assert admin_client.get("/api/devices/999/events").status_code == 404

    def test_deleting_the_device_takes_its_history(self, admin_client: TestClient, device_id: int) -> None:
        admin_client.delete(f"/api/devices/{device_id}")
        assert admin_client.get(f"/api/devices/{device_id}/events").status_code == 404


class TestM32RoleBoundary:
    """SPEC §3.2 — read and Read now for everyone, mutations for admins."""

    @pytest.fixture
    def device_id(self, admin_client: TestClient, fake_meter: FakeMeterState) -> int:
        return add_device(admin_client, fake_meter).json()["data"]["id"]

    def test_a_user_cannot_pause(self, user_client: TestClient, device_id: int) -> None:
        assert user_client.post(f"/api/devices/{device_id}/pause").status_code == 403

    def test_a_user_cannot_resume(self, admin_client: TestClient, user_client: TestClient, device_id: int) -> None:
        admin_client.post(f"/api/devices/{device_id}/pause")
        assert user_client.post(f"/api/devices/{device_id}/resume").status_code == 403

    def test_a_user_cannot_clear_the_readings(self, user_client: TestClient, device_id: int) -> None:
        write_readings(device_id, 2)
        response = user_client.post(f"/api/devices/{device_id}/readings/clear", json={"confirm_name": "Main Incomer"})
        assert response.status_code == 403

    def test_a_refused_clear_deletes_nothing(self, user_client: TestClient, device_id: int) -> None:
        write_readings(device_id, 2)
        user_client.post(f"/api/devices/{device_id}/readings/clear", json={"confirm_name": "Main Incomer"})
        assert count_readings(device_id) == 2

    def test_a_user_can_read_now(self, user_client: TestClient, device_id: int) -> None:
        """Read now is granted to every role (SPEC §3.2)."""
        assert user_client.post(f"/api/devices/{device_id}/read-now").status_code == 200

    def test_a_user_can_read_the_history(self, user_client: TestClient, device_id: int) -> None:
        assert user_client.get(f"/api/devices/{device_id}/events").status_code == 200


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
                json={
                    "model": "prometer100",
                    "transport": {"kind": "net", "host": "127.0.0.1", "port": 4059},
                    "password": "diag-secret",
                },
            )

        for secret in ("hunter2", "CIPHER-1", "AUTH-1", "another-secret", "diag-secret"):
            assert secret not in caplog.text

    def test_the_list_never_carries_the_cipher_keys(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """The password is the deliberate exception (owner ruling, 2026-08-11) —
        see ``test_returns_the_password``. The two cipher keys are not."""
        add_device(admin_client, fake_meter, block_cipher_key="CIPHER-1", authentication_key="AUTH-1")
        response = admin_client.get("/api/devices")
        for secret in ("CIPHER-1", "AUTH-1"):
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
            json={
                "model": "prometer100",
                "transport": {"kind": "net", "host": "127.0.0.1", "port": 4059},
                "password": "",
            },
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

    def test_the_403_is_not_a_401(self, user_client: TestClient) -> None:
        """Authenticated-but-not-allowed is a different answer from unauthenticated."""
        response = user_client.post("/api/devices", json=DEVICE)

        assert response.status_code == 403
        assert "WWW-Authenticate" not in response.headers


# ─── Helpers that reach into the database ─────────────────────────────────────
#
# The cipher keys are never returned by any endpoint, so the only honest way to
# assert "the stored value is unchanged" is to read the column. The password is
# returned by `GET /api/devices` (owner ruling, 2026-08-11) but these helpers
# still read the column directly — most callers here assert against a device
# fetched *before* the change under test, and going straight to the database
# avoids re-fetching just to check one field.


def stored_password(device_id: int) -> str:
    """Return the password column of *device_id*."""
    return stored_secret(device_id, "password")


def stored_status(device_id: int) -> str:
    """Return the raw ``status`` column — what is *stored*, not what is shown."""
    return stored_secret(device_id, "status")


def set_stored_status(device_id: int, value: str) -> None:
    """Force the raw ``status`` column, to prove what the API does with it."""
    from arichds.db.models import Device
    from arichds.db.session import session_scope

    with session_scope() as session:
        session.get(Device, device_id).status = value


class RestartCountingPoller(Poller):
    """A Poller that counts :meth:`restart` calls instead of running anything.

    ``enabled=False`` so ``start()`` is a no-op — the question these tests ask
    is whether a handler decided to respawn every worker on the site, which is a
    decision, not a thread.
    """

    def __init__(self) -> None:
        super().__init__(enabled=False, locks=EndpointLocks())
        self.restarts = 0

    def restart(self) -> None:
        """Count the call."""
        self.restarts += 1
        super().restart()


def count_tick(ticks: list[float]) -> Callable[..., TickOutcome]:
    """A ``poll_fn`` that records when it ran and reports nothing.

    ``SKIPPED`` keeps it inert (D3), so the tick count is observable without the
    background thread rewriting the status columns under the assertions.
    """

    def poll(device, locks, shutdown) -> TickOutcome:  # noqa: ANN001
        ticks.append(time.monotonic())
        return TickOutcome.SKIPPED

    return poll


def wait_for(predicate: Callable[[], bool], *, timeout: float = 5.0) -> bool:
    """Poll *predicate* until it is true or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def events_of(client: TestClient, device_id: int) -> list[dict]:
    """Every Device Event of *device_id* as the API returns them (newest first)."""
    response = client.get(f"/api/devices/{device_id}/events")
    assert response.status_code == 200, response.text
    return response.json()["data"]["items"]


def stored_secret(device_id: int, column: str) -> str:
    """Return one never-exposed column of *device_id*."""
    from arichds.db.models import Device
    from arichds.db.session import session_scope

    with session_scope() as session:
        return getattr(session.get(Device, device_id), column)


def insert_undrivable_device() -> int:
    """Insert an enabled row whose model has no driver in this build."""
    from arichds.db.models import Device
    from arichds.db.session import session_scope

    with session_scope() as session:
        device = Device(
            name="Old Sim",
            brand="SIM",
            model="sim",
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            enabled=True,
        )
        session.add(device)
        session.flush()
        return device.id


def write_readings(device_id: int, count: int) -> None:
    """Write *count* Interval Readings straight into the table."""
    from datetime import UTC, timedelta

    from arichds.db.models import LoadProfileReading
    from arichds.db.session import session_scope

    now = datetime.now(UTC)
    with session_scope() as session:
        for index in range(count):
            session.add(
                LoadProfileReading(
                    device_id=device_id,
                    # Distinct timestamps: ``(device_id, logger_id, read_at)`` is
                    # unique from migration 0006 on, so ``count`` identical rows
                    # would now be one row.
                    read_at=now - timedelta(minutes=15 * index),
                    source="dlms",
                    logger_id=1,
                    interval_sec=900,
                    import_active_kwh=100.0 + index,
                )
            )


def count_readings(device_id: int) -> int:
    """How many Interval Readings a device has, straight from the table.

    The API stopped exposing readings when M3-3 removed ``/readings/latest``
    (ADR 0007), so counting rows is now the only way to assert that Read now
    wrote nothing and that Delete all data deleted exactly what it claimed.
    """
    from sqlalchemy import func, select

    from arichds.db.models import LoadProfileReading
    from arichds.db.session import session_scope

    with session_scope() as session:
        return (
            session.scalar(
                select(func.count()).select_from(LoadProfileReading).where(LoadProfileReading.device_id == device_id)
            )
            or 0
        )


def write_billing_rows(device_id: int, count: int) -> None:
    """Write *count* closed Billing Readings straight into the table."""
    from datetime import UTC, timedelta

    from arichds.db.models import BillingReading
    from arichds.db.session import session_scope

    now = datetime.now(UTC)
    with session_scope() as session:
        for index in range(count):
            session.add(
                BillingReading(
                    device_id=device_id,
                    bill_date=now - timedelta(days=30 * index),
                    read_at=now,
                    record_status=None,
                    source="dlms",
                    import_active_kwh_total=100.0 + index,
                )
            )


def count_billing_rows(device_id: int) -> int:
    """How many Billing Readings a device has, straight from the table."""
    from sqlalchemy import func, select

    from arichds.db.models import BillingReading
    from arichds.db.session import session_scope

    with session_scope() as session:
        return (
            session.scalar(
                select(func.count()).select_from(BillingReading).where(BillingReading.device_id == device_id)
            )
            or 0
        )


def schema_property_names(model: type) -> set[str]:
    """Every property name in *model*'s JSON schema, ``$defs`` included."""
    schema = model.model_json_schema()
    names: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                names.update(properties)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return names


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


def insert_device_with_transport(transport: dict) -> int:
    """Insert a row with an arbitrary — possibly malformed — transport dict.

    Bypasses the API on purpose: Create and Update both validate by schema,
    so this is the only way to get a malformed row into the table, which is
    exactly what ``TestMalformedStoredTransportNeverLies`` needs to exercise
    the read path's degrade behaviour.
    """
    from arichds.db.models import Device
    from arichds.db.session import session_scope

    with session_scope() as session:
        device = Device(
            name="Malformed Transport",
            brand="mitsu",
            model="smw110",
            site_name="Plant A",
            transport=transport,
            enabled=False,
        )
        session.add(device)
        session.flush()
        return device.id
