# 01: The billing export file

**What to build:** an operator who has set the export output folder gets one growing CSV
per meter, holding every billing period their meter has closed, one row each. They can
press a button on the Billing page to write it immediately instead of waiting for the next
cycle, which is how they prove the folder is right at install time.

This ticket also builds the file-writing machinery the other two export files use: the
five-line file header block, the append-with-fsync write, and the rule that a file whose
head no longer matches what we would write today is closed and a new one opened.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

Source: `.scratch/export-files/spec.md`. Neither v1 nor v2 has ever produced this file —
it is a new artefact, not a port. The customer's samples are in
`.scratch/capture-billing-energy/source/fixtures/`.

## The file

- [ ] Twenty-four columns, in the customer's manual-sample order, always — there is no
      setting that changes the column count. Their other program offers a twenty-column
      variant; a file that appends cannot carry a switchable shape.
- [ ] Header names for the four Export columns use the clean single-spaced form. The
      customer's own files spell them four different ways.
- [ ] A five-line file header block above the column header row: customer, site name,
      meter serial, `Setting : 1`, and the file-type label. The first three come from the
      device row, which already carries them.
- [ ] `Setting : 1` is a literal copied from the customer's samples. **Nobody on either
      side knows what it means** — say so in a comment where it is written, so a later
      reader does not go looking for the setting it names.
- [ ] Only closed periods. The Open Period's Bill Date advances on every read (ADR 0018),
      so including it would append the same period repeatedly under a moving date.
- [ ] `Record No` is the row's ordinal among that device's closed periods ordered by Bill
      Date, computed in the query — not a count of lines already in the file.
- [ ] Rate A, B and C only. No Rate D column.
- [ ] The `Record Status` column carries `closed` on every row.
- [ ] Timestamps use the existing export date-format setting, shared with the Load Profile
      CSV.
- [ ] A timestamp cell the meter never set reads as a dash. **Two shapes reach this
      code**: NULL, which CEWE meters give, and the meter epoch (local 2000-01-01), which
      a SMART TCC gives. Both are "never", and both must produce the dash — an unfiltered
      epoch prints as a date a reader cannot tell from a real one.
- [ ] Numbers carry at most four decimals with trailing zeros and a trailing point
      trimmed, matching the customer's samples. The Load Profile CSV's own formats are
      untouched — that file has an Output Parity obligation this one does not.
- [ ] A cell with no value is empty, never `0` and never `None`.

## The shared file machinery

- [ ] One helper writes any of the three export files: it reads the existing file's head,
      compares it against the head we would write now, and when they differ renames the
      existing file with today's date appended before the extension and starts a new one.
      A name already taken takes a numeric suffix.
- [ ] The comparison covers **both** the file header block and the column header row, so
      renaming a site starts a new edition rather than leaving the file claiming a name
      that was not in effect when its rows were written.
- [ ] Every roll is logged.
- [ ] Reading the head reads a few lines, never the whole file.
- [ ] Ordering is unchanged from the Load Profile CSV's: query, format, append and fsync,
      and only then advance and commit the watermark. A write failure leaves the watermark
      alone and the rows retry.

## Wiring

- [ ] A new watermark column on the device row (never a table, ADR 0008), following the
      Load Profile CSV's own watermark. An unset watermark exports everything stored.
- [ ] The existing CSV export job writes this file too — one job, one interval, one output
      folder, one auto-save switch. Each file is written inside its own error boundary, so
      a billing file that cannot be written does not stop that device's Load Profile file.
- [ ] A filename template setting for this file, beside the Load Profile CSV's, on the
      Export Format page.
- [ ] A Save-now action and a button on the Billing page, mirroring "Save CSV now" on the
      Load Profile page.
- [ ] Rides the `billing` feature key. **No new feature key** — a new sellable key is
      absent from every licence already signed with an explicit feature list, silently and
      for ever.

## Documentation

- [ ] ADR 0013 gains an amendment: a file that appends is a contract, and a contract that
      changes opens a new edition rather than being rewritten in place. Amend 0013 rather
      than writing a new ADR — this is that decision's next step.
- [ ] `CONTEXT.md`'s Export Format entry stops describing one file and starts describing
      the set.
- [ ] `SPEC.md` records the new file.

## Gate

- [ ] `ruff format --check` and `ruff check` pass.
- [ ] `pytest -n auto` passes — the full suite, never a subset.
- [ ] `pnpm lint` and `pnpm build` pass.
- [ ] Tests read the produced file off disk and assert its content: the header block, the
      twenty-four columns, the exclusion of the Open Period, `Record No`, the dash for both
      absent shapes, decimal trimming, and the roll — old file renamed, new file opened,
      and no row written under a header that does not describe it.
