"""Field probe: validate **v2's own** load-profile read path against a live SMW110W4.

This is the second SMW110W4 probe and it differs from the first one in the way
that matters. ``probe_smw110_serial.py`` built its own DLMS argv and did its own
parsing, because when it was written v2 had no driver for this model — so it
proved facts about the *meter*, not about our code. Issue #10 shipped
``Smw110Driver.read_load_profile()``, so this script **imports that driver and
calls it**. Every number below comes out of the code that will be installed. If
this passes, the shipped read path passes; if it fails, the shipped read path
fails. A reimplementation here would prove nothing.

It is a diagnostic, not part of the product: nothing imports it, and it is not
wired into the app.

What it answers — the eight questions replaying recorded rows cannot:

  1. Does a time window turn into the right rows on a buffer that is *moving*?
     The recorded probe replays a fixed list; the real ring advances every 900 s
     and the entry arithmetic is where an off-by-one hides.
  2. Is the same window stable when asked twice?
  3. Does a wide window contain a narrow one, value-for-value?
  4. Does a window outside the buffer return nothing — not an error, not junk?
  5. Are the returned ``read_at`` values unique and evenly spaced? **M5 intends
     to make ``(device_id, logger_id, read_at)`` a unique key.** If this meter
     ever repeats or skews a timestamp, that design breaks on insert, and it is
     far cheaper to learn it here.
  6. Is the meter's clock really ICT? ``METER_LOCAL_UTC_OFFSET_HOURS`` is a
     hardcoded 7 and a site outside ICT silently shifts every row.
  7. Does the live schema still match the scan (20 columns / 900 s / 8640)?
  8. Is Logger 2 still absent, so the ``logger_id`` design keeps its evidence?

**Read-only.** It opens an association, reads, and disconnects. It never writes
to the meter, and it never writes to any database.

The meter password is a command-line argument. It is never printed and never
written to the report file.

Usage (the built exe takes the same arguments):

    probe_lp_smw110.exe --host 192.168.1.31 --port 4059 --password SECRET
    probe_lp_smw110.exe --serial COM4 --password SECRET
    probe_lp_smw110.exe --list-ports

Build (from ``app/``; the vendored Gurux modules import each other by bare name,
which is why they need --paths and explicit hidden imports):

    .venv\\Scripts\\pyinstaller.exe --onefile --console ^
        --paths src --paths src/arichds/vendor/gurux ^
        --hidden-import GXSettings --hidden-import GXDLMSReader ^
        --hidden-import GXDLMSSecureClient2 --hidden-import GXCmdParameter ^
        scripts/probe_lp_smw110.py
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Allow running straight from a checkout without installing the package. When
# frozen by PyInstaller the package is bundled and there is no src/ next to us.
if not getattr(sys, "frozen", False):
    _SRC = Path(__file__).resolve().parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))

from gurux_dlms.objects import GXDLMSClock, GXDLMSProfileGeneric  # noqa: E402

from arichds.acquisition.connection_params import ConnectionParams  # noqa: E402
from arichds.acquisition.drivers.base import IntervalReading  # noqa: E402
from arichds.acquisition.drivers.smw110 import LOAD_PROFILE_OBIS, Smw110Driver  # noqa: E402
from arichds.constants import METER_LOCAL_UTC_OFFSET_HOURS  # noqa: E402

#: Logger 2. Both units answered "undefined object" on 2026-08-07; re-checked so
#: the ``logger_id`` design keeps a dated fact behind it rather than a memory.
LOGGER_2_OBIS = "1.0.99.2.0.255"

#: The meter clock, read as a Clock object rather than a Register.
CLOCK_OBIS = "0.0.1.0.0.255"

#: What the 2026-08-07 scan recorded. Deviations are reported, never asserted —
#: the meter is the authority and a changed schema is a finding, not a crash.
EXPECTED_COLUMNS = 20
EXPECTED_PERIOD_SEC = 900
EXPECTED_ENTRIES = 8640


class Report:
    """Write every line to the console and to the report file at once.

    Output is deliberately ASCII-only: a Windows console defaults to cp1252 and
    raises UnicodeEncodeError on anything else, which would abort the probe at
    the print rather than at the meter. Every line is flushed, so a link that
    dies mid-run still leaves a readable file.
    """

    def __init__(self, path: Path) -> None:
        self._fh = path.open("w", encoding="utf-8", newline="\n")

    def __call__(self, line: str = "") -> None:
        print(line)
        self._fh.write(line + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def describe_ports() -> list[str]:
    """Return one human line per serial port this machine can see."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return ["(pyserial not available - cannot enumerate ports)"]
    found = sorted(list_ports.comports(), key=lambda p: p.device)
    if not found:
        return ["(no serial ports found on this machine)"]
    return [f"{p.device}  {p.description}" for p in found]


def fmt(value: Any) -> str:
    """Format a measurement for the report without lying about precision."""
    if value is None:
        return "None"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def row_line(reading: IntervalReading) -> str:
    """One buffer row as a fixed-width line."""
    return (
        f"    {reading.read_at.isoformat()}"
        f"  kwh={fmt(reading.import_active_kwh):>10}"
        f"  V={fmt(reading.volt_l1):>8}/{fmt(reading.volt_l2):>8}/{fmt(reading.volt_l3):>8}"
        f"  A={fmt(reading.current_l1):>8}/{fmt(reading.current_l2):>8}/{fmt(reading.current_l3):>8}"
        f"  freq={fmt(reading.freq)}"
    )


def read_profile_attr(driver: Smw110Driver, obis: str, attr: int) -> Any:
    """Read one ProfileGeneric attribute through the driver's own reader.

    The driver does not expose the profile attributes — it reads them inside
    ``read_load_profile`` and keeps them. A probe reaching for ``_reader`` is
    acceptable here and nowhere else: this file is a diagnostic, and the point
    is to see what the driver sees.
    """
    pg = GXDLMSProfileGeneric(obis)
    driver._client.objects.append(pg)  # noqa: SLF001 - diagnostic, see docstring
    return driver._reader.read(pg, attr)  # noqa: SLF001


def check_identity(report: Report, driver: Smw110Driver) -> None:
    """Confirm which physical meter answered, so the report is attributable."""
    report("[1] IDENTITY")
    serial = driver.read_meter_serial()
    report(f"    meter serial (1.0.199.128.134.255) : {serial}")
    report(f"    model string (0.0.96.1.1.255)      : {driver.read_register('0.0.96.1.1.255')}")
    report("    NOTE: 0.0.96.1.0.255 answers the placeholder 99999999 on this model")
    report("          and is never the serial (scan 2026-08-07).")
    report()


def check_schema(report: Report, driver: Smw110Driver) -> None:
    """Read capture objects, period and entries-in-use live, and compare to the scan."""
    report("[2] LIVE SCHEMA vs THE 2026-08-07 SCAN")
    capture = read_profile_attr(driver, LOAD_PROFILE_OBIS, 3)
    period = read_profile_attr(driver, LOAD_PROFILE_OBIS, 4)
    entries = read_profile_attr(driver, LOAD_PROFILE_OBIS, 7)

    n_cols = len(capture) if capture is not None else 0
    report(f"    capture objects (attr 3) : {n_cols:>6}   expected {EXPECTED_COLUMNS}")
    report(f"    capture period  (attr 4) : {period!s:>6} s expected {EXPECTED_PERIOD_SEC} s")
    report(f"    entries in use  (attr 7) : {entries!s:>6}   expected {EXPECTED_ENTRIES}")

    for label, got, want in (
        ("columns", n_cols, EXPECTED_COLUMNS),
        ("period", period, EXPECTED_PERIOD_SEC),
        ("entries", entries, EXPECTED_ENTRIES),
    ):
        if got != want:
            report(f"    !! {label} CHANGED since the scan: {got} (was {want})")
            report("       This is a finding, not a failure - the meter is the authority.")
    report()


def check_clock(report: Report, driver: Smw110Driver) -> None:
    """Compare the meter's clock to this host's, and check the hardcoded offset."""
    report("[3] METER CLOCK vs HOST CLOCK")
    clock = GXDLMSClock(CLOCK_OBIS)
    driver._client.objects.append(clock)  # noqa: SLF001 - diagnostic
    meter_time = driver._reader.read(clock, 2)  # noqa: SLF001
    host_local = datetime.now()
    host_utc = datetime.now(UTC)

    raw = getattr(meter_time, "value", meter_time)
    report(f"    meter clock        : {raw}")
    report(f"    host local clock   : {host_local.isoformat(timespec='seconds')}")
    report(f"    host UTC clock     : {host_utc.isoformat(timespec='seconds')}")
    report(f"    v2 assumes the meter runs UTC+{METER_LOCAL_UTC_OFFSET_HOURS} (constants.py)")

    if isinstance(raw, datetime):
        implied = round((raw.replace(tzinfo=UTC) - host_utc).total_seconds() / 3600)
        report(f"    implied meter offset from UTC : +{implied} h")
        if implied != METER_LOCAL_UTC_OFFSET_HOURS:
            report(f"    !! MISMATCH - every stored read_at would be off by {implied - METER_LOCAL_UTC_OFFSET_HOURS} h")
            report("       Do NOT install until this is resolved.")
    else:
        report("    (clock did not come back as a datetime - cannot compute the offset)")
    report()


def fetch(
    report: Report, driver: Smw110Driver, label: str, start: datetime, end: datetime, show: int = 4
) -> list[IntervalReading]:
    """Call the shipped read path for one window and print what came back."""
    report(f"    {label}")
    report(f"      window : {start.isoformat()}  ->  {end.isoformat()}")
    # This model has one logger (D2, issue #24) — [0] is always Logger 1.
    rows = driver.read_load_profile(driver.load_profile_loggers()[0], start, end)
    report(f"      rows   : {len(rows)}")
    for reading in rows[:show]:
        report(row_line(reading))
    if len(rows) > show * 2:
        report(f"      ... {len(rows) - show * 2} more ...")
    for reading in rows[max(show, len(rows) - show) :]:
        report(row_line(reading))
    return rows


def check_windows(report: Report, driver: Smw110Driver) -> list[IntervalReading]:
    """Questions 1-4: the arithmetic that only a moving buffer can test."""
    now = datetime.now(UTC)

    report("[4] WINDOW -> ROWS  (the entry arithmetic, on a buffer that is moving)")
    narrow_start, narrow_end = now - timedelta(hours=2), now
    narrow = fetch(report, driver, "A. last 2 hours", narrow_start, narrow_end)
    expected = 8
    report(f"      expected about {expected} rows at 900 s; got {len(narrow)}")
    if not narrow:
        report("      !! EMPTY - either the window maths is wrong or the meter stopped logging.")
    report()

    report("[5] SAME WINDOW TWICE  (is it stable, or does it drift with call time?)")
    again = fetch(report, driver, "A again", narrow_start, narrow_end, show=2)
    same = [r.read_at for r in narrow] == [r.read_at for r in again]
    report(f"      identical timestamps : {same}")
    if not same:
        report("      !! NOT STABLE - two identical requests returned different rows.")
        report("         M5's dedup would write duplicates or lose rows.")
    report()

    report("[6] WIDE WINDOW CONTAINS THE NARROW ONE  (off-by-one in start/count)")
    wide = fetch(report, driver, "B. last 6 hours", now - timedelta(hours=6), now, show=3)
    by_time = {r.read_at: r for r in wide}
    missing = [r.read_at for r in narrow if r.read_at not in by_time]
    differing = [
        r.read_at for r in narrow if r.read_at in by_time and by_time[r.read_at].as_columns() != r.as_columns()
    ]
    report(f"      narrow rows absent from the wide window : {len(missing)}")
    report(f"      narrow rows whose values differ         : {len(differing)}")
    if missing or differing:
        report("      !! The two windows disagree about the same instants.")
        for stamp in (missing + differing)[:5]:
            report(f"         {stamp.isoformat()}")
    report()

    report("[7] WINDOWS OUTSIDE THE BUFFER  (must be empty, not an error)")
    logger_id = driver.load_profile_loggers()[0]
    future = driver.read_load_profile(logger_id, now + timedelta(days=1), now + timedelta(days=2))
    report(f"      one day in the future : {len(future)} rows   (expected 0)")
    ancient = driver.read_load_profile(logger_id, datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 1, 2, tzinfo=UTC))
    report(f"      January 2020          : {len(ancient)} rows   (expected 0)")
    if future or ancient:
        report("      !! Rows returned for a window the buffer cannot cover.")
    report()

    return wide


def check_timestamps(report: Report, rows: list[IntervalReading]) -> None:
    """Question 5 - the one that decides whether M5's unique key is safe."""
    report("[8] read_at SPACING AND UNIQUENESS  (M5's unique key depends on this)")
    if len(rows) < 2:
        report("      too few rows to judge - skipped")
        report()
        return

    stamps = [r.read_at for r in rows]
    duplicates = [s for s, n in Counter(stamps).items() if n > 1]
    report(f"      rows            : {len(stamps)}")
    report(f"      distinct stamps : {len(set(stamps))}")
    report(f"      duplicates      : {len(duplicates)}")
    if duplicates:
        report("      !! DUPLICATE TIMESTAMPS - a unique key on (device, logger, read_at)")
        report("         would reject real rows. M5's storage design must change.")
        for stamp in duplicates[:5]:
            report(f"         {stamp.isoformat()}")

    ordered = sorted(stamps)
    # zip() must NOT be strict here: pairing a list with its own tail is one
    # element shorter by construction. strict=True raised and killed the run.
    gaps = Counter(int((b - a).total_seconds()) for a, b in zip(ordered, ordered[1:], strict=False))
    report("      gaps between consecutive rows (seconds -> count):")
    for seconds, count in sorted(gaps.items()):
        marker = "" if seconds == EXPECTED_PERIOD_SEC else "   <-- not the capture period"
        report(f"        {seconds:>6} s : {count}{marker}")
    if len(gaps) > 1:
        report("      NOTE: more than one gap size. Either the meter skipped intervals")
        report("            (a real data gap) or the window maths dropped rows.")
    report(f"      ascending order as returned : {stamps == ordered}")
    report()


def check_logger_2(report: Report, driver: Smw110Driver) -> None:
    """Question 8 - re-confirm the absence the logger_id design rests on."""
    report("[9] LOGGER 2")
    try:
        entries = read_profile_attr(driver, LOGGER_2_OBIS, 7)
    except Exception as exc:  # noqa: BLE001 - the exception IS the finding
        report(f"    {LOGGER_2_OBIS} -> {type(exc).__name__}: {exc}")
        report("    Expected: 'undefined object'. This model has one logger, which is why")
        report("    logger_id cannot be exercised for real until M4c (Prometer 100 / Premier 550).")
    else:
        report(f"    !! {LOGGER_2_OBIS} ANSWERED: entries in use = {entries}")
        report("    This contradicts the 2026-08-07 scan. Logger 2 exists after all -")
        report("    M5 can and must exercise logger_id on this meter.")
    report()


def build_connection(args: argparse.Namespace) -> ConnectionParams:
    """Build the same ConnectionParams the product builds for this device."""
    if args.serial:
        return ConnectionParams.serial(args.serial, baud_rate=args.baud)
    return ConnectionParams.net(args.host, args.port)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate v2's load-profile read path against a live SMW110W4.",
    )
    parser.add_argument("--host", help="TCP host of the meter, e.g. 192.168.1.31")
    parser.add_argument("--port", type=int, default=4059, help="TCP port (default 4059)")
    parser.add_argument("--serial", help="Serial port, e.g. COM4")
    parser.add_argument("--baud", type=int, default=19200, help="Serial baud (default 19200)")
    parser.add_argument("--password", help="DLMS Low-auth password. Never printed or written.")
    parser.add_argument("--out", help="Report file (default: next to the exe, timestamped)")
    parser.add_argument("--list-ports", action="store_true", help="List serial ports and exit")
    args = parser.parse_args()

    if args.list_ports:
        print("Serial ports on this machine:")
        for line in describe_ports():
            print(f"  {line}")
        return 0

    if bool(args.serial) == bool(args.host):
        parser.error("give exactly one of --serial COM4 or --host <ip>")
    if not args.password:
        parser.error("--password is required")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else Path.cwd() / f"lp-probe-{stamp}.txt"
    report = Report(out)

    conn = build_connection(args)
    driver = Smw110Driver(conn, args.password)

    report("=" * 78)
    report("ARICHDS v2 - LOAD PROFILE READ PATH, AGAINST A LIVE METER")
    report("=" * 78)
    report(f"started        : {datetime.now().isoformat(timespec='seconds')}")
    report(f"endpoint       : {conn.endpoint}")
    report(f"transport      : {conn.connection_type.value}")
    report("code under test: arichds.acquisition.drivers.smw110.Smw110Driver.read_load_profile")
    report("                 (the shipped driver, imported - not a reimplementation)")
    report("read-only      : nothing is written to the meter or to any database")
    report()
    report("Serial ports visible from this machine:")
    for line in describe_ports():
        report(f"  {line}")
    report()

    failed = False
    try:
        report("connecting ...")
        driver.connect()
        report("connected.")
        report()

        # Each check is isolated. The first run of this probe crashed inside
        # check_timestamps and took check_logger_2 down with it, losing a fact
        # the meter had already been asked for. One broken check must cost one
        # block of the report, never the trip to site.
        wide: list[IntervalReading] = []
        for name, run in (
            ("[1] identity", lambda: check_identity(report, driver)),
            ("[2] schema", lambda: check_schema(report, driver)),
            ("[3] clock", lambda: check_clock(report, driver)),
            ("[4-7] windows", lambda: wide.extend(check_windows(report, driver))),
            ("[8] timestamps", lambda: check_timestamps(report, wide)),
            ("[9] logger 2", lambda: check_logger_2(report, driver)),
        ):
            try:
                run()
            except Exception as exc:  # noqa: BLE001 - one bad check, not one bad run
                failed = True
                report(f"    !! {name} FAILED: {type(exc).__name__}: {exc}")
                for line in traceback.format_exc().splitlines():
                    report(f"       {line}")
                report()

    except Exception as exc:  # noqa: BLE001 - a probe reports failures, it does not raise them
        failed = True
        report()
        report("!! PROBE FAILED")
        report(f"   {type(exc).__name__}: {exc}")
        report()
        for line in traceback.format_exc().splitlines():
            report(f"   {line}")
        report()
        report("   If this is WinError 2, the COM port in --serial does not exist on this")
        report("   machine - run with --list-ports and use one of the ports it prints.")
        report("   If this is WinError 5, the port exists but something else holds it open")
        report("   (the vendor tool, or another copy of this probe).")
        report("   If this is a timeout on --host, the meter is not reachable from here.")
    finally:
        driver.disconnect()
        report("disconnected.")
        report()
        report("=" * 78)
        report(f"report written to: {out}")
        report("=" * 78)
        report.close()

    print()
    print(f"Send this file back: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
