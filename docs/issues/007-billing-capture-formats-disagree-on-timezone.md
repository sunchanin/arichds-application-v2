# The `.pdf`/`.xlsx` and `.png` billing captures disagree on timezone, seven hours apart

**Type**: AFK · **Found**: review of issue #45, 2026-08-25 · **Blocks**: nothing today

## The problem

ADR 0015 gives a closed billing period's three capture formats one shared filename stem —
`<capture_dir>/<serial>/<bill_date>.{pdf,xlsx,png}` — deliberately, so a human can find all three
together for one period. The three formats do not agree on what timezone to render Bill Date and
the ten Demand Time columns in:

- `capture/_render_shared.py:107-108`'s `format_cell` — `if isinstance(value, datetime): return
  value.isoformat(sep=" ", timespec="seconds")` — never re-attaches UTC before formatting. It is
  reached for every Demand Time cell and for Bill Date via `capture/pdf.py:90` and
  `capture/xlsx.py:55`. SQLite hands these columns back naive (`arichds/db/models.py`'s
  `DateTime(timezone=True)` columns do not round-trip `tzinfo` — measured, issue #45's diagnosis),
  and every row in this product's tables is UTC by the normalization contract — so the `.pdf` and
  `.xlsx` print a bare UTC clock face: no offset marker, no local conversion.
- `web/src/pages/Billing.tsx:49` — `const time = (value) => dayjs(value).format("YYYY-MM-DD
  HH:mm:ss")` — renders the same fields in the **browser's local timezone**. ADR 0017 makes the
  `.png` capture a headless screenshot of exactly this page.

On any machine not set to UTC, the `.png` in a capture folder shows a different clock time than
the `.pdf`/`.xlsx` sitting next to it under the same filename stem, for the same period, on the
same fields. On the CEWE fleet (ICT, UTC+7 — `METER_LOCAL_UTC_OFFSET_HOURS`), that is a
**seven-hour** disagreement.

## Why it is not urgent

Nothing here corrupts stored data — `billing_readings` holds the correct UTC instant in every
case (issue #45's live-meter evidence). This is a rendering disagreement between three files that
already exist, not a new defect introduced by any pending work, and no customer complaint is on
record.

## Why it still needs a decision

ADR 0010 calls a capture "a document a human carries to a customer" — the whole reason `capture_dir`
is an operator setting rather than a fixed path. Two documents in the same folder, sharing one
filename stem by design (ADR 0015), showing different clock times for the same event is exactly
the kind of inconsistency that erodes trust in a document handed to someone outside the company.
Nobody has decided *which* timezone is correct here — UTC (what the `.pdf`/`.xlsx` do today) or
ICT/local (what the `.png` does today, and what `Billing.tsx`'s live page does) — so there is
nothing to enforce even if someone wanted to fix it.

The nearest precedent is **ADR 0013** ("display units are a view, an appended file is a
contract") — it drew exactly this line for kW/W scaling: a rendered view may change per the
machine-wide display setting, but an appended file (the Load Profile CSV) is a contract written
once and never renormalized. Billing captures are not appended files in that sense (each period's
capture is written once, not accumulated into), but the same question applies: is a capture's
displayed timezone a view (follow the browser/machine, like the live page) or a contract (fixed at
UTC, like the stored data), and ADR 0013 did not settle it because timezone was not the axis it
was written about.

## What to do

Nothing here proposes an answer. Whoever picks this up should put the choice — UTC everywhere,
local (ICT) everywhere, or leave the page local and fix only the two file renderers to match it —
in front of the owner, the way ADR 0013 settled the kW/W question, and record the decision as an
ADR or an amendment to 0015. Only after that is decided does a code or test change belong here.

## Acceptance criteria (for whoever picks this up)

- [ ] The owner has chosen one timezone convention for `.pdf`/`.xlsx`/`.png` billing captures, and
      the decision is recorded (new ADR or an amendment to an existing one)
- [ ] `capture/pdf.py`, `capture/xlsx.py` and (if the decision requires it) `web/src/pages/Billing.tsx`
      render Bill Date and the ten Demand Time columns consistently with that decision and with
      each other
- [ ] A test pins the chosen convention — asserting on the rendered string, not merely that
      *some* timezone handling ran
- [ ] `ruff format --check .` + `ruff check .` + `python -m pytest -n auto` (use `python -m
      pytest`; the console script under-collects, see `docs/issues/004`) and `pnpm lint && pnpm build`
      for the frontend half, if touched

## Not touched by this filing

`docs/issues/006` (the `TypeDecorator` question) is a different problem — it is about deduplicating
reattachments that already exist and agree with each other on the API read path. This issue is
about two renderers and a page that never agreed in the first place.
