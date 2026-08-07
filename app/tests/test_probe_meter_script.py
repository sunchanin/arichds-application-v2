"""probe_meter.py must finish its report when the Meter Serial is refused or empty.

The Meter Serial read (``probe_meter.py`` around line 110) used to run bare,
inside the function-wide ``try``. A meter that associated but then raised on
that one register — or answered with nothing — took the whole report down
with it, even though the per-register instantaneous loop right below it is
already built to survive exactly that (docs/issues/001).

``scripts/`` is not a package and is not on ``pythonpath`` (``pyproject.toml``
only lists ``src``), so this mirrors ``conftest.vendor_cli``'s own
``sys.path`` insert rather than adding a second import mechanism.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import probe_meter as probe_meter_script  # noqa: E402

OBIS_MAP = {"volt_l1": ("1.0.32.7.0.255", 2), "import_active_kwh": ("1.0.1.8.0.255", 2)}


class StubMeterDriver:
    """A driver double exposing exactly what ``probe_meter.main()`` touches.

    Not a :class:`~arichds.acquisition.drivers.base.MeterDriver` subclass and
    not added to ``tests/fakes.py`` — the script duck-types its driver, and
    ``FakeMeterDriver`` has no ``read_register``/``_normalize`` and an empty
    OBIS map, so it cannot produce an instantaneous set to assert on.
    """

    def __init__(
        self,
        *,
        serial: str | None = "unset",
        serial_error: Exception | None = None,
        connect_error: Exception | None = None,
    ) -> None:
        self._serial = serial
        self._serial_error = serial_error
        self._connect_error = connect_error
        self.disconnect_calls = 0

    def connect(self) -> None:
        if self._connect_error is not None:
            raise self._connect_error

    def disconnect(self) -> None:
        # Never raises — it runs in the script's `finally`, same contract as
        # every real MeterDriver.
        self.disconnect_calls += 1

    def get_obis_map(self) -> dict[str, tuple[str, int]]:
        return OBIS_MAP

    def read_register(self, obis: str, attr: int) -> Any:
        return 240.0

    def _normalize(self, column: str, raw: Any) -> Any:
        return raw

    def read_meter_serial(self) -> str | None:
        if self._serial_error is not None:
            raise self._serial_error
        return self._serial


def run_probe_meter(monkeypatch, driver: StubMeterDriver, capsys) -> tuple[int, str]:
    """Run ``probe_meter.main()`` against *driver*, opening no network connection."""
    monkeypatch.setattr(probe_meter_script, "create_driver", lambda *a, **kw: driver)
    monkeypatch.setattr(probe_meter_script, "configure_logging", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", ["probe_meter.py", "--host", "198.51.100.7"])

    exit_code = probe_meter_script.main()

    return exit_code, capsys.readouterr().out


def test_happy_path_prints_serial_and_instantaneous_set(monkeypatch, capsys) -> None:
    driver = StubMeterDriver(serial="ABC12345")

    exit_code, out = run_probe_meter(monkeypatch, driver, capsys)

    assert "meter_serial      : ABC12345" in out
    assert "volt_l1" in out
    assert "import_active_kwh" in out
    assert exit_code == 0


def test_refused_serial_still_prints_the_instantaneous_set(monkeypatch, capsys) -> None:
    driver = StubMeterDriver(serial_error=RuntimeError("undefined object"))

    exit_code, out = run_probe_meter(monkeypatch, driver, capsys)

    assert "!! RuntimeError: undefined object" in out
    assert "volt_l1" in out
    assert "import_active_kwh" in out
    assert exit_code == 0


def test_none_serial_is_distinguishable_and_report_continues(monkeypatch, capsys) -> None:
    driver = StubMeterDriver(serial=None)

    exit_code, out = run_probe_meter(monkeypatch, driver, capsys)

    assert "<none>" in out
    assert not any(line.rstrip().endswith(": None") for line in out.splitlines())
    assert "volt_l1" in out
    assert "import_active_kwh" in out
    assert exit_code == 0


def test_connect_failure_still_returns_1_and_disconnects(monkeypatch, capsys) -> None:
    driver = StubMeterDriver(connect_error=RuntimeError("association refused"))

    exit_code, out = run_probe_meter(monkeypatch, driver, capsys)

    assert "!!! FAILED:" in out
    assert exit_code == 1
    assert driver.disconnect_calls == 1
