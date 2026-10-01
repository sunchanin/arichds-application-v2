# 01: A device's brand is always a catalog key

**What to build:** Opening any existing device never shows its own model as
"(not licensed on this machine)" when the licence covers it, and the Devices page's Model
filter lists display names only. Today device `Prometer100_4059` stores its brand as `CEWE`
while the catalog and the other three devices use `cewe`; the device form compares brands
with `===`, finds no catalog entry for `CEWE`, and falls through to the "not licensed" label
— the same mismatch puts a raw `CEWE · prometer100` entry in the Model filter and shows the
brand as `CEWE` on one page and `cewe` on another. A brand is a catalog key (SPEC §3.3, the
locked catalog): it is normalised on the way in and the rows already written are brought
into line.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] A migration rewrites every `devices.brand` whose value differs from a catalog brand key
      only by case to that key; a row whose brand matches no key even case-insensitively is
      left as is (it is the "no driver in this build" case the form already names).
      Test: a row seeded with `CEWE` reads back `cewe` after upgrade; a row seeded with
      `acme` is unchanged.
- [ ] Create and Update accept a brand in any case and store the catalog key; a brand that
      matches no key is refused with a 422 naming the accepted brands. Test: creating with
      `CEWE` stores `cewe`; creating with `acme` is refused. Mutation probe: dropping the
      normalisation turns the first test red.
- [ ] The device form's model list is built by comparing catalog keys, so a device whose
      brand was normalised shows its model's display name ("Prometer 100") with no suffix.
      The two suffix labels ("not licensed on this machine" / "no driver in this build")
      still appear for the cases they name — a test for each.
- [ ] The Devices page Model filter shows one display name per model and never a raw
      `brand · model` key.
- [ ] The brand is rendered from the catalog's display name everywhere the UI shows it, so
      it reads the same on the tree, the form and the filter.
- [ ] `antd-ui` skill invoked for the web change; `fastapi` skill for the API change.
- [ ] Gate: `ruff format --check .` + `ruff check .` + `pytest -n auto` green in `app/`;
      `pnpm lint` + `pnpm build` green in `web/`.
- [ ] After install on the dev machine, the `Prometer100_4059` device page shows
      "Prometer 100" and Settings → License still says "Licensed models: All models".
