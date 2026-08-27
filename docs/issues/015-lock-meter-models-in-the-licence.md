# Let a licence name which meter models the machine may add

**Type**: AFK · **Requested**: owner, 2026-08-27 · **Blocks**: nothing · **Blocked by**: nothing
(issues 010–013 are already committed on `feature/light-modules`)

## What is being asked

A licence can already cap **how many** meters a machine runs (`max_meters`) and **which meters**
individually (Meter Activation Code, ADR 0019). It cannot say **which kinds**. The owner wants to
sell by model — "this site is licensed for CEWE only" — and asked specifically whether the choice
can go down to the individual model, not just the brand.

**It can, and it must.** See D1.

## D1 — the payload field is `models`, never `brands`

The obvious design is a `brands` list checked against `devices.brand`. **That gate can be defeated
by typing.**

```
app/src/arichds/api/devices.py:281   brand: str = Field(min_length=1, max_length=64)
app/src/arichds/api/devices.py:960   brand=payload.brand,           # create — written straight to the row
app/src/arichds/api/devices.py:1099  device.brand = payload.brand   # update — same
```

Nothing anywhere compares `payload.brand` to `CATALOG[model].brand`. The form prefills it from
`GET /api/devices/catalog` (`_to_catalog_entry`, `devices.py:636`) but the API accepts any string
up to 64 chars. An operator locked to `cewe` types `cewe` and adds a SMART TCC meter.

`model` is the opposite: `_require_known_model` (`devices.py:645-658`) refuses anything outside
`supported_models()`, and the brand is derivable from it. Verified this run — the driver registry
and the catalog hold **exactly the same nine keys**, no drift in either direction:

| Brand | Models |
|---|---|
| `cewe` | `prometer100`, `saral305`, `premier550` |
| `smart_tcc` | `st3c`, `st3cl`, `st33tl`, `st3tl`, `st3dh` |
| `mitsu` | `smw110` |

So: **the licence payload carries model keys.** Brand-level selling is a convenience at the vendor
CLI — `--brands cewe` expands to that brand's three model keys *before* signing — and the payload
that results is indistinguishable from `--models prometer100,saral305,premier550`. One field in
the payload, one thing to enforce, one null-vs-empty rule to reason about.

**The consequence, stated rather than discovered later:** a licence sold as "all CEWE" is frozen
against future catalog additions. If a tenth model joins CEWE, that customer does not get it until
the code is reissued. That is arguably what a contract should do, and it is the same trade
`--features` already makes (`docs/issues/013`). Do not "fix" it by storing brands alongside models.

## D2 — `None` grandfathers, `[]` forbids, `""` is an error

Mirror `features` exactly (`licensing/features.py:47`):

```python
ceiling = SELLABLE_FEATURE_KEYS if license_features is None else frozenset(license_features)
```

- `models: null` — every licence issued before this lands, plus every code signed without the flag
  — means **every catalogued model**.
- `models: []` means no model may be added at all. Meaningfully different, deliberately.
- **`--models ""` must be a hard error, not "all"** — `docs/issues/014` records that
  `--features ""` currently splits to `[""]`, fails validation, and would otherwise have signed a
  grant-everything licence while the seller believed they had restricted it. Do not reproduce that
  shape here. 014 is still open; this issue must not depend on it being fixed first, and must not
  fix it either.

## D3 — enforce at Create **and** Update

`update_device` assigns `device.model = payload.model.lower()` (`devices.py:1100`). A gate on
create alone is bypassable in principle: add a licensed model, then PUT the row to an unlicensed
one.

There *is* an incidental guard — `_reject_changed_serial` refuses any Update whose probed serial
differs from the stored one, so the row cannot be walked onto a different physical meter. **Do not
rely on it.** It is a side effect of ADR 0005, it depends on a successful probe, and nothing in it
says anything about licensing. The harm here is "an unlicensed model gets polled"; that verb
happens on both legs, so the guard belongs on both legs.

## D4 — where the check goes, and what it answers

Before the probe, after `_require_known_model`:

```
_require_known_model(payload.model)
_require_licensed_model(payload.model, license_service.current_state().models)   ← new
_enforce_quota(session, ...)
_reject_duplicate_name(session, payload.name)
```

A licence refusal is a form error decided locally — nobody should wait out a DLMS association
(Premier 550 was measured at **95.5 s** to connect, ADR 0018) to be told their contract does not
cover the model they picked.

Read the licence **per request** through `LicenseServiceDep`, never at import (ADR 0001) — the
handler already does exactly this for `max_meters` on the line below.

**Derive the status code and error shape from the code, not from this issue.** Read
`app/src/arichds/api/deps.py::require_feature` and `_enforce_quota` (`devices.py:715-742`) and
match whichever convention fits a licence refusal; say in the report which you matched and why.
The message must name the model the operator picked and the models the licence allows — a bare
"not licensed" makes the operator phone the vendor to learn what they bought.

## D5 — the two traps in the Activation Code layer

**Do not add `"models"` to `_REQUIRED_FIELDS`** (`licensing/activation_code.py:59-69`). The
verifier refuses a payload missing any required field as `MALFORMED`. Every licence already
issued — including the one signed on this machine on 2026-08-27 for `f46b6763…b57e0` — has no
`models` key. Adding it there invalidates all of them. It goes in `build_payload` (so new codes
always carry it, explicitly `null` when unrestricted) and is read with `payload.get("models")`
plus a type check, the way `features` is at `activation_code.py:285`.

**Do not bump `PAYLOAD_VERSION`.** The check is `payload.get("v") != PAYLOAD_VERSION` — strict
equality — so v3 would make every v2 licence invalid on the new build.

The consequence of *not* bumping, which must be written down somewhere a reader will find it:
`verify_activation_code` re-canonicalizes the payload it parsed (`activation_code.py:300-310`) and
only checks that the required fields are *present*, so **an extra key verifies cleanly on builds
that predate this change** — they accept the licence and ignore the model lock in silence. A model
lock is therefore a **contractual** control, not a security boundary, exactly like `max_meters`:
an old exe defeats both. Record that in `SPEC.md` §3.9 next to the lock itself, not only here.

## D6 — grandfathering existing devices (owner decision, defaulted)

**Default: the lock governs adding a device, not reading one.** A machine that already polls five
SMART TCC meters and is then issued a CEWE-only licence keeps polling all five; only the next
Create or Update is refused.

The reason is the same one ADR 0019 gave for grandfathering devices that predate the Meter
Activation Code: the alternative silently stops collecting a customer's data, and data loss is not
a licensing mechanism. **Flag this in the report as the one decision the owner should overrule if
it is wrong** — the code change to enforce it at poll time instead is small, but it is not a call
an implementer makes.

## D7 — `GET /api/devices/catalog` (decide, do not assume)

`list_catalog` (`devices.py:833`) feeds the Model dropdown on the Add-device form **and**
`Battery.tsx:74`, which builds its `supports_battery` set from it.

Filtering the endpoint by licence hides unlicensed models from both — coherent with issue 012's
rule that the UI does not advertise what the licence does not allow. It also makes a currently
dependency-free endpoint licence-dependent, and it changes a page this issue is not about.

Pick one, implement it, and say which and why. If you filter, `Battery.tsx` must still behave
correctly for a licence that grants no CEWE model — check it renders an empty state rather than
throwing. **The API gate in D4 stands either way**: hiding an option is not enforcing it.

## D8 — the vendor CLI

`tools/arichds_vendor.py sign` gains `--models` and `--brands`, validated the way `--features`
already is (issue 010): **import the truth, never restate it.** `sellable_feature_keys()`
(`arichds_vendor.py:227-239`) is the pattern — the model list must come from the app's own catalog
by import, so a tenth model needs no edit here.

- An unrecognised model or brand name **refuses the run before anything is signed**.
- `--models` and `--brands` may be combined; the result is the union, deduplicated and sorted.
- Naming every model of a brand and naming the brand produce byte-identical payloads.
- The stderr summary must print the resolved model list, not the flags as typed — the seller has
  to see what they actually signed. It already prints Customer / Machine ID / Mode / Expires /
  Max meters; this joins that block.

**Where the harm lives is `tools/`, not `app/`** — a customer ends up with the wrong entitlement
because of what the *seller* typed. `docs/issues/010` and `013` both shipped guards on the product
side while the sale went unguarded; do not make it three.

## Where else it must reach

Search rather than trusting this list — issue 013's sweep found stale counts nothing had updated:

- `licensing/service.py` — `LicenseState` gains `models: list[str] | None = None`, carried through
  `_from_verification`.
- `api/license.py` — `LicenseStatusOut`. Note it exposes **`enabled_features`** (the effective
  set), not raw `features`; decide whether models get the same treatment or are exposed raw, and
  say why.
- `web/src/api.ts` — the `LicenseStatus` type (`api.ts:34-42`).
- `web/src/components/LicenseCard.tsx` — the descriptions list (`max_meters` at line 102,
  `enabled_features` at 104). A licensed-models row belongs beside them; `All models` is the
  `null` rendering.
- `LicenseCard.tsx:165` — the replace-licence confirm text enumerates what the current licence
  grants so the operator can see what they are about to lose (issue 011). Models belong in it.
- `SPEC.md` §3.9 — the licence surface, plus D5's note about old builds.
- `CONTEXT.md` — if "Licensed Model" (or whatever you name it) becomes a term, it goes in the
  glossary. Reuse an existing term if one fits; do not mint a synonym for `model`.

## Acceptance criteria

- [ ] The payload carries `models`; `build_payload` always emits the key, explicitly `null` when
      unrestricted
- [ ] `_REQUIRED_FIELDS` is **unchanged**, proven by a test that verifies a licence signed
      *before* this change — paste one and verify it, do not construct a fake missing-key payload
- [ ] `PAYLOAD_VERSION` is still `2`
- [ ] `models: null` grants every catalogued model; `models: []` refuses every Create
- [ ] `--models ""` is refused, not read as "all" (D2)
- [ ] Create **and** Update both refuse an unlicensed model, each with its own test (D3)
- [ ] The refusal happens before any socket is opened, proven by a test whose probe would fail if
      reached
- [ ] `--brands cewe` and `--models prometer100,saral305,premier550` produce byte-identical
      payloads, proven by decoding both
- [ ] The vendor CLI's model list is **imported** from the catalog, not restated — proven the way
      `test_vendor_sign_features.py` proves it for features: assert object identity, not equality
- [ ] The stderr summary prints the resolved models
- [ ] D6's grandfathering is implemented as stated, and the report flags it for the owner
- [ ] D7 is decided in writing, and `Battery.tsx` still renders under a licence granting no CEWE
      model
- [ ] The License card shows the licensed models, and the replace-licence confirm names them
- [ ] Docs updated: `SPEC.md` §3.9 including D5's old-build note; `CONTEXT.md` if a term is minted
- [ ] Required tests are derived as a **mutation table** — one row per decision above, each naming
      the mutation that turns it red — and every mutation is actually run. A decision whose test
      stays green under its own mutation is not covered
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `python -m pytest -n auto` in `app/`
      (use `python -m pytest`; the console script under-collects — `docs/issues/004`), and
      `pnpm lint` (**zero** problems) + `pnpm build` in `web/`
- [ ] **Real-meter read** is not applicable — nothing here touches acquisition. Say so rather than
      inventing a check
- [ ] **Output Parity vs v1** is not applicable — v1 had no model entitlement. Say so

## What this issue does not do

- **It does not make `devices.brand` authoritative.** The field stays unvalidated free text and
  keeps its current behaviour; the lock simply does not read it. Whether the brand column should
  be derived from the catalog instead of typed is a separate defect worth its own issue — say so
  in the report if you agree, do not fix it here.
- **It does not touch the Meter Activation Code path.** ADR 0019 still binds each meter
  individually; the two gates stack, exactly as `max_meters` and ADR 0019 already stack.
- **It does not stop an unlicensed model from being polled** once its row exists (D6).
