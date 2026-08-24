# A meter is licensed individually, not just counted

The machine licence already carries a meter **quota**: `max_meters` is a field of the
Activation Code (`licensing/activation_code.py:65`), reaches the app through
`LicenseService.current_state()`, and is enforced when a device is created
(`api/devices.py:852`). A customer licensed for ten meters can add any ten meters they like.

The owner needs the stronger thing: a customer can only add **the meters we sold them**. A
portal will eventually issue those entitlements online; this ADR records the offline stopgap
that ships first, because the offline shape is the one that has to survive the portal's arrival.

## The decision

A **Meter Activation Code** is a signed one-line string, issued by us with the same Ed25519
key and CLI shape as the Activation Code, and **bound to two things at once**:

- the **Meter Serial**, read from the meter itself, and
- the **Machine ID** of the install it will run on.

It is supplied when a device is added and stored on that device's row. Both gates apply: a new
device needs a valid Meter Activation Code **and** must fit inside `max_meters`.

## Why bound to the serial *and* the machine

The serial alone would let one code follow a meter to any install. Binding the machine too
means a code authorises one meter on one machine — which is what "we sold this customer this
meter" actually means.

It works because the serial is not something a person types. ADR 0005 already establishes that
**identity comes from the meter**: Create probes before writing a row, and `POST
/test-connection` already returns `meter_serial` (`api/devices.py:505`). So the operator's flow
needs no new endpoint:

```
Test connection  →  Meter Serial  →  ask us for a code  →  paste it  →  Create
```

## When it is checked

**At Create.**

> **Amendment (issue #42 implementation, 2026-08-24):** this section originally said the gate
> was also checked "again at Update when the serial changes," reasoning that ADR 0005's
> serial-change handling "accepts the new identity" and would otherwise let a device keep
> running on a code issued for the old serial. **That is false about the shipped code.**
> `_reject_changed_serial` (`api/devices.py`, ADR 0005) already refuses **any** Update whose
> probed serial differs from the stored one, with a 409, unconditionally — the only case it
> lets through is a stored `NULL` serial (a pre-M3 row being identified for the first time, ADR
> 0019's own "Devices that predate this" population). There is no window in which an Update
> silently repoints a device at a different physical meter, so there is nothing for a
> Meter-Activation-Code re-check to close that isn't already closed, and adding one would only
> *loosen* `_reject_changed_serial` into "admit the new serial if a valid code is supplied" —
> reopening the exact bypass this section was written to prevent. No Update-side code check was
> built; do not add one without first relaxing `_reject_changed_serial` on purpose.

It is deliberately **not** re-checked continuously. That is what separates it from the machine
licence, where ADR 0001 requires live re-evaluation because Limited Mode has to arrive and
leave without a restart. This is an entitlement checked at the moment of entitlement — a
meter already added keeps working, and a machine whose licence lapses is already stopped by
Limited Mode at a higher layer.

## Devices that predate this

**Grandfathered.** Existing rows have no Meter Activation Code and keep working. Enforcing
retroactively would break every install we have already delivered at the moment it is
upgraded, for a rule the customer had no way to satisfy in advance.

The cost is that the gate only tightens over time, and an install that already holds fifty
un-coded meters stays that way. `max_meters` is what still bounds it.

## Alternatives rejected

| | Why not |
|---|---|
| Raise `max_meters` and stop there | Already possible today by re-issuing the Activation Code. It gates the count, never which meters — the thing being asked for. |
| Bind to the serial only | One code works on any install; a customer with two machines needs one purchase. |
| Replace `max_meters` with per-meter codes | One concept instead of two, but every existing install would need re-licensing, and the count is still the useful backstop when a code leaks. |
| Wait for the portal | The owner flagged this as urgent, and the offline path has to exist anyway for sites with no outbound connectivity — the same constraint that produced the Syncthing answer for data-out. |

## Consequences

- **A meter swap costs a new code.** Replacing a failed meter under RMA changes the serial, and
  the shipped code never gets as far as checking a code over it: `_reject_changed_serial` (ADR
  0005) refuses the Update outright with a 409 the moment the probed serial disagrees with the
  stored one. The operator's real procedure is **delete the device and create a new one** —
  `POST /api/devices` with a code issued for the new serial — not edit the existing row. Deleting
  discards that device's stored readings, with no tombstone (ADR 0005 — the freed serial can be
  re-added later; `delete_device`). That is the deliberate price of closing the bypass above,
  and it needs to be in the operator documentation, not discovered at a site visit.
- **Moving an install to new hardware invalidates every meter code**, because the Machine ID
  changes — on top of the machine licence itself needing reissue. A hardware migration is now
  an N+1 code operation, not a one-code operation.
- **A new column on `devices` and an Alembic migration**, with `render_as_batch=True` as this
  repo's SQLite setup requires.
- **Two vocabulary items one letter apart.** `CONTEXT.md` carries both **Activation Code** and
  **Meter Activation Code**, and the second lists *"per-meter Activation Code"* under `_Avoid_`
  precisely because prose that blurs them will produce code that gates the wrong thing.
- **The portal must issue the same artefact.** When it lands it replaces the delivery channel,
  not the format — otherwise every already-issued code becomes a migration problem.
