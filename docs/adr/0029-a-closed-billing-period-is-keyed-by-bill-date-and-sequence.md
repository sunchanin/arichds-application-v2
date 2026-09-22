# 0029. A closed billing period is keyed by bill date **and sequence** — every entry the meter holds is stored

**Status:** Accepted · 2026-09-22 · owner decision ("ข"), at the customer's request: the rows
ARICHDS shows must be the rows the meter's own vendor tool shows.

**Amends:** ADR 0009's natural key for a closed period, `(device, bill_date)`, and CONTEXT.md's
*Bill Date*. ADR 0009's one read path, its dissolved "backfill", the Open Period slot and its
partial unique index are all untouched. **Touches** ADR 0024 (the Central Push's billing natural
key, contract version 1 → 2), ADR 0015 (the capture filename stem) and ADR 0028 (row order).

## Context

Site TC's Prometer 100 (`WP089573`) holds thirteen closed periods. Its vendor tool (ConfigView,
customer screenshot 2026-09-22) lists them as History 1–13. ARICHDS held **seven**, and the
customer said the two did not match. They were right, and the log said why, four times per
read: *"Billing period … at bill_date 2026-09-19T08:59:50+00:00 is already stored with a
different value — skipping"*.

The meter writes its periods **in pairs at the same second**: six pairs, every one with *Cause
of Billing: Invocation of Scaling tariff* — commissioning resets when the CT/VT ratio was set,
not monthly cuts. One pair makes the mechanism visible: History 2 holds `31.18` kWh and
History 1, stamped the same second, `3118.25` — the same register before and after a ×100
scaling. Two of the pairs are `0.00` in every column, identical to the last digit.

ADR 0009 keyed a closed period on `(device, bill_date)` so that reading the same buffer twice
stores nothing new. That key assumed a meter never stamps two periods on one second. This meter
does, and the customer's yardstick is the vendor tool, which shows all thirteen.

## Decision

**A closed period's natural key is `(device, bill_date, sequence)`.** *Sequence* (CONTEXT.md:
**Billing Sequence**) is the position of an entry among the entries that share its bill date,
counted from the newest as the meter lists them — History 1 is `0`, History 2 is `1`. It is
computed inside one whole-buffer read and stored as a column; a single-entry bill date is
`sequence = 0`, so every row that exists today keeps its key.

The partial unique index over closed periods gains the column; the Open Period slot is
unchanged. The store's rule is otherwise ADR 0009's: insert what is absent, skip and WARN what
is present with different values, do nothing for what is present and equal.

**Every entry is stored, including a pair that is identical in every column.** The goal is
"what the meter holds", not "what differs". Keeping only the pairs whose values differ would
have given TC eleven rows and the same complaint.

**Why sequence and not something else.**
- *An auto-increment id alone* (the owner's first suggestion): the table already has one. An id
  gives a row identity; it cannot tell the next whole-buffer read — daily, and after every
  change — that History 2 today is History 2 yesterday. With only an id, thirteen rows become
  twenty-six on the second day.
- *The values as part of the key*: two of the pairs are identical in every column.
- *The entry's position in the buffer*: shifts by one every time the meter cuts a period, so
  the same entry has a different position each read. Sequence is counted **within** a bill-date
  group from its newest member, and the meter drops the oldest entry first, so a group can lose
  its `1` and keep its `0`, never the reverse.

**Order, everywhere a person looks: oldest bill date first, then sequence ascending** (owner,
Q6 "ก"). The Billing page's default sort changes from newest-first to oldest-first, and with it
the Standard capture image, which is a screenshot of that page (ADR 0017). The Billing Export
File already lists oldest first (`record_no` runs that way). The Classic image (ADR 0028) was
already oldest-first. The Central Push and the Database Destination carry no order.

**Where the key travels.**
- *Central Push*: `sequence` joins `BillingItem` and the server's natural key for billing
  becomes `(meter_serial, bill_date, sequence)` — **contract version 2**. The server may keep
  its own auto id but must upsert on the natural key, for the same reason as above: a machine
  re-pushes after *Delete all data* or a reinstall (ADR 0024). Nothing else in the contract
  changes.
- *Capture documents* (ADR 0015's one stem): a period with `sequence > 0` gets the stem
  suffixed `_<sequence + 1>` (`2026-09-19_085950_2.pdf`); `sequence = 0` keeps the unsuffixed
  stem, so no existing file changes its name. Both periods of a pair get documents.
- *Billing Export File*: `sequence` is a column, after `bill_date`.
- *Database Destination*: `sequence` is a column after `bill_date`; the table is replaced
  wholesale every cycle and its index is not unique, so nothing else moves.
- *Billing Change Check* (ADR 0018): unaffected — it compares the newest closed bill date.

**Sites already running.** The six TC entries are still in the meter (buffer 16, 13 in use); the
first whole-buffer read on the new build stores them, with no manual step. The migration adds
the column with default `0` and rebuilds the partial index.

## What it costs

- A bill date is no longer unique on its own. Every query that groups, joins or dedups closed
  periods by `(device, bill_date)` — the page, the export, the push, the capture's ten-period
  window — must carry `sequence` or accept two rows. The tickets name each caller they touch;
  the count is theirs to establish, not this ADR's to guess.
- Two rows the page cannot tell apart: the Billing page shows no sequence column (the vendor
  tool shows none either) — a pair reads as two identical bill dates, which is what the meter
  has.
- The contract version bump costs the server team a change; until it lands, a version-1 server
  would collapse each pair onto one row.

## Alternatives rejected

- **Keep the key, explain the six rows to the customer** (my recommendation): the customer
  measures us against the vendor tool, and a row we cannot show is a row they cannot audit.
- **Store both only when values differ**: gives eleven, not thirteen.
- **Key on the buffer position**: not stable across reads.
- **Auto id as the only key**: duplicates on every read; see Decision.
