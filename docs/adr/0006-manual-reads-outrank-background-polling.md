# Manual Reads outrank background polling on the Transport Endpoint lock

Status: accepted (2026-08-05, M3 grill)

Carries forward: v1 (`cewe`) ADR 0020 — manual reads take priority over background readers.
Moves it earlier: SPEC §3.4 had scheduled this for M4, but M3 is where the buttons that need
it first appear.

## The situation M3 creates

Before M3 there was exactly one thing talking to a meter: the Poller, every 60 seconds, one
worker per device, one lock per Transport Endpoint (CONTEXT.md). M3 adds four ways a person
can start a conversation with the same meter:

1. the probe behind **Create** (ADR 0005)
2. the re-probe behind **Update**
3. **Test connection**
4. **Read now**

All four take the same lock, and devices sharing a serial line share one lock — so on a
multi-drop line a person can be queued behind reads for meters they are not even looking at.

## Why plain FIFO is not good enough

A first-come-first-served lock with a timeout is the smaller change, and it is what the code
does today by default. It fails in the ordinary case rather than an exotic one: three meters
on one line, each taking a few seconds per cycle, means a person who presses `Read now` waits
for a queue they cannot see, and if the wait exceeds the request timeout they get an error for
a device that is working perfectly. The operator's conclusion — "this button doesn't work" —
is worse than the delay.

The asymmetry is what decides it: **a background tick that is skipped costs one minute of a
60-second series; a person waiting on a button costs trust in the product.** Those are not
comparable losses, so the lock should not treat them as equal.

## Decision

The Transport Endpoint lock is **priority-aware**: a Manual Read is granted the endpoint ahead
of any queued background tick.

- "Manual Read" means a read a person asked for — the four paths above. It is a property of
  the *request*, not of the driver or the model, so no acquisition code branches on it.
- An **in-flight** read is never interrupted. Priority decides who gets the lock next, never
  who keeps it now — the same principle as v1 ADR 0009's pause, which stops new cycles rather
  than force-closing sockets.
- A background tick that loses its slot is **skipped, not queued**. Deferring it would deliver
  a reading stamped later than the interval it belongs to; the next tick is 60 seconds away and
  carries a correct timestamp.
- Skipped ticks do **not** count toward the 3-consecutive-failures rule that flips a device to
  `Offline` (ADR 0004). A tick that never ran is not a tick that failed — conflating them would
  make pressing `Read now` a way to mark your own meter offline.

## Consequences

- **Background polling can starve under manual load**, in principle: a person hammering
  `Read now` on a busy line delays that line's ticks indefinitely. This is bounded in practice
  (a human pressing a button, at v2's 10–30 meter scale) but it is a real property of the
  design, so it must be covered by an explicit starvation test rather than left to assumption.
- The lock is no longer a plain `threading.Lock`, which is a genuine increase in the
  concurrency surface — the one place in v2 where lock behavior is not the language default,
  and therefore the one place worth testing hardest.
- Every Manual Read path must be able to say *why* it failed. Having won the lock, an error is
  now about the meter (auth, timeout, unreachable) and never about queuing, so the message
  shown to the operator should never be "busy, try again".
