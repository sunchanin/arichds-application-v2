# The Database Destination form blocks the empty Host its own text promises

**Type**: AFK · **Status**: ready-for-agent · **Found**: implementing `docs/issues/022`, 2026-09-18 —
the grep that checked the built bundle for the removed "A host is required" rule found one copy
left, and it was this page's · **Blocks**: nothing shipped · **Blocked by**: nothing (022 is the
precedent, already implemented)

## The problem

`web/src/pages/DatabaseDestination.tsx` says, under Last sync: *"The sync is off while Host is
empty. Save a host and a database to start it; it then runs every fifteen minutes."* — and the API
agrees: `api/settings.py`'s `DatabaseDestinationIn.host` is documented "Empty means not configured
— the sync then returns immediately", and the save accepts it. But the form itself carries
`rules={[{ required: true, whitespace: true, message: "A host is required." }]}` on Host, so an
operator who clears the host to stop the sync is told "A host is required." and the sync keeps
connecting every fifteen minutes. Exactly the class of bug `docs/issues/022` removed from the FTP
page; the FTP fix left this sibling's form untouched because the grill had taken the page's text at
face value.

ADR 0020's Mirror Window makes this worse than on the FTP page: a sync that cannot be stopped keeps
**deleting** past-window rows from the customer's database (`_purge_destination`) as well as
writing — the operator's only way to stop that today is to break the credentials on purpose.

## What to do

- Drop the `required` rule from Host on `DatabaseDestination.tsx` (keep the placeholder; Port stays
  required, it is prefilled). Do the same for **Database** only if the API's "Empty means not
  configured, same as host" makes it equally an off state — it does (`api/settings.py`, the
  `database` attribute) — so drop it there too, and let the existing sentence stand as the
  explanation.
- No API change: the save already accepts both empty; `dataout/sync.py` already returns on an
  empty host/database. Confirm by reading, and cite the lines in the report.
- No 022-style "only when active" guard is needed: this page has one tab, so an empty save cannot
  switch a *different* destination off by accident.
- Do **not** touch the Test saved connection flow or the Mirror Window purge.

## Acceptance criteria

- [ ] `pnpm lint && pnpm build` pass; the built bundle no longer contains "A host is required"
      (`grep -o "A host is required" web/dist/assets/*.js` is empty) — this is the seam the web has.
- [ ] By eye on the page: Host can be cleared and saved; the Last sync card then reports the sync as
      not configured on the next cycle (or Refresh). Say plainly if this was not run against a live
      backend.
- [ ] `app/tests/test_dataout_config_api.py` (or wherever the Database Destination save is tested)
      gains one test: saving with `host=""` (and one with `database=""`) → 200, the stored value
      empty, `dataout`'s cycle publishing its not-configured outcome without opening a connection —
      find the existing not-configured test in `test_dataout_sync.py` and reuse its shape.
      *Mutation*: make the cycle attempt a connection on an empty host → red.
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `pytest -n auto` in `app/` (foreground, no
      pipe), plus `pnpm lint && pnpm build` in `web/`.
- [ ] **Real-meter read / Output Parity**: not applicable — no acquisition or export code is
      touched; say so.
- [ ] One sentence in `CLAUDE.md`'s ADR 0016/0020 digest (the Database Destination paragraph)
      recording that the form now allows the empty host the page always promised.

## Evidence

- `web/src/pages/DatabaseDestination.tsx` — the Host `Form.Item` rule and the "sync is off while
  Host is empty" sentence in the same file.
- `app/src/arichds/api/settings.py` — `DatabaseDestinationIn` attribute docstrings for `host` and
  `database` ("Empty means not configured").
- `docs/issues/022` and the ADR 0025 Consequences bullet it added — the precedent and the corrected
  sentence that points here.
