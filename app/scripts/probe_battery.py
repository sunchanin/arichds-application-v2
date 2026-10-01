"""Read-only: does this meter answer the battery register the product reads?

The ``battery`` job reads :data:`CEWE_BATTERY_STATUS_OBIS` (attribute 2) on
every model whose catalog flag says ``supports_battery`` (ADR 0011). On the
first real install two of the three CEWE models — Prometer 100 and Saral 305 —
answered every hourly read with *"Device reports a undefined object"* while
Premier 550 read fine (ui-audit ticket 04). This script asks each unit the
same question the job asks, then walks the standard COSEM battery addresses
(``0.0.96.6.0–6.255``: use-time counter, charge display, next-change date,
voltage, …) as both a Data and a Register object, so the answer is "absent
on this unit" or "present under a different object", not a guess.

**The primary target comes from the driver module, never from a literal
here** — the same rule ``probe_lp_new_column_scalers.py`` follows — so this
script cannot go stale against what the product actually reads.

One association per meter, attribute reads only, then disconnect. Nothing is
ever written to a meter (CLAUDE.md invariant). The password is a command-line
argument and is never printed.

Usage, from ``app/``::

    PYTHONPATH=src .venv/Scripts/python.exe scripts/probe_battery.py \\
        --model prometer100 --host 203.170.151.152 --port 4059 --password <operator-supplied>
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from gurux_dlms.objects import GXDLMSData, GXDLMSRegister

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms import CEWE_BATTERY_STATUS_OBIS
from arichds.acquisition.drivers.factory import create_driver, supported_models

#: COSEM Blue Book "battery" group (C=96, D=6): E=0 use-time counter, E=1
#: charge display, E=2 date of next change, E=3 voltage, E=4–6 vendor use.
CANDIDATES: tuple[str, ...] = tuple(f"0.0.96.6.{e}.255" for e in range(7))


def read_attr(driver: Any, obis: str, cosem_class: type, attr: int) -> str:
    """One attribute read, rendered as a printable verdict — a refusal is a
    result here, not a crash."""
    obj = cosem_class(obis)
    driver._client.objects.append(obj)  # noqa: SLF001 — the driver's own reader, read-only
    try:
        value = driver._reader.read(obj, attr)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        return f"DENIED ({type(exc).__name__}: {exc})"
    return f"{type(value).__name__} {value!r}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only battery-register probe.")
    parser.add_argument("--host", required=True, help="Meter IP address")
    parser.add_argument("--port", type=int, default=4059, help="Meter TCP port (default 4059)")
    parser.add_argument("--password", default="", help="DLMS password (never printed)")
    parser.add_argument("--model", default="prometer100", help=f"One of: {', '.join(supported_models())}")
    args = parser.parse_args()

    if args.model.lower() not in supported_models():
        print(f"!! unknown model {args.model!r} — one of: {', '.join(supported_models())}")
        return 2

    driver = create_driver(args.model, ConnectionParams.net(args.host, args.port), password=args.password)
    print(f"[*] {args.model} @ {args.host}:{args.port} — connecting (read-only, one association)")
    driver.connect()
    try:
        print(f"[+] meter serial: {driver.read_meter_serial()}")
        print(f"[+] supports_battery(): {driver.supports_battery()}")
        print(f"\n=== the product's own read: read_battery_status() -> {CEWE_BATTERY_STATUS_OBIS} attr 2 ===")
        try:
            print(f"  {driver.read_battery_status()!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"  DENIED ({type(exc).__name__}: {exc})")

        print("\n=== the standard battery group, every object shape ===")
        for obis in CANDIDATES:
            print(f"{obis}")
            print(f"  as Data     attr 2 -> {read_attr(driver, obis, GXDLMSData, 2)}")
            print(f"  as Register attr 3 -> {read_attr(driver, obis, GXDLMSRegister, 3)}")
            print(f"  as Register attr 2 -> {read_attr(driver, obis, GXDLMSRegister, 2)}")
    finally:
        driver.disconnect()
        print("[*] disconnected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
