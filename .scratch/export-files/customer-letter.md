# For the customer: your three export files

Written 2026-09-11, on delivery of M13 (the export files). Everything below was read off
your meters or ours directly, read-only — none of it is from a datasheet.

You sent two sample workbooks. This is what you will get, where it differs from your
samples, and why. **None of these are questions** — they are decisions, and each has a
reason beside it. If any of them is wrong for you, say so and we will change it.

---

## 1. You now get three files, not one

| File | What it holds | When it is written |
|---|---|---|
| `<meter>.csv` | Load Profile — one row per interval, **25 columns** | every export cycle, appended |
| `<meter>-billing.csv` | Billing — one row per closed period, **24 columns** | every export cycle, appended |
| `<meter>-energy.csv` | Energy Summary — one row per day, 9 columns | daily, appended, **plus a Save button** |

All three share one folder, one on/off switch and one date format — the settings you
already have. Only the filename pattern is per-file, so the three cannot overwrite each
other.

---

## 2. What changed in the Load Profile file

**All 25 columns from your sample are there, in your order.** That order inserts the three
phase angles and the status column *before* `Frequency (Hz)` rather than at the end, so an
existing column moved. See §5 on what happens to your current file.

### Which columns carry values on which meter

| Column | Prometer 100 | Premier 550 | Saral 305 | SMART TCC |
|---|---|---|---|---|
| `Avg Phase Angle Ph-A/B/C` | yes | empty | empty | yes, unverified |
| `Record Status` | yes | yes | empty | empty |
| `Import/Export Active (kW)`, `Import/Export Reactive (kvar)` | yes | empty | empty | empty |
| `Voltage L1-L2 / L2-L3 / L3-L1 (V)` | yes | empty | empty | empty |

**The four power columns and the three line-to-line voltages arrive on the Prometer 100
only.** The other models do not record them — the values are not in the data the meter
captures, so there is nothing for us to read. A meter that does not record a quantity gets
an **empty column, never a missing one**, so every meter's file has the same shape and the
same column positions.

The SMART TCC's phase angles are mapped from a July scan and have **never been read on
hardware** — that meter has not answered on either port since August. Its status column
stays empty deliberately: it uses a different register whose bit meanings nobody has
verified, and writing a number we cannot decode would be worse than writing nothing.

### The phase angles read 0.000 and -1.000 on the meter we tested

This is the meter's own answer, not a gap in the file. We checked it directly: those
registers return those values, while the power factor register on the same connection
returns 0.076 — and a power factor that low means an angle near 86 degrees. So the meter
is not reporting a usable angle at all.

Our mapping is correct and transcribes faithfully; no change on our side can produce a
number the meter does not have. **Worth raising with CEWE** — it looks like these registers
are not commissioned on this unit.

---

## 3. What is in the billing file

24 columns, your order, one row per **closed** billing period.

**Only closed periods are exported.** The period the meter is still accumulating into has a
date that moves every time we read it, so including it would append the same period again
and again under a changing date.

**On your machine this file will be empty at first.** The one billing row stored there
today is that still-open period. The file fills as periods close.

**`Record No` counts closed periods for that meter, oldest first** — not lines in the file.
A line count would reset whenever the file rolls; this number stays stable for the life of
the meter.

**There is no Rate D column.** Your contract has three tariffs and your sample shows three.
Our system does hold a fourth internally and the Billing screen shows it, which is why you
may notice the difference — but it measures `0.0` on your meter and is empty on all four of
our test meters, so putting it in the file would add a column of nothing. If a four-tariff
site ever appears we can add the columns then, safely.

**`Record Status` reads `closed` on every row.** Your sample has `..........` there. Since
only closed periods are exported the value is constant — but constant and true is better
than blank and ambiguous, and it will mean something if we ever include open periods.

**This is not the same column as `Record Status` in the Load Profile file**, despite the
shared name. In the billing file it is a per-period open/closed state. In the Load Profile
file it is a 13-bit word the meter sets per interval.

---

## 4. What is in the Energy Summary file

`Date` plus the eight Time-of-Use columns the screen shows. **No total row** — a running
file cannot have one, and the total belongs on the screen.

**Two things can make this file stale, and one button fixes both.**

1. Interval readings that arrive late, through the 90-day catch-up, never reach the daily
   file — the day was already written.
2. A holiday entered *after* the fact changes what an earlier day should have reported.

The **Save to file** button on the Energy Summary page re-saves any range you pick, which
corrects either case. And when you add, edit or delete a Holiday, the screen now tells you
how many meters' files already hold the affected day, and points you at that button. That
notice stays on screen until you dismiss it — it is asking you to do something later, not
just telling you something happened.

---

## 5. Your existing Load Profile file has been closed, and a new one opened

The column set changed, so the file that was being appended to is **renamed** with the date
the update reached your machine — `<meter>.<date>.csv` — and a fresh `<meter>.csv` starts
with the new 25-column header.

Nothing in the old file is altered, and **no row is ever written under a header that does
not describe it.** That is the rule the whole delivery is built on: a file that appends is a
contract, so when the contract changes the old file closes rather than being rewritten.

If your tooling reads a fixed filename it will find the new file. If it scans the folder it
will now see two files with different column counts — the dated one is history, the
undated one is current.

This happens **once**. Normal cycles append as before. It will happen again only if the
column set or the header block changes again, or if you edit the meter's Customer, Site
Name or Serial — those three are in the file header block, so changing them starts a new
edition too.

---

## 6. Column names, where they differ from your sample

**Two power columns.** Your sample spells them `Import kW Active` and `Import kVar
Reactive`. Those name a kilowatt and a kilovar quantity in the style used for
kilowatt-hours — the same mix-up we corrected in the four energy headers in August. We use
`Import Active (kW)` and `Import Reactive (kvar)`, matching the rest of the file, so one
file does not carry two naming conventions.

**The status column keeps your word** — `Record Status`. That one is yours.

**The date format follows your own setting.** Your billing sample shows `5/1/2025 00:00`;
the default here is `2025-05-01 00:00:00`. It is the Export Format setting you already
have, and it applies to all three files — tell us if you want the default changed.

---

## 7. The status column's wording

`OK` when the interval is clean. When the meter flags something the words are `DISTURBED`
and `POWER_LOSS`, and **two or more join with a pipe**: `DISTURBED|POWER_LOSS`. A pipe
rather than a comma, so the cell never needs quoting and cannot split a row in a reader
that handles CSV quoting loosely.

A flag we do not yet have a word for shows as a hex number (`DISTURBED|0x0400`) rather than
being dropped, so nothing the meter told us disappears.

**Intervals the meter itself marks all-invalid are removed entirely** — from the Load
Profile file, the Load Profile screen and the Energy Summary totals. That matches what your
previous system did. An interval flagged only `DISTURBED` or `POWER_LOSS` is still included;
only the meter's own "everything in this interval is invalid" flag removes a row.
Day-completeness counts still count every interval that arrived, whatever the meter thought
of it.

---

## Questions we would still like answered

Nothing below blocks you using the files.

1. **Do you need `Avg Phase Angle` to work?** If yes, it is a meter commissioning question
   for CEWE, not a software one — see §2.
2. **`Setting : 1`** appears in every one of your samples with no explanation. We reproduce
   the line exactly so your tooling's line offsets stay right, but nobody on either side
   knows what it means. If it matters, we would like to know what it is.
3. **Does anything read the dated, closed files?** If your tooling globs the folder, §5 will
   give it two shapes. We can put closed editions in a subfolder instead if that is easier.
4. **Is `M/D/YYYY HH:MM` actually required**, or is the current default fine? See §6.
