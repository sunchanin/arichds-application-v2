"""The Database Destination cycle's pure logic (issue #46).

Window arithmetic and row shaping, tested directly with no server anywhere —
:mod:`arichds.dataout.sync` keeps them as pure functions precisely so this can
be. The round trip against a real MariaDB is ``test_dataout_mysql.py``.

**ADR 0021's named hazard lives here.** The destination speaks local time while
our store speaks UTC, so the watermark comparison crosses a timezone boundary
on every cycle, and *"a missing or doubled conversion is seven hours of
silently duplicated or skipped rows, with no error on either side"*. One shared
pair of functions absorbs it, and these tests are what pin them.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from arichds.constants import (
    DBDEST_WATERMARK_REWIND_SEC,
    METER_LOCAL_UTC_OFFSET_HOURS,
    RETENTION_DAYS,
)
from arichds.dataout import sync
from arichds.dataout.status import last_sync, set_last_sync
from arichds.dataout.sync import (
    _from_local,
    _local_row,
    _purge_cutoff,
    _to_local,
    _watermark_start,
)
from arichds.db.app_settings import (
    DB_DEST_DATABASE_KEY,
    DB_DEST_HOST_KEY,
    DB_DEST_PASSWORD_KEY,
    DB_DEST_PORT_KEY,
    DB_DEST_USER_KEY,
    set_setting,
)
from arichds.db.session import session_scope
from arichds.licensing.current import set_current_license_service
from arichds.licensing.service import LicenseState


class _StubLicenseService:
    """A minimal stand-in satisfying `feature_enabled`'s one call —
    `.current_state()` — without going through a real activation flow. Copied
    from `test_billing_eager_capture.py:56-71`, which is where this shape was
    established for the other background feature gate."""

    def __init__(self, features: list[str] | None) -> None:
        self._features = features

    def current_state(self) -> LicenseState:
        return LicenseState(state="active", reason=None, features=self._features)


@pytest.fixture
def license_features():
    def apply(features: list[str] | None) -> None:
        set_current_license_service(_StubLicenseService(features))

    yield apply
    set_current_license_service(None)


@pytest.fixture(autouse=True)
def _clear_status():
    """The status is process-wide (ADR 0008 — in memory, nowhere else), so one
    test's cycle would otherwise be visible to the next."""
    set_last_sync(None)
    yield
    set_last_sync(None)


def _configure(*, host: str, database: str) -> None:
    """Write the five Database Destination settings rows."""
    with session_scope() as session:
        set_setting(session, DB_DEST_HOST_KEY, host)
        set_setting(session, DB_DEST_PORT_KEY, "3306")
        set_setting(session, DB_DEST_DATABASE_KEY, database)
        set_setting(session, DB_DEST_USER_KEY, "root")
        set_setting(session, DB_DEST_PASSWORD_KEY, "")


def _explode(*_args, **_kwargs):
    """Stand-in for `create_destination_engine` that must never be called."""
    raise AssertionError("the cycle tried to connect when it should have returned first")


def _raiser(exc: BaseException):
    def _fail(*_args, **_kwargs):
        raise exc

    return _fail


def _spy_on_the_three_work_functions(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record which pieces of work a cycle reaches, with no server anywhere."""
    called: list[str] = []
    monkeypatch.setattr(sync, "create_destination_engine", lambda *_a, **_k: _FakeEngine())
    monkeypatch.setattr(sync, "reconcile", lambda _connection: None)
    monkeypatch.setattr(sync, "_replace_billing", lambda *_a, **_k: called.append("billing"))
    monkeypatch.setattr(sync, "_append_load_profile", lambda *_a, **_k: called.append("load_profile"))
    monkeypatch.setattr(sync, "_purge_destination", lambda *_a, **_k: called.append("purge"))
    return called


class _FakeEngine:
    """Just enough Engine for `_run_cycle`'s `reconcile` step and `dispose()`."""

    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def dispose(self) -> None:
        return None


class TestLocalTimeConversion:
    def test_to_local_shifts_by_exactly_the_constant(self) -> None:
        """Measured live on the design probe: `2026-08-24 13:15:00` UTC
        arrived as `2026-08-24 20:15:00`."""
        assert _to_local(datetime(2026, 8, 24, 13, 15, tzinfo=UTC)) == datetime(2026, 8, 24, 20, 15)

    def test_to_local_returns_a_naive_datetime(self) -> None:
        """The destination's columns are `DATETIME`, which carries no zone —
        a tz-aware value handed to PyMySQL would be rendered with an offset
        the column cannot hold."""
        assert _to_local(datetime(2026, 8, 24, 13, 15, tzinfo=UTC)).tzinfo is None

    def test_to_local_treats_a_naive_input_as_utc(self) -> None:
        """SQLite hands datetimes back naive even from a
        `DateTime(timezone=True)` column, and every one of them is UTC by
        CLAUDE.md's write-time normalization invariant."""
        assert _to_local(datetime(2026, 8, 24, 13, 15)) == datetime(2026, 8, 24, 20, 15)

    def test_from_local_is_the_inverse_and_is_utc_aware(self) -> None:
        assert _from_local(datetime(2026, 8, 24, 20, 15)) == datetime(2026, 8, 24, 13, 15, tzinfo=UTC)

    def test_the_pair_round_trips(self) -> None:
        original = datetime(2026, 3, 31, 17, 0, tzinfo=UTC)

        assert _from_local(_to_local(original)) == original

    def test_bill_date_crosses_midnight_exactly_as_adr_0021_predicts(self) -> None:
        """A period the meter closed at `2026-03-31 17:00 UTC` lands in the
        destination as `2026-04-01 00:00`. **That is correct** — the meter's
        own local cut time — not a bug to fix."""
        assert _to_local(datetime(2026, 3, 31, 17, 0, tzinfo=UTC)) == datetime(2026, 4, 1, 0, 0)

    def test_the_shift_really_is_the_constant_and_not_a_hardcoded_seven(self) -> None:
        """So a mutation of `METER_LOCAL_UTC_OFFSET_HOURS` moves this, which
        is what makes rows 9's two mutations meaningful."""
        base = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

        assert _to_local(base) - base.replace(tzinfo=None) == timedelta(hours=METER_LOCAL_UTC_OFFSET_HOURS)


class TestPurgeCutoff:
    def test_the_cutoff_is_computed_in_local_time(self) -> None:
        """ADR 0020's named silent failure: computing this in UTC deletes
        seven hours too much from the customer's database on **every** cycle,
        with nothing on either side to notice."""
        now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)

        assert _purge_cutoff(now) == datetime(2026, 8, 24, 12, 0) - timedelta(days=RETENTION_DAYS) + timedelta(
            hours=METER_LOCAL_UTC_OFFSET_HOURS
        )

    def test_the_cutoff_is_naive(self) -> None:
        assert _purge_cutoff(datetime(2026, 8, 24, 12, 0, tzinfo=UTC)).tzinfo is None

    def test_a_utc_cutoff_would_be_seven_hours_earlier_and_delete_more(self) -> None:
        """Pins the direction of the error, so a mutation cannot pass by
        being wrong the other way."""
        now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
        naive_utc_cutoff = (now - timedelta(days=RETENTION_DAYS)).replace(tzinfo=None)

        assert _purge_cutoff(now) > naive_utc_cutoff
        assert _purge_cutoff(now) - naive_utc_cutoff == timedelta(hours=METER_LOCAL_UTC_OFFSET_HOURS)


class TestWatermarkStart:
    def test_a_destination_watermark_is_converted_back_to_utc_before_comparison(self) -> None:
        """The destination's `MAX(read_at)` is **local**; the source's
        `read_at` is UTC. Comparing them without converting is ADR 0021's
        seven-hour hazard."""
        destination_max = datetime(2026, 8, 24, 20, 15)  # local

        start = _watermark_start(destination_max)

        assert start.tzinfo is UTC
        assert start == datetime(2026, 8, 24, 13, 15, tzinfo=UTC) - timedelta(seconds=DBDEST_WATERMARK_REWIND_SEC)

    def test_the_watermark_is_rewound_by_the_safety_margin(self) -> None:
        """Bounded waste instead of silent corruption (ADR 0021): the re-sent
        rows collapse onto themselves through ON DUPLICATE KEY UPDATE."""
        destination_max = datetime(2026, 8, 24, 20, 15)

        assert _from_local(destination_max) - _watermark_start(destination_max) == timedelta(
            seconds=DBDEST_WATERMARK_REWIND_SEC
        )
        assert DBDEST_WATERMARK_REWIND_SEC > 0

    def test_no_watermark_means_send_everything_we_hold(self) -> None:
        """A destination that has never seen this `(serial, logger)` gets the
        first cycle's backfill — 61,023 rows on the design probe."""
        assert _watermark_start(None) is None


class TestLocalRow:
    def test_every_datetime_value_is_converted_and_nothing_else_is(self) -> None:
        row = {
            "meter_serial": "WP079074",
            "read_at": datetime(2026, 8, 24, 13, 15, tzinfo=UTC),
            "created_at": datetime(2026, 8, 24, 13, 20, tzinfo=UTC),
            "logger_id": 2,
            "import_active_kwh": 0.0085671,
            "avg_geo_pf": None,
        }

        converted = _local_row(row)

        assert converted["read_at"] == datetime(2026, 8, 24, 20, 15)
        assert converted["created_at"] == datetime(2026, 8, 24, 20, 20)
        assert converted["meter_serial"] == "WP079074"
        assert converted["logger_id"] == 2
        assert converted["import_active_kwh"] == 0.0085671  # value unchanged, probe-confirmed
        assert converted["avg_geo_pf"] is None

    def test_a_none_datetime_stays_none(self) -> None:
        """Thirteen of billing's columns are NULL on a real row, including
        Demand Time columns — converting `None` must not raise."""
        assert _local_row({"max_demand_import_active_time_total": None})["max_demand_import_active_time_total"] is None

    def test_an_empty_row_is_an_empty_row(self) -> None:
        assert _local_row({}) == {}

    def test_the_source_row_is_not_mutated(self) -> None:
        """The caller may still hold it — an in-place shift would double on a
        retry."""
        row = {"read_at": datetime(2026, 8, 24, 13, 15, tzinfo=UTC)}

        _local_row(row)

        assert row["read_at"] == datetime(2026, 8, 24, 13, 15, tzinfo=UTC)


class TestLicenceGating:
    """The job's own gates — the **background** shape (`feature_enabled` with
    `current_license_service()`), not `require_feature`: there is no `Request`
    on the scheduler thread.

    Limited Mode needs nothing extra here: it stops the whole scheduler thread
    already (`jobs/scheduler.py::on_license_state`).
    """

    def test_without_the_feature_the_job_does_nothing_at_all(
        self, migrated_db, license_features, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not even a connection attempt — an unlicensed machine must not
        appear in the customer's server logs."""
        _configure(host="127.0.0.1", database="d")
        monkeypatch.setattr(sync, "create_destination_engine", _explode)
        license_features(["billing", "load_profile"])

        sync.database_destination_cycle()

        assert last_sync() is None  # status untouched — it never ran

    def test_an_unconfigured_destination_returns_before_connecting(
        self, migrated_db, license_features, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`""` means "not configured"; that is not a fault and must not be
        recorded as one."""
        _configure(host="", database="")
        monkeypatch.setattr(sync, "create_destination_engine", _explode)
        license_features(None)  # every sellable key

        sync.database_destination_cycle()

        assert last_sync() is None

    def test_a_host_without_a_database_is_still_unconfigured(
        self, migrated_db, license_features, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _configure(host="127.0.0.1", database="")
        monkeypatch.setattr(sync, "create_destination_engine", _explode)
        license_features(None)

        sync.database_destination_cycle()

        assert last_sync() is None

    def test_without_billing_no_billing_rows_are_written(
        self, migrated_db, license_features, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = _spy_on_the_three_work_functions(monkeypatch)
        _configure(host="127.0.0.1", database="d")
        license_features(["database_destination", "load_profile"])

        sync.database_destination_cycle()

        assert "billing" not in called
        assert "load_profile" in called
        assert "purge" in called

    def test_without_load_profile_no_interval_readings_and_no_purge(
        self, migrated_db, license_features, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The purge goes with its table: purging a destination we are not
        allowed to append to would drain the customer's rows to nothing."""
        called = _spy_on_the_three_work_functions(monkeypatch)
        _configure(host="127.0.0.1", database="d")
        license_features(["database_destination", "billing"])

        sync.database_destination_cycle()

        assert "billing" in called
        assert "load_profile" not in called
        assert "purge" not in called

    def test_with_every_key_all_three_run_in_order(
        self, migrated_db, license_features, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Billing first because it is small, bounded and all-or-nothing, and
        a large first-run load-profile backfill must not starve it."""
        called = _spy_on_the_three_work_functions(monkeypatch)
        _configure(host="127.0.0.1", database="d")
        license_features(None)

        sync.database_destination_cycle()

        assert called == ["billing", "load_profile", "purge"]

    def test_a_failure_is_recorded_on_the_status_and_never_propagates(
        self, migrated_db, license_features, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The scheduler runs jobs sequentially on one thread; a customer's
        database being down must not strand the meter reads. And the page must
        be able to say *why*, or the operator cannot tell a working sync from
        a silent one."""
        _configure(host="127.0.0.1", database="d")
        monkeypatch.setattr(
            sync, "create_destination_engine", _raiser(RuntimeError("the customer unplugged the server"))
        )
        license_features(None)

        sync.database_destination_cycle()

        status = last_sync()
        assert status is not None
        assert status.error is not None
        assert "the customer unplugged the server" in status.error
        assert status.load_profile_rows == 0


class TestThePasswordNeverLeavesTheCycle:
    def test_a_real_failed_cycle_puts_no_password_in_the_status_or_the_log(
        self, migrated_db, license_features, caplog: pytest.LogCaptureFixture
    ) -> None:
        """`SyncStatus.error` is rendered on the page, so a driver message that
        embedded the connection URL would put the password on screen as well as
        in the log. Driven against a **real** refused connection (port 1) so
        the assertion is about what PyMySQL and SQLAlchemy actually produce,
        not about what they are assumed to.
        """
        secret = "cycle-secret-do-not-leak"
        _configure(host="127.0.0.1", database="nope")
        with session_scope() as session:
            set_setting(session, DB_DEST_PORT_KEY, "1")
            set_setting(session, DB_DEST_PASSWORD_KEY, secret)
        license_features(None)

        with caplog.at_level(logging.DEBUG):
            sync.database_destination_cycle()

        status = last_sync()
        assert status is not None
        assert status.error is not None, "a refused connection must be reported, not silently swallowed"
        assert secret not in status.error
        for record in caplog.records:
            assert secret not in record.getMessage()
            assert secret not in str(record.exc_info or "")


class TestItDoesNotShareTheExportHelper:
    def test_sync_does_not_import_from_export(self) -> None:
        """ADR 0021's Consequences forbid it explicitly: the two boundaries
        agree today by coincidence of one constant, not by contract, and a
        shared helper would make a future change to one silently change the
        other."""
        source = (
            pytest.importorskip("pathlib")
            .Path(__import__("arichds.dataout.sync", fromlist=["_"]).__file__)
            .read_text(encoding="utf-8")
        )

        assert "arichds.export" not in source
        assert "from arichds.capture" not in source
