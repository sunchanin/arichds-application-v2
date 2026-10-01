# 05: Average power factor is empty on every row ever stored

**What to build:** the Load Profile page and the Load Profile CSV show a value in the
Average Power Factor column on a meter that records it. Today they never have.

**Blocked by:** 04 (the declaration this changes is the one ticket 04 reshapes).

**Status:** ready-for-agent

Source: `.scratch/export-files/spec.md`. Found while checking the customer's export
request; diagnosed during the phase 3 grill, 2026-09-09.

## What is wrong

`avg_geo_pf` is NULL on **all 87,000+ stored rows across four meters**, including on the
two Prometer 100s whose hardware records the quantity and whose driver maps it.

The cause is measured, not suspected. A read-only probe on 2026-09-09 shows the register
the driver borrows its scaler from answers with unit **no unit (255)**, while the column
declares unit **none (0)**. They are different members of the same enumeration. The
multiplier is therefore rejected, and a column with no resolved multiplier stores nothing
on every row — which is correct, deliberate behaviour, applied to a wrong declaration.

Nothing logs an error. Nothing fails. The column has simply been empty since it shipped.

## What to change

- [ ] The declared unit for this column matches what the meter actually reports.
- [ ] Nothing else. This is one enumeration value.

## What this ticket must not do

- [ ] Do not widen the unit check so that any unit is accepted. The check is what makes the
      stored value trustworthy; loosening it would trade an empty column for a wrong one.
- [ ] Do not fold this into ticket 04 or ticket 06. In 04 it would falsify that ticket's
      claim to change no behaviour; in 06 a fix to a shipped defect would be invisible among
      eleven additions.

## Gate

- [ ] `ruff format --check` and `ruff check` pass.
- [ ] `pytest -n auto` passes.
- [ ] **A real meter read, by hand**: connect to a development Prometer 100, run a load
      profile read, and confirm the stored column is non-NULL. Attach the values to this
      ticket.
- [ ] **Automated tests alone do not close this.** The meter fake is applied to every test
      automatically and answers with whatever the fake declares, regardless of whether a
      scaler would resolve against real hardware. That is exactly how this defect passed
      every gate for 87,000 rows.

## Real-meter result — 2026-09-09, read-only

Development Prometer 100 `WP079074` at `203.170.151.152:4059`. One association,
attribute reads only, through the **shipped driver's own `read_load_profile()`** —
not an isolated scaler probe, because the defect was never in reading the scaler
but in the declaration the read was checked against.

Logger 1, a three-hour window, twelve rows:

```
avg_geo_pf              12/ 12 non-NULL   0.07599999755620956, ... , -0.9989999532699585
import_active_kwh       12/ 12 non-NULL   0.008524200000000001
volt_l1                 12/ 12 non-NULL   237.7141571044922
current_l1              12/ 12 non-NULL   0.6092000007629395
freq                    12/ 12 non-NULL   49.98400115966797
```

Before this change the same read returned `None` for `avg_geo_pf` on every one of
those twelve rows, and for all 87,000+ rows already stored.

The value is also consistent with the other columns rather than merely present:
0.0085242 kWh over a 900 s interval is 34 W, against 237.7 V × 0.6092 A × 3 ≈ 434 VA,
which gives a power factor of ≈ 0.079 for a declared 0.076. The last row reads
−0.999, so the sign is carried too.
