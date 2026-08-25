"""The Database Destination settings endpoints (issue #46, SPEC §3.10).

``GET``/``PUT /api/settings/database-destination`` and its ``/test`` action —
the configuration half of the Database Destination (CONTEXT.md). The sync
itself is :mod:`arichds.dataout.sync`; nothing here talks to a customer
database except the ``/test`` tests, which drive a fake connector.
"""

from __future__ import annotations

import logging
from typing import get_args

import pytest
from fastapi.testclient import TestClient
from pymysql.err import OperationalError

from arichds.constants import SELLABLE_FEATURE_KEYS
from arichds.dataout.destination import (
    ConnectionCheck,
    ConnectionResult,
    DestinationConfig,
    check_destination_connection,
    classify_connect_error,
    destination_url,
    missing_privileges,
)
from arichds.db.app_settings import DB_DEST_PASSWORD_KEY
from arichds.logging_config import CredentialRedactionFilter


class TestFeatureKey:
    def test_database_destination_is_a_sellable_feature_key(self) -> None:
        """The tenth sellable key (SPEC §3.9/§3.10, issue #46) — a licence
        that omits it must be able to withhold the whole module."""
        assert "database_destination" in SELLABLE_FEATURE_KEYS
        assert len(SELLABLE_FEATURE_KEYS) == 10


class TestGet:
    def test_defaults_on_a_fresh_database(self, admin_client: TestClient) -> None:
        """A fresh install answers without a seed migration — `""` means
        "not configured", the convention `capture_dir` set."""
        response = admin_client.get("/api/settings/database-destination")

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["host"] == ""
        assert data["port"] == 3306
        assert data["database"] == ""
        assert data["user"] == ""
        assert data["password_set"] is False
        assert data["last_sync"] is None

    def test_the_serialised_body_never_carries_a_password(self, admin_client: TestClient) -> None:
        """Asserted on the response body, not on the model — a field added to
        `…Out` would pass a model-level assertion and still leak."""
        admin_client.put(
            "/api/settings/database-destination",
            json={"host": "h", "port": 3306, "database": "d", "user": "u", "password": "s3cret"},
        )

        response = admin_client.get("/api/settings/database-destination")

        assert "password" not in response.json()["data"]
        assert "s3cret" not in response.text


def _save(client: TestClient, **overrides: object):
    """PUT a full, valid body with *overrides* applied."""
    body: dict[str, object] = {"host": "127.0.0.1", "port": 3306, "database": "arichds_dest", "user": "root"}
    body.update(overrides)
    return client.put("/api/settings/database-destination", json=body)


def _stored_password(client: TestClient) -> str:
    """Read `db_dest_password` straight from the `settings` table.

    The API cannot answer this by design, so the only way to prove the two
    branches below differ is to look at what was stored.
    """
    from arichds.db.app_settings import DB_DEST_PASSWORD_DEFAULT, DB_DEST_PASSWORD_KEY, get_setting
    from arichds.db.session import session_scope

    with session_scope() as session:
        return get_setting(session, DB_DEST_PASSWORD_KEY, DB_DEST_PASSWORD_DEFAULT)


class TestPut:
    def test_an_omitted_password_keeps_the_stored_one(self, admin_client: TestClient) -> None:
        """The form sends `password` only when the field was edited, so an
        untouched form must not clear a saved password."""
        _save(admin_client, password="kept-secret")

        response = _save(admin_client, host="10.0.0.9")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["host"] == "10.0.0.9"
        assert response.json()["data"]["password_set"] is True
        assert _stored_password(admin_client) == "kept-secret"

    def test_an_explicit_empty_string_stores_an_empty_password(self, admin_client: TestClient) -> None:
        """Decided against the obvious reading (SPEC §3.10): XAMPP's `root`
        genuinely has an empty password, so `""` must be enterable."""
        _save(admin_client, password="kept-secret")

        response = _save(admin_client, password="")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["password_set"] is False
        assert _stored_password(admin_client) == ""

    def test_an_explicit_null_password_keeps_the_stored_one(self, admin_client: TestClient) -> None:
        """`null` is the wire form of "omitted" — the same branch, pinned so
        the two cannot drift apart."""
        _save(admin_client, password="kept-secret")

        _save(admin_client, password=None)

        assert _stored_password(admin_client) == "kept-secret"

    def test_a_port_outside_the_range_is_a_422_naming_the_value(self, admin_client: TestClient) -> None:
        """An unreachable host is the Test button's job; a port that cannot
        exist is a 422, in `_validate_filename_template`'s style."""
        for bad in (0, 65536, -1):
            response = _save(admin_client, port=bad)
            assert response.status_code == 422, response.text
            assert str(bad) in response.text

    def test_the_edges_of_the_range_are_accepted(self, admin_client: TestClient) -> None:
        """1 and 65535 are valid ports — an off-by-one in the validator that
        rejected them would strand a customer on a high port."""
        assert _save(admin_client, port=1).status_code == 200
        assert _save(admin_client, port=65535).status_code == 200

    def test_saving_is_admin_only(self, user_client: TestClient) -> None:
        """`AdminDep`, the same as every other PUT in this module."""
        assert _save(user_client, host="evil").status_code == 403

    def test_reading_is_any_authenticated_caller(self, user_client: TestClient) -> None:
        """`/display` and `/export-format` both allow this."""
        assert user_client.get("/api/settings/database-destination").status_code == 200


class TestClassifyConnectError:
    """The three connection-failure outcomes, keyed on the codes **measured** against MariaDB
    10.4.32 with PyMySQL 1.2.0 on 2026-08-25 — not inherited from a datasheet.

    Both a refused TCP connection and an unresolvable hostname come back as
    **2003**; PyMySQL does not use 2002 or 2005 for either, whatever the C
    client does.
    """

    def test_refused_connection_is_unreachable(self) -> None:
        result, message = classify_connect_error(
            OperationalError(2003, "Can't connect to MySQL server on '127.0.0.1' ([WinError 10061] refused)"),
            database="arichds_dest",
        )
        assert result == "unreachable"
        assert "127.0.0.1" in message or "reach" in message.lower()

    def test_unresolvable_host_is_unreachable(self) -> None:
        """Measured: PyMySQL reports 2003 here too, not 2005."""
        result, _ = classify_connect_error(
            OperationalError(2003, "Can't connect to MySQL server on 'nope.invalid' ([Errno 11001] getaddrinfo)"),
            database="arichds_dest",
        )
        assert result == "unreachable"

    def test_access_denied_is_auth_failed(self) -> None:
        result, message = classify_connect_error(
            OperationalError(1045, "Access denied for user 'root'@'localhost' (using password: YES)"),
            database="arichds_dest",
        )
        assert result == "auth_failed"
        assert result != "unreachable"
        assert "password" in message.lower() or "user" in message.lower()

    def test_unknown_database_is_database_missing(self) -> None:
        result, message = classify_connect_error(
            OperationalError(1049, "Unknown database 'no_such_db'"),
            database="no_such_db",
        )
        assert result == "database_missing"
        assert "no_such_db" in message

    def test_a_socket_timeout_is_unreachable(self) -> None:
        """A connect timeout never reaches a server code at all."""
        result, _ = classify_connect_error(TimeoutError("timed out"), database="arichds_dest")
        assert result == "unreachable"

    def test_an_unrecognised_server_code_is_unreachable_not_a_crash(self) -> None:
        """A server code we have never seen must still map to a real outcome."""
        result, message = classify_connect_error(OperationalError(1234, "something new"), database="d")
        assert result == "unreachable"
        assert "1234" in message or "something new" in message


class TestAnUnconfiguredDestinationIsNotOk:
    """A blank host is **not** a connection failure — PyMySQL defaults it to
    ``localhost``, and a blank database to "no default schema". Measured on the
    reference server 2026-08-25: all three shapes below connected and returned
    ``ok`` with ``Server: 10.4.32-MariaDB`` before this guard existed.

    That is the *expected* way to hit it on this product, not an exotic one:
    the customer runs XAMPP on the same machine as ARICHDS, as ``root`` with an
    empty password. The operator would have been shown a green tick while the
    sync did nothing at all.

    These run with no server: the guard returns before any connection is
    attempted, which is the property being pinned.
    """

    def test_a_blank_host_is_not_configured_rather_than_ok(self) -> None:
        check = check_destination_connection(DestinationConfig("", 3306, "arichds_dest", "root", ""))

        assert check.result == "not_configured"
        assert check.result != "ok"
        assert "host" in check.message
        assert check.server_version is None

    def test_a_blank_database_is_not_configured_rather_than_ok(self) -> None:
        check = check_destination_connection(DestinationConfig("127.0.0.1", 3306, "", "root", ""))

        assert check.result == "not_configured"
        assert "database" in check.message

    def test_both_blank_names_both_fields(self) -> None:
        check = check_destination_connection(DestinationConfig("", 3306, "", "root", ""))

        assert check.result == "not_configured"
        assert "host" in check.message
        assert "database" in check.message

    def test_a_whitespace_only_host_counts_as_blank(self) -> None:
        assert check_destination_connection(DestinationConfig("   ", 3306, "d", "root", "")).result == "not_configured"

    def test_the_message_points_at_save_because_the_button_tests_saved_settings(self) -> None:
        check = check_destination_connection(DestinationConfig("", 3306, "", "root", ""))

        assert "Save" in check.message

    def test_the_endpoint_surfaces_it_on_a_200_like_every_other_outcome(self, admin_client: TestClient) -> None:
        """A fresh install: nothing saved, Test connection pressed."""
        response = admin_client.post("/api/settings/database-destination/test")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["result"] == "not_configured"
        assert response.json()["data"]["server_version"] is None

    def test_the_cycle_and_the_test_button_agree_about_what_configured_means(self) -> None:
        """The defect was that these two disagreed: the cycle returned early on
        `not config.configured` while the test path never consulted it, so the
        button said "Connected" about a destination the sync would skip."""
        for host, database in (("", "d"), ("h", ""), ("", ""), ("  ", "  ")):
            config = DestinationConfig(host, 3306, database, "root", "")
            assert config.configured is False
            assert check_destination_connection(config).result == "not_configured"


class TestMissingPrivileges:
    """`SHOW GRANTS FOR CURRENT_USER()` parsing.

    **Only recognised grant syntax counts; anything unparseable grants
    nothing** — which can produce a false `missing_privilege`, and is why the
    message says "could not confirm" rather than "you lack".
    """

    def test_all_privileges_on_everything_confirms_all(self) -> None:
        grants = ["GRANT ALL PRIVILEGES ON *.* TO `root`@`localhost` WITH GRANT OPTION"]
        assert missing_privileges(grants, database="arichds_dest") == []

    def test_the_full_explicit_set_on_the_database_confirms_all(self) -> None:
        grants = ["GRANT SELECT, INSERT, DELETE, CREATE, ALTER ON `arichds_dest`.* TO `svc`@`%`"]
        assert missing_privileges(grants, database="arichds_dest") == []

    def test_a_missing_privilege_is_named(self) -> None:
        """ALTER is what decision 8b added to the account's needs — the one
        most likely to be absent on an account a DBA set up for issue #37."""
        grants = ["GRANT SELECT, INSERT, DELETE, CREATE ON `arichds_dest`.* TO `svc`@`%`"]
        assert missing_privileges(grants, database="arichds_dest") == ["ALTER"]

    def test_a_grant_on_a_different_database_grants_nothing_here(self) -> None:
        grants = ["GRANT ALL PRIVILEGES ON `someone_elses`.* TO `svc`@`%`"]
        assert sorted(missing_privileges(grants, database="arichds_dest")) == [
            "ALTER",
            "CREATE",
            "DELETE",
            "INSERT",
            "SELECT",
        ]

    def test_an_escaped_underscore_in_the_database_name_still_matches(self) -> None:
        """MySQL escapes `_` as `\\_` in a grant scoped through a wildcard."""
        grants = ["GRANT ALL PRIVILEGES ON `arichds\\_dest`.* TO `svc`@`%`"]
        assert missing_privileges(grants, database="arichds_dest") == []

    def test_usage_only_grants_nothing(self) -> None:
        """`USAGE` is MySQL's "no privileges at all"."""
        grants = ["GRANT USAGE ON *.* TO `svc`@`%`"]
        assert len(missing_privileges(grants, database="arichds_dest")) == 5

    def test_an_unparseable_grant_grants_nothing(self) -> None:
        grants = ["GRANT PROXY ON ''@'' TO `svc`@`%`", "something we have never seen"]
        assert len(missing_privileges(grants, database="arichds_dest")) == 5


class TestTestConnectionEndpoint:
    """`POST …/test` — **HTTP 200 for every outcome, including the failures.**

    A 4xx would be swallowed by the page's generic error surface and the
    operator would be told "Connection failed", which is exactly what this
    endpoint exists to avoid.
    """

    def test_each_outcome_comes_back_on_a_200(self, admin_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Driven from ``ConnectionResult`` itself, never a hand-written list.

        This test used to enumerate five literals by hand, and adding
        ``not_configured`` as a sixth left it silently testing five of six —
        exactly the staleness the derived schema in `dataout/schema.py` avoids
        for columns. `get_args` makes it exhaustive by construction.
        """
        outcomes = get_args(ConnectionResult)
        assert len(outcomes) == 6, outcomes

        for outcome in outcomes:
            monkeypatch.setattr(
                "arichds.api.settings.check_destination_connection",
                lambda _config, _outcome=outcome: ConnectionCheck(_outcome, f"message for {_outcome}", None),
            )
            response = admin_client.post("/api/settings/database-destination/test")

            assert response.status_code == 200, response.text
            assert response.json()["data"]["result"] == outcome
            assert response.json()["data"]["message"] == f"message for {outcome}"

    def test_it_uses_the_stored_settings_not_a_body(
        self, admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No body at all — a Test button that tested something other than
        what is saved would prove nothing about the sync job."""
        _save(admin_client, host="10.1.2.3", port=3399, database="cust", user="svc", password="pw")
        seen: list[object] = []

        def spy(config):
            seen.append(config)
            return ConnectionCheck("ok", "fine", "10.4.32-MariaDB")

        monkeypatch.setattr("arichds.api.settings.check_destination_connection", spy)

        response = admin_client.post("/api/settings/database-destination/test")

        assert response.status_code == 200, response.text
        assert response.json()["data"]["server_version"] == "10.4.32-MariaDB"
        assert (seen[0].host, seen[0].port, seen[0].database, seen[0].user, seen[0].password) == (
            "10.1.2.3",
            3399,
            "cust",
            "svc",
            "pw",
        )

    def test_testing_is_admin_only(self, user_client: TestClient) -> None:
        assert user_client.post("/api/settings/database-destination/test").status_code == 403


class TestFeatureGate:
    """All three routes carry `require_feature("database_destination")`.

    The shape `test_api_billing_captures.py:404-419` established — a licence
    that omits the key gets `FEATURE_DISABLED` with the key as `reason`.
    """

    def test_get_refuses_without_the_feature(self, admin_client: TestClient, relicense) -> None:
        relicense(admin_client, features=["billing", "load_profile"])

        response = admin_client.get("/api/settings/database-destination")

        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FEATURE_DISABLED"
        assert response.json()["error"]["reason"] == "database_destination"

    def test_put_refuses_without_the_feature(self, admin_client: TestClient, relicense) -> None:
        relicense(admin_client, features=["billing", "load_profile"])

        response = _save(admin_client)

        assert response.status_code == 403, response.text
        assert response.json()["error"]["reason"] == "database_destination"

    def test_test_refuses_without_the_feature(self, admin_client: TestClient, relicense) -> None:
        relicense(admin_client, features=["billing", "load_profile"])

        response = admin_client.post("/api/settings/database-destination/test")

        assert response.status_code == 403, response.text
        assert response.json()["error"]["reason"] == "database_destination"


class TestThePasswordNeverReachesALog:
    def test_a_failing_connection_logs_nothing_containing_the_password(
        self, admin_client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Drives a **real** failed connection — port 1 on a host that is not
        listening — and asserts every captured record is clean.

        The two things protecting the password are that `URL.create` hides it
        in `repr()`/`render_as_string()` by default, and that nothing here
        ever passes `hide_password=False`.
        """
        secret = "hunter2-do-not-log-me"
        _save(admin_client, host="127.0.0.1", port=1, user="svc", password=secret)

        with caplog.at_level(logging.DEBUG):
            response = admin_client.post("/api/settings/database-destination/test")

        assert response.json()["data"]["result"] == "unreachable"
        assert secret not in response.text
        for record in caplog.records:
            assert secret not in record.getMessage()
            assert secret not in str(record.exc_info or "")

    def test_the_url_object_hides_the_password_by_default(self) -> None:
        """Pinned rather than trusted: `repr()` and `render_as_string()` both
        mask it, and nothing in this codebase passes `hide_password=False`."""
        url = destination_url(DestinationConfig("h", 3306, "d", "u", "s3cret-value"))

        assert "s3cret-value" not in repr(url)
        assert "s3cret-value" not in url.render_as_string()
        assert "s3cret-value" not in str(url)
        # …and the password really is in there, so the assertions above are
        # about hiding rather than about an empty password.
        assert url.render_as_string(hide_password=False).count("s3cret-value") == 1

    def test_the_redaction_filter_covers_the_setting_key_name(self) -> None:
        """`db_dest_password` ends in the literal `password`, and the filter's
        pattern matches anywhere in the line — so the key needs no new
        pattern. Confirmed by test rather than by reading, because renaming
        the key would silently drop this protection.
        """
        record = logging.LogRecord(
            "t", logging.INFO, __file__, 1, "saving db_dest_password=hunter2 for the destination", None, None
        )

        assert CredentialRedactionFilter().filter(record) is True
        assert "hunter2" not in record.getMessage()
        assert DB_DEST_PASSWORD_KEY.endswith("password")
