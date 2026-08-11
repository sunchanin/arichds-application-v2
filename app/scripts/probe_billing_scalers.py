"""Read-only diagnostic for a *wrong units* report on SMW110W4 billing.

A billing cell reaches the database through four steps, and the **stored
number alone cannot tell you which one is wrong**::

    raw cell            straight off the ProfileGeneric buffer, unscaled
      x multiplier      scaler_unit (attr 3) read off a SEPARATE register object
      / 1000            WH_TO_KWH_DIVISOR, applied to every billing column
      = stored value

This script prints all four, per column, so the broken link is visible instead
of inferred. The three failure shapes it is built to tell apart:

1. **A borrowed scaler.** :meth:`~arichds.acquisition.drivers.smw110.Smw110Driver._billing_multiplier`
   falls back to the ``E=0`` (total) sibling when a tariff column's own
   ``scaler_unit`` is denied (``smw110.py:525-530``). If this meter scales its
   totals and its tariff registers differently, every borrowed column is off by
   a power of ten while the totals read correctly. The ``src`` column below
   marks which columns borrowed.
2. **A scaler that does not apply to the buffer.** The multiplier comes from a
   standalone register at the same OBIS, on the assumption that the captured
   column uses the same scaling. That assumption is not guaranteed by DLMS.
   The ``REGISTER CROSS-CHECK`` section is what tests it: the standalone
   register's own value should match the Open Period's stored cell, because
   both are the same running total.
3. **An unresolved scaler.** Neither address answered with the required Unit,
   so the column is stored ``NULL`` rather than unscaled
   (``build_fields``, ``_profile.py:140-143``). Shown as ``src=none``.

Note the Unit check is load-bearing for step 3 of the chain: the driver only
accepts W / Wh / var / varh (DLMS 27 / 30 / 29 / 32 - all base units), which is
what makes the unconditional ``/1000`` correct. A multiplier accepted under any
other unit would be a defect, so the reported unit is printed too.

**Read-only, exactly like every other script under this directory.** It opens
one association, reads attributes and the billing buffer, and disconnects. **It
never writes to a meter** - no register write, no clock set, no MD reset, on
any transport, ever (``CLAUDE.md``).

The password is a command-line argument only - never logged, never printed,
never written into the report file. ``--password`` is **required** rather than
defaulted from ``catalog.MITSU_SMW110_FIXED_PASSWORD``, even though that
constant is correct again since 2026-08-10: it carried the retired unit's
password for months without anyone noticing (``smw110w4-scan.md`` closing
notes), and the costs are asymmetric. Requiring the flag costs one argument;
silently authenticating with a stale constant costs a confusing ``AUTH_FAILED``
in front of a customer, which is exactly when a diagnostic must not lie.

Every line goes to the console and to a report file at once
(``billing-scalers-<timestamp>.txt`` in the current directory), the same way
``probe_smw110_serial.py`` and ``probe_lp_smw110.py`` do - the console is what
the engineer on site watches, the file is the artifact that comes back.

Scope: **SMW110W4 (``smw110``) only** - it reads that driver's billing column
map and its ``_billing_multiplier`` directly. The CEWE and SMART TCC billing
paths live on a different base class and are not covered here.

Usage::

    probe_billing_scalers.exe --host 192.168.1.31 --password <supplied by the operator>
    probe_billing_scalers.exe --serial-port COM4 --password <supplied by the operator>
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from gurux_dlms import GXReplyData
from gurux_dlms.enums import Unit
from gurux_dlms.objects import GXDLMSProfileGeneric

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._profile import (
    coerce_clock_cell,
    meter_local_to_utc,
    positions_by_obis_attr,
)
from arichds.acquisition.drivers.factory import create_driver
from arichds.acquisition.drivers.smw110 import (
    _CLOCK_OBIS,
    _MAPPED_BILLING_COLUMNS,
    BILLING_PROFILE_OBIS,
    Smw110Driver,
)
from arichds.constants import WH_TO_KWH_DIVISOR

_MODEL = "smw110"

#: What a resolved multiplier is expected to look like on a healthy meter. A
#: multiplier outside this range is not proof of a fault, but it is the shape a
#: power-of-ten error takes, so it is flagged rather than left to the eye.
_PLAUSIBLE_MULTIPLIERS = frozenset({0.001, 0.01, 0.1, 1.0, 10.0, 100.0, 1000.0})


class Report:
    """Write every line to the console and to the report file at once.

    Same shape as ``probe_smw110_serial.py``'s ``Report`` - duplicated rather
    than shared because these are standalone scripts, each frozen into its own
    exe, and that is already the convention across this directory.

    Output is deliberately **ASCII-only** - a Windows console defaults to cp1252
    and raises UnicodeEncodeError on anything else, which would abort the probe
    at the print, not at the meter.
    """

    def __init__(self, path: Path) -> None:
        self._fh = path.open("w", encoding="utf-8", newline="\n")

    def __call__(self, line: str = "") -> None:
        print(line)
        self._fh.write(line + "\n")
        self._fh.flush()  # a link that dies mid-run must still leave the file readable

    def close(self) -> None:
        self._fh.close()


def _exponent(multiplier: float | None) -> str:
    """Render a Gurux multiplier (``10**exponent``, ADR 0002) as its exponent."""
    if multiplier is None or multiplier <= 0:
        return "-"
    return f"{round(math.log10(multiplier)):+d}"


def _probe_scaler_unit(
    driver: Smw110Driver,
    obis: str,
    cosem_class: type,
    cache: dict[tuple[str, type], tuple[Unit | None, float | None]],
) -> tuple[Unit | None, float | None]:
    """Read *obis*'s ``scaler_unit`` (attr 3) and keep BOTH halves - read-only.

    The driver's own :meth:`Smw110Driver._read_scaler_unit` returns only the
    multiplier, discarding the unit it checked against. The unit is exactly
    what a "wrong units" report needs, so this reads it separately and reports
    it. The driver's answer is still reported alongside (the ``mult`` column
    comes from the driver, not from here) - if the two ever disagree, that
    disagreement is itself the finding.
    """
    key = (obis, cosem_class)
    if key in cache:
        return cache[key]

    obj = cosem_class(obis)
    driver._client.objects.append(obj)
    try:
        driver._reader.read(obj, 3)
    except Exception:  # noqa: BLE001 - a denied attribute is a result here, not a crash.
        result: tuple[Unit | None, float | None] = (None, None)
    else:
        result = (obj.unit, obj.scaler)

    cache[key] = result
    return result


def _sibling_obis(capture_obis: str) -> str:
    """The ``E=0`` (total) sibling address - the same split the driver uses."""
    parts = capture_obis.split(".")
    return ".".join([*parts[:4], "0", parts[5]])


def _read_raw_buffer(
    driver: Smw110Driver,
) -> tuple[list[Any], dict[tuple[str, int], int], int, list[Any]]:
    """Read the billing buffer raw, through the driver's own span - read-only.

    Replicates ``Smw110Driver.read_billing()``'s transport exactly
    (``smw110.py:565-601``): a full-width read answers "Data Block Unavailable"
    on this profile, so the span-limited ``GXDLMSClient.readRowsByEntry`` is
    driven by hand. Nothing vendored is touched.
    """
    pg = GXDLMSProfileGeneric(BILLING_PROFILE_OBIS)
    driver._client.objects.append(pg)

    driver._reader.read(pg, 3)  # live capture list, never cached (D7)
    entries_in_use = int(driver._reader.read(pg, 7))
    if entries_in_use <= 0:
        return [], {}, 0, []

    span = list(pg.captureObjects)[: driver.BILLING_COLUMN_SPAN]
    positions = positions_by_obis_attr(span)

    original_capture_objects = pg.captureObjects
    try:
        request = driver._client.readRowsByEntry(pg, 1, entries_in_use, span)
        reply = GXReplyData()
        driver._reader.readDataBlock(request, reply)
        pg.captureObjects = span
        rows = driver._client.updateValue(pg, 2, reply.value) or []
    finally:
        pg.captureObjects = original_capture_objects

    return rows, positions, entries_in_use, span


def _report_meter_declared_classes(
    driver: Smw110Driver,
    span: list[Any],
    out: Report,
) -> None:
    """Ask the METER for each column's scaler, using the class the meter declares.

    The rest of this probe (and the driver itself) constructs a fresh object of a
    class chosen ahead of time - ``GXDLMSRegister`` for ``D=8``,
    ``GXDLMSExtendedRegister`` for ``D=6`` (``smw110.py``'s
    ``_MAPPED_BILLING_COLUMNS``). If the meter models a column as some other
    COSEM class, reading attribute 3 off the guessed class is a malformed
    request, and this meter answers such a request with **"Device reports a
    unavailable object"** - indistinguishable, from the driver's side, from a
    column that genuinely has no scaler.

    ``pg.captureObjects`` (attribute 3, read live) already carries the object the
    meter itself declares, class included. This reads ``scaler_unit`` off *that*
    instance, so an "unavailable object" here means the meter really will not
    scale the column, rather than that we asked the wrong way.
    """
    out("")
    out("=== METER-DECLARED CAPTURE CLASSES - scaler read off the meter's own object ===")
    out("'guessed' is the class the driver assumes; 'declared' is what the meter says.")
    out("")

    header = f"{'field':<38} {'capture obis':<16} {'guessed':<18} {'declared':<18} {'unit':<20} {'exp':>4} {'mult':>10}"
    out(header)
    out("-" * len(header))

    for obj, capture_def in span:
        key = (str(obj.logicalName), int(capture_def.attributeIndex))
        mapped = _MAPPED_BILLING_COLUMNS.get(key)
        if mapped is None:
            continue
        field, guessed_class, _required_unit = mapped

        declared = type(obj).__name__
        try:
            driver._reader.read(obj, 3)
        except Exception as exc:  # noqa: BLE001 - a refusal is a result, not a crash.
            out(f"{field:<38} {key[0]:<16} {guessed_class.__name__:<18} {declared:<18} REFUSED: {str(exc)[:52]}")
            continue

        unit = getattr(obj, "unit", None)
        mult = getattr(obj, "scaler", None)
        unit_text = f"{unit.name}({int(unit)})" if unit is not None else "-"
        mult_text = f"{mult:g}" if isinstance(mult, (int, float)) else "-"
        flag = "" if declared == guessed_class.__name__ else "   <-- CLASS MISMATCH"
        out(
            f"{field:<38} {key[0]:<16} {guessed_class.__name__:<18} {declared:<18} "
            f"{unit_text:<20} {_exponent(mult):>4} {mult_text:>10}{flag}"
        )


def _report_chain(
    driver: Smw110Driver,
    row: list[Any],
    positions: dict[tuple[str, int], int],
    out: Report,
) -> list[str]:
    """Report the four-step chain for every mapped column of one row.

    Returns:
        The names of the columns whose multiplier looks suspicious - borrowed
        from a sibling, unresolved, or outside :data:`_PLAUSIBLE_MULTIPLIERS`.
    """
    scaler_cache: dict[tuple[str, type], tuple[Unit | None, float | None]] = {}
    driver_cache: dict[tuple[str, type, Unit], float | None] = {}
    suspicious: list[str] = []

    header = (
        f"{'field':<38} {'capture obis':<16} {'pos':>3} {'raw':>16} "
        f"{'src':<8} {'unit':<10} {'exp':>4} {'mult':>10} {'stored':>18}"
    )
    out(header)
    out("-" * len(header))

    for capture_key, (field, cosem_class, required_unit) in sorted(
        _MAPPED_BILLING_COLUMNS.items(), key=lambda item: item[1][0]
    ):
        obis, _attr = capture_key
        pos = positions.get(capture_key)
        if pos is None:
            out(f"{field:<38} {obis:<16} {'-':>3} {'(not in span)':>16}")
            continue

        raw = row[pos] if pos < len(row) else None

        own_unit, own_mult = _probe_scaler_unit(driver, obis, cosem_class, scaler_cache)
        if own_mult is not None and own_unit == required_unit:
            src, unit = "own", own_unit
        else:
            sib = _sibling_obis(obis)
            sib_unit, sib_mult = _probe_scaler_unit(driver, sib, cosem_class, scaler_cache)
            if sib_mult is not None and sib_unit == required_unit:
                src, unit = "SIBLING", sib_unit
            else:
                src, unit = "none", own_unit or sib_unit

        # The multiplier the SHIPPED path resolves - reported rather than
        # re-derived, so this column reports the product, not this script.
        mult = driver._billing_multiplier(obis, cosem_class, required_unit, field, driver_cache)

        if raw is None or mult is None or not isinstance(raw, (int, float)):
            stored = "NULL"
        else:
            stored = f"{float(raw) * mult / WH_TO_KWH_DIVISOR:.4f}"

        unit_text = f"{unit.name}({int(unit)})" if unit is not None else "-"
        raw_text = f"{raw}" if raw is not None else "-"
        mult_text = f"{mult:g}" if mult is not None else "-"

        out(
            f"{field:<38} {obis:<16} {pos:>3} {raw_text:>16} "
            f"{src:<8} {unit_text:<10} {_exponent(mult):>4} {mult_text:>10} {stored:>18}"
        )

        if src != "own" or (mult is not None and mult not in _PLAUSIBLE_MULTIPLIERS):
            suspicious.append(f"{field} (src={src}, mult={mult_text})")

    return suspicious


def _write_csv(
    driver: Smw110Driver,
    rows: list[Any],
    positions: dict[tuple[str, int], int],
    meter_serial: str | None,
    path: Path,
    out: Report,
) -> None:
    """Dump every billing row x every mapped column as CSV, for diffing.

    Written **long** (one line per cell), not wide, for one reason: a column the
    driver stores as ``NULL`` still has a ``raw`` cell, and the raw cell is the
    only thing there is to compare against a known-correct export. A wide dump
    would show a blank where the answer lives.

    ``multiplier`` is what the shipped driver resolves, so ``stored`` is exactly
    what the product would write to ``billing_readings``. Dividing a
    known-correct value by ``raw`` gives the multiplier the meter never told us
    - which is the whole point of the comparison.
    """
    clock_pos = positions.get((_CLOCK_OBIS, 2))
    scaler_cache: dict[tuple[str, type, Unit], float | None] = {}

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "meter_serial",
                "entry_index",
                "is_open",
                "bill_date_utc",
                "field",
                "capture_obis",
                "raw",
                "multiplier",
                "stored",
            ]
        )

        for index, row in enumerate(rows):
            local_dt = coerce_clock_cell(row[clock_pos]) if clock_pos is not None else None
            bill_date = meter_local_to_utc(local_dt).isoformat() if local_dt is not None else ""

            for capture_key, (field, cosem_class, required_unit) in sorted(
                _MAPPED_BILLING_COLUMNS.items(), key=lambda item: item[1][0]
            ):
                obis, _attr = capture_key
                pos = positions.get(capture_key)
                if pos is None:
                    continue  # outside the 43-column span - no cell exists to compare

                raw = row[pos] if pos < len(row) else None
                mult = driver._billing_multiplier(obis, cosem_class, required_unit, field, scaler_cache)
                if raw is None or mult is None or not isinstance(raw, (int, float)):
                    stored = ""
                else:
                    stored = f"{float(raw) * mult / WH_TO_KWH_DIVISOR:.4f}"

                writer.writerow(
                    [
                        meter_serial or "",
                        index + 1,
                        "yes" if index == 0 else "no",
                        bill_date,
                        field,
                        obis,
                        "" if raw is None else raw,
                        "" if mult is None else f"{mult:g}",
                        stored,
                    ]
                )

    out("")
    out(f"[*] CSV written to {path}")


def _cross_check_registers(driver: Smw110Driver, stored_open: dict[str, Any], out: Report) -> None:
    """Compare each ``E=0`` total against the standalone register - read-only.

    The decisive test for a *wrong units* report. The Open Period's total is a
    running counter, so the standalone register at the same OBIS should read
    essentially the same number. A clean factor between the two columns names
    the error without any reference to v1 or to the meter's display.

    Reads attr 3 **before** attr 2 so Gurux applies the meter's own multiplier
    inside ``setValue`` (ADR 0002) - the same order the product uses.
    """
    out("")
    out("=== REGISTER CROSS-CHECK - standalone register vs the Open Period cell ===")
    out("A ratio far from 1.0 is the size of the error; 1000 or 0.001 means the /1000 step.")
    out("")

    header = f"{'field':<38} {'obis':<16} {'register (base unit)':>22} {'/1000':>16} {'stored':>16} {'ratio':>10}"
    out(header)
    out("-" * len(header))

    for capture_key, (field, cosem_class, _required_unit) in sorted(
        _MAPPED_BILLING_COLUMNS.items(), key=lambda item: item[1][0]
    ):
        if not field.endswith("_total"):
            continue
        obis, _attr = capture_key

        obj = cosem_class(obis)
        driver._client.objects.append(obj)
        try:
            driver._reader.read(obj, 3)
            value = driver._reader.read(obj, 2)
        except Exception as exc:  # noqa: BLE001 - a denied register is a result, not a crash.
            out(f"{field:<38} {obis:<16} {'DENIED: ' + str(exc)[:60]:>22}")
            continue

        if not isinstance(value, (int, float)):
            out(f"{field:<38} {obis:<16} {'non-numeric':>22}")
            continue

        scaled = float(value) / WH_TO_KWH_DIVISOR
        stored = stored_open.get(field)
        ratio = f"{scaled / stored:.4g}" if isinstance(stored, (int, float)) and stored else "-"
        stored_text = f"{stored:.4f}" if isinstance(stored, (int, float)) else str(stored)

        out(f"{field:<38} {obis:<16} {float(value):>22.4f} {scaled:>16.4f} {stored_text:>16} {ratio:>10}")


def probe(conn: ConnectionParams, password: str, all_rows: bool, csv_path: Path, out: Report) -> None:
    """Run the whole diagnostic on one association - read-only throughout."""
    driver = create_driver(_MODEL, conn, password=password)

    out(f"[*] {_MODEL} @ {conn.endpoint} - connecting (read-only, one association)")
    driver.connect()
    try:
        meter_serial = driver.read_meter_serial()
        out(f"[+] connected - meter serial: {meter_serial}")

        rows, positions, entries_in_use, span = _read_raw_buffer(driver)
        out("")
        out(f"=== Billing profile {BILLING_PROFILE_OBIS} ===")
        out(f"    entries_in_use: {entries_in_use}   rows returned: {len(rows)}")
        out(f"    span: {driver.BILLING_COLUMN_SPAN} columns   mapped: {len(_MAPPED_BILLING_COLUMNS)}")
        if not rows:
            out("    buffer is empty - nothing to check")
            return

        _report_meter_declared_classes(driver, span, out)

        suspicious: list[str] = []
        for index in range(len(rows)) if all_rows else [0]:
            label = "Open Period (entry 1)" if index == 0 else f"closed period (entry {index + 1})"
            out("")
            out(f"=== SCALING CHAIN - {label} ===")
            suspicious = _report_chain(driver, rows[index], positions, out)

        out("")
        out("=== SUSPICIOUS COLUMNS (from the last chain above) ===")
        if suspicious:
            for item in suspicious:
                out(f"    ! {item}")
        else:
            out("    none - every column resolved its own scaler at a plausible multiplier")

        _write_csv(driver, rows, positions, meter_serial, csv_path, out)

        # The shipped read, so the cross-check compares against what the product
        # actually stores rather than against this script's arithmetic.
        billing_rows = driver.read_billing()
        out("")
        out(f"[*] driver.read_billing() -> {len(billing_rows)} row(s)")
        if billing_rows:
            _cross_check_registers(driver, billing_rows[0].as_columns(), out)
    finally:
        driver.disconnect()
        out("")
        out("[*] disconnected - nothing was written to the meter")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only SMW110W4 billing scaler/unit diagnostic.")
    transport = parser.add_mutually_exclusive_group(required=True)
    transport.add_argument("--host", help="Meter IP address (TCP transport)")
    transport.add_argument("--serial-port", help="COM port, e.g. COM4 (serial transport)")
    parser.add_argument("--port", type=int, default=4059, help="Meter TCP port (default 4059)")
    parser.add_argument("--baud-rate", type=int, default=19200, help="Serial baud rate (default 19200)")
    parser.add_argument(
        "--password",
        required=True,
        help="DLMS password (never printed, never written to the report). Required "
        "on purpose - a diagnostic must not authenticate with a constant that can go "
        "stale without anyone noticing (docs/meter-notes/smw110w4-scan.md).",
    )
    parser.add_argument("--all-rows", action="store_true", help="Report the chain for every billing row")
    parser.add_argument(
        "--out",
        help="Report file (default billing-scalers-<timestamp>.txt in the current directory)",
    )
    parser.add_argument(
        "--csv",
        help="Machine-diffable dump of every row x every mapped column "
        "(default billing-scalers-<timestamp>.csv in the current directory)",
    )
    parser.add_argument("--verbose", action="store_true", help="Show driver logs on the console")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    if args.host:
        conn = ConnectionParams.net(args.host, args.port)
    else:
        conn = ConnectionParams.serial(args.serial_port, baud_rate=args.baud_rate)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = Path(args.out) if args.out else Path.cwd() / f"billing-scalers-{stamp}.txt"
    csv_path = Path(args.csv) if args.csv else Path.cwd() / f"billing-scalers-{stamp}.csv"
    out = Report(out_path)

    out(f"### Mitsubishi SMW110W4 billing scaler probe @ {conn.endpoint}")
    out(f"# probed {datetime.now().isoformat(timespec='seconds')}  (read-only, one association)")
    out("# password supplied on the command line - deliberately not recorded here")
    out("")

    try:
        probe(conn, args.password, args.all_rows, csv_path, out)
    except Exception as exc:  # noqa: BLE001 - the report must survive any failure.
        out("")
        out(f"[!] probe failed: {type(exc).__name__}: {exc}")
        return 1
    finally:
        out("")
        out(f"[*] report written to {out_path}")
        out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
