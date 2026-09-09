# Spec — All-Meters View (Billing)

**Produced by** `/to-spec` on 2026-09-09, from the `/grill-with-docs` round recorded in
`docs/REMAKE-PLAN.md` §7.3 · **Source brief**: `requirements.md` in this folder ·
**Glossary**: `CONTEXT.md` — All-Meters View, Interval Status
**Tracker**: local — tickets live in `issues/` beside this file, the per-feature form
`/run-issue` and `/run-batch` accept directly (CLAUDE.md). Not published to GitHub.

---

## Problem Statement

An operator running a site full of meters cannot answer the one question they ask every month: **did every meter cut its bill, and which one needs attention?**

The Billing page shows one meter at a time across its periods. To check twenty meters, the operator selects each in turn and reads a forty-column table twenty times. Nothing anywhere shows the fleet at once.

Two failures are invisible today:

- A meter that **stopped answering** does not appear as a problem on any screen. The system has counted its consecutive failures since ADR 0004 and uses them to drive the offline threshold, but no page shows the number and no API returns it.
- A meter that has **never produced a Billing Reading at all** — newly added, or never successfully read — is absent from the Billing page entirely, because there is nothing to list. The worst case is the one the current design hides best.

The customer described this gap three separate ways in one workbook (`.scratch/capture-billing-energy/`, notes AF10, AF17–AF18, F60): "let me click and see which ones did not get pulled", "show all the bill cuts, ignoring the billing cycle", and "I want the old style" — v1's Billing screen, which listed one row per meter. Three descriptions of one missing screen.

## Solution

A third tab on the Billing page, **All Meters**, beside History and Current.

One row per device carrying that device's **latest closed** Billing Reading, with no date filter. A **Status** column says at a glance which meters need attention and why, and a counter on the tab header says how many. A **capture time** column answers "was this period captured?" for the whole fleet in one look.

The tab answers one question and is shaped for it: a narrow table, not the forty columns History shows for one meter over time. Clicking a row takes the operator to that meter's History when they want the full picture.

## User Stories

1. As an operator, I want to see every meter's latest bill on one screen, so that I can tell in one look whether the month closed cleanly.
2. As an operator, I want one row per meter rather than one row per meter per period, so that twenty meters take twenty rows rather than two hundred.
3. As an operator, I want the table to include meters that have never produced a bill at all, so that a newly added or never-read meter cannot hide by having no data.
4. As an operator, I want a Status column that names the problem, so that I do not have to infer it from a date.
5. As an operator, I want a meter that has stopped answering to say so, so that I chase the connection rather than the billing cycle.
6. As an operator, I want a meter whose latest bill is old to say so, so that I notice a meter that quietly stopped cutting.
7. As an operator, I want to see the cause rather than the symptom when a meter is both unreachable and behind, so that one row tells me one thing to do.
8. As an operator, I want a paused meter to be marked as paused rather than as broken, so that a deliberate decision is not reported as a fault.
9. As an operator, I want a paused meter left out of the attention count, so that the count means "things to fix".
10. As an operator, I want a count of meters needing attention on the tab itself, so that I know whether to open the tab at all.
11. As an operator, I want the worst rows sorted to the top, so that the tab answers its question without scrolling.
12. As an operator, I want to click a row and land on that meter's full billing history, so that the narrow table costs me nothing when I need detail.
13. As an operator, I want to see when each meter's latest period was captured, so that I can confirm the documents I hand to a customer exist.
14. As an operator, I want the capture column present even when captures are switched off, so that the table's shape does not change under me.
15. As an operator running a Manual Read, I want the confirmation to tell me how many captures were written as well as how many periods were stored, so that I know the documents were produced and not only the rows.
16. As an operator, I do not want a device picker, a date range, or a per-meter capture button on this tab, so that no control on screen contradicts what the tab shows.
17. As an operator whose licence does not include billing, I want this tab gated exactly as the rest of the Billing page is, so that entitlement is consistent.
18. As a non-admin user, I want the same view and the same status information an admin sees, so that reading a meter's data is not an admin-only act — as it is nowhere else in this product.
19. As the owner, I want the rule that decides "behind" to live in one place in the backend, so that it cannot drift between the screen and any future exporter.
20. As the owner, I want the query behind this tab to be callable without going through HTTP, so that the billing export planned next reuses it rather than reimplementing it.
21. As the owner, I want the Open Period excluded, so that a period whose Bill Date advances on every read cannot make every meter look freshly cut.
22. As a future reader, I want the vocabulary for this screen in the glossary, so that "All-Meters View" and "Interval Status" are not reinvented under other names.

## Implementation Decisions

**The tab**

- A third tab on the Billing page, labelled **All Meters**, beside History and Current. The glossary term is **All-Meters View**; the customer's word is "Bill total", which is avoided because in English it reads as a sum of money.
- One row per device, carrying that device's **latest closed** Billing Reading.
- **No date filter.** The customer's own complaint about the prior behaviour was that it "cares about the current billing cycle" and so hid meters that cut at other times.
- **The Open Period is excluded.** Its Bill Date advances on every read (ADR 0018), so including it would make every meter look freshly cut and would destroy the staleness signal the Status column depends on. The Current tab already exists for the Open Period.

**Row set**

- The view is built over **devices**, not over Billing Readings. A meter with no Billing Reading at all still appears, with an empty Bill Date. Deriving the row set from the readings would hide precisely the case the tab exists to surface.

**Columns**

- Device · Meter Serial · Bill Date · Import Active total · Export Active total · capture time · Status.
- Deliberately narrow. History shows roughly forty columns because it is shaped for one meter across time; that shape is unreadable across every meter at once. Clicking a row navigates to History filtered to that meter.

**Status**

- One column, one chip per row, with a fixed precedence:

  `Paused` › `Not answering` › (`Never billed` | `Behind`) › `OK`

  Cause outranks symptom: an unreachable meter is also a behind meter, and the operator's action is to fix the connection. `Never billed` and `Behind` cannot co-occur, since a meter with no Bill Date has nothing to be behind against.
- The chip carries its own number (how many consecutive failures, how many days behind).
- **Behind** means the latest closed Bill Date is older than a fixed threshold, **35 days**, held as a named constant in the backend constants module. This deliberately ignores the per-device bill-day configuration that already exists on the device row: that path is more precise, but it depends on configuration being correct, and when the configuration is wrong it would *hide* the problem rather than surface it — while wrong configuration is itself a cause worth seeing.
- **The attention counter** on the tab header counts every row that is not `OK` and not `Paused`, matching the counter v1 showed and the customer is used to.
- **Sort order**: worst status first, then device name. The tab is scanned for problems, not read for position.

**Capture time**

- Sourced from the Billing Reading's existing **read time**. Nothing in the system stores a capture timestamp, and none is added: a Capture is created eagerly and synchronously at the moment a closed period is inserted, so the read time *is* the capture time to within milliseconds.
- Known limitation to record, not fix: a Capture that failed at insert and was later re-rendered on download still shows the insert time. A missing Capture is re-rendered on download rather than tracked as a failure, so there is no failure state to display.
- The column is **always present**, blank where there is no capture. A table whose column count changes with a setting has an unstable shape, and a missing column is a harder question to answer than an empty cell.

**Filters**

- The device picker, the date range and the per-meter capture control are **hidden** on this tab. All three contradict it: the tab is every device, the latest period, and a per-meter capture spanning ten periods. Hidden rather than disabled — a greyed control invites the question, an absent one does not.

**API**

- A **new endpoint** returning the All-Meters View, rather than a new mode on the existing billing list endpoint. That endpoint's existing parameter distinguishes which tab (closed or open); making it also carry which aggregation would give one parameter two jobs, and the two have different paging characteristics — the existing list is paged, this one is bounded by device count.
- **The reusable unit is the query function in the database layer, not the endpoint.** The billing export planned in the next phase needs the same "latest closed period per device" result and must call the function directly rather than issuing HTTP against this process.
- **Status is computed server-side** and returned as a resolved value. The threshold constant lives in the backend, the counter needs the same rule, and a future exporter cannot call frontend code. Computing it in the browser would put one rule in two languages.
- Gated by the existing billing feature entitlement, and readable by any authenticated role, matching every other read surface in this product.

**Manual Read response**

- The manual billing read response gains a **captured count** alongside the existing stored count, and the existing confirmation message is extended rather than replaced.
- The stored count is deliberately **not** reused as the capture count: when the capture folder is unset, captures are disabled and none are written even though periods are stored, so the message would be wrong. Inferring it in the browser from the capture-folder setting fails for non-admin roles, which never load that setting.

**Vocabulary**

- **All-Meters View** and **Interval Status** are added to the glossary. Interval Status sits immediately after Records because those two are the pair that get confused: Records answers whether a *day* is complete by counting rows we hold; Interval Status answers whether *one row* is trustworthy, from the meter's own verdict.

## Testing Decisions

**What makes a good test here.** Every behaviour above is observable from outside the process as an HTTP response. A test asserts on the rows and the resolved status the API returns for a database it set up — never on how the status was computed, which functions were called, or how the query was shaped.

**One seam: the HTTP API through the test client.** No new seam is introduced. Prior art is the existing billing API test module, which uses the shared authenticated-client fixtures and the fake-meter fixture from the shared conftest, and whose docstring style explains *why* an endpoint differs rather than restating what it does.

The decision to compute status server-side is what makes one seam sufficient: had the browser resolved the chips, the precedence and the threshold would only be observable in a layer that has no test runner at all.

**Modules under test**

- The new endpoint: row set, ordering, status precedence, threshold behaviour, counter, capture time, empty-capture case, entitlement and role.
- The manual billing read: the captured count, including the case where the capture folder is unset.

**Cases that must each have a test that fails without the change**

- A device with no Billing Reading appears, with an empty Bill Date and the never-billed status.
- The Open Period never appears, even when it is the newest row for that device.
- A device whose latest closed Bill Date is just inside the threshold is OK; just outside, it is behind.
- A device that is both unreachable and behind reports unreachable.
- A paused device reports paused and is not counted.
- Ordering places the worst status first and breaks ties by device name.
- A licence without the billing entitlement is refused.
- The manual read reports a captured count of zero when the capture folder is unset, while still reporting the stored count.

**Two known hazards**

- The fake-meter fixture is autouse. The captured count must be exercised through the real store path; a fake that returns the number directly would keep the test green while proving nothing.
- Ordering and precedence assertions need at least three rows with three distinct statuses. Two rows make several wrong orderings indistinguishable from the right one.

**Not covered by this seam**

The tab rendering, the hidden filter card, and the chip colours are covered only by the frontend lint and build. The repository has no frontend test runner, and adding one is not part of this work. This is recorded as a known gap rather than silently accepted.

**Gate.** Backend format check, lint, and the full parallel test suite; frontend lint and build. The full suite, never a subset. Output Parity against v1 does not apply — v1 has no equivalent of this screen's status derivation, and the underlying numbers are the already-parity-checked Billing Readings. No real-meter read is required: nothing here touches acquisition.

## Out of Scope

- **Highlighting whole rows.** The customer asked for a highlighted row; this delivers a Status chip instead, because one row colour can carry one meaning and there are two to carry. See Further Notes.
- **Changing when captures fire.** The note describing per-device sequential capture describes behaviour that already exists; the response is to show the customer the capture folder, not to build a sweep.
- **Comparing a bill document against a captured image.** The customer placed this on a different web system in their own note.
- **A separate recent-captures page.** The capture time column on this tab is that list.
- **Real-time push of capture completion.** A notification for the unattended path would need a whole push channel to deliver a message to an empty room; the column and the manual-path confirmation cover what is actually observable.
- **A frontend test runner.**
- **The export-file work** — the billing CSV, the Energy Summary file, and the eleven added Load Profile columns are a later phase.
- **The empty average-power-factor column**, which is a separate defect found while gathering evidence for this work and needs its own diagnosis.

## Further Notes

**One deliberate deviation from the literal request.** The customer wrote "have a highlight like this on the latest bill". They will get a chip in a Status column, not a coloured row. The reason: a row colour can encode one axis, and this table has two things to say — a meter can be unreachable, behind, both, or paused. Two colour systems competing on one table teaches the operator a code instead of answering their question. **If the customer pushes back on this, it needs a conversation rather than a silent change** — the Status column is the load-bearing part, and a row tint could be added on top of it without redesigning anything.

**One assumption that must be stated wherever the threshold is implemented:** no customer runs a billing cycle longer than a month. The 35-day threshold is only correct under that assumption. If a quarterly cycle appears, this constant is where it breaks, and it should break loudly rather than by quietly marking every meter behind.

**Provenance.** The full requirements round this belongs to, the evidence behind it, and the twenty grill decisions that produced these choices are recorded in the remake plan's section 7. The three source briefs, with the customer's notes quoted cell by cell and every answer they gave, are under the scratch directory. Two warnings recorded there apply to later phases rather than this one, and should not be lost: the v1 phase-angle map is wrong for one meter family in a way that will make a correct implementation fail a naive parity test, and the licence key for the meter-activation change must be shaped so that its absence preserves today's behaviour.
