# `arichds_vendor.py sign` accepts any feature name, including ones that do not exist

**Type**: AFK · **Found**: while issuing a test licence, 2026-08-26 · **Blocks**: nothing today —
but the failure it allows is silent and reaches a paying customer

## The problem

`--features` is written straight into the signed payload with no validation. A misspelling is
signed happily:

```
$ python tools/arichds_vendor.py sign --customer "typo test" \
    --machine-id 50aa2362... --features "load_profile,databse_destination"
                                                     ^^^ 'a' missing
Customer   : typo test
Mode       : offline
Expires    : never
Max meters : unlimited

ACTIVATION CODE (send this single line to the customer):
<a perfectly valid, correctly signed code>
```

`databse_destination` is not in `SELLABLE_FEATURE_KEYS` (`app/src/arichds/constants.py`). The
code verifies, installs, and activates. The feature the customer paid for is simply off.

## Why it matters

The vendor CLI is the only place a feature name is typed by a human, and it is typed once per
sale. Every other use of these keys is a symbol the type checker or the test suite would catch.

The failure surfaces as *"we bought that, why is it not there"*, days later, on the customer's
machine. Whoever investigates starts on the product side — the gate, the licence service, the
page — because the licence "is valid". Nothing points at a typo in a command line run in another
office.

This is the same shape as `docs/issues/009`: **a tool reporting success while doing the wrong
thing.** The vendor tool has no reviewer and no test between it and a customer, which makes it
the worst place in the system for a silent accept.

## What to do

Validate `--features` against `SELLABLE_FEATURE_KEYS` and refuse the run, naming every key it
did not recognise and listing the valid ones. Import the constant rather than restating the list —
a second copy in `tools/` goes stale the next time a key is added, which is exactly what
`database_destination` (issue #46) just did to a nine-key world.

Note `FEATURE_KEYS` = `SELLABLE_FEATURE_KEYS | {"app_log"}`: `app_log` is ops-only and is **not**
sellable, so it must be rejected here too. Validate against the sellable set, not the union.

## Acceptance criteria

- [ ] An unknown feature name makes `sign` exit non-zero and print which name(s) were unknown,
      before anything is signed
- [ ] `app_log` is rejected as not sellable, with a message saying so rather than "unknown"
- [ ] The valid list comes from `SELLABLE_FEATURE_KEYS` by import — a test fails if `tools/`
      grows its own copy
- [ ] A test covers a good list, an unknown name, `app_log`, and empty/whitespace entries
      (`"billing,,records"`, `"billing, records"`)
- [ ] `sign-meter` is checked for the same class of unvalidated pass-through and fixed or
      explicitly cleared
- [ ] `ruff format --check .` + `ruff check .` + `python -m pytest -n auto`

## Blocked by

Nothing.
