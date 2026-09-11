"""Read-only: do the eleven new columns come back non-NULL, and is the
borrowed export-power scaler right?

Runs the SHIPPED driver's `read_load_profile()` on both loggers and reports
per-column fill counts, then does the **cross-quantity check** issue 06's gate
requires: average power over an interval, times the interval length, against
the energy stored for that same interval.

That check matters because every scaler on the reference meter is 1.0. A
wrongly borrowed scaler therefore yields a plausible number rather than a
blank, and comparing a stored value against the register it came from would
prove only that it was copied faithfully. Energy and power arrive by different
routes — different OBIS, different COSEM class, different scaler sibling — so
agreement between them is evidence.

One association, reads only, disconnect. Never writes to a meter (CLAUDE.md).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.factory import create_driver

ELEVEN_LOGGER1 = (
    "phase_angle_a",
    "phase_angle_b",
    "phase_angle_c",
    "import_active_kw",
    "import_reactive_kvar",
    "export_active_kw",
    "export_reactive_kvar",
    "interval_status_flag",
)
ELEVEN_LOGGER2 = ("volt_l1_l2", "volt_l2_l3", "volt_l3_l1")

# The energy column each power column should agree with after multiplying by
# the interval length in hours.
CROSS_CHECK = (
    ("import_active_kw", "import_active_kwh"),
    ("export_active_kw", "export_active_kwh"),
    ("import_reactive_kvar", "import_reactive_kvarh"),
    ("export_reactive_kvar", "export_reactive_kvarh"),
)


def report(rows: list, fields: tuple[str, ...]) -> None:
    for field in fields:
        values = [getattr(r, field, None) for r in rows]
        filled = [v for v in values if v is not None]
        sample = ", ".join(repr(v) for v in filled[:3])
        print(f"  {field:22} {len(filled):3}/{len(values):3} non-NULL   {sample}")


def cross_check(rows: list) -> int:
    """Compare each power column against its energy counterpart.

    Reports **how many pairs were actually compared**, not just the error, and
    treats "nothing to compare" as a failure rather than a pass. Without that
    count the check is silently vacuous on a site that does not export: zero
    times an interval equals zero, so a wrongly borrowed scaler reports 0.00 %
    exactly as a correct one does. That is what happened on 2026-09-09 — both
    export rows read OK and neither proved anything.

    Returns the number of columns that could not be verified.
    """
    print()
    print("cross-quantity check — kW x interval_hours vs kWh, same interval:")
    bad = 0
    for power_field, energy_field in CROSS_CHECK:
        pairs = [
            (getattr(r, power_field), getattr(r, energy_field), r.interval_sec)
            for r in rows
            if getattr(r, power_field, None) is not None and getattr(r, energy_field, None) is not None
        ]
        if not pairs:
            print(f"  {power_field:22} no row carries both columns — CANNOT CHECK")
            bad += 1
            continue

        worst = 0.0
        compared = 0
        example = ""
        for power, energy, interval_sec in pairs:
            expected = power * (interval_sec / 3600.0)
            denom = max(abs(energy), abs(expected))
            if denom < 1e-9:
                continue  # zero against zero proves nothing — not counted
            compared += 1
            error = abs(expected - energy) / denom
            if error >= worst:
                worst = error
                example = f"{power!r} kW x {interval_sec / 3600:.4g} h = {expected!r} vs {energy!r}"

        if compared == 0:
            print(
                f"  {power_field:22} {len(pairs)} row(s) but every one is zero on both sides — VACUOUS, proves nothing"
            )
            bad += 1
            continue

        verdict = "OK" if worst <= 0.05 else "MISMATCH"
        if worst > 0.05:
            bad += 1
        print(
            f"  {power_field:22} {compared}/{len(pairs)} row(s) non-zero, worst error "
            f"{worst * 100:6.2f} %  {verdict}   {example}"
        )
    return bad


def main() -> int:
    p = argparse.ArgumentParser(description="Read-only check of the eleven M13 load-profile columns.")
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=4059)
    p.add_argument("--password", required=True)
    p.add_argument("--model", default="prometer100")
    p.add_argument("--hours", type=int, default=3)
    a = p.parse_args()

    end = datetime.now(UTC)
    start = end - timedelta(hours=a.hours)

    conn = ConnectionParams.net(a.host, a.port)
    driver = create_driver(a.model, conn, password=a.password)
    print(f"[*] {a.model} @ {a.host}:{a.port} — connecting (read-only, one association)")
    driver.connect()
    failures = 0
    try:
        print(f"[+] meter serial: {driver.read_meter_serial()}\n")

        rows1 = driver.read_load_profile(1, start, end)
        print(f"logger 1 — {len(rows1)} rows, interval {rows1[0].interval_sec if rows1 else '?'} s")
        report(rows1, ELEVEN_LOGGER1)
        if rows1:
            failures += cross_check(rows1)
            last = rows1[-1]
            print(f"\n  last row: read_at={last.read_at}  status={last.interval_status_flag!r}")
            print(f"            import_active_kw={last.import_active_kw!r} export_active_kw={last.export_active_kw!r}")

        if 2 in driver.load_profile_loggers():
            rows2 = driver.read_load_profile(2, start, end)
            print(f"\nlogger 2 — {len(rows2)} rows, interval {rows2[0].interval_sec if rows2 else '?'} s")
            report(rows2, ELEVEN_LOGGER2)
    finally:
        driver.disconnect()
        print("\n[*] disconnected")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
