"""Eager capture on a closed Billing Reading insert (decision 11, SPEC §3.6,
issue #22).

Wired into ``read_and_store_billing`` after the Transport Endpoint lock is
released and after the row commits — never inside the lock, never for the
Open Period. Gated on ``auto_capture`` (PDF) / ``billing_excel_export``
(xlsx alongside it), read through the process-wide LicenseService holder
(``licensing.current``) since this path has no request.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fakes import FakeMeterState

from arichds.acquisition.billing import read_and_store_billing
from arichds.acquisition.drivers.base import BillingReading
from arichds.acquisition.locks import EndpointLocks
from arichds.config import Settings
from arichds.constants import SOURCE_DLMS
from arichds.db.app_settings import CAPTURE_DIR_KEY, set_setting
from arichds.db.session import session_scope
from arichds.licensing.current import set_current_license_service
from arichds.licensing.service import LicenseState

pytestmark = pytest.mark.usefixtures("fake_meter")

NOW = datetime(2026, 8, 7, 6, 0, tzinfo=UTC)
#: Matches `make_device()`'s transport below — the Poller's lock key
#: (`Device.transport_endpoint`) for `{"kind": "net", "host": "127.0.0.1", "port": 4059}`.
ENDPOINT = "127.0.0.1:4059"

ENTRY_CLOSED = BillingReading(
    bill_date=datetime(2026, 7, 31, 17, 0, 0, tzinfo=UTC),
    source=SOURCE_DLMS,
    is_open=False,
    meter_serial="1232002893",
    import_active_kwh_total=198685.030,
)
ENTRY_OPEN = BillingReading(
    bill_date=datetime(2026, 8, 7, 4, 37, 58, tzinfo=UTC),
    source=SOURCE_DLMS,
    is_open=True,
    meter_serial="1232002893",
    import_active_kwh_total=200464.501,
)


class _StubLicenseService:
    """A minimal stand-in satisfying `feature_enabled`'s one call —
    `.current_state()` — without going through a real activation flow."""

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


def make_device() -> int:
    from arichds.db.models import Device

    with session_scope() as session:
        device = Device(
            name="Main Incomer",
            brand="mitsu",
            model="smw110",
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="hunter2",
        )
        session.add(device)
        session.flush()
        return device.id


@pytest.fixture
def device_id(migrated_db: Settings) -> int:
    return make_device()


@pytest.fixture
def capture_dir(tmp_path: Path) -> Path:
    """A directory distinct from `data_dir`'s tree — the `data_dir` fixture
    (through `migrated_db`) also lives under `tmp_path`, and pointing
    `capture_dir` at the same root would make `captured_files()` pick up the
    SQLite file and its WAL/SHM siblings."""
    target = tmp_path / "captures"
    target.mkdir()
    return target


def set_capture_dir(path: Path) -> None:
    with session_scope() as session:
        set_setting(session, CAPTURE_DIR_KEY, str(path))


def captured_files(path: Path) -> list[Path]:
    return sorted(p for p in path.rglob("*") if p.is_file())


class TestBothFeaturesOn:
    def test_pdf_and_xlsx_are_both_written(
        self, device_id: int, fake_meter: FakeMeterState, capture_dir: Path, license_features
    ) -> None:
        license_features(["billing", "auto_capture", "billing_excel_export"])
        set_capture_dir(capture_dir)
        fake_meter.billing_rows = [ENTRY_CLOSED]

        read_and_store_billing(device_id, now=NOW)

        files = captured_files(capture_dir)
        assert any(f.suffix == ".pdf" for f in files)
        assert any(f.suffix == ".xlsx" for f in files)


class TestOnlyAutoCaptureOn:
    def test_only_the_pdf_is_written(
        self, device_id: int, fake_meter: FakeMeterState, capture_dir: Path, license_features
    ) -> None:
        license_features(["billing", "auto_capture"])
        set_capture_dir(capture_dir)
        fake_meter.billing_rows = [ENTRY_CLOSED]

        read_and_store_billing(device_id, now=NOW)

        files = captured_files(capture_dir)
        assert any(f.suffix == ".pdf" for f in files)
        assert not any(f.suffix == ".xlsx" for f in files)


class TestNeitherFeatureOn:
    def test_nothing_is_written(
        self, device_id: int, fake_meter: FakeMeterState, capture_dir: Path, license_features
    ) -> None:
        license_features(["billing"])  # neither auto_capture nor billing_excel_export
        set_capture_dir(capture_dir)
        fake_meter.billing_rows = [ENTRY_CLOSED]

        read_and_store_billing(device_id, now=NOW)

        assert captured_files(capture_dir) == []


class TestOpenPeriodNeverCaptured:
    def test_only_open_row_produces_no_capture(
        self, device_id: int, fake_meter: FakeMeterState, capture_dir: Path, license_features
    ) -> None:
        license_features(["billing", "auto_capture", "billing_excel_export"])
        set_capture_dir(capture_dir)
        fake_meter.billing_rows = [ENTRY_OPEN]

        read_and_store_billing(device_id, now=NOW)

        assert captured_files(capture_dir) == []

    def test_a_mixed_buffer_captures_only_the_closed_row(
        self, device_id: int, fake_meter: FakeMeterState, capture_dir: Path, license_features
    ) -> None:
        license_features(["billing", "auto_capture"])
        set_capture_dir(capture_dir)
        fake_meter.billing_rows = [ENTRY_OPEN, ENTRY_CLOSED]

        read_and_store_billing(device_id, now=NOW)

        files = captured_files(capture_dir)
        assert len(files) == 1
        assert "2026-07-31" in files[0].name  # the closed entry's bill_date, not the open one's


class TestNoCaptureDirConfigured:
    def test_nothing_is_written_and_the_read_still_succeeds(
        self, device_id: int, fake_meter: FakeMeterState, license_features
    ) -> None:
        license_features(["billing", "auto_capture", "billing_excel_export"])
        # capture_dir left at its default ("") — never configured.
        fake_meter.billing_rows = [ENTRY_CLOSED]

        result = read_and_store_billing(device_id, now=NOW)

        assert result.error is None
        assert result.stored == 1


class TestCaptureFailureNeverFailsTheRead:
    def test_a_capture_that_raises_is_logged_and_the_read_still_reports_success(
        self,
        device_id: int,
        fake_meter: FakeMeterState,
        capture_dir: Path,
        license_features,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import arichds.acquisition.billing as billing_module

        license_features(["billing", "auto_capture"])
        set_capture_dir(capture_dir)
        fake_meter.billing_rows = [ENTRY_CLOSED]

        def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("capture blew up")

        monkeypatch.setattr(billing_module, "capture_reading", boom)

        with caplog.at_level("ERROR"):
            result = read_and_store_billing(device_id, now=NOW)

        assert result.error is None
        assert result.stored == 1
        assert any("capture" in record.message.lower() for record in caplog.records)


class TestNoLicenseServicePublished:
    def test_no_service_means_no_capture_and_no_crash(
        self, device_id: int, fake_meter: FakeMeterState, capture_dir: Path
    ) -> None:
        """`licensing.current` starts with nothing published — background code
        run outside the lifespan must treat that as "feature off", never crash."""
        set_capture_dir(capture_dir)
        fake_meter.billing_rows = [ENTRY_CLOSED]

        result = read_and_store_billing(device_id, now=NOW)

        assert result.error is None
        assert captured_files(capture_dir) == []


class TestCaptureRunsOutsideTheEndpointLock:
    def test_the_endpoint_lock_is_free_the_moment_capture_runs(
        self,
        device_id: int,
        fake_meter: FakeMeterState,
        capture_dir: Path,
        license_features,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SPEC §3.6: capture is eager but runs OUTSIDE the Transport Endpoint
        lock — a slow network share must never delay another meter on the
        same line, or make a Manual Read wait behind a capture write.

        Proven by trying to acquire the SAME lock object, for the SAME
        endpoint, from inside the (patched) capture path: `background()`
        only succeeds when nothing else holds the lock. If capture still ran
        *inside* the read's `with registry.get(endpoint).manual(...)` block,
        this acquisition would find the lock held and return `False`.
        """
        import arichds.acquisition.billing as billing_module

        license_features(["billing", "auto_capture"])
        set_capture_dir(capture_dir)
        fake_meter.billing_rows = [ENTRY_CLOSED]

        locks = EndpointLocks()
        acquired_during_capture: list[bool] = []

        def spy_capture_reading(row, device_name, capture_dir_arg, *, write_excel):  # noqa: ANN001
            with locks.get(ENDPOINT).background() as ok:
                acquired_during_capture.append(ok)

        monkeypatch.setattr(billing_module, "capture_reading", spy_capture_reading)

        read_and_store_billing(device_id, locks=locks, now=NOW)

        assert acquired_during_capture == [True]
