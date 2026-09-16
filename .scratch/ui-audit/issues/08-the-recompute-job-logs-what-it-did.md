# 08: The recompute job logs what it did

**What to build:** Every `energy_summary_recompute` cycle writes one INFO line to the App
Log, the way `dbdest_sync`, `retention` and `backup` already do: how many devices it walked,
how many stored days it upserted, how many it deleted, and how long it took. Today the job
is silent, so the only way to prove it ran is to watch `updated_at` in the database — which
is what it took to verify ADR 0022 on the dev machine, and what support will have no answer
for when a customer asks why a number has not changed yet.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] One INFO line per cycle, always — including a cycle that changed nothing ("… 0 day(s)
      upserted, 0 deleted …"), because silence is what this ticket removes. Test: a cycle
      with no changes emits exactly one line carrying `0`. Mutation probe: skipping the log
      on a no-change cycle turns it red.
- [ ] The counts are the ones the recompute already computes (changed days written,
      stale days deleted) — no extra query is added to produce them.
- [ ] The line passes through the credential redaction filter like every other log record
      and names no meter password or path.
- [ ] Gate: `ruff format --check .` + `ruff check .` + `pytest -n auto` green in `app/`.
