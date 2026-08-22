# Three capture formats share one name and do not cover the same period

A closed Billing Reading now produces three files under one filename stem:

```
<capture_dir>/<meter_serial>/2026-07-26_000000.pdf    ← July only
<capture_dir>/<meter_serial>/2026-07-26_000000.xlsx   ← July only
<capture_dir>/<meter_serial>/2026-07-26_000000.png    ← February through July
```

**The `.png` covers the ten most recent closed periods; the other two cover exactly one.** The
owner chose this shape explicitly after the collision was raised (grill, 2026-08-22). This ADR
exists because the folder gives a reader no hint of it, and the natural reading of three
same-named files — "one document, three formats" — is wrong.

## Why the image spans ten periods

The customer wants the image to look like the Billing History table, and that table's whole
purpose is comparison across months: a single-row table would be the per-period report again in
a new coat. Ten is a fixed count rather than "everything", so the image stays legible in year
one and year ten alike, and so an automatic render and a hand-pressed one always produce the
same picture — there is no filter state to diverge on.

Nothing is lost by bounding it. An older period's own image still exists, still holds the ten
periods that preceded *it*, and is never rewritten.

## Why the name is not disambiguated

Considered and rejected:

| | Why not |
|---|---|
| `<serial>/history/<bill_date>.png` | Cleanest for a reader; **rejected by the owner** — the customer wants the three files side by side |
| `<serial>/<bill_date>_last10.png` | Same folder, but noisy, and the number rots the moment the count changes |
| Widen the term "Capture" and say nothing | What we are doing, plus this ADR — the point is that the saying is not optional |

The decisive argument for the rejected first option was that `capture_dir` **is** the handoff
mechanism (ADR 0010): a human opens that folder and hands a file to a customer, so ambiguity in
the folder is ambiguity in the deliverable. The owner weighed that against the customer's
explicit request and chose the request. Recorded, not relitigated.

## Consequences

- **The failure mode is a person sending six months of data believing they sent one.** They
  attach `2026-07-26_000000.png` intending July. Nothing on disk warns them. Documentation and
  the Billing page's own wording are the only guards, which is why this ADR and the `Capture`
  entry in `CONTEXT.md` both spell the span out rather than mentioning it in passing.
- **Do not "fix" the inconsistency.** A future reader who notices that one extension covers a
  different span than its siblings is looking at a decision, not a bug. Renaming the files later
  breaks every downstream folder, sync target and operator habit already pointed at them.
- **The naming convention itself is unchanged** — still `<capture_dir>/<meter_serial>/<bill_date>`,
  still derived fresh on every render, still never stored in the database (ADR 0010). Only the
  set of extensions grew.
