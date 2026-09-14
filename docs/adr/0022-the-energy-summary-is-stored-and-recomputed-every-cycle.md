# The Energy Summary is stored, and recomputed over the whole window every cycle

Status: accepted (2026-09-14, owner decision during the M14 grill). **Supersedes ADR 0012.**
**The stored table and the recompute landed with M14 ticket 01**
(`.scratch/central-push/issues/01-energy-summary-is-stored-and-recomputed.md`): migration 0017's
`energy_summary_days`, the `energy_summary_recompute` scheduler job
(`db/energy_summary_store.py`), and `GET /api/energy/summary` reading the table instead of
aggregating live. **The Energy Export File moved onto the stored table with M14 ticket 04
(`.scratch/central-push/issues/04-energy-and-billing-files-are-rewritten-every-cycle.md`)**: both
`export/energy_csv.py::export_device_energy` and its on-demand **Save to file**
(`export_energy_range`) now read `energy_summary_days` through
`db/energy_summary_store.py::stored_energy_summary_rows`, never the live `energy_summary_rows()`
aggregation — see ADR 0023 below for the file's own every-cycle rewrite. **The recalculation
notice landed with the same ticket**: the Holidays page shows a fixed "Energy Summary will be
recalculated within 15 minutes" notice on every Holiday change
(`web/src/pages/Holidays.tsx::notifyEnergySummaryWillRecompute`), replacing M13 issue 03's
per-change "these energy files may be stale" computation — `HolidayMutationOut` dropped
`affected_date`/`energy_files_written_past`, and `db/energy_query.py::most_recent_occurrence`/
`energy_files_written_past` are gone. **The Holiday Change log itself — a `holiday_changes` table
recording who/when/which day for all five mutation paths — is still not implemented**: that is a
separate ticket, not ticket 04, which only had to retire the fields ticket 04's own column drop
(`devices.energy_exported_through`, migration 0018) made unreadable.

ADR 0012 made the Energy Summary a live derivation with no table, deliberately not reproducible,
so that a Holiday entered late would move the numbers toward the truth. That rested on one
assumption the next requirement broke: that nothing outside the page needs the numbers to be
*rows*. The central push (ADR 0024) sends only what it can track, and it tracks rows by
`updated_at`. A derivation has no rows to track.

## The decision

- **One stored row per meter per local calendar day**, carrying the eight Time-of-Use buckets
  (Peak, Off-Peak, Holiday and Total, import and export). The page, the Energy Export File and
  the central push all read that table, so there is **one truth** and the three cannot disagree.
- **Every fifteen-minute cycle recomputes the whole `RETENTION_DAYS` window for every meter**
  from `load_profile_readings`. A Holiday change and a late Interval Reading therefore reach every
  stored day within one cycle, by the same mechanism, with no trigger for either.
- **`updated_at` moves only when a row's values actually change.** Recomputing everything every
  cycle must not look like everything changed, or the push would resend the whole window every
  fifteen minutes.
- **The table keeps 90 days**, dropped by the retention job with the readings it comes from.
- **Every Holiday change is recorded** — who, when, which day, add/edit/delete — through all five
  ways a Holiday moves: add, edit, delete, CSV import, Import from meter. Kept 90 days in its own
  small table, because that is how long the numbers it explains exist, and also written to the App
  Log. The Holidays page says the summary **will be recalculated within fifteen minutes**, which
  replaces M13 issue 03's "these energy files may be stale" warning — nothing can be stale by more
  than one cycle any more.

## Why every cycle, and why the whole window

Measured 2026-09-14 on a copy of the install database (4 meters, 96,017 load-profile rows, a full
90-day span), through the shipped `energy_summary_rows()`: **about 0.07 s per meter** for the
whole window, and essentially unchanged between 0 and 37 Holidays. The largest site the owner has
seen has under 20 meters, so a cycle costs roughly 1.4 s on the scheduler thread.

At that price, the owner chose the design with nothing to get wrong over the cheaper ones:

| Rejected | Why |
|---|---|
| Keep 0012 — derive live, store nothing | The push has no rows to track, and the page, file and server would each compute their own answer |
| Freeze each row when first written; apply Holiday changes only from the next row | The owner's first answer. Reversed the same day: the customer wants past days recalculated. It would also have frozen a data gap forever when a meter caught up late |
| Recompute today and yesterday each cycle, the whole window daily, and a changed Holiday's day at once | About ten times cheaper, and correct for a late reading only within a day. Rejected by the owner as more moving parts than the saving is worth |
| Mark "dirty" days in the load-profile write path | Most precise. Touches the meter-reading path and persists job state, which ADR 0008 forbids |

## What survives from ADR 0012

- **The peak window stays a constant.** The Holiday table remains the only knob that moves past
  numbers, and it still moves them toward the truth.
- **No cache-invalidation problem appears.** 0012 rejected "materialize and recompute on holiday
  change" because an invalidation that is slightly wrong produces a confidently stale page. This
  design invalidates nothing: it recomputes everything, every time.

## Consequences

- **The summary is not reproducible past 90 days on the machine.** The rows go when the readings
  they come from go. The central server keeps them, frozen at the value last pushed (ADR 0024).
- **ADR 0012's M13 amendment is void**: a row in the Energy Export File is no longer "a snapshot
  that drifts", because the file is rewritten from this table every cycle (ADR 0023).
- Two tables are added (this one and the Holiday Change log) while `sync_state` is dropped
  (ADR 0024), taking the schema from 10 tables to 12.
