# Billing has one read path — every read reads the whole buffer

Status: accepted (2026-08-09, owner decision during M6 grilling). **Implemented** — M6a
(issue #21) landed the schema (`billing_readings`, both partial unique indexes), the
`Smw110Driver.read_billing()` 43-column span read, `read_and_store_billing()` /
`billing_cycle()`, the `billing` Read now job and scheduler entry, `Delete all data`
covering both tables, the read-only `GET /api/billing` endpoint and the Billing page.
This ADR was written before the code so the issues could cite it; it now describes what
shipped.

Reverses: v1's three billing read paths and two daemon schedulers —
`cewe/cewe-worker/src/billing/docs/adr/0012` (Backfill as a separate operator action),
`0013` (Auto-Backfill scheduler plus the `devices.billing_backfilled_at` column),
`0010` (wall-clock auto-read plus `billing_settings.last_auto_run_date`) — and v2's own
`SPEC.md` §3.6, which listed *"Backfill ประวัติจากมิเตอร์ · manual read · auto-read ตามเวลา"*
as three separate capabilities because it was copying that shape.

## The shape v1 ended up with was not designed, it accreted

Read v1's billing ADRs in the order they were written and the whole thing is visible:

| ADR | What it added | Why |
|---|---|---|
| 0002 / 0004 | Read **entry 1 only** | Decided before anyone knew the buffer held history |
| 0012 | **Backfill** — read the whole buffer, on a separate path | A probe found the history was there. The ADR says it plainly: *"กลับคำ 'entry-1 only' ของ ADR 0002/0004 บางส่วน"* |
| 0013 | **Auto-Backfill** daemon + `devices.billing_backfilled_at` | So an operator would not have to press it per device |
| 0018 | Taught all of them open-vs-closed, added an **is_latest reconciler** | The three paths wrote the same flag from different places and the history filled with junk (issue #74) |

Every row after the first exists to repair the row above it. The end state is two daemon
threads, three endpoints, two columns whose only job is to remember what a previous run did,
and a reconciler whose only job is to heal races between the paths. None of that serves a
requirement. It serves ADR 0002.

And the feature at the top of the pile was never switched on: v1 ADR 0017 §3 hid the Auto-Read
control out of the UI entirely — *"ฟีเจอร์ถูกปิดชั่วคราว operator เปิดไม่ได้"* — with the column
defaulting to `false`. The scheduler v1 built, persisted state for, and wrote an ADR about has
never run at a customer.

## The fact that removes the reason

ADR 0002's "entry 1 only" is a cost argument, and the cost is not there. Every billing profile
this product will ever read is small enough to read whole:

| Fleet | `entries_in_use` | Evidence |
|---|---|---|
| Mitsubishi SMW110W4 | **13** | `docs/meter-notes/smw110w4-scan.md:234` |
| CEWE Premier 550 / Prometer 100 / Saral 305 | **3 / 5 / 13** | v1 `billing/docs/billing-history-profile-probe.md` |
| SMART TCC (Scheme 1) | **1** | v1 `billing/docs/adr/0018` §3, field probe 2026-07-24 |

A billing period is monthly. Thirteen entries is thirteen months. There is no fleet in the
plan where "read one row instead of thirteen" buys anything measurable, and there is no fleet
where reading thirteen rows is a problem.

## Decision

**One function.** `read_and_store_billing(device_id, *, locks, background, now)`, shaped like
`acquisition/load_profile.py`'s entry point — same signature idea, same lock discipline, same
two callers. It reads the profile buffer in full, classifies each row, inserts the closed
periods it does not already have, and upserts the open period into that device's single slot.

**Two callers, one difference.** Manual Read (`Read now` on the Devices page, job `billing`)
and the scheduler's job call the same function; the job passes `background=True` so a device
whose Transport Endpoint is busy is **skipped, never queued** (ADR 0006).

**One registry line, no wall clock.** The job is
`Job(name=JOB_BILLING, interval_sec=BILLING_INTERVAL_SEC, fn=billing_cycle)` in
`default_jobs()`, on a fixed daily interval. No `HH:MM`, no catch-up, no persisted last-run
date — ADR 0008 already forbids persisted scheduler state, and `jobs/scheduler.py:251-253`
promised this exact landing:

> *"Adding a job is adding one line here… M5c's retention and backup landed that way, and
> **M6's billing auto-read** and M8's sync will — no new thread, no new class, no subclass of
> anything."*

v1 needed `last_auto_run_date` to stop a restart re-reading the whole fleet. That reason is
gone: a re-read of an already-stored period is a dedup lookup that writes nothing.

**"Backfill" stops being a concept.** Not removed — dissolved. Every read is a full-buffer
read, so there is no operation left for the word to name. No `POST /backfill`, no
`billing_backfilled_at`, no Auto-Backfill daemon, no is_latest reconciler.

## Why this is safe — it removes a race v1 had to write code for

v1 ADR 0018 §4 documents a reset-window race it calls *"load-bearing"*: right after a real
meter reset, the stranded open slot's `bill_date` freezes at its pre-reset value while backfill
imports the just-closed period whose locked `bill_date` is **newer**. Reconciling on
max-`bill_date` therefore demotes the open slot and strands it into history — reproducing the
pollution the ADR was written to fix. v1 pinned the open slot as the reconcile target to avoid
it.

The race exists because v1 learns about a closed period from a *different read* than the one
that was watching it while open. Reading the whole buffer collapses that: in a single read the
newly closed period arrives as its own row, stamped by the meter, at the same moment the open
slot is refreshed to the new running period. There is nothing to reconcile, because nothing was
ever inferred.

Traced against SMW110W4's actual buffer (`smw110w4-scan.md:275-291`), month rollover reads:
entry 2 is the just-closed period with a frozen Clock → not present → inserted with the meter's
own values; entry 1 is the new running period → overwrites the slot. Correct in one pass, with
no state carried between passes.

## What replaces the reconciler

The reconciler was v1's only enforcement of *"one is_latest per device"* — v1 ADR 0012
§Consequences records that the invariant was **never enforced at the database**, and ADR 0013
§4 records the healer built on top. Deleting the healer without closing the hole would be a
downgrade, so M6 enforces it in the schema instead:

- `UNIQUE(device_id, bill_date) WHERE record_status IS NULL` — closed-period dedup
- `UNIQUE(device_id) WHERE record_status = 'open'` — at most one open slot, ever

Partial indexes, which SQLite supports and Alembic's batch mode carries. The second one is the
invariant the whole module rests on; it is now a constraint rather than a convention plus a
repair thread.

## Consequences

- **A read costs a whole-buffer transfer.** Thirteen rows against a daily job is not a
  problem, but nobody has timed it on **serial at 19200 baud** — the probe runs recorded that
  the read succeeds, never how long it took. **Still true after issue #21**: that issue's own
  scope forbids a real meter read (the two units are at the customer site and read-only), so
  the timing is still owner's milestone-exit work, not something M6a's code could measure. If
  it turns out expensive, that is when a narrowing is added, with a measurement behind it.
- **Deleted rows come back.** `Delete all data` for a device removes its billing rows, and the
  next cycle re-imports every closed period still in the meter. That makes the button a repair
  tool for values that were wrong on *our* side (a scaler fix, re-read correctly) and a no-op
  for values the meter itself reports. The confirmation text has to say so.
- **This ADR does not simplify the read *mechanism*.** SMW110W4's billing profile refuses a
  full-width `readRowsByEntry` and needs a 43-column span (`smw110w4-scan.md:246-253`), which
  the vendored `GXDLMSReader.readRowsByEntry` (`vendor/gurux/GXDLMSReader.py:400`) cannot
  express and which `CLAUDE.md`'s vendored-API invariant forbids adding. The way through is
  `GXDLMSClient.readRowsByEntry(pg, index, count, columns)` reached via the `self._client` the
  driver already holds (`acquisition/drivers/_dlms.py:255`) — proven in v1
  (`_tcp_driver_base.py:771`) and in our own `app/scripts/probe_smw110_serial.py:534`. One read
  path is a statement about **how many times we go to the meter**, not about how hard one visit
  is.

## Amendment — M4c (issue #24, 2026-08-09)

The 43-column span became a property of the driver rather than a module constant
(`Smw110Driver.BILLING_COLUMN_SPAN`, base default `None`) — M4c is the first slice with models
that need no span at all. The three CEWE models (Prometer 100, Saral 305, Premier 550) share
one billing profile OBIS (`1.0.98.2.0.255`, F4) and read it full width through
`self._reader.readRowsByEntry(pg, 1, entries_in_use)` — genuinely simpler than SMW110W4's
hand-driven span, not a second read path: it is still one call per device per read, still no
window, still every field a full-buffer transfer. The billing position map moved from
OBIS-only to `(OBIS, attribute)` keying (`acquisition/drivers/_profile.py`) because the twenty
new Demand Time / Cumulative Demand columns this issue added put a max-demand value and its own
capture time on the same OBIS at different attributes (F2) — an OBIS-only map would have
silently collapsed them. The one-read-path decision itself — every read is the whole buffer,
no window, no watermark — is untouched.
