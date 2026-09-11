"""v1's ``INV-LP-06`` — an interval the meter marked all-invalid is excluded
from the Energy Summary, the Load Profile page and the Load Profile CSV.

Found by ``/scrutinize`` on 2026-09-11, after M13 issue 07 shipped. v1 applies
``(status_flag IS NULL OR (status_flag & 1) = 0)`` in six places
(``cewe/cewe-worker/src/load_profile/repository.py:182`` for the Energy Summary,
``:204``/``:242`` for the page and its count, ``:260``/``:290``/``:329`` for the
export). v2 applied it in none — **not by oversight originally**: there was no
column to filter on until issue 06 stored the word. Issue 06 made the filter
possible and issue 07 rendered the word without ever consuming it, which is what
turned an unavoidable divergence into an undone one.

CLAUDE.md binds Output Parity to exactly three modules — "Output Parity vs v1
for LP/Billing/Energy" — and all three are affected.

**Records deliberately keeps counting these rows**, matching v1's own
``_GRID_SQL`` (``repository.py:61-76``), which carries no such predicate. The
two answer different questions, as CONTEXT.md separates them: Records asks
whether a row arrived, Interval Status asks whether one row is trustworthy.
``TestRecordsStillCountsThem`` pins that, so a later reader does not "make it
consistent" and silently change what a complete day means.
"""

from __future__ import annotations

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
from arichds.export.csv_export import export_device

pytestmark = pytest.mark.usefixtures("fake_meter")

#: 2026-08-01 local (UTC+7) is 2026-07-31 17:00 UTC. Every timestamp below is
#: chosen to sit inside one local day so the Energy Summary groups them
#: together.
BASE = datetime(2026, 8, 1, 3, 0, tzinfo=UTC)

#: Bit 0 set, and nothing else — the word v1 excludes on.
ALL_INVALID = 1

#: Bit 4 (DISTURBED) — a meter complaint that is **not** all-invalid, so the
#: row stays. Without this case the tests would pass against a filter that
#: rejected any non-zero word, which is not the rule.
DISTURBED = 0x0010


def make_device(*, serial: str = "SN-1") -> int:
    with session_scope() as session:
        device = Device(
            name="Main Incomer",
            brand="cewe",
            model="prometer100",
            site_name="Plant A",
            transport={"kind": "net", "host": "127.0.0.1", "port": 4059},
            password="hunter2",
            enabled=True,
            status="online",
            meter_serial=serial,
        )
        session.add(device)
        session.flush()
        return device.id


def seed(device_id: int, read_at: datetime, *, logger_id: int = 1, **columns: object) -> None:
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


def configure(output_dir: Path) -> None:
    with session_scope() as session:
        set_setting(session, EXPORT_OUTPUT_DIR_KEY, str(output_dir))
        set_setting(session, EXPORT_AUTO_SAVE_ENABLED_KEY, "true")
        set_setting(session, EXPORT_CSV_FILENAME_TMPL_KEY, "[meter].csv")
        set_setting(session, EXPORT_DATE_FORMAT_KEY, "yyyy-mm-dd HH:MM:SS")


def watermark(device_id: int) -> datetime | None:
    with session_scope() as session:
        value = session.get(Device, device_id).csv_exported_through
        return value.replace(tzinfo=UTC) if value is not None else None


class TestTheEnergySummaryExcludesThem:
    """``repository.py:182`` — the module the customer bills from."""

    def _totals(self, device_id: int) -> float:
        from arichds.db.energy_query import energy_summary_rows

        with session_scope() as session:
            days = energy_summary_rows(session, device_id, BASE.date(), BASE.date() + timedelta(days=1))
        return sum(day.total_import_kwh or 0.0 for day in days)

    def test_an_all_invalid_interval_does_not_reach_the_daily_total(self, migrated_db: Settings) -> None:
        device_id = make_device()
        seed(device_id, BASE, import_active_kwh=10.0, interval_status_flag=0)
        seed(device_id, BASE + timedelta(minutes=15), import_active_kwh=999.0, interval_status_flag=ALL_INVALID)

        assert self._totals(device_id) == pytest.approx(10.0)

    def test_a_disturbed_but_not_invalid_interval_still_counts(self, migrated_db: Settings) -> None:
        """The rule is bit 0, not "any complaint". A filter written as
        `interval_status_flag = 0` would pass every other test in this file and
        silently drop real energy."""
        device_id = make_device()
        seed(device_id, BASE, import_active_kwh=10.0, interval_status_flag=0)
        seed(device_id, BASE + timedelta(minutes=15), import_active_kwh=5.0, interval_status_flag=DISTURBED)

        assert self._totals(device_id) == pytest.approx(15.0)

    def test_a_model_that_records_no_status_word_is_untouched(self, migrated_db: Settings) -> None:
        """NULL means "this model has no such register" — the SMW110W4 and the
        Saral 305. "The meter said nothing" is not "the meter said this is
        rubbish", and a filter missing the IS NULL branch would empty those
        models' summaries completely."""
        device_id = make_device()
        seed(device_id, BASE, import_active_kwh=10.0, interval_status_flag=None)
        seed(device_id, BASE + timedelta(minutes=15), import_active_kwh=5.0, interval_status_flag=None)

        assert self._totals(device_id) == pytest.approx(15.0)


class TestThePageExcludesThem:
    """``repository.py:204``/``:242`` — the rows and the count, which
    ``merged_rows_select`` serves from one Select so they cannot disagree."""

    def _rows_and_total(self, device_id: int) -> tuple[int, int]:
        from sqlalchemy import func, select

        from arichds.db.load_profile_query import merged_rows_select

        with session_scope() as session:
            base = merged_rows_select(device_id)
            rows = session.execute(base).all()
            total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
        return len(rows), total

    def test_an_all_invalid_row_is_absent_from_both_the_rows_and_the_count(self, migrated_db: Settings) -> None:
        device_id = make_device()
        seed(device_id, BASE, import_active_kwh=1.0, interval_status_flag=0)
        seed(device_id, BASE + timedelta(minutes=15), import_active_kwh=2.0, interval_status_flag=ALL_INVALID)

        assert self._rows_and_total(device_id) == (1, 1)

    def test_a_model_with_no_status_word_keeps_every_row(self, migrated_db: Settings) -> None:
        """The SMW110W4 and the Saral 305 store NULL here. Dropping the IS NULL
        branch would empty the Load Profile page and the CSV for both models
        entirely — a mutation that survived this file when it was first
        written, because every other case here sets the word explicitly."""
        device_id = make_device()
        seed(device_id, BASE, import_active_kwh=1.0, interval_status_flag=None)
        seed(device_id, BASE + timedelta(minutes=15), import_active_kwh=2.0, interval_status_flag=None)

        assert self._rows_and_total(device_id) == (2, 2)

    def test_a_disturbed_but_not_invalid_row_stays_on_the_page(self, migrated_db: Settings) -> None:
        """Bit 0, not "any complaint" — a filter written `== 0` would hide
        every DISTURBED and POWER_LOSS interval from the page and the CSV,
        which v1 shows. Another mutation that survived this file at first."""
        device_id = make_device()
        seed(device_id, BASE, import_active_kwh=1.0, interval_status_flag=0)
        seed(device_id, BASE + timedelta(minutes=15), import_active_kwh=2.0, interval_status_flag=DISTURBED)

        assert self._rows_and_total(device_id) == (2, 2)

    def test_the_rows_and_the_count_never_disagree(self, migrated_db: Settings) -> None:
        device_id = make_device()
        for index in range(6):
            seed(
                device_id,
                BASE + timedelta(minutes=15 * index),
                import_active_kwh=float(index),
                interval_status_flag=ALL_INVALID if index % 2 else 0,
            )

        rows, total = self._rows_and_total(device_id)
        assert rows == total == 3


class TestTheCsvExcludesThem:
    """``repository.py:260``/``:290``/``:329``."""

    def _data_lines(self, path: Path) -> list[str]:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        header_index = next(i for i, line in enumerate(lines) if line.startswith("Name,Date/Time,"))
        return lines[header_index + 1 :]

    def test_an_all_invalid_interval_is_not_written(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(tmp_path)
        seed(device_id, BASE, import_active_kwh=1.0, interval_status_flag=0)
        seed(device_id, BASE + timedelta(minutes=15), import_active_kwh=999.0, interval_status_flag=ALL_INVALID)

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 1
        written = self._data_lines(tmp_path / "SN-1.csv")
        assert len(written) == 1
        assert "999.000000000" not in written[0]

    def test_a_disturbed_but_not_invalid_interval_is_still_written(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(tmp_path)
        seed(device_id, BASE, import_active_kwh=1.0, interval_status_flag=DISTURBED)

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 1
        assert "DISTURBED" in self._data_lines(tmp_path / "SN-1.csv")[0]

    def test_a_model_with_no_status_word_still_exports(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(tmp_path)
        seed(device_id, BASE, import_active_kwh=1.0, interval_status_flag=None)

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 1


class TestTheWatermarkAdvancesPastAnExcludedRow:
    """The trap this filter would otherwise set, and the reason the export
    watermark stopped keying on ``rows[-1]``.

    The window is ``(watermark, cap]``. If the watermark only ever advances to
    the newest row that was *written*, an all-invalid row at the frontier is
    never passed, the window grows by one interval every cycle, and the same
    rejected rows are re-queried for ever — no bug required, just a meter that
    flagged one interval. It is the shape of the self-healing-watermark trap.
    """

    def test_a_window_whose_newest_row_is_invalid_still_advances(self, migrated_db: Settings, tmp_path: Path) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(tmp_path)
        newest = BASE + timedelta(minutes=15)
        seed(device_id, BASE, import_active_kwh=1.0, interval_status_flag=0)
        seed(device_id, newest, import_active_kwh=2.0, interval_status_flag=ALL_INVALID)

        export_device(device_id, require_auto_save=True)

        assert watermark(device_id) == newest, "the watermark must pass the row the filter dropped"

    def test_a_window_of_nothing_but_invalid_rows_advances_and_writes_nothing(
        self, migrated_db: Settings, tmp_path: Path
    ) -> None:
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(tmp_path)
        newest = BASE + timedelta(minutes=15)
        seed(device_id, BASE, import_active_kwh=1.0, interval_status_flag=ALL_INVALID)
        seed(device_id, newest, import_active_kwh=2.0, interval_status_flag=ALL_INVALID)

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 0
        assert not list(tmp_path.glob("*.csv")), "nothing should have been created"
        assert watermark(device_id) == newest

    def test_a_second_cycle_re_reads_nothing(self, migrated_db: Settings, tmp_path: Path) -> None:
        """The observable the growing window would break."""
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(tmp_path)
        seed(device_id, BASE, import_active_kwh=1.0, interval_status_flag=0)
        seed(device_id, BASE + timedelta(minutes=15), import_active_kwh=2.0, interval_status_flag=ALL_INVALID)

        export_device(device_id, require_auto_save=True)
        second = export_device(device_id, require_auto_save=True)

        assert second.rows_written == 0
        assert len(self_data_lines(tmp_path / "SN-1.csv")) == 1

    def test_a_failed_write_still_leaves_the_watermark_alone(
        self, migrated_db: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The distinction the new watermark must not blur: a row deliberately
        excluded is dealt with, a row that could not be written is not."""
        device_id = make_device()
        fake_meter_state().load_profile_loggers = (1,)
        configure(tmp_path)
        seed(device_id, BASE, import_active_kwh=1.0, interval_status_flag=0)

        def raising_open(*args: object, **kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("arichds.export.writer.open", raising_open, raising=False)

        result = export_device(device_id, require_auto_save=True)

        assert result.rows_written == 0
        assert watermark(device_id) is None


def self_data_lines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    header_index = next(i for i, line in enumerate(lines) if line.startswith("Name,Date/Time,"))
    return lines[header_index + 1 :]


class TestRecordsStillCountsThem:
    """v1's ``_GRID_SQL`` (``repository.py:61-76``) carries no status predicate,
    and neither should ours. Pinned so nobody "makes it consistent" later: that
    would silently redefine what a complete day means."""

    def test_records_counts_an_all_invalid_row_like_any_other(self, migrated_db: Settings) -> None:
        """Behavioural, not a grep: Records builds its own count straight off
        the model (``api/records.py:183-199``) rather than through
        ``merged_rows_select``, so it is unaffected by the filter — and this is
        what proves it stays that way."""
        from sqlalchemy import func, select

        device_id = make_device()
        seed(device_id, BASE, import_active_kwh=1.0, interval_status_flag=0)
        seed(device_id, BASE + timedelta(minutes=15), import_active_kwh=2.0, interval_status_flag=ALL_INVALID)

        with session_scope() as session:
            stored = session.scalar(
                select(func.count()).select_from(LoadProfileReading).where(LoadProfileReading.device_id == device_id)
            )

        assert stored == 2, "a day whose rows all arrived is complete, whatever the meter thinks of them"
