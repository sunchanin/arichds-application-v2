# A PDF renderer test compares whole bytes, so a one-second clock tick fails it

**Type**: AFK · **Found**: review of issue #46, 2026-08-25 · **Blocks**: nothing — it makes the
gate flaky, which is worse than it sounds

## The problem

`app/tests/test_capture_renderers.py:148` asserts two rendered PDFs are byte-for-byte equal:

```python
def test_kilo_is_the_default(self) -> None:
    row_a = make_row(import_active_kwh_total=200464.501)
    row_b = make_row(import_active_kwh_total=200464.501)

    assert render_billing_pdf(row_a, "Main Incomer") == render_billing_pdf(row_b, "Main Incomer", scale="kilo")
```

`capture/pdf.py` never sets `/CreationDate`, so `fpdf2` embeds its own — the wall clock at
**one-second resolution**. Two renders that straddle a second boundary differ, and the assertion
fails on the clock rather than on the feature.

Reproduced deliberately by forcing the boundary (`app/.venv`, 2026-08-25):

```
identical: False
A CreationDate: [b'D:20260825045848Z']
B CreationDate: [b'D:20260825045849Z']
len A/B: 3806 3806   first diff at: 3338   diff bytes: 63
```

63 bytes differ, not 1 — the timestamp reaches the document `/ID` as well as `/CreationDate`.

## Why it matters more than a rare red

It fails **only under load**, because that is when the two renders are most likely to land either
side of a tick — so it fires during a parallel `-n auto` gate run and passes on the re-run that
investigates it. That is the exact profile of a test people learn to re-run rather than read, and
this repo's gate is the thing standing between a change and a customer install. It failed once in
issue #46's gate run.

The odds are not negligible: the two renders take roughly a millisecond, so the failure rate is
about the fraction of a second boundary they can straddle — small per run, but the full suite is
the gate on every issue.

## What the test is actually for

That `scale="kilo"` is the default — i.e. passing it explicitly changes nothing. Byte equality is
a *proxy* for that, and a needlessly strong one: it asserts the two documents agree on their
creation timestamp too, which has nothing to do with the display-unit setting (ADR 0013).

## What to do

Compare what the test means, not the whole byte string. Either:

- extract and compare the rendered **text** (the sibling xlsx tests already do exactly this via
  `_xlsx_values`, `test_capture_renderers.py:155-158` — there is no equivalent helper for PDF
  yet), or
- freeze `/CreationDate` in `capture/pdf.py` so a rendered capture is reproducible, and keep the
  byte comparison.

The second is the larger change and has an argument in its favour beyond this test — ADR 0015
gives the `.pdf`, `.xlsx` and `.png` one shared filename stem, and a byte-reproducible pdf makes
"has this capture changed?" answerable. It also touches a shipped renderer, so it is not a
test-only fix. **Decide which, do not do both.**

## Acceptance criteria

- [ ] The test no longer depends on wall-clock time — proven by rendering either side of a forced
      one-second boundary and having it stay green
- [ ] The test still goes red when `scale="kilo"` stops being the default (mutation: make `"base"`
      the default in `render_billing_pdf`)
- [ ] If `/CreationDate` is frozen instead, ADR 0015's three-format contract is checked for
      anything the change makes false, and `capture/xlsx.py` is checked for the same class of
      embedded timestamp
- [ ] `ruff format --check .` + `ruff check .` + `python -m pytest -n auto` (use `python -m
      pytest`; the console script under-collects, see `docs/issues/004`)

## Blocked by

Nothing.
