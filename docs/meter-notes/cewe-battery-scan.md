# CEWE battery register — scanned off the four reachable units, 2026-09-16

**Why this file exists.** The `battery` job read `0.0.96.6.1.255` (attribute 2 — the
COSEM "battery charge display", what v1 read and stored as a raw string) on every model
whose catalog flag said `supports_battery`, which since M7-2 (issue #29) meant all three
CEWE models. On the first real install two of them answered every hourly read with
*"Device reports a undefined object"* and the App Log filled with a traceback per meter per
hour (ui-audit ticket 04). ADR 0011 says a flag turns on from a meter, never a datasheet —
so the meters were asked.

**How.** `app/scripts/probe_battery.py` — one association per meter, attribute reads only,
never a write. It first runs the product's own `read_battery_status()`, then walks the whole
COSEM battery group `0.0.96.6.{0..6}.255` as a class-1 Data object (attribute 2) and as a
class-3 Register (attributes 3 and 2). Password: the documented CEWE fixed password.

## What each unit answered

| Model | Serial | Endpoint | `read_battery_status()` → `0.0.96.6.1.255` | Anything else in `0.0.96.6.x` |
|---|---|---|---|---|
| Prometer 100 | `WP079074` | `203.170.151.152:4059` | **undefined object** (every class) | `E=0` as Data → `GXUInt32 0` — a battery **use-time counter**, not a status; as Register → "inconsistent Class or object" |
| Prometer 100 | `WP080652` | `147.50.94.190:4060` | **undefined object** (every class) | `E=0` as Data → `GXUInt32 20`; everything else undefined |
| Saral 305 | `SS21996979` | `203.170.151.217:4059` | **undefined object** (every class) | **nothing** — `E=0..6` all undefined in every class |
| Premier 550 | `SS18197374` | `49.229.159.44:50001` | **`'0'`** (Data attr 2 → `GXUInt8 0`) | `E=0`, `E=2..6` undefined; the Register shapes of `E=1` → "inconsistent Class or object" |

Two facts a datasheet would not have given:

1. **The register the product reads exists on exactly one of the three CEWE models.**
   Premier 550 answers it as a class-1 Data object holding an unsigned 8-bit integer — the
   raw-string storage rule (M7-2 D8) is right for it, and the value is `0`.
2. **The Prometer 100 exposes a different member of the group** — `E=0`, the use-time
   counter (`0` on one unit, `20` on the other; the unit of that count is not stated by the
   meter and was not guessed). It is *a* battery datum but it is not the status display the
   customer asked for, so it is **recorded here and not read**: declaring it as the battery
   status would store a running counter under a column the page calls "Status".

## What changed because of this

- `supports_battery` is now `False` on Prometer 100 and Saral 305 (driver and catalog,
  `test_catalog.py` asserts they agree). The job never asks those meters, so the hourly
  traceback is gone by construction.
- A meter that still fails at runtime (Premier 550 on a bad day) is one WARNING per device
  per UTC day, kept in memory, and the Battery page names the last failure instead of showing
  an empty table.
- ADR 0011's digest is amended: three CEWE models → **Premier 550 alone**.

## Limitations

- **One firmware per model, one unit for two of them.** A Saral 305 or Prometer 100 elsewhere
  may carry the register; if one does, the flag is flipped from that meter's answer, not from
  this file. The probe is the acceptance criterion (`fake_meter` is autouse in the suite).
- **SMART TCC and Mitsubishi were not probed** — they were never flagged battery-capable and
  the TCC test meter does not answer at all (CLAUDE.md).
- **The Prometer 100's `E=0` counter is recorded, not interpreted.** Whether it is hours or
  days, and whether the customer wants it, are questions for CEWE and the owner respectively.
