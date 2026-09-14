"""The Central Push cycle (ADR 0024, spec.md "Central Push"; M14 ticket 08).

Driven against :class:`FakeCentralPushReceiver`, an in-process HTTP server
implementing contract version 1 — the same "assert only on what the fake
holds" discipline `test_dataout_mysql.py` uses against a real MariaDB.
`test_api_central_push.py` (ticket 07) owns the settings/contract HTTP
surface; this file owns the cycle itself: the scheduler job, the
holdings/push client, and everything that writes `centralpush/status.py`.
"""

from __future__ import annotations

import socket
import time
from datetime import UTC, date, datetime, timedelta

import jwt
import pytest
from conftest import TEST_MACHINE_ID, VENDOR_PRIVATE_KEY_PEM, VENDOR_PUBLIC_KEY_PEM
from fake_central_push_receiver import FakeCentralPushReceiver

from arichds.centralpush import client as centralpush_client
from arichds.centralpush import cycle as centralpush_cycle_module
from arichds.centralpush.contract import BillingItem, EnergySummaryItem
from arichds.centralpush.cycle import _load_profile_start, central_push_cycle
from arichds.centralpush.status import last_cycle, set_last_cycle
from arichds.constants import CENTRAL_PUSH_LOAD_PROFILE_REWIND_SEC, SOURCE_DLMS
from arichds.db.app_settings import (
    CENTRAL_PUSH_TOKEN_KEY,
    CENTRAL_PUSH_URL_KEY,
    DISPLAY_UNIT_SCALE_KEY,
    set_setting,
)
from arichds.db.models import BillingReading, Device, EnergySummaryDay, LoadProfileReading
from arichds.db.session import session_scope
from arichds.licensing.current import set_current_license_service
from arichds.licensing.push_token import PUSH_TOKEN_ALGORITHM, build_push_token_claims
from arichds.licensing.service import LicenseState


class _StubLicenseService:
    """The same minimal stand-in `test_dataout_sync.py` uses for the
    background-path licence gate, plus `.machine_id` — the cycle needs it
    for the envelope's `machine_id` field."""

    def __init__(self, features: list[str] | None, *, machine_id: str = TEST_MACHINE_ID) -> None:
        self._features = features
        self.machine_id = machine_id

    def current_state(self) -> LicenseState:
        return LicenseState(state="active", reason=None, features=self._features)


@pytest.fixture
def license_features():
    def apply(features: list[str] | None, *, machine_id: str = TEST_MACHINE_ID) -> None:
        set_current_license_service(_StubLicenseService(features, machine_id=machine_id))

    yield apply
    set_current_license_service(None)


@pytest.fixture(autouse=True)
def _clear_status():
    """The status is process-wide (ADR 0008), so one test's cycle would
    otherwise be visible to the next."""
    set_last_cycle(None)
    yield
    set_last_cycle(None)


@pytest.fixture
def receiver():
    fake = FakeCentralPushReceiver(public_key_pem=VENDOR_PUBLIC_KEY_PEM)
    yield fake
    fake.shutdown()


def mint_push_token(*, machine_id: str = TEST_MACHINE_ID) -> str:
    """Issue a Push Token with the suite's throwaway vendor key — everything
    `tools/arichds_vendor.py sign-push` does, without shelling out to it
    (mirrors `test_api_central_push.py::mint_push_token`)."""
    claims = build_push_token_claims(machine_id=machine_id)
    return jwt.encode(claims, VENDOR_PRIVATE_KEY_PEM, algorithm=PUSH_TOKEN_ALGORITHM)


def _configure(url: str, *, token: str | None = None) -> None:
    with session_scope() as session:
        set_setting(session, CENTRAL_PUSH_URL_KEY, url)
        if token is not None:
            set_setting(session, CENTRAL_PUSH_TOKEN_KEY, token)


def make_device(name: str = "Meter A", *, serial: str | None = "SN0001") -> int:
    with session_scope() as session:
        device = Device(
            name=name,
            brand="cewe",
            model="prometer100",
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="hunter2",
            meter_serial=serial,
        )
        session.add(device)
        session.flush()
        return device.id


def seed_billing(
    device_id: int,
    *,
    bill_date: datetime,
    record_status: str | None,
    total: float,
    updated_at: datetime | None = None,
) -> None:
    with session_scope() as session:
        session.add(
            BillingReading(
                device_id=device_id,
                bill_date=bill_date,
                read_at=bill_date,
                record_status=record_status,
                source=SOURCE_DLMS,
                import_active_kwh_total=total,
                # An explicit `updated_at` (never left to `server_default`,
                # which is real wall-clock "now") is what lets a test control
                # ordering against a *later* explicit update deterministically
                # — the seed dates below are in the past relative to the real
                # clock, and `server_default=func.now()` would otherwise make
                # the very first insert the "newest" thing in the row.
                updated_at=updated_at if updated_at is not None else bill_date,
            )
        )


def seed_energy_summary(device_id: int, *, local_date: date, total_import_kwh: float, updated_at: datetime) -> None:
    with session_scope() as session:
        session.add(
            EnergySummaryDay(
                device_id=device_id,
                local_date=local_date,
                total_import_kwh=total_import_kwh,
                updated_at=updated_at,
            )
        )


def seed_load_profile(device_id: int, *, read_at: datetime, logger_id: int = 1, import_active_kwh: float = 1.0) -> None:
    with session_scope() as session:
        session.add(
            LoadProfileReading(
                device_id=device_id,
                read_at=read_at,
                source=SOURCE_DLMS,
                logger_id=logger_id,
                interval_sec=900,
                import_active_kwh=import_active_kwh,
            )
        )


class TestOptOut:
    def test_no_url_configured_the_receiver_sees_no_request_at_all(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        _configure("", token=mint_push_token())
        license_features(None)

        central_push_cycle()

        assert receiver.request_count == 0
        assert last_cycle() is None  # status untouched — the cycle never ran


class TestFirstAndSecondCycle:
    def test_first_sends_everything_second_sends_only_the_roster(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        """Load profile is deliberately absent from this scenario — its
        safety-margin rewind (ADR 0024) structurally re-sends the row that
        set the watermark on every following cycle (the same property
        `test_dataout_mysql.py::test_a_steady_state_cycle_re_reads_only_the_rewind_window`
        proves for the Database Destination's own rewind), so a *strict*
        "only the roster" claim is only exact for billing and the Energy
        Summary, which carry no rewind. `TestLoadProfileSafetyMargin` below
        covers load profile's own, bounded, re-send."""
        device_id = make_device(serial="SN0001")
        seed_billing(device_id, bill_date=datetime(2026, 8, 1, tzinfo=UTC), record_status=None, total=10.0)
        seed_energy_summary(
            device_id, local_date=date(2026, 8, 1), total_import_kwh=5.0, updated_at=datetime(2026, 8, 1, tzinfo=UTC)
        )
        _configure(receiver.url, token=mint_push_token())
        license_features(None)

        central_push_cycle()

        assert set(receiver.meters) == {"SN0001"}
        assert len(receiver.billing) == 1
        assert len(receiver.energy_summary) == 1
        status = last_cycle()
        assert status is not None
        assert status.outcome == "success"
        assert status.billing_rows == 1
        assert status.energy_summary_rows == 1

        pushes_after_first = len(receiver.pushes)

        central_push_cycle()

        new_pushes = receiver.pushes[pushes_after_first:]
        assert [push["kind"] for push in new_pushes] == ["meters"]
        status2 = last_cycle()
        assert status2 is not None
        assert status2.billing_rows == 0
        assert status2.energy_summary_rows == 0
        assert status2.meters_rows == 1


class TestRosterFullSnapshot:
    def test_a_deleted_device_makes_the_next_roster_empty(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        """A review's own minor: `receiver.meters == {}` holds whether an
        empty roster was actually sent or nothing was sent at all — this
        pins the real behaviour by also checking the last `meters` push's
        `items` list, which only an actually-sent empty envelope produces
        (`push_kind(..., send_when_empty=True)`, ADR 0024: the roster is a
        full snapshot every cycle, so an empty one is the only way the
        server learns every meter is gone)."""
        device_id = make_device(serial="SN0001")
        _configure(receiver.url, token=mint_push_token())
        license_features(None)
        central_push_cycle()
        assert set(receiver.meters) == {"SN0001"}

        with session_scope() as session:
            session.delete(session.get(Device, device_id))

        central_push_cycle()

        assert receiver.meters == {}
        meters_pushes = [push for push in receiver.pushes if push["kind"] == "meters"]
        assert meters_pushes[-1]["items"] == []


class TestChangedRowsAreResent:
    def test_a_changed_open_period_is_resent(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        device_id = make_device(serial="SN0001")
        seed_billing(device_id, bill_date=datetime(2026, 8, 1, tzinfo=UTC), record_status="open", total=10.0)
        _configure(receiver.url, token=mint_push_token())
        license_features(None)
        central_push_cycle()
        billing_key = next(iter(receiver.billing))
        assert receiver.billing[billing_key]["import_active_kwh_total"] == 10.0

        with session_scope() as session:
            row = session.query(BillingReading).filter_by(device_id=device_id).one()
            row.import_active_kwh_total = 12.5
            row.updated_at = datetime(2026, 8, 2, tzinfo=UTC)  # force a later, unambiguous updated_at

        central_push_cycle()

        stored = receiver.billing[billing_key]
        assert stored["import_active_kwh_total"] == 12.5
        assert stored["is_open"] is True

    def test_an_energy_summary_day_moved_by_a_holiday_change_and_recompute_is_resent(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        device_id = make_device(serial="SN0001")
        seed_energy_summary(
            device_id, local_date=date(2026, 8, 1), total_import_kwh=5.0, updated_at=datetime(2026, 8, 1, tzinfo=UTC)
        )
        _configure(receiver.url, token=mint_push_token())
        license_features(None)
        central_push_cycle()
        assert receiver.energy_summary[("SN0001", "2026-08-01")]["total_import_kwh"] == 5.0

        # A Holiday change plus a recompute (ADR 0022) — stand in for the
        # real recompute job with the same effect it has: the bucket value
        # and `updated_at` both move.
        with session_scope() as session:
            row = session.query(EnergySummaryDay).filter_by(device_id=device_id).one()
            row.total_import_kwh = 8.0
            row.updated_at = datetime(2026, 8, 2, tzinfo=UTC)

        central_push_cycle()

        assert receiver.energy_summary[("SN0001", "2026-08-01")]["total_import_kwh"] == 8.0


class TestCatchUp:
    def test_a_receiver_that_lost_its_data_gets_everything_back_next_cycle(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        device_id = make_device(serial="SN0001")
        seed_billing(device_id, bill_date=datetime(2026, 8, 1, tzinfo=UTC), record_status=None, total=10.0)
        seed_energy_summary(
            device_id, local_date=date(2026, 8, 1), total_import_kwh=5.0, updated_at=datetime(2026, 8, 1, tzinfo=UTC)
        )
        seed_load_profile(device_id, read_at=datetime(2026, 8, 1, tzinfo=UTC))
        _configure(receiver.url, token=mint_push_token())
        license_features(None)
        central_push_cycle()
        assert receiver.billing and receiver.energy_summary and receiver.load_profile

        # The receiving server lost its data — nothing in our store changed.
        receiver.billing.clear()
        receiver.energy_summary.clear()
        receiver.load_profile.clear()

        central_push_cycle()

        assert len(receiver.billing) == 1
        assert len(receiver.energy_summary) == 1
        assert len(receiver.load_profile) == 1


class TestFailure:
    def test_a_closed_port_ends_the_cycle_skipped_with_status_recorded(self, migrated_db, license_features) -> None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
        probe.close()  # nothing listens here now

        _configure(f"http://127.0.0.1:{closed_port}", token=mint_push_token())
        license_features(None)

        central_push_cycle()

        status = last_cycle()
        assert status is not None
        assert status.outcome == "skipped"
        assert status.error is not None

    def test_an_https_url_on_a_closed_port_ends_skipped_with_a_transport_error_not_typeerror(
        self, migrated_db, license_features
    ) -> None:
        """A blocker a review caught: `_SplitTimeoutHTTPSHandler.https_open`
        was passing `check_hostname=` to `do_open`, a keyword `HTTPSConnection`
        dropped in Python 3.12 — every `https://` URL raised `TypeError`
        before connecting, on this 3.14 runtime, which is not
        `URLError`/`OSError` and so escaped `_round_trip` uncaught. The real
        central server is HTTPS (SPEC §3.8), so this is the scheme that must
        actually work. `error` must never be `"TypeError"` — that would mean
        the TLS handshake path is still broken, not that the port refused."""
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
        probe.close()  # nothing listens here now

        _configure(f"https://127.0.0.1:{closed_port}", token=mint_push_token())
        license_features(None)

        central_push_cycle()

        status = last_cycle()
        assert status is not None
        assert status.outcome == "skipped"
        assert status.error is not None
        assert status.error != "TypeError", f"the https:// path is still broken: {status.error}"

    def test_a_stalling_receiver_is_abandoned_within_the_time_budget(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bounded so it cannot hang the suite: the receiver sleeps far
        longer than the read timeout, and the read timeout is shortened so
        the whole test finishes in well under a second either way. If the
        read timeout were dropped, this would instead take the full stall —
        still finite, but the wall-clock assertion below catches it."""
        monkeypatch.setattr(centralpush_client, "CENTRAL_PUSH_READ_TIMEOUT_SEC", 0.3)
        receiver.stall_seconds = 5.0
        _configure(receiver.url, token=mint_push_token())
        license_features(None)

        started = time.monotonic()
        central_push_cycle()
        elapsed = time.monotonic() - started

        assert elapsed < 2.0, f"the read timeout was not honoured — took {elapsed:.2f}s"
        status = last_cycle()
        assert status is not None
        assert status.outcome == "skipped"

    def test_a_wrong_token_is_refused_by_the_receiver_and_the_cycle_ends_skipped(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        _configure(receiver.url, token="not-a-real-push-token")
        license_features(None)

        central_push_cycle()

        assert receiver.unauthorized_requests >= 1
        status = last_cycle()
        assert status is not None
        assert status.outcome == "skipped"

    def test_a_failed_push_is_not_retried_within_the_cycle(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        device_id = make_device(serial="SN0001")
        seed_billing(device_id, bill_date=datetime(2026, 8, 1, tzinfo=UTC), record_status=None, total=10.0)
        seed_energy_summary(
            device_id, local_date=date(2026, 8, 1), total_import_kwh=5.0, updated_at=datetime(2026, 8, 1, tzinfo=UTC)
        )
        receiver.fail_next_push_for_kind = "billing"
        _configure(receiver.url, token=mint_push_token())
        license_features(None)

        central_push_cycle()

        billing_attempts = [push for push in receiver.pushes if push["kind"] == "billing"]
        assert billing_attempts == []  # the failed attempt was never stored
        # And the cycle stopped right there — energy_summary, which sits
        # behind billing, was never attempted at all.
        energy_attempts = [push for push in receiver.pushes if push["kind"] == "energy_summary"]
        assert energy_attempts == []
        status = last_cycle()
        assert status is not None
        assert status.outcome == "skipped"


class TestFiltering:
    def test_billing_is_not_sent_when_the_feature_is_not_licensed(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        device_id = make_device(serial="SN0001")
        seed_billing(device_id, bill_date=datetime(2026, 8, 1, tzinfo=UTC), record_status=None, total=10.0)
        _configure(receiver.url, token=mint_push_token())
        license_features(["load_profile", "energy_summary"])

        central_push_cycle()

        assert receiver.billing == {}
        assert receiver.meters  # the roster carries no licence key at all

    def test_load_profile_is_not_sent_when_the_feature_is_not_licensed(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        device_id = make_device(serial="SN0001")
        seed_load_profile(device_id, read_at=datetime(2026, 8, 1, tzinfo=UTC))
        _configure(receiver.url, token=mint_push_token())
        license_features(["billing", "energy_summary"])

        central_push_cycle()

        assert receiver.load_profile == {}

    def test_energy_summary_is_not_sent_when_the_feature_is_not_licensed(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        device_id = make_device(serial="SN0001")
        seed_energy_summary(
            device_id, local_date=date(2026, 8, 1), total_import_kwh=5.0, updated_at=datetime(2026, 8, 1, tzinfo=UTC)
        )
        _configure(receiver.url, token=mint_push_token())
        license_features(["billing", "load_profile"])

        central_push_cycle()

        assert receiver.energy_summary == {}

    def test_rows_without_a_known_meter_serial_are_not_sent_and_are_counted(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        serialless_id = make_device(name="No serial", serial=None)
        seed_billing(serialless_id, bill_date=datetime(2026, 8, 1, tzinfo=UTC), record_status=None, total=1.0)
        seed_energy_summary(
            serialless_id,
            local_date=date(2026, 8, 1),
            total_import_kwh=1.0,
            updated_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
        seed_load_profile(serialless_id, read_at=datetime(2026, 8, 1, tzinfo=UTC))
        _configure(receiver.url, token=mint_push_token())
        license_features(None)

        central_push_cycle()

        assert receiver.meters == {}
        assert receiver.billing == {}
        assert receiver.energy_summary == {}
        assert receiver.load_profile == {}
        status = last_cycle()
        assert status is not None
        # One skip per kind that saw the serial-less device: meters, billing,
        # energy_summary, and one load-profile (device, logger) pair.
        assert status.skipped_rows == 4


class TestValues:
    def test_every_instant_carries_a_utc_offset(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        device_id = make_device(serial="SN0001")
        seed_load_profile(device_id, read_at=datetime(2026, 8, 1, 0, 0, tzinfo=UTC))
        seed_billing(device_id, bill_date=datetime(2026, 8, 1, tzinfo=UTC), record_status=None, total=1.0)
        _configure(receiver.url, token=mint_push_token())
        license_features(None)

        central_push_cycle()

        lp_read_at = next(iter(receiver.load_profile.values()))["read_at"]
        billing_bill_date = next(iter(receiver.billing.values()))["bill_date"]
        # `fromisoformat` raises on a naive-looking string with no offset,
        # so parsing back and reading `.utcoffset()` is the honest check —
        # not a string `in` check, which a differently-formatted offset
        # would still pass by accident.
        assert datetime.fromisoformat(lp_read_at).utcoffset() is not None
        assert datetime.fromisoformat(billing_bill_date).utcoffset() is not None

    def test_energy_is_kwh_regardless_of_the_display_unit_setting(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        device_id = make_device(serial="SN0001")
        seed_energy_summary(
            device_id, local_date=date(2026, 8, 1), total_import_kwh=5.5, updated_at=datetime(2026, 8, 1, tzinfo=UTC)
        )
        with session_scope() as session:
            set_setting(session, DISPLAY_UNIT_SCALE_KEY, "base")  # W instead of kW, at render time only
        _configure(receiver.url, token=mint_push_token())
        license_features(None)

        central_push_cycle()

        assert receiver.energy_summary[("SN0001", "2026-08-01")]["total_import_kwh"] == 5.5


class TestBudget:
    def test_the_cycle_stops_at_its_time_budget_but_the_roster_still_goes(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        device_id = make_device(serial="SN0001")
        seed_billing(device_id, bill_date=datetime(2026, 8, 1, tzinfo=UTC), record_status=None, total=1.0)
        seed_energy_summary(
            device_id, local_date=date(2026, 8, 1), total_import_kwh=1.0, updated_at=datetime(2026, 8, 1, tzinfo=UTC)
        )
        seed_load_profile(device_id, read_at=datetime(2026, 8, 1, tzinfo=UTC))
        monkeypatch.setattr(centralpush_cycle_module, "CENTRAL_PUSH_BUDGET_SEC", 0.0)
        _configure(receiver.url, token=mint_push_token())
        license_features(None)

        central_push_cycle()

        assert receiver.meters  # always sent, budget or not
        assert receiver.billing == {}
        assert receiver.energy_summary == {}
        assert receiver.load_profile == {}
        status = last_cycle()
        assert status is not None
        assert status.outcome == "success"  # ran out of time, did not fail

    def test_the_budget_is_checked_before_every_chunk_not_once_per_kind(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reproduces a review's own probe exactly: budget 0.6s, a
        0.25s/request receiver, item cap 1, 8 billing rows. Before this
        fix the whole kind ran to completion regardless of the budget
        (checked once, before `_send_billing` was even called) — measured
        at 2.69s, all 8 sent. Bounded here so the assertion below is what
        catches a regression, not a hung test: even the worst case (every
        one of the 8 chunks attempted) is only 8 * 0.25s = 2.0s plus the
        holdings/roster requests, nothing close to hanging the suite."""
        monkeypatch.setattr(centralpush_client, "CENTRAL_PUSH_ITEM_CAP", 1)
        monkeypatch.setattr(centralpush_cycle_module, "CENTRAL_PUSH_BUDGET_SEC", 0.6)
        receiver.stall_seconds = 0.25
        device_id = make_device(serial="SN0001")
        for month in range(1, 9):
            seed_billing(device_id, bill_date=datetime(2026, month, 1, tzinfo=UTC), record_status=None, total=1.0)
        _configure(receiver.url, token=mint_push_token())
        license_features(None)

        started = time.monotonic()
        central_push_cycle()
        elapsed = time.monotonic() - started

        assert elapsed < 1.5, f"the budget was not honoured per-chunk — took {elapsed:.2f}s"
        assert len(receiver.billing) < 8, "every row was sent — the per-chunk budget check did not stop anything"
        status = last_cycle()
        assert status is not None
        assert status.outcome == "success"  # a budget stop is not a failure

    def test_the_budget_is_checked_before_every_load_profile_pair_too(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_send_load_profile` walks its own list of `(device, logger)`
        pairs, one `push_kind` call each. `push_kind`'s own per-chunk check
        (proved by `test_the_budget_is_checked_before_every_chunk_not_once_per_kind`
        above) already keeps a pair whose budget has run out from making an
        HTTP call — so a wall-clock/received-rows assertion alone cannot
        tell a per-*pair* check apart from relying on `push_kind` alone.
        What a per-pair check (`dataout/sync.py:375`'s own pattern) actually
        buys is skipping the DB read and item-building for every pair after
        the budget is spent — real, unbounded work on a first-run backfill
        of many pairs (the review's own ~345k-row/~70-pair estimate) that a
        review-caught bug would otherwise still do in full before `push_kind`
        quietly no-ops. Counting calls to `push_kind` itself is what makes
        that visible: without the per-pair check, one call happens for every
        pair regardless of the budget; with it, the loop returns before
        reaching the pairs behind the deadline."""
        push_kind_calls = 0
        real_push_kind = centralpush_cycle_module.push_kind

        def counting_push_kind(*args, **kwargs):
            nonlocal push_kind_calls
            push_kind_calls += 1
            return real_push_kind(*args, **kwargs)

        monkeypatch.setattr(centralpush_cycle_module, "push_kind", counting_push_kind)
        monkeypatch.setattr(centralpush_cycle_module, "CENTRAL_PUSH_BUDGET_SEC", 0.6)
        receiver.stall_seconds = 0.25
        for n in range(8):
            device_id = make_device(name=f"Meter {n}", serial=f"SN{n:04d}")
            seed_load_profile(device_id, read_at=datetime(2026, 8, 1, tzinfo=UTC))
        _configure(receiver.url, token=mint_push_token())
        license_features(None)

        started = time.monotonic()
        central_push_cycle()
        elapsed = time.monotonic() - started

        assert elapsed < 1.5, f"the budget was not honoured — took {elapsed:.2f}s"
        # 1 call each for the roster, billing (empty — none seeded) and the
        # Energy Summary (empty), plus at most a couple of load-profile
        # pairs before the 0.6s budget (already ~0.5s spent on holdings and
        # the roster push, both slowed by the same receiver) runs out —
        # nowhere near one call per pair (3 + 8 = 11).
        assert push_kind_calls < 3 + 8, (
            f"push_kind was called for every pair ({push_kind_calls} calls total) — "
            "the per-pair budget check did not stop the loop early"
        )
        status = last_cycle()
        assert status is not None
        assert status.outcome == "success"  # a budget stop is not a failure


class TestPartialSendOrderingSafety:
    """A review's own hazard: once a kind's send can stop partway (the
    budget check above, or a later chunk's request failing), an UNSENT row
    whose `updated_at` is older than one already accepted for the same
    meter would be lost forever — the next cycle's watermark compare
    (`updated_at <= threshold`) treats it as already covered. `_send_billing`
    and `_send_energy_summary` order their query by Meter Serial then
    `updated_at` ascending so every *prefix* of a partial send stays safe.
    `push_kind` is faked out here — no network, no receiver — so this is a
    pure read of the order `_send_billing`/`_send_energy_summary` would
    actually push, straight off a real SQLite query.
    """

    def test_billing_items_are_pushed_oldest_updated_at_first_per_meter(self, migrated_db) -> None:
        captured: list[BillingItem] = []

        def fake_push_kind(*_args, **kwargs):
            captured.extend(kwargs["items"])
            return len(kwargs["items"])

        device_id = make_device(serial="SN0001")
        # Inserted NEWEST-updated-at first, deliberately: a plain SELECT
        # with no ORDER BY returns SQLite rows in insertion (rowid) order,
        # so this is the one insertion order that actually exercises the
        # ORDER BY rather than coincidentally already matching it.
        seed_billing(
            device_id,
            bill_date=datetime(2026, 9, 1, tzinfo=UTC),
            record_status=None,
            total=2.0,
            updated_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
        seed_billing(
            device_id,
            bill_date=datetime(2026, 8, 1, tzinfo=UTC),
            record_status=None,
            total=1.0,
            updated_at=datetime(2026, 8, 1, tzinfo=UTC),
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(centralpush_cycle_module, "push_kind", fake_push_kind)
            centralpush_cycle_module._send_billing(
                "http://example.invalid",
                "token",
                machine_id=TEST_MACHINE_ID,
                sent_at=datetime.now(UTC),
                watermarks={},
                counts=centralpush_cycle_module._Counts(),
                deadline=time.monotonic() + 60,
            )

        assert [item.import_active_kwh_total for item in captured] == [1.0, 2.0], (
            "billing items were not pushed oldest-updated_at first"
        )

    def test_energy_summary_items_are_pushed_oldest_updated_at_first_per_meter(self, migrated_db) -> None:
        captured: list[EnergySummaryItem] = []

        def fake_push_kind(*_args, **kwargs):
            captured.extend(kwargs["items"])
            return len(kwargs["items"])

        device_id = make_device(serial="SN0001")
        seed_energy_summary(
            device_id, local_date=date(2026, 9, 1), total_import_kwh=2.0, updated_at=datetime(2026, 9, 1, tzinfo=UTC)
        )
        seed_energy_summary(
            device_id, local_date=date(2026, 8, 1), total_import_kwh=1.0, updated_at=datetime(2026, 8, 1, tzinfo=UTC)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(centralpush_cycle_module, "push_kind", fake_push_kind)
            centralpush_cycle_module._send_energy_summary(
                "http://example.invalid",
                "token",
                machine_id=TEST_MACHINE_ID,
                sent_at=datetime.now(UTC),
                watermarks={},
                counts=centralpush_cycle_module._Counts(),
                deadline=time.monotonic() + 60,
            )

        assert [item.total_import_kwh for item in captured] == [1.0, 2.0], (
            "Energy Summary items were not pushed oldest-updated_at first"
        )


class TestLoadProfileSafetyMargin:
    def test_the_rewind_subtracts_the_constant(self) -> None:
        threshold = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

        start = _load_profile_start(threshold)

        assert threshold - start == timedelta(seconds=CENTRAL_PUSH_LOAD_PROFILE_REWIND_SEC)
        assert CENTRAL_PUSH_LOAD_PROFILE_REWIND_SEC > 0

    def test_no_threshold_means_send_everything(self) -> None:
        assert _load_profile_start(None) is None

    def test_a_second_cycle_resends_only_the_row_inside_the_rewind_window(
        self, migrated_db, receiver: FakeCentralPushReceiver, license_features
    ) -> None:
        """The end-to-end shape of the rewind (ADR 0024's "a small safety
        margin ... an overlap is harmless") — the same property
        `test_dataout_mysql.py::test_a_steady_state_cycle_re_reads_only_the_rewind_window`
        proves for the Database Destination's own rewind. An older row, well
        outside the margin, must NOT be re-sent; the newest row, which set
        the watermark, always is."""
        device_id = make_device(serial="SN0001")
        seed_load_profile(device_id, read_at=datetime(2026, 8, 1, 0, 0, tzinfo=UTC))
        seed_load_profile(device_id, read_at=datetime(2026, 8, 1, 0, 15, tzinfo=UTC))
        _configure(receiver.url, token=mint_push_token())
        license_features(None)
        central_push_cycle()
        assert len(receiver.load_profile) == 2

        central_push_cycle()

        status = last_cycle()
        assert status is not None
        # Only the newest row (inside the rewind margin) is re-sent — the
        # older one, 900s before it, is well outside CENTRAL_PUSH_LOAD_PROFILE_REWIND_SEC.
        assert status.load_profile_rows == 1
