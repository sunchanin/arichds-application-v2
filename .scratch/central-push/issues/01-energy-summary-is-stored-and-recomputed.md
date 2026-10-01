# 01: The Energy Summary is stored, and recomputed over the whole window every cycle

**What to build:** The Energy Summary page shows exactly the numbers it shows today, but they
now come from stored rows — one per meter per local calendar day — that the program recomputes
over the last 90 days on every load-profile cycle. A Holiday entered for a past day, or readings
a meter sends late, reach every affected day within one cycle, with no trigger for either.
Nothing else changes for the user in this ticket: the Energy Export File and **Save to file**
keep working as they do today. Decision record: ADR 0022; spec: `.scratch/central-push/spec.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] A migration creates `energy_summary_days`: device, local calendar date (a plain date), the
      eight buckets (Peak, Off-Peak, Holiday, Total × import, export active energy) and
      `updated_at` (UTC). Unique on device plus local date; rows go when their device goes
- [ ] A recompute job is registered **immediately after** the load-profile job, at the same
      interval. For every device it computes `local_today − (RETENTION_DAYS − 1)` through
      `local_today` with the **existing** Time-of-Use aggregation, unchanged — Logger 1 only,
      the constant peak window, weekends and both Holiday kinds as Holiday, all-invalid intervals
      excluded — and upserts each day
- [ ] `GET /api/energy/summary` reads the table. Its response shape and its 31-day request bound
      are unchanged
- [ ] **Stored, not live**: after a recompute, deleting the underlying load-profile rows leaves
      the API's response unchanged
- [ ] **Output Parity**: on seeded readings covering a weekend, a public Holiday, an annual
      Holiday, both sides of the peak boundary and an all-invalid interval, the stored rows equal
      what the current live aggregation returns, day by day and bucket by bucket
- [ ] **Retroactive**: a Holiday added through the API for a past day moves that day's energy
      into the Holiday bucket after one recompute
- [ ] **Late readings**: rows inserted for a past day after a recompute are counted after the
      next one
- [ ] **Quiet recompute**: a second recompute over unchanged data leaves every `updated_at`
      untouched; changing one day's data moves only that day's `updated_at`
- [ ] A day with no readings produces no row
- [ ] Retention deletes stored days older than `RETENTION_DAYS`
- [ ] Every test above is mutation-probed: reverting the behaviour it names turns it red
- [ ] `CLAUDE.md`'s digest for ADR 0022 records what landed (the stored table and the recompute),
      and stops saying "not yet implemented" for that part
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/`
- [ ] **Output Parity vs v1**: held by the parity criterion above — the live aggregation is the
      one already checked against v1
- [ ] No real-meter read is required: no driver changes
