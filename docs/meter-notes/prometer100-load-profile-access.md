# CEWE Prometer 100 — how its load profile answers, and refuses

Measured **read-only** on 2026-09-20 against three real meters, after a customer site (TC)
stored no load profile at all. Every line below is an executed read, not a datasheet claim.
Tools: `app/scripts/probe_lp_buffer.py` (also built as the carry-to-site
`app/dist/probe_lp_buffer.exe`, `app/packaging/probe_lp_buffer.spec`) and ad-hoc range reads
through the shipped driver.

| Meter | Driver | Where |
|---|---|---|
| Prometer 100 `WP079074` | `prometer100` (WRAPPER) | lab, `203.170.151.152:4059` |
| Prometer 100 `WP089573` | **`premier550` (HDLC)** — see the last section | site TC, `10.100.91.1:4059` |
| Premier 550 `SS18197374` | `premier550` (HDLC) | lab, `49.229.159.44:50001` |

## What the model does

1. **Entry access to the load profile is refused — always.**
   `readRowsByEntry(pg, 1, 1)`, the newest entry, and a one-column selection all answer
   `GXDLMSException: Access Error : Other Reason.` on both Loggers, on the lab unit and the
   site unit alike. Attributes 3 (capture objects), 4 (capture period), 7 (entries in use) and
   8 (capacity) read normally. The Premier 550 and the Saral 305 answer entry 1.
2. **A range holding no entries is refused, not answered with `[]`.**
   A 24 h window in 2020 and one in 2030 both answer
   `Access Error : Data Block Unavailable.` The Premier 550 answers `0 row(s)` to the same two
   requests.
3. **A range that overlaps the buffer is answered even when it starts before the oldest row.**
   Site unit, 44 h of buffer, a 48 h window: 176 of 176 rows on Logger 1, 528 of 528 on
   Logger 2.
4. **Range rows come back newest first.** Lab unit, Logger 1: first returned `22:45`, last
   returned `17:15` (UTC, same day). Entry order is a property of the profile
   (`.claude/skills/gurux-dlms/patterns.md`); the shipped read path does not depend on it, it
   upserts on `(device, logger, read_at)`.
5. **A one-column selection is refused on the Premier 550 too** (`Data Block Unavailable`)
   while a full-width row is answered — so a refused narrow read proves nothing about width.

## What that did to the product

`load_profile._backfill_start` clamps a first backfill to the meter's oldest row, because the
walk keeps no memory between cycles (ADR 0008) and a 60 s budget cannot cross 88 empty 24 h
chunks. The clamp asked for **entry 1** — which this model refuses (1) — so it answered `None`,
the walk kept its 90-day window, the first chunk held no entries, and (2) turned "no entries"
into a failed read. Every cycle, forever: `load_profile_readings` stayed at 0 rows while
billing, the Meter Serial and the liveness tick all worked.

The lab unit never showed it: its buffer is ~100 days, longer than the 90-day window, so its
first chunk always holds rows.

**Fixed 2026-09-20**: `DlmsProfileDriver.load_profile_oldest_reading` falls back to
`now − (entries_in_use + 1) × capture_period` when entry 1 is refused and the attributes
answer. Measured against the lab unit's true oldest row (found by range):

| Logger | entries × period | estimate vs true oldest row |
|---|---|---|
| 1 | 9585 × 900 s (~100 d) | **20 min early** |
| 2 | 32789 × 300 s (~114 d) | **10 min early** |

Early is the safe side (3). The estimate is *late* by the total downtime on a meter that
stopped logging for a while — the lab Saral 305 would be 485 days late (12273 entries spread
over ~1.7 years) — which is why it is a fallback only: that Saral answers entry 1.

## Still open

- **A gap inside the buffer stalls the walk.** Because of (2), a 24 h chunk with no entries —
  a meter switched off for two days — is a *failed* chunk, the walk stops there, and the
  watermark can never cross it. Not fixed by the change above. `docs/issues/024`.
- **The site unit is a Prometer 100 running under the `premier550` driver.** Its capture
  objects are the Prometer 100's (Logger 1: 900 s / 25 columns, Logger 2: 300 s / 7; the
  Premier 550 is 7 / 14 at 900 s), its serial is `WP…` like every Prometer 100 we hold, and
  it behaves as (1) and (2) say — but it only associates over **HDLC**, which is the
  `premier550` driver's framing; `prometer100` speaks WRAPPER and gets `Invalid connection`.
  Framing is a property of the install (a serial-to-TCP converter), not of the model, and one
  driver class currently fixes both. Under `premier550` the column map matches **5 of 25**
  Logger 1 columns and **0 of 7** on Logger 2 (`prometer100`: 20 and 3) — which is what the
  customer reported as "voltage and current do not arrive". Billing is unaffected: every CEWE
  driver inherits one set of billing declarations from `DlmsProfileDriver`.
  **Resolved the same day** (`docs/issues/025`): framing became a field of the `net` transport and
  the Prometer 100 driver declares both. Measured: that driver with `framing="hdlc"` associates
  with the lab's HDLC meter (`49.229.159.44:50001`) and is refused on `wrapper`. Not yet measured:
  the site's own unit under it — `probe_lp_buffer.exe --model prometer100 --framing hdlc`.
