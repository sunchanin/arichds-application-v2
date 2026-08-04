#!/usr/bin/env python3
"""Read the M1 instantaneous set from one real meter. Operator diagnostic.

READ-ONLY: connects, reads, disconnects. It never writes to the meter and never
writes to the database — use it to prove a driver and its connection parameters
against real hardware without involving the Poller or the API.

Mirrors the role of v1's ``cewe-worker/scripts/`` probes. Not part of the pytest
suite: it needs a reachable meter, which CI will never have.

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
    """Connect to one meter, print the instantaneous set, disconnect."""
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
        reading = driver.read_instantaneous()
    except Exception as exc:  # noqa: BLE001 — a diagnostic reports, it does not crash.
        print(f"\n!!! FAILED: {type(exc).__name__}: {exc}")
        return 1
    finally:
        driver.disconnect()
        print("--- disconnected ---")

    print("\n=== INSTANTANEOUS READING (normalized: UTC, kWh) ===")
    print(f"  read_at (UTC)     : {reading.read_at.isoformat()}")
    print(f"  source            : {reading.source}")
    print(f"  volt_l1 (V)       : {reading.volt_l1}")
    print(f"  volt_l2 (V)       : {reading.volt_l2}")
    print(f"  volt_l3 (V)       : {reading.volt_l3}")
    print(f"  current_l1 (A)    : {reading.current_l1}")
    print(f"  current_l2 (A)    : {reading.current_l2}")
    print(f"  current_l3 (A)    : {reading.current_l3}")
    print(f"  freq (Hz)         : {reading.freq}")
    print(f"  import_active_kwh : {reading.import_active_kwh}")
    print(f"\n  read latency      : {getattr(driver, 'last_latency_ms', None)} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
