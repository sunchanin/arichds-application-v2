# CEWE billing capture objects — Prometer 100 / Saral 305 / Premier 550

Read off the physical meters on **2026-08-09**, read-only, via
`app/scripts/probe_m4c_read.py` (issue #24, M4c). This is field evidence —
what the meters actually answered — not a restatement of the OBIS scheme.
Nothing was written to any meter.

| Meter | Endpoint | Meter Serial | Billing entries_in_use | Billing capture columns |
|---|---|---|---|---|
| Prometer 100 | `203.170.151.152:4059` | `WP079074` | 10 | 69 |
| Saral 305 | `203.170.151.217:4059` | `SS21996979` | 13 | 104 |
| Premier 550 | `49.229.159.44:50001` | `SS18197374` | 5 | 73 |

These column counts match `docs/meter-notes/load-profile-capture-objects.md`'s
"How it was captured" table (69/104/73, scanned 2026-08-05) exactly — the
billing profile shape has not changed on any of the three meters between the
two scans.

## The billing profile is `1.0.98.2.0.255` on all three, entry 1 = newest

Confirmed live: `entries_in_use` is read fresh every call (never assumed),
and the row at entry 1 has the highest `bill_date` and `is_open=True` on
every model — F4's finding holds.

## What resolved, and to what — the twenty new columns

Every one of the ten Demand Time columns (`max_demand_import_active_time_*`,
`max_demand_import_reactive_time_*`) resolved to a real, sensible UTC
timestamp on all three models, on every closed period read — the reset-reason
open/closed discriminator worked correctly on every row, and rate A/B/C all
carry distinct values (rate D is `NULL` on every model: this fleet uses three
active tariffs, not four).

**Cumulative Demand — fixed same-day, after the first read exposed the gap.**
The first live read showed every Cumulative Demand column `NULL` on every
model: the driver tried the column's own `scaler_unit` (attr 3) and the `E=0`
sibling of the same `C.2` group; both were refused. **The meter denies
`scaler_unit` on every `D=6` (max demand) tariff column too** (`E=1`..`E=4`),
not just `D=2` — only each `D` group's own total (`E=0`) answers directly.
`resolve_billing_multiplier` (`acquisition/drivers/_cewe.py`) now tries, in
order: the column's own address, the `E=0` sibling of its own group, the
same-tariff `D=6` sibling, and finally the `D=6` group's own total (`E=0`) —
that last step is what actually resolves every Cumulative Demand column on
a live re-read, total and every populated tariff alike (Premier 550 and
Prometer 100 both capture this OBIS group; Saral 305 does not capture it at
all — see "What resolved" below). **This is v1's proven route**
(`cewe-worker/_tcp_driver_base.py:861-873`): borrow the D=6 max-demand
scaler for the same physical quantity, same unit.

## Load-profile scalers: the same refusal, fixed the same day

**Every CEWE model refused `scaler_unit` (attr 3) on essentially every
load-profile measurement column tried directly at its own address**, on the
first live read:

```
WARNING <model>: could not read scaler_unit for 1.0.1.29.0.255 (import_active_kwh)
WARNING <model>: could not read scaler_unit for 1.0.32.27.0.255 (volt_l1)
... (repeated for every energy, voltage and current column on all three models)
```

The one exception: Prometer 100's frequency column (`1.0.14.27.0.255`)
resolved directly on both loggers.

**This is the same pattern the SMW110W4 already has a documented, working
fix for** (`smw110w4-scan.md`): that meter also denies `scaler_unit` on every
load-profile capture column, and `Smw110Driver._resolve_multiplier` works
around it by borrowing the scaler from a different, always-readable sibling
OBIS chosen by required Unit. **The three CEWE drivers now do the same** —
each mapped column in `prometer100.py` / `saral305.py` / `premier550.py`
declares a sibling OBIS (D=29 interval energy borrows D=8 cumulative energy,
D=27 V/I borrows the D=7 instantaneous sibling, D=24 total PF borrows D=7),
and `resolve_load_profile_multiplier` tries the column's own address first,
then the sibling, memoized per connection so a 90-day chunked backfill does
not re-issue the same DLMS round trip once per chunk.

**Re-read live after the fix**: real, plausible values resolved for every
mapped column on all three models — voltage, current and interval energy on
Prometer 100's and Saral 305's Logger 1; interval energy on Premier 550's
Logger 1; voltage and current on Premier 550's Logger 2. The one column
still `NULL` after the fix is Prometer 100's `avg_geo_pf` (total power
factor): its own address and its declared sibling (`1.0.13.7.0.255`) both
fail to resolve. D12 still applies — no guessed multiplier — so it stays
`NULL` rather than inventing a number. No other CEWE model maps `avg_geo_pf`
at all (D16), so this is the only remaining gap.

**v1 shows a number here, not a blank — expected, not a parity gap.** v1
applies **no scaler at all** on the load-profile read path
(`cewe-worker/src/worker/load_profile_reader.py:814` guards on
`co.scaler is not None`; the cache-fill at `:1240-1250` never sets it), so
its `avg_geo_pf` column is the meter's **raw, unscaled** integer — not a
correctly-scaled value it happens to have and v2 does not.
`load-profile-capture-objects.md:129-131` already carries this exact warning
for the Prometer 100's phase angles: *"if v2 maps these correctly it will
show numbers v1 leaves blank [or, here, wrong] — that is v2 being right, not
v2 diverging, but the parity test must be written knowing it."* The same
applies in reverse for `avg_geo_pf`: v2's `NULL` is the correct, honest
answer (no scaler resolved, D12 forbids guessing one), and v1's raw number
is not evidence v2 is missing something — it is v1 showing an unscaled
integer as if it were a power factor. At the owner's live parity comparison,
read v1's `avg_geo_pf` column knowing this, or it will look like a
regression that is not one.

### Resolved / NULL counts, live re-read (after both fixes)

| Model | Billing (of 60) | Load profile |
|---|---|---|
| Prometer 100 | 48 resolved, 12 NULL (all `rate_d` — no 4th tariff on this fleet) | Logger 1: volt/current/freq/energy resolve; `avg_geo_pf` NULL. Logger 2: `freq` resolves; nothing else maps |
| Saral 305 | 22 resolved, 38 NULL (F10's measured hardware NULL set — unaffected by the scaler fix, since those OBIS are simply absent from the live capture list) | Logger 1: volt/current/energy resolve; no `freq`/`avg_geo_pf` column exists on this model (D16) |
| Premier 550 | 48 resolved, 12 NULL (all `rate_d`) | Logger 1: energy resolves. Logger 2: volt/current resolve; no `freq`/`avg_geo_pf` column exists on this model (D16) |

## Limitations

- Read once, against whichever billing period was open at scan time
  (2026-08-09). `entries_in_use` and the specific values above will have
  moved by the time anyone next reads this file — the *shape* (column
  counts, which columns resolve, which do not) is the part expected to
  still hold.
- The scan used a 6-hour load-profile window; it does not rule out a wider
  window returning different scaler behaviour (unlikely, since `scaler_unit`
  is a property of the column, not the window, but not verified).
- No password appears in this file, in `probe_m4c_read.py`, or in any test
  fixture built from this scan — the CEWE fixed password is recorded once,
  in `CLAUDE.md`'s "v1 as reference" section, and is passed to the probe
  script as a command-line argument only.
