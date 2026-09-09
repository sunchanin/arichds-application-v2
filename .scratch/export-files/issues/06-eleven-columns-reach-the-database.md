# 06: The eleven requested quantities stop being discarded

**What to build:** the three average phase angles, the interval status word, the four
average power quantities and the three line-to-line voltages are stored with every Interval
Reading. Every one of them is already inside a buffer the product reads off the meter every
cycle and throws away for want of a field — this ticket gives those rows somewhere to put
them. Nothing an operator sees changes yet; ticket 07 carries them to the file and the
screen.

**Blocked by:** 05 (which is blocked by 04 — this ticket edits the same declarations both
of those touch, and wants their diffs separate from its own).

**Status:** ready-for-agent

Source: `.scratch/export-files/spec.md`. Requirements A1/A2.

## Storage

- [ ] Eleven new nullable columns on the Interval Reading, plus one migration.
- [ ] The interval status column is named for the product term, **Interval Status**, not
      for the customer's file header. The glossary already separates that term from
      **Records**, and the Billing Reading already owns a differently-meaning column of the
      header's name.
- [ ] The status word is stored as **the raw integer**, decoded at render time. Its bit
      meanings are settled for one meter family and unverified for another; storing decoded
      text would make every historical row permanently un-decodable on the day the second
      family is finally verified. This is also what v1 does.

## Driver mapping — from real scans, per family

- [ ] **Prometer 100** — all eleven.
- [ ] **Premier 550** — the interval status word only.
- [ ] **Saral 305** — none. The meter records none of them.
- [ ] **SMART TCC** — the three phase angles, which it captures at a different address than
      CEWE does. Its status word is a different object whose bit meanings nobody has
      verified on hardware, and v1 deliberately refused to map it. **It stays unmapped.**
- [ ] The SMART TCC mapping comes from the July scan and **cannot be verified now** — that
      meter answers on neither port. Record in the code that these three are not
      hardware-verified, and how to verify them when the meter is reachable. Do not let this
      ticket's acceptance imply they were checked.

## Scaler sources — measured, read-only, 2026-09-09

Every own-address scaler read was denied on all twelve targets, so the sibling is the only
path on this family. That matches the 2026-08-09 billing scan; do not spend a probe
rediscovering it.

- [ ] Phase angles, line-to-line voltages and the two **import** power columns resolve
      through their D=7 sibling.
- [ ] The two **export** power columns do not — their D=7 siblings are denied. They resolve
      from the maximum-demand export registers, read as an **Extended Register**. Same
      physical quantity, same unit, different statistic; the billing path already borrows
      across addresses this way, and ADR 0002 is satisfied because the scaler is read rather
      than assumed.
- [ ] The interval status word offers no scaler and is a passthrough column.

## The failure mode to design against

**Every scaler on the reference meter is 1.0.** A scaler that fails to resolve does not
produce a wrong magnitude — it produces nothing. So a mistake in this ticket will not look
like a wrong number. It will look like a meter with no data, which is precisely what ticket
05's defect looked like for 87,000 rows.

- [ ] A column whose scaler resolves to nothing stores nothing, never a raw count. Assert
      this; do not merely rely on it.

## Gate

- [ ] `ruff format --check` and `ruff check` pass.
- [ ] `pytest -n auto` passes.
- [ ] Driver tests: given a buffer carrying the full capture list, the eleven fields land in
      the right places and the scaler candidates are tried in declared order.
- [ ] **A real meter read, by hand**: a development Prometer 100, all eleven columns
      non-NULL in the database, values attached to this ticket.
- [ ] **A cross-quantity check, by hand**: average export power over an interval, times the
      interval length, against the export energy stored for that same interval. Because
      every scaler here is 1.0, a wrongly borrowed scaler yields a plausible number rather
      than a blank — and comparing a stored value against the register it came from would
      prove only that it was copied faithfully.
- [ ] **No extra meter read, poll or row.** Confirm the cycle asks the meter for exactly
      what it asked for before.
- [ ] Record in this ticket that the new columns will reach any configured **Database
      Destination automatically** on the next sync, because the destination derives its
      schema from ours and reconciles by adding what is missing. That is designed behaviour
      with a precedent, and it is still a schema change fired into a customer's own database.

## Real-meter result — 2026-09-09, read-only

Development Prometer 100 `WP079074` at `203.170.151.152:4059`, through the shipped
`read_load_profile()` on both loggers. Three hours.

```
logger 1 — 12 rows, interval 900 s
  phase_angle_a           12/ 12 non-NULL   0.0
  phase_angle_b           12/ 12 non-NULL   0.0
  phase_angle_c           12/ 12 non-NULL   0.0
  import_active_kw        12/ 12 non-NULL   0.0343844
  import_reactive_kvar    12/ 12 non-NULL   0.4384872
  export_active_kw        12/ 12 non-NULL   0.0
  export_reactive_kvar    12/ 12 non-NULL   0.0
  interval_status_flag    12/ 12 non-NULL   0

logger 2 — 36 rows, interval 300 s
  volt_l1_l2              36/ 36 non-NULL   416.26287841796875
  volt_l2_l3              36/ 36 non-NULL   416.47479248046875
  volt_l3_l1              36/ 36 non-NULL   410.00494384765625
```

All eleven resolve a scaler and store a value. A column whose multiplier does not
resolve stores `None`, so non-NULL is itself the proof that each declared sibling
and each declared COSEM class was accepted by the meter — including the two export
columns, which resolve only through their D=6 max-demand siblings read as Extended
Registers.

### The cross-quantity check — passes on import, proves nothing on export

```
import_active_kw       worst error 0.00 %  OK
import_reactive_kvar   worst error 0.00 %  OK
export_active_kw       worst error 0.00 %  OK      <- vacuous
export_reactive_kvar   worst error 0.00 %  OK      <- vacuous
```

`kW x interval_hours` against the energy stored for the same interval, over all
twelve rows. The two import columns agree exactly, which verifies the whole
mechanism end to end: the Demand Register captured at attribute 3, the scaler read
at attribute 4, the sibling borrow, and the W-to-kW division.

**The two export rows are not evidence.** This site exports nothing, so both the
power and the energy are zero and the comparison is zero against zero — it would
have reported `OK` under a wrong multiplier just as readily. What *is* verified for
the export pair is that the borrowed scaler resolves at all, under the right unit
and only as an Extended Register; what is not verified is the multiplier applied to
a non-zero value. That needs a site that exports, and there is not one to hand.
Recorded rather than papered over.

### The phase angles read zero, and that is the meter's own answer

All three phase angles are `0.0` on every row, which sits badly beside an
`avg_geo_pf` of 0.076 on the same meter — a power factor that low implies an angle
near 86 degrees.

Checked rather than assumed: reading the **instantaneous** registers
`1.0.81.7.4/15/26.255` directly returns `0.0` as well, with scaler 1.0 and unit
`PHASE_ANGLE_DEGREE`, while `1.0.13.7.0.255` on the same association returns 0.078.
So the meter reports zero for phase angle and a real number for power factor. Our
columns transcribe what it says; the mapping is right and the datum is zero on this
unit.

The customer should be told this, because their sample file expects those three
columns populated: on this firmware the meter answers zero, and no mapping change
on our side can produce a number it does not report.

### Confirmed: no extra meter read

The cycle reads ProfileGeneric attribute 3 and attribute 4 and fetches the buffer
once, exactly as before — pinned by
`test_load_profile_new_columns.py::TestTheCycleAsksTheMeterForNothingNew`. The only
new traffic is scaler resolution, which is memoized per connection, so a chunked
backfill resolves each column once rather than once per chunk.

### Confirmed: the eleven reach a Database Destination automatically

`dataout/schema.py` derives its columns from `LoadProfileReading`, so the next sync
issues `ALTER TABLE ... ADD COLUMN` against the customer's own MySQL for all eleven.
Designed behaviour with a precedent — `billing_readings` grew from 40 columns to 60
the same way at M4c — and ADR 0020 requires it, since a destination that mirrors our
window cannot mirror only part of it. **It is still a schema change fired into
somebody else's database.** Pinned by
`test_dataout_sync.py::TestNewLocalColumnsReachTheDestinationDefinition`.
