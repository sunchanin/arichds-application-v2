# A destination mirrors our window, it never archives

A customer's MySQL is a **Data-out Destination** (ADR 0016), not our store. That ADR settled
*who owns the write path*. It left open a question that only appears once rows actually start
landing there: **how much history the destination holds.**

Our own store does not hold history indefinitely. `db/retention.py` purges
`load_profile_readings` at `RETENTION_DAYS` — 90 (`constants.py:130`) — and deliberately never
purges `billing_readings`, because ADR 0009 forbids rewriting a closed period and the only way
to remove one is *Delete all data* on the Devices page. Measured on the dev machine on
2026-08-24: 60,947 load-profile rows across 3 devices spanning 2026-05-25 to 2026-08-24, which
is the retention window doing exactly what it says.

So a destination can hold *more* than we do — trivially, by never deleting — and the obvious
reading is that it should. Their database, their disk, their data; an append-only sink becomes
the long-term archive our 90-day window cannot be.

## The decision

**The destination holds exactly what we hold, and our sync job deletes from the customer's
database to keep it that way.** Rows past `RETENTION_DAYS` are removed from their
`load_profile_readings` on the same schedule they are removed from ours. The owner chose this
explicitly on 2026-08-24, against the recommendation in the grill.

Recorded because a `DELETE` statement fired into someone else's database reads as a bug, or as
an overreach, to anyone who finds it without this page. It is neither. It is the destination
being a mirror.

## What it buys

**The "offline longer than retention" question dissolves.** With an append-only destination, a
MySQL unreachable for more than 90 days loses those rows permanently and silently: the append
path asks the destination for its newest row and sends what is newer, and rows that aged out of
our store on day 91 are no longer ours to send. That is a real data-loss window with no error
and no log line — the sync would report success forever while a gap sat in the middle of the
customer's table.

Under a mirror there is no such window, because rows we can no longer send are rows the
destination is no longer supposed to hold. The gap and the purge are the same event.

**The operator's retention setting keeps meaning something.** If the destination archived, then
`RETENTION_DAYS` would govern our disk and nothing else — the real retention policy for the
customer's data would be "forever, silently", set by nobody.

**The size is bounded and knowable.** At the measured 224 rows per meter per day, nine meters
hold about 181,000 rows in a 90-day window. It stays 181,000 in year three. An archive would be
at roughly 735,000 rows per year and growing, in a database whose capacity planning is the
customer's and whose growth we caused.

## The asymmetry this creates — do not "fix" it

The two tables mirror on different clocks, because they are written differently:

| | How it mirrors | When a device is deleted here |
|---|---|---|
| `billing_readings` | whole table replaced each cycle (28 rows today) | its periods vanish from the destination at the **next sync** |
| `load_profile_readings` | rows appended, old rows purged by time | its intervals linger in the destination for **up to 90 days** |

Deleting a device therefore erases its billing history from the customer's database within
fifteen minutes and its load profile within three months. That looks like an inconsistency and
it is a consequence of ADR 0009's shape meeting this one: billing is small enough to replace
wholesale and contains a row that mutates in place (the Open Period, which is why
`billing_readings` carries `updated_at` at all — `models.py:301`), while load profile is large,
immutable per row, and must be appended.

Making them agree would mean either replacing 181,000 load-profile rows every fifteen minutes,
or tracking per-meter deletions in a table ADR 0008 forbids. Neither is worth buying symmetry.

## Alternatives rejected

| | Why not |
|---|---|
| Append forever; never delete | The recommendation in the grill, and refused by the owner. Buys the customer an archive at the price of an unbounded table we grow and a silent data-loss window past day 90 |
| Append forever, warn when a sync gap exceeds the window | Keeps both costs and adds a warning nobody reads until after the gap already happened |
| Mirror, but let the operator set the destination's own window | A second retention number that can disagree with the first. `constants.py:126-129` already refuses to let `RETENTION_DAYS` and `LOAD_PROFILE_BACKFILL_DAYS` share a constant *because* they are independent policies; inventing a third is the same mistake with none of that one's justification |
| Replace both tables wholesale every cycle | Simplest to describe, and it is what "just sync the database" sounds like. It also deletes a customer's archive down to our 90 days on every run, and rewrites 181,000 rows every fifteen minutes to move about 20 |

## Consequences

- **The destination account needs `DELETE`**, not only `SELECT`/`INSERT`. Least privilege
  cannot be narrowed past that, so it must be granted on a database dedicated to us rather
  than on one holding the customer's own tables.
- **A customer who wants an archive must build it themselves** — a view, a scheduled copy into
  their own table, whatever their DBA prefers. This has to be said at install time, not
  discovered when a year-old row disappears.
- **Two installs may safely share one destination database.** Rows are keyed on Meter Serial,
  which is globally unique per meter, and the purge is by time rather than by owner — so
  neither install deletes rows it did not write in any way that matters, and an install that is
  removed leaves rows that age out on schedule.
- **Nothing records that a purge ran** on either side. ADR 0008 forbids persisted job state and
  `db/retention.py` already honours that with a single INFO line; the destination's purge is
  the same shape.
