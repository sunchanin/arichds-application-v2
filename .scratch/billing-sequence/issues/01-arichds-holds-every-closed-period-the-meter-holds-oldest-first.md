# 01: ARICHDS holds every closed period the meter holds, oldest first

**What to build:** A meter that stamps two closed periods on the same second — site TC's Prometer
100 does it six times, *Invocation of Scaling tariff*, one pair being `31.18` / `3118.25` kWh and
two pairs identical in every column — ends up with **every** period stored, keyed by Bill Date
**and Billing Sequence** (`0` for the newest of a same-second group, `1` for the next). Reading
the buffer again stores nothing new; a re-read with different values under a stored key is still
skipped with today's warning. The Billing page lists periods **oldest first** — the exact reverse of
the meter's own listing, so within a pair sequence 1 comes before 0; page one is the newest periods —
shows no sequence column, highlights exactly one "latest bill" when the newest bill date is a
pair, and the All-Meters View still shows one row per device. The Billing Export File and the
Database Destination's billing table both carry `sequence` immediately after `bill_date`. On the
TC database, the first whole-buffer read after this lands turns seven closed rows into thirteen
with nobody pressing anything. Decision record: ADR 0029; spec:
`.scratch/billing-sequence/spec.md`; glossary: CONTEXT.md → *Bill Date*, *Billing Sequence*,
*All-Meters View*, *Billing Export File*.

**Blocked by:** None (can start immediately)

**Status:** done — commit `20d7933`, 2026-09-22 (full gate 2546 passed; MariaDB 79 passed; four mutation probes each red one named test)

- [ ] Migration: `billing_readings.sequence` (integer, not null, default `0`); the closed-period
      partial unique index is rebuilt as `(device_id, bill_date, sequence) WHERE record_status IS
      NULL`; the Open Period index is untouched. The migration test reads the index back from
      SQLite (`PRAGMA index_list` / `index_info`, the memory *schema assertions must read back from
      the server*) and shows an existing closed row answering `sequence = 0` after upgrade
- [ ] Sequence is assigned in the **store**, from the order the driver already hands closed
      periods over in (newest entry first) — no driver changes, no branch on model; every one of
      the nine drivers' billing tests stays green untouched
- [ ] Through `fake_meter` (`test_billing_job.py` shape): a thirteen-entry buffer with six
      same-second pairs (one pair differing in values, one identical in every column, the rest
      as TC has them) stores thirteen closed rows; the identical pair is two rows; a second read of
      the same buffer stores nothing and logs no skip; the same buffer minus the *older* member of
      one pair leaves every stored key unchanged; a re-read whose values differ under a stored key
      is skipped with the existing *already stored with a different value* warning. **Each is a
      mutation the test would catch**: counting from the oldest instead of the newest, keying on
      two columns instead of three, and skipping identical pairs must each turn a named test red
- [ ] The Open Period is untouched: one slot per device, `bill_date` = read time, overwritten in
      place — an existing test proves it still, unchanged
- [ ] `GET` billing (TestClient): a page reads `bill_date ASC, sequence DESC` and page one holds the
      newest periods (selection newest first, each page reversed); a pair is two rows with
      one bill date; the All-Meters View returns one row per device when that device's newest
      closed bill date is a pair (the `MAX(bill_date)` join takes `sequence = 0`) — a test with a
      pair as the newest period would return two rows without the fix
- [ ] Billing page: the default sort is oldest first; no sequence column is added; the "latest
      bill" highlight resolves a tie on equal bill dates to `sequence = 0` (one highlighted row,
      never two) — proven with the *React renders outside the browser* method or an equivalent
      pure-function test on the highlight helper
- [ ] Billing Export File: header and rows carry `sequence` right after `bill_date`; a pair is two
      lines; `record_no` still runs oldest first; the file is rewritten whole so the head change
      needs no special handling (`test_billing_csv_export.py`)
- [ ] Database Destination: `sequence` after `bill_date` in the billing table, `NOT NULL DEFAULT
      0`, created on a fresh table and added `AFTER bill_date` on a 0.7.7-shaped table by the
      existing reconcile; a pair arrives as two rows (`test_dataout_mysql.py`, run by hand with
      `ARICHDS_TEST_MYSQL_URL`, output line in the evidence)
- [ ] Billing Change Check (ADR 0018) is untouched — its existing tests pass with no edit
- [ ] Docs in the same change: SPEC.md §3.6 names the key and the order; CLAUDE.md's ADR 0029
      digest drops "decided, not implemented" for the parts this ticket lands; the store's module
      docstring no longer says "dedupe on `(device_id, bill_date)`"
- [ ] Gate: `ruff format --check`, `ruff check`, `pytest -n auto` (app); `pnpm lint`, `pnpm build`
      (web)
