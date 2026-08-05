# Device status is derived from the Poller — there is no health-check loop

Status: accepted (2026-08-05, M3 grill)

Reverses: v1 (`cewe`) `cewe-worker/src/worker/background_worker.py::_meter_loop` +
`connection_manager.health_check()`, and the two tables they feed —
`device_status` (one row per device) and `device_heartbeats` (append-only), created in
migration `a6e231540b96`.

## What v1 did

v1 ran a dedicated health check: one thread per device, waking every
`POLL_INTERVAL_SEC = 300` (`src/constants.py:42`), opening its own DLMS association purely to
answer "is this meter reachable?", then writing one `device_status` upsert plus one
`device_heartbeats` row per check. Reading actual data was a *separate* concern handled by the
Load Profile scheduler, the billing auto-reader and the battery reader — so a v1 device had
five independent background readers competing for its line, and the health check was one of
them.

## Why it cannot be carried over

v2 already reads every device every 60 seconds. The M1 Poller opens the connection, reads
V/I/frequency/energy, and writes an Interval Reading — and by doing so it has *already
answered the health question more recently and more thoroughly than a 5-minute connectivity
probe would*. Adding a health-check job on top would mean a second connection to the same
meter, on the same Transport Endpoint lock, to learn something the first connection just
proved.

That cost is not theoretical: meters sharing a serial line queue behind one lock, so a
redundant prober does not just waste a socket — it delays the reads that carry actual data.

The heartbeat table has the same shape of problem. At v2's design scale (30 meters, SPEC §4)
a per-tick heartbeat is 30 × 1440 = 43,200 rows/day, which at 90-day retention would make it
the second-largest table in a database whose whole premise is 13 lean tables. Nobody has asked
for uptime-percentage reporting; the operator question is "what is down right now" and "when
did it drop", and both are answered by transitions alone.

## Decision

- **No health-check job.** The status of a device is a function of its Poller ticks. The job
  registry gains nothing at M3.
- **Four statuses: `Online` · `Offline` · `Paused` · `Unknown`.** v1's `Error` is folded into
  `Offline` — a read that did not succeed did not succeed, and the reason lives in a `detail`
  string rather than in the state machine. `Unknown` means no tick has reported yet.
- **Offline after 3 consecutive failed ticks** (~3 minutes), not the first one. A single
  timeout on a GPRS link is normal; flipping state on it would flap the tree and write paired
  transition rows all day.
- **A successful Create sets `Online` immediately** — the probe (ADR 0005) just held a
  conversation with the meter seconds ago, so making the operator watch `Unknown` for a minute
  would be reporting less than we know.
- **Resume sets `Unknown`, not the pre-pause status.** While paused nobody talked to the
  meter, so nobody knows; carrying the old value forward would present a stale fact as current.
- **`device_events` records transitions and operator actions only** — status changes plus
  created / updated / paused / resumed / data cleared, each with the acting user.

## Consequences

- **Uptime percentage over an arbitrary window is no longer computable exactly.** Transitions
  give you outage start/end, which covers "when was it down"; they do not give you the
  per-check sample density v1's heartbeats had. If a customer ever asks for SLA reporting,
  the answer is to derive it from transition intervals, not to reinstate heartbeats.
- **A paused device has no live status.** It reads `Paused`, and that is all the system knows
  — by design, since pause exists precisely to stop touching the meter.
- Status detection is coupled to the poll cadence: the "3 ticks" rule means ~3 minutes at the
  fixed 60-second cadence. The cadence is deliberately not configurable (SPEC §3.3), so the
  two cannot drift apart.
- Two v1 tables never get built, and the v2 count stays at the 13 in SPEC §4.
