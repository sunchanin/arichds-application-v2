# 0028. The capture image has a style, and Classic reproduces the customer's previous program

**Status:** Accepted · 2026-09-21 · owner decision (grill, two rounds), at the customer's request:
the Billing capture image must look like the image their previous program wrote — "เป๊ะ 100%".
That program is **ARICHDS Meter** (named by the owner 2026-09-22) — a desktop program, not v1;
its toolbar icons may be shipped in our installer. The references (owner, 2026-09-22): a PNG the
program itself wrote (`capture_WP081200.png`, 1280×709 — so the program writes a fixed-size
image, and display scaling never enters), a PNG strip of its ten toolbar icons (514×54), its
`billing.csv` export (26 unlabelled columns, 2,028 rows, 237 meters), and an earlier chat-app
JPEG of another window at the same 1280×709.

**Amends:** ADR 0017, whose Decision makes the `.png` a screenshot of *our own Billing page* and
counts "fidelity is an identity" as the gain — true of one style only from here on. **Touches**
ADR 0015: the ten-period span stands, but Classic lists the periods oldest first. **Does not
touch** the mechanism (headless Edge over CDP, the `LOCAL SERVICE` task, the row-id gate), the
`.pdf`/`.xlsx`, the filename convention, or ADR 0010.

## Context

The customer hands the capture image on to people who have been receiving the previous
program's image for years: a 1280×709 window client area — a ten-icon toolbar, a *Save Path*
box, a *Data Billing* group (Group, *Statistics Summary*, Billing/Current tabs, Device, *Read
Billing*), an *Auto Read Schedule* group, a *Data Table* cut off mid-way through its ninth
column by the window edge, and a status line. The reader is **a person**, not a program reading
pixels (owner, Q1) — which is what makes the request satisfiable at all.

Pixel identity is not on offer and the ADR should not pretend otherwise: that window is drawn by
a native toolkit, ours by Chromium, and the two rasterise glyphs differently. What is on offer
is an image that agrees with theirs in every position, size, colour and string.

## Decision

**Capture Style** (CONTEXT.md) — one machine-wide setting beside the capture folder, admin-only,
`standard` (default) or `classic`. No licence feature key: whoever may capture may choose, and a
key would cost the customer a new Activation Code to change how a picture looks.

Classic is **a page drawn only to be photographed**: a route in `web/` no menu reaches, at a
fixed 1280×709 viewport that never grows, laid out in HTML/CSS with every measured distance,
colour and column width in **one stylesheet**, and the ten toolbar icons as bitmaps cut from an
image the previous program wrote. It goes through the same seeded, headless, row-id-gated
pipeline as Standard.

What it shows:

| Part | Value |
|---|---|
| Save Path | the real `capture_dir`, with `/` separators as that program showed them |
| Group / Device | the device's real `group_name` (blank when it has none) · `<BRAND> - <serial>` |
| Data Table | the **ten most recent closed periods, oldest first** (then by Billing Sequence — a same-second pair is two rows with one Time, ADR 0029; since ADR 0029 this order is every page's, not Classic's alone), never the Open Period; columns up to the window edge only — Name `<BRAND> (<serial>)`, Time (bill date, local, `M/D/YYYY HH:MM`), Total kWh Total / Rate A / B / C, Prev kW Demand Rate A, Time of kW Demand A, Prev kW Demand Rate B (cut) |
| Numbers | **always kWh and kW**, four decimals with trailing zeros dropped — the headings state the unit, so the Display unit setting (ADR 0013) does not reach this image |
| Statistics Summary | counted over the devices sharing the captured device's group (or sharing *no* group) **at the moment of writing**: Paused devices are not counted at all; *Devices with Issues* = those the Poller currently holds Offline; Unknown counts in the total and is not an issue; *Complete* = Total − Issues |
| Auto Read Schedule | fixed text — `00:00`, `Status: Running`, `Stop` |
| Status line | `Capture bill data <serial>...` |

**Every value is true or is inert.** A Capture is a document a person carries to someone else,
so a number in it is a claim. The schedule panel is allowed to be fixed text because it claims
nothing about a bill; the statistics are not.

Switching style rewrites nothing on disk (the rule `capture_dir` already follows): it governs
the next write — the automatic capture of a new closed period, a hand-pressed Capture image,
and the render-on-miss download.

**Acceptance is an overlay against a PNG the program itself wrote**: positions, sizes, colours
and text agree; glyph edges may differ. The column mapping above is **confirmed from ARICHDS
Meter's own `billing.csv`** against its own picture of the same meter (WP081200): columns 8–11
are Total kWh Total/A/B/C with A+B+C = Total on every row, 12/13 are Prev kW Demand Rate A and
its time, 14/15 Rate B, 16/17 Rate C, 18–20 the cumulative demands (each a running sum of the
monthly maxima, verified to 0.0001), 21 the reactive kvarh total, 22/23 a reactive maximum
demand and its time, 24 its cumulative ×1000. Nobody reports "identical" before the overlay has
been done.

## What it costs

- A page in `web/` that imitates another program, carries that program's icons in every
  customer's installer, and says `Status: Running` about a schedule we do not have. This ADR is
  the explanation; without it the page reads as a mistake.
- ADR 0017's cheapest property is gone for Classic: a change to the Billing page no longer
  changes the image, so the two can drift, and the Classic page is a second thing to keep
  working — with a DOM contract of its own in `capture/dom.py`.
- The mapping from their headings to our columns is a guess until the overlay ticket closes.

## Alternatives rejected

- **A bitmap of their window with text drawn over it.** Exact chrome for free, but every string
  that varies (path, group, counts, ten rows, the status line) still has to be typeset to match,
  and Pillow left the product with ADR 0017. Kept only for the icons, which cannot be redrawn.
- **Statistics from billing completeness** ("which meters of the group have this period yet").
  A Capture is written meter by meter the moment a closed period lands: the first meter of a
  seven-meter group would be pictured beside `Devices with Issues: 6` when nothing is wrong.
- **Holding the capture until the whole group has read.** Breaks the Capture's "written
  eagerly, synchronously" rule and needs a persisted pending state (ADR 0008).
- **A fourth file, or replacing the image for everyone.** The folder already holds three formats
  under one stem (ADR 0015), and other customers did not ask for this.
- **Calling it "legacy".** v1 and the customer's `meter.logger` table already answer to that word.
