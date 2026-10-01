# 02: The Energy Summary export file

**What to build:** an energy manager gets the Time-of-Use daily split written to a file in
two ways. The scheduler appends a row per meter per day, so the split survives long after
the interval readings it came from have been purged. And a button on the Energy Summary
page writes the range currently on screen, which is how a corrected file is produced after
a holiday is entered late or readings arrive through a backfill.

**Blocked by:** 01 (the file-writing machinery, the header block and the roll rule).

**Status:** ready-for-agent

Source: `.scratch/export-files/spec.md`.

## The file

- [ ] `Date` plus the eight Time-of-Use columns the Summary Report tab shows — peak,
      off-peak, holiday and total, import and export.
- [ ] **No total row in either form.** A total row cannot exist in a file that appends, and
      giving the on-demand file one would leave two shapes for one concept. The total
      belongs to the screen.
- [ ] Both forms share one layout, one header block and one set of columns.
- [ ] Same header block, decimal formatting and date formatting as the billing file.
- [ ] Nothing is persisted and nothing is read back. **ADR 0012 is untouched** — the
      summary is still derived on every request; a file is a snapshot somebody chose to
      take, not a cache.

## The daily file

- [ ] A new watermark column on the device row, following the Load Profile CSV's own.
- [ ] Written by the same export job as the other two files. It does nothing on a pass
      where the local day has not advanced, rather than carrying its own interval.
- [ ] **The watermark advances whether or not a row was written.** A day with no interval
      readings produces no row and is never revisited. Holding the watermark until a day
      produces a row turns a genuine data gap into a window the job re-queries for ever
      with nothing to report it — this codebase has shipped that bug before.
- [ ] The consequence is real and goes in the code comment, not just here: readings that
      arrive late through the ninety-day load-profile backfill never reach the daily file.
      Together with a holiday entered after the fact, that is exactly two reasons the file
      can be stale, and the on-demand save is the single corrective for both.

## The on-demand save

- [ ] A button on the Energy Summary page writes the device and date range currently
      selected.
- [ ] Its filename carries the range, so it never collides with the daily file.
- [ ] It writes into the same output folder as everything else, server-side — not a
      browser download. The product has no second delivery channel and the customer's
      Syncthing sees only the folder.
- [ ] Rides the `energy_summary` feature key. **No new feature key.**

## Reuse

- [ ] The daily rows and the on-demand rows come from the same aggregation the Summary
      Report tab uses. The exporter calls that function directly; it never issues an HTTP
      request to our own API.

## Gate

- [ ] `ruff format --check` and `ruff check` pass.
- [ ] `pytest -n auto` passes.
- [ ] `pnpm lint` and `pnpm build` pass.
- [ ] Tests read both produced files off disk and assert their content, including a device
      whose range contains a day with no stored readings: that day is absent from the file
      and **the watermark has still moved past it**.
