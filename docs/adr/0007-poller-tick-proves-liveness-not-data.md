# The Poller's tick proves liveness, not data — v2 has no live-value display

Status: accepted (2026-08-05, owner decision after grilling). **Fully implemented.**
**Decision item 1 landed in issue #6 (M3-3)**: the Devices page replaced the Monitor page as
the app's landing screen, `web/src/pages/Monitor.tsx` and `api.latestReading` are gone, and
`GET /api/devices/{id}/readings/latest` and its `ReadingOut` model are gone from
`app/src/arichds/api/devices.py`. Nothing in `web/src` displays an electrical value any more.
**Items 2, 3, 5 and 6 landed in issue #8 (M3-4)**: `poll_once` now reads the Meter Serial and
discards it, `store_reading()` and `INTERVAL_LABEL_INSTANTANEOUS` are gone, migration `0005`
deleted the `interval='60s'` rows and renamed `interval_readings` to `load_profile_readings`
(class `LoadProfileReading`), and `read_instantaneous()`/`health_check()` are gone from both
`MeterDriver` and `TcpDlmsDriver`. `TickOutcome.STORED` became `TickOutcome.OK` in the same
change. Item 4 (no cache) needed no code — the cache was never built. Issue #5 was deliberately
untouched by any of this: the Poller kept behaving exactly as it did until #6 had removed the
last reader, so no intermediate state left the product without a working screen.

Two things #8 decided that this ADR had left open. A `read_meter_serial()` that returns
**`None`** is a *failed* tick, not a successful one — the association succeeded and the
register came back empty, which is precisely the "answers but cannot serve a read" state item 2
exists to catch, and `probe_meter` already classifies the same answer as
`ProbeFailure.NO_SERIAL`. And `poll_once` does **not** reuse `probe_meter()` despite reading the
same register: the probe takes the endpoint as a *Manual Read*, and a background tick holding
the manual lock would invert ADR 0006 and starve the buttons a person is waiting on.

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
repository: `GET /api/devices/{id}/readings/latest` is called from `web/src/pages/Monitor.tsx`
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

6. **`MeterDriver.read_instantaneous()` and `health_check()` go with it.** `read_instantaneous()`
   has exactly one production caller, the Poller, which this decision removes. Leaving it as an
   `@abstractmethod` would make every future base class implement code nothing calls: the seven
   remaining DLMS-over-TCP models inherit `TcpDlmsDriver`'s implementation and pay nothing, but the
   serial (SMW110) and Modbus bases that M4 introduces would each have to. That is a small cost,
   not a large one — the reason to remove it is simply that an abstract method with no callers
   is not a contract, it is a leftover.

   `health_check()` is different mechanics, same verdict. It is **concrete** — a default
   implementation on the base (`base.py`), overridden in `TcpDlmsDriver` — so no future base class
   would be forced to implement it. It goes because it has no caller anywhere in `src/` or `tests/`
   today (dead since M1), and because its default body **calls `read_instantaneous()`**: removing
   one breaks the other, so they leave together.

   **This does mean the ADR must be implemented before M4**, which is where those new base classes
   get written.

   The three scaler cases in `tests/test_dlms_scaler.py` that exercise ADR 0002 through
   `read_instantaneous()` move to `read_register()` — coverage of ADR 0002 must not shrink to pay
   for this.

## What stays, and why

- **The 60-second cadence.** ADR 0004 deleted v1's separate health-check loop on the grounds that
  the Poller already talks to every meter every minute. That tick is now the *only* source of
  device status. This ADR removes what the tick stores, never the tick.
- **`volt_*`, `current_*`, `freq` on `interval_readings`.** SPEC §3.5's Logger 2 (Premier 550)
  records V/I/PF/freq **as load profile** — meter-recorded intervals, which is exactly what the
  table is for.
- **`InstantaneousReading`, the dataclass.** M5 may well use the same shape for a load-profile
  row, so the decision belongs there. The *method* does not survive — see below.

## Consequences

- **v2 ships with no live-values screen.** If a customer asks for one later it is a new feature
  with its own storage decision — not a reason to keep this one.
- **The readings table is empty from M3 until M5** — and while it was empty, #8 renamed it from
  `interval_readings` to `load_profile_readings`, because after the 60 s rows go what it holds
  genuinely is load profile and there will never be a cheaper moment. Accepted: load profile
  arrives at M5, and the day-5 demo runs Devices → Load Profile → Billing.
- **`TickOutcome.STORED`** (issue #4) became a lie the moment nothing was stored, so #8 renamed it
  to `TickOutcome.OK`. It is never persisted and never crosses the API, so the value was free.
- Removing `/readings/latest` is an API removal. Nothing outside `Monitor.tsx` calls it, so it
  leaves with the page rather than lingering as an unused route.
- `SPEC.md` §3.1, §3.3, §3.5 and §3.7's page count, plus `REMAKE-PLAN.md` §6.1's row-count table,
  all described the old behaviour and were corrected in #8, the change that implements this.
  §6.1's v2 row-count was also wrong on its own terms — it read `20 × 96` against a stated mix of
  18 DLMS + 2 Modbus meters, ignoring Modbus's own cadence — and is now `1,728 + 2,880 = 4,608`.
- **Storage stops being a question.** At 30 meters the old shape wrote 43,200 rows/day (measured:
  239 rows from one meter in four hours on the installed machine); what remains is 2,880/day of
  meter-recorded intervals. The saving is a side effect — the reason is that nothing read them.
