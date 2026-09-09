# 03: Tell the operator when a holiday change has left an energy file stale

**What to build:** an operator who adds, edits or deletes a Holiday is told, then and
there, that energy files have already written the day they just changed — and how many
meters are affected. The message points them at the Save button on the Energy Summary page,
which is how a corrected file is produced.

A holiday dated in the future says nothing at all, because nothing has been written for it
yet. That silence is what makes the warning mean something when it appears.

**Blocked by:** 02 (the energy watermark has to exist before anything can say a day was
already written).

**Status:** ready-for-agent

Source: `.scratch/export-files/spec.md`.

## Why this exists

The Energy Summary is derived on every request precisely so that entering a holiday today
changes what last January reports tomorrow (ADR 0012). A file written last night froze
yesterday's arithmetic. The file is right to exist — it outlives the ninety-day retention
on the readings behind it — but nothing else in the product would ever tell the operator
that the file and the screen have parted company.

## Behaviour

- [ ] Adding, editing or deleting a Holiday whose date is already past a device's energy
      watermark raises a warning naming how many meters' files hold that day.
- [ ] A Holiday whose date no file has reached raises nothing.
- [ ] The warning names the remedy: re-save that range from the Energy Summary page.
- [ ] It is a persistent notification, not a toast. It asks the operator to do something
      later, and a message that disappears after three seconds cannot.
- [ ] **The count is computed on the server and returned finished by the Holidays
      endpoint.** The page cannot see the watermarks, and a page that derived the count
      would be guessing.
- [ ] Saving the Holiday itself is never blocked or confirmed away. The holiday is correct;
      it is the file that is behind.

## Gate

- [ ] `ruff format --check` and `ruff check` pass.
- [ ] `pytest -n auto` passes.
- [ ] `pnpm lint` and `pnpm build` pass.
- [ ] Tests cover, at the endpoint: a past date with files written past it reports the
      right count; a past date on a machine whose files have not reached it reports zero; a
      future date reports zero; and a delete reports the same way an add does.
