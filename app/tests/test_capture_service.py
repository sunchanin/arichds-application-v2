"""``capture.service`` — wires the renderers and the hardened write together
(M6b, issue #22). The one place both callers (the eager write in
``acquisition/billing.py`` and the render-on-miss download in
``api/billing.py``) build a path and write a file, so they cannot drift.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from arichds.capture.service import capture_reading, capture_target_paths

BILL_DATE = datetime(2026, 7, 31, 17, 0, 0, tzinfo=UTC)


def make_row(**overrides: object) -> SimpleNamespace:
    from arichds.capture._render_shared import ALL_SECTIONS

    fields = {attr: None for _title, section in ALL_SECTIONS for _label, attr in section}
    fields.update(bill_date=BILL_DATE, meter_serial="1232002893", record_status=None, read_at=BILL_DATE)
    fields.update(overrides)
    return SimpleNamespace(**fields)


class TestCaptureTargetPaths:
    def test_the_path_follows_the_fixed_convention(self, tmp_path: Path) -> None:
        pdf_path, xlsx_path = capture_target_paths(tmp_path, "1232002893", BILL_DATE)

        assert pdf_path == (tmp_path / "1232002893" / "2026-07-31_170000.pdf").resolve()
        assert xlsx_path == (tmp_path / "1232002893" / "2026-07-31_170000.xlsx").resolve()

    def test_a_naive_bill_date_is_treated_as_utc(self, tmp_path: Path) -> None:
        naive = BILL_DATE.replace(tzinfo=None)
        pdf_path, _ = capture_target_paths(tmp_path, "1232002893", naive)

        assert pdf_path.name == "2026-07-31_170000.pdf"

    def test_an_unsafe_serial_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            capture_target_paths(tmp_path, "../escape", BILL_DATE)


class TestCaptureReading:
    def test_writes_only_the_pdf_when_excel_is_off(self, tmp_path: Path) -> None:
        row = make_row()

        capture_reading(row, "Main Incomer", tmp_path, write_excel=False)

        pdf_path, xlsx_path = capture_target_paths(tmp_path, "1232002893", BILL_DATE)
        assert pdf_path.exists()
        assert not xlsx_path.exists()

    def test_writes_both_when_excel_is_on(self, tmp_path: Path) -> None:
        row = make_row()

        capture_reading(row, "Main Incomer", tmp_path, write_excel=True)

        pdf_path, xlsx_path = capture_target_paths(tmp_path, "1232002893", BILL_DATE)
        assert pdf_path.exists()
        assert xlsx_path.exists()

    def test_a_missing_meter_serial_writes_nothing_and_does_not_raise(self, tmp_path: Path) -> None:
        row = make_row(meter_serial=None)

        capture_reading(row, "Main Incomer", tmp_path, write_excel=True)  # must not raise

        assert list(tmp_path.iterdir()) == []

    def test_the_scale_argument_reaches_the_xlsx_render(self, tmp_path: Path) -> None:
        """`capture_reading`'s `scale` must reach the renderer, not just be
        accepted and dropped — proven by reading the label back off the
        written file rather than by inspecting the call."""
        from openpyxl import load_workbook

        row = make_row(import_active_kwh_total=42.5)

        capture_reading(row, "Main Incomer", tmp_path, write_excel=True, scale="base")

        _pdf_path, xlsx_path = capture_target_paths(tmp_path, "1232002893", BILL_DATE)
        values = [cell.value for sheet_row in load_workbook(xlsx_path).active.iter_rows() for cell in sheet_row]
        assert "Import Active Wh Total" in values
        assert 42500.0 in values or "42500.0" in values

    def test_an_xlsx_write_failure_does_not_undo_the_pdf(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import arichds.capture.service as service_module

        row = make_row()

        def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("xlsx blew up")

        monkeypatch.setattr(service_module, "write_xlsx_capture", boom)

        capture_reading(row, "Main Incomer", tmp_path, write_excel=True)  # must not raise

        pdf_path, xlsx_path = capture_target_paths(tmp_path, "1232002893", BILL_DATE)
        assert pdf_path.exists()
        assert not xlsx_path.exists()
