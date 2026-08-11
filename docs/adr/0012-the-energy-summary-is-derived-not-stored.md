# The Energy Summary is derived on every request, and is deliberately not reproducible

Status: accepted (2026-08-11, owner decision during M7 grilling). **Not yet implemented** —
lands with M7's first slice.

Reverses nothing. This ADR exists because the Energy Summary has a property that looks like a
bug from every angle except the one that explains it, and the cheapest "fix" for it would cost
a table, a cache-invalidation problem, and the thing that makes the numbers correct.

## The property

An Energy Summary is not stored. The Peak / Off-Peak / Holiday buckets are aggregated out of
`load_profile_readings` on every request, the way the Records page counts its cells live. So:

```
today       operator opens January   →  Peak 1,200 kWh
tomorrow    an admin adds 15 January as a public Holiday
next day    operator opens January   →  Peak 1,150 kWh
```

Same month, same meter, no new meter data, different number. Nobody edited a reading. A report
printed last month does not reproduce.

That is not a defect being tolerated. It is what the design is for.

## Why the numbers move

Holidays are not a property of a reading — they are a property of a *calendar*, and the
calendar is maintained by a human after the fact. Thailand's public holidays are announced; a
site's own annual closures get entered when someone remembers. ADR 0016 (v1) chose to store
holidays as rules — `kind ∈ {annual, public}` — rather than expanding them into concrete dates,
precisely so that "1 January, every year" stays one row that means what it says.

Given rules rather than snapshots, live aggregation is the only arrangement where **adding a
holiday you forgot fixes the past instead of only the future**. A materialized summary would
freeze January's buckets around the calendar as it stood in January, which is the calendar that
was *missing* the holiday. The stored number would be permanently, invisibly wrong, and the
page would look more trustworthy for it.

So the movement is not noise. Each move is the report catching up with something true that we
learned late.

## Why the peak window is a constant, then

The same argument does not extend to the peak-hour window, and this is the line the ADR is
really drawing.

v1 hardcodes it (`constants.py:299` — `TOU_PEAK_START_UTC = 2`, `TOU_PEAK_END_UTC = 15`, being
local 09:00–22:00) and ADR 0016 records that the customer never asked to change it. M7 keeps it
a constant, and the reason is not that changing it is hard — the `settings` table exists since
M6b and the Export Format page is in this very milestone, which is exactly the argument that
moved CSV export here.

The reason is that the two knobs are not alike:

| | what moves the numbers | what justifies the move |
|---|---|---|
| Holiday table | adding a real day off | 15 January **was** a holiday; we knew late |
| Peak window | editing `09` to `08` | nothing in the world changed |

A holiday edit is a correction. A peak-window edit is a re-definition, and it would silently
restate every month ever reported with no event behind it. One retroactive knob that tracks
reality is a feature. A second one that tracks nothing turns "the summary changed" from a
question with an answer into a question without one.

If a site is genuinely on a different tariff structure, that is a different tariff — it belongs
in a per-site value with its own history, not in a free-text box that rewrites the past. Until
a real site needs one, the constant is the honest model.

## Consequences

- **No `energy_summary` table, no cache, no invalidation.** M7 adds three tables; this is not
  one of them.
- **Cost is on the read.** v1's query is a full aggregate with six `CASE` branches over
  `load_profile_readings`, the largest table in the product (90 days × 96 intervals × devices).
  The Records page already accepted this shape and bounds its request to 31 days
  (`SPEC.md:482`); the Energy Summary must bound its range the same way rather than assume the
  aggregate is free.
- **The property must be visible to the reader, not discovered.** It is written into
  `CONTEXT.md` under *Energy Summary*, and the page should not present a summary as a document
  of record. Anything that must be reproducible — an invoice, a customer handoff — belongs to
  Billing, which stores what the meter itself froze and never recomputes.
- **Push (M8) sends readings, not summaries.** `SPEC.md:835` lists "energy summary" among the
  pushed payloads; with this ADR the TOU buckets are a view, so what crosses the wire is the
  Interval Readings and the Energy Registers rows. Whether the central server wants a
  server-side TOU of its own is a question for M8 — it cannot be answered by shipping ours,
  because ours is a function of a holiday table that lives on one customer's machine.

## What was rejected

**Materialize a daily summary row and recompute on holiday change.** Buys a fast, stable read
and a reproducible report. Rejected because the invalidation is the whole feature: a holiday
edit invalidates every day it touches across every device and both directions of energy, and an
invalidation that is even slightly wrong produces a page that is confidently stale — strictly
worse than a page that is honestly live. It also adds an eleventh table to buy speed on a query
nobody has measured as slow.

**Make the peak window a setting now, on the argument that the settings page is in this
milestone.** Rejected above: the milestone's convenience is not a reason for the knob to exist.
