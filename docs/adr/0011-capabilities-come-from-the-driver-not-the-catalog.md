# A model's capabilities come from its driver, not from the catalog

Status: accepted (2026-08-11, owner decision during M7 grilling). **Fully implemented.** M7-1
(issue #28) landed `supports_energy_registers()`/`read_energy_registers()` and
`supports_special_days()`/`read_special_days()` on `MeterDriver`, implemented on `smw110.py`
and `smart_tcc.py`. M7-2 (issue #29) landed the third flag: `supports_battery()`/
`read_battery_status()` on `MeterDriver`, implemented on the three CEWE models
(`prometer100.py`, `saral305.py`, `premier550.py`) via the shared `_dlms.py` free function
`read_battery_status_via()`, and the catalog's `supports_battery` corrected from all nine
models to exactly those three. `test_catalog.py` now asserts the driver-catalog correspondence
this ADR calls for (`TestCapabilityFlagsMatchTheDriver`, covering all three flags) in place of
the three hardcoded-list tests it names below. The `supports_energy_summary`/
`supports_special_days` *values* already matched what this ADR proposes — the 2026-08-11 ST-3CL
probe (`docs/meter-notes/`) confirmed both on real hardware, so no flag flip was needed for
those two.

Reverses a rule this repo states about itself. `CLAUDE.md` lists among the invariants:

> *"OBIS/register maps and vendored Gurux (`GX*.py`) are copied from v1 verbatim — they are
> field-proven; never 'improve', rename, or reformat their APIs."*

and `acquisition/catalog.py` opens by extending that to itself: its keys, brands, order and
capability flags are *"customer-confirmed and are **locked**"*. This ADR changes six flag
values in that locked file, so it owes an explanation.

## What the flags actually say versus what v1 does

The catalog carries three capability booleans per model. Grepping v1 for the driver methods
those booleans promise gives a different answer on every one:

| Flag | Models the catalog marks `True` | Drivers that implement it in v1 |
|---|---|---|
| `supports_battery` | all 9 | **3** — `prometer100`, `saral305`, `premier550` (`drivers/_cewe_battery.py`) |
| `supports_energy_summary` | 6 (TCC ×5 + `smw110`) | **1** — `smw110` |
| `supports_special_days` | 6 (TCC ×5 + `smw110`) | **1** — `smw110` |

```
$ grep -rln "def read_energy_summary" drivers/   →  base_driver.py  smw110.py
$ grep -rln "def read_special_days"   drivers/   →  base_driver.py  smw110.py
$ grep -rln "def read_battery_status" drivers/   →  base_driver.py  _cewe_battery.py
                                                    prometer100.py  saral305.py  premier550.py
```

`base_driver.py` is the one that raises `FeatureNotSupportedError`. So on fourteen of the
eighteen model-by-feature cells above, the catalog promises a capability that has never
existed, in either product.

v1 knew. `worker/battery_reader.py` says so in its own docstring — *"Scope is CEWE-only for
now … `smw110` keeps raising `FeatureNotSupportedError`; the catalog gate skips it"* — and
worked around its own catalog with a second gate at the call site. The flags were a roadmap
that nobody moved back to `False` when the roadmap did not happen.

## Why "copied verbatim" does not protect these

The verbatim rule protects things whose *value* was established by contact with a meter: an
OBIS address, a scaler, a vendored wrapper's API. Getting those "right" from first principles
is how v1's bugs were made, and the rule exists to stop that.

A capability flag is not that kind of value. It is a claim about our own code — whether a
`read_*` method exists — and our own code is the authority on it. Copying it verbatim
propagated a claim that was false when written and stayed false for a year.

The keys, brands, dropdown order and fixed passwords stay locked. Those are customer-confirmed
and this ADR does not touch them.

## What a lying flag costs at M7 specifically

Until M7 the flags had no consumer, which is why the drift survived. M7 gives them three: the
Battery, Energy Registers and Special Days pages each build a device dropdown by filtering
`CATALOG` on their flag. Ship the flags as they are and the customer gets a selector that
offers a meter and an error when they pick it — the product telling them, in its own UI, that
it does not know what it can do.

The failure is also silent in the direction that matters least: a page that offers too few
meters gets a support call; a page that offers too many gets a customer who concludes the
product is broken.

## Decision

**1. The driver is the authority.** `read_battery_status()`, `read_energy_registers()` and
`read_special_days()` become capability methods on `MeterDriver`, defaulting to
`NotImplementedError` the way `read_load_profile()` and `read_billing()` already do. Generic
code asks the driver.

**2. The catalog flags are corrected to what the drivers do**, and are maintained that way:

| Flag | M7 value |
|---|---|
| `supports_battery` | CEWE ×3 only |
| `supports_energy_summary` | `smw110` + SMART TCC ×5 |
| `supports_special_days` | `smw110` |

**3. A flag is turned on by evidence from a meter, never by a datasheet.** The TCC entries
above are the test case: the catalog claimed all five TCC models for a year with no driver
behind it, and the thing that made them real was `scripts/probe_tcc.py` reading
`1.0.{1,2,3,4}.8.0.255` off a live ST-3CL and getting four answers with correct units
(`docs/meter-notes/tcc-3cl-serial-scan.md`). The per-tariff addresses `E=1..4` and the special
days table are unproven at the time of writing and the probe now asks about both; whichever way
it answers, that answer sets the flag.

## What this costs

**The catalog stops describing the world and starts describing this build.** A customer whose
SMART TCC does have a backup battery will see no Battery page, because we have not written the
read. That is a real loss of information, and the honest version of it: the flag now means *"we
can"*, not *"the meter can"*.

`test_catalog.py` asserted the aspirational values — `test_every_model_reports_battery`,
`test_the_new_brands_have_both`. Those tests were written to lock the catalog against drift, and
both are now gone: `test_the_new_brands_have_both` was removed with issue #28 (the
energy-summary/special-days correspondence test replaced it), and `test_every_model_reports_battery`
was removed with issue #29, folded into the same `TestCapabilityFlagsMatchTheDriver` correspondence
class the other two flags already use — every model flagged `True` resolves to a driver that
implements the method, a test that cannot go stale the way a hardcoded list can.

## What was rejected

**Leave the flags and let the call site gate**, exactly as v1 did. It is the smallest change
and it is what "copied verbatim" would produce. Rejected because it keeps the lie in the one
file whose entire job is to be the vocabulary, and because M7's dropdowns read the catalog, not
the call site — v1's second gate protected a background daemon, not a UI.

**Implement all three features on all nine models.** Rejected because five of the nine cannot
be reached from this machine at all, so it means inventing OBIS addresses for meters we cannot
test — the practice `docs/meter-notes/` exists to prevent.
