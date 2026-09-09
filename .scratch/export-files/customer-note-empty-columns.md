# For the customer: which of the new columns carry values, on which meter

Written 2026-09-09, M13 issue 07. Everything below was read off the meters themselves,
read-only, not taken from a datasheet.

Your Load Profile file now carries all twenty-five columns your sample asks for, in your
order. **Some of them will be empty on some meters, and that is the meter, not the file.**
A meter that does not record a quantity gets an empty column rather than a missing one, so
every meter's file has the same shape and the same column positions.

## What each model fills

| Column | Prometer 100 | Premier 550 | Saral 305 | SMART TCC |
|---|---|---|---|---|
| `Avg Phase Angle Ph-A/B/C` | yes | empty | empty | yes, but see below |
| `Record Status` | yes | yes | empty | empty |
| `Import Active (kW)` / `Import Reactive (kvar)` | yes | empty | empty | empty |
| `Export Active (kW)` / `Export Reactive (kvar)` | yes | empty | empty | empty |
| `Voltage L1-L2 / L2-L3 / L3-L1 (V)` | yes | empty | empty | empty |

The fourteen columns you already had are unchanged on every model.

**In short: the four power columns and the three line-to-line voltages arrive on the
Prometer 100 only.** The other models do not record them at all — they are not in the data
the meter captures, so there is nothing for us to read.

## Three things worth knowing before you look at the file

**1. Your existing file has been closed and a new one opened beside it.**
The column set changed, so the file that was being appended to is renamed with the date it
closed — `<meter>.2026-09-09.csv` — and a new `<meter>.csv` starts with the new header. No
row is ever written under a header that does not describe it, and nothing in the old file is
altered. If your tooling reads a fixed filename, it will find the new file; the old rows are
in the dated one.

**2. The three phase angles read `0.000` on the meter we tested.**
This is the meter's own answer, not a gap in the file. We checked it directly: the phase
angle registers on that Prometer 100 return zero while the power factor register on the same
connection returns a real number. If your meters report a real phase angle, the column will
carry it; on this firmware they report zero, and no change on our side can produce a number
the meter does not have. Worth raising with CEWE if you expect otherwise.

**3. Two column names differ from your sample, on purpose.**
Your sample spells the power columns `Import kW Active` and `Import kVar Reactive`. Those
name a kilowatt and a kilovar quantity in the style used for kilowatt-hours, which is the
same mix-up that was corrected in the four energy headers in August. We use
`Import Active (kW)` and `Import Reactive (kvar)`, matching the rest of the file, so one
file does not carry two naming conventions. The status column **keeps your word** —
`Record Status` — because that one is yours.

## The status column's wording

`OK` when the interval is clean. When the meter flags something, the words are
`ALL_INVALID`, `DISTURBED` and `POWER_LOSS`, and **two or more join with a pipe**:
`ALL_INVALID|DISTURBED`. A pipe rather than a comma, so the cell never needs quoting and
cannot split a row in a reader that handles CSV quoting loosely.
