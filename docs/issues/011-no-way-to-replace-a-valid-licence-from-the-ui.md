# A licence that still works cannot be replaced from the UI

**Type**: AFK · **Found**: while testing feature gating, 2026-08-26 · **Blocks**: selling a
feature upgrade to an existing customer

## The problem

The Activation page is a gate, not a settings page. `web/src/App.tsx:218`:

```tsx
if (status.state !== "active") {
  return <Activation status={status} role={session.role} onActivated={...} />;
}
```

It renders **only** when the licence is missing, expired or invalid. There is no nav entry and no
route to it. So on a machine whose licence is working there is nowhere to paste a new Activation
Code.

The backend has no such limit: `POST /api/license/activate` (`app/src/arichds/api/license.py:93`)
is admin-gated but carries **no "must be inactive" check** — it verifies, installs and takes
effect immediately, whatever the current state. The capability exists; only the surface is
missing.

## Why it matters

Every ordinary licence change hits this:

- a customer buys a feature they did not have at install
- a customer adds meters and needs a higher `max_meters`
- a leased licence is renewed **before** it lapses, which is the whole point of renewing

Today each of those ends with someone telling the customer to delete
`%ProgramData%\ARICHDS\license\license.lic` and reload the page — teaching a customer to delete
the licence file to install a licence. If they do it wrong, or the new code is bad, the machine
sits in Limited Mode with polling stopped.

The renewal case is the sharpest: a lease exists so a site keeps working offline, and the only
way to renew it is to first break it.

## What to do

Put the Activation Code field somewhere reachable while active — the Settings page is the
natural home (it already shows machine-wide settings and is admin-gated for changes). Show what
is licensed now (customer, mode, expiry, `max_meters`) and accept a new code.

Keep the existing gate screen exactly as it is for first run and Limited Mode. This adds a second
entrance; it does not move the first.

Two things to decide and state:

- **A rejected code must change nothing** — the endpoint already guarantees this ("A rejected code
  changes nothing: the stored license and the current state are left exactly as they were"). The
  page must make that visible, so an operator who pastes the wrong line is not left wondering
  whether they just broke a working machine.
- **A valid code that licenses *less* than the current one** is a downgrade and applies silently
  today. Decide whether to confirm first. Not hypothetical: `docs/issues/010` shows a typo'd
  feature list signs cleanly, so the downgrade may be an accident rather than a sale.

## Acceptance criteria

- [ ] An admin can paste an Activation Code while the current licence is active, and it takes
      effect without a restart (ADR 0001) and without touching the licence file by hand
- [ ] The current licence's customer, mode, expiry and `max_meters` are visible on that surface
- [ ] A rejected code leaves the machine exactly as it was, and the page says why it was rejected
      (wrong machine / expired / tampered), proven by a test per reason
- [ ] A `user` cannot reach or use it; the existing admin gate on the endpoint is unchanged
- [ ] The first-run / Limited Mode Activation screen is unchanged
- [ ] The downgrade question above is decided and the decision is written down
- [ ] `ruff format --check .` + `ruff check .` + `python -m pytest -n auto`; `pnpm lint` +
      `pnpm build`

## Blocked by

Nothing. Related: `docs/issues/012` also adds `features` to the licence status — if both are
built, that field belongs on this surface too.
