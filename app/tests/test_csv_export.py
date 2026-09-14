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
from arichds.db.retention import purge_expired
from arichds.db.session import session_scope
from arichds.export.csv_export import csv_export_cycle, csv_trim_cycle, export_device, trim_device_load_profile_csv
from arichds.export.format import _EXPORT_HEADERS

pytestmark = pytest.mark.usefixtures("fake_meter")

BASE = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)

#: Spelled out because a literal newline inside a source string is easy to
#: lose to an editing tool.
#: A status word with **two bits set and bit 0 clear** — DISTURBED (0x0010)
#: and POWER_LOSS (0x0800). It has to avoid bit 0 deliberately: since
#: `/scrutinize` (2026-09-11) a row whose word carries ALL_INVALID is excluded
#: from the export altogether (v1's INV-LP-06), so using it as sample data here
#: would produce a file with no rows in it and a test that appeared to fail for
#: the wrong reason. `test_all_invalid_intervals_are_excluded.py` owns that case.
STATUS_TWO_BITS = 0x0010 | 0x0800

LF = chr(10)
QUOTE = chr(34)
BOM = chr(65279)

#: Five file-header-block lines plus the column header row (M13, issue 07).
HEAD_LINES = 6

#: The twenty-five column headers this file carries, in the customer's own
#: order — imported from the module that owns them rather than restated, so a
#: test that counts positions cannot drift from the file it is counting.
EXPECTED_HEADERS = _EXPORT_HEADERS


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

        # Patched where the write now happens — M13 issue 07 moved this file's
        # own writer to the shared ``arichds.export.writer``.
        monkeypatch.setattr("arichds.export.writer.open", raising_open, raising=False)
        first = export_device(device_id, require_auto_save=True)

        assert first.rows_written == 0
        assert watermark(device_id) is None, "a failed write must not advance the watermark"
        assert not (tmp_path / "SN-1.csv").exists(), "nothing must have reached disk"

        monkeypatch.undo()
        second = export_device(device_id, require_auto_save=True)

        assert second.rows_written == 2, "none of the pending rows may be lost, and none duplicated"
        assert watermark(device_id) == BASE + timedelta(minutes=15)
        rows = list(csv.reader(io.StringIO(read_file(tmp_path / "SN-1.csv"))))
        # Five file-header-block lines and one column-header row (M13, issue
        # 07), then exactly two data rows — no duplicate, no loss.
        assert len(rows) == HEAD_LINES + 2, "no duplicate, no loss"


class TestAHeadChangeRewritesTheFileInPlace:
    """T4, **reversed at M13 issue 07, and reversed again by ADR 0023 (ticket
    02)**.

    This class used to assert that an old-header file was **closed** under a
    dated name while a new one opened beside it. ADR 0023 replaces that: the
    customer's limited disk space rules out a folder that accumulates dated
    editions, so a head change now **rewrites the one file in place**, under
    an atomic swap, with the whole 90-day window recomputed from the database
    rather than just the rows a stale watermark would have picked up. No
    dated file is ever created.
    """

    def _write_old_edition(self, target: Path) -> str:
        v1_header = (
            "Name,Date/Time,Import kWh Active,Import kWh Reactive,Export kWh Active,Export kWh Re,"
            "Avg Geo PF,Voltage L1 (V),Voltage L2 (V),Voltage L3 (V),Current L1 (A),Current L2 (A),"
            "Current L3 (A),Frequency (Hz)" + LF
        )
        v1_row = "Old Row (SN-1),2026-01-01 00:00:00," + ",".join(["0"] * 12) + LF
        target.write_bytes(("﻿" + v1_header + v1_row).encode("utf-8"))
        return v1_header

    def test_the_file_is_rewritten_in_place_under_the_new_head_and_no_dated_file_appears(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        target = tmp_path / "SN-1.csv"
        self._write_old_edition(target)

        seed(device_id, BASE, import_reactive_kvarh=99.0)
        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 1
        rows = list(csv.reader(io.StringIO(read_file(target))))
        assert rows[0] == ["Customer :", ""]
        assert rows[HEAD_LINES - 1] == list(EXPECTED_HEADERS)
        assert len(rows) == HEAD_LINES + 1, "the rewritten file holds only what the current window produces"
        assert rows[HEAD_LINES][EXPECTED_HEADERS.index("Import Reactive (kvarh)")] == format(99.0, ".9f")
        assert list(tmp_path.glob("SN-1.*.csv")) == [], "no dated edition may ever be created"

    def test_a_second_export_appends_rather_than_rewriting_again(self, migrated_db: Settings, tmp_path: Path) -> None:
        """The rewrite fires on a head *change*, not on every write —
        otherwise every cycle would pay for a full-window query."""
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        target = tmp_path / "SN-1.csv"
        self._write_old_edition(target)

        seed(device_id, BASE, import_reactive_kvarh=99.0)
        export_device(device_id, require_auto_save=True)
        seed(device_id, BASE + timedelta(minutes=15), import_reactive_kvarh=98.0)
        export_device(device_id, require_auto_save=True)

        rows = list(csv.reader(io.StringIO(read_file(target))))
        assert len(rows) == HEAD_LINES + 2
        assert list(tmp_path.glob("SN-1.*.csv")) == [], "a head change must never leave a dated file behind"

    def test_the_rewrite_reproduces_a_row_the_old_watermark_had_already_marked_exported(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        """The behaviour a plain append cannot give: a row inside the 90-day
        window that an earlier cycle already exported *under the old head*
        must still appear in the rewritten file — a rewrite reproduces the
        whole window, not just what a stale watermark still calls pending."""
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        target = tmp_path / "SN-1.csv"
        self._write_old_edition(target)

        already_exported = BASE
        newly_pending = BASE + timedelta(minutes=15)
        seed(device_id, already_exported, import_reactive_kvarh=11.0)
        seed(device_id, newly_pending, import_reactive_kvarh=22.0)
        set_watermark(device_id, already_exported)  # as if a prior cycle, under the old head, had exported this row

        export_device(device_id, require_auto_save=True)

        rows = list(csv.reader(io.StringIO(read_file(target))))
        data_rows = rows[HEAD_LINES:]
        assert len(data_rows) == 2, "the row before the old watermark must reappear under the new head"
        assert watermark(device_id) == newly_pending

    def test_a_row_older_than_ninety_days_is_excluded_from_the_rewrite(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        target = tmp_path / "SN-1.csv"
        self._write_old_edition(target)

        now = datetime.now(UTC)
        outside_window = now - timedelta(days=100)
        inside_window = now - timedelta(days=10)
        seed(device_id, outside_window, import_active_kwh=1.0)
        seed(device_id, inside_window, import_active_kwh=2.0)

        export_device(device_id, require_auto_save=True)

        rows = list(csv.reader(io.StringIO(read_file(target))))
        data_rows = rows[HEAD_LINES:]
        assert len(data_rows) == 1, "only the row inside the 90-day window may reach the rewritten file"
        assert watermark(device_id) == inside_window

    def test_the_rewrite_still_holds_rows_past_the_skew_cap(self, migrated_db: Settings, tmp_path: Path) -> None:
        """F5's skew cap is not just an incremental-append rule — the
        head-change rewrite goes through the same `_compute_cap` and must
        stay behind it too: a Logger 1 row newer than Logger 2's own frontier
        is still held back, even on a full-window rewrite."""
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1, 2)
        configure(output_dir=tmp_path)
        target = tmp_path / "SN-1.csv"
        self._write_old_edition(target)

        seed(device_id, BASE, import_active_kwh=1.0)
        seed(device_id, BASE + timedelta(hours=1), import_active_kwh=2.0)  # past L2's frontier — held
        seed(device_id, BASE, logger_id=2, volt_l1=1.0)

        export_device(device_id, require_auto_save=True)

        rows = list(csv.reader(io.StringIO(read_file(target))))
        data_rows = rows[HEAD_LINES:]
        assert len(data_rows) == 1, "only the row at or before the skew cap may reach the rewritten file"
        assert watermark(device_id) == BASE


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

    def test_flipping_kw_w_changes_no_byte_of_the_four_power_columns_either(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        """M13, issue 07 — **the other half of ADR 0013's boundary.**

        Until this ticket the file carried no column the display-unit setting
        had any opinion about, so "the CSV never follows the setting" was true
        the way a rule about an empty set is true. The four average-power
        columns are the first that the setting genuinely converts *on the
        screen*, which makes this the first time the file half is a real
        claim rather than a vacuous one — and the reason the page test beside
        it asserts the opposite direction on the same four columns.
        """
        from arichds.db.app_settings import DISPLAY_UNIT_SCALE_KEY
        from arichds.db.app_settings import set_setting as _set_setting

        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(
            device_id,
            BASE,
            import_active_kw=34.1,
            import_reactive_kvar=5.3,
            export_active_kw=12.2,
            export_reactive_kvar=7.4,
        )

        export_device(device_id, require_auto_save=True)
        at_kilo = (tmp_path / "SN-1.csv").read_bytes()
        (tmp_path / "SN-1.csv").unlink()
        with session_scope() as session:
            _set_setting(session, DISPLAY_UNIT_SCALE_KEY, "base")
        set_watermark(device_id, BASE - timedelta(seconds=1))

        export_device(device_id, require_auto_save=True)
        at_base = (tmp_path / "SN-1.csv").read_bytes()

        assert at_kilo == at_base
        # And the header still says kW/kvar, not W/var, in both.
        assert "Import Active (kW)" in at_kilo.decode("utf-8-sig")
        assert "Import Active (W)" not in at_base.decode("utf-8-sig")

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
    """T9 — byte for byte, BOM + file header block + column header + rows, with
    a None column and a midnight-crossing timestamp.

    Twenty-five columns since M13 issue 07. **The fourteen pre-existing columns
    keep their v1 formats and their v1 values** — this file has an Output
    Parity obligation the two files added in this phase do not, so the eleven
    new columns adopt its existing `.3f` rather than the trimmed decimals used
    elsewhere.
    """

    def _seed_every_column(self, device_id: int, read_at: datetime) -> None:
        """Every one of the twenty-three measurement columns, each a distinct
        value — a transposition between two columns of the same quantity is a
        byte difference here rather than a silent one in a customer's file."""
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
            phase_angle_a=118.5,
            phase_angle_b=238.25,
            phase_angle_c=358.75,
            interval_status_flag=STATUS_TWO_BITS,
            import_active_kw=34.1,
            import_reactive_kvar=5.3,
            export_active_kw=12.2,
            export_reactive_kvar=7.4,
            volt_l1_l2=411.5,
            volt_l2_l3=412.25,
            volt_l3_l1=413.75,
        )

    def test_the_whole_file_matches_the_expected_bytes(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device(name="Main Incomer", serial="1232002893")
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        # UTC 18:30 -> ICT 01:30 the next day.
        read_at = datetime(2026, 8, 1, 18, 30, 0, tzinfo=UTC)
        self._seed_every_column(device_id, read_at)

        result = export_device(device_id, require_auto_save=True)
        assert result.rows_written == 1

        expected_block = (
            "Customer :,"
            + LF
            + "Site Name :,Plant A"
            + LF
            + "Serial Meter :,1232002893"
            + LF
            + "Setting :,1"
            + LF
            + "Load Profile :,"
            + LF
        )
        expected_header = ",".join(EXPECTED_HEADERS) + LF
        expected_row = (
            ",".join(
                [
                    "Main Incomer (1232002893)",
                    "2026-08-02 01:30:00",
                    format(1234.5, ".9f"),
                    "",  # import_reactive_kvarh is None — an empty cell, never "None", never 0
                    format(10.123456789, ".9f"),
                    format(0.0, ".9f"),
                    format(0.987, ".3f"),
                    format(230.123, ".3f"),
                    format(229.5, ".3f"),
                    format(231.2, ".3f"),
                    format(5.111, ".3f"),
                    format(5.222, ".3f"),
                    format(5.333, ".3f"),
                    format(118.5, ".3f"),
                    format(238.25, ".3f"),
                    format(358.75, ".3f"),
                    format(50.01, ".3f"),
                    "DISTURBED|POWER_LOSS",  # 0x0810 = bit 4 | bit 11, pipe-joined
                    format(34.1, ".3f"),
                    format(5.3, ".3f"),
                    format(12.2, ".3f"),
                    format(7.4, ".3f"),
                    format(411.5, ".3f"),
                    format(412.25, ".3f"),
                    format(413.75, ".3f"),
                ]
            )
            + LF
        )
        expected_bytes = (BOM + expected_block + expected_header + expected_row).encode("utf-8")
        assert (tmp_path / "1232002893.csv").read_bytes() == expected_bytes

    def test_the_fourteen_pre_existing_cells_are_unchanged_by_the_eleven(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        """Output Parity over the columns v1 also produced: same header
        strings, same formats, same values, at their new positions. The three
        phase angles and the status column are inserted **before** `Frequency
        (Hz)`, which moves an existing column — this is what proves the move
        did not disturb what it moved."""
        device_id = make_device(name="Main Incomer", serial="1232002893")
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        self._seed_every_column(device_id, datetime(2026, 8, 1, 18, 30, 0, tzinfo=UTC))

        export_device(device_id, require_auto_save=True)

        rows = list(csv.reader(io.StringIO(read_file(tmp_path / "1232002893.csv"))))
        cells = dict(zip(EXPECTED_HEADERS, rows[HEAD_LINES], strict=True))
        assert cells["Import Active (kWh)"] == format(1234.5, ".9f")
        assert cells["Import Reactive (kvarh)"] == ""
        assert cells["Export Active (kWh)"] == format(10.123456789, ".9f")
        assert cells["Export Reactive (kvarh)"] == format(0.0, ".9f")
        assert cells["Avg Geo PF"] == format(0.987, ".3f")
        assert cells["Voltage L1 (V)"] == format(230.123, ".3f")
        assert cells["Voltage L2 (V)"] == format(229.5, ".3f")
        assert cells["Voltage L3 (V)"] == format(231.2, ".3f")
        assert cells["Current L1 (A)"] == format(5.111, ".3f")
        assert cells["Current L2 (A)"] == format(5.222, ".3f")
        assert cells["Current L3 (A)"] == format(5.333, ".3f")
        assert cells["Frequency (Hz)"] == format(50.01, ".3f")

    def test_a_model_that_records_nothing_new_gets_empty_columns_not_missing_ones(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        """Every meter's file has the same shape — already the shipped
        behaviour for `Frequency (Hz)` on an SMW110W4."""
        device_id = make_device(serial="SN-1")
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(device_id, BASE, import_active_kwh=1.0)

        export_device(device_id, require_auto_save=True)

        rows = list(csv.reader(io.StringIO(read_file(tmp_path / "SN-1.csv"))))
        assert len(rows[HEAD_LINES]) == len(EXPECTED_HEADERS)
        cells = dict(zip(EXPECTED_HEADERS, rows[HEAD_LINES], strict=True))
        assert cells["Avg Phase Angle Ph-A"] == ""
        assert cells["Import Active (kW)"] == ""
        assert cells["Voltage L1-L2 (V)"] == ""
        assert cells["Record Status"] == ""


class TestTheStatusColumnIsWordsJoinedByAPipe:
    """v1 joined set bits with a comma, but v1's rendering never reached a CSV
    — it existed only on v1's screen — so no parity is broken. A comma inside a
    cell survives only if every downstream consumer honours CSV quoting, which
    cannot be tested from here."""

    def _status_cell(self, tmp_path: Path, flag: int | None) -> str:
        device_id = make_device(serial="SN-1")
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(device_id, BASE, import_active_kwh=1.0, interval_status_flag=flag)
        export_device(device_id, require_auto_save=True)
        rows = list(csv.reader(io.StringIO(read_file(tmp_path / "SN-1.csv"))))
        return dict(zip(EXPECTED_HEADERS, rows[HEAD_LINES], strict=True))["Record Status"]

    def test_a_clean_interval_reads_ok(self, migrated_db: Settings, tmp_path: Path) -> None:
        assert self._status_cell(tmp_path, 0) == "OK"

    def test_two_set_bits_are_joined_by_a_pipe_and_the_cell_is_not_quoted(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        assert self._status_cell(tmp_path, STATUS_TWO_BITS) == "DISTURBED|POWER_LOSS"
        # A comma would have forced csv to quote the cell; a pipe does not.
        raw = read_file(tmp_path / "SN-1.csv")
        assert "DISTURBED|POWER_LOSS" in raw
        assert QUOTE + "DISTURBED" not in raw

    def test_a_model_with_no_status_word_gets_an_empty_cell(self, migrated_db: Settings, tmp_path: Path) -> None:
        assert self._status_cell(tmp_path, None) == ""


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
        the lock, thread 2 cannot even reach ``append_rows`` until thread 1
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
        # Patched on the module that *calls* it — at M13 issue 07 this file's
        # own private writer was replaced by the shared
        # ``arichds.export.writer.append_rows``, which every export file goes
        # through; patching it at the source would slow the billing and Energy
        # writers too.
        real_append = __import__("arichds.export.csv_export", fromlist=["append_rows"]).append_rows

        def slow_append(final_path, **kwargs):  # noqa: ANN001, ANN003
            nonlocal concurrent_entries, max_concurrent_entries
            with entries_guard:
                concurrent_entries += 1
                max_concurrent_entries = max(max_concurrent_entries, concurrent_entries)
            entered.set()
            release.wait(timeout=10)
            with entries_guard:
                concurrent_entries -= 1
            return real_append(final_path, **kwargs)

        monkeypatch.setattr("arichds.export.csv_export.append_rows", slow_append)

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


class TestTheDailyTrimJob:
    """Ticket 05, ADR 0023 — the daily job that rewrites the Load Profile CSV
    down to the 90-day window. Registered at the retention job's cadence,
    immediately behind it (`jobs/scheduler.py::default_jobs`, own test in
    `test_scheduler.py`); this class proves what the job itself does,
    through `trim_device_load_profile_csv` and `csv_trim_cycle` directly.
    """

    def test_the_trim_drops_rows_older_than_the_retention_window(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        now = datetime.now(UTC)
        outside_window = now - timedelta(days=100)
        inside_window = now - timedelta(days=10)
        seed(device_id, outside_window, import_active_kwh=1.0)
        seed(device_id, inside_window, import_active_kwh=2.0)
        export_device(device_id, require_auto_save=True)
        before = list(csv.reader(io.StringIO(read_file(tmp_path / "SN-1.csv"))))
        assert len(before[HEAD_LINES:]) == 2, "both rows must have appended first, or the trim proves nothing"

        result = trim_device_load_profile_csv(device_id, require_auto_save=True)

        rows = list(csv.reader(io.StringIO(read_file(tmp_path / "SN-1.csv"))))
        data_rows = rows[HEAD_LINES:]
        assert len(data_rows) == 1, "the trim must drop the row older than RETENTION_DAYS"
        assert result.rows_written == 1
        assert watermark(device_id) == inside_window

    def test_the_fifteen_minute_cycle_never_trims_the_window_on_its_own(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        """Cadence — only the daily trim (or a head change) may drop an
        out-of-window row. The plain append path the fifteen-minute cycle
        uses must never trim on its own, even once the file already holds a
        row past RETENTION_DAYS."""
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        now = datetime.now(UTC)
        outside_window = now - timedelta(days=100)
        seed(device_id, outside_window, import_active_kwh=1.0)
        export_device(device_id, require_auto_save=True)

        newer = now - timedelta(days=10)
        seed(device_id, newer, import_active_kwh=2.0)
        export_device(device_id, require_auto_save=True)  # a plain append — no head change, no trim

        rows = list(csv.reader(io.StringIO(read_file(tmp_path / "SN-1.csv"))))
        data_rows = rows[HEAD_LINES:]
        assert len(data_rows) == 2, "the fifteen-minute cycle rewrote the file down to the window on its own"

    def test_the_trim_keeps_the_kept_rows_byte_identical_to_the_appended_file(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        """Faithful — for the rows it keeps, the trimmed file equals what
        appending alone had already produced: same formatting, same order,
        byte for byte."""
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        now = datetime.now(UTC)
        outside_window = now - timedelta(days=100)
        inside_window = now - timedelta(days=10)
        seed(device_id, outside_window, import_active_kwh=1.0)
        seed(device_id, inside_window, import_active_kwh=2.0)
        export_device(device_id, require_auto_save=True)
        appended_lines = (tmp_path / "SN-1.csv").read_text(encoding="utf-8-sig").splitlines()
        kept_line = appended_lines[-1]  # the newer row's own line — unaffected by the trim

        trim_device_load_profile_csv(device_id, require_auto_save=True)

        trimmed_lines = (tmp_path / "SN-1.csv").read_text(encoding="utf-8-sig").splitlines()
        assert trimmed_lines[-1] == kept_line, "the kept row's own bytes changed between append and trim"
        assert len(trimmed_lines) == HEAD_LINES + 1, "the older row must be gone, not just the newer one kept"

    def test_the_first_append_after_a_trim_adds_only_newer_rows_with_no_duplicate(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        now = datetime.now(UTC)
        inside_window = now - timedelta(days=10)
        seed(device_id, inside_window, import_active_kwh=2.0)
        export_device(device_id, require_auto_save=True)
        trim_device_load_profile_csv(device_id, require_auto_save=True)

        newer = inside_window + timedelta(minutes=15)
        seed(device_id, newer, import_active_kwh=3.0)
        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 1, "the append after a trim duplicated or skipped a row"
        rows = list(csv.reader(io.StringIO(read_file(tmp_path / "SN-1.csv"))))
        data_rows = rows[HEAD_LINES:]
        assert len(data_rows) == 2, "no duplicate and no gap after a trim"
        assert watermark(device_id) == newer

    def test_the_trim_writes_nothing_when_auto_save_is_off(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(device_id, BASE, import_active_kwh=1.0)
        export_device(device_id, require_auto_save=True)
        before = (tmp_path / "SN-1.csv").read_bytes()
        with session_scope() as session:
            set_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, "false")

        result = trim_device_load_profile_csv(device_id, require_auto_save=True)

        assert result.rows_written == 0
        assert (tmp_path / "SN-1.csv").read_bytes() == before, "the trim wrote despite auto-save being off"

    def test_the_cycle_trims_every_enabled_device(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_a = make_device("A", port=4059, serial="SN-A")
        device_b = make_device("B", port=4060, serial="SN-B")
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        now = datetime.now(UTC)
        outside_window = now - timedelta(days=100)
        inside_window = now - timedelta(days=10)
        for device_id in (device_a, device_b):
            seed(device_id, outside_window, import_active_kwh=1.0)
            seed(device_id, inside_window, import_active_kwh=2.0)
            export_device(device_id, require_auto_save=True)

        csv_trim_cycle()

        for serial in ("SN-A", "SN-B"):
            rows = list(csv.reader(io.StringIO(read_file(tmp_path / f"{serial}.csv"))))
            assert len(rows[HEAD_LINES:]) == 1, f"{serial} was not trimmed to the window"

    def test_the_trim_cycle_does_not_skip_a_paused_device(self, migrated_db: Settings, tmp_path: Path) -> None:
        """Reviewer finding 1(a) — unlike `csv_export_cycle`, this cycle must
        not filter on `enabled`. `purge_expired` deletes a paused device's
        rows past RETENTION_DAYS exactly like every other device's; a filter
        here would leave a paused device's CSV holding rows the database no
        longer has, forever. Paired with an active device that must behave
        the same way, so a blanket "trim everything" implementation can't
        pass this test for the wrong reason."""
        paused_id = make_device("Paused", port=4059, enabled=False, serial="SN-PAUSED")
        active_id = make_device("Active", port=4060, serial="SN-ACTIVE")
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        now = datetime.now(UTC)
        outside_window = now - timedelta(days=100)
        for device_id in (paused_id, active_id):
            seed(device_id, outside_window, import_active_kwh=1.0)
            export_device(device_id, require_auto_save=True)

        csv_trim_cycle()

        paused_rows = list(csv.reader(io.StringIO(read_file(tmp_path / "SN-PAUSED.csv"))))
        active_rows = list(csv.reader(io.StringIO(read_file(tmp_path / "SN-ACTIVE.csv"))))
        assert len(paused_rows[HEAD_LINES:]) == 0, "the paused device's out-of-window row was not trimmed"
        assert len(active_rows[HEAD_LINES:]) == 0, "the enabled device's out-of-window row was not trimmed"

    def test_a_device_whose_every_logger_1_row_has_aged_out_is_trimmed_to_nothing(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        """Reviewer finding 1(b) — `purge_expired` runs immediately ahead of
        this job in the registry, so a device that has not reported for the
        whole retention window has *no* Logger 1 rows left by the time this
        runs: the ordinary state of a meter gone quiet for 90 days, not a
        bug. `_resolve_export_context` (the append path) holds quietly on
        that, but the trim must not — the file must still come down to
        nothing, or it carries a 100-day-old row forever."""
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        old_reading = datetime.now(UTC) - timedelta(days=100)
        seed(device_id, old_reading, import_active_kwh=1.0)
        export_device(device_id, require_auto_save=True)
        before = list(csv.reader(io.StringIO(read_file(tmp_path / "SN-1.csv"))))
        assert len(before[HEAD_LINES:]) == 1, "the row must have appended first, or this test proves nothing"

        purge_expired()
        csv_trim_cycle()

        rows = list(csv.reader(io.StringIO(read_file(tmp_path / "SN-1.csv"))))
        assert len(rows[HEAD_LINES:]) == 0, "a device with no Logger 1 rows left must still be trimmed to nothing"

    def test_the_trim_cycle_writes_nothing_when_auto_save_is_off(self, migrated_db: Settings, tmp_path: Path) -> None:
        """Pins that the *job* (`csv_trim_cycle`, `require_auto_save=True`)
        respects the switch — the direct-call test above only proves
        `trim_device_load_profile_csv` does."""
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        now = datetime.now(UTC)
        outside_window = now - timedelta(days=100)
        seed(device_id, outside_window, import_active_kwh=1.0)
        export_device(device_id, require_auto_save=True)
        before = (tmp_path / "SN-1.csv").read_bytes()
        with session_scope() as session:
            set_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, "false")

        csv_trim_cycle()

        assert (tmp_path / "SN-1.csv").read_bytes() == before, "the trim cycle wrote despite auto-save being off"

    def test_the_trim_cycle_never_creates_a_file(self, migrated_db: Settings, tmp_path: Path) -> None:
        """Reviewer finding 1, round 3 — trimming only ever shrinks a file
        the fifteen-minute cycle already created. A device with stored rows
        but no file yet (paused before its first `export_device` call, so
        never exported — `export_device` is deliberately never called here)
        must not get one created by the daily trim; that would be export
        work, which `csv_export_cycle`'s own Pause rule already governs."""
        device_id = make_device("Paused", enabled=False, serial="SN-PAUSED")
        fake_meter_state().load_profile_loggers = (1,)
        configure(output_dir=tmp_path)
        seed(device_id, datetime.now(UTC) - timedelta(days=10), import_active_kwh=1.0)

        csv_trim_cycle()

        assert not (tmp_path / "SN-PAUSED.csv").exists(), "the trim cycle created a file that never existed"
