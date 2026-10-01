# 003 — the CSV export lock test pins that a lock exists, not that it covers the whole critical section

Raised as a non-blocking nit while reviewing issue #30 (M7-3) and filed rather than fixed in
that round, on the same rule this repo learned the hard way: a defect recorded only in prose has
no enforcement.

## What

`app/tests/test_csv_export.py::TestPerDeviceLock` counts concurrent entries into the patched
`_append_rows` — the innermost operation. That correctly catches "the per-device lock was
deleted", which is what it was rewritten to catch.

It does **not** catch "the lock was narrowed". The reviewer moved the lock so it wrapped only
`_append_rows`, leaving the query-and-format section outside it, and the test stayed **green**.

Under that arrangement two concurrent exports of one device — the scheduler cycle and a
"Save CSV now" pressed at the wrong moment — would both select the same pending rows, both
format them, and both append them. **Duplicate rows in the customer's append-only contract
file**, which nothing downstream would flag.

## Not a defect in the shipped code

`export_device` holds the lock across the whole read-format-write sequence today, which is
correct. This ticket is about the test, and about the fact that the correct arrangement is
currently unpinned: the next person who moves the lock inward for a plausible reason ("the query
does not need to be serialised") gets a green suite.

## Fix direction (either)

- **Move the counter outward** — count entries at the top of `_export_device_locked` rather than
  inside the patched writer. One line, and it makes the assertion about the section rather than
  the operation.
- **Or add a second test** running two genuinely concurrent `export_device` calls on one device
  and asserting the resulting file contains no duplicated `read_at`. Slower, but it asserts the
  outcome the lock exists to produce rather than the mechanism.

The first is cheaper; the second is the one that survives a refactor that replaces the lock with
something else entirely.

## Acceptance criteria

- [ ] Narrowing the lock to cover only the write makes a test fail
- [ ] Deleting the lock entirely still makes a test fail (do not lose what #30 gained)
- [ ] Both proven by mutation, restored and hash-verified
- [ ] `ruff format --check` + `ruff check` + `pytest -n auto` (full suite)
