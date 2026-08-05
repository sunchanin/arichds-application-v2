# A device's identity comes from the meter — probe before the row exists

Status: accepted (2026-08-05, M3 grill)

Reverses: v1 (`cewe`) `src/license/meter_slots.py` + `DeviceService.create_device`, where
probing for the meter serial happened **only on lease-mode machines** (it existed to bind a
Meter Key to a serial, issue #145). On an offline-mode machine v1 created the device row
immediately and filled `meter_serial` later, on the first successful connection (INV-DEV-02).

## What v1 did

Two different creation paths depending on licensing mode:

| Machine mode | Create behavior |
|---|---|
| `lease` | probe the meter for its serial → redeem the Meter Key against the portal → create |
| `offline` | create the row now; `meter_serial` stays `NULL` until some later read fills it |

Every v1 machine in the field is offline-mode, so in practice the row-first path is the one
that ran, and `meter_serial` was a column that filled in eventually.

## Why it cannot be carried over

`meter_serial` is the only field that says *which physical meter this row is about*. Every
other identifying field — name, site, meter number — is typed by a person and can be typed
wrongly. If the serial arrives "eventually", then between Create and the first successful read
the system holds a device it cannot identify, and two rows pointed at the same meter (a copied
IP, a typo in a port) look identical to two rows pointed at different meters. The duplicate is
only discovered later, after both have been accumulating readings.

That matters more in v2 than in v1 because v2 pushes meter identity outward (SPEC §3.8: the
device list and its status are part of the sync payload). A duplicate that resolves late is a
duplicate the central server has already ingested.

## Decision

**Identity is read from the meter before anything is written.**

- **Create probes first.** Connect, read the serial, then insert. A failed probe — timeout,
  authentication rejected, host unreachable — **refuses the create and names the cause**. No
  row is written. Every row in `devices` therefore has a serial, from the moment it exists.
- **Update probes too.** If the serial that comes back differs from the stored one, the edit
  is pointing the row at a different physical meter; refuse it. Without this check, changing a
  host would silently merge two meters' history into one row.
- **`meter_serial` is unique across rows that currently exist.** A collision answers 409 and
  names the device already holding it, so the operator moves the existing row instead of
  creating a second one.
- **Deleting a device frees its serial.** There is no tombstone table. The alternative —
  remembering every serial ever seen — turns one mistyped meter into a permanent, unrecoverable
  block on re-adding a meter the customer physically owns. That is the same class of failure as
  the self-lockout rules M2 had to design around, and it is worse here because the product ships
  to unattended machines with no vendor CLI escape hatch (SPEC §3.2 records that the escape
  hatch does not exist yet).

## Consequences

- **A meter must be reachable to be configured.** Staging a site — entering all the devices
  before the meters are wired — is not possible. This is the deliberate trade: it was chosen
  over "add anyway" because a row without a serial is a row the duplicate check cannot protect,
  and the value of the check is exactly at the moment of adding.
- **Create is slow and can fail for reasons unrelated to the form.** It holds a Transport
  Endpoint lock and performs a DLMS association, so it takes seconds; the UI must say what is
  happening rather than spin, and the error must distinguish "wrong password" from "no route to
  host" — the operator's next action differs completely.
- The `Test connection` button exists because of this decision: it lets an operator check a
  form's values without a create attempt, so diagnosing a bad password is not done by
  repeatedly failing to create a device.
- Probing is a Manual Read and therefore takes lock priority over background polling
  (ADR 0006).
- The simulated (`SIM`) driver is removed from the product as part of this change: a fake
  meter cannot supply a real identity, and keeping it would mean a "if this is SIM, skip the
  probe" branch in the create path — precisely the model-shaped `if` that the driver
  abstraction exists to prevent. It survives as a test-only fake registered in `conftest.py`.
