# Billing has two read shapes but still one write path

ADR 0009 says *"billing has **one** read path — every read reads the whole buffer, so
'Backfill' dissolves as a concept"*. This ADR adds a **second, much smaller read** in front of
it, and exists so that a future reader who finds it does not delete it as a violation.

The customer's requirement is narrow: the meter cuts a billing period at, say, 00:13, our daily
job ran at 00:00, and nobody should wait a full day to see it. Detection must happen within
about fifteen minutes.

## What 0009 actually protects

0009's subject is **what gets stored and how**: one span, no partial writes, no reconciler, no
`billing_backfilled_at`, the invariant carried by two partial unique indexes. Its "one read
path" phrasing is about never having a *second way of producing rows*, because that is what
made v1's Backfill and its is-latest reconciler necessary.

**That is untouched here.** Rows are still produced by exactly one function reading the whole
buffer. What this ADR adds is a *trigger* — a read that produces no rows at all and decides
only whether the real read should run.

## The decision

**The change check rides the Load Profile cycle's existing connection.** `load_profile.py`
already connects to every device every fifteen minutes, holds the Transport Endpoint for the
walk, and disconnects (`load_profile.py:272-294`). The check happens inside that association:

1. read `captureObjects` (attr 3) and `entriesInUse` (attr 7) — both already read by
   `read_billing()` today;
2. **[corrected by issue #43 — see the amendment below]** ~~read the newest entry only —
   `readRowsByEntry(pg, 1, 1)`~~. This was wrong: read the newest **two** entries and
   classify them with the driver's own `_classify_open`, because the newest entry is the
   Open Period on every model this product reads, not a closed one;
3. **[corrected by issue #43]** ~~compare its `bill_date` against the newest `bill_date`
   stored for that `(device, meter_serial)`~~. This was also wrong: compare the newest
   **closed** row's `bill_date` against `MAX(bill_date)` stored for that `device_id` **alone**
   (`record_status IS NULL`);
4. if and only if it differs, run the existing whole-buffer read, unchanged.

`JOB_BILLING` **stays at its daily interval as a backstop**. If the check ever goes wrong —
a driver that cannot read one entry, an ordering assumption that turns out to be
model-specific — the daily full read still repairs the gap. A trigger that silently stops
triggering must not be the only thing standing between the customer and their data.

## Why not `entriesInUse`, which looks like the obvious signal

It saturates. `docs/meter-notes/smw110w4-scan.md:71` records `Entries in use = 8640 (a full
ring)` on our own hardware — once a ProfileGeneric ring is full the counter stops moving while
data keeps arriving. A billing ring holding, say, thirteen periods reaches that state after
roughly a year.

The failure mode that produces is the worst kind: **correct on a fresh install, silent
afterwards**, with nothing in the logs. `saral` already holds twelve closed periods plus one
open. Reading the newest row's `bill_date` costs one extra row and cannot saturate.

## Measured, because the first version of this decision rested on a guess

The proposal originally claimed the check would be "about thirteen times cheaper". It is not.
Measured twice against the three reachable meters, 2026-08-23, seconds:

| | connect | attr 3 | attr 7 | 1 row | all rows | entries |
|---|---|---|---|---|---|---|
| Prometer 100 | 0.17 | 0.20 | 0.08 | 1.02 | 1.74 | 10 |
| Premier 550 | 4.92 | 3.54 | 0.28 | 1.60 | 9.10 | 5 |
| Saral 305 | 0.35 | 3.11 | 0.14 | 1.17 | 14.23 | 13 |

**`captureObjects` is an irreducible floor** — every row read needs it parsed first, so it is
paid whether you fetch one row or thirteen. The real saving is 33 % / 42 % / 73 % of a full
cycle, not 13×.

The number that actually decides the design is elsewhere: **the association**. The first run
measured Premier 550's `connect` at **95.5 s** with `association aborted (ValueError) —
retrying (attempt 1/3)` in the log, against 4.92 s on the second. `MANUAL_READ_LOCK_TIMEOUT_SEC`
is 120 s, so a bad association nearly exhausts it on its own.

A separate fifteen-minute billing job would pay that cost **a second time, per meter, per
tick**. Riding the Load Profile connection pays it once. That, not the row count, is why this
ADR exists in the shape it does.

## Consequences

- **Two scheduler jobs become coupled.** The billing change check lives inside the Load Profile
  cycle, so switching Load Profile off, or changing its interval, silently changes how quickly
  billing is detected. The scheduler's own model is `[(name, interval, fn)]` — one job, one
  name — and this deliberately steps outside it. Anyone tuning `LOAD_PROFILE_INTERVAL_SEC`
  needs to know they are also tuning billing latency.
- **`BILLING_INTERVAL_SEC` keeps its daily value.** It is now a backstop rather than the primary
  path, and its comment must say so, or the next reader will "fix" the inconsistency by
  lowering it to 900 and reintroduce the second association this ADR avoids.
- **Detection latency is bounded by the Load Profile cycle, not by the billing job.** Fifteen
  minutes today; whatever that constant becomes tomorrow.
- **Marginal cost, measured**: about 12 s per tick across the three meters here, roughly 36 s
  extrapolated to nine — against roughly 90 s if the full read ran every tick. On a
  single-threaded scheduler that also runs Load Profile walks with a 60 s budget each, that
  difference is the point.
- **The Load Profile cycle's scheduler slot can now overrun `budget_sec` by a capture.** When
  the check fires, it calls `read_and_store_billing` unchanged (D6), which reaches
  `_capture_new_closed_periods` — ADR 0017's Edge-over-CDP screenshot — as its normal eager
  capture path. That capture runs outside the Transport Endpoint lock and after `_read_while_
  holding`'s own `budget_sec` accounting has already finished, so it is not counted against
  the walk's budget, but it still shares the scheduler's one thread: the LP job's slot for
  that tick does not return until the capture does. This is bounded and deliberate — once per
  newly **closed** billing period per device, roughly monthly, never once per fifteen-minute
  tick — and is exercised by `test_the_whole_buffer_read_stores_rows_and_reaches_the_eager_
  capture_path` (issue #43). No behaviour changes for it; it is recorded here because nothing
  in this ADR's original text said the two paths would ever share a scheduler slot.
- **One assumption is per-driver and must be verified, not inherited**: that entry 1 of the
  billing profile is the newest row. `read_billing()`'s docstring says rows come back newest
  first, but `smw110w4-scan.md:81` records that the SMW110W4's *load profile* orders entries
  the opposite way from the Premier 550. Ordering is a property of the profile and the model,
  so the check must read the ordering from the driver rather than assume 1 is newest.

## Amendment — issue #43 (2026-08-24): steps 2–3 above were wrong

**Status: implemented**, with two corrections to this ADR's own original text. Both were
caught before merge, by re-reading `docs/meter-notes/cewe-billing-capture-objects.md` and
`CONTEXT.md`'s own Open Period entry against what step 2 above actually proposed, and by
tracing what the two driver read paths store when the meter-serial read fails after the
buffer was already read.

**Step 2 was wrong: the newest *entry* is the Open Period, not a candidate for "the newest
bill_date".** `docs/meter-notes/cewe-billing-capture-objects.md:19-23` — *"entry 1 = newest …
the row at entry 1 has the highest `bill_date` and `is_open=True` on every model"*.
`CONTEXT.md`'s Open Period entry — *"its Bill Date is the meter's live clock and advances on
every read"*. Reading entry 1 only and comparing its `bill_date` would therefore have fired
the whole-buffer read on **every single tick**, forever — and it would have looked completely
correct against any static test fixture, because a fixture that never re-reads never exposes
that the value it is comparing against moves on its own. The corrected signal is the newest
row that classifies **closed** — reading the newest two entries and running them through the
driver's own `_classify_open` (never a fresh guess), so the check answers exactly what a full
`read_billing()` would have called "the newest closed row" had it stopped after two entries.

**Step 3 was wrong: `(device, meter_serial)` is the wrong key.** Both `_dlms_profile.py` and
`smw110.py` store `meter_serial=None` on a row when the serial register read fails *after*
the billing buffer was already read (both driver files, the `read_meter_serial()` fallback
around `read_billing()`'s last few lines) — a real, recorded failure mode, not a hypothetical
one. A comparison keyed on `(device, meter_serial)` would exclude those legitimately stored
rows from the lookup, `MAX(bill_date)` would come back `NULL` for a device that has one, and
the check would conclude "nothing stored" and fire a full read on every cycle — silently,
and only on devices that happened to hit that one serial-read race. The corrected key is
`device_id` **alone**: ADR 0005's `_reject_changed_serial` (`api/devices.py`) already refuses
any Update whose probed serial differs from the stored one, unconditionally, so a device is
already pinned to exactly one meter without needing the serial in this comparison too.

What shipped, unchanged from this ADR's own reasoning otherwise: the check still rides the
Load Profile cycle's own connection (never a second association per tick), `entriesInUse`
is still never the signal, `BILLING_INTERVAL_SEC` still stays daily as the backstop, and the
comparison is `!=` rather than `>` (a buffer that appears to move backwards — a wrapped ring,
a re-provisioned meter — is still worth re-reading, and the whole-buffer write path is
idempotent). `MeterDriver.billing_newest_closed_bill_date()` and
`MeterDriver.BILLING_NEWEST_ENTRY_FIRST` (base default `True` — every billing implementation
shipped today reads newest-first, including the SMW110W4, whose *load profile* is the
opposite) landed on `base.py`, `_dlms_profile.py` and `smw110.py`; `billing_change_check()`
landed on `billing.py`; the wiring landed in `load_profile.py::_read_while_holding`, gated to
the background path only and executed strictly after the Transport Endpoint lock block has
exited — `PriorityEndpointLock` is not reentrant, so firing the whole-buffer read from inside
that lock would have made `read_and_store_billing`'s own `background=True` acquisition see
the endpoint already held and return `skipped=True` silently, the one failure mode that would
have passed every fake-lock unit test while never triggering in production.
