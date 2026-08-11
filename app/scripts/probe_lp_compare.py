"""Compare the shipped SMW110W4 load-profile read against the vendor's own export.

Every earlier diagnostic on this model compared our numbers against **the meter's
own registers** - which cannot detect an error the meter and we share. The CT/VT
ratio is exactly that kind of error: `0.0.96.51.1.255` ("Multiply Factor of
energy and Demand") reads **40** on this site, so a value that is internally
consistent end to end can still be 40x away from what the customer's world
calls correct. Only an outside source settles it.

This script takes the Mitsubishi tool's own CSV export as that outside source,
reads the same intervals off the meter through the **shipped driver**, joins
them on timestamp, and reports the ratio per column. A column whose ratio is a
clean constant across every matched interval is telling you the size of a
systematic factor; a column whose ratio is 1.0 is correct.

Reading the vendor CSV
----------------------
The export is sectioned. Two sections matter, and they must be joined on
``Entry No.`` because neither carries all the columns:

* ``----LP Data:Demand & Energy----`` - ``Energy Wh(imp)``, declared ``Unit:Wh``
* ``----LP Data:PQM----`` - ``Voltage A/B/C``, ``Current A/B/C``

Timestamps in the export are **meter-local** (ICT, UTC+7 - the same assumption
:func:`~arichds.acquisition.drivers._profile.meter_local_to_utc` encodes) in
``DD/MM/YYYY`` form. ``24:00:00`` appears for the interval that closes at
midnight and is normalised to ``00:00:00`` of the following day rather than
dropped, because dropping it would silently lose one interval per day.

**Read-only.** One association, reads the load profile through the driver's own
``read_load_profile()``, disconnects. It never writes to a meter (``CLAUDE.md``).
The password is a command-line argument only.

Usage::

    probe_lp_compare.exe --host 192.168.1.31 --password <supplied by the operator> \\
        --csv reading_01232002892_20260811092503.csv --hours 48
"""

from __future__ import annotations

import argparse
import csv
import logging
import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._profile import meter_local_to_utc
from arichds.acquisition.drivers.factory import create_driver

_MODEL = "smw110"

#: Our ``IntervalReading`` field -> the vendor CSV column that holds the same
#: quantity, and the factor that puts the vendor's value into OUR unit. The
#: vendor exports energy in Wh (``Unit:Wh/varh`` in its own header) while
#: ``IntervalReading.import_active_kwh`` is kWh, so that one column carries a
#: unit conversion; the electrical columns are already in V and A on both sides.
_COMPARISONS: dict[str, tuple[str, float]] = {
    "import_active_kwh": ("Energy Wh(imp)", 0.001),
    "volt_l1": ("Voltage A", 1.0),
    "volt_l2": ("Voltage B", 1.0),
    "volt_l3": ("Voltage C", 1.0),
    "current_l1": ("Current A", 1.0),
    "current_l2": ("Current B", 1.0),
    "current_l3": ("Current C", 1.0),
}

#: Ratios worth naming when one shows up, so a reader does not have to recognise
#: 0.025 by eye. Keyed on the ratio OUR value has to the vendor's.
_KNOWN_RATIOS: dict[float, str] = {
    1.0: "match",
    0.025: "we are 40x LOW - the CT/VT Multiply Factor (0.0.96.51.1.255)",
    40.0: "we are 40x HIGH",
    0.001: "we are 1000x LOW - a Wh/kWh step",
    1000.0: "we are 1000x HIGH - a Wh/kWh step",
}


class Report:
    """Console + file at once, ASCII only - same shape as the other probes here."""

    def __init__(self, path: Path) -> None:
        self._fh = path.open("w", encoding="utf-8", newline="\n")

    def __call__(self, line: str = "") -> None:
        print(line)
        self._fh.write(line + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def _parse_local_stamp(date_text: str, time_text: str) -> datetime | None:
    """``DD/MM/YYYY`` + ``HH:MM:SS`` (meter-local) -> naive local datetime.

    ``24:00:00`` is the interval closing at midnight; it belongs to 00:00 of the
    next day. Returning ``None`` for anything unparseable keeps a malformed line
    from aborting a comparison over thousands of good ones.
    """
    date_text, time_text = date_text.strip(), time_text.strip()
    rolls_over = time_text.startswith("24:")
    if rolls_over:
        time_text = "00" + time_text[2:]
    for date_format in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            stamp = datetime.strptime(f"{date_text} {time_text}", f"{date_format} %H:%M:%S")
        except ValueError:
            continue
        return stamp + timedelta(days=1) if rolls_over else stamp
    return None


def _read_vendor_csv(path: Path, out: Report) -> dict[datetime, dict[str, float]]:
    """Parse both LP sections of the vendor export into ``{utc_stamp: {column: value}}``.

    The two sections are merged on their timestamp rather than on ``Entry No.``
    - the entry numbering restarts per section in some exports, while the
    timestamp is what both sections agree on and what we have to join to the
    meter read by anyway.
    """
    merged: dict[datetime, dict[str, float]] = defaultdict(dict)
    section: str | None = None
    header: list[str] | None = None
    wanted = {vendor_column for vendor_column, _factor in _COMPARISONS.values()}

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for fields in csv.reader(fh):
            if not fields:
                continue
            first = fields[0].strip()

            if first.startswith("----") or first.startswith("===="):
                section = first.strip("-= ").strip()
                header = None
                continue
            if section not in ("LP Data:Demand & Energy", "LP Data:PQM"):
                continue
            if first == "Entry No.":
                header = [f.strip() for f in fields]
                continue
            if header is None or len(fields) < 4:
                continue

            local = _parse_local_stamp(fields[1], fields[2])
            if local is None:
                continue
            stamp = meter_local_to_utc(local)

            for index, name in enumerate(header):
                if name not in wanted or index >= len(fields):
                    continue
                text = fields[index].strip()
                if not text or text.upper() == "N/A":
                    continue
                try:
                    merged[stamp][name] = float(text)
                except ValueError:
                    continue

    out(f"[*] vendor CSV: {len(merged)} interval(s) parsed from {path.name}")
    return merged


def _ratio_label(ratio: float) -> str:
    """Name a ratio when it is one of the ones that mean something."""
    for known, label in _KNOWN_RATIOS.items():
        if known * 0.98 <= ratio <= known * 1.02:
            return label
    return ""


def compare(
    conn: ConnectionParams,
    password: str,
    vendor: dict[datetime, dict[str, float]],
    hours: int,
    out: Report,
) -> None:
    """Read the meter over *hours* and report per-column ratios - read-only."""
    driver = create_driver(_MODEL, conn, password=password)

    out(f"[*] {_MODEL} @ {conn.endpoint} - connecting (read-only, one association)")
    driver.connect()
    try:
        out(f"[+] connected - meter serial: {driver.read_meter_serial()}")

        now = datetime.now(UTC)
        window_start = now - timedelta(hours=hours)
        loggers = driver.load_profile_loggers()
        out(f"[*] reading logger(s) {loggers} for the last {hours}h")

        ours: list[Any] = []
        for logger_id in loggers:
            ours.extend(driver.read_load_profile(logger_id, window_start, now))
        out(f"[*] driver.read_load_profile() -> {len(ours)} interval(s)")
    finally:
        driver.disconnect()
        out("")
        out("[*] disconnected - nothing was written to the meter")

    if not ours:
        out("[!] the meter returned no intervals in that window - widen --hours")
        return

    matched = [(reading, vendor[reading.read_at]) for reading in ours if reading.read_at in vendor]
    out("")
    out(f"=== MATCHED INTERVALS: {len(matched)} of {len(ours)} read ===")
    if not matched:
        out("[!] no timestamp overlap. The vendor export may predate this window -")
        out("    check the newest 'Date Stamp' in the CSV against the times above.")
        return

    out(f"    ours:   {min(r.read_at for r in ours).isoformat()} .. {max(r.read_at for r in ours).isoformat()}")
    out(f"    vendor: {min(vendor).isoformat()} .. {max(vendor).isoformat()}")

    out("")
    header = f"{'field':<22} {'vendor column':<16} {'pairs':>6} {'ours':>14} {'vendor':>14} {'ratio':>10}  verdict"
    out(header)
    out("-" * (len(header) + 20))

    for field, (vendor_column, to_our_unit) in _COMPARISONS.items():
        ratios: list[float] = []
        sample: tuple[float, float] | None = None

        for reading, vendor_row in matched:
            mine = getattr(reading, field, None)
            theirs_raw = vendor_row.get(vendor_column)
            if mine is None or theirs_raw is None:
                continue
            theirs = theirs_raw * to_our_unit
            # A zero on either side carries no ratio - a no-load interval would
            # otherwise flood the median with 0/0 noise and hide a real factor.
            if not theirs or not mine:
                continue
            ratios.append(float(mine) / theirs)
            if sample is None:
                sample = (float(mine), theirs)

        if not ratios:
            out(f"{field:<22} {vendor_column:<16} {0:>6}  (no interval where both sides are non-zero)")
            continue

        median = statistics.median(ratios)
        spread = max(ratios) / min(ratios)
        mine_text, theirs_text = (f"{sample[0]:.4f}", f"{sample[1]:.4f}") if sample else ("-", "-")
        verdict = _ratio_label(median)
        if spread > 1.05:
            verdict = f"{verdict} (SPREAD {spread:.3f} - not a clean constant)".strip()

        out(
            f"{field:<22} {vendor_column:<16} {len(ratios):>6} {mine_text:>14} "
            f"{theirs_text:>14} {median:>10.5g}  {verdict}"
        )

    out("")
    out("'ours' and 'vendor' are one sample pair for orientation; 'ratio' is the MEDIAN")
    out("across every matched interval where both sides are non-zero. A ratio that is a")
    out("clean constant is a systematic factor, not noise.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare the shipped SMW110W4 load-profile read against the vendor CSV export."
    )
    transport = parser.add_mutually_exclusive_group(required=True)
    transport.add_argument("--host", help="Meter IP address (TCP transport)")
    transport.add_argument("--serial-port", help="COM port, e.g. COM4 (serial transport)")
    parser.add_argument("--port", type=int, default=4059, help="Meter TCP port (default 4059)")
    parser.add_argument("--baud-rate", type=int, default=19200, help="Serial baud rate (default 19200)")
    parser.add_argument("--password", required=True, help="DLMS password (never printed, never written)")
    parser.add_argument("--csv", required=True, help="The vendor tool's CSV export for THIS meter")
    parser.add_argument("--hours", type=int, default=48, help="How far back to read (default 48)")
    parser.add_argument("--out", help="Report file (default lp-compare-<timestamp>.txt)")
    parser.add_argument("--verbose", action="store_true", help="Show driver logs")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    if args.host:
        conn = ConnectionParams.net(args.host, args.port)
    else:
        conn = ConnectionParams.serial(args.serial_port, baud_rate=args.baud_rate)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = Path(args.out) if args.out else Path.cwd() / f"lp-compare-{stamp}.txt"
    out = Report(out_path)

    out(f"### SMW110W4 load profile: shipped driver vs vendor export @ {conn.endpoint}")
    out(f"# compared {datetime.now().isoformat(timespec='seconds')}  (read-only, one association)")
    out("# password supplied on the command line - deliberately not recorded here")
    out("")

    try:
        vendor = _read_vendor_csv(Path(args.csv), out)
        if not vendor:
            out("[!] no load-profile rows found in that CSV - is it the right export?")
            return 1
        compare(conn, args.password, vendor, args.hours, out)
    except Exception as exc:  # noqa: BLE001 - the report must survive any failure.
        out("")
        out(f"[!] comparison failed: {type(exc).__name__}: {exc}")
        return 1
    finally:
        out("")
        out(f"[*] report written to {out_path}")
        out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
