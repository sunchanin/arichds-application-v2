# 07: The eleven columns reach the Load Profile file and the Load Profile page

**What to build:** the operator's Load Profile CSV carries all twenty-five columns their
sample asks for, in their order, with the file header block above them. Their existing file
is closed under a dated name and a new one opens, so no row is ever written under a header
that does not describe it. The same eleven columns appear on the Load Profile page, where a
number that looks wrong in the file can be checked without opening the file.

**Blocked by:** 06 (the data has to be stored before it can be exported) and 01 (the file
header block and the roll rule).

**Status:** ready-for-agent

Source: `.scratch/export-files/spec.md`. Requirements A1/A2/A4.

## The file

- [ ] Twenty-five columns, **in the customer's order** — which inserts the three phase
      angles before `Frequency (Hz)` rather than appending everything at the end. That
      moves an existing column's position, and is only survivable because of the roll.
- [ ] **Column names follow this product's own convention**, continuing the 2026-08-11
      ruling that corrected v1's four mis-united energy headers. The customer's spelling
      repeats the same error and carries stray whitespace. Adopting it verbatim would leave
      one file using two naming conventions. The customer is told, not asked.
- [ ] The status column keeps the customer's header word. The file speaks their language;
      the product speaks the glossary's. That is the same split ADR 0013 already draws.
- [ ] The Load Profile CSV gains the five-line file header block here — **not earlier**.
      Adding the block is itself a header change, so doing it in an earlier ticket would
      roll every operator's file twice instead of once.
- [ ] The status word is decoded to words through one helper shared with the page: the
      settled wording for the family whose bits are verified, and blank for the family
      whose are not.
- [ ] **Multiple set bits join with a pipe, not a comma.** v1's comma-joined rendering
      never reached a CSV — it existed only on v1's screen — so no parity is broken, and a
      comma inside a cell survives only if every downstream consumer honours CSV quoting,
      which cannot be tested from here.
- [ ] A model that does not record a quantity gets an empty column, never a missing one, so
      every meter's file has the same shape. This is already the shipped behaviour for
      `Frequency (Hz)`.
- [ ] The Load Profile CSV's existing numeric formats are unchanged. It has an Output Parity
      obligation the two new files do not.

## The page

- [ ] All eleven columns appear on the Load Profile page.
- [ ] **The display unit setting changes the four power columns on the screen and never in
      the file.** This is ADR 0013's own boundary, and until now no column existed that the
      boundary ran through in both directions — so assert both halves. This is the first
      time that rule is testable rather than merely stated.

## Output Parity — written to reject the wrong fix

v1 reads phase angle at an address that is right for one meter family and wrong for the
other, so on CEWE meters v1's phase-angle columns are NULL. A correct v2 prints numbers
where v1 prints blanks.

- [ ] Parity is asserted over the fourteen pre-existing columns.
- [ ] For the phase angles it is **inverted**: assert that v2 is *not* NULL where v1 is,
      with the reason in the test's name. Without that assertion, the correct implementation
      looks like a regression and the obvious repair is to break it.

## Documentation

- [ ] `CONTEXT.md`'s Interval Status entry records the pipe separator, because it is part of
      the file contract rather than a coding detail.
- [ ] `SPEC.md` records the new column set.

## Gate

- [ ] `ruff format --check` and `ruff check` pass.
- [ ] `pytest -n auto` passes.
- [ ] `pnpm lint` and `pnpm build` pass.
- [ ] Tests read the produced file off disk: twenty-five columns in the customer's order,
      the header block, the pipe-joined status, empty columns on a model that records
      nothing, and — starting from a file written with the old fourteen-column header — the
      old file renamed under a dated name and the new one opened with the new header.
- [ ] Output Parity against v1, including the inverted phase-angle assertion.
- [ ] The customer is told, in writing, which columns are empty on which model: the
      line-to-line and power columns carry values on one model only, and a SMART TCC gets
      phase angles but a blank status column until that meter is reachable.
