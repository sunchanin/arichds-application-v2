"""Why will this meter not hand over its load profile? — a read-only field probe.

Written 2026-09-20 for a customer site (TC) where two CEWE meters — a Premier 550
and a Prometer 100, on different IPs — both answered every load-profile buffer
read with ``GXDLMSException: Access Error : Data Block Unavailable`` while
*everything else* worked: the association, the Meter Serial, the billing profile,
and the load profile's own attributes 3 and 4. The service log cannot say why,
because the failure is one exception string with three very different causes.

This script separates them. It is **read-only**: it opens one association, reads
attributes, asks for rows, and disconnects. It never writes to the meter — no
register write, no clock set, no MD reset — which is a product invariant
(CLAUDE.md), not a courtesy of this script.

What it asks each logger, in order, and what each answer rules out:

1. **attr 4 — capture period.** ``0`` means the profile is not logging at all.
   Then there is nothing to read and nothing for us to fix: the meter has to be
   configured at the meter.
2. **attr 7 — entries in use** and **attr 8 — capacity.** ``0`` entries is an
   empty buffer: a meter commissioned yesterday has nothing 90 days back, and
   several firmwares answer a selective read of an empty buffer with exactly the
   error above rather than with an empty list.
3. **one row by entry, full width.** The narrowest possible *real* read.
4. **one row by entry, Clock column only.** This test reads in **one direction
   only**, measured 2026-09-20 against the healthy lab Premier 550 (SS18197374):
   that meter answers a full-width row and *refuses* the one-column selection
   with the very same "Data Block Unavailable". So a narrow **success** while the
   full row fails proves the row is too wide for the firmware — the ceiling the
   SMW110's billing profile has at 43 columns
   (``docs/meter-notes/smw110w4-scan.md``), which the billing path already caps
   for, and ours to fix. A narrow **failure** proves nothing at all.
5. **rows by range** over the last few days, in **meter-local** time (the range
   selection is sent as-is, ``.claude/skills/gurux-dlms/patterns.md``). If entry
   reads work and only this fails, the meter refuses selective access by range —
   the SMW110 does — and the fix is an entry walk for this model.

It also prints the meter's own clock beside the PC's. A meter whose clock is far
from real time makes any range query miss, and that looks like "no data" from
every layer above.

Usage (from ``app/``)::

    .venv\\Scripts\\python.exe scripts\\probe_lp_buffer.py \\
        --host 10.100.91.1 --port 4059 --model premier550 --password <meter password>

A Prometer 100 behind a serial-to-TCP converter (``docs/issues/025``) adds
``--model prometer100 --framing hdlc``.

Frozen for a site that has no Python::

    .venv\\Scripts\\pyinstaller --onefile --name arichds-lp-probe \\
        --paths src scripts\\probe_lp_buffer.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from gurux_dlms.objects import GXDLMSClock, GXDLMSProfileGeneric

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms_profile import meter_local_to_utc_inverse
from arichds.acquisition.drivers.factory import create_driver, supported_models

#: The two load-profile Profile Generic objects, ported from v1 verbatim and the
#: same pair `_dlms_profile.py` builds its own OBIS from.
LOGGER_OBIS: dict[int, str] = {1: "1.0.99.1.0.255", 2: "1.0.99.2.0.255"}

CLOCK_OBIS = "0.0.1.0.0.255"

ATTR_BUFFER = 2
ATTR_CAPTURE_OBJECTS = 3
ATTR_CAPTURE_PERIOD = 4
ATTR_ENTRIES_IN_USE = 7
ATTR_PROFILE_ENTRIES = 8


def describe_exception(exc: BaseException) -> str:
    """``ClassName: message`` — the class alone is what the service log keeps,
    and the message is what it drops."""
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def read_attribute(driver: Any, obj: Any, attr: int, label: str, *, show_value: bool = True) -> tuple[Any, str | None]:
    """Read one attribute; return ``(value, None)`` or ``(None, failure)``.

    *show_value* is off for capture objects, whose value is a list of Gurux
    objects that prints as pages of ``<... at 0x...>`` and says nothing; the
    caller renders that list itself.
    """
    try:
        value = driver._reader.read(obj, attr)
    except Exception as exc:  # noqa: BLE001 — a diagnostic reports every failure, it never raises
        print(f"    {label:<28} FAILED  {describe_exception(exc)}")
        return None, describe_exception(exc)
    print(f"    {label:<28} {value if show_value else 'read'}")
    return value, None


def try_rows(label: str, call) -> tuple[list[Any] | None, str | None]:  # noqa: ANN001
    """Run one row read, printing what came back or why it did not."""
    try:
        rows = call() or []
    except Exception as exc:  # noqa: BLE001
        print(f"    {label:<28} FAILED  {describe_exception(exc)}")
        return None, describe_exception(exc)
    print(f"    {label:<28} {len(rows)} row(s)")
    if rows:
        first = rows[0]
        cells = len(first) if hasattr(first, "__len__") else "?"
        print(f"    {'':<28} first row: {cells} cell(s) - {str(first)[:110]}")
    return rows, None


def probe_logger(driver: Any, logger_id: int, days: int) -> dict[str, Any]:
    """Ask one logger the five questions above. Returns what was learned."""
    obis = LOGGER_OBIS[logger_id]
    print(f"=== Logger {logger_id}  ({obis}) ===")

    pg = GXDLMSProfileGeneric(obis)
    driver._client.objects.append(pg)

    found: dict[str, Any] = {"obis": obis, "columns": None, "period": None, "entries": None}

    _, capture_failure = read_attribute(driver, pg, ATTR_CAPTURE_OBJECTS, "attr 3 capture objects", show_value=False)
    captured = getattr(pg, "captureObjects", None) or []
    found["columns"] = len(captured) if captured else 0
    found["capture_failure"] = capture_failure
    if captured:
        print(f"    {'':<28} {len(captured)} column(s):")
        for obj, capture_def in captured:
            attr_index = getattr(capture_def, "attributeIndex", "?")
            print(f"    {'':<28}   {str(obj.logicalName):<22} attr={attr_index} class={int(obj.objectType)}")

    period, _ = read_attribute(driver, pg, ATTR_CAPTURE_PERIOD, "attr 4 capture period (s)")
    found["period"] = period
    entries, _ = read_attribute(driver, pg, ATTR_ENTRIES_IN_USE, "attr 7 entries in use")
    found["entries"] = entries
    read_attribute(driver, pg, ATTR_PROFILE_ENTRIES, "attr 8 capacity")

    # 3 — one row, full width, at both ends of the buffer. Entry 1 is the oldest
    #     row; the newest is where a meter that is logging right now must have
    #     something, so a buffer that answers one and not the other is worth
    #     seeing rather than averaging into "entry reads fail".
    _, found["entry_full_failure"] = try_rows(
        "oldest row by entry (full)", lambda: driver._reader.readRowsByEntry(pg, 1, 1)
    )
    newest = int(entries) if isinstance(entries, int) and entries > 1 else None
    if newest is not None:
        _, found["entry_newest_failure"] = try_rows(
            f"newest row by entry (#{newest})", lambda: driver._reader.readRowsByEntry(pg, newest, 1)
        )

    # 4 — one row, one column. Separates "too wide" from "refused" and from "empty".
    #     Driven through the client directly because the vendored reader exposes no
    #     column-restricted call; the packet handling is the reader's own.
    if captured:
        clock_column = [captured[0]]

        def narrow() -> Any:
            from gurux_dlms import GXReplyData

            data = driver._client.readRowsByEntry(pg, 1, 1, clock_column)
            reply = GXReplyData()
            driver._reader.readDataBlock(data, reply)
            return driver._client.updateValue(pg, ATTR_BUFFER, reply.value)

        _, found["entry_narrow_failure"] = try_rows("1 row by entry (1 column)", narrow)
    else:
        found["entry_narrow_failure"] = "not attempted — no capture objects"

    # 5 — by range, meter-local, a short window so an empty answer means "no rows
    #     in these days" rather than "no rows in 90 days".
    end_utc = datetime.now(UTC)
    start_utc = end_utc - timedelta(days=days)
    start_local = meter_local_to_utc_inverse(start_utc)
    end_local = meter_local_to_utc_inverse(end_utc)
    print(f"    {'range window (meter-local)':<28} {start_local:%Y-%m-%d %H:%M} to {end_local:%Y-%m-%d %H:%M}")
    _, found["range_failure"] = try_rows(
        f"rows by range (last {days}d)", lambda: driver._reader.readRowsByRange(pg, start_local, end_local)
    )

    print()
    return found


def verdict(logger_id: int, found: dict[str, Any]) -> None:
    """Say what this logger's answers mean, in the operator's terms."""
    period = found.get("period")
    entries = found.get("entries")
    print(f"Logger {logger_id}:")

    if found.get("capture_failure"):
        print("  The profile object itself could not be read. Check the password and the")
        print("  association level before reading anything else - nothing below is reliable.")
        return

    if period is not None and int(period) == 0:
        print("  CAPTURE PERIOD IS 0 - this profile is not logging. There is nothing stored")
        print("  to read, and nothing our software can do about it: the load profile has to")
        print("  be enabled on the meter itself.")
        return

    if entries is not None and int(entries) == 0:
        print("  THE BUFFER IS EMPTY (0 entries in use). A meter commissioned recently has")
        print("  nothing to give yet. Re-check after one or two capture periods; if it stays")
        print("  at 0 while the period is non-zero, logging is configured but not running.")
        return

    entry_full = found.get("entry_full_failure")
    entry_newest = found.get("entry_newest_failure")
    entry_narrow = found.get("entry_narrow_failure")
    range_failure = found.get("range_failure")
    entry_works = not entry_full or not entry_newest

    if entry_full and not entry_narrow:
        print("  THE ROW IS TOO WIDE for this firmware: one column comes back, the full row")
        print("  does not. This is ours to fix - the billing path already caps its read for")
        print(f"  exactly this reason. Report the column count ({found.get('columns')}) with this output.")
        return

    if not entry_works and range_failure:
        print("  EVERY buffer read was refused while the profile's own attributes read fine.")
        print("  The buffer is not readable through this association: either the firmware")
        print("  refuses attribute 2 of this profile, or it holds entries it will not return.")
        print("  Ask the meter's owner which association may read the load profile, and send")
        print("  this output. (A failed one-column read above proves nothing on its own - the")
        print("  healthy lab Premier 550 refuses that selection too.)")
        return

    if entry_works and range_failure:
        print("  ENTRY READS WORK, RANGE READS DO NOT. This meter refuses selective access by")
        print("  range, the way the SMW110 does. This is ours to fix - the model needs an")
        print("  entry walk instead of a date window.")
        return

    if entry_works and not range_failure:
        print("  Both read paths answered. If the product still stores nothing, the problem is")
        print("  above the driver - send this output together with the service log.")
        return

    print("  Mixed result - send this whole output; the combination is not one this script")
    print("  has a rule for.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Why a meter will not hand over its load profile (read-only diagnostic).",
    )
    parser.add_argument("--host", required=True, help="Meter IP address")
    parser.add_argument("--port", type=int, default=4059, help="Meter TCP port (default 4059)")
    parser.add_argument("--password", default="", help="DLMS password (never printed)")
    parser.add_argument("--model", default="premier550", help=f"One of: {', '.join(supported_models())}")
    parser.add_argument(
        "--framing",
        choices=["wrapper", "hdlc"],
        default=None,
        help="WRAPPER or HDLC over TCP, for a model that offers the choice (prometer100). "
        "HDLC is what a serial-to-TCP converter speaks. Default: the model's own.",
    )
    parser.add_argument("--days", type=int, default=2, help="Range-test window in days (default 2)")
    parser.add_argument("--loggers", default="1,2", help="Which loggers to ask (default 1,2)")
    parser.add_argument("--verbose", action="store_true", help="Show driver logs")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    if args.model.lower() not in supported_models():
        print(f"Unknown model {args.model!r}. Registered: {', '.join(supported_models())}", file=sys.stderr)
        return 2

    try:
        logger_ids = [int(part) for part in args.loggers.split(",") if part.strip()]
    except ValueError:
        print(f"--loggers takes a comma-separated list of numbers, got {args.loggers!r}", file=sys.stderr)
        return 2
    if any(logger_id not in LOGGER_OBIS for logger_id in logger_ids):
        print(f"--loggers accepts {sorted(LOGGER_OBIS)} - got {logger_ids}", file=sys.stderr)
        return 2

    conn = ConnectionParams.net(args.host, args.port, framing=args.framing)
    try:
        driver = create_driver(args.model, conn, password=args.password)
    except ValueError as exc:  # a framing this model does not offer
        print(str(exc).replace(chr(0x2014), "-"), file=sys.stderr)  # a cp1252 console cannot print the dash
        return 2

    print("ARICHDS load-profile probe - READ ONLY, nothing is written to the meter")
    print(f"target : {args.model} @ {args.host}:{args.port}  framing: {args.framing or 'model default'}")
    print(f"PC time: {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %z}")
    print()

    driver.connect()
    try:
        print("[+] associated")
        try:
            serial = driver.read_meter_serial()
            print(f"    {'Meter Serial':<28} {serial}")
        except Exception as exc:  # noqa: BLE001
            print(f"    {'Meter Serial':<28} FAILED  {describe_exception(exc)}")

        clock = GXDLMSClock(CLOCK_OBIS)
        driver._client.objects.append(clock)
        read_attribute(driver, clock, ATTR_BUFFER, "meter clock")
        print()

        results = {logger_id: probe_logger(driver, logger_id, args.days) for logger_id in logger_ids}

        print("=" * 72)
        print("WHAT THIS MEANS")
        print("=" * 72)
        for logger_id in logger_ids:
            verdict(logger_id, results[logger_id])
            print()
        print("Compare the column counts with the meters we have measured:")
        print("  Premier 550   Logger 1: 900 s / 7 columns    Logger 2: 900 s / 14 columns")
        print("  Prometer 100  Logger 1: 900 s / 25 columns   Logger 2: 300 s / 8 columns")
        print("  (docs/meter-notes/load-profile-capture-objects.md, read off real meters)")
    finally:
        driver.disconnect()
        print("\n[*] disconnected")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
