# The Poller's tick proves liveness, not data — v2 has no live-value display

Status: accepted (2026-08-05, owner decision after grilling). **Not yet implemented.** It lands
in two places: **issue #6** retires the Monitor page and the `/readings/latest` endpoint, then
**issue #8** stops the writing, changes what the tick reads, and renames the table. Issue #5 is
deliberately untouched by it — the Poller keeps behaving exactly as it does today until #6 has
removed the last reader, so no intermediate state leaves the product without a working screen.
Until #8 lands, the Poller still reads the instantaneous set and writes a row per tick.

Reverses: v2's own M1 decision in `SPEC.md` §3.1 — both the "หน้า monitor" and the practice of
storing an instantaneous reading every 60 seconds.

## Where the Monitor page came from

Nobody asked for it. v1 has fourteen pages — ApiConfig, AppLog, BatteryStatus, Billing,
DatabaseSettings, Devices, EnergySummary, ExportFormat, Holidays, Instantaneous, LoadProfile,
Login, SpecialDays, UserManagement — and none of them is a Monitor. The word appears exactly once
in this repository's own planning documents, in `SPEC.md` §3.1, where it is introduced as part of
M1's walking skeleton and justified in the same sentence as *"พิสูจน์ chain เต็มเส้น"* — prove the
chain end to end. `docs/REMAKE-PLAN.md` never mentions it at all, and SPEC §3.7's page accounting
("14 v1 pages → 12 owned in M2–M7") does not count it.

It was scaffolding with a user interface, and it kept standing because nothing ever asked it to
justify itself.

## The consequence nobody had traced

The Monitor page is the **only** consumer of instantaneous data — verified across the whole
repository: `GET /api/devices/{id}/readings/latest` is called from `web/src/pages/Monitor.tsx:60`
and from nowhere else, in either the backend or the frontend.

Meanwhile the M3 grill (2026-08-05) redefined the "Instantaneous" page as a data-coverage grid —
because that is what v1's page of that name actually was — and moved it to M5. That quietly left
v2 with **no product page that displays live electrical values at all**, while the scaffold that
displayed them was still on screen. The loss was invisible precisely because the scaffold was
still there.

So the question was never actually asked. Asked now, the answer is **no**: v2 does not display
live values. v1 did not, v1's outputs are the confirmed baseline (Output Parity, CONTEXT.md), and
no one has requested it.

That answer collapses the rest.

## Decision

1. **No live-value display.** Monitor retires in issue #6, together with
   `GET /api/devices/{id}/readings/latest` and `api.latestReading`. Not before: it is currently
   the only page that can add a meter, and removing it earlier would leave the product with no way
   to configure one.

2. **The tick reads the Meter Serial and discards it.** It uses `read_meter_serial()` — the same
   driver seam the Probe uses (ADR 0005). One register, one code path, and it proves what "Online"
   actually claims: the association succeeded **and** a real read came back. Merely connecting
   would not; a meter that accepts an association but cannot serve a register would report Online
   while being useless.

3. **Nothing instantaneous is persisted.** `store_reading()` and `INTERVAL_LABEL_INSTANTANEOUS`
   go. `interval_readings` holds only intervals **the meter itself recorded**: 15-minute load
   profile (M5) and the Modbus cadences (M4b).

4. **No cache.** An earlier draft of this ADR proposed an in-process latest-reading cache so the
   Monitor page would still have values to show. With no page to show them, the cache has no
   reason to exist. What issue #5 needs from a tick is its **outcome**, not its payload — and #4 already gave it that.

5. **The migration that lands this deletes the existing `interval='60s'` rows.** They are real
   readings, but nothing will ever read them, and leaving them means two kinds of row live in one
   table forever with every future reader having to know which is which.

## What stays, and why

- **The 60-second cadence.** ADR 0004 deleted v1's separate health-check loop on the grounds that
  the Poller already talks to every meter every minute. That tick is now the *only* source of
  device status. This ADR removes what the tick stores, never the tick.
- **`volt_*`, `current_*`, `freq` on `interval_readings`.** SPEC §3.5's Logger 2 (Premier 550)
  records V/I/PF/freq **as load profile** — meter-recorded intervals, which is exactly what the
  table is for.
- **`MeterDriver.read_instantaneous()`, for now.** Issue #4 is landing an interface change
  alongside it; cutting it in the same breath would collide. M5 decides its fate once the
  load-profile read methods exist and it is clear whether anything still calls it.

## Consequences

- **v2 ships with no live-values screen.** If a customer asks for one later it is a new feature
  with its own storage decision — not a reason to keep this one.
- **`interval_readings` is empty from M3 until M5.** Accepted: load profile arrives at M5, and the
  day-5 demo runs Devices → Load Profile → Billing.
- **`TickOutcome.STORED`** (issue #4) becomes a lie the moment nothing is stored. Rename it in the
  same change; do not leave an enum describing behaviour the code no longer has.
- Removing `/readings/latest` is an API removal. Nothing outside `Monitor.tsx` calls it, so it
  leaves with the page rather than lingering as an unused route.
- `SPEC.md` §3.1, §3.3, §3.5 and §3.7's page count, plus `REMAKE-PLAN.md` §6.1's row-count table,
  all describe the old behaviour and must be corrected in the change that implements this.
- **Storage stops being a question.** At 30 meters the old shape wrote 43,200 rows/day (measured:
  239 rows from one meter in four hours on the installed machine); what remains is 2,880/day of
  meter-recorded intervals. The saving is a side effect — the reason is that nothing read them.
