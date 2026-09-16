"""The File Upload Destination cycle (ADR 0025, spec.md "The cycle sends
what the Upload Manifest lacks", ticket 02).

Driven against :class:`InMemoryTransport` — the same "cycle tested once,
against an in-memory transport" ADR 0025 decision 5 asks for, and the same
"assert only on what the fake holds" discipline
``test_central_push_cycle.py`` uses against its own fake.
"""

from __future__ import annotations

import logging
import pathlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from arichds.db.app_settings import (
    CAPTURE_DIR_KEY,
    EXPORT_BILLING_FILENAME_TMPL_DEFAULT,
    EXPORT_BILLING_FILENAME_TMPL_KEY,
    EXPORT_CSV_FILENAME_TMPL_DEFAULT,
    EXPORT_CSV_FILENAME_TMPL_KEY,
    EXPORT_ENERGY_FILENAME_TMPL_DEFAULT,
    EXPORT_ENERGY_FILENAME_TMPL_KEY,
    EXPORT_OUTPUT_DIR_KEY,
    FILEUPLOAD_ACTIVE_PROTOCOL_KEY,
    FILEUPLOAD_SFTP_HOST_KEY,
    set_setting,
)
from arichds.db.models import Device
from arichds.db.session import session_scope
from arichds.export.format import render_filename
from arichds.fileupload import cycle as cycle_module
from arichds.fileupload.cycle import file_upload_cycle
from arichds.fileupload.manifest import Manifest, ManifestEntry
from arichds.fileupload.status import last_cycle, set_last_cycle
from arichds.fileupload.transport import TransportError
from arichds.licensing.current import set_current_license_service
from arichds.licensing.service import LicenseState

TEST_MACHINE_ID = "f" * 64


class _StubLicenseService:
    """The same minimal stand-in ``test_dataout_sync.py``/``test_central_push_cycle.py``
    use for the background-path licence gate, plus ``.machine_id`` — the
    cycle needs it for the manifest's informational field."""

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


def _configure_sftp(*, host: str = "sftp.example.com") -> None:
    with session_scope() as session:
        set_setting(session, FILEUPLOAD_ACTIVE_PROTOCOL_KEY, "sftp")
        set_setting(session, FILEUPLOAD_SFTP_HOST_KEY, host)


def _configure_dirs(*, export_dir: Path | None, capture_dir: Path | None) -> None:
    with session_scope() as session:
        set_setting(session, EXPORT_OUTPUT_DIR_KEY, str(export_dir) if export_dir is not None else "")
        set_setting(session, CAPTURE_DIR_KEY, str(capture_dir) if capture_dir is not None else "")


class InMemoryTransport:
    """A test-only :class:`~arichds.fileupload.transport.Transport` — records
    every put and serves whatever manifest it is given, exactly the seam
    the real transports (tickets 03-05) will fill in for real.

    Args:
        manifest: What :meth:`read_manifest` answers — ``None`` means "no
            manifest yet" (a fresh remote root).
        fail_read_manifest: Raise :class:`TransportError` from
            :meth:`read_manifest` instead of answering *manifest*.
        fail_on_put: Relative paths that raise :class:`TransportError` from
            :meth:`put_file` — everything else succeeds.
        fail_write_manifest: Raise :class:`TransportError` from
            :meth:`write_manifest` instead of recording it.
    """

    def __init__(
        self,
        *,
        manifest: Manifest | None = None,
        fail_read_manifest: bool = False,
        fail_on_put: frozenset[str] = frozenset(),
        fail_write_manifest: bool = False,
    ) -> None:
        self.manifest = manifest
        self.fail_read_manifest = fail_read_manifest
        self.fail_on_put = fail_on_put
        self.fail_write_manifest = fail_write_manifest
        self.puts: dict[str, bytes] = {}
        self.written_manifest: Manifest | None = None

    def read_manifest(self) -> Manifest | None:
        if self.fail_read_manifest:
            raise TransportError("BoomOnRead")
        return self.manifest

    def put_file(self, relative_path: str, local_path: Path) -> None:
        if relative_path in self.fail_on_put:
            raise TransportError("BoomOnPut")
        self.puts[relative_path] = local_path.read_bytes()

    def write_manifest(self, manifest: Manifest) -> None:
        if self.fail_write_manifest:
            raise TransportError("BoomOnWrite")
        self.written_manifest = manifest

    def describe(self) -> str:
        return "in-memory"


class _NeverCalledTransport:
    """A transport that fails the test the moment anything calls it — proves
    a "not configured" cycle makes no attempt at all."""

    def read_manifest(self):  # noqa: ANN201
        raise AssertionError("the cycle talked to a transport it should never have built")

    def put_file(self, *_a, **_k):  # noqa: ANN201
        raise AssertionError("the cycle talked to a transport it should never have built")

    def write_manifest(self, *_a, **_k):  # noqa: ANN201
        raise AssertionError("the cycle talked to a transport it should never have built")

    def describe(self) -> str:
        raise AssertionError("the cycle talked to a transport it should never have built")


def _write_export_files(export_dir: Path, serial: str) -> dict[str, Path]:
    """The three export files a device with *serial* would have on disk,
    named through the **real** production naming function
    (``arichds.export.format.render_filename``) with the product's own
    default templates — never a hardcoded literal. This is deliberate
    (reviewer finding, ticket 02 round 1, problem 1): the whole point of the
    fix is that the cycle recognises whatever `render_filename` actually
    produces, so the fixture must go through the same function a mutation
    to it can reach."""
    export_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    for template in (
        EXPORT_CSV_FILENAME_TMPL_DEFAULT,
        EXPORT_BILLING_FILENAME_TMPL_DEFAULT,
        EXPORT_ENERGY_FILENAME_TMPL_DEFAULT,
    ):
        filename = render_filename(template, serial)
        relative = f"export/{filename}"
        path = export_dir / filename
        path.write_text(f"content for {relative}", encoding="utf-8")
        files[relative] = path
    return files


def _write_capture_file(capture_dir: Path, serial: str, name: str = "2026-09-01.pdf") -> str:
    device_dir = capture_dir / serial
    device_dir.mkdir(parents=True, exist_ok=True)
    (device_dir / name).write_bytes(b"%PDF-fake-capture-bytes")
    return f"captures/{serial}/{name}"


class TestImportBoundary:
    def test_cycle_does_not_import_from_export_or_capture(self) -> None:
        """ADR 0021's reasoning for ``dataout/`` applies here too (module
        docstring, spec.md "Module") — a shared helper would make a future
        change to one silently change the other. Mirrors
        ``test_dataout_sync.py::TestItDoesNotShareTheExportHelper``."""
        source = pathlib.Path(cycle_module.__file__).read_text(encoding="utf-8")

        assert "arichds.export" not in source
        assert "from arichds.capture" not in source


class TestNotConfigured:
    """The criterion is "the cycle does nothing **and reports** that it was
    not configured" — a status is published even though no transport is
    ever touched (reviewer finding, ticket 02 round 1, problem 3)."""

    def test_an_unset_active_protocol_makes_no_attempt_and_reports_not_configured(
        self, migrated_db, license_features
    ) -> None:
        license_features(["file_upload_destination"])

        file_upload_cycle(transport=_NeverCalledTransport())

        status = last_cycle()
        assert status is not None
        assert status.outcome == "not_configured"
        assert status.protocol == ""
        assert status.files_sent == 0

    def test_an_active_protocol_with_no_host_makes_no_attempt_and_reports_not_configured(
        self, migrated_db, license_features
    ) -> None:
        license_features(["file_upload_destination"])
        with session_scope() as session:
            set_setting(session, FILEUPLOAD_ACTIVE_PROTOCOL_KEY, "sftp")
            set_setting(session, FILEUPLOAD_SFTP_HOST_KEY, "")

        file_upload_cycle(transport=_NeverCalledTransport())

        status = last_cycle()
        assert status is not None
        assert status.outcome == "not_configured"
        assert status.protocol == "sftp"

    def test_without_the_feature_the_cycle_does_nothing(self, migrated_db, license_features) -> None:
        """Never reaches the "not configured" judgment at all — the licence
        gate returns first, the same as `centralpush_cycle`'s own gate, so
        no status is published either way."""
        license_features(["billing"])
        _configure_sftp()

        file_upload_cycle(transport=_NeverCalledTransport())

        assert last_cycle() is None


class TestFirstCycleSendsEverything:
    def test_it_sends_every_candidate_and_names_every_file_in_the_manifest(
        self, migrated_db, license_features, tmp_path: pathlib.Path
    ) -> None:
        license_features(["file_upload_destination"])
        _configure_sftp()
        export_dir = tmp_path / "export"
        capture_dir = tmp_path / "captures"
        _configure_dirs(export_dir=export_dir, capture_dir=capture_dir)
        make_device(serial="SN0001")
        export_files = _write_export_files(export_dir, "SN0001")
        capture_rel = _write_capture_file(capture_dir, "SN0001")
        transport = InMemoryTransport(manifest=None)

        file_upload_cycle(transport=transport)

        expected = set(export_files) | {capture_rel}
        assert set(transport.puts) == expected
        assert transport.written_manifest is not None
        assert set(transport.written_manifest.files) == expected

        status = last_cycle()
        assert status is not None
        assert status.outcome == "success"
        assert status.files_sent == len(expected)
        assert status.files_skipped_unchanged == 0


class TestExportFolderIsListedNotPredicted:
    """Reviewer finding, round 1, problem 1 — the export group is found by
    **listing** `export_dir` and matching against the three templates,
    never by predicting a filename and hoping it exists."""

    def test_export_writers_own_temp_file_is_never_a_candidate(
        self, migrated_db, license_features, tmp_path: pathlib.Path
    ) -> None:
        license_features(["file_upload_destination"])
        _configure_sftp()
        export_dir = tmp_path / "export"
        _configure_dirs(export_dir=export_dir, capture_dir=None)
        make_device(serial="SN0001")
        _write_export_files(export_dir, "SN0001")
        # `export/writer.py:249`'s own atomic-replace temp file shape:
        # `tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.",
        # suffix=".tmp")`.
        (export_dir / ".SN0001.ab12cd.tmp").write_text("mid-write, never a candidate", encoding="utf-8")

        transport = InMemoryTransport(manifest=None)
        file_upload_cycle(transport=transport)

        assert all(not relative.endswith(".tmp") for relative in transport.puts)
        assert transport.written_manifest is not None
        assert all(not relative.endswith(".tmp") for relative in transport.written_manifest.files)

    def test_an_earlier_days_dated_file_is_still_found(
        self, migrated_db, license_features, tmp_path: pathlib.Path
    ) -> None:
        """The exact harm the ticket named: `ExportFormat.tsx` offers a
        `[date]` token, and a name predicted for "today" alone made every
        earlier day's file permanently invisible to the cycle."""
        license_features(["file_upload_destination"])
        _configure_sftp()
        export_dir = tmp_path / "export"
        _configure_dirs(export_dir=export_dir, capture_dir=None)
        with session_scope() as session:
            set_setting(session, EXPORT_CSV_FILENAME_TMPL_KEY, "[meter]-[date].csv")
        make_device(serial="SN0001")
        export_dir.mkdir(parents=True, exist_ok=True)
        today_name = f"SN0001-{date.today().isoformat()}.csv"
        (export_dir / "SN0001-2026-01-01.csv").write_text("an earlier day's export", encoding="utf-8")
        (export_dir / today_name).write_text("today's export", encoding="utf-8")

        transport = InMemoryTransport(manifest=None)
        file_upload_cycle(transport=transport)

        assert "export/SN0001-2026-01-01.csv" in transport.puts
        assert f"export/{today_name}" in transport.puts

    def test_a_file_matched_by_two_colliding_templates_is_sent_only_once(
        self, migrated_db, license_features, tmp_path: pathlib.Path
    ) -> None:
        """Reviewer finding, round 2 — belt and braces: two templates can
        only collide on one file if neither carries `[meter]`/`[serial]`,
        which already breaks the export writer itself, but the cycle must
        still not digest/send/count that file twice."""
        license_features(["file_upload_destination"])
        _configure_sftp()
        export_dir = tmp_path / "export"
        _configure_dirs(export_dir=export_dir, capture_dir=None)
        with session_scope() as session:
            set_setting(session, EXPORT_BILLING_FILENAME_TMPL_KEY, "shared.csv")
            set_setting(session, EXPORT_ENERGY_FILENAME_TMPL_KEY, "shared.csv")
        make_device(serial="SN0001")
        export_dir.mkdir(parents=True, exist_ok=True)
        (export_dir / "shared.csv").write_text("one file, two colliding templates", encoding="utf-8")

        transport = InMemoryTransport(manifest=None)
        file_upload_cycle(transport=transport)

        assert transport.puts.keys() == {"export/shared.csv"}
        status = last_cycle()
        assert status is not None
        assert status.files_sent == 1


class TestSecondCycleWithNoChanges:
    def test_it_sends_nothing(self, migrated_db, license_features, tmp_path: pathlib.Path) -> None:
        license_features(["file_upload_destination"])
        _configure_sftp()
        export_dir = tmp_path / "export"
        capture_dir = tmp_path / "captures"
        _configure_dirs(export_dir=export_dir, capture_dir=capture_dir)
        make_device(serial="SN0001")
        _write_export_files(export_dir, "SN0001")
        _write_capture_file(capture_dir, "SN0001")

        first = InMemoryTransport(manifest=None)
        file_upload_cycle(transport=first)

        second = InMemoryTransport(manifest=first.written_manifest)
        file_upload_cycle(transport=second)

        assert second.puts == {}
        status = last_cycle()
        assert status is not None
        assert status.outcome == "success"
        assert status.files_sent == 0
        assert status.files_skipped_unchanged == 4  # 3 export + 1 capture
        # The write itself is skipped too (reviewer finding, ticket 02
        # round 1, problem 6): the read succeeded and nothing was sent, so
        # `write_manifest` is never called — writing would have reproduced
        # exactly what `first` already holds.
        assert second.written_manifest is None

    # Mutation-probed by hand during implementation, not encoded here as a
    # permanent monkeypatch (the compare lives inline in `_run_cycle`, and a
    # runtime patch of `ManifestEntry.sha256` fights the frozen dataclass's
    # own slot descriptor more than it proves anything): temporarily
    # removing the `existing.sha256 == digest` short-circuit in
    # `_run_cycle` and rerunning `test_it_sends_nothing` above turns it red
    # (the second cycle resends all four files instead of zero) — see the
    # implementation report.


class TestManifestWriteSkip:
    """Problem 6, reviewer round 1 — the write itself is skipped only when
    the read succeeded intact (``manifest_was_read``) and nothing was sent;
    a fresh or unreadable root still gets one."""

    def test_a_fresh_root_still_gets_a_write_even_with_nothing_to_send(
        self, migrated_db, license_features, tmp_path: pathlib.Path
    ) -> None:
        license_features(["file_upload_destination"])
        _configure_sftp()
        # No export dir, no capture dir configured — zero candidates.
        _configure_dirs(export_dir=None, capture_dir=None)

        transport = InMemoryTransport(manifest=None)  # a fresh root
        file_upload_cycle(transport=transport)

        assert transport.written_manifest is not None
        assert transport.written_manifest.files == {}

    def test_an_unreadable_root_still_gets_a_write_even_with_nothing_to_send(
        self, migrated_db, license_features, tmp_path: pathlib.Path
    ) -> None:
        license_features(["file_upload_destination"])
        _configure_sftp()
        _configure_dirs(export_dir=None, capture_dir=None)

        transport = InMemoryTransport(manifest=None, fail_read_manifest=True)
        file_upload_cycle(transport=transport)

        assert transport.written_manifest is not None
        assert transport.written_manifest.files == {}


class TestAChangedFile:
    def test_it_is_resent_and_its_digest_updated(self, migrated_db, license_features, tmp_path: pathlib.Path) -> None:
        license_features(["file_upload_destination"])
        _configure_sftp()
        export_dir = tmp_path / "export"
        _configure_dirs(export_dir=export_dir, capture_dir=None)
        make_device(serial="SN0001")
        export_files = _write_export_files(export_dir, "SN0001")

        first = InMemoryTransport(manifest=None)
        file_upload_cycle(transport=first)

        energy_path = "export/SN0001-energy.csv"
        export_files[energy_path].write_text("changed content", encoding="utf-8")

        second = InMemoryTransport(manifest=first.written_manifest)
        file_upload_cycle(transport=second)

        assert set(second.puts) == {energy_path}
        old_digest = first.written_manifest.files[energy_path].sha256
        new_digest = second.written_manifest.files[energy_path].sha256
        assert new_digest != old_digest
        # The other two entries carry forward untouched.
        for path in ("export/SN0001.csv", "export/SN0001-billing.csv"):
            assert second.written_manifest.files[path].sha256 == first.written_manifest.files[path].sha256


class TestBudget:
    def test_near_zero_sends_at_most_one_file_and_the_manifest_names_exactly_that(
        self, migrated_db, license_features, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        license_features(["file_upload_destination"])
        _configure_sftp()
        export_dir = tmp_path / "export"
        _configure_dirs(export_dir=export_dir, capture_dir=None)
        make_device(serial="SN0001")
        _write_export_files(export_dir, "SN0001")  # 3 candidates

        calls = {"n": 0}

        def _budget_exhausted_after_first(_deadline: float) -> bool:
            calls["n"] += 1
            return calls["n"] > 1

        monkeypatch.setattr(cycle_module, "_out_of_budget", _budget_exhausted_after_first)

        transport = InMemoryTransport(manifest=None)
        file_upload_cycle(transport=transport)

        assert len(transport.puts) <= 1
        assert set(transport.written_manifest.files) == set(transport.puts)

        status = last_cycle()
        assert status is not None
        assert status.files_skipped_budget >= 2

    # Mutation-probed by hand during implementation: temporarily changing
    # `_run_cycle`'s manifest merge from `{**manifest.files, **sent_entries}`
    # to a full rebuild off `candidates` (every file the export scan found,
    # not only what was sent) and rerunning
    # `test_near_zero_sends_at_most_one_file_and_the_manifest_names_exactly_that`
    # above turns it red — the manifest then names all 3 candidates after
    # sending at most 1 — see the implementation report.


class TestTransportErrorMidCycle:
    def test_it_ends_skipped_and_the_manifest_still_names_what_arrived(
        self, migrated_db, license_features, tmp_path: pathlib.Path
    ) -> None:
        license_features(["file_upload_destination"])
        _configure_sftp()
        export_dir = tmp_path / "export"
        _configure_dirs(export_dir=export_dir, capture_dir=None)
        make_device(serial="SN0001")
        _write_export_files(export_dir, "SN0001")

        # Candidate order for one device is csv, billing, energy — fail on
        # the second so the first is already accepted before the failure.
        transport = InMemoryTransport(manifest=None, fail_on_put=frozenset({"export/SN0001-billing.csv"}))

        file_upload_cycle(transport=transport)

        status = last_cycle()
        assert status is not None
        assert status.outcome == "skipped"
        assert status.error == "TransportError"
        assert set(transport.puts) == {"export/SN0001.csv"}
        assert transport.written_manifest is not None
        assert set(transport.written_manifest.files) == {"export/SN0001.csv"}


class TestStaleManifestEntrySurvives:
    def test_a_file_gone_locally_keeps_its_manifest_entry(
        self, migrated_db, license_features, tmp_path: pathlib.Path
    ) -> None:
        license_features(["file_upload_destination"])
        _configure_sftp()
        export_dir = tmp_path / "export"
        _configure_dirs(export_dir=export_dir, capture_dir=None)
        make_device(serial="SN0001")
        _write_export_files(export_dir, "SN0001")

        stale_entry = ManifestEntry(sha256="deadbeef", size=1, uploaded_at=datetime.now(UTC) - timedelta(days=30))
        manifest = Manifest(version=1, machine_id=TEST_MACHINE_ID, files={"export/GONE-billing.csv": stale_entry})
        transport = InMemoryTransport(manifest=manifest)

        file_upload_cycle(transport=transport)

        assert transport.written_manifest is not None
        assert transport.written_manifest.files["export/GONE-billing.csv"] == stale_entry


class TestDeviceWithoutMeterSerial:
    def test_it_is_skipped_and_counted(self, migrated_db, license_features, tmp_path: pathlib.Path) -> None:
        license_features(["file_upload_destination"])
        _configure_sftp()
        export_dir = tmp_path / "export"
        _configure_dirs(export_dir=export_dir, capture_dir=None)
        make_device(name="No serial yet", serial=None)
        make_device(name="Meter B", serial="SN0002")
        _write_export_files(export_dir, "SN0002")

        transport = InMemoryTransport(manifest=None)
        file_upload_cycle(transport=transport)

        assert len(transport.puts) == 3  # only SN0002's three files
        status = last_cycle()
        assert status is not None
        assert status.files_skipped_no_serial == 1


class TestUnreadableManifest:
    def test_it_falls_back_to_send_everything(self, migrated_db, license_features, tmp_path: pathlib.Path) -> None:
        license_features(["file_upload_destination"])
        _configure_sftp()
        export_dir = tmp_path / "export"
        _configure_dirs(export_dir=export_dir, capture_dir=None)
        make_device(serial="SN0001")
        _write_export_files(export_dir, "SN0001")

        transport = InMemoryTransport(manifest=None, fail_read_manifest=True)
        file_upload_cycle(transport=transport)

        status = last_cycle()
        assert status is not None
        assert status.outcome == "success"
        assert status.files_sent == 3


class TestLogging:
    def test_one_info_line_per_cycle_with_counts(
        self, migrated_db, license_features, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        license_features(["file_upload_destination"])
        _configure_sftp()
        export_dir = tmp_path / "export"
        _configure_dirs(export_dir=export_dir, capture_dir=None)
        make_device(serial="SN0001")
        _write_export_files(export_dir, "SN0001")

        with caplog.at_level(logging.INFO, logger="arichds.fileupload.cycle"):
            file_upload_cycle(transport=InMemoryTransport(manifest=None))

        info_lines = [
            r for r in caplog.records if r.levelno == logging.INFO and "File Upload Destination cycle" in r.getMessage()
        ]
        assert len(info_lines) == 1

    def test_a_secret_never_reaches_the_status_or_the_log(
        self, migrated_db, license_features, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A review of ticket 01 named the hazard: the redaction filter only
        catches text shaped like `password=`/`token=`/`passphrase=`. The
        cycle's own exception handling never touches an exception's message
        at all — only its class name — so a secret embedded any other way
        in a transport failure still cannot reach the log or the status."""
        license_features(["file_upload_destination"])
        _configure_sftp()
        export_dir = tmp_path / "export"
        _configure_dirs(export_dir=export_dir, capture_dir=None)
        make_device(serial="SN0001")
        _write_export_files(export_dir, "SN0001")

        secret = "hunter2-the-sftp-password"

        class _LeakyTransport(InMemoryTransport):
            def put_file(self, relative_path: str, local_path: Path) -> None:
                raise RuntimeError(f"connection dropped while authenticating with {secret}")

        with caplog.at_level(logging.INFO, logger="arichds.fileupload.cycle"):
            file_upload_cycle(transport=_LeakyTransport(manifest=None))

        status = last_cycle()
        assert status is not None
        assert status.outcome == "skipped"
        assert status.error == "RuntimeError"
        assert secret not in (status.error or "")
        for record in caplog.records:
            assert secret not in record.getMessage()
            assert secret not in str(record.exc_info or "")
