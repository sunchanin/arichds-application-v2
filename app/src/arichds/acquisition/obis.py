"""OBIS codes for the instantaneous set.

**Byte-identical to v1's map** — these codes are proven against the deployed
fleet and are not to be "improved". Taken from
``cewe-worker/src/worker/load_profile_reader.py`` (``OBIS_COLUMN_MAP``, the
``D=7`` IEC-standard group that Prometer 100 uses) and
``cewe-worker/src/billing/obis.py`` (``kwh_import_total``).

The keys are the ``load_profile_readings`` column names, so the mapping from
wire to storage is visible in one place and the driver has nothing to interpret.

It also holds the load-profile **logger** map (M5a-1) — a separate constant,
added rather than folded in, because ``INSTANTANEOUS_OBIS`` below is
field-proven and frozen.

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

#: Columns whose meter value is raw Wh/varh and must be divided to kWh/kvarh
#: before it reaches ``load_profile_readings``. Everything else is already in
#: its stored unit. Grew from one column to all four energy columns at M4c
#: (issue #24, D13): the SMW110W4 only ever populated ``import_active_kwh``,
#: but all three CEWE models populate all four (F7), and all four are raw
#: Wh/varh on the wire — adding the other three changes no SMW110W4 behaviour.
ENERGY_COLUMNS_WH: Final[frozenset[str]] = frozenset(
    {"import_active_kwh", "export_active_kwh", "import_reactive_kvarh", "export_reactive_kvarh"}
)

#: Which ``logger_id`` a load-profile row gets, keyed by the ProfileGeneric OBIS
#: it was read from (SPEC §3.5). Two entries, scanned off real meters on
#: 2026-08-05 (``docs/meter-notes/load-profile-capture-objects.md``) — there is
#: no third profile anybody has seen.
LOAD_PROFILE_LOGGER_IDS: Final[dict[str, int]] = {"1.0.99.1.0.255": 1, "1.0.99.2.0.255": 2}


def logger_id_for_profile(obis: str) -> int:
    """Return the ``logger_id`` for a load-profile OBIS code (M5a-1, D5).

    **An explicit map, not a parse of the OBIS group.** Deriving the id
    arithmetically (``1.0.99.N.0.255`` → ``N``) would silently mint ids for
    profiles nobody has scanned, and an id nobody can trace back to a real
    profile is the same class of failure as deriving one from the order profiles
    happened to be discovered in — which is what ADR 0005 forbids for identity.

    Args:
        obis: The ProfileGeneric's OBIS code.

    Returns:
        1 for Logger 1, 2 for Logger 2.

    Raises:
        ValueError: For any other code. Adding a profile means adding it to
            :data:`LOAD_PROFILE_LOGGER_IDS` with the scan that justifies it.
    """
    logger_id = LOAD_PROFILE_LOGGER_IDS.get(obis)
    if logger_id is None:
        raise ValueError(f"{obis!r} is not a known load profile — no logger_id can be derived from it")
    return logger_id
