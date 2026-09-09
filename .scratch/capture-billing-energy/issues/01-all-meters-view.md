# 01: All-Meters View — every meter's latest bill on one screen

**What to build:** An operator opens the Billing page, clicks a third tab called **All
Meters**, and sees every meter in the system — one row each, carrying that meter's latest
closed Billing Reading. Rows that need attention sort to the top with a chip saying what is
wrong, and the tab header carries a count of how many need attention, so the operator knows
whether to open the tab at all.

A meter that has never produced a bill appears too, which is the case the current Billing
page hides best. A meter that has stopped answering says so rather than looking merely
stale. A paused meter says it is paused rather than reporting as broken.

Each row shows when its latest period was captured, so the documents handed to a customer
can be confirmed for the whole fleet in one look. Clicking a row opens that meter's full
history, which is what keeps the table narrow enough to scan.

Nothing on the tab contradicts what it shows: the device picker, the date range and the
per-meter capture control are not there.

Source: `../spec.md`. The decisions behind each choice are in `docs/REMAKE-PLAN.md` §7.3;
the customer's own notes are in `../requirements.md`. Glossary terms **All-Meters View**,
**Bill Date**, **Open Period**, **Capture**, **Pause** are in `CONTEXT.md`.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] A third tab, **All Meters**, sits beside History and Current on the Billing page
- [ ] It lists **one row per device**, carrying that device's **latest closed** Billing
      Reading, with **no date filter**
- [ ] A device with **no Billing Reading at all** appears, with an empty Bill Date and a
      never-billed status — the row set comes from devices, not from the readings
- [ ] The **Open Period never appears**, even when it is that device's newest row
- [ ] Status is **one chip per row, resolved server-side**, with the precedence
      `Paused` › `Not answering` › (`Never billed` | `Behind`) › `OK`, each chip carrying
      its own number
- [ ] **Behind** means the latest closed Bill Date is older than a **named 35-day
      constant** in the backend constants module — a Bill Date just inside the threshold is
      `OK`, just outside it is `Behind`
- [ ] A device that is **both unreachable and behind reports unreachable** — cause outranks
      symptom
- [ ] A **paused** device reports paused and is **excluded from the count**
- [ ] The **tab header carries a count** of rows that are neither `OK` nor `Paused`
- [ ] Rows **sort worst status first, then device name** — proven with at least **three
      rows in three distinct statuses**, because two rows leave several wrong orderings
      indistinguishable from the right one
- [ ] Each row shows **when its latest closed period was captured**, sourced from the
      reading's **existing read time** — no new column, no migration. The column is
      **always present and blank** when captures are switched off
- [ ] **Clicking a row** opens that device's History
- [ ] The **device picker, date range and per-meter capture control are hidden** on this
      tab — hidden, not disabled
- [ ] The query is a **reusable function in the database layer**, callable without HTTP, so
      the planned billing export calls it directly rather than reimplementing it. Follow the
      existing per-domain query module precedent rather than inventing a new shape
- [ ] The endpoint is a **new one**, not a new mode on the existing billing list endpoint,
      and is gated by the **existing billing entitlement** and readable by **any
      authenticated role**
- [ ] Tests sit at the **existing HTTP seam** through the shared test-client fixtures — no
      new seam. Prior art is the existing billing API test module
- [ ] Write into the implementation the assumption the 35-day threshold rests on: **no
      customer runs a billing cycle longer than a month.** If a quarterly cycle ever
      appears, this constant is where it breaks
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `python -m pytest -n auto` in
      `app/`; `pnpm lint` + `pnpm build` in `web/`. The **full** suite, never a subset
- [ ] **Output Parity vs v1**: not applicable — v1 has no equivalent of this screen's status
      derivation, and the underlying numbers are already-parity-checked Billing Readings.
      Say so in the report
- [ ] **Real-meter read**: not applicable, nothing here touches acquisition. Say so
