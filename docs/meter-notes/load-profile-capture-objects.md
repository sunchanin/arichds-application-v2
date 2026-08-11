# Load-profile capture objects — CEWE Prometer 100 / Saral 305 / Premier 550

Read off the physical meters on **2026-08-05**. This is field evidence, not
documentation of an intention: it is what the meters actually answered, and it
settles a schema question that could not be settled from a desk.

Raw dumps of every Profile Generic on each meter are in [`raw/`](raw/).

## How it was captured

`cewe/cewe-worker/scripts/probe_profile_capture.py`, parameterised (the v1 repo is
read-only, so the copy that ran lives outside it) and executed with v1's venv. It
opens **one** association per meter and reads attributes 3 (capture objects) and 4
(capture period). Nothing is written to the meter.

| Meter | Endpoint | Driver | Objects | Profile Generic |
|---|---|---|---|---|
| Prometer 100 | `203.170.151.152:4059` | `Prometer100Driver` | 285 | 39 |
| Saral 305 | `203.170.151.217:4059` | `Saral305Driver` | 103 | 19 |
| Premier 550 | `49.229.159.44:50001` | `Premier550Driver` | 185 | 41 |

To repeat it with v2's own driver (Logger 1 / Logger 2 only, plus a merge verdict):

```powershell
cd app
.\.venv\Scripts\python.exe scripts\probe_capture_objects.py --host <ip> --port <port> --password ABCD0001
```

## The headline: the two loggers cannot be merged

`SPEC.md` §3.5 said load-profile rows from Logger 1 and Logger 2 are *"รวมแถวด้วย
`read_at`"* — merged into one row per timestamp. **The meters say that is wrong**,
and for a different reason on each model.

| Model | Logger 1 (`1.0.99.1.0.255`) | Logger 2 (`1.0.99.2.0.255`) | Can they merge? |
|---|---|---|---|
| Prometer 100 | 900 s, 25 columns | **300 s**, 8 columns | **No** — different periods, so no shared `read_at` at all |
| Saral 305 | 900 s, 15 columns | **absent** | N/A — this model has one logger |
| Premier 550 | 900 s, 7 columns | 900 s, 14 columns | **No** — same period, but the columns collide (below) |

**Prometer 100** logs Logger 2 every **5 minutes** against Logger 1's 15. Three
Logger 2 rows exist for every Logger 1 row; there is no timestamp to merge on.

**Premier 550** does share a period, so the merge is arithmetically possible — and
still wrong. Logger 1 captures `1.0.1.29.0.255` and Logger 2 captures
`1.0.1.8.0.255`; v1's OBIS map sends **both to the same column**
(`load_profile_reader.py:208-209` → `import_wh_total_active`). They are not the
same measurement — D=29 is the interval value, D=8 the cumulative total — so a
merge would silently overwrite one with the other. The same collision repeats for
C=2, 3 and 4.

**Prometer 100** collides too, independently of the period problem:
`1.0.14.27.0.255` (frequency) is captured by **both** loggers.

⇒ v1's shape — a `logger_id` discriminator with unique
`(device_id, logger_id, read_at)` — is not incidental complexity. It is what the
data requires. v1's ADR-6 exists for exactly this.

## Two more SPEC statements the meters contradict

1. **"Logger 2 is a Premier 550 thing"** — the Prometer 100 has one as well, and
   the Saral 305 does not. Logger 2 is per-model, and the split is not the one
   SPEC assumed.
2. **"Logger 1 = energy, Logger 2 = V/I/PF/freq"** — true only on the Premier 550.
   The Prometer 100 puts energy *and* V/I/PF/frequency in Logger 1 and reserves
   Logger 2 for line-to-line voltage; the Saral 305 has everything in Logger 1.

## Logger 1 — what each model captures

**Prometer 100** — 900 s, 25 columns

| OBIS | Meaning |
|---|---|
| `0.0.1.0.0.255` | clock (the row timestamp), class 8 |
| `1.0.1/2/3/4.29.0.255` | active/reactive import & export energy, interval |
| `1.0.1/2/3/4.5.0.255` (attr 3) | corresponding max-demand objects, class 5 |
| `1.0.96.5.4.255` | status bitmap, class 1 |
| `1.0.32/52/72.27.0.255` | voltage L-N, L1/L2/L3 |
| `1.0.31/51/71.27.0.255` | current, L1/L2/L3 |
| `1.0.33/53/73.27.0.255` | power factor per phase |
| `1.0.13.24.0.255` | power factor total |
| `1.0.14.27.0.255` | frequency — **also in Logger 2** |
| `1.0.81.27.4/15/26.255`, `1.0.81.24.128.255` | phase angles — **v1 never reads these**, see below |

**Saral 305** — 900 s, 15 columns

`0.0.1.0.0.255` · current `1.0.31/51/71.27.0.255` · voltage L-N
`1.0.32/52/72.27.0.255` · `1.0.149.4.0.255` · energy
`1.0.1/2/16/3/4/9/10.29.0.255`.

`1.0.149.4.0.255` and `1.0.16.29.0.255` are **not in v1's OBIS map** — they were
being read and discarded. **Decided at M4c (issue #24, D16): dropped.** No
screen shows either; `1.0.149.4.0.255` is a manufacturer-range register with
no nameable meaning, and `1.0.16.29.0.255`/`1.0.9.29.0.255`/`1.0.10.29.0.255`
are apparent-kVAh variants no page shows either.

**Premier 550** — 900 s, 7 columns

`0.0.1.0.0.255` · `1.0.96.71.0.255` (active TOU register — v1's
`active_tou_register`) · `1.0.96.5.4.255` (status bitmap) · energy
`1.0.1/2/3/4.29.0.255`. Nothing electrical; that lives in Logger 2.

## Logger 2 — what each model captures

**Prometer 100** — 300 s, 8 columns

`0.0.1.0.0.255` · line-to-line voltage `1.0.157/177/197.27.0.255` ·
`1.0.14.27.0.255` (frequency, duplicated from Logger 1) · and three codes that
appear in **no** v1 mapping: `1.0.11.132.0.255`, `1.0.11.132.124.255`,
`1.0.12.132.124.255`.

**Premier 550** — 900 s, 14 columns

`0.0.1.0.0.255` · voltage L-N `1.0.32/52/72.27.0.255` · current
`1.0.31/51/71.27.0.255` · power factor per phase `1.0.33/53/73.27.0.255` ·
cumulative energy `1.0.1/2/3/4.8.0.255` (the codes that collide with Logger 1).

**Saral 305** — no Logger 2.

## v1 silently drops the Prometer 100's phase angles

v1's map knows phase angle only as `1.0.81.**7**.4/15/26.255` and
`1.0.81.**7**.40/51/62.255` (`load_profile_reader.py:327-335`, with a comment
claiming *"Correct Phase Angle OBIS: 1.0.81.7.4/15/26.255 (confirmed in both
CSVs)"*). The Prometer 100 actually captures `1.0.81.**27**.4/15/26.255` — same
quantity, same phase, **different D value** — plus `1.0.81.24.128.255`.

None of those four appear in the map. So v1 reads them off the meter every 15
minutes and throws them away; its `avg_phase_angle_*` columns stay NULL on this
model. The same is true of `1.0.16.29.0.255` and `1.0.149.4.0.255` on the Saral 305.

This matters for **Output Parity**: if v2 maps these correctly it will show numbers
v1 leaves blank. That is v2 being right, not v2 diverging — but the parity test must
be written knowing it, or a correct v2 will look like a regression.

## Also worth knowing

- **`1.0.99.N.128.255` is the scaler/unit companion** of `1.0.99.N.0.255` — the same
  object list read at attribute 3 instead of 2. That confirms v1's
  `LP_LOGGER1_SCALAR_OBIS` / `LP_LOGGER2_SCALAR_OBIS` constants. On the Prometer 100
  every `…128.255` profile answered **"Read-Write denied"** for the capture period
  while still returning its capture list, so a driver must not treat a period read
  failure as a dead profile.
- **`1.0.99.128.0.255` is a daily profile** (period 86400) carrying cumulative
  energy: 8 columns on the Saral 305, 5 on the Premier 550. Nothing in v2 reads it
  today; it is a candidate source for billing backfill (M6).
- **`1.0.99.98.132/133/134/135.255`** carry 17–21 columns of per-phase voltage at
  various E values on both the Prometer 100 and the Premier 550 — likely power-quality
  or event profiles. Unmapped, unread.
- **`1.0.99.11.129/130/134/135.255` hold 93 columns each** on both models. Nothing
  reads them and nobody has asked what they are.

## What this changes

- `SPEC.md` §3.5's "merge on `read_at`" must be corrected to v1's separate-row shape
  with a `logger_id` discriminator, and its "Logger 1 = energy / Logger 2 = V/I/PF"
  description is wrong for two of the three models.
- The load-profile table needs `logger_id` in its unique key —
  `(device_id, logger_id, read_at)`.
- Reading Logger 2 on a Prometer 100 at 300 s costs **288 rows/device/day** against
  Logger 1's 96, for three line-to-line voltages and a duplicated frequency.
  **Decided at M4c (issue #24, D17): stored anyway.** Only `freq` maps to a
  column (the three line-to-line voltages are dropped structurally, no field
  for them), but Logger 2 is read and stored regardless — it is the only
  case in this build that exercises the per-logger watermark and the
  96-vs-288-row Records case on one physical meter, both of which need real
  coverage.
- Three model-specific OBIS codes (`1.0.149.4.0.255`, `1.0.11.132.0.255`,
  `1.0.11.132.124.255`, `1.0.12.132.124.255`) are captured by meters in the field and
  mapped nowhere. **Decided at M4c (issue #24, D16): stay dropped** — same
  reasoning as `1.0.149.4.0.255` above, no screen shows any of them.
- **Field-verified 2026-08-09, fixed the same day** (`docs/meter-notes/cewe-billing-capture-objects.md`):
  all three models refuse `scaler_unit` on essentially every load-profile
  measurement column when read at its own address — the same denial pattern
  the SMW110W4 already documents for load profile. The fix is the same shape
  as SMW110W4's proven resolver: each mapped column now declares a sibling
  OBIS to borrow `scaler_unit` from (`resolve_load_profile_multiplier`,
  `acquisition/drivers/_dlms_profile.py`, renamed from `_cewe.py` at issue
  #25), and a live re-read confirmed it resolves
  real values on all three models — voltage, current and energy on Prometer
  100 and Saral 305's Logger 1, energy on Premier 550's Logger 1 and V/I on
  its Logger 2. The one column still `NULL` after the fix is Prometer 100's
  `avg_geo_pf` (total power factor) — its own address and its declared
  sibling (`1.0.13.7.0.255`) both fail to resolve; D12 still applies (no
  guessed multiplier), so it stays `NULL` rather than storing an invented
  number. See `cewe-billing-capture-objects.md`'s "Load-profile scalers"
  section for the resolved/NULL counts per model.
