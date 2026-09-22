# 03: The Central Push carries sequence — contract version 2

**What to build:** The team's server receives a same-second pair as two rows. The billing item on
the wire gains `sequence`, the billing natural key the server upserts on becomes
`(meter_serial, bill_date, sequence)`, and the contract version published on the API page reads
**2** with one sentence saying what changed and why a version-1 server would collapse a pair. A
machine that re-pushes after *Delete all data* or a reinstall creates no duplicates, because the
key is the meter's, not this machine's. Holdings, watermarks, the roster, load profile and energy
summary are unchanged. Decision record: ADR 0029 (key), ADR 0024 (no state, natural keys, own
versioned contract); spec: `.scratch/billing-sequence/spec.md`; glossary: CONTEXT.md → *Central
Push*, *Billing Sequence*.

**Blocked by:** 01 (ARICHDS holds every closed period the meter holds, oldest first)

**Status:** done — 2026-09-22 (commit follows the full gate; cycle 61 passed incl. the pair, the reset re-push and the other kinds unchanged)

- [ ] The billing item model carries `sequence` (integer, ≥ 0); because the item's measurement
      columns are built by walking the ORM model, confirm `sequence` is placed deliberately beside
      `bill_date` in the rendered contract rather than falling among the measurements
- [ ] The published natural key for billing is `(meter_serial, bill_date, sequence)`;
      `CONTRACT_VERSION` is 2; the API page's rendered contract states the version, the new key
      and the one-line reason (a version-1 server upserting on two columns collapses a pair)
- [ ] The fake receiver (`fake_central_push_receiver.py`) upserts billing on the three-column key
      and reports version 2 in its holdings; a cycle pushing a pair leaves two rows on it; deleting
      the device's rows, re-reading the same buffer and pushing again leaves the same two rows,
      never four (`test_central_push_cycle.py`)
- [ ] A test asserts the roster, load-profile and energy-summary items and the holdings request
      are byte-identical to version 1 (recorded request comparison), so the bump changes billing
      alone
- [ ] Docs in the same change: CLAUDE.md's ADR 0024 digest records version 2 and the key; a short
      note for the server team (what to add, what to key on) is written into the API page's
      contract text itself, not a separate document
- [ ] Gate: `ruff format --check`, `ruff check`, `pytest -n auto` (app); `pnpm lint`, `pnpm build`
      (web) if the API page changed
