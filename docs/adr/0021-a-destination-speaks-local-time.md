# A destination speaks local time; UTC stops at our boundary

`CLAUDE.md` carries this as a load-bearing invariant:

> **Interval Readings are UTC + kWh + COSEM column names, normalized at write time in the
> driver** — never at read time.

Every timestamp in the store obeys it. The drivers convert the meter's local clock on the way in
(`acquisition/drivers/_profile.py:62-65`), every API boundary re-asserts it with an `_as_utc`
helper, and `db/models.py` declares `DateTime(timezone=True)` throughout.

The owner's requirement for the customer MySQL destination is the opposite: **local time, not
UTC** (2026-08-24). This ADR records that the invariant is not being broken, because it never
described the outbound boundary in the first place.

## The decision

**A Data-out Destination receives local time. UTC is a property of our store, not of the data
leaving it.** The sync writes `read_at`, `bill_date`, `created_at` and `updated_at` shifted by
`METER_LOCAL_UTC_OFFSET_HOURS` (`constants.py:191`, currently 7) into MySQL `DATETIME` columns.

This is not new behaviour being invented for MySQL — it is the existing rule finally being
named. The Load Profile CSV auto-export already does exactly this: `export/format.py:162` is
`read_at_ict = read_at + _ICT_OFFSET  # UTC -> ICT (+7), F2`. The web pages already do it too,
rendering stored UTC in the browser's own zone, which on the customer's machine is ICT
(`web/src/pages/LoadProfile.tsx:79-87`). **Every existing path by which a human sees one of our
timestamps already converts.** MySQL was going to be the only exception.

ADR 0013 drew the same line for units and is the closest precedent: *display units are a view,
an appended file is a contract*. This one says the same about clocks — with the difference that
here the destination is neither a view nor an append-only file, and the conversion is therefore
part of the schema we create rather than of a renderer.

## The constant, not the machine's clock

The offset comes from `METER_LOCAL_UTC_OFFSET_HOURS`, **not** from the host's configured
timezone. Three reasons:

- The sync runs on the scheduler thread inside a Windows service under LocalSystem. There is no
  browser and no user session to inherit a zone from.
- A customer machine with a wrong timezone would silently produce wrong timestamps in their
  database, discoverable only by someone comparing against the meter.
- `constants.py:186-190` already frames the offset as *"a property of the SITE, not of the
  model"*, cites the field probe that measured it, and names its own trigger for change: *"A
  site outside ICT is the trigger to make this per-device rather than one constant."* That
  trigger now covers one more consumer.

## `DATETIME`, not `TIMESTAMP`

MySQL's `TIMESTAMP` converts on the way in and out using the session's `time_zone` variable.
That would make the correctness of the customer's data depend on their `my.cnf`, on the
connection's session settings, and on whether their reporting tool sets either — three places
we do not control and cannot test. `DATETIME` stores the literal we send.

The price is that the destination carries **no timezone information at all**. A column reading
`2026-08-24 17:35:00` does not say it is ICT. That is what the customer asked for, and it is why
the offset must come from a constant we can point at rather than from ambient state.

## The hazard this creates, and what absorbs it

The load-profile write path asks the destination for its newest `read_at` per
`(meter_serial, logger_id)` and sends what is newer. **That value is now in local time while
ours is in UTC**, so the comparison must convert — and a missing or doubled conversion is seven
hours of silently duplicated or skipped rows, with no error on either side.

Two things absorb it, deliberately rather than by luck:

- The conversion lives in **one** function, used by both the write and the watermark read, so
  there is no second place for the two to disagree.
- The insert is `INSERT … ON DUPLICATE KEY UPDATE` against a unique key on
  `(meter_serial, logger_id, read_at)`, and the watermark is rewound by a safety margin before
  sending. An off-by-offset therefore re-sends rows the destination already has and they collapse
  onto the existing row, rather than creating duplicates. The failure mode is bounded waste
  instead of silent corruption.

  **Not `INSERT IGNORE`**, which dedups identically and was what an earlier draft of this ADR
  said. Measured against MariaDB 10.4.32 on 2026-08-24: `IGNORE` downgrades data errors to
  warnings **even under `STRICT_TRANS_TABLES`**, so an over-long value is truncated and stored
  silently, while both plain `INSERT` and `ON DUPLICATE KEY UPDATE` raise `ERROR 1406 Data too
  long`. Dedup was never worth buying with a swallowed error — least of all on the boundary this
  ADR exists to keep honest.

## Alternatives rejected

| | Why not |
|---|---|
| Write UTC, as v1 did | v1's MySQL was UTC in every table (`cewe-worker/src/core/models.py:108` and every model below it), so this is the proven path — and the owner refused it on 2026-08-24. A customer reading their own database should not have to know our storage convention to read a timestamp |
| Write both — a UTC column and a local one | Removes the comparison hazard outright and costs 8 bytes a row. Rejected because two columns that must agree is a new invariant nobody enforces, and the second one exists only for our convenience in a schema the customer reads |
| Store `TIMESTAMP` and let MySQL convert | Moves correctness into the customer's server configuration. See above |
| Add a `timezone` column, or an offset column per row | Honest, and answers the "17:35 of what?" question the chosen design leaves open. Rejected as scope the owner did not ask for; revisit it together with the per-device offset when a non-ICT site appears — they are the same change |

## Consequences

- **A non-ICT site now breaks two things, not one.** `constants.py`'s stated trigger for making
  the offset per-device already covered the CSV export; it now covers the destination too, and
  the destination's rows would be wrong in a database we do not own.
- **`bill_date` shifts across midnight.** A period the meter closed at `2026-03-31 17:00 UTC`
  lands in the destination as `2026-04-01 00:00`. That is the meter's own local cut time and is
  the correct value, but it means the destination's bill dates and any UTC-based report of ours
  will name different days for the same period.
- **This ADR does not touch the store.** Nothing in `app/src/arichds/` outside the sync module
  may hold a local-time datetime; the conversion happens at the write, in the sync module, and
  nowhere earlier. The invariant quoted at the top stands unchanged.
- **`export/` and the sync module must not share the conversion helper.** ADR 0013 kept
  `export/` clear of the render-time scale machinery for exactly this reason: the two boundaries
  agree today by coincidence of the same constant, not by contract, and a shared helper would
  make a future change to one silently change the other.
