"""Brand / model taxonomy — the nine models the product knows about (M3-1).

Ported from ``cewe-worker/src/catalog.py``. Its keys, brands, dropdown order and
fixed passwords are customer-confirmed and are **locked**: never change the set
of canonical model strings, the brand of a model, or the insertion order (which
is the UI dropdown order — SMART TCC first, Mitsubishi, then CEWE).

Two v1 fields are deliberately **not** carried over:

* ``driver_status`` — in v2 the **driver registry** is the single source of
  truth for whether a model can be driven, and the catalog endpoint filters
  against :func:`~arichds.acquisition.drivers.factory.supported_models`. A
  duplicated status field would drift from the registry silently, and the first
  symptom would be an operator picking a model that cannot connect.
* ``protocol`` — SPEC §3.3 says there is no Source field in M3, and every
  catalogued model is DLMS today. Modbus arrives after day 5 and will say so on
  the reading, not here (CONTEXT.md — Source is a property of the reading).

This module is **data**. It imports nothing from
:mod:`arichds.acquisition.drivers`: the catalog says what exists in the world,
the registry says what this build can drive, and keeping the two apart is what
stops them from lying about each other.

Fixed credentials per brand (server-side, from the customer answers):

* CEWE — all models use password ``ABCD0001``.
* Mitsubishi ``smw110`` — Low auth. The value is :data:`MITSU_SMW110_FIXED_PASSWORD`
  below and is deliberately not repeated in prose: it was wrong once already
  (until 2026-08-10 the constant carried the password of the **retired** unit
  ``1252008102``, so an operator adding either in-service unit got the wrong
  password prefilled and the create-time probe failed ``AUTH_FAILED``), and a
  second copy in a docstring is a second thing to miss. Both units in service
  share one password — confirmed by the owner, 2026-08-10.
* SMART TCC — does NOT use a simple password. It authenticates with HighGMAC +
  Security Suite 0 keys, which belong to the TCC driver (M4), so
  ``fixed_password`` is ``None`` here. No real TCC keys are stored in this
  module.

The two passwords stay here rather than in ``constants.py`` exactly as they did
in v1: they are catalog data about particular brands, not cross-cutting product
constants. ``DLMS_DEFAULT_TCP_PORT`` is the opposite case — 4059 is a protocol
constant every IP-connected model shares, not a property of any one model, so
it lives here as a bare constant rather than as a per-model field (issue #9
removed ``ModelSpec.default_port`` for exactly this reason — see below).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

# Standard DLMS/COSEM TCP port — shared default for all IP-connected models.
DLMS_DEFAULT_TCP_PORT: Final[int] = 4059

# Fixed passwords per brand (server-side). See the module docstring.
CEWE_FIXED_PASSWORD: Final[str] = "ABCD0001"
MITSU_SMW110_FIXED_PASSWORD: Final[str] = "47895612345896471324"  # Low auth


class Brand(StrEnum):
    """Meter brand — the top of the taxonomy."""

    CEWE = "cewe"
    MITSU = "mitsu"
    SMART_TCC = "smart_tcc"


@dataclass(frozen=True)
class ModelSpec:
    """Immutable taxonomy entry for one meter model.

    **Carries no transport information** (issue #9). The field probe of two
    live SMW110W4 units — one on serial, one on TCP, otherwise identical —
    proved transport is a property of the *installation*, not of the model:
    ``docs/meter-notes/smw110w4-scan.md`` — "The site was reported as holding
    two different models. It does not." Every catalogued model is offered both
    transports; the operator picks per device.

    Attributes:
        brand: Owning brand.
        ui_label: Human-readable label for the Model dropdown.
        supports_battery: True if the model exposes a battery reading.
        supports_energy_summary: True if the model exposes an energy summary.
        supports_special_days: True if the model exposes a special-days table.
        fixed_password: Brand-wide DLMS password, or None when the model uses
            key-based auth (SMART TCC — owned by its driver, M4). A documented
            brand default the Create form prefills, not a per-site secret.
    """

    brand: Brand
    ui_label: str
    supports_battery: bool
    supports_energy_summary: bool
    supports_special_days: bool
    fixed_password: str | None


# ── The catalog ───────────────────────────────────────────────────────────────
#
# Capability-flag rationale (ADR 0011 — the driver is the authority, this
# catalog only mirrors what a real driver implements; `test_catalog.py`'s
# correspondence test fails if the two ever drift):
#   - supports_battery: True for exactly the three CEWE models, whose drivers
#     implement `read_battery_status()` against the CEWE battery-status
#     register 0.0.96.6.1.255 (M7-2, issue #29). False for `smw110` and the
#     five SMART TCC models — no driver in this build implements the read for
#     them; the earlier all-nine value was aspirational (ADR 0011's own "What
#     this costs") and issue #29 is what corrects it.
#   - supports_energy_summary / supports_special_days: True for `smw110` and the
#     five SMART TCC models — confirmed on real hardware (the 2026-08-11 ST-3CL
#     probe: 20 of 20 standalone energy registers answered, and the Special Days
#     Table returned 82 entries). Both hooks — `MeterDriver.read_energy_registers()`
#     / `read_special_days()` (M7-1, issue #28) — are implemented on `smw110.py`
#     and `smart_tcc.py`. Still False for the three CEWE models: those two hooks
#     are unimplemented on CEWE, and no CEWE meter is known to expose either
#     register set.

CATALOG: Final[dict[str, ModelSpec]] = {
    # ── SMART TCC (TCP, key-based auth) ──────────────────────────────────────
    #     Five models, one shared OBIS set / driver. Auth is HighGMAC + Security
    #     Suite 0; the keys live in the driver, so fixed_password=None.
    "st3c": ModelSpec(
        brand=Brand.SMART_TCC,
        ui_label="SMART TCC ST-3C",
        supports_battery=False,  # no driver implements read_battery_status() (issue #29)
        supports_energy_summary=True,
        supports_special_days=True,
        fixed_password=None,
    ),
    "st3cl": ModelSpec(
        brand=Brand.SMART_TCC,
        ui_label="SMART TCC ST-3CL",
        supports_battery=False,  # no driver implements read_battery_status() (issue #29)
        supports_energy_summary=True,
        supports_special_days=True,
        fixed_password=None,
    ),
    "st33tl": ModelSpec(
        brand=Brand.SMART_TCC,
        ui_label="SMART TCC ST-33TL",
        supports_battery=False,  # no driver implements read_battery_status() (issue #29)
        supports_energy_summary=True,
        supports_special_days=True,
        fixed_password=None,
    ),
    "st3tl": ModelSpec(
        brand=Brand.SMART_TCC,
        ui_label="SMART TCC ST-3TL",
        supports_battery=False,  # no driver implements read_battery_status() (issue #29)
        supports_energy_summary=True,
        supports_special_days=True,
        fixed_password=None,
    ),
    "st3dh": ModelSpec(
        brand=Brand.SMART_TCC,
        ui_label="SMART TCC ST-3DH",
        supports_battery=False,  # no driver implements read_battery_status() (issue #29)
        supports_energy_summary=True,
        supports_special_days=True,
        fixed_password=None,
    ),
    # ── Mitsubishi SMW110 ─────────────────────────────────────────────────────
    "smw110": ModelSpec(
        brand=Brand.MITSU,
        ui_label="Mitsubishi SMW110",
        supports_battery=False,  # no driver implements read_battery_status() (issue #29)
        supports_energy_summary=True,  # energy 1.0.{1,2,3,4}.8.x
        supports_special_days=True,  # 0.0.11.0.0.255
        fixed_password=MITSU_SMW110_FIXED_PASSWORD,
    ),
    # ── CEWE ─────────────────────────────────────────────────────────────────
    "prometer100": ModelSpec(
        brand=Brand.CEWE,
        ui_label="Prometer 100",
        supports_battery=True,  # read_battery_status 0.0.96.6.1.255
        supports_energy_summary=False,
        supports_special_days=False,
        fixed_password=CEWE_FIXED_PASSWORD,
    ),
    "saral305": ModelSpec(
        brand=Brand.CEWE,
        ui_label="Saral 305",
        supports_battery=True,  # read_battery_status 0.0.96.6.1.255
        supports_energy_summary=False,
        supports_special_days=False,
        fixed_password=CEWE_FIXED_PASSWORD,
    ),
    "premier550": ModelSpec(
        brand=Brand.CEWE,
        ui_label="Premier 550",
        supports_battery=True,  # read_battery_status 0.0.96.6.1.255
        supports_energy_summary=False,
        supports_special_days=False,
        fixed_password=CEWE_FIXED_PASSWORD,
    ),
}


def get_model_spec(model: str) -> ModelSpec | None:
    """Return the :class:`ModelSpec` for *model*, or None if unknown.

    Case-insensitive, matching the driver factory's ``.lower()`` convention.
    Unknown models return None rather than raising — callers decide what an
    unrecognised model string means to them.

    Args:
        model: Meter model identifier, e.g. ``"prometer100"``.

    Returns:
        The matching spec, or None.
    """
    return CATALOG.get(model.lower())
