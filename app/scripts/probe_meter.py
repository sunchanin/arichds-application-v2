#!/usr/bin/env python3
"""Read one real meter's Meter Serial and instantaneous set. Operator diagnostic.

READ-ONLY: connects, reads, disconnects. It never writes to the meter and never
writes to the database — use it to prove a driver and its connection parameters
against real hardware without involving the Poller or the API.

It reads two things. The **Meter Serial** is the register the Poller's liveness
tick reads (ADR 0007): if it fails here, that device will never leave Unknown.
The **instantaneous set** is no longer read by the app at all — nothing in v2
displays or stores a live value — and survives here because settling an Output
Parity argument against v1 needs those numbers in front of a person.

Mirrors the role of v1's ``cewe-worker/scripts/`` probes. The meter-facing path
itself still needs real hardware, which CI will never have; the report-formatting
logic below — how a refused or empty Meter Serial is rendered — is covered against
a stub driver by ``tests/test_probe_meter_script.py``.

Usage (from ``app/``)::

    python scripts/probe_meter.py --host 203.0.113.10 --port 4059 --password ABCD0001
    python scripts/probe_meter.py --host 203.0.113.10 --model sim
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Allow running straight from a checkout without installing the package.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from arichds.acquisition.connection_params import ConnectionParams  # noqa: E402
from arichds.acquisition.drivers.factory import create_driver, supported_models  # noqa: E402
from arichds.logging_config import configure_logging  # noqa: E402


def _report_scalers(driver) -> None:  # noqa: ANN001 — any MeterDriver with a Gurux client.
    """Print raw value, scaler exponent and scaled value for each register.

    Reads ``scaler_unit`` (attr 3) and the value (attr 2) explicitly so the
    meter's own exponent is visible. This is what settles output-parity
    arguments: v1 mis-read the Gurux ``scaler`` attribute as an exponent when it
    is really the multiplier, so its arithmetic only came out right where the
    exponent happened to be 0 (v1 ADR 0010).
    """
    import math

    from gurux_dlms.objects import GXDLMSRegister

    # ASCII only: a Windows console defaults to cp1252 and would raise on arrows.
    print("\n=== SCALER REPORT (raw -> scaled) ===")
    for column, (obis, _attr) in driver.get_obis_map().items():
        try:
            obj = GXDLMSRegister(obis)
            driver._client.objects.append(obj)
            driver._reader.read(obj, 3)  # populates obj.scaler = 10**exponent
            multiplier = float(obj.scaler)
            exponent = int(round(math.log10(multiplier))) if multiplier > 0 else 0
            scaled = driver._reader.read(obj, 2)  # Gurux applies the multiplier
            raw = float(scaled) / multiplier if multiplier else float(scaled)
            print(
                f"  {column:<18} {obis:<16} raw={raw:<18.4f} exp={exponent:<4} "
                f"multiplier={multiplier:<10g} scaled={float(scaled):.4f}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  {column:<18} {obis:<16} !! {type(exc).__name__}: {exc}")


def main() -> int:
    """Connect to one meter, print its serial and instantaneous set, disconnect."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", required=True, help="Meter host or IP.")
    parser.add_argument("--port", type=int, default=4059, help="Meter TCP port (default 4059).")
    parser.add_argument("--password", default="", help="DLMS password. Never logged.")
    parser.add_argument(
        "--model",
        default="prometer100",
        help=f"Meter model. Supported: {supported_models()}",
    )
    parser.add_argument("--verbose", action="store_true", help="DEBUG logging.")
    parser.add_argument(
        "--show-scaler",
        action="store_true",
        help="Also report each register's raw value and scaler exponent. Use this when checking "
        "output parity against v1 — the scaler is the one place v2 deliberately differs (SPEC §3.4).",
    )
    args = parser.parse_args()

    # Console only — a diagnostic must not pollute the service log directory.
    configure_logging(level="DEBUG" if args.verbose else "INFO", log_dir=None, enable_file=False)

    conn = ConnectionParams.net(args.host, args.port)
    driver = create_driver(args.model, conn, password=args.password)

    print(f"=== {args.model} @ {conn.endpoint} — connecting ===")
    started = time.monotonic()
    try:
        driver.connect()
        print(f"--- associated in {time.monotonic() - started:.1f}s ---")
        if args.show_scaler:
            _report_scalers(driver)

        # The Meter Serial first, on its own line: this is the exact register the
        # Poller's liveness tick reads (ADR 0007), so if it fails here it will
        # fail there, and the device will never leave Unknown.
        print("\n=== METER SERIAL (the register the liveness tick reads) ===")
        try:
            serial = driver.read_meter_serial()
        except Exception as exc:  # noqa: BLE001 — a refused serial must not end the report either.
            serial_line = f"!! {type(exc).__name__}: {exc}"
        else:
            serial_line = (
                serial
                if serial is not None
                else "<none> (associated, but the meter served no serial - a FAILED tick per ADR 0007)"
            )
        print(f"  meter_serial      : {serial_line}")

        # Then the instantaneous set, register by register. The app itself no
        # longer reads this set — it is here because settling an Output Parity
        # argument against v1 needs the values, not because anything stores them.
        print("\n=== INSTANTANEOUS SET (normalized: kWh, engineering units) ===")
        for column, (obis, attr) in driver.get_obis_map().items():
            try:
                value = driver._normalize(column, driver.read_register(obis, attr))
            except Exception as exc:  # noqa: BLE001 — one refused register must not end the report.
                value = f"!! {type(exc).__name__}: {exc}"
            print(f"  {column:<18} {obis:<16} {value}")
    except Exception as exc:  # noqa: BLE001 — a diagnostic reports, it does not crash.
        print(f"\n!!! FAILED: {type(exc).__name__}: {exc}")
        return 1
    finally:
        driver.disconnect()
        print("--- disconnected ---")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
