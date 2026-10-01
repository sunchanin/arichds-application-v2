# Requirements brief: ตัวอย่างไฟล์.xlsx

**Source:** `source/ตัวอย่างไฟล์.xlsx` · ingested 2026-09-08 · sha256 `1b2bc79d14ea`
**Original path:** C:\Users\HP\Downloads\ตัวอย่างไฟล์.xlsx

## Summary

A two-sheet workbook named literally "example file" (`ตัวอย่างไฟล์`), carrying **no screenshots and no prose** — it is a column specification expressed as two sample output files, one per sheet: `LP` (Load Profile) and `BL` (Billing), both for customer `LPH`, site `LPH Days1`, meter `WP076996`. Each sheet has the same four-line header block (`Customer :` / `Site Name :` / `Serial Meter :` / `Setting :`) above a header row and sample data rows.

**The document's entire meaning is carried by font colour.** The only two prose cells in the file say so: `B17` on LP reads "the added pulls are the red ones at the back", `G16` on BL reads "the added pulls are the red ones". Seven LP columns and four BL columns are set in red (`FFFF0000`); every other header is the theme's default black. The extractor does not capture colour, so the red/black split below was read out of the workbook separately and is recorded here because without it the file says nothing.

This file is a companion to `แก้ไข capture และฟอร์ม billing+เมนู  sum energy.xlsx` (ingested the same day into `.scratch/capture-billing-energy/`): its `BL` sheet and that workbook's two billing-format sheets are the **same file format for three different meters**, and the four red Export columns here are the same four marked red there.

## Terminology

Glossary read: `CONTEXT.md` at the repo root. `CONTEXT-MAP.md` and `docs/agents/domain.md` do not exist.

| Customer's term | Where | Glossary term | Status | Note |
|---|---|---|---|---|
| Load Profile | LP A5, sheet name | **Interval Reading** / Load Profile | match | glossary's row type is Interval Reading; the page and CSV are called Load Profile |
| Billing | BL A6, sheet name | **Billing Reading** | match | |
| Date/Time (LP) vs Time (BL) | LP B7, BL B8 | **Bill Date** (billing) | conflict | glossary names the billing timestamp `bill_date`; the file calls it `Time`, and the two sheets do not agree with each other |
| Record No | BL A8 | — | missing | a 1-based counter, 1…4 in the sample; v2 has no such column |
| Record Status | LP R7, BL X8 | **Records** | conflict | glossary's **Records** is a per-day completeness grid; here it is a per-row string, `..........` in every sample row |
| Customer : | LP A1, BL A2 | — | missing | v2 has no Customer concept |
| Site Name : | LP A2, BL A3 | — | missing | v2 has no Site concept; v1's Billing screen shows `Site Name` and `Site Code` |
| Serial Meter : | LP A3, BL A4 | **Meter Serial** | match | glossary's term is Meter Serial; word order reversed here |
| Setting : | LP A4, BL A5 | — | missing | value is the number `1`; meaning unknown |
| Import kWh Active / Export kWh Active | LP C7, E7 | **Interval Reading** columns | match | glossary: Interval Readings are UTC + kWh + COSEM column names |
| Import kW Active / Import kVar Reactive | LP S7, T7 (**red**) | — | conflict | these are **power** (kW / kvar), not energy (kWh / kvarh). ADR 0013 is explicit that the Load Profile CSV is always kWh/kvarh and never follows the Display unit setting |
| Billing total Export kWh Total/Rate A/B/C | BL G8–J8 (**red**) | **Billing Reading** | match | v2 already stores and displays Export Active kWh Total and Rate A–D |
| Cumul kW demand | BL Q8–S8 | **Cumulative Demand** | match | glossary: COSEM `D=2`, distinct from the period maximum `D=6` |
| Previous kW demand / Previous Time of kW deman | BL K8–P8 | **Demand Time** | match | glossary: the value at attribute 2 and its `capture_time` at attribute 5 share one OBIS, which is why columns key on `(OBIS, attribute)` |

## Sections

### 01. LP *(Load Profile)*

**Screenshot:** none.
**Example data:** [`lp-load-profile-columns.csv`](source/fixtures/lp-load-profile-columns.csv), from `A7:Y10` — **25 columns**, header row plus 3 data rows.

**The three data rows are empty except for `Date/Time`.** B8, B9 and B10 hold real **datetime** cells `2025-04-01 00:00:00`, `2025-04-01 00:15:00`, `2025-04-01 00:30:00` — 15-minute intervals — and every other cell in those rows is blank. The sheet is a column list with a cadence, not sample values.

**File header block (A1:A5), quoted:**

- A1 `Customer :` / B1 `LPH`
- A2 `Site Name :` / B2 `LPH Days1`
- A3 `Serial Meter :` / B3 `WP076996`
- A4 `Setting :` / B4 `1` (a number)
- A5 `Load Profile :` (no value beside it)

**Column headers (A7:Y7), quoted in order, with the customer's colour recorded:**

| Ref | Header (verbatim) | Colour |
|---|---|---|
| A7 | `Name` | black |
| B7 | `Date/Time` | black |
| C7 | `Import kWh Active` | black |
| D7 | `Import kWh Reactive` | black |
| E7 | `Export kWh Active` | black |
| F7 | `Export kWh Reactive` | black |
| G7 | `(Average Power Factor Avg` | black |
| H7 | `Voltage L1 (V)` | black |
| I7 | `Voltage L2 (V)` | black |
| J7 | `Voltage L3 (V)` | black |
| K7 | `Current L1 (A)` | black |
| L7 | `Current L2(B)` | black |
| M7 | `Current L3 (C)` | black |
| N7 | `Avg Phase Angle Ph-A` | black |
| O7 | `Avg Phase Angle Ph-B` | black |
| P7 | `Avg Phase Angle Ph-C` | black |
| Q7 | `Frequency (Hz)` | black |
| R7 | `Record Status` | black |
| S7 | `Import kW Active` | **RED** |
| T7 | `Import kVar Reactive` | **RED** |
| U7 | `Export kW Active` | **RED** |
| V7 | `Export kVar Reactive` | **RED** |
| W7 | `Voltage L1-L2 ` | **RED** |
| X7 | `Voltage L2-L3` | **RED** |
| Y7 | `Voltage L3-L1` | **RED** |

Verbatim oddities preserved above: `G7` opens with an unclosed parenthesis and reads `(Average Power Factor Avg`; `L7` has no space before its parenthesis (`Current L2(B)`) and labels phase 2 as `B` while `K7` labels phase 1 as `A`; `W7` has a trailing space.

**Note (verbatim), 1 cell:**

- B17: "**** เพิ่มดึงคือสีแดงด้านหลัง" → "**** The added pulls are the red ones at the back." (`ด้านหลัง` = "at the back / behind", matching the fact that all seven red columns are the last seven)

**Open questions:**

- [customer] The seven red columns split into two kinds. Four are **power, not energy** — `Import kW Active`, `Import kVar Reactive`, `Export kW Active`, `Export kVar Reactive` — while the existing black columns C–F are the matching **energy** (`kWh`/`kvarh`). Is the ask for a second set of columns holding a different quantity, or for the same numbers expressed in kW?
- [internal] If it is the latter, it collides head-on with **ADR 0013**: the Load Profile CSV is always kWh/kvarh and deliberately never follows the machine-wide Display unit setting, because an appended file is a contract and a unit switch is a view. A kW column *in the file* is not the same thing as the Display unit setting, but the ADR is the first place to take this.
- [customer] The other three red columns are **line-to-line voltages** (`Voltage L1-L2`, `L2-L3`, `L3-L1`) alongside the existing line-to-neutral ones (`Voltage L1 (V)`, `L2`, `L3`). Does the meter's load profile actually capture these, or are they to be **computed** from the phase voltages and angles?
- [internal] Which of the 25 columns does v2's Load Profile CSV produce today, and in what order? The file states an order; nothing here says whether it matches.
- [customer] `Name` (A7) is a column, but it is blank in all three sample rows. What goes in it — device name, meter serial, site?
- [customer] The three data rows carry a 15-minute cadence and an April 2025 date but no values. Is the cadence part of the specification or incidental to the sample?

### 02. BL *(Billing)*

**Screenshot:** none.
**Example data:** [`bl-billing-columns.csv`](source/fixtures/bl-billing-columns.csv), from `A8:X12` — **24 columns**, header row plus 4 data rows with real values.

**File header block (A2:A6), quoted:**

- A2 `Customer :` / B2 `LPH`
- A3 `Site Name :` / B3 `LPH Days1`
- A4 `Serial Meter :` / B4 `WP076996`
- A5 `Setting :` / B5 `1` (a number)
- A6 `Billing :` (no value beside it)

The block starts at row **2** here and at row **1** on the LP sheet.

**Column headers (A8:X8), quoted in order, with the customer's colour recorded:**

| Ref | Header (verbatim) | Colour |
|---|---|---|
| A8 | `Record No` | black |
| B8 | `Time` | black |
| C8 | `111 Billing total kWh Total` | black |
| D8 | `010 Billing total kWh Rate A` | black |
| E8 | `020 Billing total kWh Rate B` | black |
| F8 | `030 Billing total kWh Rate C` | black |
| G8 | `Billing total Export kWh Total` | **RED** |
| H8 | `Billing total Export  kWh Rate A` | **RED** |
| I8 | `Billing total  Export  kWh Rate B` | **RED** |
| J8 | `Billing total  Export  kWh Rate C` | **RED** |
| K8 | `050 Previous kW demand Rate A` | black |
| L8 | `050T Previous Time of kW deman` | black |
| M8 | `060 Previous kW demand Rate B` | black |
| N8 | `060T Previous Time of kW deman` | black |
| O8 | `070 Previous kW demand Rate C` | black |
| P8 | `070T Previous Time of kW deman` | black |
| Q8 | `015 Cumul kW demand Rate A` | black |
| R8 | `016 Cumul kW demand Rate B` | black |
| S8 | `017 Cumul kW demand Rate C` | black |
| T8 | `222 Billing total Varh Total` | black |
| U8 | `280 Previous Var demand Total` | black |
| V8 | `280T Previous Time of Var dem` | black |
| W8 | `118 Cumul Var demand Total` | black |
| X8 | `Record Status` | black |

The four red headers carry **inconsistent internal whitespace** (`Export  kWh Rate A` with two spaces, `Billing total  Export  kWh Rate B` with two doubles) — reproduced verbatim above. The demand headers are truncated at 30 characters (`…of kW deman`, `…of Var dem`).

**Data cells that are strings rather than numbers — all of them timestamps, all in `M/D/YYYY HH:MM` with no leading zeros:**

| Column | Row 1 | Row 2 | Row 3 | Row 4 |
|---|---|---|---|---|
| B `Time` | B9 `5/1/2025 00:00` | B10 `6/1/2025 00:00` | B11 `7/1/2025 00:00` | B12 `8/1/2025 00:00` |
| L `050T` | L9 `4/13/2025 12:45` | L10 `5/18/2025 11:45` | L11 `6/3/2025 12:15` | L12 `7/12/2025 13:00` |
| N `060T` | N9 `4/2/2025 19:00` | N10 `5/9/2025 19:15` | N11 `6/28/2025 19:30` | N12 `7/27/2025 19:15` |
| P `070T` | P9 `4/2/2025 19:00` | P10 `5/9/2025 19:15` | P11 `6/19/2025 19:30` | P12 `7/22/2025 19:15` |
| V `280T` | V9 `4/4/2025 06:30` | V10 `5/20/2025 06:15` | V11 `6/27/2025 06:15` | V12 `7/1/2025 06:30` |
| X `Record Status` | X9 `..........` | X10 `..........` | X11 `..........` | X12 `..........` |

**This is the format detail most likely to be lost in a paraphrase:** every timestamp on this sheet is a **text string** in `M/D/YYYY HH:MM`, while the LP sheet's `Date/Time` cells are real **datetime** cells, and the billing samples in the companion workbook are **datetime** cells too. Three samples of the same format, two different cell types.

**The four red Export columns are empty in all four data rows** (G9:J12 are blank), exactly as in the companion workbook's manual sample.

**Note (verbatim), 1 cell:**

- G16: "**** เพิ่มดึงคือสีแดง" → "**** The added pulls are the red ones."

**Open questions:**

- [customer] Why are the four red Export columns empty in every sample row, in both this file and the companion workbook? Does `WP076996` export nothing, or were the samples produced before the values existed?
- [internal] The same four headers appear with **four different whitespace spellings** across the two workbooks. If the header row is a contract an operator's tooling parses, exactly one spelling is correct — and none of them is obviously it.
- [customer] `Time` is a string here and a datetime in the companion file. Which is the required output — and is `M/D/YYYY HH:MM` (no leading zeros, no seconds) the format the file must produce?
- [internal] The customer's file has **three tariffs** (Rate A/B/C); v2 stores **four** (`rate_a`…`rate_d`) and its Billing page shows a Rate D column. What happens to Rate D in this file?
- [customer] Row 1 is `Record No` 1 at `5/1/2025 00:00` and the values grow monotonically to row 4 — so `Record No` counts from the oldest. Is it a position in the meter's buffer, or a row number in the file?
- [internal] Every OBIS-prefixed header here (`111`, `010`, `020`, `030`, `050`, `050T`, …) matches the companion workbook exactly, so these prefixes are a stable vocabulary. Do they correspond to the register maps in `docs/meter-notes/`?
- [customer] `Setting : 1` — the same unexplained field as in the companion workbook.

## Open questions (consolidated)

**Load Profile columns**

1. [customer] Are the four red **power** columns (`Import kW Active`, `Import kVar Reactive`, `Export kW Active`, `Export kVar Reactive`) a new quantity, or the existing energy columns re-expressed in kW?
2. [internal] If re-expressed, how does that sit with **ADR 0013** (the Load Profile CSV is always kWh/kvarh, never the Display unit setting)?
3. [customer] Are the three red **line-to-line voltage** columns read from the meter's load profile, or computed from the phase voltages and angles?
4. [internal] Which of the 25 LP columns does v2's Load Profile CSV produce today, and in what order?
5. [customer] What value belongs in the `Name` column, which is blank in every sample row?
6. [customer] Is the 15-minute cadence in the sample part of the specification?

**Billing columns**

7. [customer] Why are the four red Export columns empty in every sample row of every file?
8. [internal] Which of the four whitespace spellings of the Export headers is the contract?
9. [customer] Is `Time` required as a **string** in `M/D/YYYY HH:MM`, or as a real datetime? The two files disagree.
10. [internal] Three tariffs (customer) vs four (`rate_a`…`rate_d`, v2) — what happens to Rate D?
11. [customer] Is `Record No` a buffer position or a file row number?
12. [internal] Do the OBIS-number prefixes map onto `docs/meter-notes/`?

**Shared with the companion workbook**

13. [customer] What is the `Setting :` header field, whose value is `1`?
14. [internal] What is `Record Status`, given it is `..........` in every sample row of every file?
15. [customer] Where do `Customer` and `Site Name` come from? v2 has neither concept, and both appear in every sample file's header.
16. [internal] The header block starts at row 1 on LP and row 2 on BL. Is that meaningful or a typing slip?
17. [internal] Headers are truncated at 30 characters by whatever program produced these files. Is the truncation part of the contract or an artefact to fix?

## Not covered

- **Neither sheet carries a screenshot**, so nothing in this file shows which control produces these outputs, or whether they are the same feature as v2's Load Profile CSV auto-export.
- **No prose beyond the two colour-legend cells.** There is no statement of what should happen to the existing columns, only which ones are added.
- **Colour is the only signal**, and it is carried on the header cells alone — the data rows below a red header carry no marking, and four of the eleven red columns have no sample value at all.

---

## Answers — 2026-09-08 (owner)

Answers given by the owner in session, plus a code check the owner approved
(question 15). Recorded here because `/grill-with-docs` and `/to-tickets` read
this file, not the chat.

### Answered

- **A1 — the four kW/kvar columns: approved.** Adding columns is not flipping a
  unit, so ADR 0013 is not reversed. Say so explicitly in the issue anyway.
- **A2 — the three line-to-line voltages are READ FROM THE METER**, not computed.
- **A4 — header spelling: use the clean form** (single spaces, no leading space).
  The customer's own file disagrees with itself four ways; we pick one.
- **BL `Time` / demand-time format, Record No, Setting:, Record Status** — still
  unanswered; see "Still open" below.

### Code check (approved as question 15, run 2026-09-08)

**The gap is 11 columns, not 7.** `export/format.py:34` `_EXPORT_HEADERS` has
**14** columns:

```
Name · Date/Time · Import Active (kWh) · Import Reactive (kvarh) ·
Export Active (kWh) · Export Reactive (kvarh) · Avg Geo PF ·
Voltage L1/L2/L3 (V) · Current L1/L2/L3 (A) · Frequency (Hz)
```

v1 (`cewe-worker/src/load_profile/export_format.py:25`) has the **same 14**, with
four header strings differing (`Import kWh Active`, `Import kWh Reactive`,
`Export kWh Active`, `Export kWh Re`) — v2 renamed those four deliberately
(owner ruling 2026-08-11, recorded in `format.py:29-33`).

So the customer's **18 black columns are not what either product exports today**.
Four of the black ones are missing from both: `Avg Phase Angle Ph-A`, `Ph-B`,
`Ph-C` and `Record Status`. The customer left them black — they were never told
we do not have them.

**Neither quantity exists in the v2 schema at all.** `db/models.py` has no phase
angle and no line-to-line voltage column; `record_status` exists only on
`billing_readings`, where it marks the Open Period, and means something
different. With A2 answered "read from the meter", the work is:

```
new capture objects  →  new driver reads  →  new DB columns  →  migration
                     →  new CSV columns
```

That is a driver + schema change, not a formatter change.

**Header-name conflict.** The customer's sample uses v1's old names
(`Import kWh Active`). v2's are the corrected ones. Matching the sample undoes
the 2026-08-11 ruling; keeping ours means the file does not match the sample
byte for byte. Not decided.

### Still open

- Is `Time` required as a string in `M/D/YYYY HH:MM`, or a real datetime? (Q9)
- What is `Setting : 1`? (Q13 of this brief)
- What is `Record Status` and what replaces `..........`? (Q14 of this brief)
- Do we adopt the customer's header names or keep v2's corrected ones? **New —
  raised by the code check, not by the customer.**

---

## Answers — round 2, 2026-09-08 (owner)

### Answered

- **All four black columns are genuinely required** — `Avg Phase Angle Ph-A/B/C`
  and `Record Status`. Together with the seven red ones that is **11 new
  columns**, confirmed.
- **The billing file is an appended CSV**, one file per meter that grows, the way
  the Load Profile CSV does — not one file per period.

### The meters do not all have the data — checked against real scans

`docs/meter-notes/load-profile-capture-objects.md` was scanned off real hardware
on 2026-08-05. What it says about the two quantities:

| quantity | Prometer 100 | Premier 550 | Saral 305 | Mitsubishi |
|---|---|---|---|---|
| line-to-line voltage | **yes** — Logger 2, `1.0.157/177/197.27.0.255` | no — Logger 2 carries L-N only | no Logger 2 at all | **no L-L register exists** (`mitsu-obis-scan.md:66`) |
| phase angle | **yes** — Logger 1, `1.0.81.27.4/15/26.255` + `1.0.81.24.128.255` | not in the scan | not in the scan | yes (`mitsu-obis-scan.md:55`) |

Two consequences, neither of them ours to fix:

1. **On most models these columns will be empty**, because the meter never
   captured the value. That is not a defect and it cannot be coded around. The
   customer's own licence is CEWE **Premier 550**, which is precisely the model
   that does **not** expose line-to-line voltage.
2. **On the Prometer 100 the line-to-line voltages are already being read and
   thrown away today.** Issue #24 decision D17 stored Logger 2 anyway but mapped
   only `freq`: *"the three line-to-line voltages are dropped structurally, no
   field for them"*. So for that one model this is adding fields to catch data
   already arriving — cheap.

**Phase angle has a second trap.** v1 maps it as `1.0.81.**7**.…`; the meter
actually captures `1.0.81.**27**.…` — same quantity, different D value — so v1
reads them and discards them, and its `avg_phase_angle_*` columns are NULL on
this model. `load-profile-capture-objects.md:120-133` records this and warns:
if v2 maps it correctly it will show numbers v1 leaves blank, which **looks like
an Output Parity regression and is not one**. The parity test has to be written
knowing this.

### Still open

- **`Record Status` on a Load Profile row is still undefined.** It is blank in
  every sample row of the customer's LP file, and `..........` in every billing
  row. v2 has `record_status` only on `billing_readings`, where it marks the Open
  Period — a different meaning. Nothing yet says what this column should contain.
- **Header names.** The customer's sample uses v1's `Import kWh Active`; v2 uses
  `Import Reactive (kvarh)` etc. because v1 called a kvarh quantity kWh
  (owner ruling 2026-08-11, `format.py:29-33`). Matching the sample reverses that
  ruling. **Decision: notify the customer rather than ask** — the file will carry
  v2's corrected names.

---

## Live meter probe — 2026-09-08

Re-read off the physical meters today with `app/scripts/probe_capture_objects.py`
(read-only: one association, attributes 3 and 4, nothing written). **The
2026-08-05 scan is confirmed unchanged.**

| | Prometer 100 | Premier 550 | Saral 305 |
|---|---|---|---|
| Logger 1 | 900 s, 25 columns | 900 s, 7 columns | 900 s, 15 columns |
| Logger 2 | 300 s, 8 columns | 900 s, 14 columns | **absent** |
| line-to-line voltage `1.0.157/177/197.27.0.255` | **yes** (Logger 2) | no | no |
| phase angle `1.0.81.27.4/15/26.255` | **yes** (Logger 1) | no | no |
| frequency `1.0.14.27.0.255` | yes (both loggers) | **no** | **no** |
| power factor total `1.0.13.24.0.255` | yes | **no** (per-phase only) | **no** |

### The decisive precedent: two columns are already empty today

`_EXPORT_HEADERS` (`export/format.py:34`) ships `Avg Geo PF` and
`Frequency (Hz)`. Neither the Premier 550 nor the Saral 305 captures either
quantity, and neither driver maps them — `saral305.py:46` says so in a comment:
*"power factor on this model's Logger 1 (D16) — `freq` and `avg_geo_pf`"*.
`premier550.py` maps neither.

**So the customer already receives a Load Profile CSV with two permanently empty
columns on those two models, and has never raised it.** An empty column for a
model that does not capture the quantity is the shipped, accepted behaviour — not
a new compromise this request would introduce.

That changes the shape of the question. It is no longer *"should we build columns
that will be empty?"* — we already ship two. It is *"is the customer content that
these are empty on Premier 550 and Saral 305, the way Avg Geo PF and Frequency
already are?"* — which is a notification, not a blocking question.

### What this makes buildable

- **Line-to-line voltage** — Prometer 100 only. v2 already reads it every 300 s
  and drops it (issue #24 D17). Adding three fields catches data already
  arriving. Empty on the other two models, like `freq`.
- **Phase angle** — Prometer 100 only, at `1.0.81.27.4/15/26.255`. Confirmed on
  the meter today, and confirmed **absent** from Premier 550 and Saral 305, so
  the earlier "not found in the scan" for those two is now a definite no.
- The fourth Prometer 100 phase-angle object `1.0.81.24.128.255` is captured too
  and maps to nothing. Out of scope here; recorded so it is not rediscovered.

---

## Record Status — recommendation, 2026-09-08

**The source is settled; only the rendering is open, and that is ours to choose.**

### What the column is

`1.0.96.5.4.255` — a **13-bit status bitmap**, one per load-profile interval.
v1 names it exactly that (`constants.py:311`,
`LP_STATUS_FLAG_OBIS ... # 13-bit status bitmap`), maps it to `status_flag`
(`load_profile_reader.py:354`) and decodes it into `record_status`.

Confirmed on the meters **today**, in Logger 1:

| | Prometer 100 | Premier 550 | Saral 305 |
|---|---|---|---|
| `1.0.96.5.4.255` | **yes** | **yes** | **no** |

So v2 is already reading it — it is a capture object inside the profile we pull —
and dropping it, exactly like the three line-to-line voltages.

### The rendering: two references disagree, and neither is the customer's decision

- **v1** (`_decode_status_flag`, `load_profile_reader.py:1128`) writes words:
  `OK` when the flag is 0, otherwise a comma-joined list of `ALL_INVALID`
  (bit 0), `DISTURBED` (bit 4), `POWER_LOSS` (bit 11), and `STATUS_0x{flag:04X}`
  for anything else.
- **The customer's sample** writes `..........` — **exactly ten characters**,
  verified identical in all four sample files. That is a
  flags-as-positions convention from the Windows-Forms program, not from v1.

**Recommend v1's wording.** Four reasons:

1. **Output Parity is judged against v1**, and v1's outputs are the
   customer-confirmed ground truth.
2. **`OK` is readable by the person who opens the CSV.** `..........` needs a
   legend of which position means what, and no such legend exists in anything
   the customer sent.
3. **The customer never asked for dots.** They pasted a sample from a third
   program; nothing in the notes says the dots themselves matter.
4. **We could not reproduce the dots faithfully anyway.** Ten characters against
   a thirteen-bit word means we do not know which ten flags, in which order —
   information we do not have and the customer may not either. Copying a format
   we cannot decode would produce a column that looks right and means nothing.

### Two caveats to carry into the issue

- **Saral 305 has no status bitmap**, so the column is empty on that model —
  the same family as `Avg Geo PF` and `Frequency (Hz)`, which are already empty
  there today.
- **Do not map SMART TCC's `0.0.96.10.1.255`.** v1 found it and deliberately
  left it unmapped, saying so at `load_profile_reader.py:343`: *"bitmap
  semantics unverified vs `_decode_status_flag` (live-verification item; do NOT
  map)."* Mapping it without verifying would put confident, wrong words in the
  column — worse than leaving it blank.

### The billing file's Record Status is a different column with the same name

The customer's **billing** sample also has a `Record Status` header, also
`..........`. That cannot be the load-profile interval bitmap — billing rows are
period cuts, not intervals. What v2 actually knows for a billing row is whether
it is the **Open Period** (`billing_readings.record_status = 'open'`, else NULL).

**Recommend: say so explicitly in the issue** rather than letting one header name
carry two meanings silently. The billing CSV's column should state whether the
period is open or closed, which is the only status v2 holds for that row.

### The question to put to the customer

Not *"what should Record Status contain?"* — they answered that by including the
column at all. Ask instead:

> "ช่อง Record Status เราจะเขียนเป็นคำว่า `OK` หรือ `DISTURBED` / `POWER_LOSS`
> แทนจุด `..........` นะครับ จะได้อ่านออกเลยว่าช่วงไหนมีปัญหา — โอเคไหมครับ"

A person who does not know the bitmap can answer that. Nobody can answer the
first version.

---

## Answers — round 4, 2026-09-08 (owner) + the SMART TCC evidence

### Answered

- **Record Status: render it as words, v1's way** — `OK` / `ALL_INVALID` /
  `DISTURBED` / `POWER_LOSS`, not the customer's `..........`. **With one
  correction the owner could not have known, below.**
- **Header names: keep v2's corrected ones** (`Import Reactive (kvarh)`), and
  tell the customer rather than ask.

### The model that actually matters was missing from every table so far

The customer database the owner supplied (`C:\Users\HP\Downloads\data`) holds
**exactly one device**:

```
id=1  name='3CL'  model='st3cl'  meter_serial='002607000049'  consecutive_failures=0
```

Not a CEWE at all — a **SMART TCC 3CL**. Every model comparison in this brief
until now covered only the three CEWE meters, because the SMART TCC test meter
is unreachable (`203.170.148.103:4059`, timeout on 4059 and 50001). Its capture
objects were read on **2026-07-18** and are recorded in
`docs/meter-notes/tcc-obis-scan.md:648`.

Reading that list against the eleven requested columns:

| requested | Prometer 100 | Premier 550 | Saral 305 | **SMART TCC 3CL** |
|---|---|---|---|---|
| phase angle ×3 | `1.0.81.27.4/15/26` | — | — | **`1.0.81.7.40/51/62`** |
| Record Status | `1.0.96.5.4` | `1.0.96.5.4` | — | **`0.0.96.10.1`** |
| line-to-line ×3 | `1.0.157/177/197.27` | — | — | — |
| power kW/kvar ×4 | `1.0.1/2/3/4.5.0` | — | — | — |
| **total** | **11 / 11** | **1 / 11** | **0 / 11** | **4 / 11** |

The scan file's own summary line (`tcc-obis-scan.md:639`) calls the TCC load
profile *"โครงตรง requirement ของลูกค้า"* — the structure matches what the
customer asked for. That is consistent: the customer's notes mark **only ST-3CL**
as `ดึงได้แล้ว`.

### This also explains v1's phase-angle bug

v1 maps phase angle as `1.0.81.**7**.40/51/62.255` — which is **exactly what the
SMART TCC captures**. It is wrong only for the Prometer 100, which uses
`1.0.81.**27**.4/15/26.255`. v1's map was written against the TCC family and
silently produced NULL on the CEWE meter. Not a typo: a map built for one family
and reused for another.

### Correction to the Record Status answer, which the owner could not have known

v1's `_decode_status_flag` decodes **`1.0.96.5.4.255`** — the CEWE bitmap, bits
0 / 4 / 11. **The SMART TCC's status word is a different object,
`0.0.96.10.1.255`**, and v1 deliberately refused to map it
(`load_profile_reader.py:343`):

> *"record-status `0.0.96.10.1.255` — bitmap semantics unverified vs
> `_decode_status_flag` (live-verification item; do NOT map)."*

So "use v1's wording" is right **for the CEWE bitmap** and cannot be extended to
the TCC one without verifying it first. Running the CEWE decoder over the TCC
word would print `DISTURBED` and `POWER_LOSS` from bit positions nobody has
checked — confident, wrong, and unfalsifiable from the CSV.

**Recommendation:** implement the decode for `1.0.96.5.4.255` only; leave the
TCC column blank until the bitmap is verified on hardware, exactly as v1 chose.
The verification needs the TCC meter to be reachable, which it currently is not.

### What this does to the size of the work

The columns split cleanly into two groups by cost:

- **Phase angle + Record Status** — captured by **three of the four families**
  (Prometer 100, SMART TCC, and Record Status also on Premier 550). This is the
  half worth building.
- **Line-to-line voltage + the four power columns** — **Prometer 100 only**, and
  the machine we have data from does not own one. This is the half to defer
  until the customer confirms a Prometer 100 exists somewhere.

---

## The owner's own machine has two Prometer 100s — 2026-09-08

Read from a copy of `C:\ProgramData\ARICHDS\arichds.db` (copied out, opened
read-only; nothing under `%ProgramData%` was touched):

```
1  Prometer100_4059  CEWE  prometer100  WP079074  online
2  Phase 2           cewe  premier550   SS18197374  online
3  saral             cewe  saral305     SS21996979  online
4  OTC2              cewe  prometer100  WP080652  online
```

**So the blocking question is answered for development purposes**: there are two
Prometer 100s online to build and verify against. The remaining customer question
is narrower — *which model is installed at the site the sample files came from*
(`WP076996`, `WP080672`), since those serials belong to neither this machine nor
the SMART TCC machine.

### The line-to-line data is already in the database, and already wasted

Counting non-NULL values per stored row:

| | rows | data columns with any value |
|---|---|---|
| Prometer 100 · Logger 2 (300 s) | **26,128** | **2 of 13** — `freq`, `interval_sec` |
| Prometer 100 · Logger 1 (900 s) | 8,709 | 12 of 13 |
| Premier 550 · Logger 2 | 8,706 | 7 of 13 |

Logger 2 on a Prometer 100 carries the three line-to-line voltages every 300
seconds. **26,128 rows are being written per device to keep two useful values**,
because there is no column for the other three — issue #24's decision D17, stated
plainly and now measured. Two devices are doing this, at 288 rows/device/day.

**Adding three columns does not add a read, a poll, or a row.** It gives the rows
we already pay for something to hold. That moves the largest item in group A from
"expensive and unverifiable" to "cheap, and testable against hardware on the
desk".

### Defect found while checking: `avg_geo_pf` is NULL on every row of every meter

| model | rows | `avg_geo_pf` non-null |
|---|---|---|
| prometer100 (dev 1) | 8,709 | **0** |
| premier550 (dev 2) | 8,706 | 0 |
| saral305 (dev 3) | 8,709 | 0 |
| prometer100 (dev 4) | 8,709 | **0** |

Zero out of **87,000+ rows across four meters.** For the Premier 550 and the
Saral 305 that is expected — neither captures `1.0.13.24.0.255`, and
`saral305.py:46` says so. **For the Prometer 100 it is not**: the probe run today
shows `1.0.13.24.0.255 attr=2 class=3` in its Logger 1, and
`prometer100.py:77` maps `("1.0.13.24.0.255", 2) -> avg_geo_pf`. Capture object
present, mapping present, value absent.

**This corrects an argument used earlier in this brief.** The claim was that
*"the customer already receives a CSV with two permanently empty columns and has
never raised it, so an empty column is accepted behaviour"*. That is true of
`Frequency (Hz)`, which is genuinely absent from two models. It is **not** true of
`Avg Geo PF`, which is empty on the model that does provide it. That column is
empty because of a defect, not because of the meter — so it cannot be cited as
precedent for shipping empty columns.

Root cause not traced. Needs its own issue and a `/diagnosing-bugs` pass; the
candidates are the scaler/unit path for `Unit.NONE`, the `(OBIS, attribute)` key
match, and the meter returning a null value. **Do not guess in the issue body.**

### One earlier observation resolved

`C:\Users\HP\Documents\test-cewe\Billing` holds `SS18197374`, `SS21996979` and
`WP079074` — devices 2, 3 and 1 of **this machine**. It is the owner's own capture
output, not the customer's. The missing `.xlsx` on one meter and missing `.png` on
another are most likely licence churn on the development box across the months
those captures span, which is a far less alarming explanation than the one
recorded earlier. Still unconfirmed, but no longer customer-facing.

### Question withdrawn: which model is at the sample-file site

Asked, then challenged by the owner, then checked. **It changes nothing we would
build**, so it is dropped rather than carried:

- *Deciding whether to build it* — already answered. Two Prometer 100s are online
  on the owner's machine and the Logger 2 data is already being stored and
  discarded. Adding columns costs no read, no poll and no row, so the work is
  justified whatever the customer's site holds.
- *Finding hardware to verify against* — already answered by the same two meters.
- *Output Parity* — judged against v1's numbers, not against a site.

The code is identical either way; only whether that customer's file has values in
those columns differs, and that is an outcome, not an input to the decision.

The one thing the answer would have served — stopping the customer opening the
file, seeing three empty columns and reporting a bug — needs no answer either.
The sentence to send is the same in every case: **"these three columns carry
values on Prometer 100 only."**

**A coherence signal, recorded but not relied on.** On the owner's machine the
serial prefixes split cleanly by model — `WP079074` and `WP080652` are Prometer
100s, `SS18197374` is a Premier 550, `SS21996979` a Saral 305. The customer's
sample files are `WP076996` and `WP080672`. Two `WP` observations is not enough
to assert a rule. But it sits alongside a stronger observation: **the eleven
columns the customer asked for are exactly the Prometer 100's capability set,
neither short nor over.** Somebody did not pick eleven columns at random and
happen to land on the one model of four that provides all of them.

### Record Status rendering — customer approved, 2026-09-08

The customer agreed to words rather than dots. **All customer questions on these
three briefs are now closed.**

What that settles, and what it does not:

- **CEWE meters** — implement the decode for `1.0.96.5.4.255` and render v1's
  wording (`OK`, `ALL_INVALID`, `DISTURBED`, `POWER_LOSS`, `STATUS_0x….`).
  Fully specified; nothing outstanding.
- **SMART TCC** — still blank. Its status word is `0.0.96.10.1.255`, a different
  object whose bitmap v1 refused to decode because the semantics were never
  verified. The approval covers *how to render a decoded flag*, not *which bits
  mean what on a family nobody has checked*.

**Worth telling the customer plainly:** on a SMART TCC machine this column will
stay empty until that meter is reachable and its bitmap verified — and the TCC
test meter is exactly the one that does not answer (`203.170.148.103`, timeout on
both ports). The approval does not change that, and the gap should not arrive as
a surprise in a delivered file.

Verifying it needs one association to a reachable TCC and a comparison of the
raw word against a known meter state. Until then, blank is the honest output —
the same call v1 made at `load_profile_reader.py:343`.
