# Export files mirror our window; they are rewritten, never archived

Status: accepted (2026-09-14, owner decision during the M14 grill). **Supersedes the M13
amendment to ADR 0013** (closed editions). ADR 0013's core — display units never reach a file —
is untouched. Extends ADR 0020's rule from the customer's database to the export folder.
**The atomic-replace primitive and the in-place head-change rewrite landed with M14 ticket 02**:
`export/writer.py` gained `replace_rows()` (temp file in the same directory, `flush()` +
`fsync()`, then `os.replace()`) and `head_changed()`; `_roll` and its dated-edition naming are
deleted, with nothing left referring to them. Each of the three files gained its own "whole
current content" query, used only on a head change at that point: Load Profile CSV (the 90-day
merged query, same skew cap and all-invalid exclusion), Billing (every closed period, unfiltered)
and Energy (the live `energy_summary_rows()` aggregation over 90 days).

**Energy and Billing rewritten whole every cycle landed with M14 ticket 04**
(`.scratch/central-push/issues/04-energy-and-billing-files-are-rewritten-every-cycle.md`):
`export/energy_csv.py::export_device_energy` and `export/billing_csv.py::export_device_billing`
now call `replace_rows()` on **every** export cycle, unconditionally — `head_changed()` is gone
from both modules, because there is no cheaper conditional path left to guard: a normal cycle
*is* what a head change used to trigger. Energy reads `energy_summary_days` for
`[local_today − (RETENTION_DAYS − 1), local_today]` (today inclusive — a wrong partial-day number
is corrected on the very next cycle, so there is no reason left to hold it back the way the
append-only file had to); Billing reads every closed period, unfiltered, exactly as its old
head-change path already did. Migration 0018 drops `devices.billing_exported_through` (0014) and
`devices.energy_exported_through` (0015); nothing in the application reads or writes either
column any more. The on-demand **Save to file** button also moved onto `energy_summary_days`
(`export_energy_range`), so it can never disagree with the daily file or the page for the same
days. **A device with nothing stored in its window still holds quietly** (no file written) rather
than replacing an existing file with an empty one — the same choice the Load Profile CSV and
Billing files already made for "nothing to write yet"; for Billing this can never go stale
(a closed period is never deleted, ADR 0009), but for Energy a device that stops reporting for a
whole retention window is a residual gap ticket 04 did not close, flagged rather than fixed
silently. **Not yet implemented**: ticket 05 (the Load Profile CSV's own daily 90-day trim) — the
Load Profile CSV still only appends, exactly as ticket 02 left it.

M13 treated the export files as a long-term archive. Its spec called the daily Energy file "a
long-term archive — it outlives the ninety-day retention", and ADR 0013's amendment let dated
Closed Editions accumulate in the folder "the way a filing cabinet accumulates volumes". Both
contradicted a reason the customer had already given and ADR 0020 had already recorded on
2026-08-24: **limited disk space on the machine.** Purging our database to 90 days while the
export folder grows forever beside it saves nothing.

## The decision

| File | Holds | Written |
|---|---|---|
| Load Profile CSV | the last 90 days | appended every cycle; **trimmed and rewritten once a day** with the retention job |
| Energy Export File | the last 90 days | **rewritten whole every cycle** from the stored Energy Summary (ADR 0022) |
| Billing Export File | every closed period | **rewritten whole every cycle** — billing is never purged from our store, so its window is all of it |

- **Every rewrite is atomic**: write a temporary file, then replace. A reader — Syncthing, the
  customer's own tooling — never sees half a file.
- **Closed Editions are removed.** They existed only because rewriting was forbidden. A changed
  head now means rewriting the window under the new head, so a file carries **exactly one head,
  the current one**, and every row in it matches. The rule that survives from the amendment is the
  part that mattered: no row sits under a head that does not describe it.
- **A Holiday change rewrites nothing specially.** Only the Energy file depends on Holidays, and
  it is rewritten every cycle anyway.

## Considered

| Rejected | Why |
|---|---|
| Keep M13: append forever, close editions on a head change | Grows without bound on a machine whose owner asked for bounded storage |
| Rewrite the Load Profile CSV every cycle | 96 full rewrites a day of a file around 2 MB per meter, each one resent by Syncthing |
| One file per day via the `[date]` filename token, deleting files past 90 days | `[date]` renders the day of *writing*, not the day of the data (`export/format.py`), so a late reading lands in the wrong file; the customer's samples are one file per meter; and the folder would hold thousands of files |

## Consequences

- **Nothing on the machine holds an energy split, or an interval, older than 90 days.** That is
  the customer's choice, made for space.
- **The Load Profile CSV may hold up to 91 days** between daily trims.
- Syncthing receives small appends through the day and one large change a day, instead of a
  file that grows for months — which also retires the hashing-while-growing problem the
  Syncthing runbook worked around.
- `.scratch/export-files/customer-letter.md` §5 ("your existing file has been closed") and
  question 3 in `customer-questions.md` ("does anything read the closed files?") describe a
  mechanism that no longer exists and must be rewritten before either is sent.
- The on-demand **Save to file** stays, for a chosen range in its own file, but stops being "the
  corrective for a stale archive": the daily file cannot be stale by more than one cycle.
