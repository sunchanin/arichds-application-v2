# A SMART TCC billing cut lands in the Current tab, and the next cut will erase it

**Type**: AFK · **Found**: customer machine, 2026-09-01, diagnosed from their `arichds.db` ·
**Blocks**: nothing · **Blocked by**: nothing (related to `docs/issues/005`, but independent —
see the bottom)

## The symptom, from the customer's own database

One device, one billing row, and it is in the wrong tab:

```
device 1  '3CL'  smart_tcc/st3cl  serial=002607000049  COM3 @ 9600 8N1
  Current tab shows : 2026-08-31 17:00:00      <- UTC; 2026-09-01 00:00 meter-local
  History tab       : nothing
```

That row is unambiguously a **closed** period, on three independent pieces of evidence:

| Evidence | Value | What an Open Period would look like |
|---|---|---|
| `bill_date` | `2026-08-31 17:00:00` — an exact period boundary, no seconds | the meter's live clock, seconds and all |
| `bill_date` vs its own `read_at` | **19.3 hours apart** (`read_at = 2026-09-01 12:15:29`) | the same instant, to within one round trip |
| every `max_demand_*_time_*` | `2026-08-15`, `-17`, `-18`, `-29`, `-30` — all inside August | inside the period still accumulating |

The max-demand timestamps are the decisive one: those are the peaks **frozen at close**. A period
still accumulating cannot have all of its peaks in the previous month.

## Root cause

`DlmsProfileDriver._classify_open` (`_dlms_profile.py:853-865`) asks the meter first and falls back
to position:

```python
if reset_reason_key is not None:
    ...                              # 255 = not reset = open
else:
    candidate = position == 0        # <- the fallback
```

`SmartTccDriver` declares `RESET_REASON_KEY = None` (`smart_tcc.py:167`), correctly: this family
**has no reset-reason register at all** — `0.0.0.1.12.255` is not a capture column on it. So every
TCC read reaches the positional branch, and whatever the meter returned first is called the Open
Period whatever it actually holds.

**The correct rule is already written down and was never implemented.**
`docs/meter-notes/tcc-obis-scan.md:605`, from a field probe on a real 3CL on 2026-07-24:

> **ไม่มี reset_reason register** (`0.0.0.1.12.255` ไม่ใช่ capture column) → classifier reset-reason
> คืน None สำหรับ TCC; **open/closed จำแนกจาก bill_date ที่ set แทน**

and `:597` of the same file records what the profile actually contains:

> อ่าน `0.0.98.1.0.255` ได้ 148 capture columns ครบทั้งใบ ถือ **1 cut จริง**: 14/07/2026 16:00

Scheme 1 holds **cuts** — closed periods. The owner's ruling on 2026-09-01, choosing between
"declare the family has no Open Period" and "classify by comparing bill_date to the clock", is the
first: **a SMART TCC billing profile never contains an Open Period, so `is_open` must always be
False for this family.** That matches what the meter was measured to hold, and needs no threshold
anyone could tune wrong.

## The second half — the stale row does not heal itself

Fixing the classifier alone leaves the customer worse, not better. `billing.py:448-450`:

```python
open_updated = False
if open_reading is not None:
    open_updated = _upsert_open(session, device_id, open_reading, read_at)
```

A read that returns **no** open reading leaves whatever is in the open slot untouched. After the
classifier fix, the next read would write the August cut as a **closed** row (a different partial
index, so no collision) while the stale `record_status = 'open'` row stays exactly where it is —
**the same period visible in both tabs at once.**

So the fix has two halves, and the second is not optional.

## Severity — this is data loss, not a display bug

The Open Period is one row per device, **overwritten in place** on every read (CONTEXT.md — Open
Period). The customer's only billing cut is currently sitting in that slot.

**When the meter takes its next cut, the new cut overwrites the August one, and August is gone** —
it will never have been written as history. Nothing recovers it: ADR 0009's read path reads the
whole buffer, but the buffer holds one entry (`entries_in_use = 1` on this meter), so once the
meter itself rolls the entry over there is no source left.

Today the customer has one cut and has lost nothing. The window closes at their next billing cut.

## What to do

**D1 — declare it on `DlmsProfileDriver`, not on `MeterDriver`.**
`Smw110Driver` extends `DlmsDriver`, not `DlmsProfileDriver` (`smw110.py:202`), so it never sees
`_classify_open` and has its own positional logic. Putting the flag on the base `MeterDriver` would
create a declaration that one driver honours and another silently ignores — which is exactly the
defect `docs/issues/005` exists to complain about. Declaring it where it is honoured means Smw110
cannot be given a flag that does nothing.

Name it for what it says about the meter, not about the code — the profile is what does or does not
carry an open period. `BILLING_PROFILE_HAS_OPEN_PERIOD: bool = True` on `DlmsProfileDriver`,
`False` on `SmartTccDriver`, with the field-note citation in the comment.

**D2 — `_classify_open` returns `(False, already_assigned)` immediately when the flag is False.**
Before the reset-reason branch, not inside the fallback: the point is that this family has no open
period at all, not that its fallback picks wrong.

**D3 — a read that returns no open reading clears the slot, but only for a driver that declares
none.** In `billing.py`'s `_store`, when the driver declares no open period, delete the device's
`record_status = 'open'` row if one exists. Self-healing on the next read, no migration, no repair
script — the same shape ADR 0008 chose for the watermark.

**Do not** make this unconditional for every driver. A CEWE read that momentarily returns no open
row is a different situation, and deleting there would be a behaviour change this issue has no
evidence for.

`_store` currently takes readings, not a driver. Getting the declaration to it is the one design
question this issue leaves open — pass a flag down from the caller that already built the driver,
rather than importing the catalog into `billing.py`. Say in the report which seam you chose.

**D4 — an existing test pins the wrong behaviour and must flip.**
`test_smart_tcc.py::TestOpenClosedPositionalFallbackIsSilent::test_entry_zero_is_open_with_no_reset_reason_warning`
(`:291`) asserts `readings[0].is_open is True`. That assertion is the bug, written down. Flip it to
`is False`, keep the "no WARNing fires" half — that half is still correct and still worth pinning —
and rename the class so it no longer advertises a positional fallback this family does not use.

`test_dlms_profile_seams.py:171,188` also assert `is_open is True` for a fake driver with no
reset-reason column. Those must **keep passing unchanged**: they exercise the generic fallback,
which still exists for any future family that has neither a reset-reason column nor a ruling like
this one. If they fail, the flag was defaulted the wrong way round.

## Acceptance criteria

- [ ] `BILLING_PROFILE_HAS_OPEN_PERIOD` (or the name you argue for) is declared on
      `DlmsProfileDriver`, defaults True, and is False on `SmartTccDriver` with the
      `tcc-obis-scan.md` citation in the comment
- [ ] `Smw110Driver` gains nothing — proven by grep, since it cannot honour it
- [ ] A TCC read of a buffer whose entry 1 is a closed cut returns `is_open=False` for every row
- [ ] A TCC read returning no open reading **deletes** an existing open row for that device
- [ ] A CEWE read returning no open reading **leaves** an existing open row alone
- [ ] `test_smart_tcc.py:291`'s assertion is flipped and its class renamed; the "no WARNing" half
      still passes
- [ ] `test_dlms_profile_seams.py:171,188` pass **unchanged**
- [ ] The customer's exact row shape is a test fixture: `bill_date` at a period boundary, `read_at`
      19 h later, max-demand times in the previous month. Paste it from this issue rather than
      inventing a shape
- [ ] Required tests are derived as a **mutation table** — one row per decision, each naming the
      mutation that turns it red — and every mutation is actually run
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `python -m pytest -n auto` in `app/`
      (use `python -m pytest`; the console script under-collects — `docs/issues/004`)
- [ ] **Real-meter read**: the three CEWE meters must still classify their Open Period correctly —
      this changes a shared classifier. The customer's TCC is on COM3 at their site and is not
      reachable from here; say so rather than claiming a TCC read
- [ ] **Output Parity vs v1**: v1 had no open/closed split to compare against. Say so
- [ ] `CONTEXT.md`'s **Open Period** entry gains one line: not every meter family has one

## What this issue does not do

- **It does not repair the customer's database by hand.** D3 makes the next successful read fix it.
  If the owner wants it fixed before then, that is a separate, deliberate act.
- **It does not fix `docs/issues/005`.** 005 is about `read_billing()` hardcoding
  `readRowsByEntry(pg, 1, …)` instead of honouring `BILLING_NEWEST_ENTRY_FIRST`. **Fixing 005 would
  not have fixed this**: this meter's buffer holds one entry, so entry 1 is simultaneously the
  newest and the oldest, and the positional classifier calls it open from either end. The two are
  independent and 005 stays open.
- **It does not add a bill_date-versus-clock heuristic.** That was the rejected alternative
  (owner, 2026-09-01): it would need a tuned threshold, where the declaration needs none.
