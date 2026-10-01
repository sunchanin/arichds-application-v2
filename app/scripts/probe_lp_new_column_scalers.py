"""Read-only: will each load-profile column's scaler actually resolve on this meter?

For every column the chosen model's driver declares, this reports what the meter
answers at the column's **own** address and at each **sibling** the driver would
borrow from, and whether :func:`_read_scaler_unit` would accept any of them.

The question it answers is not "does the OBIS exist" —
``probe_capture_objects.py`` answers that. It is "will the multiplier resolve",
which needs BOTH the unit the meter declares AND the class/attribute the scaler
sits at. A column whose multiplier does not resolve stores NULL on every row
with nothing logged anywhere, which is how ``avg_geo_pf`` stayed empty for
87,000 rows (M13, issue 05).

**The targets come from the driver's own ``LOAD_PROFILE_COLUMN_MAP``, never from
a table in this file.** An earlier version of this script carried its own
hand-written list and went stale the moment the driver shipped different
siblings: it still tried the export columns' ``D=7`` siblings, which the meter
denies, and therefore reported two working columns as broken. Deriving the
targets means this script says what the product actually does, or it says
nothing.

One association, attribute reads only, then disconnect. Nothing is ever written
to a meter (CLAUDE.md invariant). The password is a command-line argument only.

Its 2026-09-09 output against the development Prometer 100 is recorded in
``docs/meter-notes/lp-new-columns-scan.md``, which is where the sibling and
class choices in ``prometer100.py``'s column map come from.

Usage, from ``app/``::

    PYTHONPATH=src .venv/Scripts/python.exe scripts/probe_lp_new_column_scalers.py \\
        --host 203.170.151.152 --port 4059 --password <supplied by the operator>

    ... --model premier550 --port 50001
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms_profile import _SCALER_ATTRIBUTE, LpColumn
from arichds.acquisition.drivers.factory import create_driver, supported_models


def read_scaler(driver: Any, obis: str, cosem_class: type) -> tuple[str, str]:
    """Return ``(unit, scaler)`` as printable strings; ``DENIED`` when the read
    fails. Reads the attribute that class carries ``scaler_unit`` at — 3 on a
    Register or Extended Register, 4 on a Demand Register — exactly as the
    driver does."""
    obj = cosem_class(obis)
    driver._client.objects.append(obj)  # noqa: SLF001
    try:
        driver._reader.read(obj, _SCALER_ATTRIBUTE[cosem_class])  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001 — a denial is a result here, not a crash
        return ("DENIED", type(exc).__name__)
    unit = obj.unit
    name = getattr(unit, "name", None) or str(unit)
    return (f"{name}({int(unit)})" if unit is not None else "None", str(obj.scaler))


def report_column(driver: Any, capture_obis: str, attr: int, column: LpColumn) -> bool:
    """Print one column's verdict. Returns True when it would resolve."""
    if column.passthrough:
        print(f"{column.field:22} {capture_obis:18} attr={attr}  passthrough — no scaler is read at all")
        return True

    attempts: list[tuple[str, type, tuple[str, str]]] = []
    candidates = [(capture_obis, column.capture_class), *column.scaler_siblings]
    resolved = False
    for obis, cosem_class in candidates:
        answer = read_scaler(driver, obis, cosem_class)
        attempts.append((obis, cosem_class, answer))
        unit, scaler = answer
        if unit.startswith(column.unit.name + "(") and scaler not in ("None", "-"):
            resolved = True
            break

    verdict = "OK" if resolved else f"NO SCALER (wants {column.unit.name}) -> NULL on every row"
    print(f"{column.field:22} {capture_obis:18} attr={attr}  wants {column.unit.name:20} {verdict}")
    for obis, cosem_class, (unit, scaler) in attempts:
        where = "own address" if obis == capture_obis else "sibling    "
        print(f"  {where} {obis:18} as {cosem_class.__name__:22} -> {unit} / {scaler}")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only load-profile scaler/unit probe.")
    parser.add_argument("--host", required=True, help="Meter IP address")
    parser.add_argument("--port", type=int, default=4059, help="Meter TCP port (default 4059)")
    parser.add_argument("--password", default="", help="DLMS password (never printed)")
    parser.add_argument("--model", default="prometer100", help=f"One of: {', '.join(supported_models())}")
    args = parser.parse_args()

    if args.model.lower() not in supported_models():
        print(f"!! unknown model {args.model!r} — one of: {', '.join(supported_models())}")
        return 2

    driver = create_driver(args.model, ConnectionParams.net(args.host, args.port), password=args.password)
    column_map = getattr(type(driver), "LOAD_PROFILE_COLUMN_MAP", {})
    if not column_map:
        print(f"!! {args.model} declares no load-profile columns — nothing to probe")
        return 2

    print(f"[*] {args.model} @ {args.host}:{args.port} — connecting (read-only, one association)")
    driver.connect()
    unresolved: list[str] = []
    try:
        print(f"[+] meter serial: {driver.read_meter_serial()}\n")
        for logger_id in sorted(column_map):
            print(f"=== Logger {logger_id} ({len(column_map[logger_id])} mapped columns) ===")
            for (capture_obis, attr), column in column_map[logger_id].items():
                if not report_column(driver, capture_obis, attr, column):
                    unresolved.append(f"logger {logger_id} {column.field}")
            print()
    finally:
        driver.disconnect()
        print("[*] disconnected")

    if unresolved:
        print(f"\n!! {len(unresolved)} column(s) would store NULL on every row: {', '.join(unresolved)}")
        return 1
    print("\n[+] every mapped column resolves a scaler on this meter")
    return 0


if __name__ == "__main__":
    sys.exit(main())
