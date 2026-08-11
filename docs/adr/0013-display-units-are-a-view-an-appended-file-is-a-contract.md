# Display units are a view setting; an appended file is a contract

Status: accepted (2026-08-11). The machine-wide kW/W setting **is implemented** (Billing, Load
Profile, Records, and the two capture renderers — commit `bbdd6b7`); the boundary this ADR
draws is applied to the Load Profile CSV at M7, and one shipped gap is recorded below as
outstanding.

Reverses a v1 feature: `format_settings.divide_by_1000`, which v1 shipped **on by default**, is
not ported. A customer who knows that switch will ask where it went.

## Two switches on one axis

The customer asked for a machine-wide choice between kilo and base units, covering power *and*
energy, on Billing, Load Profile, capture files and Records. That shipped as a `settings` key
with `scale_value()` / `scale_label()` in `capture/_render_shared.py`.

While planning M7 it turned out v1 already had a switch on the same axis, reached from a
different direction:

```
v1:  stores Wh   →  divide_by_1000  →  the export file reads kWh
v2:  stores kWh  →  scale switch    →  the surface reads kWh or Wh
```

v2 does v1's division at write time, in the driver, before the row exists — the write-time
normalization invariant. So `divide_by_1000` has nothing left to divide; porting it would give
two controls on one axis that can disagree (`divide_by_1000` off **and** display set to kilo
has no correct answer). Default-to-default the two systems agree on kWh, so Output Parity
survives dropping it.

That much was straightforward. The part that was not is *where the surviving switch is allowed
to reach*.

## The mistake this ADR exists to prevent

The M7 grill first decided the Load Profile CSV should follow the display switch — one switch,
one behaviour everywhere, which reads like the tidy answer. Scrutinising the plan against the
export path showed it is wrong, and wrong in a way that produces silently corrupt data:

- The exporter **appends**. A per-meter file accumulates for months (`SPEC.md` §3.5, from v1's
  `worker/lp_csv_exporter.py`).
- The header is written **once**, when the file is absent or empty — never rewritten.

So an operator who flips the switch to read a screen in month four leaves a file whose header
says `(kWh)` above rows that are now Wh. A thousandfold discontinuity, mid-file, with nothing
marking it, in the artifact the customer's own downstream tooling reads.

v1 was safe from this by placement rather than by argument: `divide_by_1000` lived on the
Export Format page, so the person touching it was already thinking about files. Collapsing two
switches into one destroyed that protection without anyone noticing it was protection.

## The rule

**A destination that is written once per view follows the display setting. A destination that
is appended to across time does not — it has a fixed unit, and that unit is kilo.**

| Destination | Written how | Follows the switch |
|---|---|---|
| Billing / Load Profile / Records pages | rendered per request | ✅ |
| Billing capture `.pdf` / `.xlsx` | rendered per document | ✅ (see gap below) |
| **Load Profile CSV auto-export** | **appended, months long** | ❌ always kWh/kvarh |

The test is not "is it a file" — it is *does this artifact have a past that my change would
contradict?* A re-rendered document has no past: change the setting, download again, the whole
document is consistent. An appended file's past is on disk and cannot be revised.

Apply this rule to every new destination. M8's push payload is the next one — it accumulates on
a server across time, so it is base-unit-fixed by the same test, and the unit belongs in the
contract rather than in a setting the site can change.

## Outstanding: the capture folder is a half-case

Captures sit on the wrong side of their own row above, and this ADR records it rather than
quietly claiming otherwise.

A capture is rendered per document — but it is written **eagerly at period close** and then
kept (`capture/__init__.py`: *"the eager write in `acquisition.billing` and the render-on-miss
download"*). Flipping the switch therefore does not restate the captures already on disk; it
changes the next one. The folder ends up:

```
{capture_dir}/{serial}/2026-06-30.pdf   kWh
                      /2026-07-31.pdf   kWh
                      /2026-08-31.pdf   Wh    ← nothing on the outside says so
```

Each file is internally consistent, because `scale_label()` moves the column headings with the
values — that was the feature's one hard requirement and it holds. What is missing is any
marking *between* files, so a folder handed to a customer can carry both units.

This is a shipped gap, not an M7 decision, and it is **not fixed by this ADR**. It needs its
own issue, and the plausible fixes are cheap: put the unit in the rendered document's header
where a reader will see it, or in the filename. It is recorded here because this is where a
future reader will come looking for why the rule has an exception.

## What was rejected

**Port `divide_by_1000` as its own Export Format control.** Restores v1's placement exactly and
keeps the file switchable. Rejected because it re-creates two controls on one axis — the
original problem — and because a file whose unit is switchable at all still has the append
discontinuity; the placement only makes it likelier that whoever pulls the trigger meant to.

**Rewrite the CSV header when the scale changes.** A header that no longer describes the rows
above it is not fixed by describing the rows below it. The only honest version is a new file,
which breaks the one-file-per-meter contract the customer's tooling depends on.
