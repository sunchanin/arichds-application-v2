"""The ``framing`` field of a ``net`` transport, through the devices API
(``docs/issues/025``; the driver half is ``test_framing.py``).

What has to be true at this layer: the operator's choice **reaches the driver**
on every path that opens a connection (Test connection, Create, Update), it is
**stored and echoed** so the form can show it again, a model that offers no
choice **refuses** one with a sentence instead of silently speaking its default,
and a device saved before the field existed keeps working untouched.
"""

from __future__ import annotations

import pytest
from fakes import FakeMeterState
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("fake_meter")

PROMETER = {
    "name": "CEWE behind a converter",
    "brand": "cewe",
    "model": "prometer100",
    "site_name": "TC",
    "transport": {"kind": "net", "host": "10.100.91.1", "port": 4059, "framing": "hdlc"},
    "password": "hunter2",
}

SERIAL_SMW110 = {
    "name": "Serial Meter",
    "brand": "mitsu",
    "model": "smw110",
    "site_name": "TC",
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


class TestTheCatalogSaysWhichModelsOfferAChoice:
    def test_prometer_100_lists_both_framings_default_first(self, admin_client: TestClient) -> None:
        catalog = {e["model"]: e for e in admin_client.get("/api/devices/catalog").json()["data"]}

        assert catalog["prometer100"]["framings"] == ["wrapper", "hdlc"]

    def test_a_model_with_no_choice_lists_none(self, admin_client: TestClient) -> None:
        catalog = {e["model"]: e for e in admin_client.get("/api/devices/catalog").json()["data"]}

        assert catalog["smw110"]["framings"] == []


class TestTheChoiceReachesTheDriver:
    def test_test_connection_probes_with_it(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        body = {"model": "prometer100", "transport": PROMETER["transport"], "password": "hunter2"}

        response = admin_client.post("/api/devices/test-connection", json=body)

        assert response.status_code == 200, response.text
        assert response.json()["data"]["reachable"] is True
        assert fake_meter.framings_seen == ["hdlc"]

    def test_create_probes_with_it_stores_it_and_echoes_it(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        response = admin_client.post("/api/devices", json=PROMETER)

        assert response.status_code == 201, response.text
        assert fake_meter.framings_seen[0] == "hdlc"
        assert response.json()["data"]["transport"] == PROMETER["transport"]
        listed = admin_client.get("/api/devices").json()["data"][0]
        assert listed["transport"]["framing"] == "hdlc"

    def test_update_can_move_a_device_onto_hdlc(self, admin_client: TestClient, fake_meter: FakeMeterState) -> None:
        """The site's own repair: the device exists already, under the wrong
        framing; the operator edits it rather than re-adding it."""
        created = admin_client.post(
            "/api/devices", json={**PROMETER, "transport": {"kind": "net", "host": "10.100.91.1", "port": 4059}}
        ).json()["data"]
        fake_meter.framings_seen.clear()

        response = admin_client.put(f"/api/devices/{created['id']}", json={**PROMETER, "password": ""})

        assert response.status_code == 200, response.text
        assert fake_meter.framings_seen[0] == "hdlc"
        assert response.json()["data"]["transport"]["framing"] == "hdlc"


class TestADeviceSavedBeforeTheFieldExisted:
    def test_no_framing_is_accepted_and_nothing_is_stored_for_it(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """The stored JSON keeps its old shape — no ``"framing": null`` key written
        into every new row for a choice the operator never made."""
        from arichds.db.models import Device
        from arichds.db.session import session_scope

        legacy = {**PROMETER, "transport": {"kind": "net", "host": "10.100.91.1", "port": 4059}}

        response = admin_client.post("/api/devices", json=legacy)

        assert response.status_code == 201, response.text
        assert fake_meter.framings_seen[0] is None
        assert response.json()["data"]["transport"]["framing"] is None
        with session_scope() as session:
            stored = session.get(Device, response.json()["data"]["id"]).transport
        assert stored == {"kind": "net", "host": "10.100.91.1", "port": 4059}

    def test_update_back_to_the_default_removes_the_key_rather_than_nulling_it(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        """The converter is replaced by the meter's own port: the operator picks
        the default again, and the row returns to the shape it would have had."""
        from arichds.db.models import Device
        from arichds.db.session import session_scope

        created = admin_client.post("/api/devices", json=PROMETER).json()["data"]
        back_to_default = {
            **PROMETER,
            "password": "",
            "transport": {"kind": "net", "host": "10.100.91.1", "port": 4059},
        }
        fake_meter.framings_seen.clear()

        response = admin_client.put(f"/api/devices/{created['id']}", json=back_to_default)

        assert response.status_code == 200, response.text
        assert fake_meter.framings_seen[0] is None
        assert response.json()["data"]["transport"]["framing"] is None
        with session_scope() as session:
            stored = session.get(Device, created["id"]).transport
        assert stored == {"kind": "net", "host": "10.100.91.1", "port": 4059}


class TestAModelThatOffersNoChoiceRefusesOne:
    def test_create_answers_422_naming_the_model_and_opens_no_connection(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        net_smw110 = {
            **SERIAL_SMW110,
            "transport": {"kind": "net", "host": "10.0.0.9", "port": 4059, "framing": "hdlc"},
        }

        response = admin_client.post("/api/devices", json=net_smw110)

        assert response.status_code == 422, response.text
        assert "smw110" in response.text
        assert "framing" in response.text.lower()
        assert fake_meter.connects == 0

    def test_test_connection_refuses_it_the_same_way(
        self, admin_client: TestClient, fake_meter: FakeMeterState
    ) -> None:
        body = {
            "model": "smw110",
            "transport": {"kind": "net", "host": "10.0.0.9", "port": 4059, "framing": "hdlc"},
            "password": "x",
        }

        response = admin_client.post("/api/devices/test-connection", json=body)

        assert response.status_code == 422, response.text
        assert fake_meter.connects == 0

    def test_a_word_that_is_not_a_framing_is_a_schema_error(self, admin_client: TestClient) -> None:
        bad = {**PROMETER, "transport": {**PROMETER["transport"], "framing": "modbus"}}

        assert admin_client.post("/api/devices", json=bad).status_code == 422

    def test_a_serial_transport_takes_no_framing_at_all(self, admin_client: TestClient) -> None:
        """Serial is HDLC by nature; the field belongs to ``net`` alone, and a
        stray one must not be stored as if it meant something."""
        stray = {**SERIAL_SMW110, "transport": {**SERIAL_SMW110["transport"], "framing": "hdlc"}}

        response = admin_client.post("/api/devices", json=stray)

        assert response.status_code in (201, 422), response.text
        if response.status_code == 201:
            assert "framing" not in response.json()["data"]["transport"]
