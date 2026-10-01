# 0027. The Database Destination's load profile is one merged row per interval

**Status:** Accepted · 2026-09-20 · owner decision ("ทาง ก"), at the customer's request: a meter
that logs on Logger 1 and Logger 2 must arrive in their database as **one row per interval**,
because the table they feed from it (`meter.logger`, written by the previous program) holds one
row per interval.

**Amends:** SPEC §3.10 and ADR 0021's Consequences, which key the destination's
`load_profile_readings` on `(meter_serial, logger_id, read_at)` with a watermark per
`(meter_serial, logger_id)`. **Does not touch** our own store: `load_profile_readings` in SQLite
still holds one row per `(device, logger, read_at)`, and
`docs/meter-notes/load-profile-capture-objects.md` is still why.

## Context

The meters say the two Loggers cannot be *stored* merged: a Prometer 100 logs Logger 2 every
300 s against Logger 1's 900 s, and both capture frequency; a Premier 550 shares a period but
captures different quantities. That is why the store keeps a `logger_id`.

But the product already *shows* them merged, in two places, under one rule
(`db/load_profile_query.py::merged_rows_select`, owner ruling 2026-08-11): **Logger 1 is the
spine, Logger 2 is outer-joined on an exact `read_at`, every measurement is
`COALESCE(logger1, logger2)`**, and an interval the meter marked all-invalid is left out. The
Load Profile page renders it and the Load Profile CSV exports it. The Database Destination was
the one output still shaped like the store.

## Decision

The destination's `load_profile_readings` holds the **same merged row** the page and the CSV
hold.

- **No `logger_id` column.** Unique key `(meter_serial, read_at)`, which also serves the
  watermark's `MAX(read_at)` per serial — so the secondary `(meter_serial, read_at)` index the
  per-logger shape carried would be an exact duplicate and is gone. One index is added:
  `ix_load_profile_readings_read_at`, for the purge, whose `DELETE … WHERE read_at < :cutoff`
  names no serial and so could never use an index that leads with one (true of the old
  secondary index too — every purge was a full scan; code review, 2026-09-20). Measured on
  MariaDB 10.4.32, 172,800 rows (20 meters × 90 days), the steady-state statement with nothing
  to delete: `range` on the new index, **0.7 ms**; without it `ALL` over every row, **137 ms**
  — per cycle, per batch.
- **Rows come from `merged_rows_select`**, never from a second implementation of the rule. Every
  measurement column of the destination is one of `MERGED_COLUMNS`; `source`, `interval_sec` and
  `created_at` are copied from the Logger 1 row. `test_dataout_schema.py` pins that split as an
  exact set, so a measurement column added to the model cannot reach the destination as a
  Logger-1-only value by accident.
- **The watermark is per `meter_serial`.** A lagging Logger 2 is handled by the **cap**, not by
  a second watermark: a sent row never changes (ADR 0020), so a Logger 1 row sent ahead of its
  Logger 2 partner would stay half-empty for good. Logger 1 rows are therefore held until Logger
  2 has caught up — the Load Profile CSV's own rule (F5), which moved from
  `export/csv_export.py::_compute_cap` to `db/load_profile_query.py::merged_rows_cap` so both
  writers share it (`dataout/` may not import `export/`, ADR 0021). Whether a meter *has* a
  Logger 2 comes from its driver, so a one-logger model is never held; a device whose driver
  cannot be built is still sent, and its stored rows answer instead.
- **The 24 h escape is not the CSV's** (`never_rewritten=True`; code review, 2026-09-20). The
  load-profile walk reads Logger 1 to the present before Logger 2 gets more than one chunk per
  visit (`_walk_every_logger`: one shared 60 s budget, Logger 1 first), so after any long
  backfill Logger 2 is *days* behind while still arriving, and the CSV's plain rule — release
  everything once Logger 2 is more than 24 h behind — would send every Logger 1 row half-empty.
  The CSV survives that because its daily whole-window rewrite (ADR 0023) repairs the rows;
  nothing repairs a destination row. So here the escape fires only once Logger 2 has **stored
  nothing for 24 h**, read off its `MAX(created_at)` (first-store time — the upsert never
  touches it), and until then rows are released only up to Logger 2's own frontier. Stateless,
  as ADR 0008 requires. The CSV's behaviour is unchanged and pinned by a test.
- **An existing per-logger table is refused, not reshaped.** The load-profile step raises when
  `load_profile_readings` still has a `logger_id` column
  (`dataout/schema.py::per_logger_load_profile_error`, on `reconcile`'s own answer from the same
  cycle — no second `information_schema` query), and the message names the way out:
  `DROP TABLE load_profile_readings;` — `reconcile` recreates it and the next cycle re-sends the
  whole window. Reshaping a unique key on a table that holds rows is not ours to do in someone
  else's database (the rule `reconcile` already lives by), and `reconcile` itself leaves such a
  table exactly as it found it — no column added, no index created, its key not judged.

## What it costs

- **Logger 2 rows with no Logger 1 partner are not sent.** On a Prometer 100 that is two in
  three Logger 2 rows — the 5-minute line-to-line voltages between quarter hours. They remain in
  our store for 90 days and on nothing we send. The owner accepted this; it is exactly what the
  page and the CSV already do.
- **A Logger 2 value that arrives after the 24 h escape released its row never reaches the
  destination**, because `ON DUPLICATE KEY UPDATE` still rewrites nothing but `source`. The CSV
  behaves identically.
- **A two-Logger meter's rows reach the destination one Logger-2 read later** than they used to.
- **A two-Logger meter whose Logger 2 has never stored a row is a day behind, permanently.** With
  no Logger 2 row there is no frontier and no `created_at` to read, so the cap is
  `l1_max − 24 h` on every cycle — the CSV's rule, unchanged. Nothing on the Database page says
  so: the cycle succeeds. Accepted rather than fixed (code review, 2026-09-20) — the way out is
  to make Logger 2 readable, and `docs/issues/024` is the known way it is not. **Bounded to two
  models**: only `prometer100` and `premier550` declare a Logger 2
  (`load_profile_loggers()`, checked across all nine drivers), and both were measured to have
  one; the other seven can never be held.
- **Every site upgrading from 0.7.5 or earlier must drop the table once.** Until then every
  cycle ends with the refusal as its error on the Database page and nothing is written to that
  table. **Billing is still brought current** — the refusal is raised by the load-profile step,
  after the billing replace, and not at all on a site with no `load_profile` licence. The first
  version of this ADR stopped the whole cycle from inside `reconcile`, "loud on purpose"; the
  review's point stood — the error on the page is the loudness, and freezing a table the refusal
  has nothing to do with added none.

## How it was proven (2026-09-21)

`fake_meter` is autouse in the suite and the MariaDB tests are opt-in, so the gate proves neither
half of this. `app/scripts/probe_dbdest_merge_backfill.py` drives the shipped read path and the
shipped sync alternately, the way the scheduler does, against a real two-Logger meter and a real
MariaDB, from a throw-away data directory. Lab Prometer 100 (`203.170.151.152:4059`, read-only),
MariaDB 10.4.32, a full 90-day backfill:

| round | Logger 1 reaches | Logger 2 reaches | destination reaches | rows there |
|---|---|---|---|---|
| 1 | 07-15 | 06-24 | 06-24 | 96 |
| 4 | 09-20 | 06-27 | 06-27 | 384 |
| 5 | 09-21 (the present) | 07-26 | 07-26 | 3,102 |
| 6 | 09-21 | 08-26 | 08-26 | 6,048 |
| 7 | 09-21 | 09-21 | 09-21 | 8,545 |

Rounds 4–6 are the review's scenario on real hardware: Logger 1 at the present, Logger 2 **86,
57 and 26 days behind** while still arriving. The CSV's plain escape would have released every
row in round 4. The hold was broken in **0 rounds**. At the end the destination held **8,545 rows
against 8,545** from `merged_rows_select` inside the Mirror Window, with `volt_l1_l2` — a column
only Logger 2 captures — **NULL in 0** of them on both sides. (8,641 Logger 1 rows were read; the
other 96 are intervals the meter marked all-invalid, which the merge leaves out everywhere.)

The probe's own first run said FAIL, by one row, and the row was the instrument's: `06-23 12:15`,
eight minutes behind the Mirror Window's cutoff by the time the run ended — purged at the
destination on the next cycle while our own daily retention had not run, exactly ADR 0020's "the
same length but not the same instant". The comparison is now bounded to the window on both sides.

## Alternatives rejected

- **A second, merged table beside the per-logger one** — recommended in the grill, and the
  option that loses nothing. The owner chose one table: the customer asked for one shape, and
  two tables double the writes and the Mirror Window's purge for data nobody asked to keep.
- **A view in the customer's database** — no code, but an `AFTER INSERT` trigger into their
  `logger` table cannot hang off a view, and Logger 1 and Logger 2 rows arrive in separate
  statements, so a trigger on the per-logger table would fire before its partner exists.
- **Reshaping the existing table in place** — `ALTER TABLE … DROP COLUMN logger_id` plus a new
  unique key fails outright on any table holding a two-Logger meter (duplicate `read_at`), and
  succeeding would silently keep whichever Logger's row the server met first.
