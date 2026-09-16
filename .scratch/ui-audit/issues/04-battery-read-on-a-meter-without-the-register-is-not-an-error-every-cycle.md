# 04: A battery read on a meter without the register is not an ERROR every cycle

**What to build:** A meter that answers the battery register with *"Device reports a
undefined object"* stops producing an ERROR with a full traceback every fifteen minutes, the
Battery page says why that meter has no rows, and the catalog's `supports_battery` flag for
that model reflects what real hardware says (ADR 0011: a flag turns on from a meter, never a
datasheet). On the dev machine two of three CEWE models — Prometer 100 (both units) and
Saral 305 — fail this way on every cycle while Premier 550 reads fine; the log is filling
with tracebacks that will bury a real error.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The read-only battery probe is run against `WP079074`, `WP080652` (Prometer 100) and
      `SS21996979` (Saral 305) and the outcome — register present or "undefined object" —
      is recorded in `docs/meter-notes/` with the date. This is the acceptance evidence;
      `fake_meter` is autouse, so no test can stand in for it.
- [ ] If the register is absent on those units: the catalog flag for the affected model(s)
      is corrected and ADR 0011's digest is amended with the evidence, so the Battery job
      never asks those meters. If it is present but under a different object: the driver is
      corrected. Either way, the `gurux-dlms` skill is invoked before touching a driver.
- [ ] A meter that still fails at runtime is logged as **one WARNING per device per day**
      naming the meter and the reason, not an ERROR with a traceback per cycle. Test: two
      consecutive failing cycles on one device emit one WARNING. Mutation probe: logging on
      every cycle turns it red.
- [ ] The Battery page shows, for a device with no rows, a sentence naming the reason ("this
      model does not expose a battery reading" or "the last read failed at <time>") instead
      of an empty table. `antd-ui` skill invoked.
- [ ] Gate: `ruff format --check .` + `ruff check .` + `pytest -n auto` green in `app/`;
      `pnpm lint` + `pnpm build` green in `web/`; probe output pasted into the ledger.
