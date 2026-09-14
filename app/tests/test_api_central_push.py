"""``/api/settings/central-push`` (ADR 0024, ticket 07) — configuration,
write-only Push Token verification, the (still-empty) status, and the
published contract.

Ticket 07 builds no push cycle: :mod:`arichds.centralpush.status` is never
written to here, so every status assertion below is "no cycle has run".
Ticket 08 is what starts populating it.
"""

from __future__ import annotations

import logging

import jwt
import pytest
from conftest import TEST_MACHINE_ID, VENDOR_PRIVATE_KEY_PEM
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from fastapi.testclient import TestClient
from pydantic import Field, create_model

from arichds.centralpush.contract import (
    HOLDINGS_ENTRY_KINDS,
    ITEM_KINDS,
    HoldingsResponse,
    MeterItem,
    PushEnvelope,
    render_contract,
)
from arichds.db.app_settings import CENTRAL_PUSH_TOKEN_KEY
from arichds.licensing.push_token import PUSH_TOKEN_ALGORITHM, build_push_token_claims
from arichds.logging_config import CredentialRedactionFilter


def mint_push_token(*, machine_id: str = TEST_MACHINE_ID) -> str:
    """Issue a Push Token signed with the suite's throwaway vendor key —
    everything ``tools/arichds_vendor.py sign-push`` does, without shelling
    out to it (mirrors ``conftest.mint_meter_activation_code``)."""
    claims = build_push_token_claims(machine_id=machine_id)
    return jwt.encode(claims, VENDOR_PRIVATE_KEY_PEM, algorithm=PUSH_TOKEN_ALGORITHM)


def _save(client: TestClient, **overrides: object):
    body: dict[str, object] = {"url": "https://push.example.com"}
    body.update(overrides)
    return client.put("/api/settings/central-push", json=body)


def _stored_token(client: TestClient) -> str:
    """Read ``central_push_token`` straight from the ``settings`` table — the
    API cannot answer this by design."""
    from arichds.db.app_settings import CENTRAL_PUSH_TOKEN_DEFAULT, get_setting
    from arichds.db.session import session_scope

    with session_scope() as session:
        return get_setting(session, CENTRAL_PUSH_TOKEN_KEY, CENTRAL_PUSH_TOKEN_DEFAULT)


class TestGet:
    def test_defaults_on_a_fresh_database(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/settings/central-push")

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["url"] == ""
        assert data["token_set"] is False
        assert data["last_cycle"] is None

    def test_reading_is_admin_only(self, user_client: TestClient) -> None:
        """Unlike most of ``/api/settings/*``, even ``GET`` here is admin-only
        (ADR 0024) — the URL and whether a token is set are machine-internal
        configuration."""
        assert user_client.get("/api/settings/central-push").status_code == 403


class TestPutUrl:
    def test_saving_a_url_alone_is_accepted(self, admin_client: TestClient) -> None:
        response = _save(admin_client, url="https://push.example.com")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["url"] == "https://push.example.com"

    def test_an_empty_url_disables_the_push(self, admin_client: TestClient) -> None:
        _save(admin_client, url="https://push.example.com")

        response = _save(admin_client, url="")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["url"] == ""

    def test_saving_is_admin_only(self, user_client: TestClient) -> None:
        assert _save(user_client).status_code == 403


class TestPutToken:
    def test_a_valid_token_for_this_machine_is_accepted_and_stored(self, admin_client: TestClient) -> None:
        token = mint_push_token()

        response = _save(admin_client, token=token)

        assert response.status_code == 200, response.text
        assert response.json()["data"]["token_set"] is True
        assert _stored_token(admin_client) == token

    def test_an_omitted_token_keeps_the_stored_one(self, admin_client: TestClient) -> None:
        token = mint_push_token()
        _save(admin_client, token=token)

        response = _save(admin_client, url="https://new.example.com")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["url"] == "https://new.example.com"
        assert response.json()["data"]["token_set"] is True
        assert _stored_token(admin_client) == token

    def test_an_explicit_empty_token_clears_the_stored_one(self, admin_client: TestClient) -> None:
        _save(admin_client, token=mint_push_token())

        response = _save(admin_client, token="")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["token_set"] is False
        assert _stored_token(admin_client) == ""

    def test_a_token_for_a_different_machine_is_refused_and_nothing_changes(self, admin_client: TestClient) -> None:
        good = mint_push_token()
        _save(admin_client, url="https://push.example.com", token=good)

        response = _save(admin_client, url="https://evil.example.com", token=mint_push_token(machine_id="f" * 64))

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "PUSH_TOKEN_INVALID"
        assert body["error"]["reason"] == "WRONG_MACHINE"
        assert "machine" in body["error"]["message"].lower()
        # Nothing changed — the endpoint's own docstring promises a rejected
        # token leaves both the stored URL and the stored token exactly as
        # they were, not just the token.
        assert _stored_token(admin_client) == good
        assert admin_client.get("/api/settings/central-push").json()["data"]["url"] == "https://push.example.com"

    def test_a_malformed_token_is_refused_and_nothing_changes(self, admin_client: TestClient) -> None:
        good = mint_push_token()
        _save(admin_client, url="https://push.example.com", token=good)

        response = _save(admin_client, url="https://evil.example.com", token="not-a-token-at-all")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is False
        assert body["error"]["reason"] == "MALFORMED"
        assert _stored_token(admin_client) == good
        assert admin_client.get("/api/settings/central-push").json()["data"]["url"] == "https://push.example.com"

    def test_a_token_signed_by_another_key_is_refused_as_invalid_signature(self, admin_client: TestClient) -> None:
        other_key = Ed25519PrivateKey.generate()
        other_pem = other_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        forged = jwt.encode(
            build_push_token_claims(machine_id=TEST_MACHINE_ID), other_pem, algorithm=PUSH_TOKEN_ALGORITHM
        )

        response = _save(admin_client, token=forged)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is False
        assert body["error"]["reason"] == "INVALID_SIGNATURE"

    def test_a_tampered_token_is_refused_as_invalid_signature(self, admin_client: TestClient) -> None:
        """Distinct from the "signed by another key" test above — this is a
        genuine, validly-issued token whose bytes were altered *after*
        signing, the scenario the acceptance criterion names separately from
        a token signed by the wrong key."""
        good = mint_push_token()
        _save(admin_client, token=good)

        header_b64, payload_b64, signature_b64 = good.split(".")
        middle = len(payload_b64) // 2
        flipped_char = "A" if payload_b64[middle] != "A" else "B"
        tampered = f"{header_b64}.{payload_b64[:middle]}{flipped_char}{payload_b64[middle + 1 :]}.{signature_b64}"

        response = _save(admin_client, token=tampered)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is False
        assert body["error"]["reason"] == "INVALID_SIGNATURE"
        assert _stored_token(admin_client) == good

    def test_an_activation_code_is_refused_as_the_wrong_wire_format(
        self, admin_client: TestClient, activation_code: str
    ) -> None:
        response = _save(admin_client, token=activation_code)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is False
        assert body["error"]["reason"] == "LICENCE_CODE_NOT_PUSH_TOKEN"

    def test_saving_a_token_is_admin_only(self, user_client: TestClient) -> None:
        assert _save(user_client, token=mint_push_token()).status_code == 403


class TestTheResponseNeverCarriesTheToken:
    def test_the_serialised_body_never_carries_the_token(self, admin_client: TestClient) -> None:
        """Asserted on the response body, not on the model — a field added to
        ``CentralPushOut`` would pass a model-level assertion and still leak."""
        token = mint_push_token()

        _save(admin_client, token=token)
        response = admin_client.get("/api/settings/central-push")

        assert "token" not in response.json()["data"]
        assert token not in response.text


class TestStatus:
    def test_no_cycle_has_run_yet(self, admin_client: TestClient) -> None:
        """Ticket 07 lands no push cycle — this must read ``None`` until
        ticket 08's scheduler job calls ``set_last_cycle``."""
        response = admin_client.get("/api/settings/central-push/status")

        assert response.status_code == 200, response.text
        assert response.json()["data"] is None

    def test_reading_status_is_admin_only(self, user_client: TestClient) -> None:
        assert user_client.get("/api/settings/central-push/status").status_code == 403


class TestContractEndpoint:
    def test_it_lists_the_four_kinds_with_their_natural_keys(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/settings/central-push/contract")

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["contract_version"] == 1
        kinds = {kind["kind"]: kind for kind in data["kinds"]}
        assert set(kinds) == {"meters", "billing", "energy_summary", "load_profile"}
        assert kinds["load_profile"]["natural_key"] == ["meter_serial", "logger_id", "read_at"]
        assert kinds["billing"]["natural_key"] == ["meter_serial", "bill_date"]
        assert kinds["energy_summary"]["natural_key"] == ["meter_serial", "local_date"]
        assert kinds["meters"]["replace_whole_roster"] is True

    def test_it_lists_every_field_of_every_item_model(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/settings/central-push/contract")

        kinds = {kind["kind"]: kind for kind in response.json()["data"]["kinds"]}
        for kind, model in ITEM_KINDS.items():
            names = {field["name"] for field in kinds[kind]["fields"]}
            assert names == set(model.model_fields), (kind, names, set(model.model_fields))

    def test_it_states_the_interval_status_bit_0_meaning(self, admin_client: TestClient) -> None:
        data = admin_client.get("/api/settings/central-push/contract").json()["data"]

        load_profile = next(kind for kind in data["kinds"] if kind["kind"] == "load_profile")
        flag_field = next(field for field in load_profile["fields"] if field["name"] == "interval_status_flag")
        assert "bit 0" in flag_field["description"].lower()
        assert "all-invalid" in flag_field["description"].lower()

    def test_it_states_units_offset_and_holdings_and_retention(self, admin_client: TestClient) -> None:
        data = admin_client.get("/api/settings/central-push/contract").json()["data"]
        notes = " ".join(data["notes"]).lower()

        assert "kwh" in notes
        assert "utc offset" in notes
        assert "local_date" in notes
        assert "holdings" in data["holdings_endpoint"].lower()
        assert "90-day" in notes and "never" in notes

    def test_reading_the_contract_is_admin_only(self, user_client: TestClient) -> None:
        assert user_client.get("/api/settings/central-push/contract").status_code == 403

    def test_it_lists_every_field_of_the_holdings_response_and_its_entries(self, admin_client: TestClient) -> None:
        """`HoldingsResponse` and its three entry models are payload models
        too (ADR 0024's "the four item kinds" is not the whole list) — a
        field added to any of them, e.g. `newest_read_at`, must appear here
        exactly as the item kinds already do."""
        data = admin_client.get("/api/settings/central-push/contract").json()["data"]

        assert {field["name"] for field in data["holdings"]} == set(HoldingsResponse.model_fields)

        entries = {entry["kind"]: entry for entry in data["holdings_entries"]}
        assert set(entries) == set(HOLDINGS_ENTRY_KINDS)
        for kind, model in HOLDINGS_ENTRY_KINDS.items():
            names = {field["name"] for field in entries[kind]["fields"]}
            assert names == set(model.model_fields), (kind, names, set(model.model_fields))

    def test_it_lists_every_field_of_the_push_envelope(self, admin_client: TestClient) -> None:
        data = admin_client.get("/api/settings/central-push/contract").json()["data"]

        names = {field["name"] for field in data["envelope"]}
        assert names == set(PushEnvelope.model_fields), (names, set(PushEnvelope.model_fields))
        # The fields the review round named as missing before this fix.
        assert {"machine_id", "sent_at", "items"} <= names

    def test_published_type_strings_carry_no_python_internals(self, admin_client: TestClient) -> None:
        """A field's ``type`` is read by a receiving team that is not
        Python — it must never leak this module's own dotted import path or
        the bare word ``typing``."""
        data = admin_client.get("/api/settings/central-push/contract").json()["data"]

        holdings_load_profile = next(field for field in data["holdings"] if field["name"] == "load_profile")
        assert holdings_load_profile["type"] == "list[HoldingsLoadProfileEntry]"

        envelope_kind = next(field for field in data["envelope"] if field["name"] == "kind")
        assert envelope_kind["type"].startswith("one of [")
        assert "typing.Literal" not in envelope_kind["type"]

        for field in [*data["holdings"], *data["envelope"], *(f for kind in data["kinds"] for f in kind["fields"])]:
            assert "arichds.centralpush.contract" not in field["type"]
            assert "typing." not in field["type"]


class TestContractIsGeneratedNotHandWritten:
    """The acceptance criterion this exists for: a field added to a model
    appears in the rendered contract with no other edit. Proved by
    substituting a model that carries one extra field, rather than mutating
    the real ones — this is what proves ``render_contract`` walks
    ``model_fields`` generically instead of a hand-written per-kind list.
    """

    def test_a_field_added_to_a_model_appears_with_no_other_change(self) -> None:
        extended_meter_item = create_model(
            "ExtendedMeterItem",
            __base__=MeterItem,
            probe_field=(str, Field(description="added by the test")),
        )
        item_kinds = dict(ITEM_KINDS)
        item_kinds["meters"] = extended_meter_item

        contract = render_contract(item_kinds)

        meters_kind = next(kind for kind in contract.kinds if kind.kind == "meters")
        assert "probe_field" in {field.name for field in meters_kind.fields}

    def test_the_real_models_are_untouched_by_the_probe_above(self) -> None:
        assert "probe_field" not in MeterItem.model_fields


class TestThePushTokenNeverReachesALog:
    def test_the_redaction_filter_covers_the_setting_key_name(self) -> None:
        """``central_push_token`` ends in the literal ``token``, and the
        filter's existing pattern matches anywhere in the line — confirmed by
        test rather than by reading, because renaming the key would silently
        drop this protection."""
        record = logging.LogRecord(
            "t", logging.INFO, __file__, 1, "saving central_push_token=hunter2 for the push", None, None
        )

        assert CredentialRedactionFilter().filter(record) is True
        assert "hunter2" not in record.getMessage()
        assert CENTRAL_PUSH_TOKEN_KEY.endswith("token")

    def test_a_captured_log_line_naming_the_saved_token_carries_no_token(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Attaches the real filter to ``caplog``'s own handler — the shape
        every production handler carries (``logging_config.configure_logging``)
        — then drives a real log call naming the setting key and the token,
        and captures the output: this file's own acceptance criterion asks
        for exactly this, "a test captures the log output and finds no
        token"."""
        token = mint_push_token()
        caplog.handler.addFilter(CredentialRedactionFilter())
        logger = logging.getLogger("arichds.centralpush.test")

        with caplog.at_level(logging.DEBUG):
            logger.info("saving central_push_token=%s", token)

        assert token not in caplog.text
        for record in caplog.records:
            assert token not in record.getMessage()
