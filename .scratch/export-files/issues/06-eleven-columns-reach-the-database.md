# 06: The eleven requested quantities stop being discarded

**What to build:** the three average phase angles, the interval status word, the four
average power quantities and the three line-to-line voltages are stored with every Interval
Reading. Every one of them is already inside a buffer the product reads off the meter every
cycle and throws away for want of a field — this ticket gives those rows somewhere to put
them. Nothing an operator sees changes yet; ticket 07 carries them to the file and the
screen.

**Blocked by:** 05 (which is blocked by 04 — this ticket edits the same declarations both
of those touch, and wants their diffs separate from its own).

**Status:** ready-for-agent

Source: `.scratch/export-files/spec.md`. Requirements A1/A2.

## Storage

- [ ] Eleven new nullable columns on the Interval Reading, plus one migration.
- [ ] The interval status column is named for the product term, **Interval Status**, not
      for the customer's file header. The glossary already separates that term from
      **Records**, and the Billing Reading already owns a differently-meaning column of the
      header's name.
- [ ] The status word is stored as **the raw integer**, decoded at render time. Its bit
      meanings are settled for one meter family and unverified for another; storing decoded
      text would make every historical row permanently un-decodable on the day the second
      family is finally verified. This is also what v1 does.

## Driver mapping — from real scans, per family

- [ ] **Prometer 100** — all eleven.
- [ ] **Premier 550** — the interval status word only.
- [ ] **Saral 305** — none. The meter records none of them.
- [ ] **SMART TCC** — the three phase angles, which it captures at a different address than
      CEWE does. Its status word is a different object whose bit meanings nobody has
      verified on hardware, and v1 deliberately refused to map it. **It stays unmapped.**
- [ ] The SMART TCC mapping comes from the July scan and **cannot be verified now** — that
      meter answers on neither port. Record in the code that these three are not
      hardware-verified, and how to verify them when the meter is reachable. Do not let this
      ticket's acceptance imply they were checked.

## Scaler sources — measured, read-only, 2026-09-09

Every own-address scaler read was denied on all twelve targets, so the sibling is the only
path on this family. That matches the 2026-08-09 billing scan; do not spend a probe
rediscovering it.

- [ ] Phase angles, line-to-line voltages and the two **import** power columns resolve
      through their D=7 sibling.
- [ ] The two **export** power columns do not — their D=7 siblings are denied. They resolve
      from the maximum-demand export registers, read as an **Extended Register**. Same
      physical quantity, same unit, different statistic; the billing path already borrows
      across addresses this way, and ADR 0002 is satisfied because the scaler is read rather
      than assumed.
- [ ] The interval status word offers no scaler and is a passthrough column.

## The failure mode to design against

**Every scaler on the reference meter is 1.0.** A scaler that fails to resolve does not
produce a wrong magnitude — it produces nothing. So a mistake in this ticket will not look
like a wrong number. It will look like a meter with no data, which is precisely what ticket
05's defect looked like for 87,000 rows.

- [ ] A column whose scaler resolves to nothing stores nothing, never a raw count. Assert
      this; do not merely rely on it.

## Gate

- [ ] `ruff format --check` and `ruff check` pass.
- [ ] `pytest -n auto` passes.
- [ ] Driver tests: given a buffer carrying the full capture list, the eleven fields land in
      the right places and the scaler candidates are tried in declared order.
- [ ] **A real meter read, by hand**: a development Prometer 100, all eleven columns
      non-NULL in the database, values attached to this ticket.
- [ ] **A cross-quantity check, by hand**: average export power over an interval, times the
      interval length, against the export energy stored for that same interval. Because
      every scaler here is 1.0, a wrongly borrowed scaler yields a plausible number rather
      than a blank — and comparing a stored value against the register it came from would
      prove only that it was copied faithfully.
- [ ] **No extra meter read, poll or row.** Confirm the cycle asks the meter for exactly
      what it asked for before.
- [ ] Record in this ticket that the new columns will reach any configured **Database
      Destination automatically** on the next sync, because the destination derives its
      schema from ours and reconciles by adding what is missing. That is designed behaviour
      with a precedent, and it is still a schema change fired into a customer's own database.
