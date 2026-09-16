# 07: The pages say what they know

**What to build:** Eight small places where the UI is silent, stale or unexplained — found
by driving every page on the installed 0.6.0 build — each become one sentence or one
affordance. No schema, no API change; this is copy and affordance work across six pages,
reviewed together because each item is a line or two.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

Billing page:
- [ ] The tooltips on **Capture image**, **Save billing file now** and **Read now** actually
      appear, both when the button is disabled ("choose one device first") and when enabled
      (what the button does). Today the Tooltip wraps a disabled Button directly and never
      renders; AntD needs a wrapping element on a disabled child.
- [ ] The All-Meters **Status** chip has a tooltip naming what the state means, and the five
      states carry the colours §7.3 decided (paused > not answering > never billed / behind
      > ok), so an OK is not the same grey as a problem.
- [ ] The **Current** tab carries a caption saying these are Open Periods (CONTEXT.md — Open
      Period): the bill date moves on every read and is not a closed bill.

Other pages:
- [ ] **Special Days** and **Energy Summary → Meter Registers**: when no device on the
      machine supports the capability, the device picker's empty state says so ("No meter on
      this machine exposes Special Days") instead of "No data".
- [ ] **Records**: the `(-N)` suffix on a partial day has a tooltip ("N intervals still to
      come today").
- [ ] **Energy Summary**: switching from Single day back to Range restores the 7-day default
      window instead of collapsing the range to the single day.
- [ ] **Export Format**: the intro names all three files (Load Profile CSV, billing file,
      Energy file) and describes ADR 0023's behaviour — LP appends and is trimmed daily, the
      other two are rewritten whole every cycle — instead of "rows append for months".
- [ ] **Database Destination**: a sentence under the form says the sync is off while Host is
      empty, the way the API page already says it for the push.

Everything:
- [ ] `antd-ui` skill invoked (the page conventions, `App.useApp()` for toasts, English-only).
- [ ] Each item is verified on the dev machine after `pnpm build` and recorded in the ledger
      with the page and the sentence as shown.
- [ ] Gate: `pnpm lint` + `pnpm build` green in `web/`; `ruff format --check .` +
      `ruff check .` + `pytest -n auto` green in `app/` (unchanged backend, still run).
