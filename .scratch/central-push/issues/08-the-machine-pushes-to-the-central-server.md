# 08: The machine pushes to the central server every cycle

**What to build:** A machine with a URL and a Push Token configured sends its meter roster,
billing periods, Energy Summary and load profile to the team's server every fifteen minutes. Each
cycle starts by asking the server what it already holds and sends only what is missing or has
changed, so a machine that was offline catches up on its own, and a machine whose server is down
simply tries again next cycle. The API page shows how the last cycle went. Decision record: ADR
0024; spec: `.scratch/central-push/spec.md` (Central Push and Contract version 1).

**Blocked by:** 01 (Energy Summary rows with `updated_at`), 07 (settings, payload models, status
endpoint and page)

**Status:** ready-for-agent

- [ ] A push job is registered **last**, after the Database Destination sync, every fifteen
      minutes
- [ ] **Opt-out**: with no URL configured, the cycle makes no request at all
- [ ] Requests use the standard library's `urllib`, carry `Authorization: Bearer <Push Token>`,
      and have explicit connect and read timeouts. The whole cycle runs within a per-cycle time
      budget
- [ ] **The cycle, in order**:
  1. ask the server what it holds (`GET /v1/holdings`)
  2. send the meter roster as a full snapshot
  3. send billing rows, the Open Period included with `is_open`, whose `updated_at` is newer than
     the server's newest for that Meter Serial
  4. send Energy Summary rows the same way
  5. send load-profile rows newer than the server's newest `read_at` for that Meter Serial and
     logger, rewound by a small safety margin

  Every push goes through `POST /v1/push`, with items capped per request
- [ ] **Licensed kinds only**: billing is sent only under `billing`, load profile only under
      `load_profile`, the Energy Summary only under `energy_summary`. The roster is always sent
- [ ] Rows whose device has no known Meter Serial are not sent, and are counted
- [ ] An unreachable server, a timeout or a non-2xx response ends the cycle as **skipped**. There
      is no retry within the cycle
- [ ] Status — ran at, outcome, rows sent per kind, rows skipped for lack of a Meter Serial, error
      class — lives in memory, resets on restart, and appears through ticket 07's status endpoint
      and page
- [ ] **A fake receiver** is built for the tests: an HTTP server run in-process on an ephemeral
      port, implementing contract version 1 — it verifies the Push Token against a test public
      key, answers holdings from what it has stored, upserts on the spec's natural keys, and
      records every item. Tests assert only on what the receiver holds
- [ ] **First and second cycles**: the first sends everything; the second, with nothing changed,
      sends only the roster
- [ ] **Changed rows are re-sent**: a changed Open Period, and an Energy Summary day moved by a
      Holiday change plus a recompute
- [ ] **Catch-up**: a receiver that lost its data gets everything back on the next cycle
- [ ] **Failure**: a closed port ends the cycle skipped, with status recorded. A receiver that
      stalls is abandoned within the time budget
- [ ] **Values on the wire**: every instant carries a UTC offset, `local_date` is a plain date,
      and energy is in kWh whatever the display unit setting says
- [ ] Every test above is mutation-probed: reverting the behaviour it names turns it red
- [ ] `CLAUDE.md`'s digest for ADR 0024 stops saying "not yet implemented", and its Invariants line
      about the central-server push stops calling it unbuilt
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/`;
      `pnpm lint` + `pnpm build` in `web/` if the page changes
- [ ] No real-meter read is required: no driver changes

**Before this ships**: give the receiving team the contract from the API page. The first real
cycle needs both of their endpoints — push and holdings — to exist.
