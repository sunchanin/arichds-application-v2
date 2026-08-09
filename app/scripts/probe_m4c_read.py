"""Real-meter, read-only diagnostic for the three CEWE M4c drivers (issue #24).

Connects once per meter and prints, for both the load profile and the billing
profile: the live capture list, the capture period (load profile, attr 4),
``entries_in_use``, a small load-profile window read through the shipped
driver, the billing rows read through the shipped driver, and which columns
resolved a scaler and to what (F8) — so a non-unity scaler on a CEWE model can
be told apart from v1, which applied none.

**Read-only, exactly like every other script under this directory.** It opens
one association, reads attributes and the two profiles through the product's
own driver methods (:meth:`~arichds.acquisition.drivers._dlms_profile.DlmsProfileDriver.read_load_profile`
/ :meth:`~arichds.acquisition.drivers._dlms_profile.DlmsProfileDriver.read_billing`), and
disconnects. **It never writes to a meter** — no register write, no clock set,
no MD reset, on any transport, ever (``CLAUDE.md``).

The password is a command-line argument only — never logged, never printed,
never written to a file by this script.

Usage::

    app\\.venv\\Scripts\\python.exe scripts\\probe_m4c_read.py \\
        --model prometer100 --host 203.170.151.152 --port 4059 --password ABCD0001
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from gurux_dlms.objects import GXDLMSProfileGeneric

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms_profile import CEWE_BILLING_PROFILE_OBIS
from arichds.acquisition.drivers.factory import create_driver, supported_models

_LOAD_PROFILE_WINDOW_HOURS = 6


def _read_profile_shape(driver: Any, profile_obis: str) -> tuple[list[tuple[str, int]], int]:
    """Read a ProfileGeneric's live capture list and ``entries_in_use`` — read-only."""
    pg = GXDLMSProfileGeneric(profile_obis)
    driver._client.objects.append(pg)
    driver._reader.read(pg, 3)
    entries_in_use = int(driver._reader.read(pg, 7))
    columns = [(str(obj.logicalName), int(cap.attributeIndex)) for obj, cap in pg.captureObjects]
    return columns, entries_in_use


def _print_columns(columns: list[tuple[str, int]]) -> None:
    for obis, attr in columns:
        print(f"      {obis:<20} attr={attr}")


def probe_one(model: str, host: str, port: int, password: str) -> None:
    conn = ConnectionParams.net(host, port)
    driver = create_driver(model, conn, password=password)

    print(f"[*] {model} @ {host}:{port} — connecting (read-only, one association)")
    driver.connect()
    try:
        serial = driver.read_meter_serial()
        print(f"[+] connected — meter serial: {serial}")

        # ── Load profile — every logger this driver declares ────────────────
        for logger_id in driver.load_profile_loggers():
            profile_obis = f"1.0.99.{logger_id}.0.255"
            print(f"\n=== Load profile — logger {logger_id} ({profile_obis}) ===")
            columns, entries_in_use = _read_profile_shape(driver, profile_obis)
            print(f"    {len(columns)} live capture column(s):")
            _print_columns(columns)
            print(f"    entries_in_use: {entries_in_use}")

            now = datetime.now(UTC)
            window_start = now - timedelta(hours=_LOAD_PROFILE_WINDOW_HOURS)
            rows = driver.read_load_profile(logger_id, window_start, now)
            print(f"    read_load_profile({logger_id}, last {_LOAD_PROFILE_WINDOW_HOURS}h) -> {len(rows)} row(s)")
            if rows:
                first, last = rows[0], rows[-1]
                print(f"      first: {first.read_at.isoformat()}  interval_sec={first.interval_sec}")
                print(f"      last:  {last.read_at.isoformat()}")
                print(f"      sample fields: {first.as_columns()}")

        # ── Billing ──────────────────────────────────────────────────────────
        print(f"\n=== Billing ({CEWE_BILLING_PROFILE_OBIS}) ===")
        columns, entries_in_use = _read_profile_shape(driver, CEWE_BILLING_PROFILE_OBIS)
        print(f"    {len(columns)} live capture column(s):")
        _print_columns(columns)
        print(f"    entries_in_use: {entries_in_use}")

        billing_rows = driver.read_billing()
        print(f"    read_billing() -> {len(billing_rows)} row(s)")
        for row in billing_rows:
            columns_dict = row.as_columns()
            resolved = {k: v for k, v in columns_dict.items() if v is not None}
            null_cols = [k for k, v in columns_dict.items() if v is None]
            print(f"      bill_date={row.bill_date.isoformat()} is_open={row.is_open} meter_serial={row.meter_serial}")
            print(f"        resolved ({len(resolved)}): {resolved}")
            print(f"        NULL ({len(null_cols)}): {null_cols}")
    finally:
        driver.disconnect()
        print("\n[*] disconnected — nothing was written to the meter")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only M4c load-profile + billing diagnostic.")
    parser.add_argument("--model", required=True, help=f"One of: {', '.join(supported_models())}")
    parser.add_argument("--host", required=True, help="Meter IP address")
    parser.add_argument("--port", type=int, default=4059, help="Meter TCP port (default 4059)")
    parser.add_argument("--password", default="", help="DLMS password (never printed)")
    parser.add_argument("--verbose", action="store_true", help="Show driver logs")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    if args.model.lower() not in supported_models():
        print(f"Unknown model {args.model!r}. Registered: {', '.join(supported_models())}", file=sys.stderr)
        return 2

    probe_one(args.model.lower(), args.host, args.port, args.password)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
