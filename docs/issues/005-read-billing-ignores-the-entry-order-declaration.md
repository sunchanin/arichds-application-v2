# `read_billing()` ignores the entry-order declaration the change check obeys

**Type**: AFK · **Found**: review of issue #43, 2026-08-24 · **Blocks**: nothing today; blocks the
first oldest-first billing driver

## The problem

Issue #43 introduced `MeterDriver.BILLING_NEWEST_ENTRY_FIRST` (`drivers/base.py:487`) so that a
driver *declares* which end of its billing buffer is newest, rather than the code assuming it.
ADR 0018's own amendment explains why that matters: entry ordering is a property of the profile,
not of the model — the SMW110W4's load profile is oldest-first while its billing profile is
newest-first (`docs/meter-notes/smw110w4-scan.md:74`, `SPEC.md`).

**The declaration is honoured by the new change check and ignored by the read path that actually
produces rows.**

| | honours the flag | hardcodes newest-first |
|---|---|---|
| `billing_newest_closed_bill_date()` — `_dlms_profile.py:808,811` and `smw110.py:704,716` | ✅ | |
| `read_billing()` — `_dlms_profile.py:683`, `smw110.py:595` | | `readRowsByEntry(pg, 1, …)` |
| open/closed classification in `read_billing()` — `smw110.py:659` | | `is_open = position == 0` |

`_dlms_profile.py`'s `read_billing` is partly insulated, because `_classify_open` consults the
reset-reason cell first and only falls back to position. `smw110.py` is not: its
`RESET_REASON_KEY` path aside, `is_open = position == 0` is a bare positional assumption, and it
appears three times (`:622`, `:632`, `:659`).

## Why it is not urgent

Every driver shipping today is newest-first, so the flag's value is `True` everywhere and both
halves agree by coincidence. Nothing is wrong in the field.

## Why it still needs fixing

The next person adding an oldest-first billing driver will set
`BILLING_NEWEST_ENTRY_FIRST = False`, watch the change check do the right thing, and get a
`read_billing()` that reads the wrong end of the buffer and marks the wrong row open — which is
precisely the defect ADR 0018's amendment was written to prevent, arriving through the half of
the pair nobody touched. A declaration obeyed in one place and ignored in another is worse than
no declaration, because it reads as covered.

## What to do

Make `read_billing()` on both drivers compute its entry window and its open/closed position from
`BILLING_NEWEST_ENTRY_FIRST`, the same way `billing_newest_closed_bill_date()` already does.
Pin it with a test that goes red when the declaration is inverted — asserting on the **rows
returned**, not on the requested index. That distinction is not pedantic: the same criterion on
`billing_newest_closed_bill_date()` was written as an index assertion at first, and issue #43's
review found the row-order half completely unpinned as a result.

Alternatively, decide the flag should govern only the cheap check and say so in ADR 0018 — but
that needs to be written down, not left as the current silence.

## Acceptance criteria

- [ ] Both drivers' `read_billing()` derive the entry window and the open/closed position from
      `BILLING_NEWEST_ENTRY_FIRST`
- [ ] A test asserts on the returned rows and goes red when the declaration is inverted, for each
      driver
- [ ] **Output Parity vs v1** for billing is re-confirmed — this touches the row-producing path
      ADR 0009 calls the one read path
- [ ] Real-meter read against the three reachable CEWE meters, since this changes what is
      requested over the wire
- [ ] `ruff format --check .` + `ruff check .` + `python -m pytest -n auto` (use `python -m
      pytest`; the console script under-collects, see `docs/issues/004`)

## Blocked by

Issue #43 must be committed first — it is what introduces the declaration.
