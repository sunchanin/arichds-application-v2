# A capture folder can hold both kWh and Wh documents with nothing marking which

**Type**: AFK · **Found**: ADR 0013, recorded as a shipped gap at M7 (issue #30) · **Supersedes**:
GitHub **#32**, which was filed for exactly this and then **closed without the fix** in a
nine-issue bulk close on 2026-08-24T03:50:25Z · **Re-verified against the code** 2026-09-11

## The problem

A Billing capture is rendered **once, eagerly, at period close** and then kept. The machine-wide
Display unit setting (kW/W, ADR 0013) is read at render time, so flipping it does not restate the
documents already on disk — it changes the next one. The folder a customer is handed ends up:

```
{capture_dir}/{serial}/2026-06-30_000000.pdf   kWh
                      /2026-07-31_000000.pdf   kWh
                      /2026-08-31_000000.pdf   Wh    <- nothing on the outside says so
```

Each file is internally consistent: `scale_label()` moves the column headings with the values,
which was the feature's hard requirement and it holds (`capture/pdf.py:85,93`,
`capture/xlsx.py:53,55`). What is missing is any marking **between** files.

Verified still present 2026-09-11:

- `capture/service.py:58` — the filename stem is `bill_date` only
  (`aware.astimezone(UTC).strftime("%Y-%m-%d_%H%M%S")`). No unit.
- `capture/pdf.py:70-76` — the document header carries Device, Meter Serial and Bill Date. No
  unit line.

## Why it is not merely cosmetic

The unit of a billing document is not decoration; it is the magnitude of the number a customer
may put in front of an auditor. Two documents in one folder, same meter, same naming convention,
differing by a factor of 1000, with the distinction stored **only in a setting that has since
changed** — that is not recoverable from the folder. ADR 0013's whole subject is that a written
artifact cannot retroactively agree with a switch flipped later.

## Why this issue exists and #32 does not close it

ADR 0013:131 says the gap *"needs its own issue"*. `CLAUDE.md`'s ADR digest repeats it. Both are
still accurate, because #32 was closed with the code unchanged — so the repo's own enforcement
mechanism was used correctly and then defeated by bookkeeping. Reopening #32 would put the
history in the right place but leave the record of *how* it was lost on GitHub only; this file
carries both.

**Do not close this by re-reading #32 and concluding it is done.** Check
`capture/service.py:58` and `capture/pdf.py:70-76` for a unit.

## The choice this issue does not make

Two cheap fixes, and they are not equivalent. **The owner picks.**

1. **Put the unit in the rendered document's header**, next to Bill Date. A reader sees it
   without knowing the convention. Does nothing for a folder listing, and does not help
   somebody diffing two files by name.
2. **Put the unit in the filename** — `2026-08-31_000000.kwh.pdf`. Visible in a folder listing
   and to any tooling that globs. But ADR 0015 fixes the three-format filename stem deliberately
   (`{serial}/{bill_date}.{pdf,xlsx,png}`) and the owner chose that shape explicitly, so this
   changes an artifact somebody decided on purpose.

They can also both be done; the header is the one that survives a file being renamed or emailed.

**A third option to reject explicitly**: re-rendering existing captures when the setting flips.
That is exactly the retroactive rewrite ADR 0013 exists to forbid, and it would rewrite documents
a customer may already hold.

## Acceptance criteria

- [ ] A capture document written under either Display unit setting states its unit, by whichever
      mechanism the owner picked
- [ ] A test renders the same billing row under both settings and asserts the two documents are
      distinguishable **by the chosen mechanism** — not merely that the values differ
- [ ] Existing captures on disk are **not** touched, and a test or an explicit note pins that
- [ ] If the filename changes: ADR 0015 gets an amendment saying so, because it fixes the stem
      on purpose, and the render-on-miss download path (`api/billing.py`) still finds files
      written under the old name
- [ ] `pytest -n auto` from `app/` green; `ruff format --check .` + `ruff check .`
- [ ] ADR 0013's "Outstanding" section and `CLAUDE.md`'s digest of it are updated to say the gap
      is closed and by which mechanism — they are the two places that currently advertise it

## Blocked by

The owner's choice between header and filename. Everything else is small.
