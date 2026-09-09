# 04: Give a load-profile column one declaration instead of a positional tuple

**What to build:** nothing an operator can see. Every driver declares which load-profile
capture objects it stores and how each one's multiplier is resolved; today that declaration
is a positional three-part tuple and the resolution hardcodes a single COSEM class read at
a single attribute. The columns ticket 06 adds cannot be expressed in that shape. This
ticket changes the shape and nothing else.

**Make the change easy, then make the easy change.** This is the first half.

**Blocked by:** None (can start immediately — it shares no file with ticket 01).

**Status:** ready-for-agent

Source: `.scratch/export-files/spec.md`.

## What the new columns need that the tuple cannot say

Measured on a real Prometer 100, 2026-09-09, read-only:

- The four average-power capture objects are a **Demand Register** — a different COSEM
  class whose scaler sits at a different attribute than a plain Register's. Read with the
  hardcoded class, the meter denies the read and the column silently stores nothing.
- The interval status word has **no scaler at all** and must skip multiplier resolution
  entirely, the way Demand Time cells already do.
- The two export-power columns resolve their scaler from a **different class than their
  import counterparts** — the import side answers as a plain Register, the export side only
  as an Extended Register. So a scaler candidate is an address *and* a class, not an
  address.

## What to change

- [ ] A load-profile column's map value becomes a small frozen declaration carrying: the
      stored field, the expected unit, the ordered scaler candidates as address-and-class
      pairs, and a passthrough flag. Class and passthrough carry defaults, so adding a
      twelfth column later is one line rather than another shape change.
- [ ] Scaler candidate resolution takes those pairs and tries each with its own class,
      rather than one class applied to every candidate.
- [ ] Passthrough columns skip multiplier resolution and the numeric guard, exactly as the
      existing non-numeric cells do. Do not invent a second mechanism for this — reuse the
      one that is there.
- [ ] Every driver that declares load-profile columns moves to the new shape in this
      ticket. Leaving one behind means two shapes and a rule nobody wrote down.

## What must not change

- [ ] **No stored value changes.** Every column resolves the same multiplier it resolves
      today, from the same address, with the same class.
- [ ] **No test is edited to make this pass.** If a test needs changing, the change was not
      behaviour-preserving and the diff is wrong.
- [ ] No bug is fixed here, including the one ticket 05 fixes. A ticket that declares
      itself behaviour-preserving has to stay true, or the declaration is worthless and the
      review cannot tell which edit moved a number.

## Gate

- [ ] `ruff format --check` and `ruff check` pass.
- [ ] `pytest -n auto` passes **with no test file modified**.
- [ ] The driver-contract test that holds the map-shape invariant across every registered
      model still passes, and covers the new shape.
