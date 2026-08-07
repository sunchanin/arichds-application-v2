"""OBIS codes for the instantaneous set.

**Byte-identical to v1's map** — these codes are proven against the deployed
fleet and are not to be "improved". Taken from
``cewe-worker/src/worker/load_profile_reader.py`` (``OBIS_COLUMN_MAP``, the
``D=7`` IEC-standard group that Prometer 100 uses) and
``cewe-worker/src/billing/obis.py`` (``kwh_import_total``).

The keys are the ``load_profile_readings`` column names, so the mapping from
wire to storage is visible in one place and the driver has nothing to interpret.

**No production read path uses this map today** (ADR 0007, issue #8): the
Poller's tick reads one register, the Meter Serial. It is reached only by
``scripts/probe_meter.py``, the read-only field diagnostic. It stays because it
is field-proven and because M5's load-profile reader needs exactly these
column-to-OBIS pairs — CLAUDE.md forbids editing an OBIS map, not keeping one.
"""

from __future__ import annotations

from typing import Final

#: The instantaneous set: V/I per phase, frequency, and the cumulative
#: active-energy import register.
#:
#: ``{column_name: (obis_code, attribute_index)}`` — attribute 2 is the value.
INSTANTANEOUS_OBIS: Final[dict[str, tuple[str, int]]] = {
    # ── Voltage phase-to-neutral (V) — C=32/52/72, D=7 IEC instantaneous ──────
    "volt_l1": ("1.0.32.7.0.255", 2),
    "volt_l2": ("1.0.52.7.0.255", 2),
    "volt_l3": ("1.0.72.7.0.255", 2),
    # ── Current per phase (A) — C=31/51/71, D=7 ──────────────────────────────
    "current_l1": ("1.0.31.7.0.255", 2),
    "current_l2": ("1.0.51.7.0.255", 2),
    "current_l3": ("1.0.71.7.0.255", 2),
    # ── Frequency (Hz) — C=14, D=7 ───────────────────────────────────────────
    "freq": ("1.0.14.7.0.255", 2),
    # ── Active energy import total — C=1, D=8 (cumulative register). The meter
    #    reports Wh; the driver divides to kWh at write time (REMAKE-PLAN §6.1).
    "import_active_kwh": ("1.0.1.8.0.255", 2),
}

#: Columns whose meter value is raw Wh and must be divided to kWh before it
#: reaches ``load_profile_readings``. Everything else is already in its stored
#: unit.
ENERGY_COLUMNS_WH: Final[frozenset[str]] = frozenset({"import_active_kwh"})
