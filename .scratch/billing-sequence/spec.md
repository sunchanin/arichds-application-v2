# Spec — Billing Sequence: every closed period the meter holds is stored

**Status:** ready-for-agent · grilled 2026-09-22 (6 questions, 3 rounds) · owner decisions
recorded inline · ADR 0029 accompanies this spec · glossary: CONTEXT.md → *Bill Date*, *Billing
Sequence*, *Open Period*, *All-Meters View*, *Billing Export File*, *Capture*. Tracker: local
(`.scratch/billing-sequence/issues/` once `/to-tickets` runs); no GitHub issue. **Blocks**
`.scratch/capture-style/` (its images draw the rows this spec keys and orders).

## Problem Statement

Site TC's meter holds thirteen closed billing periods. The vendor's own tool lists all thirteen;
ARICHDS lists seven, and the customer said the two do not match. They are right: the meter
stamps its commissioning resets in pairs on the same second, and ARICHDS keeps one row per bill
date — the second of each pair is skipped with a warning nobody at the site reads. A row the
customer can see in the vendor tool and not in ARICHDS is a row they cannot audit.

## Solution

ARICHDS stores every closed period the meter holds — a same-second pair is two rows, even when
the two are identical in every column — by keying a closed period on its bill date **and its
Billing Sequence** (`0` for the newest of a same-second group, `1` for the next). Reading the
buffer again still stores nothing new. Everywhere a person reads periods they now run **oldest
first**, as the customer asked. The pair reaches every output: the Billing page, both capture
documents (the second with a `_2` suffix, so no existing file is renamed), the Billing Export
File, the Database Destination and the Central Push (contract version 2). At TC the six missing
rows arrive on the first whole-buffer read of the new build, with no manual step.

## User Stories

1. As the customer, I want ARICHDS to list the same closed periods my meter's vendor tool lists,
   so that I can audit one against the other.
2. As the customer, I want two periods the meter stamped on the same second to be two rows, so
   that a scaling reset that froze the register before and after the change shows both values.
3. As the customer, I want a same-second pair that is identical in every column to still be two
   rows, so that the count matches the meter's and not a rule of ARICHDS's own.
4. As an operator, I want a re-read of the buffer — the daily backstop, a change-triggered read,
   a Read now — to store nothing already stored, so that thirteen rows stay thirteen.
5. As an operator, I want a re-read that finds different values under a key already stored to
   skip it with the same warning as today, so that stored history is never rewritten.
6. As an operator, I want the meter dropping its oldest entry to leave every stored key valid,
   so that a pair losing its older member does not renumber the younger one.
7. As an operator, I want the Billing page to list periods **oldest first**, then by sequence,
   so that the screen reads the way the customer asked to read it.
8. As an operator, I want the Billing page to show no sequence column, so that the page looks
   as the vendor tool does — a pair is two rows with one bill date.
9. As an operator, I want the "latest bill" highlight on the Billing page to pick exactly one
   row when the newest bill date is a pair, so that the highlight never doubles.
10. As an operator, I want the All-Meters View to show one row per device when its newest
    closed period is a pair, so that a device is never listed twice.
11. As an operator, I want the Open Period untouched by all this — one slot, overwritten in
    place, `record_status = 'open'` — so that the Current tab behaves exactly as before.
12. As an operator, I want every period of a pair to get its own PDF and xlsx, the second one
    named with a `_2` suffix on the same stem, so that both are documents I can hand over.
13. As an operator, I want a period that is alone on its bill date to keep today's unsuffixed
    filename, so that no file already handed over changes its name.
14. As an operator, I want the PNG capture's ten-period window to count a pair as two of its
    ten, oldest first, so that the image holds the same rows the page holds.
15. As an operator, I want the render-on-miss download and the Capture image button to use the
    same suffixed name, so that a download and an automatic write never disagree about a path.
16. As an operator, I want the FTP upload to carry the suffixed documents without any change to
    its configuration, so that a pair reaches the server like any other period.
17. As a downstream reader of the Billing Export File, I want a `sequence` column immediately
    after `bill_date`, so that my tooling can tell a pair apart.
18. As a downstream reader of the Billing Export File, I want the file still ordered oldest
    first with `record_no` running that way, so that nothing about its order changes.
19. As the customer's database owner, I want a `sequence` column after `bill_date` in the
    destination's billing table, added by the same reconcile that adds any other missing column,
    so that an upgrade needs no DROP.
20. As the team's server developer, I want the Central Push billing item to carry `sequence`
    and the published natural key to become `(meter_serial, bill_date, sequence)`, so that a
    pair is two rows on the server too.
21. As the team's server developer, I want the contract version to read 2 and the API page to
    say what changed, so that I know why a version-1 server would collapse a pair.
22. As the team's server developer, I want to keep my own auto-increment id but upsert on the
    natural key, so that a machine re-pushing after *Delete all data* creates no duplicates.
23. As an operator at a running site, I want the upgrade to keep every existing row and its
    key, so that nothing I already have moves or disappears.
24. As an operator at TC, I want the six skipped periods to appear after the first read on the
    new build, so that I do not have to press anything or delete anything.
25. As an operator, I want *Delete all data* followed by a read to bring back all thirteen, so
    that the repair tool ADR 0009 describes still works.
26. As a developer, I want the sequence assigned in one place that every meter model shares, so
    that no driver has to know about it and no `if` on model appears.
27. As a developer, I want the Billing Change Check untouched, so that the fifteen-minute
    trigger keeps comparing the newest closed bill date and nothing else.
28. As the owner, I want the migration to be one column with default `0` plus the rebuilt
    partial index, read back from SQLite to prove it exists, so that a green Python-side
    assertion cannot hide a missing index.

## Implementation Decisions

**The key.**
- `billing_readings` gains `sequence` (integer, not null, default `0`). The partial unique index
  over closed periods becomes `(device_id, bill_date, sequence) WHERE record_status IS NULL`.
  The Open Period's partial index is unchanged. One migration: add the column, drop and recreate
  the closed index, under the existing batch-mode setup.
- **Sequence is assigned in the store, not the driver.** The whole-buffer read hands the store
  the closed periods in the meter's own order (newest entry first, as every driver declares
  today); the store walks them, counts equal bill dates within that order from `0`, and stores
  the count. Every model gets it for free, the driver contract does not change, and there is no
  branch on model. The fake meter's billing buffer already replays entries in order, so the
  seam is the store call the existing job tests drive.
- Dedup keeps ADR 0009's three outcomes, keyed on the three columns: absent → insert; present
  with different values → skip and WARN (message unchanged); present and equal → nothing.
- The Open Period is untouched: still one slot per device, still `bill_date = read time`.

**Order.**
- The Billing page's listing endpoint orders `bill_date ASC, sequence ASC` (per device, the
  device ordering it already has). The page's "latest bill" highlight ties on equal bill dates
  and takes `sequence = 0`. The PNG window query keeps its "same device and serial, closed,
  `bill_date <=` anchor" selection and orders the same way on the page; the renderer's expected
  row-id list is built in that order.
- The All-Meters View's newest-per-device join adds `sequence = 0` to the equality, so a device
  whose newest bill date is a pair still yields one row.
- The Billing Export File is already oldest first; `record_no` keeps running that way.

**Capture documents.**
- The one filename-stem function takes the sequence and appends `_<sequence + 1>` only when
  `sequence > 0`. The three formats keep sharing the stem (ADR 0015). The FTP upload lists the
  capture folder and needs no change — proven by a test, not assumed.

**Data-out.**
- Billing Export File: a `sequence` column placed right after `bill_date`, in both the header
  and every row; the file is rewritten whole every cycle (ADR 0023), so the head change is
  absorbed.
- Database Destination: `sequence` after `bill_date` in the billing table, added `AFTER` by the
  existing reconcile; the billing table is replaced wholesale each cycle and its index is not
  unique, so nothing else changes.
- Central Push: `sequence` on the billing item, the billing natural key becomes
  `(meter_serial, bill_date, sequence)`, `CONTRACT_VERSION` becomes 2, the published contract
  names the change; the fake receiver upserts on the new key. Holdings and watermarks are
  unchanged (billing is pushed by `updated_at`).

**Documents.**
- ADR 0029 (written), CONTEXT.md *Bill Date* / *Billing Sequence* (written), CLAUDE.md digest
  (written, marked "decided, not implemented" — flip when it lands). SPEC.md §3.6 gains the key
  and the order. `installer/arichds.iss` `AppVersion` bumps for the build that ships it.

## Testing Decisions

A good test here seeds a buffer the way the meter actually writes one — pairs on the same
second, one pair differing, one identical — drives the shipped entry point, and asserts on the
rows, the file names, the JSON or the bytes a person or a server would see; never on how the
count was computed.

- **Store** (`test_billing_job.py` shape, `fake_meter`): a buffer of thirteen with six pairs
  stores thirteen; a second read stores nothing and warns nothing; the same buffer with the
  oldest member of a pair dropped leaves every stored key intact; different values under a
  stored key → skipped with the existing warning; an Open Period row is still one slot. Each
  as a mutation: swapping the counting direction, or keying on two columns, must turn a test
  red (the memory *write required tests as mutations, not scenarios*).
- **Migration** (`test_migration_00NN.py` prior art): existing rows read back with `sequence =
  0`; the rebuilt index is listed by `PRAGMA index_list` with the three columns and its `WHERE`.
- **API** (`test_api_billing.py`, `test_api_billing_all_meters.py`, TestClient): order is
  `bill_date ASC, sequence ASC`; a pair is two rows with one bill date; All-Meters View returns
  one row per device when the newest period is a pair; the image endpoint's ten-row window
  counts the pair as two.
- **Capture** (`test_capture_paths.py`, `test_capture_service.py`): `sequence = 0` → today's
  stem byte-for-byte; `sequence = 1` → `_2`; both documents written for a pair; the render-on-miss
  download resolves the same suffixed path. **FTP** (`test_fileupload_cycle.py` shape): a
  suffixed document is uploaded like any other.
- **Export** (`test_billing_csv_export.py`): header has `sequence` after `bill_date`; a pair is
  two lines; `record_no` still oldest first.
- **Database Destination** (`test_dataout_mysql.py`, opt-in): the column exists after
  `bill_date` on a fresh table and is added `AFTER bill_date` on a 0.7.7 table; a pair is two
  rows.
- **Central Push** (`test_central_push_cycle.py`, fake receiver): version 2 on the wire; a
  pair lands as two rows; a re-push after the rows are deleted and re-read yields the same two,
  not four.
- **Web**: `pnpm lint && pnpm build`; the highlight tie-break proven with the *React renders
  outside the browser* method if a reviewer asks.
- Gate: `ruff format --check` + `ruff check` + `pytest -n auto` (app), `pnpm lint` + `pnpm build`
  (web); the MySQL file run by hand with `ARICHDS_TEST_MYSQL_URL`.

## Out of Scope

- Any change to how the Open Period is found or stored (reset-reason cell, one slot).
- A sequence column on the Billing page or in either capture image.
- Reading a narrower buffer than the whole (ADR 0009 stands).
- Interpreting *Cause of Billing* — not stored today, not stored by this spec.
- Renaming or rewriting any existing capture document.
- The server team's own implementation of contract version 2 (their side).

## Further Notes

- The evidence: TC's `arichds.db` copy on the owner's desktop (7 closed rows, one Open Period)
  against the customer's ConfigView screenshots of 2026-09-22 (History 1–13, *Invocation of
  Scaling tariff* on every one), and TC's log (`already stored with a different value — skipping`
  ×4 per read: 09-19 08:59:50Z, 08:58:40Z, 09-12 17:53:45Z, 17:42:50Z; the two 09-11 pairs
  are identical and were skipped silently).
- The `31.18` / `3118.25` pair is one register before and after a ×100 scaling — worth knowing
  when someone asks why the customer's "first bill" is 3118 kWh after a month of 31.
- Owner decisions from the grill: store every entry, identical pairs included (Q1, Q5); key by
  sequence, not an auto id — an id cannot recognise a re-read (Q1, Q3); `_2` suffix, existing
  names untouched (Q2); contract version 2 with sequence in the natural key (Q3); oldest first
  everywhere a person looks, including the Standard capture image (Q6).
- My own recommendation was to keep the key and explain the six rows; the owner chose the
  customer's yardstick. Recorded, not to be reopened by me.
