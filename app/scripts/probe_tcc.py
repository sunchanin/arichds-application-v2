"""Read-only field probe for the SMART TCC family over serial (or TCP).

Five of this product's nine models sit behind one driver
(:class:`~arichds.acquisition.drivers.smart_tcc.SmartTccDriver`) and **none of
them has ever been read from real hardware** — the site's TCP endpoint has
never answered. This script is the first contact, and it drives the shipped
driver rather than a reimplementation, so what it proves is what the product
does.

Pre-flight, already done against the customer's own Gurux Director export
(`tcc.gxc`) and association view (`test 3CL.xml`) before this script existed:

* Connection profile matches the driver exactly — client 1, physical/logical
  server 127/127, HDLC, LN referencing, HighGMAC + AuthenticationEncryption.
* The block cipher key and the authentication key on the customer's device are
  **the same values the driver already carries**, so the association should
  authenticate without any per-site key.
* Every OBIS the driver declares exists on the meter with the class the driver
  expects: the billing profile, load-profile logger 1, the meter serial, the
  invocation-counter object, all 11 load-profile columns and all 50 billing
  columns.

So the open questions this probe answers are the ones a static check cannot:
does the association actually open over this serial line, does the meter serve
the two profile buffers, and do the values that come back look like
measurements rather than noise.

**Read-only.** One association, attribute reads, disconnect. It never writes to
a meter - no register write, no clock set, no MD reset, on any transport, ever
(``CLAUDE.md``).

**No password is required or accepted.** HighGMAC is keyless; the key material
belongs to the driver. Nothing secret is printed or written by this script.

Output: `tcc-probe-<timestamp>.txt` (human) and `.csv` (machine-diffable), both
in the current directory, matching the other probes in this directory.

Usage::

    probe_tcc.exe --serial-port COM3
    probe_tcc.exe --serial-port COM3 --baud-rate 9600 --model st3cl
    probe_tcc.exe --host 203.170.148.103           # if the TCP path ever answers
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from gurux_dlms import GXReplyData
from gurux_dlms.objects import GXDLMSProfileGeneric

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms_profile import CEWE_DEMAND_TIME_COLUMNS
from arichds.acquisition.drivers.factory import create_driver, supported_models

#: The five catalog keys this one driver serves. Any of them produces the same
#: driver; the flag exists so the report records which model the operator
#: believed they were probing.
_TCC_MODELS = ("st3c", "st3cl", "st33tl", "st3tl", "st3dh")

#: `tcc.gxc` names a COM port but **no line settings**, so Gurux's own default
#: applies. 9600 is that default; it is NOT field-confirmed for this meter the
#: way 19200 is for the SMW110W4. If the association will not open, this is the
#: first thing to vary.
_DEFAULT_BAUD = 9600

_LOAD_PROFILE_WINDOW_HOURS = 6

#: Line settings to try, in order, when the association will not open. The
#: customer's Director export names a COM port and nothing else, so the line is
#: genuinely unknown and guessing one value per site visit is the wrong trade:
#: sweeping eleven combinations costs under a minute, a wrong guess costs a
#: round trip. 8N1 first (what DLMS/HDLC almost always runs), then the 7E1
#: shapes an IEC 62056-21 style link uses.
_LINE_CANDIDATES: tuple[tuple[int, int, str, int], ...] = (
    (9600, 8, "None", 1),
    (19200, 8, "None", 1),
    (38400, 8, "None", 1),
    (115200, 8, "None", 1),
    (57600, 8, "None", 1),
    (4800, 8, "None", 1),
    (2400, 8, "None", 1),
    (1200, 8, "None", 1),
    (9600, 7, "Even", 1),
    (19200, 7, "Even", 1),
    (300, 7, "Even", 1),
)

#: Per-attempt timeout while sweeping. The driver's own is **90 s** (GPRS +
#: GMAC latency, `smart_tcc.py`), which is right for a real read and useless
#: for discovery: a wrong baud produces silence, so a short wait is all the
#: information there is. Once a line opens, the full read runs on the driver's
#: real timeout, not this one.
_SWEEP_TIMEOUT_MS = 4000

#: The instantaneous profile scanned for any sign of load, and how many of its
#: rows to pull. Logger 2 samples every 60 s on this model, so 240 rows is
#: four hours - long enough that a working installation cannot be all zeros.
_ACTIVITY_PROFILE = "1.0.99.2.0.255"
_ACTIVITY_SAMPLE = 240


class Report:
    """Write every line to the console and to the report file at once.

    ASCII-only on purpose - a Windows console defaults to cp1252 and raises
    UnicodeEncodeError on anything else, which would abort the probe at the
    print rather than at the meter.
    """

    def __init__(self, path: Path) -> None:
        self._fh = path.open("w", encoding="utf-8", newline="\n")

    def __call__(self, line: str = "") -> None:
        print(line)
        self._fh.write(line + "\n")
        self._fh.flush()  # a link that dies mid-run must still leave a readable file

    def close(self) -> None:
        self._fh.close()


def _describe_ports() -> list[str]:
    """One line per serial port Windows currently reports.

    A COM number belongs to the USB adapter, not to the meter, and Windows
    re-issues it when the adapter is replugged - so the number saved in a
    Director profile goes stale on its own. Printing the ports that *do* exist
    turns "timeout" into a next step.
    """
    try:
        from serial.tools import list_ports
    except Exception as exc:  # noqa: BLE001 - never let the diagnostic break the diagnostic
        return [f"(could not list ports: {exc})"]
    ports = sorted(list_ports.comports(), key=lambda p: p.device)
    return [f"{p.device:<8} {p.description}" for p in ports] or ["(none - Windows reports no serial ports)"]


def _try_line(model: str, port: str, line: tuple[int, int, str, int], out: Report) -> ConnectionParams | None:
    """Attempt one association on one set of line settings - read-only.

    Returns the :class:`ConnectionParams` that worked, or ``None``. The
    driver's 90 s timeout is overridden **on this instance only**, for the
    sweep only; nothing about the shipped configuration changes.
    """
    baud, data_bits, parity, stop_bits = line
    conn = ConnectionParams.serial(port, baud_rate=baud, data_bits=data_bits, parity=parity, stop_bits=stop_bits)
    label = f"{baud} {data_bits}{parity}{stop_bits}"
    driver = create_driver(model, conn, password="")
    driver._read_timeout_ms = lambda: _SWEEP_TIMEOUT_MS  # type: ignore[method-assign]
    try:
        driver.connect()
    except Exception as exc:  # noqa: BLE001 - a refusal is the result we are measuring
        out(f"    {label:<16} no  ({type(exc).__name__})")
        return None
    else:
        out(f"    {label:<16} **ASSOCIATION OPENED**")
        return conn
    finally:
        # Tearing down a failed attempt must never mask what the attempt found.
        with contextlib.suppress(Exception):
            driver.disconnect()


def _find_line_settings(
    model: str, port: str, first: tuple[int, int, str, int] | None, out: Report
) -> ConnectionParams | None:
    """Sweep the candidate line settings until one opens an association."""
    candidates = list(_LINE_CANDIDATES)
    if first is not None:
        candidates = [first] + [c for c in candidates if c != first]

    out("")
    out(f"=== FINDING THE LINE SETTINGS on {port} ===")
    out(f"    (a wrong baud is silence, so each attempt waits only {_SWEEP_TIMEOUT_MS} ms)")
    for line in candidates:
        conn = _try_line(model, port, line, out)
        if conn is not None:
            return conn
    return None


#: Every ProfileGeneric on the 3CL that could plausibly hold load-profile or
#: billing data, from the customer's association view. The driver reads exactly
#: two of them - logger 1 and Scheme 1 - on reasoning inherited from a **v1 scan
#: of a different unit**. Surveying all nine turns that inheritance into a
#: measurement on the meter actually in front of us, and answers the obvious
#: question when a buffer comes back empty: *is the data simply somewhere else?*
_PROFILE_SURVEY: tuple[tuple[str, str], ...] = (
    ("1.0.99.1.0.255", "load profile logger 1  <- the driver reads this"),
    ("1.0.99.2.0.255", "load profile logger 2"),
    ("1.0.99.3.0.255", "load profile logger 3"),
    ("0.0.98.1.0.255", "billing Scheme 1       <- the driver reads this"),
    ("0.0.98.2.0.255", "billing Scheme 2"),
    ("0.0.98.3.0.255", "billing Scheme 3"),
    ("1.0.98.1.0.255", "billing 1.0 prefix, Scheme 1"),
    ("1.0.98.2.0.255", "billing 1.0 prefix, Scheme 2"),
    ("1.0.98.3.0.255", "billing 1.0 prefix, Scheme 3"),
)

#: Cumulative energy totals. These are standalone Registers, not capture
#: columns, and they answer the question a zero-valued load profile cannot:
#: has this meter **ever** measured energy? A non-zero total with a zero load
#: profile means "no load right now"; zero on both means the meter has never
#: seen current, and no scaler on any energy column has ever been exercised.
_ENERGY_TOTALS: tuple[tuple[str, str], ...] = (
    ("1.0.1.8.0.255", "import active   (cumulative)"),
    ("1.0.2.8.0.255", "export active   (cumulative)"),
    ("1.0.3.8.0.255", "import reactive (cumulative)"),
    ("1.0.4.8.0.255", "export reactive (cumulative)"),
)


def _scan_for_activity(driver: Any, obis: str, sample: int, out: Report) -> None:
    """Has this meter EVER seen current? Scan a profile's raw cells - read-only.

    The customer reports that this meter has current, voltage and energy; the
    cumulative energy registers read 0.0. Both cannot be true, and a single
    instantaneous read cannot settle it because it only speaks for one moment.

    Logger 2 samples the **instantaneous** group (``D=7`` — power, current,
    voltage, PF) every 60 s, so a few hundred of its rows cover the better part
    of a day. Raw cells are reported without scaling on purpose: a non-zero raw
    is non-zero whatever the multiplier turns out to be, so this answers the
    question even on columns whose scaler has never been verified.
    """
    out("")
    out(f"=== ACTIVITY SCAN on {obis} - was anything ever non-zero? ===")
    pg = GXDLMSProfileGeneric(obis)
    driver._client.objects.append(pg)
    try:
        driver._reader.read(pg, 3)
        entries = int(driver._reader.read(pg, 7))
    except Exception as exc:  # noqa: BLE001 - a refusal is a result, not a crash
        out(f"    could not open the profile: {type(exc).__name__}: {exc}")
        return
    if entries <= 0:
        out("    the profile is empty - nothing to scan")
        return

    count = min(sample, entries)
    start = max(1, entries - count + 1)
    out(f"    entries_in_use={entries}; reading {count} rows from entry {start}")
    try:
        request = driver._client.readRowsByEntry(pg, start, count)
        reply = GXReplyData()
        driver._reader.readDataBlock(request, reply)
        rows = driver._client.updateValue(pg, 2, reply.value) or []
    except Exception as exc:  # noqa: BLE001 - a refusal is a result, not a crash
        out(f"    read failed: {type(exc).__name__}: {exc}")
        return

    names = [str(obj.logicalName) for obj, _cap in pg.captureObjects]
    out(f"    {len(rows)} row(s) returned")
    out("")
    out(f"    {'capture obis':<20} {'non-zero rows':>14} {'max raw seen':>18}")
    out("    " + "-" * 54)
    any_activity = False
    for position, name in enumerate(names):
        values = [row[position] for row in rows if position < len(row) and isinstance(row[position], (int, float))]
        nonzero = [v for v in values if v]
        if nonzero:
            any_activity = True
        biggest = max((abs(v) for v in values), default=0)
        out(f"    {name:<20} {len(nonzero):>6} of {len(values):<5} {biggest!s:>18}")

    out("")
    if any_activity:
        out("    -> at least one column carried a non-zero value in this window.")
    else:
        out("    -> EVERY numeric cell in this window is zero. Combined with the")
        out("       cumulative registers also reading 0.0, this meter has not")
        out("       measured anything: no wiring fault on our side explains it.")


def _report_conformance(
    driver: Any,
    lp_shapes: dict[int, list[tuple[str, int]]],
    billing_columns: list[tuple[str, int]],
    survey: dict[str, tuple[int, int, int]],
    out: Report,
) -> None:
    """Does what this driver *declares* match what this meter actually serves?

    This is the check that makes adding a model cheap. One driver class serves
    all five TCC keys on the assumption they are identical (``smart_tcc.py``'s
    D14 records that as an assumption, not a measurement) — and the CEWE
    experience is the reason to distrust it: three models of one brand differ
    in logger count, capture period *and* column set
    (``docs/meter-notes/load-profile-capture-objects.md``).

    So the answer for a new model is not a fresh investigation, it is this
    verdict. Plug in, run, read one line.
    """
    out("")
    out("=== DRIVER CONFORMANCE - do the driver's declarations hold on THIS model? ===")
    verdicts: list[str] = []

    for logger_id, live in lp_shapes.items():
        declared = set(driver.LOAD_PROFILE_COLUMN_MAP.get(logger_id, {}))
        present = declared & set(live)
        missing = sorted(declared - set(live))
        state = "PASS" if not missing else "FAIL"
        verdicts.append(state)
        out(f"  load profile logger {logger_id:<3} {len(present)}/{len(declared)} declared columns present     {state}")
        for obis, attr in missing:
            field = driver.LOAD_PROFILE_COLUMN_MAP[logger_id][obis, attr][0]
            out(f"      MISSING {obis} attr={attr}  ({field})")

    declared_billing = set(driver._mapped_billing_columns()) | set(CEWE_DEMAND_TIME_COLUMNS)
    live_billing = set(billing_columns)
    missing_billing = sorted(declared_billing - live_billing)
    state = "PASS" if not missing_billing else "FAIL"
    verdicts.append(state)
    out(
        f"  billing {driver.BILLING_PROFILE_OBIS:<16} "
        f"{len(declared_billing & live_billing)}/{len(declared_billing)} declared columns present     {state}"
    )
    for obis, attr in missing_billing[:10]:
        out(f"      MISSING {obis} attr={attr}")

    # Profiles the meter is actively filling that this driver never opens. Not
    # a failure - the driver may be right to ignore them - but it is the thing
    # a reader should be told rather than left to spot in the survey table.
    declared_lp = {f"1.0.99.{n}.0.255" for n in driver.load_profile_loggers()}
    ignored = [
        (obis, entries)
        for obis, (entries, _period, _cols) in survey.items()
        if entries > 0 and obis not in declared_lp and obis != driver.BILLING_PROFILE_OBIS
    ]
    if ignored:
        out("  profiles holding data that this driver never reads:            REVIEW")
        for obis, entries in sorted(ignored):
            out(f"      {obis}  {entries} entries")

    out("")
    if "FAIL" in verdicts:
        out("  VERDICT: FAIL - this model does not match the driver's declarations.")
        out("           The missing columns above will store NULL on every row.")
    else:
        out("  VERDICT: PASS - every column this driver declares exists on this meter.")
        out("           (Presence is not correctness: a column can be present and mis-scaled.")
        out("            Only non-zero values prove scaling.)")


def _survey_profiles(driver: Any, out: Report) -> dict[str, tuple[int, int, int]]:
    """Report entries/period/width for every candidate profile - read-only.

    Reads attributes 7 (entries in use), 4 (capture period) and 3 (capture
    objects). A saved Director export cannot answer this: its stored counts are
    whatever Director happened to have read, and on this meter its load-profile
    figure was stale by a factor of six.
    """
    out("")
    out("=== PROFILE SURVEY - where the data actually is ===")
    header = f"{'obis':<16} {'entries':>8} {'period':>8} {'columns':>8}  what"
    out(header)
    out("-" * (len(header) + 12))
    found: dict[str, tuple[int, int, int]] = {}
    for obis, label in _PROFILE_SURVEY:
        pg = GXDLMSProfileGeneric(obis)
        driver._client.objects.append(pg)
        try:
            driver._reader.read(pg, 3)
            entries = int(driver._reader.read(pg, 7))
            period = int(driver._reader.read(pg, 4))
        except Exception as exc:  # noqa: BLE001 - a refusal is a result, not a crash
            out(f"{obis:<16} {'REFUSED: ' + type(exc).__name__:>26}  {label}")
            continue
        found[obis] = (entries, period, len(pg.captureObjects))
        out(f"{obis:<16} {entries:>8} {period:>8} {len(pg.captureObjects):>8}  {label}")
    return found


def _read_energy_totals(driver: Any, out: Report) -> None:
    """Read the cumulative energy registers - read-only.

    Attribute 3 before attribute 2 so Gurux applies the meter's own multiplier
    (ADR 0002), the same order the product uses.
    """
    from gurux_dlms.objects import GXDLMSRegister

    out("")
    out("=== CUMULATIVE ENERGY TOTALS - has this meter ever measured anything? ===")
    for obis, label in _ENERGY_TOTALS:
        obj = GXDLMSRegister(obis)
        driver._client.objects.append(obj)
        try:
            driver._reader.read(obj, 3)
            value = driver._reader.read(obj, 2)
        except Exception as exc:  # noqa: BLE001 - a refusal is a result, not a crash
            out(f"    {label:<30} {obis:<16} REFUSED: {type(exc).__name__}")
            continue
        unit = getattr(obj, "unit", None)
        unit_text = f"{unit.name}({int(unit)})" if unit is not None else "-"
        out(f"    {label:<30} {obis:<16} {value!s:>18}  unit={unit_text}")


def _profile_shape(driver: Any, obis: str) -> tuple[list[tuple[str, int]], int]:
    """Read a ProfileGeneric's live capture list and ``entries_in_use`` - read-only."""
    pg = GXDLMSProfileGeneric(obis)
    driver._client.objects.append(pg)
    driver._reader.read(pg, 3)
    entries = int(driver._reader.read(pg, 7))
    columns = [(str(obj.logicalName), int(cap.attributeIndex)) for obj, cap in pg.captureObjects]
    return columns, entries


def _write_csv(path: Path, rows: list[dict[str, Any]], out: Report) -> None:
    """Dump every reading as one line per field, for diffing against any export."""
    if not rows:
        out("[*] nothing read - no CSV written")
        return
    fields = ["kind", "stamp_utc", "logger_id", "field", "value"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    out(f"[*] CSV written to {path}")


def probe(conn: ConnectionParams, model: str, out: Report) -> list[dict[str, Any]]:
    """Run the whole probe on one association - read-only throughout."""
    driver = create_driver(model, conn, password="")
    csv_rows: list[dict[str, Any]] = []
    lp_shapes: dict[int, list[tuple[str, int]]] = {}

    out(f"[*] {model} @ {conn.endpoint} - connecting (read-only, one association)")
    out("[*] HighGMAC + AuthenticationEncryption, keys owned by the driver - no password sent")
    driver.connect()
    try:
        out(f"[+] ASSOCIATION OPEN - meter serial: {driver.read_meter_serial()}")

        survey = _survey_profiles(driver, out)
        _read_energy_totals(driver, out)
        _scan_for_activity(driver, _ACTIVITY_PROFILE, _ACTIVITY_SAMPLE, out)

        # ── Load profile ─────────────────────────────────────────────────────
        for logger_id in driver.load_profile_loggers():
            obis = f"1.0.99.{logger_id}.0.255"
            out("")
            out(f"=== LOAD PROFILE logger {logger_id} ({obis}) ===")
            columns, entries = _profile_shape(driver, obis)
            lp_shapes[logger_id] = columns
            out(f"    entries_in_use: {entries}   live capture columns: {len(columns)}")
            for column_obis, attr in columns:
                out(f"      {column_obis:<20} attr={attr}")

            now = datetime.now(UTC)
            readings = driver.read_load_profile(logger_id, now - timedelta(hours=_LOAD_PROFILE_WINDOW_HOURS), now)
            out(f"    read_load_profile(last {_LOAD_PROFILE_WINDOW_HOURS}h) -> {len(readings)} row(s)")
            for reading in readings:
                values = reading.as_columns()
                resolved = {k: v for k, v in values.items() if v is not None}
                out(f"      {reading.read_at.isoformat()}  interval={reading.interval_sec}s  {resolved}")
                for name, value in values.items():
                    csv_rows.append(
                        {
                            "kind": "load_profile",
                            "stamp_utc": reading.read_at.isoformat(),
                            "logger_id": logger_id,
                            "field": name,
                            "value": "" if value is None else value,
                        }
                    )

        # ── Billing ──────────────────────────────────────────────────────────
        out("")
        out(f"=== BILLING ({driver.BILLING_PROFILE_OBIS}) ===")
        columns, entries = _profile_shape(driver, driver.BILLING_PROFILE_OBIS)
        out(f"    entries_in_use: {entries}   live capture columns: {len(columns)}")
        for column_obis, attr in columns:
            out(f"      {column_obis:<20} attr={attr}")

        _report_conformance(driver, lp_shapes, columns, survey, out)

        billing = driver.read_billing()
        out(f"    read_billing() -> {len(billing)} row(s)")
        for reading in billing:
            values = reading.as_columns()
            resolved = {k: v for k, v in values.items() if v is not None}
            nulls = [k for k, v in values.items() if v is None]
            out("")
            out(f"      bill_date={reading.bill_date.isoformat()}  is_open={reading.is_open}")
            out(f"        resolved ({len(resolved)}): {resolved}")
            out(f"        NULL ({len(nulls)}): {nulls}")
            for name, value in values.items():
                csv_rows.append(
                    {
                        "kind": "billing",
                        "stamp_utc": reading.bill_date.isoformat(),
                        "logger_id": "",
                        "field": name,
                        "value": "" if value is None else value,
                    }
                )
    finally:
        driver.disconnect()
        out("")
        out("[*] disconnected - nothing was written to the meter")

    return csv_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only SMART TCC field probe (serial or TCP).")
    transport = parser.add_mutually_exclusive_group(required=True)
    transport.add_argument("--serial-port", help="COM port, e.g. COM3")
    transport.add_argument("--host", help="Meter IP address (TCP transport)")
    parser.add_argument("--port", type=int, default=4059, help="Meter TCP port (default 4059)")
    parser.add_argument(
        "--baud-rate",
        type=int,
        default=_DEFAULT_BAUD,
        help=f"Serial baud rate (default {_DEFAULT_BAUD} - Gurux's own default; the customer's "
        "device export names a COM port but no line settings, so this is unverified)",
    )
    parser.add_argument("--model", default="st3cl", choices=_TCC_MODELS, help="Which TCC key to record (default st3cl)")
    parser.add_argument("--out", help="Report file (default tcc-probe-<timestamp>.txt)")
    parser.add_argument("--csv", help="CSV file (default tcc-probe-<timestamp>.csv)")
    parser.add_argument("--verbose", action="store_true", help="Show driver logs on the console")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    if args.model not in supported_models():
        print(f"Model {args.model!r} is not registered in this build.")
        return 2

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = Path(args.out) if args.out else Path.cwd() / f"tcc-probe-{stamp}.txt"
    csv_path = Path(args.csv) if args.csv else Path.cwd() / f"tcc-probe-{stamp}.csv"
    out = Report(out_path)

    out(f"### SMART TCC probe ({args.model})")
    out(f"# probed {datetime.now().isoformat(timespec='seconds')}  (read-only)")
    out("# HighGMAC / Suite0 - key material belongs to the driver, nothing secret is recorded here")
    out("")

    if args.serial_port:
        out("Serial ports Windows reports right now:")
        for line in _describe_ports():
            out(f"  {line}")
        conn = _find_line_settings(args.model, args.serial_port, (args.baud_rate, 8, "None", 1), out)
        if conn is None:
            out("")
            out("[!] no line setting opened an association. What that leaves:")
            out(f"  1. is {args.serial_port} the adapter facing the meter? compare the list above")
            out("  2. is another program holding the port (Gurux Director, a terminal)?")
            out("  3. wiring / converter direction (RS-485 A-B swapped answers nothing at any baud)")
            out("  4. the meter may need a line this sweep does not cover - send this file back")
            out("")
            out(f"[*] report written to {out_path}")
            out.close()
            return 1
        out("")
        out(
            f"[+] line settings found: {conn.endpoint}  ({conn.baud_rate} {conn.data_bits}{conn.parity}{conn.stop_bits})"
        )
        out("    the full read below uses the DRIVER's own 90 s timeout, not the sweep's")
    else:
        conn = ConnectionParams.net(args.host, args.port)

    try:
        rows = probe(conn, args.model, out)
        _write_csv(csv_path, rows, out)
    except Exception as exc:  # noqa: BLE001 - the report must survive any failure.
        out("")
        out(f"[!] probe failed: {type(exc).__name__}: {exc}")
        out("")
        out("The association opened but the read failed - this is no longer a line-settings problem.")
        out("  Send the report back: the failure above is about the meter or the driver, not the cable.")
        return 1
    finally:
        out("")
        out(f"[*] report written to {out_path}")
        out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
