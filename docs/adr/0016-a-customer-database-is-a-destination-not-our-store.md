# A customer's database is a destination, not our store

Some sites already run their own MySQL and want the meter data to land in it. The obvious
reading of that request — *point ARICHDS at their MySQL instead of SQLite* — is the expensive
one and the fragile one. **ARICHDS keeps its own SQLite store in every deployment; a customer
database is one more outbound destination, alongside FTP and a synced folder.** Recorded
because the Database page in the UI looks exactly like v1's MySQL connection form, and a future
reader will reasonably assume it swaps the backing store.

## Why the backing-store reading is not available

| | What breaks |
|---|---|
| **ADR 0009's invariant** | Billing correctness is enforced by two **partial unique indexes** (`0007_m6_billing_readings.py:109-117`, `sqlite_where`). **MySQL has never supported partial indexes, in any version.** Losing them means resurrecting the `is_latest` reconciler that ADR 0009 deleted — reversing that ADR to satisfy this one |
| **Availability** | A meter reader that cannot write cannot read. If the store is the customer's database, their maintenance window, their network, and their disk become our uptime. Today an unreachable destination costs a retry; then it would cost the readings |
| **Migrations** | `render_as_batch=True` is set from migration 0001 and `env.py:3` calls it *"not negotiable"* — it is SQLite's rewrite-the-table workaround |
| **Backup** | The daily job copies `arichds.db`. Against MySQL it is meaningless; `mysqldump` is a different job with different failure modes |
| **Assumptions in the code** | `_as_utc()` exists because *"SQLite hands back naive datetimes"*; WAL mode; a retention `DELETE` batch size measured against SQLite 3.50.4 |

Each is individually solvable. Together they mean maintaining and testing two storage engines
for the lifetime of the product, in exchange for a benefit the destination reading already
delivers.

## What the customer actually gets

The same thing: their meter data, in their database, queryable by their systems. The difference
is only in what owns the write path — and owning it is what lets the product keep reading meters
when their database is down.

This also collapses three requirements into one shape. **FTP upload, a customer MySQL, and a
Syncthing folder are the same kind of thing: a Data-out Destination.** SPEC §3.8 already scopes
that surface as M8. Sites that refuse cloud upload for confidentiality are then not an exception
to the architecture — they are a site that chose a different destination.

## Consequences

- **`one process · one exe · one SQLite DB · one license` (CLAUDE.md) survives this request**
  rather than being quietly reversed by a settings page.
- **The Database page configures an outbound target, and its wording must say so.** A form that
  reads like v1's connection settings will be understood as v1's connection settings. It needs to
  state that ARICHDS pushes to this database; it does not run on it.
- **Schema on their side is our contract, not our schema.** We are not replicating
  `billing_readings` and its 43 columns into a stranger's database by accident; what we push is a
  designed payload, versioned like the push contract in SPEC §3.8, and the customer gets a spec
  for it. That design is M8 work and is deliberately not settled here.
- **This ADR does not authorise FTP.** Plain FTP sends credentials and data in the clear, and one
  site's stated reason for refusing cloud upload was confidentiality. Whether the destination is
  FTP, FTPS or SFTP is an open question for M8.
