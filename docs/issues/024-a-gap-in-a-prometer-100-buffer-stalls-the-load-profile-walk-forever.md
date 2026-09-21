# A gap in a Prometer 100's buffer stalls the load-profile walk forever

**Type**: HITL · **Status**: needs-decision · **Found**: site TC diagnosis, 2026-09-20 ·
**Blocks**: nothing shipped today; it is a latent stall on every Prometer 100 ·
**Blocked by**: `docs/issues/025` (the flag below belongs on the driver the site's meter should
actually run under)

## The problem

A Prometer 100 answers a range read holding **no entries** with
`GXDLMSException: Access Error : Data Block Unavailable.` instead of an empty list — measured on
the healthy lab unit and on the site's (`docs/meter-notes/prometer100-load-profile-access.md`,
point 2). `load_profile._walk` treats any exception from `driver.read_load_profile()` as a failed
chunk and stops the walk.

So a 24 h chunk (`LOAD_PROFILE_CHUNK_HOURS`) that falls wholly inside a logging gap — a meter
switched off for two days, a meter swapped and re-energised later — is refused, the walk stops
*at* the gap, and since the watermark is the data (ADR 0008) the next cycle starts from the same
last row and hits the same chunk. Rows after the gap are never stored. Nothing heals it: the gap
never fills.

The 2026-09-20 fix (the estimated backfill start in `load_profile_oldest_reading`) removes the
*leading* empty chunks only. It does nothing for a gap in the middle.

## The decision this needs

Treat that refusal as an **empty chunk** for the models measured to behave this way — proposed as
a driver-declared class attribute on the `DlmsProfileDriver` base (default `False`, `True` on the
Prometer 100 family), checked where `read_load_profile` calls `readRowsByRange`, with one INFO
line per skipped chunk. Not on the whole base: the Premier 550 answers `[]` by itself, and the
Saral 305 and the five SMART TCC models have not been measured.

The risk to weigh: if the same error ever means something else on this model (a non-empty range
refused for another reason), that chunk is skipped silently and the watermark moves past it —
silent loss of up to 24 h, against today's certain and permanent stall.

## What else rides on this (added 2026-09-21)

Since ADR 0027 the Database Destination sends one merged row per interval and holds a Logger 1
row until Logger 2 has caught up. A Logger 2 that this stall stops **at its very first chunk**
never stores a row, and a two-Logger meter with no Logger 2 row at all is sent a permanent
24 hours late (`merged_rows_cap`: `l1_max − 24 h`) with nothing on the Database page to say so.
A stall further in is milder — Logger 2 goes quiet, and after 24 h the rows are released
without their Logger 2 columns. Either way, deciding this issue also decides that.

## Evidence

- `docs/meter-notes/prometer100-load-profile-access.md` — the measurements.
- `app/src/arichds/acquisition/load_profile.py::_walk` — a failed chunk ends the walk.
- `app/src/arichds/acquisition/drivers/_dlms_profile.py::read_load_profile` — the unguarded
  `readRowsByRange`.
