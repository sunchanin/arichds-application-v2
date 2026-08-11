# 002 — `GET /api/energy/registers` returns every stored snapshot, unpaginated

Raised as a nit during the review of issue #28 (M7-1) and deliberately **not** fixed there: the
reviewer ruled the skip sound but ordered it filed, because this repo has already watched a
documented defect with no ticket sit unfixed for weeks (`docs/meter-notes/smw110w4-scan.md`'s
password finding).

## What

`GET /api/energy/registers?device_id=…` returns **every** `energy_register_readings` row for the
device, with no `limit`, no `offset` and no `total`. Its only consumer,
`web/src/pages/EnergySummary.tsx`, takes `rows[0]` — the newest snapshot — and discards the rest.

Every other row endpoint in this codebase paginates server-side. Load Profile does
(`SPEC.md` §3.5: *"ตารางแบ่งหน้าฝั่งเซิร์ฟเวอร์เสมอ"*), Billing does, Records bounds its span to
31 days. This one does not, for no reason other than that nothing forced the question at M7-1.

## Why it is not urgent

The table grows **one row per human pressing Read now** on the Meter Registers tab. There is no
scheduler job behind it (ADR-level decision at M7: energy registers are button-triggered only),
so growth is paced by a person clicking. A site would need thousands of deliberate presses
before the payload became uncomfortable.

That is why it was left out of an otherwise-approved diff rather than reopened: a correct fix
touches the response contract (adding `total`), `web/src/api.ts`, and the existing tests, which
is disproportionate to the risk inside a review round.

## Fix direction (either is acceptable)

- **Paginate** — `limit` / `offset` / `total`, matching `/api/billing`'s shape, or
- **Narrow it** — replace with `/api/energy/registers/latest` returning the single newest
  snapshot, which is all the page has ever wanted.

The second is smaller and matches the actual need; the first keeps the door open for a history
view that nobody has asked for. Pick one and say why in the commit.

## Acceptance criteria

- [ ] The endpoint cannot return an unbounded row set
- [ ] `EnergySummary.tsx` consumes whichever shape is chosen without a client-side slice
- [ ] Existing `tests/test_api_energy.py` cases updated, not weakened — a test that stopped
      asserting on the returned rows would hide the change rather than cover it
- [ ] `ruff format --check` + `ruff check` + `pytest -n auto` (full suite) + `pnpm lint` + `pnpm build`
