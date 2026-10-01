# 06: Holiday changes are recorded, and the page says the summary will be recalculated

**What to build:** Every change to the Holiday calendar is recorded with who made it, when, and
which day it names, so anyone looking at a past day whose numbers moved can find out why. After a
change, the Holidays page says the Energy Summary will be recalculated within fifteen minutes. That
notice replaces the M13 warning telling operators their energy files may be stale and asking them
to press **Save to file**, which stops being true once ticket 04 lands. Decision record: ADR 0022;
spec: `.scratch/central-push/spec.md`.

**Blocked by:** 01 (the Energy Summary recomputes, so the notice is true), 04 (the Energy file is
rewritten every cycle, so removing the stale-file warning does not leave a stale file unmentioned)

**Status:** ready-for-agent

- [ ] A migration creates `holiday_changes`: when (UTC), who (the signed-in user's username),
      the action — `add`, `edit`, `delete`, `import_csv` or `import_meter` — plus the Holiday's
      kind, name and day (a date, or a month and day) for the three single-Holiday actions, and a
      count for the two imports
- [ ] **All five mutation endpoints record exactly one change**, in the same transaction as the
      mutation itself: create, update, delete, CSV import, and Import from meter. A mutation the
      API refuses — a colliding Holiday, a 29 February annual Holiday — records nothing
- [ ] **One record per import**, carrying its source and how many Holidays it brought in — not
      one record per imported Holiday
- [ ] Each change also writes one App Log line naming the action, the user and the day or count
- [ ] A read endpoint under the Holidays API returns the changes newest first. Any signed-in role
      may read it, under the same `energy_summary` licence gate the Holidays API already carries
- [ ] Retention deletes changes older than `RETENTION_DAYS`
- [ ] The Holiday mutation responses drop `affected_date` and `energy_files_written_past`, and the
      helpers that computed them are removed with nothing left referring to them
- [ ] Web, Holidays page: after any change, a notice that the Energy Summary will be recalculated
      within fifteen minutes replaces the stale-energy-file warning; a view lists the Holiday
      Change record. English only
- [ ] **Tests, one per path**: each of the five mutations produces exactly one record with the
      right action, user and day or count, readable by a non-admin; a refused mutation produces
      none
- [ ] Every test above is mutation-probed: reverting the behaviour it names turns it red
- [ ] `CLAUDE.md`'s digest for ADR 0022 records that the Holiday Change record has landed
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/`;
      `pnpm lint` + `pnpm build` in `web/`
- [ ] No real-meter read is required: no driver changes
