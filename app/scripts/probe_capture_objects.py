"""Read the load-profile capture objects off a meter — Logger 1 and Logger 2.

Answers one design question that cannot be answered from a desk: **can Logger 1
and Logger 2 be merged into a single row per timestamp?**

SPEC §3.5 says load profile rows from both loggers merge on ``read_at``. v1 did
the opposite — it kept them as separate rows discriminated by a ``logger_id``
column — and v1's OBIS map shows why that is not obviously safe: several OBIS
codes differing only in their D value land on the *same* column
(``1.0.32.7.0.255`` and ``1.0.32.27.0.255`` are both average voltage L1), and a
v1 comment records that "Pro100 / Saral 550 Logger 2 use D=27 for the same
C-values". If both loggers on one meter capture the same quantity, merging them
silently overwrites one with the other.

Merging is safe only if **both** of these hold on the real meter:

1. the two loggers capture *disjoint* quantities, and
2. they share the same capture period, so their timestamps line up at all.

This script reads both and reports on each. It is **read-only**: it opens one
association, reads attributes 3 (capture objects) and 4 (capture period), and
disconnects. It writes nothing to the meter and nothing to the database.

Usage::

    app\\.venv\\Scripts\\python.exe scripts\\probe_capture_objects.py \\
        --host 10.0.0.5 --port 4059 --password ABCD0001

    # a model whose driver is registered; defaults to prometer100
    ... --model prometer100

The interesting target is a **CEWE Premier 550**, the one model SPEC §3.5 says
has a Logger 2. Running it against a single-logger meter is still useful — it
should report Logger 2 as absent, which is itself a data point.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from typing import Any

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.factory import create_driver, supported_models

# Profile Generic objects holding the load profile (ported from v1
# `src/constants.py` — LP_LOGGER1_OBIS / LP_LOGGER2_OBIS, verbatim).
LOGGER_OBIS: dict[int, str] = {
    1: "1.0.99.1.0.255",
    2: "1.0.99.2.0.255",
}

PROFILE_GENERIC_CLASS_ID = 7
ATTR_CAPTURE_OBJECTS = 3
ATTR_CAPTURE_PERIOD = 4


def quantity_key(obis: str) -> str:
    """Return the OBIS groups that identify *what* is measured, ignoring D.

    An OBIS code is ``A.B.C.D.E.F``. C is the quantity (32 = voltage L1),
    D is the processing method (7 = instantaneous/average, 27 and 29 = other
    averaging windows). Two codes that differ only in D are the same
    measurement recorded differently — and in v1's map they land on the same
    column. Collapsing D is therefore exactly the comparison that decides
    whether a merge would overwrite anything.
    """
    parts = obis.split(".")
    if len(parts) != 6:
        return obis
    a, b, c, _d, e, f = parts
    return f"{a}.{b}.{c}.*.{e}.{f}"


def read_logger(driver: Any, objects_by_ln: dict[str, Any], logger_id: int) -> dict[str, Any] | None:
    """Read one logger's capture objects and period, or None if absent."""
    obis = LOGGER_OBIS[logger_id]
    profile = objects_by_ln.get(obis)
    if profile is None:
        print(f"    not present in the association view ({obis})")
        return None
    if int(profile.objectType) != PROFILE_GENERIC_CLASS_ID:
        print(f"    {obis} is class {int(profile.objectType)}, not Profile Generic — skipping")
        return None

    period: int | None = None
    try:
        driver._reader.read(profile, ATTR_CAPTURE_PERIOD)
        period = getattr(profile, "capturePeriod", None)
    except Exception as exc:  # noqa: BLE001 — a diagnostic reports, it does not fail
        print(f"    capture period read failed: {exc}")

    try:
        driver._reader.read(profile, ATTR_CAPTURE_OBJECTS)
    except Exception as exc:  # noqa: BLE001
        print(f"    capture objects read failed: {exc}")
        return None

    captured = getattr(profile, "captureObjects", None)
    if not captured:
        print("    no capture objects reported")
        return None

    columns: list[tuple[str, Any, int]] = []
    for entry in captured:
        # Gurux hands back (GXDLMSObject, GXDLMSCaptureObject) pairs.
        obj, capture_def = entry
        columns.append((str(obj.logicalName), getattr(capture_def, "attributeIndex", "?"), int(obj.objectType)))

    print(f"    capture period: {period if period is not None else 'unknown'} s")
    print(f"    {len(columns)} captured column(s):")
    for logical_name, attr, class_id in columns:
        print(f"      {logical_name:<22} attr={attr} class={class_id}")

    return {"obis": obis, "period": period, "columns": columns}


def report_verdict(logger1: dict[str, Any] | None, logger2: dict[str, Any] | None) -> None:
    """Print what the two capture lists mean for the merge decision."""
    print("=" * 72)
    if logger1 is None:
        print("VERDICT: Logger 1 is unreadable — nothing to conclude. Check the")
        print("         password and the association level before reading anything else.")
        return
    if logger2 is None:
        print("VERDICT: this meter has only Logger 1.")
        print("         Merging is trivially safe here, but this meter does not settle")
        print("         the question — it has to be a model that HAS a Logger 2")
        print("         (SPEC §3.5 names the CEWE Premier 550).")
        return

    period1, period2 = logger1["period"], logger2["period"]
    if period1 is not None and period2 is not None and period1 != period2:
        print(f"VERDICT: MERGE IS NOT POSSIBLE — capture periods differ ({period1}s vs {period2}s).")
        print("         The two loggers do not share timestamps, so there is no")
        print("         common `read_at` to merge on. Keep v1's separate-row shape.")
        return

    by_quantity: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for logger_id, logger in ((1, logger1), (2, logger2)):
        for logical_name, _attr, _class_id in logger["columns"]:
            by_quantity[quantity_key(logical_name)][logger_id].append(logical_name)

    collisions = {key: sides for key, sides in by_quantity.items() if len(sides) > 1}

    if collisions:
        print(f"VERDICT: MERGE WOULD LOSE DATA — {len(collisions)} quantity/quantities are captured")
        print("         by BOTH loggers. Merging on read_at would overwrite one with")
        print("         the other. Either keep separate rows (v1's shape) or give the")
        print("         colliding quantities per-logger columns.")
        for key, sides in sorted(collisions.items()):
            detail = "  ".join(f"L{logger_id}={','.join(names)}" for logger_id, names in sorted(sides.items()))
            print(f"           {key:<22} {detail}")
    else:
        print("VERDICT: MERGE IS SAFE on this meter — the two loggers capture disjoint")
        print(f"         quantities and share a capture period ({period1}s).")
        print("         SPEC §3.5's one-row-per-(device, read_at) shape holds.")

    print()
    print("Either way, record which meter model and firmware this came from — the")
    print("answer is a property of the model, not of the product.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read Logger 1 / Logger 2 capture objects (read-only).")
    parser.add_argument("--host", required=True, help="Meter IP address")
    parser.add_argument("--port", type=int, default=4059, help="Meter TCP port (default 4059)")
    parser.add_argument("--password", default="", help="DLMS password (never printed)")
    parser.add_argument("--model", default="prometer100", help=f"One of: {', '.join(supported_models())}")
    parser.add_argument("--verbose", action="store_true", help="Show driver logs")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    if args.model.lower() not in supported_models():
        print(f"Unknown model {args.model!r}. Registered: {', '.join(supported_models())}", file=sys.stderr)
        return 2

    conn = ConnectionParams.net(args.host, args.port)
    driver = create_driver(args.model, conn, password=args.password)

    print(f"[*] {args.model} @ {args.host}:{args.port} — connecting (read-only, one association)")
    driver.connect()
    try:
        print("[+] connected — reading the association view")
        driver._reader.getAssociationView()
        objects_by_ln = {str(obj.logicalName): obj for obj in driver._client.objects}
        profiles = [obj for obj in driver._client.objects if int(obj.objectType) == PROFILE_GENERIC_CLASS_ID]
        print(f"[+] {len(objects_by_ln)} objects, {len(profiles)} Profile Generic\n")

        results: dict[int, dict[str, Any] | None] = {}
        for logger_id in (1, 2):
            print(f"=== Logger {logger_id} ({LOGGER_OBIS[logger_id]}) ===")
            results[logger_id] = read_logger(driver, objects_by_ln, logger_id)
            print()

        report_verdict(results[1], results[2])
    finally:
        driver.disconnect()
        print("\n[*] disconnected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
