# The load-profile watermark is the data, not a job record — v2 has no read-job table

Status: accepted (2026-08-07, owner decision during M5 grilling). **Fully implemented**: the
watermark, the oldest-first 24 h walk and the synchronous Manual Read landed with issue #15
(M5a-1) in `acquisition/load_profile.py`, and the background scheduler that calls it on a
cadence landed with issue #16 (M5a-2) in `jobs/scheduler.py` — one thread, a registry of
`(name, interval, fn)`, with `load_profile_cycle` as its first entry. **The read interface
became genuinely per-logger at M4c** (issue #24): `MeterDriver.read_load_profile` now takes a
`logger_id` and `load_profile_loggers()` names which ones a model has, so the walk below
resumes each logger from its own watermark inside one connection — this *implements* the
Decision below (which already said "for that device and logger"), rather than reversing it;
what changed is that the driver interface issue #15 shipped with could not yet ask a meter for
one logger at a time.

**Still no job table, and no persisted scheduler state of any kind.** The scheduler's due
times live in memory and are lost on restart, deliberately: after a restart every job simply
runs on its first pass, and the load-profile walk resumes from each logger's own
`MAX(read_at)` over `load_profile_readings` — the rows themselves, exactly as below. There is
no `last_run_at`, no `read_end`, and nothing a future reader could mistake for a watermark.

Reverses: v1's `load_profile_reads` job table, and v2's own `SPEC.md` §4 data model, which
listed `interval_read_jobs` among thirteen tables. **The count is now twelve.**

## What the load-profile job has to know

A load-profile read is incremental. The meter holds a ring of 8640 entries and the job's only
real question each cycle is *where did we get to last time* — everything after that watermark
is new, everything before it is already stored. Get the watermark wrong in the optimistic
direction and the rows in the gap are never fetched, because the next cycle starts after the
gap too. Nothing raises an error. The data is simply not there, and nobody finds out until a
customer asks why a Tuesday is missing.

So the watermark is the single most load-bearing value in the module, and the only question
worth an ADR is where it comes from.

## v1 answered this twice, and its second answer is the one worth copying

v1 has a job table. `load_profile_scheduler.py` inserts a row per read cycle, moves it
`queued → running`, records the nominal window it asked for, and updates it on completion.
A job row therefore *looks* like a watermark: it says "this device was read up to time X".

It is not one, and v1 records why in the docstring of `calculate_read_window`
(`cewe-worker/src/worker/load_profile_scheduler.py:158-166`):

> *"Sourcing `read_from` from the actual `logger_readings` table (rather than
> `load_profile_reads.read_end`) grounds the scheduler in the data it has truly ingested. This
> protects against cases where a successful job was recorded but its coverage is narrower than
> the job's nominal end-time (e.g. after the ADR-8 meter-local timezone fix was deployed,
> pre-fix `read_end` values over-reported coverage by 7 h)."*

That is not a hypothetical. A timezone bug shifted what the meter actually returned while the
job kept recording the window it had *asked* for, so every completed job over-reported its own
coverage by seven hours, the watermark advanced past data that was never stored, and the gap
became permanent. The seven hours is the same `UTC+7` offset the SMW110W4 probes confirmed on
both live units on 2026-08-07 — this is the meter-local clock, and it will be back.

v1's fix was to stop trusting the job record and read `MAX(read_at)` off the data table
instead. It kept the table for its other duties. **v2 takes the fix and declines the table.**

## Decision

- **The watermark is `MAX(read_at)` over `load_profile_readings` for that device and logger.**
  It is derived from stored rows, so it cannot claim coverage that does not exist. There is no
  second place that answers "where did we get to", and therefore no way for two answers to
  disagree.
- **There is no read-job table.** `interval_read_jobs` is removed from the data model before it
  is built.
- **A manual Read now is synchronous.** It takes the Transport Endpoint lock as a Manual Read
  and returns to the caller who is waiting on it, exactly like Test connection and the
  create-time probe. ADR 0006 already gives it priority over background ticks, so a queue would
  add a state machine to solve a problem that is already solved by a lock.
- **Backfill runs oldest-first, and a newly added meter therefore shows its oldest data first.**
  This falls straight out of the rule above and is not negotiable while that rule stands. The
  job splits the window from the watermark to now into 24 h chunks (v1's `LP_READ_CHUNK_HOURS`)
  and writes each one, so a link that drops keeps everything already fetched and the next cycle
  resumes from the data — no chunk bookkeeping, which is the payoff for deriving the watermark
  from rows. Newest-first is the tempting alternative and it is **wrong**: fetching today first
  moves `MAX(read_at)` to today, the next cycle starts from today, and the 90 days behind it are
  never read. That is the exact permanent gap this ADR exists to prevent, arrived at from the
  other direction. Owner's call, 2026-08-07: the install-time cost — an operator who adds a
  meter sees three-month-old data before today's — is accepted rather than reintroducing a
  second marker to work around it.

## What this costs, accepted deliberately

There is **no history of what was read and when**, and no record of a failed read cycle beyond
the log. On a site that goes quiet, "did the job run and find nothing, or did it not run" is a
log question rather than a table query.

That is the trade. It is accepted because the alternative is worse in a specific way: a table
holding `read_end` next to the real watermark is a loaded gun. The next person to add a feature
sees a column that appears to say how far each device was read, uses it, and reproduces v1's
gap — the fix for which is already written down in v1 and was still not enough to stop the
table existing there.

**If read history is wanted later, add it as history and nothing else.** No `read_end`, no
column any scheduler could mistake for a watermark, no "resume from the last job" path. The
watermark stays derived from the data. That constraint is the entire point of this ADR, and a
future change that quietly relaxes it should be treated as reversing this decision, not as
extending it.

## Checked against M5c's retention job (issue #19, 2026-08-07)

Retention deletes rows out of `load_profile_readings`, which is where the watermark comes from,
so it was checked against this ADR before shipping rather than after. **It cannot move a
watermark**, and that is arithmetic rather than luck: retention deletes the *oldest* rows (those
older than 90 days by `read_at`) while each logger's watermark is its own `MAX(read_at)` — the
*newest* row for that logger (M4c, issue #24 — genuinely per-logger since the driver interface
grew a `logger_id`; `_through`, shown to the operator, is the `MIN` **across** those per-logger
watermarks, which is a display rollup, not the read watermark itself). The two ends of the
table never meet except in one case, and that case is already correct: a device offline past
the cutoff loses every row it had, the per-logger `GROUP BY` produces no groups for it, and
`load_profile.py` backfills that logger from `LOAD_PROFILE_BACKFILL_DAYS` back when the device
returns. A fresh 90-day backfill is the right answer there, and `tests/test_retention.py`
asserts it through the real read path.

Nothing was reversed and nothing was added: retention records nowhere that it ran, and the
scheduler still holds its due times in memory only. The one INFO line per purge is the entire
history, which is this ADR's cost paid a second time, deliberately.

## Alternatives considered

**Keep v1's table as-is.** Closest to Output Parity, and Output Parity is about numbers rather
than internals — `CONTEXT.md` says so explicitly. It buys read history at the cost of shipping
the exact structure that caused v1's gap, in a module where the failure is silent.

**Log manual reads into `device_events` instead.** No new table, and the table already exists.
Rejected on vocabulary: `CONTEXT.md` defines a Device Event as *"one row recorded when
something changes"* and explicitly not a per-tick heartbeat. A read cycle that found nothing new
changed nothing, so writing one would either be a lie or would force the glossary to widen —
and the glossary is the thing keeping this codebase's terms honest.
