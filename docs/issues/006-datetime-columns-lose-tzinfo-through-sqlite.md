# `DateTime(timezone=True)` columns lose `tzinfo` through SQLite — ~15 hand-written re-attachments do the same fix separately

**Type**: AFK · **Found**: diagnosis of issue #45, 2026-08-25 · **Blocks**: nothing today

## The problem

SQLAlchemy 2.0.51 (the pinned version) does not round-trip `tzinfo` through SQLite: a
`mapped_column(DateTime(timezone=True))` stores an aware `datetime` as a naive TEXT string and
hands it back naive on read. Measured directly (issue #45's diagnosis): a throwaway model storing
`datetime(2026,3,31,17,0,tzinfo=UTC)` came back `datetime(2026, 3, 31, 17, 0)` with `tzinfo is
None`. Every `DateTime(timezone=True)` column in this codebase is affected — `bill_date`,
`read_at`, the ten Demand Time columns on `billing_readings`, the Load Profile timestamp, and
others.

**The codebase already knows this and works around it in roughly fifteen separate places**, each
its own hand-written `.replace(tzinfo=UTC)` or equivalent:

- `api/billing.py:195-216` — `_ensure_utc` / `_ensure_utc_or_none`, the two Pydantic
  `field_validator`s this module documents as "the house pattern"
- `api/load_profile.py` — `LoadProfileRowOut._ensure_utc`, the same pattern by another name
- `acquisition/billing.py:367-368` (`billing_change_check`) and, after issue #45, `:473-474`
  (`_measurement_differs`) — the same reattachment, inline, for a stored-vs-incoming comparison
  rather than an API response
- `capture/service.py:57` — compensates for `bill_date` **only**, to build the shared filename
  stem (ADR 0015); it never sees the ten Demand Time columns
- `export/format.py:161` and others the diagnosis did not enumerate exhaustively — issue #45's
  prompt cites this one as a reader that already compensates

**Not every site compensates.** `capture/_render_shared.py:107-108`'s `format_cell` —
`if isinstance(value, datetime): return value.isoformat(sep=" ", timespec="seconds")` — does not
re-attach UTC at all, and it is reached for every Demand Time cell and for Bill Date, via
`capture/pdf.py:90` and `capture/xlsx.py:55`. A naive UTC value prints as a bare UTC clock face,
no offset, no local conversion. Meanwhile `web/src/pages/Billing.tsx:49` renders the same fields
with `dayjs(...)`, which is **browser-local**, and ADR 0017 makes the `.png` capture a screenshot
of that page — so the `.pdf`/`.xlsx` (UTC) and the `.png` (local) that ADR 0015 gives one shared
filename stem can disagree by a full UTC offset. This is a real, pre-existing, shipped defect
(landed with issues #22/#35), **not** something this issue's fix touches, and it is tracked
separately as `docs/issues/007`.

Every site **on the API read path** independently re-derives the same fact (every row in these
tables is UTC by the normalization contract) and applies the same one-line fix — a fix repeated by
hand across the API layer is a fix a new reader on that layer can forget, and issue #45 is exactly
that: `_upsert_closed`'s stored-vs-incoming comparison was the one call site on that path that read
a `DateTime(timezone=True)` column back and compared it to an aware value without compensating,
undetected because the project's own test fixtures never populated a `datetime` column with a
non-`None` value until that issue's fix.

## Why it still needs fixing

The next `DateTime(timezone=True)` column added to any table, or the next new reader of an
existing one, starts from zero on this — nothing enforces the reattachment, and nothing fails
loudly when it is missing. A comparison against a naive value doesn't raise; it just silently
returns `True` where the values are actually equal (issue #45), or renders the wrong local time in
the browser where a response field is missing its `field_validator` (the failure mode the existing
`api/*.py` re-attachments already guard against, by hand, per field).

## What to do (not here)

Investigate a SQLAlchemy `TypeDecorator` (or a custom `DateTime` subclass) that re-attaches UTC on
every read, once, at the type level — replacing the per-field `field_validator`s in `api/*.py`,
the inline reattachments in `acquisition/billing.py`, and `capture/service.py:57`'s `bill_date`
compensation, plus whatever else `export/format.py` and elsewhere the diagnosis did not fully
enumerate. This is a cross-cutting change: every table with a `DateTime(timezone=True)` column,
and every API response model with a matching `field_validator`, is in scope. It is **not** part of
issue #45's fix, which is a narrowly-scoped bug fix mid-milestone (M6a/M4c), not a milestone slice
of its own.

**This is not the same problem as `docs/issues/007`.** A `TypeDecorator` only makes the *existing*
reattachments unnecessary to write by hand — it does nothing for `capture/pdf.py` and
`capture/xlsx.py`, which never compensate today and would still need someone to decide *which*
timezone a customer-facing document should show before either renderer changes at all. That
decision is 007's, not this issue's.

## Acceptance criteria (for whoever picks this up)

- [ ] A `TypeDecorator` (or equivalent) that re-attaches UTC to every `DateTime(timezone=True)`
      column on read, applied to every such column across `db/models.py`
- [ ] Every hand-written `_ensure_utc` / `_ensure_utc_or_none` / inline `.replace(tzinfo=UTC)`
      reattachment this issue enumerates (and any it missed — a fresh grep for
      `tzinfo=UTC` and `DateTime(timezone=True)` is the way to find the rest) is removed in favor
      of the type-level fix, not left standing alongside it
- [ ] `ruff format --check .` + `ruff check .` + `python -m pytest -n auto` (use `python -m
      pytest`; the console script under-collects, see `docs/issues/004`)
- [ ] Every table this touches keeps its existing behavior — this is a refactor, not a behavior
      change, so Output Parity does not apply, but every existing datetime-comparison and
      datetime-rendering test must still pass unmodified in intent (adjusted only for the removed
      helper's call sites)
