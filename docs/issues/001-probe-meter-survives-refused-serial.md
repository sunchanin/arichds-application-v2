# probe_meter must finish its report when the meter refuses the Meter Serial

Type: fix
Milestone: M3 (leftover nit from issue #8)

## Blocked by

_Nothing._

## Context

`app/scripts/probe_meter.py` is the dev-side diagnostic: connect to one meter, print its
Meter Serial and its instantaneous register set, disconnect. Its whole value is telling an
engineer *which* registers a misbehaving meter will and will not serve.

The per-register loop is already built for that. Each register is read inside its own
`try`, and a refused one is printed as `!! <ExceptionName>: <message>` and the report keeps
going — the comment at `probe_meter.py:119` states the intent outright: *"one refused
register must not end the report."*

The Meter Serial read does not get that treatment. `probe_meter.py:110` calls
`driver.read_meter_serial()` bare, inside the function-wide `try`. When a meter accepts the
association but refuses that one register, the exception unwinds to the handler at
`probe_meter.py:122`, which prints `!!! FAILED: …` and returns 1 — so the **entire
instantaneous set below it is never printed**, on exactly the meter where an engineer most
needs to see which registers still answer.

This is recorded as nit 3 in `.claude/run-logs/issue-8.md` and was deliberately left for
the owner to judge. The judgement is: fix it — a diagnostic that stops diagnosing at the
first refusal is the opposite of a diagnostic.

Note that `read_meter_serial()` has two distinct failure shapes and they are not the same
event: it may **raise**, and it may **return `None`** (the association worked, the register
came back empty — `ProbeFailure.NO_SERIAL` in `probe_meter`'s sibling code path, and a
*failed* tick per ADR 0007). Both should be visible in the report and neither should stop
it.

## What to change

`app/scripts/probe_meter.py` only.

1. Read the Meter Serial with the same protection the register loop uses, so a raised
   exception is rendered in place (matching the existing `!! <Type>: <msg>` shape) and
   execution continues to the instantaneous set.
2. Make a `None` serial legible as its own outcome rather than printing the bare word
   `None` — an engineer reading the output should be able to tell "refused" from "answered
   empty" from "answered".
3. Leave the exit code honest: a meter that could not be associated with at all is still a
   failure (`return 1`). A meter that associated but refused or emptied the serial is a
   successful *diagnostic run* — it reported what it found.

## Acceptance criteria

- A meter that raises on `read_meter_serial()` still gets its full instantaneous set
  printed, and the serial line shows the exception type and message.
- A meter that returns `None` for the serial prints a distinguishable line and the report
  continues.
- The existing happy path is unchanged: a working meter prints the serial exactly as it
  does today.
- Automated tests cover all three cases with a fake/stub driver — no test may open a
  network connection. `app/tests/test_dlms_scaler.py` is the precedent for a test that
  reaches into `scripts/`.
- Nothing outside `app/scripts/probe_meter.py` and its new/updated test changes.

## เทสผ่าน (project gate — from CLAUDE.md)

- `cd app && ruff format --check . && ruff check . && pytest` — all green, and the pass
  count moves only by the tests this issue adds.
- No frontend work in this issue, so `pnpm lint` / `pnpm build` are not required.
- **Real-meter read is NOT required and must NOT be attempted for this issue.** The three
  cases are unreachable on a healthy meter, the change is to a dev script the service never
  loads, and the test meters are read-only shared hardware. Verify with the stub tests.

## Out of scope

- `driver._normalize()` being private (nit 4 in the same log) — deliberate, decided.
- Any change to `read_meter_serial()` itself or to any driver.
- The Poller's own handling of a `None` serial — settled by ADR 0007, do not revisit.
- `probe_capture_objects.py`.
