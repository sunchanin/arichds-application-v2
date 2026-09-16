"""The File Upload Destination settings endpoints (SPEC §3.8, ADR 0025,
tickets 01-02) — ``/api/settings/file-upload`` and its three per-protocol
``PUT``s, the status, and (ticket 02) the manual ``POST .../upload-now``
trigger.

``TestUploadNow`` owns the manual trigger; every other class here predates
the cycle and stays "no cycle has run" (:mod:`arichds.fileupload.cycle`
still moves no bytes in production — the real transports land in tickets
03-05, so a bare `POST /upload-now` on an otherwise-untouched app cannot
populate the status either). :mod:`test_fileupload_cycle` owns the cycle's
own behaviour against an in-memory transport.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from arichds.constants import RESERVED_FEATURE_KEYS, SELLABLE_FEATURE_KEYS
from arichds.db.app_settings import (
    FILEUPLOAD_FTPS_PASSWORD_KEY,
    FILEUPLOAD_HTTPS_TOKEN_KEY,
    FILEUPLOAD_SFTP_KEY_PASSPHRASE_KEY,
    FILEUPLOAD_SFTP_PASSWORD_KEY,
)
from arichds.logging_config import CredentialRedactionFilter


class TestFeatureKey:
    def test_file_upload_destination_is_sellable_and_not_reserved(self) -> None:
        """The eleventh sellable key (issue 013) left the reserved set with
        this ticket (ADR 0025) — it is sold exactly like `database_destination`."""
        assert "file_upload_destination" in SELLABLE_FEATURE_KEYS
        assert "file_upload_destination" not in RESERVED_FEATURE_KEYS
        assert len(SELLABLE_FEATURE_KEYS) == 11


def _stored(client: TestClient, key: str, default: str) -> str:
    """Read a `settings` row straight from the database — the API cannot
    answer this by design for a secret key."""
    from arichds.db.app_settings import get_setting
    from arichds.db.session import session_scope

    with session_scope() as session:
        return get_setting(session, key, default)


def _save_sftp(client: TestClient, **overrides: object):
    """PUT a full, valid SFTP body with *overrides* applied.

    **No ``password`` or ``key_passphrase`` key by default** — the same
    convention ``test_dataout_config_api.py``'s own ``_save`` uses for
    ``password``: a test that wants "omitted" must not have to fight a
    default the helper injected, and a test that wants a value passes it
    explicitly. ``key_path`` defaults non-empty so an override-free call is
    still a valid save (the credential requirement is satisfied by the key
    file alone).
    """
    body: dict[str, object] = {
        "host": "sftp.example.com",
        "port": 22,
        "username": "arichds",
        "key_path": "/keys/id_ed25519",
        "remote_root": "/home/arichds",
    }
    body.update(overrides)
    return client.put("/api/settings/file-upload/sftp", json=body)


def _save_ftps(client: TestClient, **overrides: object):
    """PUT a full, valid FTPS body with *overrides* applied. No ``password``
    key by default, the same reasoning as :func:`_save_sftp`."""
    body: dict[str, object] = {
        "host": "ftps.example.com",
        "port": 21,
        "username": "arichds",
        "remote_root": "/home/arichds",
    }
    body.update(overrides)
    return client.put("/api/settings/file-upload/ftps", json=body)


def _save_https(client: TestClient, **overrides: object):
    """PUT a full, valid HTTPS body with *overrides* applied. No ``token``
    key by default, the same reasoning as :func:`_save_sftp`."""
    body: dict[str, object] = {"url": "https://files.example.com", "remote_root": "/arichds"}
    body.update(overrides)
    return client.put("/api/settings/file-upload/https", json=body)


class TestGet:
    def test_defaults_on_a_fresh_database(self, admin_client: TestClient) -> None:
        response = admin_client.get("/api/settings/file-upload")

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["active_protocol"] == ""
        assert data["sftp"] == {
            "host": "",
            "port": 22,
            "username": "",
            "password_set": False,
            "key_path": "",
            "key_passphrase_set": False,
            "remote_root": "",
            "host_key_fingerprint": "",
        }
        assert data["ftps"]["port"] == 21
        assert data["ftps"]["password_set"] is False
        assert data["https"]["url"] == ""
        assert data["https"]["token_set"] is False
        assert data["status"] is None

    def test_reading_is_admin_only(self, user_client: TestClient) -> None:
        """Unlike most of `/api/settings/*` (ADR 0025, mirroring Central
        Push) — the credentials are machine-internal configuration."""
        assert user_client.get("/api/settings/file-upload").status_code == 403


class TestPutSftp:
    def test_saving_makes_sftp_the_active_protocol(self, admin_client: TestClient) -> None:
        response = _save_sftp(admin_client)

        assert response.status_code == 200, response.text
        assert response.json()["data"]["active_protocol"] == "sftp"

    def test_saving_ftps_after_sftp_leaves_sftp_settings_untouched(self, admin_client: TestClient) -> None:
        """ADR 0025 decision 1 — the other two tabs keep what they hold."""
        _save_sftp(admin_client, host="keep-me.example.com")

        response = _save_ftps(admin_client)

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["active_protocol"] == "ftps"
        assert data["sftp"]["host"] == "keep-me.example.com"

    def test_an_omitted_password_keeps_the_stored_one(self, admin_client: TestClient) -> None:
        _save_sftp(admin_client, password="kept-secret")

        response = _save_sftp(admin_client, host="new-host.example.com")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["sftp"]["password_set"] is True
        assert _stored(admin_client, FILEUPLOAD_SFTP_PASSWORD_KEY, "") == "kept-secret"

    def test_an_explicit_empty_password_clears_it_but_a_key_path_keeps_the_save_valid(
        self, admin_client: TestClient
    ) -> None:
        response = _save_sftp(admin_client, password="", key_path="/keys/id_ed25519")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["sftp"]["password_set"] is False
        assert response.json()["data"]["sftp"]["key_path"] == "/keys/id_ed25519"

    def test_an_omitted_key_passphrase_keeps_the_stored_one(self, admin_client: TestClient) -> None:
        _save_sftp(admin_client, key_path="/keys/id_ed25519", password="", key_passphrase="kept-phrase")

        response = _save_sftp(admin_client, key_path="/keys/id_ed25519", password="", host="rotated.example.com")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["sftp"]["key_passphrase_set"] is True
        assert _stored(admin_client, FILEUPLOAD_SFTP_KEY_PASSPHRASE_KEY, "") == "kept-phrase"

    def test_neither_password_nor_key_path_is_refused(self, admin_client: TestClient) -> None:
        """Ticket 01's own acceptance criterion — the *effective* value, not
        just what this request sent."""
        response = _save_sftp(admin_client, password="", key_path="")

        assert response.status_code == 422, response.text
        assert "password" in response.text.lower() or "key" in response.text.lower()

    def test_a_key_path_alone_with_no_password_is_accepted(self, admin_client: TestClient) -> None:
        response = _save_sftp(admin_client, password="", key_path="/keys/id_ed25519")

        assert response.status_code == 200, response.text

    def test_a_port_outside_the_range_is_a_422_naming_the_value(self, admin_client: TestClient) -> None:
        for bad in (0, 65536, -1):
            response = _save_sftp(admin_client, port=bad)
            assert response.status_code == 422, response.text
            assert str(bad) in response.text

    def test_saving_is_admin_only(self, user_client: TestClient) -> None:
        assert _save_sftp(user_client).status_code == 403


class TestPutFtps:
    def test_saving_makes_ftps_the_active_protocol(self, admin_client: TestClient) -> None:
        response = _save_ftps(admin_client)

        assert response.status_code == 200, response.text
        assert response.json()["data"]["active_protocol"] == "ftps"

    def test_a_port_outside_the_range_is_a_422(self, admin_client: TestClient) -> None:
        response = _save_ftps(admin_client, port=70000)

        assert response.status_code == 422, response.text
        assert "70000" in response.text

    def test_an_omitted_password_keeps_the_stored_one(self, admin_client: TestClient) -> None:
        _save_ftps(admin_client, password="kept-secret")

        response = _save_ftps(admin_client, host="new-host.example.com")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["ftps"]["password_set"] is True
        assert _stored(admin_client, FILEUPLOAD_FTPS_PASSWORD_KEY, "") == "kept-secret"

    def test_saving_is_admin_only(self, user_client: TestClient) -> None:
        assert _save_ftps(user_client).status_code == 403


class TestPutHttps:
    def test_saving_makes_https_the_active_protocol(self, admin_client: TestClient) -> None:
        response = _save_https(admin_client)

        assert response.status_code == 200, response.text
        assert response.json()["data"]["active_protocol"] == "https"

    def test_a_blank_url_is_refused(self, admin_client: TestClient) -> None:
        response = _save_https(admin_client, url="")

        assert response.status_code == 422, response.text
        assert "url" in response.text.lower()

    def test_an_omitted_token_keeps_the_stored_one(self, admin_client: TestClient) -> None:
        _save_https(admin_client, token="kept-token")

        response = _save_https(admin_client, url="https://new.example.com")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["https"]["token_set"] is True
        assert _stored(admin_client, FILEUPLOAD_HTTPS_TOKEN_KEY, "") == "kept-token"

    def test_an_explicit_empty_token_clears_it(self, admin_client: TestClient) -> None:
        _save_https(admin_client, token="kept-token")

        response = _save_https(admin_client, token="")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["https"]["token_set"] is False

    def test_saving_is_admin_only(self, user_client: TestClient) -> None:
        assert _save_https(user_client).status_code == 403


class TestPlainFtpAndImplicitFtpsAreNotAProtocolValue:
    """ADR 0016/0025 — no field on this API ever accepts either."""

    def test_the_response_never_carries_a_plain_or_implicit_ftp_value(self, admin_client: TestClient) -> None:
        _save_ftps(admin_client, port=990)  # 990 is a legal *integer* — only the value 990 is legal, not a protocol
        data = admin_client.get("/api/settings/file-upload").json()["data"]

        assert data["active_protocol"] in ("", "sftp", "ftps", "https")

    def test_no_endpoint_accepts_a_protocol_field_at_all(self, admin_client: TestClient) -> None:
        """There is no generic `PUT .../protocol` taking a free-form name —
        each protocol has its own fixed-shape endpoint, so `"ftp"` has
        nowhere to be typed."""
        response = admin_client.put("/api/settings/file-upload/ftp", json={"host": "h", "port": 21, "remote_root": "/"})
        assert response.status_code == 404


class TestTheResponseNeverCarriesASecret:
    def test_the_serialised_body_never_carries_any_secret(self, admin_client: TestClient) -> None:
        """Asserted on the response body, not on the model — a field added
        to any `…Out` model would pass a model-level assertion and still
        leak."""
        _save_sftp(admin_client, password="sftp-secret", key_passphrase="phrase-secret")
        _save_ftps(admin_client, password="ftps-secret")
        _save_https(admin_client, token="https-secret")

        response = admin_client.get("/api/settings/file-upload")

        assert "password" not in response.json()["data"]["sftp"]
        assert "key_passphrase" not in response.json()["data"]["sftp"]
        assert "password" not in response.json()["data"]["ftps"]
        assert "token" not in response.json()["data"]["https"]
        for secret in ("sftp-secret", "ftps-secret", "https-secret", "phrase-secret"):
            assert secret not in response.text


class TestFeatureGate:
    """Every route carries `require_feature("file_upload_destination")`,
    the `database_destination` shape."""

    def test_get_refuses_without_the_feature(self, admin_client: TestClient, relicense) -> None:
        relicense(admin_client, features=["billing", "load_profile"])

        response = admin_client.get("/api/settings/file-upload")

        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FEATURE_DISABLED"
        assert response.json()["error"]["reason"] == "file_upload_destination"

    def test_put_sftp_refuses_without_the_feature(self, admin_client: TestClient, relicense) -> None:
        relicense(admin_client, features=["billing", "load_profile"])

        response = _save_sftp(admin_client)

        assert response.status_code == 403, response.text
        assert response.json()["error"]["reason"] == "file_upload_destination"

    def test_status_refuses_without_the_feature(self, admin_client: TestClient, relicense) -> None:
        relicense(admin_client, features=["billing", "load_profile"])

        response = admin_client.get("/api/settings/file-upload/status")

        assert response.status_code == 403, response.text
        assert response.json()["error"]["reason"] == "file_upload_destination"

    def test_upload_now_refuses_without_the_feature(self, admin_client: TestClient, relicense) -> None:
        relicense(admin_client, features=["billing", "load_profile"])

        response = admin_client.post("/api/settings/file-upload/upload-now")

        assert response.status_code == 403, response.text
        assert response.json()["error"]["reason"] == "file_upload_destination"


class TestStatus:
    def test_no_cycle_has_run_yet(self, admin_client: TestClient) -> None:
        """Ticket 01 lands no upload cycle — this must read `None` until
        ticket 02's scheduler job calls `set_last_cycle`."""
        response = admin_client.get("/api/settings/file-upload/status")

        assert response.status_code == 200, response.text
        assert response.json()["data"] is None

    def test_status_stays_none_even_after_saving_every_tab(self, admin_client: TestClient) -> None:
        """Saving configuration must not be mistaken for running a cycle."""
        _save_sftp(admin_client)
        _save_ftps(admin_client)
        _save_https(admin_client)

        response = admin_client.get("/api/settings/file-upload/status")

        assert response.json()["data"] is None

    def test_reading_status_is_admin_only(self, user_client: TestClient) -> None:
        assert user_client.get("/api/settings/file-upload/status").status_code == 403


class TestSecretsNeverReachALog:
    """The ticket's own claim — "the existing redaction filter covers it with
    no new pattern" — is false for `passphrase`: none of the filter's
    existing patterns match a key ending in `passphrase` (it does not
    contain the substring `password`). `logging_config.py` gained a new
    pattern for it in this same change; these tests prove all three secret
    suffixes (`password`, `passphrase`, `token`) are actually covered, not
    just `password` and `token`.
    """

    @pytest.mark.parametrize("word", ["password", "passphrase", "token"])
    def test_the_redaction_filter_covers_the_word(self, word: str) -> None:
        record = logging.LogRecord(
            "t", logging.INFO, __file__, 1, f"saving fileupload_sftp_{word}=hunter2 for the destination", None, None
        )

        assert CredentialRedactionFilter().filter(record) is True
        assert "hunter2" not in record.getMessage()

    def test_every_secret_setting_key_ends_in_one_of_the_three_words(self) -> None:
        from arichds.db.app_settings import (
            FILEUPLOAD_FTPS_PASSWORD_KEY,
            FILEUPLOAD_HTTPS_TOKEN_KEY,
            FILEUPLOAD_SFTP_KEY_PASSPHRASE_KEY,
            FILEUPLOAD_SFTP_PASSWORD_KEY,
        )

        for key in (
            FILEUPLOAD_SFTP_PASSWORD_KEY,
            FILEUPLOAD_SFTP_KEY_PASSPHRASE_KEY,
            FILEUPLOAD_FTPS_PASSWORD_KEY,
            FILEUPLOAD_HTTPS_TOKEN_KEY,
        ):
            assert key.endswith(("password", "passphrase", "token")), key

    def test_a_captured_log_line_naming_a_saved_passphrase_carries_no_passphrase(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Attaches the real filter to `caplog`'s own handler — the shape
        every production handler carries — then drives a real log call and
        captures the output: pins the new `passphrase` regex directly,
        without going through the HTTP layer. Kept alongside the test below
        (review fix round) — this one proves the *pattern*; that one proves
        the *save path* is actually clean, which this one cannot: a
        hand-built log line says nothing about what the real endpoints log."""
        secret = "hunter2-do-not-log-me"
        caplog.handler.addFilter(CredentialRedactionFilter())
        logger = logging.getLogger("arichds.fileupload.test")

        with caplog.at_level(logging.DEBUG):
            logger.info("saving fileupload_sftp_key_passphrase=%s", secret)

        assert secret not in caplog.text
        for record in caplog.records:
            assert secret not in record.getMessage()

    def test_a_real_save_across_all_three_tabs_logs_no_secret(
        self, admin_client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Review fix round — the test above hand-builds its log line, which
        proves the filter's pattern but nothing about the `PUT` path itself:
        a future log line added on that path (a transport error in ticket
        02-05, an audit line) could still leak a secret the pattern does
        cover, and nothing here would catch it. This one drives the real
        `PUT /sftp` and `PUT /https` endpoints — with the redaction filter
        attached to `caplog`'s own handler, the same shape every production
        handler carries — and asserts none of the three secrets it saves
        reach any captured record. Three *distinct* secrets, one per field,
        so a leak of any single one is unambiguous about which field leaked.
        """
        sftp_password = "sftp-password-do-not-log-me"
        sftp_passphrase = "sftp-passphrase-do-not-log-me"
        https_token = "https-token-do-not-log-me"
        caplog.handler.addFilter(CredentialRedactionFilter())

        with caplog.at_level(logging.DEBUG):
            sftp_response = _save_sftp(admin_client, password=sftp_password, key_passphrase=sftp_passphrase)
            https_response = _save_https(admin_client, token=https_token)

        assert sftp_response.status_code == 200, sftp_response.text
        assert https_response.status_code == 200, https_response.text
        for secret in (sftp_password, sftp_passphrase, https_token):
            assert secret not in caplog.text
            for record in caplog.records:
                assert secret not in record.getMessage()


class _SynchronousScheduler:
    """A stand-in for the process Scheduler whose ``run_soon`` runs the
    callable immediately, on the calling thread — the ``RecordingScheduler``
    pattern ``test_api_devices.py`` uses for the *other* ``run_soon`` caller,
    adapted to actually execute the one-shot rather than merely record it.

    Required here and not optional: every ``admin_client`` fixture sets
    ``ARICHDS_POLL_ENABLED=false`` (``conftest.py``'s ``unlicensed_client``),
    so the real Scheduler's one-shot thread never runs — a test that hit
    ``POST .../upload-now`` against the real (unstarted) Scheduler would
    block for the endpoint's own bounded wait
    (``FILEUPLOAD_BUDGET_SEC + 10`` seconds) before timing out.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_soon(self, name, fn) -> None:  # noqa: ANN001
        self.calls.append(name)
        fn()


class TestUploadNow:
    """``POST /api/settings/file-upload/upload-now`` (ticket 02)."""

    @pytest.fixture(autouse=True)
    def _clear_status(self):
        from arichds.fileupload.status import set_last_cycle

        set_last_cycle(None)
        yield
        set_last_cycle(None)

    def test_it_runs_on_the_schedulers_one_shot_lane(self, admin_client: TestClient) -> None:
        """Nothing is configured on this app, so the cycle it triggers is a
        genuine no-op that still reports itself unconfigured
        (`file_upload_cycle`'s own "not configured" branch, ticket 02
        round 1 problem 3) — this test proves the wiring, not the cycle's
        behaviour, which `test_fileupload_cycle.py` owns."""
        scheduler = _SynchronousScheduler()
        admin_client.app.state.scheduler = scheduler

        response = admin_client.post("/api/settings/file-upload/upload-now")

        assert response.status_code == 200, response.text
        assert scheduler.calls == ["file_upload_manual"]
        data = response.json()["data"]
        assert data["finished"] is True
        assert data["status"]["outcome"] == "not_configured"

    def test_it_returns_the_status_the_cycle_just_set(
        self, admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The endpoint's own contract — "returns that cycle's status" —
        proven independent of ticket 02's own real-transport gap: the cycle
        function the endpoint calls is monkeypatched to publish a known
        status, which the response must reflect, with `finished: true`
        since the (synchronous, in this test) one-shot lane actually ran it
        before the wait returned."""
        import arichds.api.file_upload as file_upload_api
        from arichds.fileupload.status import CycleStatus, set_last_cycle

        def _fake_cycle() -> None:
            set_last_cycle(
                CycleStatus(
                    ran_at=datetime.now(UTC),
                    protocol="sftp",
                    outcome="success",
                    files_sent=3,
                    bytes_sent=42,
                    files_skipped_unchanged=1,
                    files_skipped_budget=0,
                    files_skipped_no_serial=0,
                    duration_sec=0.1,
                    error=None,
                )
            )

        monkeypatch.setattr(file_upload_api, "file_upload_cycle", _fake_cycle)
        scheduler = _SynchronousScheduler()
        admin_client.app.state.scheduler = scheduler

        response = admin_client.post("/api/settings/file-upload/upload-now")

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["finished"] is True
        status = data["status"]
        assert status["outcome"] == "success"
        assert status["files_sent"] == 3
        assert status["bytes_sent"] == 42
        assert status["files_skipped_unchanged"] == 1

    def test_a_timed_out_wait_reports_unfinished_rather_than_a_stale_status(
        self, admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reviewer finding, ticket 02 round 1, problem 2 — a one-shot the
        scheduler never gets to (the real Scheduler is disabled under every
        `admin_client`, `ARICHDS_POLL_ENABLED=false`, so `run_soon` only
        ever queues and `_run` — and its `done.set()` — never runs) must
        not be reported as `finished: true` with whatever stale status
        happens to be published. Both halves of the endpoint's wait are
        shrunk to milliseconds so this test genuinely times out — for
        real, on the real (disabled) Scheduler — without sitting out the
        endpoint's real ~70s budget."""
        import arichds.api.file_upload as file_upload_api
        from arichds.fileupload.status import CycleStatus, set_last_cycle

        stale = CycleStatus(ran_at=datetime.now(UTC), protocol="sftp", outcome="success", files_sent=99)
        set_last_cycle(stale)
        monkeypatch.setattr(file_upload_api, "FILEUPLOAD_BUDGET_SEC", 0.01)
        monkeypatch.setattr(file_upload_api, "_UPLOAD_NOW_WAIT_MARGIN_SEC", 0.01)

        response = admin_client.post("/api/settings/file-upload/upload-now")

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["finished"] is False
        # The stale status is still returned (it is the best answer
        # available), but the caller is told not to trust it as this
        # cycle's own result.
        assert data["status"]["files_sent"] == 99

    def test_it_is_admin_only(self, user_client: TestClient) -> None:
        assert user_client.post("/api/settings/file-upload/upload-now").status_code == 403
