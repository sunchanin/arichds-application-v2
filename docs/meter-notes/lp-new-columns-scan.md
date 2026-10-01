# Load-profile scalers and column fill — the eleven M13 columns

Scanned off real meters, read-only. Nothing was written to any meter.
Passwords are command-line arguments only and appear nowhere here.

| | |
|---|---|
| Meter | CEWE **Prometer 100**, serial `WP079074`, `203.170.151.152:4059` |
| Also read | CEWE **Premier 550**, serial `SS18197374`, `49.229.159.44:50001` |
| Dates | 2026-09-09 (first measurement) and **2026-09-11 (re-read, authoritative)** |
| Scripts | `app/scripts/probe_lp_new_column_scalers.py`, `app/scripts/probe_lp_column_fill.py` |

Both scripts derive their targets from the **driver's own
`LOAD_PROFILE_COLUMN_MAP`**, so what they report is what the product actually
does. Re-run either after changing a column declaration.

```
# from app/
PYTHONPATH=src .venv/Scripts/python.exe scripts/probe_lp_new_column_scalers.py \
    --host 203.170.151.152 --port 4059 --password <supplied by the operator>
PYTHONPATH=src .venv/Scripts/python.exe scripts/probe_lp_column_fill.py \
    --host 203.170.151.152 --port 4059 --password <supplied by the operator> --hours 3
```

## 1. Which scaler source each column resolves through

Every mapped column on this meter resolves. `scaler = 1.0` on every one of them
— which is the single most important fact here, and the reason a mistake in this
area does not look like a wrong number. **It looks like a meter with no data.**

| column | capture OBIS (attr) | own address | sibling that answers | unit |
|---|---|---|---|---|
| `phase_angle_a/b/c` | `1.0.81.27.4/15/26.255` (2) | denied | `1.0.81.7.4/15/26.255`, Register | `PHASE_ANGLE_DEGREE` (8) |
| `volt_l1_l2` / `l2_l3` / `l3_l1` | `1.0.157/177/197.27.0.255` (2) | denied | `1.0.157/177/197.7.0.255`, Register | `VOLTAGE` (35) |
| `import_active_kw` | `1.0.1.5.0.255` (**3**) | denied | `1.0.1.7.0.255`, Register | `ACTIVE_POWER` (27) |
| `import_reactive_kvar` | `1.0.3.5.0.255` (**3**) | denied | `1.0.3.7.0.255`, Register | `REACTIVE_POWER` (29) |
| `export_active_kw` | `1.0.2.5.0.255` (**3**) | denied | `1.0.2.6.0.255`, **ExtendedRegister** | `ACTIVE_POWER` (27) |
| `export_reactive_kvar` | `1.0.4.5.0.255` (**3**) | denied | `1.0.4.6.0.255`, **ExtendedRegister** | `REACTIVE_POWER` (29) |
| `interval_status_flag` | `1.0.96.5.4.255` (2) | — | none, `passthrough=True` | — |
| `avg_geo_pf` | `1.0.13.24.0.255` (2) | denied | `1.0.13.7.0.255`, Register | **`NO_UNIT` (255)** |

Three things a reader is likely to get wrong from a datasheet:

1. **The four power columns are captured at attribute 3 of a class-5 Demand
   Register**, not attribute 2. Attribute 3 there is `last_average_value`, the
   average over the closed demand interval. That class carries `scaler_unit` at
   **attribute 4**; reading attribute 3 for a scaler returns a *value*, which is
   exactly the kind of wrong answer that would be believed.
2. **Import and export power do not resolve the same way.** The export columns'
   `D=7` siblings are denied outright; only their `D=6` max-demand siblings
   answer, and only when read as an **Extended Register**. Same quantity, same
   unit, different statistic.
3. **`avg_geo_pf`'s sibling reports `NO_UNIT` (255), not `NONE` (0).** Declaring
   `NONE` made the multiplier fail the unit check, and the column was NULL on all
   87,000+ stored rows with nothing logged (M13, issue 05).

### Correction to an earlier claim

Several docstrings and the 2026-08-09 notes say **every** own-address scaler read
is refused on this family. Measured 2026-09-11, that is not quite true:
`freq` at `1.0.14.27.0.255` **answers at its own address** (`FREQUENCY` (44),
scaler 1.0) and is the only measurement column here that does. Its declared
sibling is therefore never reached. Harmless — the own address is tried first
anyway — but the blanket statement is wrong, and the 2026-09-09 measurement that
produced it only covered the twelve *new* targets, none of which was `freq`.

## 2. Do the columns actually fill, end to end

Through the shipped `read_load_profile()`, 2026-09-11, three hours:

```
logger 1 — 12 rows, interval 900 s
  phase_angle_a           12/ 12 non-NULL    0.0
  phase_angle_b           12/ 12 non-NULL    0.0
  phase_angle_c           12/ 12 non-NULL   -1.0
  import_active_kw        12/ 12 non-NULL   94.27776599999999
  import_reactive_kvar    12/ 12 non-NULL    0.22555039999999998
  export_active_kw        12/ 12 non-NULL    0.0
  export_reactive_kvar    12/ 12 non-NULL    0.0244884
  interval_status_flag    12/ 12 non-NULL    0

logger 2 — 36 rows, interval 300 s
  volt_l1_l2              36/ 36 non-NULL   413.65972900390625
  volt_l2_l3              36/ 36 non-NULL   414.22021484375
  volt_l3_l1              36/ 36 non-NULL   410.8194274902344
```

## 3. The cross-quantity check — average power against stored energy

`kW × interval_hours` against the energy stored for the same interval. These two
arrive by different routes — different OBIS, different COSEM class, different
scaler sibling — so agreement is evidence. Comparing a stored value against the
register it came from would prove only faithful transcription.

```
import_active_kw       12/12 rows non-zero, worst error 0.00 %  OK
import_reactive_kvar   11/12 rows non-zero, worst error 0.00 %  OK
export_reactive_kvar   12/12 rows non-zero, worst error 0.00 %  OK
export_active_kw       12 rows, every one zero on both sides — VACUOUS, proves nothing
```

**`export_reactive_kvar` is the one that matters.** It borrows its scaler from
`1.0.4.6.0.255` read as an Extended Register — the riskiest declaration in the
set, because every scaler here is `1.0` and a wrong borrow would yield a
plausible number rather than a blank. It now agrees with independently-routed
energy on twelve non-zero rows.

`export_active_kw` stays unverified: this site exports no active power, so both
sides are zero and the comparison would report `OK` under a wrong multiplier
just as readily. Its residual risk is narrow — the identical route
(`D=6` max-demand sibling, Extended Register) is proven on its reactive twin —
but it is not zero, and closing it needs a site that exports.

On **2026-09-09 both export rows read `OK` and neither proved anything.** The
probe could not distinguish "verified" from "nothing to compare" and reported
0.00 % either way; it now counts and names the non-zero rows, and calls the
vacuous case vacuous. That flaw was in the instrument, not the meter.

## Limitations — read before trusting any of this

- **One meter, one firmware.** Everything in §1 and §2 is `WP079074`. The
  Premier 550 was read only for its Interval Status word (`1.0.96.5.4.255`,
  attr 2, class 1 Data), which returns `GXUInt8`, a Gurux integer subclass.
- **`export_active_kw`'s multiplier is unverified against a non-zero value.**
  See §3.
- **The phase angles do not look like phase angles.** They read `0.0`, `0.0`
  and `-1.0`, while `avg_geo_pf` on the same association reads `0.076` — a power
  factor that low implies an angle near 86°. Checked rather than assumed: the
  instantaneous registers `1.0.81.7.4/15/26.255` return the same values, so the
  meter reports these numbers and our columns transcribe them faithfully. Do not
  "fix" the mapping; the mapping is right. Whether this unit's phase-angle
  registers are commissioned is a question for CEWE.
- **SMART TCC is not covered at all.** Its three phase angles
  (`1.0.81.7.40/51/62.255`) come from the 2026-07-18 scan in `tcc-obis-scan.md`
  and have **never been read on hardware** — that meter answers on neither 4059
  nor 50001. `smart_tcc.py` carries the commands to verify them when it is
  reachable. Its status word `0.0.96.10.1.255` stays unmapped.
- **Saral 305 records none of the eleven** and was not re-read for this.
- Scaler values are `1.0` *on this meter*. A site with CT/VT ratios configured
  into the meter could report otherwise, and the resolver reads them rather than
  assuming (ADR 0002) — but no such site has been scanned.

## 4. 2026-09-16 — `avg_geo_pf` re-probed on both Prometer 100 units (ui-audit ticket 05)

The ticket was raised from the dev machine's App Log, which carried 960 copies of
*"prometer100: could not resolve a scaler for 1.0.13.24.0.255 (avg_geo_pf)"*. Every one of
them is stamped **before 11:00 (+07:00) on 2026-09-16** — the build running until then was
0.5.0, which predates the `NO_UNIT` correction in §1 item 3. Build 0.6.0 was installed at
10:58 and has logged the line **zero** times since.

`scripts/probe_lp_new_column_scalers.py`, one association per unit, same day:

```
prometer100 @ 203.170.151.152:4059  (WP079074)  -> every mapped column resolves a scaler
prometer100 @ 147.50.94.190:4060    (WP080652)  -> every mapped column resolves a scaler
```

`avg_geo_pf` resolves through its declared sibling `1.0.13.7.0.255` as a Register with
`NO_UNIT (255)` / scaler `1.0` on **both** units — the first time the second unit has been
measured at all (§"Limitations" above said "one meter, one firmware").

And the column fills, end to end, on the rows 0.6.0 has stored (read-only query against
`%ProgramData%\ARICHDS\arichds.db`, rows created after the install):

```
WP079074  logger 1   18 rows   18/18 avg_geo_pf non-NULL   range -0.352 .. 0.795
WP080652  logger 1   18 rows   18/18 avg_geo_pf non-NULL   range -0.250 .. 0.999
          logger 2   54 rows    0/54 — logger 2 does not capture this column (by design)
```

Plausible power factors (−1..1) on every Logger-1 row. **No code changed for this ticket**:
the fix was M13 issue 05's, and the evidence that it holds on the second unit is this section.
The "warn once per process" branch the ticket reserved for the no-scaler case is not needed,
because the case does not occur on either unit we can reach.

`docs/issues/018` (`export_active_kw`, the sibling that borrows the same way) stays open: it
needs a site that exports active power, which this re-probe does not supply.

