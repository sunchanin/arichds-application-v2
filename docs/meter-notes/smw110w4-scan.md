# Mitsubishi SMW110W4 — read off two real meters, 2026-08-07

Field evidence from a customer site, not a datasheet. Two meters were probed
end to end with `app/scripts/probe_smw110_serial.py`; the raw reports are
[`raw/smw110w4-serial-probe-2026-08-07.txt`](raw/smw110w4-serial-probe-2026-08-07.txt)
and [`raw/smw110w4-tcp-probe-2026-08-07.txt`](raw/smw110w4-tcp-probe-2026-08-07.txt).

This document covers the **units at that site**. The older Mitsubishi meter v1
read in July 2026 is a different unit and keeps its own record in
[`mitsu-obis-scan.md`](mitsu-obis-scan.md) — that file stays as it was written;
where the two disagree, the disagreement is called out below rather than edited
away.

## The two meters are one model

The site was reported as holding "two different models". It does not. Every
model-level identifier matches on the nameplate **and** on the wire:

| | Meter A | Meter B |
|---|---|---|
| Nameplate TYPE | `SMW110-C47E (ADVANCE)` | `SMW110-C47E (ADVANCE)` |
| Nameplate model code | `SMW110W4-N141C600` | `SMW110W4-N141C600` |
| Nameplate ID code | `0123 2002893` | `0123 2002892` |
| Nameplate year | 2023 | 2023 |
| `0.0.96.1.1.255` (wire) | `SMW110W4-N141C600` | `SMW110W4-N141C600` |
| `0.0.42.0.0.255` (wire) | `MAT-SMW110` | `MAT-SMW110` |
| **`1.0.199.128.134.255`** | **`1232002893`** | **`1232002892`** |
| Transport | Serial `COM4` 19200 8N1 | **TCP `192.168.1.31:4059`** |

The serial read off the wire is the nameplate ID code with its leading zero and
space removed — `0123 2002893` → `1232002893`. That closes the identity loop:
the register is not merely *a* number that looks like a serial, it is the number
printed on the meter.

Both are three-phase 4-wire, 5(10) A, class 0.5S, 5000 imp/kWh.

## Connection

Identical on both units except the media. From the customer's Gurux Director
device collection and confirmed by a successful association:

| | |
|---|---|
| Interface | HDLC |
| Referencing | LN (logical name) |
| Client address | **6** |
| Server address | physical 1 + logical 0 — `-l 0` must be sent explicitly |
| Authentication | Low (LLS, password only) |
| Security | none |
| Serial line | 19200 8N1, no flow control |
| TCP | port 4059 |

> **v1 hardcodes client address 5** for the SMW110 (`cewe-worker/src/drivers/smw110.py`).
> Neither meter at this site answers on 5. Whether the address is a per-model
> constant or a per-device setting is **not settled** — both units here use 6,
> and the only 5 ever seen came from a superseded Director profile. Do not port
> v1's constant unexamined.

**Transport is a property of the installation, not of the model.** One model,
one site, both transports at once. `catalog.py` currently encodes the opposite
(`smw110` has `supports_serial=True`, `default_port=None`, i.e. serial-only);
that is falsified and a device on `192.168.1.31` could not be created under it.

## Load profile — `1.0.99.1.0.255`

Identical on both units: same 20 columns, same order, same period.

| | |
|---|---|
| Capture period | **900 s** |
| Entries in use | **8640** (a full ring — ~90 days) |
| Columns | **20** |
| Access | **`readRowsByEntry` only** — `readRowsByRange` answers *"Read-Write denied"* |
| Entry order | **entry 1 is the OLDEST row (ascending)** |

Confirmed with real timestamps: entry 1 read `2026-05-09 10:30`, the tail read
`2026-08-07 09:00`. Two runs 14 minutes apart showed the window sliding by
exactly one 15-minute slot with `entries_in_use` unchanged at 8640 — a full
circular buffer behaving as expected.

> **Entry ordering is the opposite of the Premier 550**, where v1 found entry 1
> to be the newest. The gotcha checklist says to verify per model rather than
> assume; this is the case that proves why.

### Capture objects, in buffer order

| # | OBIS | attr | class | |
|---|---|---|---|---|
| 1 | `0.0.1.0.0.255` | 2 | 8 | Clock — the row timestamp |
| 2 | `0.0.96.5.0.255` | 2 | 1 | status word |
| 3 | `1.0.1.29.0.255` | 2 | 3 | |
| 4–6 | `1.0.32.27.0.255` · `1.0.52.27.0.255` · `1.0.72.27.0.255` | 2 | 3 | voltage L1/L2/L3 (D=27) |
| 7–9 | `1.0.31.27.0.255` · `1.0.51.27.0.255` · `1.0.71.27.0.255` | 2 | 3 | current L1/L2/L3 (D=27) |
| 10–12 | `1.0.32.128.124.255` · `1.0.52.128.124.255` · `1.0.72.128.124.255` | 2 | 3 | manufacturer-specific |
| 13–15 | `1.0.31.128.124.255` · `1.0.51.128.124.255` · `1.0.71.128.124.255` | 2 | 3 | manufacturer-specific |
| 16–18 | `1.0.81.128.4.255` · `1.0.81.128.15.255` · `1.0.81.128.26.255` | 2 | 3 | manufacturer-specific |
| 19–20 | `1.0.81.128.1.255` · `1.0.81.128.20.255` | 2 | 3 | manufacturer-specific |

The `1.0.x.128.y` group is Mitsubishi-specific and **its meaning is not
established** — the values were read, not interpreted. Do not map them to
product columns without confirming what they are.

v1 recorded **19** columns for its own SMW110 unit. These read **20**. Either
firmware differs or the earlier count was of a different configuration; the
lesson is that the capture list is read from the meter every time, never cached
across units.

## Logger 2 — declared but not readable

`1.0.99.2.0.255` appears in the association object list on both units and in
both Director exports. **Reading any of its attributes returns "undefined
object".** v1 reached the same conclusion on its unit and its reader treats the
logger as an empty buffer.

This is the sharpest lesson of the scan: **an object list states what is
declared, never what is readable.** See the section below.

## Billing — `1.0.98.1.0.255`

| | |
|---|---|
| Prefix | `1.0`, **not** the `0.0` SMART TCC uses — `0.0.98.x` answers "undefined object" |
| Capture period | 0 (event-driven, as expected for a billing profile) |
| Entries in use | 13 |
| Columns | 242 |

Schemes 2 and 3 (`1.0.98.2/3.0.255`) and the whole `0.0.98.x` family answer
"undefined object".

### The rows need a 43-column prefix

A full-width `readRowsByEntry` answers *"Data Block Unavailable"*. The firmware
serves only a **prefix of the capture-column table** — a selection must start at
column 1; v1 established that an arbitrary mid-table span is refused even for a
single column. The only free variable is the width, and it has a hard ceiling:

| Prefix width | Answer |
|---|---|
| 242 (full) | `Data Block Unavailable` |
| 93 | `Data Block Unavailable` |
| 68 | `Device reports scope of access violated` |
| 55 | `Device reports scope of access violated` |
| **43** | **reads every row** |

**Every rung matches what v1 measured on its own unit** (field probe round 5,
2026-07-24) — including the two distinct refusals, a size wall above 68 and a
permissions wall at 55–68. v1's unit was on **serial**, this one on **TCP**, and
the ceiling is the same: it is a property of the firmware, not of the unit and
not of the transport.

Mechanically the read is `client.readRowsByEntry(pg, index, count, span)` where
`span = pg.captureObjects[:43]`, and the reply must be parsed against **only that
span** — swap `pg.captureObjects` to `span` before `updateValue` and restore it
in a `finally`.

**Whatever M6 needs must live inside the first 43 columns.** The 199 above are
unreachable by entry access on this meter.

### What the rows contain

The first 43 columns are Clock, a period counter (`1.0.0.1.1.255`), the energy
registers `1.0.{1..5}.8.{0..4}` (total plus four tariffs), and the maximum-demand
registers `1.0.{1..5}.6.{0..4}`.

Read 2026-08-07 (raw, unscaled):

| Entry | Clock | counter | `1.0.1.8.0.255` |
|---|---|---|---|
| 1 | `2026-08-07 11:37:58` | 28 | 200464501 |
| 2 | `2026-08-01 00:00` | 27 | 198685030 |
| 3 | `2026-07-01 00:00` | 26 | 189917399 |

Two things follow:

- **Entry 1 is the RUNNING period**, stamped with the time of the read, not a
  closed cut. The closed cuts are entries 2 and 3, landing on the 1st of each
  month.
- **Billing is ordered newest-first — the opposite of the load profile on the
  same meter.** The load profile returns entry 1 as the oldest row. Ordering is a
  property of the *profile*, not of the meter, and must be established per
  profile rather than per model.

Every `1.0.x.6.y` maximum-demand cell read `0`. They are inside the accepted
prefix, so this is what the meter reports, not truncation — but whether the
meter genuinely records no demand or simply does not populate these is **not
established**.

## Identity registers

| OBIS | Answer | |
|---|---|---|
| `0.0.42.0.0.255` | `MAT-SMW110` | COSEM logical device name — model, not serial |
| **`1.0.199.128.134.255`** | **the real serial** | Mitsubishi register — use this one |
| `0.0.96.1.0.255` | `99999999` | factory placeholder, **never a serial** |
| `0.0.96.1.1.255` | `SMW110W4-N141C600` | the model string — the identity discriminator |
| `0.0.96.1.2.255` | raw `07e60101ff` (a date, 2022-01-01) | |
| `0.0.96.1.3.255` | `2` | |
| `0.0.96.1.4/5/6/8/9/10/12/13/14/21.255` | "undefined object" | |

For a driver: `METER_SERIAL_OBIS = ("1.0.199.128.134.255", 2)` — the same
register v1 used, for the same reason.

## The lesson: a file is hearsay, a read is evidence

Three conclusions were drawn from documents during this scan and **all three
were wrong**. Each was overturned by reading the meter:

| Claimed from a file | What the meter said |
|---|---|
| `1.0.199.*` is absent from the association export ⇒ no serial exists ⇒ ADR 0005 is in trouble | The register **reads fine**. It is simply not in the export. |
| Logger 2 is in the object list ⇒ this model has two loggers | **"undefined object"** on both units. |
| A Director profile uses client 5 and another uses 6 ⇒ the address is per-device | That profile was **superseded**; both live units use 6. |

Object lists, `.gxc` exports, `Save Values As` XML, nameplates and file names are
all *reports about* a meter. Only a read is a fact about one. ADR 0005 already
says identity comes from the meter — this widens the same rule from the serial
to everything.

Two corollaries worth keeping:

- **Absent from an export ≠ refused by the meter.** Probe before concluding.
- **Declared in the object list ≠ readable.** Probe before depending on it.

## What is still open

- **Client address `6` is treated as a per-model constant for now** (owner's call,
  2026-08-07) — both units at this site use it, and v1's hardcoded `5` is not
  carried over. Revisit if a site ever answers on a different address; nothing in
  the product should assume the value cannot change.
- **The `1.0.x.128.y` load-profile columns**: read, not understood. Deliberately
  left unmapped until the customer says what they are — do not guess one into a
  product column.
- **Maximum-demand cells read `0`** across every billing row. Inside the accepted
  prefix, so it is what the meter reports; whether that is real is unknown.
- **The older unit v1 read** (`1252008102`) is **retired — the customer no longer
  uses it**. [`mitsu-obis-scan.md`](mitsu-obis-scan.md) stays as the historical
  record of that meter; this document describes the units in service.
