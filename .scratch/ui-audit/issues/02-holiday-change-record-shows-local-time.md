# 02: The Holiday Change record shows local time

**What to build:** The Change history drawer on the Holidays page shows when a change was
made in the machine's local time, like every other timestamp in the app. Today a change made
at 11:10 (+07:00) is listed as `04:10`: the row's `created_at` leaves the API without a UTC
offset (SQLite hands `DateTime(timezone=True)` back naive — `docs/issues/006`), and the page
formats an offset-less string as if it were already local. This is a new instance of the
class issue 006 describes, introduced with M14 ticket 06; fix this instance the way the other
fifteen call sites do, without refactoring them.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `GET /api/holidays/changes` returns every `created_at` as an aware UTC instant (an ISO
      string carrying `+00:00` or `Z`). Test: the response's `created_at` parses with
      `tzinfo` not `None`. Mutation probe: removing the re-attachment turns it red.
- [ ] The drawer renders the instant in the browser's local time — a row stored at
      `04:10 UTC` reads `11:10` on a +07:00 machine. A render test (the repo already
      renders pages outside the browser for evidence) or a recorded manual check on the dev
      machine.
- [ ] The App Log line for the same change and the drawer row agree on the wall-clock time.
- [ ] No other call site is touched; the change is confined to the Holiday Change read path
      and its page.
- [ ] Gate: `ruff format --check .` + `ruff check .` + `pytest -n auto` green in `app/`;
      `pnpm lint` + `pnpm build` green in `web/`.
