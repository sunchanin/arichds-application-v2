# Hide menu entries the licence does not allow

**Type**: CR — **reverses a recorded decision**, deliberately · **Requested**: owner,
2026-08-26 · **Blocks**: nothing

## What is being asked

Today every page appears in the left nav regardless of the licence. Clicking one the customer did
not buy loads the page, which then says the feature is not enabled. The owner wants those entries
**not shown at all**.

## This reverses a decision that is written down

`web/src/components/AppShell.tsx:84-87` records the current behaviour and its reason:

> The API answers `FEATURE_DISABLED` on a machine whose `.env` omits the ops-only `app_log` key;
> the page shows that **inline rather than hiding the menu entry**, since whether the feature is
> on is not this shell's business to know in advance.

That reasoning is not only philosophical — it is also literally true of the current API (below).
Reversing it is the owner's call; this issue is not a bug report and the existing behaviour is not
a defect. **Do not treat the old comment as stale text to delete** — replace it with one recording
the new decision and this issue, the way the codebase does elsewhere.

The argument for the change: a customer who sees six greyed-out pages reads the product as broken
or as nagging them to buy. A customer who sees only what they bought reads it as theirs.

The argument against, worth keeping in view: a hidden entry is also an undiscoverable one — nobody
finds out the feature exists, and support cannot say "click X and read what it says". If the owner
wants both, the middle path is hiding by default with one "Show what else ARICHDS can do" link;
decide explicitly rather than drifting into it.

**DECIDED at implementation (2026-08-26, D9): hiding is total — no upsell affordance.** The owner's
stated goal is that a customer sees only what they bought, and a "Show what else ARICHDS can do"
link re-introduces exactly the nagging this CR removes. Discoverability is answered instead by the
**License card on Settings**, which is never hidden and now carries an "Enabled features" row: so
support can always say "open Settings → License" and read the effective set back.

## The blocker: the frontend cannot currently know

`LicenseStatus` (`app/src/arichds/api/license.py:34-53`, mirrored at `web/src/api.ts:27-35`)
carries `machine_id`, `state`, `reason`, `customer`, `mode`, `expires_at`, `max_meters` — and
**no feature list**. The SPA has no way to ask what is licensed; it only ever discovers a feature
is off by calling an endpoint and being refused. *(State at filing. Resolved by this issue —
`enabled_features` now ships on that model; see the amendment on criterion 1.)*

So this is a backend change first: the licensed feature set has to reach the client before any
menu can be filtered. `features: null` in the payload means "all features" (the current internal
convention — the live licence on the reference machine has exactly that), and the API contract
must say so, because `null` and `[]` mean opposite things here and getting them backwards hides
every menu entry on an unlimited licence.

## Two things that must not change

1. **Hiding is not a gate.** Every `require_feature` / `feature_enabled` check stays exactly as it
   is. A nav filter is cosmetic; the entitlement lives on the server. A test should assert an
   endpoint still refuses while its menu entry is hidden — otherwise the next reader assumes the
   menu is the enforcement.
2. **The inline "not enabled" message stays.** A page can still be reached without its menu entry
   — a stale `page` in component state (which `App.tsx:222-232` already defends against for
   role demotion), a licence that changes while a page is open (ADR 0001 makes that immediate), or
   a bookmark. Removing the message would turn those into a blank or broken page.

## The part that will be got wrong: a page is not one feature

Mapping "menu entry → feature key" is not one-to-one, and hiding on the wrong key removes a page
the customer paid for:

- **Billing** needs `billing`. But `billing_excel_export` and `billing_image_export` gate
  *controls on that page*, not the page. A licence with `billing` and neither export must still
  show Billing — with the buttons refusing, which is precisely the inline behaviour above.
- **App Log** is gated on `app_log`, which is **ops-only and not in `SELLABLE_FEATURE_KEYS`**. It
  is not something a customer buys, and it is already admin-only. Decide its rule separately and
  state it.
  **DECIDED at implementation (2026-08-26, D6): the same rule as every other key** — it maps to
  `app_log` and its entry hides when that key is not effective. One rule with no exception to
  remember; and because an empty/unset `.env FEATURES` expands to all of `FEATURE_KEYS`, the entry
  is present on every default install and disappears only where an operator deliberately excluded
  it — on a machine where the page 403s anyway. `AppLog.tsx`'s inline `Result` stays as the
  server-driven backstop.
- **Settings** is not feature-gated at all and must never be hidden — it is where the customer
  goes when something is wrong.
- **Devices**, **Login**, **User Management** are not feature-gated either.
- **Data-out Destination**: Database maps to `database_destination`; **File Upload is still a
  presentation-only shell** (ADR 0016, issue #37) with no transport and no feature key. Decide
  what it does under this change rather than letting it fall through whichever way the code
  happens to go, and if the whole group ends up empty, hide the group header too — a group label
  with nothing under it is worse than either option.
  **DECIDED at implementation (2026-08-26, D7): File Upload is "never advertised"** until M8 /
  SPEC §3.8 gives it a transport — there is nothing a customer can do with it, and this is also
  what makes the "hide the empty group header" criterion reachable at all (with File Upload
  always visible the group could never empty). "Never advertised" hides the menu entry **only**:
  `FileUploadDestination.tsx` is untouched and still renders normally when reached, because its
  absence from the nav is not a licence matter. It is a third, explicit outcome in the mapping —
  `never` — deliberately distinct from "gated on a key nobody has".

Derive the mapping in one named place and make the exhaustiveness checkable, the way
`dataout/schema.py` derives its columns rather than listing them: a page added later with no
mapping must be a visible failure, not a silently-always-shown entry.

## Acceptance criteria

- [ ] ~~`GET /api/license/status` returns the licensed feature set, with `null` documented as
      "everything" and a test pinning `null` vs `[]` in both directions~~
      **AMENDED at implementation (2026-08-26, D1/D2/D3/D4).** The endpoint returns
      `enabled_features: list[str]` — the **effective** set (`.env FEATURES ∩ licence`), sorted,
      **always present and never `null`**, and `[]` whenever the machine is not active. Three
      reasons the original wording was overruled: (a) `null` would move this issue's own named
      footgun onto the wire and into a second language; (b) expanding `null` client-side would
      duplicate the ten `SELLABLE_FEATURE_KEYS` in TypeScript, so adding a sellable key would
      silently need two edits in two languages; (c) the licence's *raw* list ignores
      `.env FEATURES`, so a machine whose `.env` omits a key would still show that menu entry and
      then refuse the page — precisely the behaviour this CR exists to remove. The `null`-vs-`[]`
      test still runs in both directions, moved to the resolution boundary: a licence with
      `features=None` lists all ten sellable keys, one with `features=[]` lists none of them
      (asserted by name, not by length). Named `enabled_features`, not `features`, because
      `LicenseState.features` already means the licence's raw list.
- [ ] A licence limited to a subset shows only the corresponding entries; an unlimited licence
      (`features: null`) shows every entry it shows today
- [ ] Billing stays visible with `billing` alone; its export/capture controls refuse inline
- [ ] Settings, Devices and User Management are never hidden by this change
- [ ] `app_log` and File Upload rules are decided, implemented and written down
- [ ] The Data-out Destination group header disappears when it would otherwise be empty
- [ ] A test asserts an endpoint still refuses while its menu entry is hidden — the server gate is
      unchanged
- [ ] A page reached without its menu entry still renders the inline "not enabled" message
- [ ] The licence changing at runtime updates the menu without a reload (ADR 0001)
- [ ] `AppShell.tsx:84-87`'s comment is replaced with one recording this reversal and this issue,
      not deleted
- [ ] `ruff format --check .` + `ruff check .` + `python -m pytest -n auto`; `pnpm lint` +
      `pnpm build`

## Blocked by

Nothing. Related: `docs/issues/011` adds a licence surface that should show the same feature list.
