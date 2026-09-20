# A Prometer 100 behind an HDLC converter can only be added as a Premier 550

**Type**: HITL · **Status**: done · **Found**: site TC diagnosis, 2026-09-20 ·
**Resolved**: 2026-09-20, the same day — see "What was done" at the bottom ·
**Blocked**: correct load-profile and billing data for site TC's meter `WP089573`

## The problem

Each CEWE driver fixes two unrelated things together: the **framing** it speaks
(`prometer100`: WRAPPER · `premier550`: HDLC) and the **column maps** it reads with
(`LOAD_PROFILE_COLUMN_MAP`, the billing declarations). Framing is a property of the install — a
meter behind a transparent serial-to-TCP converter speaks HDLC whatever its model — the same
lesson as the Premier 550 on port 50001 ("transport is a property of the install, not the
model", CLAUDE.md).

At site TC, meter `WP089573` at `10.100.91.1:4059` is a Prometer 100 by every measurement
(`docs/meter-notes/prometer100-load-profile-access.md`, last section): Logger 1 is 900 s / 25
columns and Logger 2 is 300 s / 7, its serial is `WP…`, and it refuses entry access and empty
ranges exactly as the lab Prometer 100 does. But it only associates over HDLC, so the operator's
four attempts as `prometer100` ended in `ValueError: Invalid connection.` and it was finally
added as `premier550`.

Under that driver its load profile is read with the wrong map: **5 of 25** Logger 1 columns match
and **0 of 7** on Logger 2 (`prometer100`'s map: 20 and 3). Billing is **not** affected
(corrected 2026-09-20 — this paragraph first said the billing map was per-model too): every CEWE
driver inherits the same billing declarations from `DlmsProfileDriver` and neither `premier550.py`
nor `prometer100.py` overrides one, so the 8 billing rows stored under `premier550` are the rows
`prometer100` would have stored.

## The decision this needs

1. **A second catalogued way to reach a Prometer 100** — e.g. a `Prometer100HdlcDriver`
   subclass that changes only `_INTERFACE`/`_protocol_args`, offered on the Devices form as a
   framing choice rather than as a tenth "model" (the catalog's keys, brands and order are locked,
   ADR 0011 — a new *model* key needs an ADR; a transport option on an existing model may not).
2. Or make framing a **transport field** on the device (`ConnectionParams`), next to host and
   port, and take it out of the drivers — the larger change, and the one that matches what the
   field keeps telling us.

Either way the site's device has to be re-added or migrated once the right driver exists, and its
stored billing rows reviewed.

## Evidence

- Site log 2026-09-20 19:04–19:24: `prometer100 association to 10.100.91.1:4059 aborted
  (ValueError)` ×8, then `Connected to premier550 10.100.91.1:4059`.
- `app/src/arichds/acquisition/drivers/prometer100.py` (`_INTERFACE = "WRAPPER"`) and
  `premier550.py` (`_INTERFACE = "HDLC"`, `-l 0`).
- Column-map match counts computed from both drivers' `LOAD_PROFILE_COLUMN_MAP` against the
  site's capture objects as printed by `probe_lp_buffer.exe`.

## What was done (2026-09-20)

The owner chose the framing-as-a-choice route, and the implementation took it one step further
than option 1's subclass, to where the repo's own principle already pointed: **framing is a field
of the `net` transport**, beside host and port.

- `ConnectionParams.framing` (`"wrapper"` / `"hdlc"` / `None` = the driver's default), read from
  the stored transport by `connection_params_from_transport` — so the Poller, the load-profile and
  billing reads and every Manual Read pick it up through the one function they already share. It
  is **not** part of `endpoint`: the lock still keys on `host:port`.
- `MeterDriver.SUPPORTED_FRAMINGS` — the driver's declaration, empty by default.
  `Prometer100Driver` declares `("wrapper", "hdlc")`; its HDLC argument list is the Premier 550's
  flag for flag, because that is the list the site's meter is proven to answer.
  `factory.create_driver` refuses a framing the model does not declare.
- API: `NetTransport.framing`, echoed on `NetTransportOut`; `CatalogEntry.framings`;
  `_require_supported_framing` → 422 before any socket opens, on Test connection, Create and
  Update. A framing nobody chose is never written into the row (`model_dump(exclude_none=True)`),
  so existing devices keep their stored shape and need no migration.
- Web: the Devices form shows **Framing** only on TCP and only for a model offering a choice; the
  default is sent as no field at all; a value left over from another model is cleared, but only
  once the catalog actually lists the model.
- `scripts/probe_lp_buffer.py --framing hdlc` (and the rebuilt `dist/probe_lp_buffer.exe`).

**Measured**: the Prometer 100 driver with `framing="hdlc"` associates with the lab's HDLC meter
(`49.229.159.44:50001`, serial read back) and is refused on `wrapper` — the mirror image of the
site's log. **Not measured**: a Prometer 100 *itself* over HDLC — there is none in the lab. Run the
probe at the site before relying on it.

**What the site has to do** — three steps, because nothing re-reads or re-sends a row that is
already stored (corrected 2026-09-20: an earlier version of this paragraph said the next read
fills stored rows in, which is wrong — the walk resumes from the watermark, ADR 0008, and Read
now takes no date range):

1. Edit the device, change Model to **Prometer 100**, set Framing to **HDLC**, save (the Meter
   Serial is the same, so the Update is accepted).
2. **Delete all data** on the device (`POST /api/devices/{id}/readings/clear`). It drops the
   load-profile rows stored under the Premier 550 map and resets the watermark, so the next read
   takes the whole buffer — two to three days at this site — with the right map. It drops the
   billing rows too, which were never wrong (above); the next read stores them again unchanged.
3. In the customer's MySQL, by hand:
   `DELETE FROM load_profile_readings WHERE meter_serial = 'WP089573';`
   The Database Destination sends only rows newer than its own `MAX(read_at)` (minus one hour)
   and its `ON DUPLICATE KEY UPDATE` rewrites nothing but `source`, so without this the wrong rows
   stay there until the Mirror Window drops them. Billing needs nothing: it is replaced wholesale
   every cycle (ADR 0020).

The gap this exposes — no way to re-read an old range, no way to re-send a corrected row to a
destination — is not filed yet.

