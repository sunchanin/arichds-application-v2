"""Decoding the Interval Status word (M13, issue 07).

The meter captures a status word beside each interval's values, setting bits
when that interval was disturbed, incomplete, or lost power. It is stored as
**the raw integer** (CONTEXT.md — Interval Status, ADR-free but for the same
reason ADR 0009 keeps meter shapes intact): the bits are settled for the CEWE
word and unverified for the SMART TCC one, and storing decoded text would make
every historical row permanently un-decodable the day the second is verified.

This module is the one decoder. It lives at the top of the package rather than
inside ``export/`` because both renderers need it and ``export/`` must not be
imported from ``api/`` — that direction closes an import cycle through
``api/deps`` -> ``jobs/scheduler`` -> ``export/csv_export``. It imports nothing
from this application, which is what keeps it importable from either side.

**Multiple set bits join with a pipe, not a comma.** v1 joined with a comma,
but v1's rendering never reached a CSV — it existed only on v1's screen — so
no Output Parity is broken, and a comma inside a cell survives only if every
downstream consumer honours CSV quoting, which cannot be tested from here.
"""

from __future__ import annotations

#: The three bits v1 decodes, and the wording it uses
#: (``cewe-worker/src/worker/load_profile_reader.py``'s ``_decode_status_flag``).
#: Carried over verbatim because the customer has been reading these words for
#: years; the only change is the separator below.
_BITS: tuple[tuple[int, str], ...] = (
    (0x0001, "ALL_INVALID"),
    (0x0010, "DISTURBED"),
    (0x0800, "POWER_LOSS"),
)

#: Every bit the table above accounts for. Anything outside it is reported as a
#: hex remainder rather than dropped — v1 dropped it whenever at least one known
#: bit was also set, which loses information silently. Nothing depends on that
#: behaviour: this column has never been written to a file.
_KNOWN_MASK = 0x0001 | 0x0010 | 0x0800

#: What separates two set bits. See the module docstring.
SEPARATOR = "|"

#: What an absent word renders as — the empty string, so a model that does not
#: record one gets an **empty column rather than a missing one**, which is the
#: shipped behaviour for ``Frequency (Hz)`` already. The SMART TCC family
#: reaches this by never mapping its own word (``0.0.96.10.1.255``), whose bit
#: meanings nobody has verified on hardware.
BLANK = ""


def decode_interval_status(flag: int | None) -> str:
    """Render one Interval Status word as words.

    Args:
        flag: The raw word as the meter reported it, or ``None`` when this
            model does not record one.

    Returns:
        ``""`` for ``None``, ``"OK"`` for zero, otherwise the set bits' names
        joined by :data:`SEPARATOR`. Bits outside the known set are appended as
        ``0x….`` so a word this table does not yet understand is visible rather
        than silently discarded.
    """
    if flag is None:
        return BLANK
    if flag == 0:
        return "OK"

    parts = [name for mask, name in _BITS if flag & mask]
    unknown = flag & ~_KNOWN_MASK
    if unknown:
        parts.append(f"0x{unknown:04X}")
    return SEPARATOR.join(parts)


__all__ = ["BLANK", "SEPARATOR", "decode_interval_status"]
