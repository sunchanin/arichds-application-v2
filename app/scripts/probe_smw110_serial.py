"""Probe a Mitsubishi SMW110W4 and prove its load profile can be read.

**This is a field diagnostic, run on the customer's machine, not part of the
product.** It answers the questions a Gurux Director export cannot: the export
carries the association object list (``<LN>`` + ``<Access>``) and nothing else —
no capture objects, no capture period, no entries in use, and no evidence that
any particular read *service* is accepted. Those are exactly what the M4 driver
must be built against.

Why this model needs its own probe rather than the existing ones:

* ``scripts/probe_meter.py`` and ``scripts/probe_capture_objects.py`` both go
  through ``create_driver()``, and at the time this script was written v2 had
  **no SMW110 driver** and **no serial transport** — ``ConnectionParams``
  carried a ``SERIAL`` enum member but only a ``net()`` constructor, and
  ``transport_args()`` hardcoded ``-h/-p``. So this script builds the
  GXSettings argv itself. (Delivered at M4a by issue #9 — this script's own
  code is left as it was, a frozen record of the probe run.)
* The customer's site turned out to hold **two units of one model**, not two
  models. Both nameplates read ``SMW110-C47E (ADVANCE)`` / ``SMW110W4-N141C600``
  and differ only in ID code (``0123 2002893`` and ``0123 2002892``). The wire
  agrees: ``0.0.96.1.1.255`` answers ``SMW110W4-N141C600`` on the probed unit and
  in v1's own saved export of the older meter, and ``0.0.42.0.0.255`` answers
  ``MAT-SMW110`` on both.
* **Transport is a property of the installation, not of the model.** The device
  collection ``swm110W.gxc`` (2026-08-07) holds both units with *identical*
  client address (6), password and timeouts — differing only in media: one
  serial on ``COM4``, one TCP on ``192.168.1.31:4059``. The catalog's assumption
  that a model is serial-only (``supports_serial=True``/``default_port=None``)
  does not survive that.

Findings this script produced that no export could (probed 2026-08-07):

* the real serial lives on the Mitsubishi register ``1.0.199.128.134.255``
  (``1232002893``, matching the nameplate ID code) while the standard
  ``0.0.96.1.0.255`` answers the placeholder ``99999999`` — **and that register
  is absent from the association export yet reads fine**, which is why "not in
  the object list" is never evidence that a meter refuses something;
* Logger 2 (``1.0.99.2.0.255``) is declared in the object list and answers
  "undefined object" when read — declared is not readable;
* the buffer is entry-access only (``readRowsByRange`` → "Read-Write denied");
* **entry 1 is the OLDEST row** here, the opposite of what v1 found on a
  Premier 550 — which is why the order is verified per model, never assumed.

Read-only, one association, nothing written to the meter and nothing to any
database. Every step is wrapped so a refused object reports itself and the run
continues — a diagnostic that stops diagnosing at the first refusal is worthless
on exactly the meter you most need it for.

Usage on the customer machine — exactly one of ``--port`` (serial; the COM port
must be free, so close GXDLMSDirector first) or ``--host`` (TCP)::

    probe_smw110_serial.exe --port COM4 --password <password>
    probe_smw110_serial.exe --host 192.168.1.31 --password <password>
    probe_smw110_serial.exe --list-ports          # touches no meter

From a checkout::

    app\\.venv\\Scripts\\python.exe scripts\\probe_smw110_serial.py ^
        --port COM4 --password <password>

The password is a CLI argument on purpose: it is a customer credential, so it is
never hardcoded, never printed, and never written into the report file.

Bring the report back and commit it under ``docs/meter-notes/raw/`` next to the
CEWE captures, then write up what it settles in ``docs/meter-notes/``.
"""

from __future__ import annotations

import argparse
import math
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Allow running straight from a checkout without installing the package. When
# frozen by PyInstaller the package is bundled and there is no src/ next to us.
if not getattr(sys, "frozen", False):
    _SRC = Path(__file__).resolve().parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))

from gurux_dlms import GXDLMSClient, GXReplyData  # noqa: E402
from gurux_dlms.enums import DataType, ObjectType, Unit  # noqa: E402
from gurux_dlms.objects import (  # noqa: E402
    GXDLMSCaptureObject,
    GXDLMSClock,
    GXDLMSData,
    GXDLMSObject,
    GXDLMSProfileGeneric,
    GXDLMSRegister,
)

from arichds.acquisition.drivers._gurux_trace import silence_frame_trace  # noqa: E402
from arichds.vendor.gurux import GXDLMSReader, GXSettings  # noqa: E402

# ── What to probe ────────────────────────────────────────────────────────────
#
# Every OBIS below was confirmed present in the customer's association export
# (test.xml, 2026-08-07) — this script does NOT call getAssociationView(),
# which is far too slow over a 19200-baud serial link and unnecessary when the
# object list is already known.

# Identity candidates. All are class 1 (Data) in the export, attr 2, no scaler.
# The real serial is whichever of these answers something that is not a
# placeholder — that is the finding, not an assumption.
IDENTITY_OBIS: tuple[str, ...] = (
    # The COSEM standard identity object — manufacturer ID + a unique number.
    # Probed 2026-08-07: 0.0.96.1.0.255 answers the placeholder "99999999" and
    # this model has no 1.0.199.* manufacturer registers, so this is the last
    # standard place a real serial could be hiding. ADR 0005 needs one.
    "0.0.42.0.0.255",
    # The Mitsubishi manufacturer register that carries the REAL serial on the
    # unit v1 read (swm.xml, 2026-07-24: "1252008102"). The association export
    # from this unit does not list it — but "absent from an export" and "the
    # meter refuses it" are different facts, and only one of them is evidence.
    # Read it directly and let the meter answer. ADR 0005 turns on this.
    "1.0.199.128.134.255",
    "0.0.96.1.0.255",
    "0.0.96.1.1.255",
    "0.0.96.1.2.255",
    "0.0.96.1.3.255",
    "0.0.96.1.4.255",
    "0.0.96.1.5.255",
    "0.0.96.1.6.255",
    "0.0.96.1.8.255",
    "0.0.96.1.9.255",
    "0.0.96.1.10.255",
    "0.0.96.1.12.255",
    "0.0.96.1.13.255",
    "0.0.96.1.14.255",
    "0.0.96.1.21.255",
)

CLOCK_OBIS = "0.0.1.0.0.255"

# Profile Generics worth reading, in priority order. Load profile first: if the
# link dies partway, the run must already have answered the M4 question.
LOAD_PROFILES: tuple[tuple[str, str], ...] = (
    ("1.0.99.1.0.255", "Load profile, recording period 1 (Logger 1)"),
    ("1.0.99.2.0.255", "Load profile, recording period 2 (Logger 2)"),
)
BILLING_PROFILES: tuple[tuple[str, str], ...] = (
    ("1.0.98.1.0.255", "Billing scheme 1, prefix 1.0 (SMW110W uses this one)"),
    ("0.0.98.1.0.255", "Billing scheme 1, prefix 0.0 (SMART TCC uses this one)"),
    ("1.0.98.2.0.255", "Billing scheme 2, prefix 1.0"),
    ("0.0.98.2.0.255", "Billing scheme 2, prefix 0.0"),
)

ATTR_VALUE = 2
ATTR_SCALER_UNIT = 3
ATTR_CAPTURE_OBJECTS = 3
ATTR_CAPTURE_PERIOD = 4
ATTR_ENTRIES_IN_USE = 7

# Serial line format from the customer's Director dialog: 8 data bits, no
# parity, one stop bit -> the "-S" FORMAT tag GXSettings expects.
SERIAL_FORMAT = "8None1"


class Report:
    """Write every line to the console and to the report file at once.

    The engineer running this watches the console; the file is the artifact that
    comes back to the repo. Keeping them identical means the thing you read on
    site is the thing that gets committed.

    Output is deliberately **ASCII-only** — a Windows console defaults to cp1252
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


def to_dt(value: Any) -> datetime | None:
    """Coerce whatever Gurux hands back for a time column into a datetime.

    A buffer timestamp arrives as ``GXDateTime`` (datetime on ``.value``), a
    plain ``datetime``, raw ``bytes`` when the column schema was not cached, or
    ``None`` on a time-compressed row. Defensive on purpose — patterns.md.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    inner = getattr(value, "value", None)
    if isinstance(inner, datetime):
        return inner
    if isinstance(value, (bytes, bytearray)):
        try:
            decoded = GXDLMSClient.changeType(value, DataType.DATETIME)
        except Exception:  # noqa: BLE001 — an undecodable cell is data, not a crash
            return None
        inner = getattr(decoded, "value", None)
        if isinstance(inner, datetime):
            return inner
    return None


def build_args(
    script: str,
    transport: list[str],
    client: int,
    password: str,
) -> list[str]:
    """Return the GXSettings argv for this meter.

    Every protocol flag traces to the customer's Director profile: HDLC,
    Logical Name referencing, Authentication Low, Client Address 6, Logical
    Server 0, Physical Server 1. Only *transport* varies.

    **This model is reached over either transport.** The customer's device
    collection (``swm110W.gxc``, 2026-08-07) holds two SMW110W4 meters whose
    profiles differ in nothing but the media: one serial on ``COM4``, one TCP on
    ``192.168.1.31:4059`` — same client address, same password, same timeouts.
    So transport is a property of the installation, not of the model, and the
    caller passes the fragment in rather than this function assuming serial.

    ``-l 0`` is the one that is easy to miss: the logical server address is
    combined with ``-s`` and must be sent explicitly.
    """
    return [
        script,
        *transport,
        "-i", "HDLC",
        "-r", "ln",
        "-c", str(client),
        "-s", "1",
        "-l", "0",
        "-a", "Low",
        "-P", password,
        "-t", "Error",
    ]  # fmt: skip


def describe_ports() -> list[str]:
    """Return one line per serial port Windows currently reports.

    A COM port number belongs to the USB-serial adapter, not to the meter, and
    Windows re-issues it when the adapter moves socket or is re-enumerated — so
    the number in a saved Director profile goes stale on its own. ``WinError 2``
    ("the system cannot find the file specified") is what an absent port looks
    like, and on its own it sends people to check the meter, the cable and the
    password, none of which is wrong. Printing the ports that *do* exist turns
    that dead end into the next step.
    """
    try:
        from serial.tools import list_ports
    except Exception as exc:  # noqa: BLE001 — never let the diagnostic break the diagnostic
        return [f"(could not enumerate ports: {type(exc).__name__}: {exc})"]
    found = sorted(list_ports.comports(), key=lambda p: p.device)
    if not found:
        return ["(none - Windows reports no serial ports at all; is the USB adapter plugged in?)"]
    return [f"{p.device:<8} {p.description}" for p in found]


def open_association(args: list[str], timeout_ms: int) -> tuple[Any, Any, Any]:
    """Open one association and return ``(client, reader, media)``.

    Mirrors ``DlmsDriver._open_association`` deliberately — same order, same
    timeouts on both the media and the reader, and ``silence_frame_trace``
    before a single frame moves. That call is not optional: the vendored reader
    writes an unredacted frame trace **containing the password** to
    ``logFile.txt`` next to the executable regardless of trace level, and this
    script runs on a customer's machine.
    """
    settings = GXSettings()
    if settings.getParameters(args) != 0:
        raise RuntimeError("GXSettings rejected the parameter list")

    client = settings.client
    media = settings.media
    if hasattr(media, "receiveTimeout"):
        media.receiveTimeout = timeout_ms

    reader = GXDLMSReader(client, media, settings.trace, settings.invocationCounter)
    silence_frame_trace(reader)
    reader.waitTime = timeout_ms

    media.open()
    reader.initializeConnection()
    return client, reader, media


def probe_identity(out: Report, client: Any, reader: Any) -> None:
    """Read every identity candidate and print what it actually answers."""
    out("=" * 78)
    out("IDENTITY CANDIDATES  (class 1 Data, attr 2)")
    out("=" * 78)
    out("The SMW110W keeps its real serial on 1.0.199.128.134.255 because the")
    out("standard 0.0.96.1.0.255 returns the placeholder 99999999. This meter has")
    out("no 1.0.199.* objects at all, so the serial OBIS has to be picked from what")
    out("these actually return.")
    out()
    for obis in IDENTITY_OBIS:
        try:
            obj = GXDLMSData(obis)
            client.objects.append(obj)
            value = reader.read(obj, ATTR_VALUE)
            if isinstance(value, (bytes, bytearray)):
                shown = f"{value.decode('ascii', 'replace')!r}  (raw {bytes(value).hex()})"
            else:
                shown = repr(value)
            out(f"  {obis:<20} {shown}")
        except Exception as exc:  # noqa: BLE001 — a refused object must not end the report
            out(f"  {obis:<20} !! {type(exc).__name__}: {exc}")
    out()


def probe_clock(out: Report, client: Any, reader: Any) -> datetime | None:
    """Read the meter clock — the anchor for the selective-access range test.

    Using the meter's own time beats assuming UTC+7: these meters store buffer
    timestamps in local time, and asking the meter what time it thinks it is
    removes the guess entirely.
    """
    out("=" * 78)
    out("METER CLOCK  (0.0.1.0.0.255 attr 2)")
    out("=" * 78)
    try:
        obj = GXDLMSClock(CLOCK_OBIS)
        client.objects.append(obj)
        value = reader.read(obj, ATTR_VALUE)
        when = to_dt(value)
        out(f"  meter time : {when}   (host time: {datetime.now()})")
        if when is not None:
            out(f"  offset host->meter: {when - datetime.now()}")
        out()
        return when
    except Exception as exc:  # noqa: BLE001
        out(f"  !! {type(exc).__name__}: {exc}")
        out()
        return None


def read_schema(out: Report, client: Any, reader: Any, obis: str, label: str) -> dict[str, Any] | None:
    """Read one ProfileGeneric's period, entry count and column layout.

    Returns the schema dict, or None when the profile could not be read at all.
    A failed *period* read is not a dead profile (patterns.md: some companion
    profiles answer "Read-Write denied" for the period yet still serve their
    capture list), so it is reported and the read continues.
    """
    out("-" * 78)
    out(f"{obis}   {label}")
    out("-" * 78)

    pg = GXDLMSProfileGeneric(obis)
    client.objects.append(pg)

    period: Any = None
    try:
        reader.read(pg, ATTR_CAPTURE_PERIOD)
        period = getattr(pg, "capturePeriod", None)
    except Exception as exc:  # noqa: BLE001
        out(f"  capture period : !! {type(exc).__name__}: {exc}")

    entries: int | None = None
    try:
        entries = int(reader.read(pg, ATTR_ENTRIES_IN_USE))
    except Exception as exc:  # noqa: BLE001
        out(f"  entries in use : !! {type(exc).__name__}: {exc}")

    try:
        reader.read(pg, ATTR_CAPTURE_OBJECTS)
    except Exception as exc:  # noqa: BLE001
        out(f"  capture objects: !! {type(exc).__name__}: {exc}")
        out("  -> cannot read this profile's column layout; skipping its rows")
        out()
        return None

    captured = list(getattr(pg, "captureObjects", None) or [])
    if not captured:
        out("  capture objects: none reported")
        out()
        return None

    columns = [
        (str(obj.logicalName), int(getattr(cap, "attributeIndex", 0)), int(obj.objectType)) for obj, cap in captured
    ]

    out(f"  capture period : {period if period is not None else 'unknown'} s")
    out(f"  entries in use : {entries if entries is not None else 'unknown'}")
    out(f"  columns        : {len(columns)}")
    for logical_name, attr, class_id in columns:
        out(f"      {logical_name:<22} attr={attr} class={class_id}")
    out()
    return {"pg": pg, "obis": obis, "period": period, "entries": entries, "columns": columns}


def unit_name(code: Any) -> str:
    """Render a DLMS unit code as its name — ``27`` alone reads as nothing.

    The unit is the whole point of this pass: it is what says whether a sibling
    measures the same thing as the column borrowing from it. ``ACTIVE_POWER``
    and ``ACTIVE_ENERGY`` are one digit apart as codes and worlds apart as
    answers.
    """
    if code is None:
        return "none"
    try:
        return f"{Unit(int(code)).name}({int(code)})"
    except Exception:  # noqa: BLE001 — an unknown code is still worth printing
        return str(code)


def scaler_siblings(obis: str) -> list[str]:
    """Return OBIS codes that should carry the same scaler as *obis*.

    An OBIS code is ``A.B.C.D.E.F``: C is the quantity, D the processing method.
    A meter that refuses attr 3 on a capture column may still serve it on a
    sibling measuring the same physical quantity a different way — v1 relied on
    exactly this (interval energy borrowing the cumulative D=8 register's
    scaler, cumulative demand D=2 borrowing D=6). The unit is a property of the
    quantity, not of how it was averaged, so the borrow is sound.

    Candidates, in order: D=7 (instantaneous), D=8 (time integral / energy),
    D=6 (maximum demand). This is a **search reported as a search** — the probe
    prints which sibling actually answered, so nothing is assumed.
    """
    parts = obis.split(".")
    if len(parts) != 6:
        return []
    a, b, c, d, e, f = parts
    return [f"{a}.{b}.{c}.{candidate}.{e}.{f}" for candidate in ("8", "7", "6") if candidate != d]


def probe_scalers(out: Report, client: Any, reader: Any, schema: dict[str, Any]) -> None:
    """Read each captured column's ``scaler_unit`` so raw buffer cells can be scaled.

    A ProfileGeneric buffer hands back **raw integers**. Gurux only applies a
    multiplier when it parses a Register object whose attr 3 it has read, and
    the capture list is not made of such objects — so every numeric cell in a
    load-profile row is unscaled until something reads the sibling register's
    ``scaler_unit`` and multiplies. Without this the driver cannot honour the
    project's "always kWh" contract; it can only return integers of unknown
    magnitude.

    **This is the register ADR 0002 exists for.** ``obj.scaler`` is the
    *multiplier* (10**exponent), not the exponent — v1 read it as an exponent
    and produced values ten times too large wherever the exponent was not 0.
    Reported here as raw, exponent, multiplier and scaled value together so the
    arithmetic is checkable by eye rather than trusted.

    A column that cannot be read standalone is a finding, not a failure: v1 hit
    exactly that and had to borrow a sibling OBIS's scaler (cumulative demand
    D=2 borrowing the D=6 scaler). Which columns need that is what this prints.
    """
    out("  --- scaler_unit per captured column (attr 3) ---")
    out("  raw buffer cells are unscaled; these are the multipliers that make them engineering units")
    out("  probed 2026-08-07: this meter denies attr 3 on EVERY capture column, so each one")
    out("  falls back to a sibling OBIS carrying the same physical quantity (v1 did the same).")
    for logical_name, _attr, class_id in schema["columns"]:
        if class_id not in (3, 4):  # Register / ExtendedRegister only
            out(f"    {logical_name:<22} class={class_id} - not a Register, no scaler")
            continue
        out(f"    {logical_name}")
        answered = 0
        for source in (logical_name, *scaler_siblings(logical_name)):
            label = "itself" if source == logical_name else f"sibling {source}"
            try:
                obj = GXDLMSRegister(source)
                client.objects.append(obj)
                reader.read(obj, ATTR_SCALER_UNIT)
                multiplier = float(obj.scaler)
                exponent = int(round(math.log10(multiplier))) if multiplier > 0 else 0
                scaled = reader.read(obj, ATTR_VALUE)
                out(
                    f"        {label:<30} exp={exponent:<4} multiplier={multiplier:<9g} "
                    f"unit={unit_name(getattr(obj, 'unit', None))}  (its own value: {float(scaled):g})"
                )
                answered += 1
            except Exception as exc:  # noqa: BLE001 — a refusal is the measurement
                out(f"        {label:<30} {str(exc).strip()}")
        if not answered:
            out(f"        ^ NOTHING answered - {logical_name} cannot be scaled from this meter")
    out("  NOTE: pick the sibling whose UNIT matches what the column measures, not merely")
    out("  the first that answers. Interval energy (D=29, Wh) must not borrow from")
    out("  instantaneous power (D=7, W) - same quantity, different unit, different scaler.")
    out()


def probe_column_prefix_ladder(
    out: Report,
    client: Any,
    reader: Any,
    schema: dict[str, Any],
    count: int,
) -> None:
    """Find the widest column prefix this meter will serve from a profile.

    A billing profile with 242 capture columns refuses a full-width
    ``readRowsByEntry`` with *"Data Block Unavailable"* — the reply does not fit
    what the firmware will assemble. Gurux can request a column subset
    (``readRowsByEntry(pg, index, count, columns)``), and v1 established on this
    exact profile (field probe round 5, 2026-07-24) how this firmware treats one:

    * **only a prefix of the column table is ever accepted** — every selection
      must start at capture column 1. A span starting at column 2, or a single
      column at position 3 or 28, is refused. So there is no point bisecting
      inside the table; the only free variable is the width.
    * on v1's unit the ceiling was **43**: width 43 returned every billing row
      correctly, 55 and 68 answered *"scope of access violated"* (a permissions
      wall, not a size limit), and 93 and full width answered *"Data Block
      Unavailable"*.

    This walks the candidate widths downwards and stops at the first one that
    reads, so the output shows both the ceiling and the shape of the wall above
    it. Each rung must parse the reply against **only the requested span** —
    hence swapping ``pg.captureObjects`` and restoring it in a ``finally``.
    """
    pg, columns = schema["pg"], schema["columns"]
    full = list(pg.captureObjects)
    widths = [w for w in (len(full), 93, 68, 55, 43, 20, 10, 1) if 0 < w <= len(full)]

    out(f"  --- column-prefix ladder ({len(full)} capture columns) ---")
    for width in widths:
        span = full[:width]
        original = pg.captureObjects
        try:
            request = client.readRowsByEntry(pg, 1, count, span)
            reply = GXReplyData()
            reader.readDataBlock(request, reply)
            pg.captureObjects = span
            rows = client.updateValue(pg, ATTR_VALUE, reply.value)
        except Exception as exc:  # noqa: BLE001 — a rejected width is the measurement
            out(f"    width {width:>4}: REJECTED - {type(exc).__name__}: {str(exc).strip()}")
            continue
        finally:
            pg.captureObjects = original

        out(f"    width {width:>4}: OK - {len(list(rows))} row(s) returned")
        show_rows(out, rows, columns[:width], count)
        out(f"    CEILING: this meter serves a {width}-column prefix of this profile.")
        if width < len(full):
            out(f"    The {len(full) - width} column(s) above it cannot be read this way -")
            out("    whatever the driver needs must live inside the prefix.")
        out()
        return

    out("    every width was rejected, down to a single column - this profile's")
    out("    rows cannot be read by entry at all on this meter.")
    out()


def show_rows(out: Report, rows: Any, columns: list[tuple[str, int, int]], limit: int) -> list[datetime | None]:
    """Print up to *limit* rows and return every row's first timestamp column.

    The timestamps are what settle entry ordering — v1 found entry 1 to be the
    *newest* on a Premier 550 and the checklist says to verify that per model
    rather than assume it.
    """
    stamps: list[datetime | None] = []
    for index, row in enumerate(list(rows)[:limit]):
        cells = list(row)
        stamp = to_dt(cells[0]) if cells else None
        stamps.append(stamp)
        rendered = []
        for position, cell in enumerate(cells):
            name = columns[position][0] if position < len(columns) else "?"
            as_dt = to_dt(cell)
            rendered.append(f"{name}={as_dt if as_dt is not None else cell!r}")
        out(f"    [{index}] " + "  ".join(rendered))
    return stamps


def probe_rows(out: Report, reader: Any, schema: dict[str, Any], sample: int) -> None:
    """Prove the buffer can actually be pulled, and record which service works.

    Three separate findings, each of which the driver at M4 needs and none of
    which an object list can tell you:

    1. does ``readRowsByEntry`` work, and is entry 1 the oldest or the newest;
    2. does ``readRowsByRange`` (selective access by time) work at all — the
       SMW110W answers "Read-Write denied" to it and accepts entry access only;
    3. do the returned rows line up with the capture-object column list.
    """
    pg, entries, columns = schema["pg"], schema["entries"], schema["columns"]

    out(f"  --- rows by ENTRY (first {sample}) ---")
    head_stamps: list[datetime | None] = []
    try:
        head_stamps = show_rows(out, reader.readRowsByEntry(pg, 1, sample), columns, sample)
    except Exception as exc:  # noqa: BLE001
        out(f"    !! readRowsByEntry(1, {sample}) failed: {type(exc).__name__}: {exc}")

    tail_stamps: list[datetime | None] = []
    if entries and entries > sample:
        start = max(1, entries - sample + 1)
        out(f"  --- rows by ENTRY (last {sample}, starting at {start} of {entries}) ---")
        try:
            tail_stamps = show_rows(out, reader.readRowsByEntry(pg, start, sample), columns, sample)
        except Exception as exc:  # noqa: BLE001
            out(f"    !! readRowsByEntry({start}, {sample}) failed: {type(exc).__name__}: {exc}")

    first = next((s for s in head_stamps if s is not None), None)
    last = next((s for s in tail_stamps if s is not None), None)
    if first and last:
        order = "entry 1 = NEWEST (descending)" if first > last else "entry 1 = OLDEST (ascending)"
        out(f"  ORDER: {order}   first={first}  last={last}")
    elif first:
        out(f"  ORDER: undetermined - only one end read (first={first})")
    out()


def probe_by_range(out: Report, reader: Any, schema: dict[str, Any], meter_now: datetime | None, hours: int) -> None:
    """Try selective access by time, anchored on the meter's own clock."""
    out(f"  --- rows by RANGE (last {hours} h, meter-local time) ---")
    if meter_now is None:
        out("    skipped: the meter clock could not be read, so there is no")
        out("    trustworthy anchor - guessing UTC+7 here would make a failure")
        out("    unattributable (wrong window vs unsupported service).")
        out()
        return
    start = meter_now - timedelta(hours=hours)
    try:
        rows = list(reader.readRowsByRange(schema["pg"], start, meter_now))
        out(f"    OK - {len(rows)} row(s) for {start} .. {meter_now}")
        show_rows(out, rows, schema["columns"], 3)
    except Exception as exc:  # noqa: BLE001
        out(f"    !! failed: {type(exc).__name__}: {exc}")
        out("    (the SMW110W answers 'Read-Write denied' here and takes entry access only)")
    out()


def restore_schema(client: Any, schema: dict[str, Any]) -> None:
    """Re-attach the capture-object layout so Gurux can parse the raw buffer.

    ``readRowsByRange`` returns a binary buffer that Gurux decodes against the
    profile's captureObjects. Reading attr 3 already populated them on this
    connection, so this is a no-op guard for the case where the list came back
    empty and the columns are known from the schema dict instead.
    """
    pg = schema["pg"]
    if getattr(pg, "captureObjects", None):
        return
    for logical_name, attr, class_id in schema["columns"]:
        obj = GXDLMSObject(ObjectType(class_id))
        obj.logicalName = logical_name
        pg.captureObjects.append((obj, GXDLMSCaptureObject(attr, 0)))
    client.objects.append(pg)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only SMW110 serial probe: identity, capture objects, and real load-profile rows.",
    )
    parser.add_argument("--port", help="Serial port, e.g. COM4 (omit when using --host)")
    parser.add_argument("--baud", type=int, default=19200, help="Baud rate (default 19200)")
    parser.add_argument("--host", help="Meter IP for a TCP-connected unit, e.g. 192.168.1.31")
    parser.add_argument("--tcp-port", type=int, default=4059, help="TCP port (default 4059)")
    parser.add_argument("--client", type=int, default=6, help="DLMS client address (default 6 - SMW110W uses 5)")
    parser.add_argument("--password", help="DLMS password (never printed, never written to the report)")
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="List the serial ports this machine has and exit - touches no meter",
    )
    parser.add_argument("--sample", type=int, default=6, help="Rows to read from each end of a buffer (default 6)")
    parser.add_argument("--range-hours", type=int, default=24, help="Window for the by-range test (default 24)")
    parser.add_argument("--timeout", type=int, default=10000, help="Media/reader timeout in ms (default 10000)")
    parser.add_argument("--skip-billing", action="store_true", help="Load profile only - the fastest useful run")
    parser.add_argument(
        "--out",
        default="",
        help="Report file (default smw110-probe-<timestamp>.txt in the current directory)",
    )
    args = parser.parse_args()

    if args.list_ports:
        print("Serial ports on this machine:")
        for line in describe_ports():
            print(f"  {line}")
        return 0
    if not args.password or bool(args.port) == bool(args.host):
        parser.error("give exactly one of --port (serial) or --host (TCP), plus --password")

    if args.host:
        transport = ["-h", args.host, "-p", str(args.tcp_port)]
        endpoint = f"{args.host}:{args.tcp_port}"
    else:
        transport = ["-S", f"{args.port}:{args.baud}:{SERIAL_FORMAT}"]
        endpoint = f"{args.port}:{args.baud} {SERIAL_FORMAT}"

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = Path(args.out) if args.out else Path.cwd() / f"smw110-probe-{stamp}.txt"
    out = Report(out_path)

    out(f"### Mitsubishi SMW110 @ {endpoint}")
    out(f"# probed {datetime.now().isoformat(timespec='seconds')}  (read-only, one association)")
    out(f"# HDLC / LN / auth Low / client {args.client} / physical server 1 / logical server 0")
    out("# password supplied on the command line - deliberately not recorded here")
    out()
    if args.port:
        # Recorded on every serial run: which port answered is only
        # interpretable next to which ports existed, and the adapter's COM
        # number changes on its own.
        out("Serial ports present on this machine at probe time:")
        for line in describe_ports():
            out(f"  {line}")
        out()

    client = reader = media = None
    try:
        hint = (
            "close GXDLMSDirector first, a COM port is exclusive"
            if args.port
            else "TCP - the meter may also refuse a second association"
        )
        out(f"[*] opening {endpoint} - {hint}")
        client, reader, media = open_association(
            build_args(Path(sys.argv[0]).name, transport, args.client, args.password),
            args.timeout,
        )
        out("[+] associated")
        out()

        probe_identity(out, client, reader)
        meter_now = probe_clock(out, client, reader)

        out("=" * 78)
        out("LOAD PROFILES")
        out("=" * 78)
        for obis, label in LOAD_PROFILES:
            schema = read_schema(out, client, reader, obis, label)
            if schema is None:
                continue
            probe_scalers(out, client, reader, schema)
            probe_rows(out, reader, schema, args.sample)
            restore_schema(client, schema)
            probe_by_range(out, reader, schema, meter_now, args.range_hours)

        if not args.skip_billing:
            out("=" * 78)
            out("BILLING PROFILES  (which prefix this model uses is the open question)")
            out("=" * 78)
            for obis, label in BILLING_PROFILES:
                schema = read_schema(out, client, reader, obis, label)
                if schema is not None:
                    # Full-width entry access is what fails on this profile, so
                    # go straight to the ladder that finds what does work.
                    probe_column_prefix_ladder(out, client, reader, schema, min(args.sample, 3))
    except Exception as exc:  # noqa: BLE001 — the report must survive any failure
        out()
        out("!!! ABORTED")
        out(traceback.format_exc())
        if "cannot find the file specified" in str(exc) or "WinError 2" in str(exc):
            out(f"DIAGNOSIS: {args.port} does not exist on this machine right now.")
            out("The meter did not refuse anything - the port was never opened. A COM number")
            out("belongs to the USB-serial adapter and Windows re-issues it when the adapter")
            out("moves socket, so a number saved in a Director profile goes stale by itself.")
            out("Ports that DO exist are listed at the top of this report; re-run with one of")
            out("them, or plug the adapter back in. (An in-use port fails differently:")
            out("'Access is denied', WinError 5 - that one means close GXDLMSDirector.)")
        return 1
    finally:
        try:
            if reader is not None:
                reader.close()
        except Exception:  # noqa: BLE001 — cleanup must never raise
            pass
        out()
        out(f"[*] disconnected - report written to {out_path}")
        out.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
