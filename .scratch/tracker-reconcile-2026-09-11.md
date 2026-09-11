# Tracker reconciliation, 2026-09-11 — what GitHub says vs what the tree holds

Written while closing phase 3. Every verdict below was reached by reading the **code**, not the
issue text. The GitHub half of this has not been applied — the commands are at the bottom.

## Why this file exists

The tracker is wrong in both directions at once, and each direction has a different cost:

- **Closed but not built** hides real work. One case, and it is the one the repo's own documents
  keep pointing at.
- **Built but still open** makes the open list untrustworthy, which is how the first kind
  survives: seven open issues that are all done teach a reader to stop believing the list.

## Every open issue is shipped — all seven

| # | Title | Verdict | Evidence |
|---|---|---|---|
| 40 | Edge via LOCAL SERVICE task; service back on LocalSystem | **SHIPPED** | `installer/arichds.iss:146` (`nssm reset … ObjectName`), task at `:181` via `register-capture-task.ps1:161` (`-UserId "LOCALSERVICE"`), removed at `:197`; launch path `capture/screenshot.py:269-341`, serialised by `_CAPTURE_LOCK` `:824` |
| 41 | Issue Meter Activation Codes — vendor signer and CLI | **SHIPPED** | `tools/arichds_vendor.py:592` (`sign-meter`), `licensing/meter_activation_code.py:97` (`verify_meter_activation_code`). **Its criteria never asked for an `/activate-meter` endpoint** — CLAUDE.md's ADR 0019 digest invented one, corrected in the same commit as this file |
| 42 | Adding a meter requires a Meter Activation Code | **SHIPPED** | `db/models.py:124` + migration `0013`, gate at `api/devices.py:1042-1054` → `_verify_meter_activation_code` `:785-809`. Deliberate divergence, argued in-code at `devices.py:311-320`: Update accepts a code and never checks it, because `_reject_changed_serial` `:1226-1244` refuses *any* serial change — stricter than a re-check |
| 43 | Detect a new billing period within 15 minutes | **SHIPPED** | `acquisition/load_profile.py:391` inside `_read_while_holding`, background path only (`:284` vs `:290`), full read fired after the walk `:316-317`; signal `acquisition/billing.py:309-380`, `entriesInUse` explicitly rejected `:332-338`; daily backstop preserved `constants.py:96` |
| 44 | A new meter reads on the next tick; Read on both pages | **SHIPPED** | `jobs/scheduler.py:308` `run_soon()` called from `api/devices.py:1092`; `POST /api/billing/read` `api/billing.py:566`, `POST /api/load-profile/read` `api/load_profile.py:334`; `history_remains` typed at `web/src/api.ts:239` |
| 45 | Every billing read reports every closed period as changed | **SHIPPED** | `acquisition/billing.py:500-521` `_measurement_differs()` re-attaches UTC to the ten Demand Time columns SQLite returns naive; regression tests `tests/test_billing_job.py:157,206,259` |
| 46 | Database Destination — sync into the customer's MariaDB | **SHIPPED** | `dataout/{destination,schema,status,sync}.py`; job registered `jobs/scheduler.py:423` (`JOB_DBDEST_SYNC`); endpoints `api/settings.py:421,433`. GitHub **#47** is the same work against "MySQL" and is already closed — #46 superseded it |

## One closed issue with nothing behind it

**#32** — *"a capture folder can hold both kWh and Wh documents with nothing marking which"* —
is `CLOSED / COMPLETED`, closed `2026-08-24T03:50:25Z` inside a nine-issue bulk close (nine
closures inside three seconds), still labelled `needs-triage`.

The code is unchanged: `capture/service.py:58` builds the filename stem from `bill_date` alone,
and `capture/pdf.py:70-76` renders a header of Device / Meter Serial / Bill Date with no unit.
`ADR 0013:111-140` and `CLAUDE.md`'s digest of it both still describe the gap as outstanding and
needing its own issue — so the repo's own documents have been right and the tracker wrong for
two and a half weeks.

Filed as **`docs/issues/019`**, which also records the choice the fix needs (unit in the document
header, or in the filename — the latter touches ADR 0015's deliberately fixed stem).

## The rest of that bulk close is real

Spot-checked the other seven of the nine. **#28, #29, #31, #35, #36, #37 are genuinely shipped**
— wired call paths, migrations, licence gates and tests, not stubs. So the bulk close was
careless bookkeeping on one issue, not nine hollow closures.

**#38 is PARTIAL, and correctly so.** Its Part B (screenshot renderer) is live. Its Part A (move
the service to `NT AUTHORITY\LocalService`) shipped at `1f9adbe` and was then **deliberately
undone** by #40, because a LocalService service cannot write a `capture_dir` under `C:\Users\…`.
Judged against today's tree it is half-present; judged against history it is complete and
superseded. ADR 0017 carries that story.

## The commands — not yet run

GitHub writes were unavailable in the session that produced this file. Review the verdicts above,
then:

```bash
# the seven that are done — close with the evidence line from the table
gh issue close 40 --comment "Shipped on feature/light-modules; verified against the tree 2026-09-11. See .scratch/tracker-reconcile-2026-09-11.md"
gh issue close 41 --comment "Shipped: tools/arichds_vendor.py sign-meter + licensing/meter_activation_code.py. No /activate-meter endpoint was ever specified — CLAUDE.md's digest was wrong and is corrected."
gh issue close 42 --comment "Shipped; the Update leg deliberately has no code check because _reject_changed_serial refuses any serial change, which is stricter. Argued at api/devices.py:311-320."
gh issue close 43 --comment "Shipped: the check rides the Load Profile cycle's connection, background path only; daily backstop kept deliberately."
gh issue close 44 --comment "Shipped: run_soon() on device create, plus POST /api/billing/read and POST /api/load-profile/read."
gh issue close 45 --comment "Shipped: the comparison re-attaches UTC to the Demand Time columns SQLite returns naive. Stored rows were never wrong."
gh issue close 46 --comment "Shipped: dataout/ + the dbdest_sync job + the three settings endpoints. Supersedes the already-closed #47."

# the one that was closed without the fix
gh issue reopen 32 --comment "Reopening: closed COMPLETED on 2026-08-24 in a nine-issue bulk close, but the code never changed — capture/service.py:58 has no unit in the stem and capture/pdf.py:70-76 has none in the header. ADR 0013:111-140 still lists it as outstanding. docs/issues/019 carries the decision the fix needs."
```

If #32 is reopened, drop its `needs-triage` label for `ready-for-agent` once the header-vs-filename
choice is made — `docs/issues/019` is blocked on exactly that and nothing else.
