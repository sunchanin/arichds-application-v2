"""``export.csv_export`` — the Load Profile CSV auto-export (M7 slice 3,
issue #30).

Everything runs against ``FakeSmw110Driver`` (the only fake that reports
``load_profile_loggers()``, D2); nothing here touches a meter — the exporter
never connects a driver at all, it only asks ``load_profile_loggers()`` to
learn whether a device has a secondary logger (D-12) and reads stored rows
straight out of the database.
"""

from __future__ import annotations

import csv
import io
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fakes import fake_meter_state

from arichds.config import Settings
from arichds.db.app_settings import (
    EXPORT_AUTO_SAVE_ENABLED_KEY,
    EXPORT_CSV_FILENAME_TMPL_KEY,
    EXPORT_DATE_FORMAT_KEY,
    EXPORT_OUTPUT_DIR_KEY,
    set_setting,
)
from arichds.db.models import Device, LoadProfileReading
from arichds.db.session import session_scope
from arichds.export.csv_export import csv_export_cycle, export_device

pytestmark = pytest.mark.usefixtures("fake_meter")

BASE = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def make_device(
    name: str = "Main Incomer",
    *,
    model: str = "smw110",
    port: int = 4059,
    serial: str | None = "SN-1",
    enabled: bool = True,
    status: str = "online",
    transport: dict | None = None,
) -> int:
    with session_scope() as session:
        device = Device(
            name=name,
            brand="mitsu",
            model=model,
            site_name="Plant A",
            transport=transport if transport is not None else {"kind": "net", "host": "127.0.0.1", "port": port},
            password="hunter2",
            enabled=enabled,
            status=status,
            meter_serial=serial,
        )
        session.add(device)
        session.flush()
        return device.id


def seed(device_id: int, read_at: datetime, *, logger_id: int = 1, **columns: float) -> None:
    with session_scope() as session:
        session.add(
            LoadProfileReading(
                device_id=device_id,
                read_at=read_at,
                source="dlms",
                logger_id=logger_id,
                interval_sec=900,
                **columns,
            )
        )


def configure(
    *,
    output_dir: Path,
    auto_save_enabled: bool = True,
    filename_tmpl: str = "[meter].csv",
    date_format: str = "yyyy-mm-dd HH:MM:SS",
) -> None:
    with session_scope() as session:
        set_setting(session, EXPORT_OUTPUT_DIR_KEY, str(output_dir))
        set_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, "true" if auto_save_enabled else "false")
        set_setting(session, EXPORT_CSV_FILENAME_TMPL_KEY, filename_tmpl)
        set_setting(session, EXPORT_DATE_FORMAT_KEY, date_format)


def watermark(device_id: int) -> datetime | None:
    with session_scope() as session:
        device = session.get(Device, device_id)
        assert device is not None
        return device.csv_exported_through.replace(tzinfo=UTC) if device.csv_exported_through else None


def set_watermark(device_id: int, value: datetime) -> None:
    with session_scope() as session:
        session.get(Device, device_id).csv_exported_through = value


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


class TestNoSecondaryLoggerExportsImmediately:
    """F5 branch (a) — a single-logger model never holds."""

    def test_a_single_logger_devices_rows_export_at_once(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(device_id, BASE, import_active_kwh=1.0)
        seed(device_id, BASE + timedelta(minutes=15), import_active_kwh=2.0)

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 2
        assert watermark(device_id) == BASE + timedelta(minutes=15)


class TestSkewCapWithSecondaryLogger:
    """F5, branches (b)-(d) — the four-way skew cap."""

    def test_branch_b_l2_within_window_holds_newer_rows(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1, 2)
        configure(output_dir=tmp_path)
        l1_max = BASE + timedelta(hours=2)
        l2_max = l1_max - timedelta(hours=1)  # within the 24h window
        older = l2_max - timedelta(minutes=15)  # on the L2 side, exports
        seed(device_id, older, import_active_kwh=1.0)
        seed(device_id, l2_max, import_active_kwh=2.0)
        seed(device_id, l1_max, import_active_kwh=3.0)  # newer than l2_max, held
        seed(device_id, l2_max, logger_id=2, volt_l1=1.0)

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 2, "only rows up to min(l1_max, l2_max) should release"
        assert watermark(device_id) == l2_max

    def test_branch_c_l2_stale_beyond_24h_releases_everything(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1, 2)
        configure(output_dir=tmp_path)
        l1_max = BASE + timedelta(hours=30)
        l2_max = BASE + timedelta(hours=5)  # 25h behind l1_max — beyond the cap
        seed(device_id, l1_max, import_active_kwh=1.0)
        seed(device_id, l2_max, logger_id=2, volt_l1=1.0)

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 1
        assert watermark(device_id) == l1_max

    def test_branch_c_boundary_at_exactly_24h_still_holds(self, migrated_db: Settings, tmp_path: Path) -> None:
        """Pins the >= direction: exactly 24h behind is still 'within the window'."""
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1, 2)
        configure(output_dir=tmp_path)
        l1_max = BASE + timedelta(hours=30)
        l2_max = l1_max - timedelta(hours=24)  # exactly on the boundary
        seed(device_id, l1_max, import_active_kwh=1.0)
        seed(device_id, l2_max, logger_id=2, volt_l1=1.0)

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 0, "exactly 24h behind must still be treated as within the window"
        assert watermark(device_id) is None

    def test_branch_d_l2_never_seen_holds_within_24h(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1, 2)
        configure(output_dir=tmp_path)
        l1_max = BASE + timedelta(hours=30)
        older = l1_max - timedelta(hours=25)  # older than l1_max - 24h -> releases
        newer = l1_max - timedelta(hours=1)  # within 24h -> held
        seed(device_id, older, import_active_kwh=1.0)
        seed(device_id, newer, import_active_kwh=2.0)
        seed(device_id, l1_max, import_active_kwh=3.0)

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 1
        assert watermark(device_id) == older

    def test_a_second_run_after_l2_catches_up_releases_the_held_rows(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        """T6(e) — proves the hold is a delay, not a loss."""
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1, 2)
        configure(output_dir=tmp_path)
        l1_max = BASE + timedelta(hours=2)
        seed(device_id, l1_max, import_active_kwh=1.0)
        # No L2 rows at all yet -> branch (d), l1_max - 24h cap -> holds everything.
        first = export_device(device_id, require_auto_save=True)
        assert first.rows_written == 0

        # L2 catches up to l1_max.
        seed(device_id, l1_max, logger_id=2, volt_l1=1.0)
        second = export_device(device_id, require_auto_save=True)

        assert second.rows_written == 1
        assert watermark(device_id) == l1_max


class TestWatermarkIsAStrictLowerBound:
    """T7."""

    def test_a_row_exactly_at_the_watermark_does_not_reexport(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        at_watermark = BASE
        newer = BASE + timedelta(minutes=15)
        seed(device_id, at_watermark, import_active_kwh=1.0)
        set_watermark(device_id, at_watermark)
        seed(device_id, newer, import_active_kwh=2.0)

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 1
        assert watermark(device_id) == newer

    def test_a_run_with_nothing_new_leaves_the_file_byte_identical(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(device_id, BASE, import_active_kwh=1.0)
        export_device(device_id, require_auto_save=True)
        before = (tmp_path / "SN-1.csv").read_bytes()

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 0
        assert (tmp_path / "SN-1.csv").read_bytes() == before


class TestFsyncPrecedesTheWatermark:
    """T5 — the fsync-then-watermark ordering, and a failed write loses nothing."""

    def test_fsync_happens_before_the_watermark_commits(
        self, migrated_db: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(device_id, BASE, import_active_kwh=1.0)

        seen_watermark_during_fsync: list[datetime | None] = []
        real_fsync = os.fsync

        def spy_fsync(fd: int) -> None:
            seen_watermark_during_fsync.append(watermark(device_id))
            real_fsync(fd)

        monkeypatch.setattr(os, "fsync", spy_fsync)

        result = export_device(device_id, require_auto_save=True)

        assert seen_watermark_during_fsync == [None], "the watermark must still be unset while fsync is in flight"
        assert watermark(device_id) == BASE, "the watermark must be advanced after the write returns"
        assert result.rows_written == 1

    def test_a_failed_write_loses_nothing_and_a_second_run_appends_everything_pending(
        self, migrated_db: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure is injected at ``open()`` — before any byte reaches
        disk — the realistic shape of a full-disk/permission failure, and
        the only injection point that lets "none lost, none duplicated" be
        checked unambiguously: failing after some bytes already landed (e.g.
        inside ``fsync`` after ``flush()`` succeeded) is a different,
        narrower case v1's own docstring already accepts as "may duplicate a
        few rows once"."""
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(device_id, BASE, import_active_kwh=1.0)
        seed(device_id, BASE + timedelta(minutes=15), import_active_kwh=2.0)

        def raising_open(*args: object, **kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("arichds.export.csv_export.open", raising_open, raising=False)
        first = export_device(device_id, require_auto_save=True)

        assert first.rows_written == 0
        assert watermark(device_id) is None, "a failed write must not advance the watermark"
        assert not (tmp_path / "SN-1.csv").exists(), "nothing must have reached disk"

        monkeypatch.undo()
        second = export_device(device_id, require_auto_save=True)

        assert second.rows_written == 2, "none of the pending rows may be lost, and none duplicated"
        assert watermark(device_id) == BASE + timedelta(minutes=15)
        rows = list(csv.reader(io.StringIO(read_file(tmp_path / "SN-1.csv"))))
        assert len(rows) == 3, "one header row plus exactly two data rows — no duplicate, no loss"


class TestAppendingUnderAnExistingV1Header:
    """T4."""

    def test_a_pre_existing_v1_header_is_not_rewritten(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        v1_header = (
            "Name,Date/Time,Import kWh Active,Import kWh Reactive,Export kWh Active,Export kWh Re,"
            "Avg Geo PF,Voltage L1 (V),Voltage L2 (V),Voltage L3 (V),Current L1 (A),Current L2 (A),"
            "Current L3 (A),Frequency (Hz)\n"
        )
        v1_row = "Old Row (SN-1),2026-01-01 00:00:00," + ",".join(["0"] * 12) + "\n"
        target = tmp_path / "SN-1.csv"
        target.write_bytes(("﻿" + v1_header + v1_row).encode("utf-8"))

        seed(device_id, BASE, import_reactive_kvarh=99.0)
        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 1
        lines = read_file(target).splitlines()
        assert lines[0] == v1_header.strip()
        assert len(lines) == 3, "no second header line was written"
        appended_cells = lines[2].split(",")
        assert appended_cells[3] == format(99.0, ".9f")


class TestNeverFollowsTheDisplayUnitSetting:
    """T2 — ADR 0013/D-1. The headline rule: this file is a contract, not a view."""

    def test_flipping_kw_w_changes_no_byte(self, migrated_db: Settings, tmp_path: Path) -> None:
        from arichds.db.app_settings import DISPLAY_UNIT_SCALE_KEY
        from arichds.db.app_settings import set_setting as _set_setting

        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        # Non-zero, mutually distinct values — a x1000 scale is a no-op on 0
        # or None, which would make this test pass vacuously either way.
        seed(
            device_id,
            BASE,
            import_active_kwh=1234.5,
            import_reactive_kvarh=2345.6,
            export_active_kwh=3456.7,
            export_reactive_kvarh=4567.8,
        )

        export_device(device_id, require_auto_save=True)
        at_kilo = (tmp_path / "SN-1.csv").read_bytes()
        (tmp_path / "SN-1.csv").unlink()
        with session_scope() as session:
            _set_setting(session, DISPLAY_UNIT_SCALE_KEY, "base")
        set_watermark(device_id, BASE - timedelta(seconds=1))

        export_device(device_id, require_auto_save=True)
        at_base = (tmp_path / "SN-1.csv").read_bytes()

        assert at_kilo == at_base, "the display-unit scale must never change a single byte of the CSV"

    def test_no_export_source_file_mentions_the_display_unit_machinery(self) -> None:
        forbidden = ("display_unit_scale", "DISPLAY_UNIT_SCALE_KEY", "scale_value", "_render_shared")
        export_dir = Path(__file__).resolve().parents[1] / "src" / "arichds" / "export"
        offenders = []
        for path in export_dir.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for term in forbidden:
                if term in text:
                    offenders.append((path.name, term))
        assert offenders == []


class TestOutputParityWholeFile:
    """T9 — byte for byte, BOM + header + rows, with a None column and a
    midnight-crossing timestamp."""

    def test_the_whole_file_matches_the_expected_bytes(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device(name="Main Incomer", serial="1232002893")
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        # UTC 18:30 -> ICT 01:30 the next day.
        read_at = datetime(2026, 8, 1, 18, 30, 0, tzinfo=UTC)
        seed(
            device_id,
            read_at,
            import_active_kwh=1234.5,
            import_reactive_kvarh=None,
            export_active_kwh=10.123456789,
            export_reactive_kvarh=0.0,
            avg_geo_pf=0.987,
            volt_l1=230.123,
            volt_l2=229.5,
            volt_l3=231.2,
            current_l1=5.111,
            current_l2=5.222,
            current_l3=5.333,
            freq=50.01,
        )

        result = export_device(device_id, require_auto_save=True)
        assert result.rows_written == 1

        expected_header = (
            "Name,Date/Time,Import Active (kWh),Import Reactive (kvarh),Export Active (kWh),"
            "Export Reactive (kvarh),Avg Geo PF,Voltage L1 (V),Voltage L2 (V),Voltage L3 (V),"
            "Current L1 (A),Current L2 (A),Current L3 (A),Frequency (Hz)\n"
        )
        expected_row = (
            "Main Incomer (1232002893),2026-08-02 01:30:00,"
            + format(1234.5, ".9f")
            + ","
            + ""
            + ","
            + format(10.123456789, ".9f")
            + ","
            + format(0.0, ".9f")
            + ","
            + format(0.987, ".3f")
            + ","
            + format(230.123, ".3f")
            + ","
            + format(229.5, ".3f")
            + ","
            + format(231.2, ".3f")
            + ","
            + format(5.111, ".3f")
            + ","
            + format(5.222, ".3f")
            + ","
            + format(5.333, ".3f")
            + ","
            + format(50.01, ".3f")
            + "\n"
        )
        expected_bytes = ("﻿" + expected_header + expected_row).encode("utf-8")
        assert (tmp_path / "1232002893.csv").read_bytes() == expected_bytes


class TestTheTwoGates:
    """T10 — D-11: the job obeys export_auto_save_enabled, "Save CSV now" ignores it."""

    def test_the_job_writes_nothing_when_auto_save_is_off(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path, auto_save_enabled=False)
        seed(device_id, BASE, import_active_kwh=1.0)

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 0
        assert watermark(device_id) is None

    def test_save_now_writes_even_when_auto_save_is_off(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path, auto_save_enabled=False)
        seed(device_id, BASE, import_active_kwh=1.0)

        result = export_device(device_id, require_auto_save=False)

        assert result.rows_written == 1

    def test_the_job_no_ops_silently_when_output_dir_is_empty(self, migrated_db: Settings) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        with session_scope() as session:
            set_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, "true")
            set_setting(session, EXPORT_OUTPUT_DIR_KEY, "")
        seed(device_id, BASE, import_active_kwh=1.0)

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 0
        assert result.path is None


class TestAnUnbuildableDriverSkipsOneDevice:
    """T12."""

    def test_the_broken_device_is_skipped_and_the_healthy_one_still_exports(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        broken_id = make_device("Broken", transport={"kind": "net"})  # no host/port -> unusable
        healthy_id = make_device("Healthy", port=4059, serial="SN-2")
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(broken_id, BASE, import_active_kwh=1.0)
        seed(healthy_id, BASE, import_active_kwh=2.0)

        for device_id in (broken_id, healthy_id):
            export_device(device_id, require_auto_save=True)

        assert watermark(broken_id) is None
        assert watermark(healthy_id) == BASE
        assert not (tmp_path / "SN-1.csv").exists()
        assert (tmp_path / "SN-2.csv").exists()

    def test_the_cycle_itself_does_not_stop_at_the_broken_device(self, migrated_db: Settings, tmp_path: Path) -> None:
        broken_id = make_device("Broken", port=4059, transport={"kind": "net"})
        healthy_id = make_device("Healthy", port=4060, serial="SN-2")
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(broken_id, BASE, import_active_kwh=1.0)
        seed(healthy_id, BASE, import_active_kwh=2.0)

        csv_export_cycle()

        assert watermark(broken_id) is None
        assert watermark(healthy_id) == BASE


class TestCycleDeviceFilters:
    """Reviewer finding 2 — only ``enabled`` gates the cycle; ``status`` does
    not. A single-device test cannot prove either half (a blanket early
    return would pass it vacuously), so each test below pairs the device
    under test with a second device that must behave the opposite way."""

    def test_a_paused_device_is_skipped_while_an_active_one_still_exports(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        paused_id = make_device("Paused", port=4059, enabled=False, serial="SN-PAUSED")
        active_id = make_device("Active", port=4060, serial="SN-ACTIVE")
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(paused_id, BASE, import_active_kwh=1.0)
        seed(active_id, BASE, import_active_kwh=2.0)

        csv_export_cycle()

        assert watermark(paused_id) is None, "CONTEXT.md — Pause stops every background read of a device"
        assert watermark(active_id) == BASE

    def test_an_offline_but_enabled_device_still_exports_its_stored_rows(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        """The rows are already on disk in the database; this job never
        talks to the meter, so an Offline status buys it nothing — unlike
        `load_profile_cycle`, which skips Offline to avoid a wasted read
        timeout. Paired with a second, Online device so a blanket early
        return on the whole query can't pass this vacuously."""
        offline_id = make_device("Offline meter", port=4059, status="offline", serial="SN-OFFLINE")
        online_id = make_device("Online meter", port=4060, status="online", serial="SN-ONLINE")
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(offline_id, BASE, import_active_kwh=1.0)
        seed(online_id, BASE, import_active_kwh=2.0)

        csv_export_cycle()

        assert watermark(offline_id) == BASE, "an Offline device's already-stored rows must still export"
        assert watermark(online_id) == BASE


class TestTheSerialHold:
    """D-15/T8."""

    def test_a_device_with_no_serial_exports_nothing_and_moves_no_watermark(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        device_id = make_device(serial=None)
        fake_meter_state().load_profile_loggers = (1,)
        output_dir = tmp_path / "csv"
        configure(output_dir=output_dir)
        seed(device_id, BASE, import_active_kwh=1.0)

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 0
        assert watermark(device_id) is None
        assert not output_dir.exists(), "no file, no directory — nothing was written at all"


class TestPerDeviceLock:
    """T13 — the lock serialises one device and never blocks another."""

    def test_a_second_export_of_the_same_device_waits_for_the_first(
        self, migrated_db: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Counts how many threads are *inside* the patched write at once.

        A blocking write alone does not discriminate: without the lock a
        second thread still parks inside ``slow_append`` (waiting on the
        same ``release`` event) rather than raising or returning, so
        ``t2.is_alive()`` and an elapsed-time floor are both true whether or
        not the per-device lock exists — that was reviewer finding 1. The
        entry count is the one observable that actually differs: **with**
        the lock, thread 2 cannot even reach ``_append_rows`` until thread 1
        releases it, so the concurrent-entry count never exceeds 1; **without**
        it, thread 2 races in immediately and both are inside at once.
        """
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(device_id, BASE, import_active_kwh=1.0)

        entered = threading.Event()
        release = threading.Event()
        entries_guard = threading.Lock()
        concurrent_entries = 0
        max_concurrent_entries = 0
        real_append = __import__("arichds.export.csv_export", fromlist=["_append_rows"])._append_rows

        def slow_append(final_path, rows, allowlist, device_id_):  # noqa: ANN001
            nonlocal concurrent_entries, max_concurrent_entries
            with entries_guard:
                concurrent_entries += 1
                max_concurrent_entries = max(max_concurrent_entries, concurrent_entries)
            entered.set()
            release.wait(timeout=10)
            with entries_guard:
                concurrent_entries -= 1
            return real_append(final_path, rows, allowlist, device_id_)

        monkeypatch.setattr("arichds.export.csv_export._append_rows", slow_append)

        def run_first() -> None:
            export_device(device_id, require_auto_save=True)

        t = threading.Thread(target=run_first)
        t.start()
        assert entered.wait(timeout=5)

        def run_second() -> None:
            export_device(device_id, require_auto_save=True)

        t2 = threading.Thread(target=run_second)
        t2.start()
        # Give an unlocked implementation every chance to race in — this is
        # not a timing assertion (see the docstring above), it only bounds
        # how long we wait before checking the entry count.
        time.sleep(0.3)

        with entries_guard:
            observed = max_concurrent_entries
        assert observed == 1, (
            f"{observed} threads were inside the write at once — a second export of the same "
            "device entered before the first released the per-device lock"
        )

        release.set()
        t.join(timeout=5)
        t2.join(timeout=5)

    def test_exporting_a_different_device_is_not_blocked(
        self, migrated_db: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        device_a = make_device("A", port=4059, serial="SN-A")
        device_b = make_device("B", port=4060, serial="SN-B")
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(device_a, BASE, import_active_kwh=1.0)
        seed(device_b, BASE, import_active_kwh=2.0)

        held = threading.Event()
        release = threading.Event()
        from arichds.export import csv_export as csv_export_module

        real_lock = csv_export_module._device_lock(device_a)
        real_lock.acquire()
        held.set()

        try:
            started = time.monotonic()
            result = export_device(device_b, require_auto_save=True)
            elapsed = time.monotonic() - started
        finally:
            real_lock.release()
            release.set()

        assert result.rows_written == 1
        assert elapsed < 1.0, "device B's export must not wait on device A's lock"
