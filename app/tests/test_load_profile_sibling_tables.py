"""The load-profile sibling tables — a structural regression guard (review
finding 1, M4c issue #24).

``LOAD_PROFILE_COLUMN_MAP``'s ``(field, sibling_obis, unit)`` triples are the
data problem 1's whole fix rests on — roughly 20 of them, spread across three
driver files, edited by hand and the kind of thing touched again when a
fourth CEWE model arrives. The Unit check inside
:func:`~arichds.acquisition.drivers._cewe.resolve_scaler_candidates` catches
a sibling from the *wrong physical quantity* (a current register reporting
``Unit.CURRENT`` where ``Unit.VOLTAGE`` was required) — but it cannot catch a
transposition **within** one Unit family: ``volt_l1`` borrowing L2's sibling
instead of L1's passes the Unit check, resolves a real multiplier, and
silently applies the wrong phase's scaler. No warning, no failing test,
wrong meter readings on every stored row.

This module is that missing check: a mechanical structural invariant over
every declared sibling, not a hand-typed list of the ~20 correct pairs (which
would just be the same data duplicated, and could drift out of sync with the
driver files exactly the way the bug it guards against would arise).

The invariant itself lives in two small predicate functions
(:func:`_shares_quantity_group`, :func:`_d_transition_is_known`) — both the
tests that walk the live driver maps and the tests that feed it deliberately
wrong pairs call the *same* functions, so "the guard rejects a bad pair" is
proven against the real predicate, not asserted about string literals beside
it.
"""

from __future__ import annotations

import pytest

from arichds.acquisition.drivers.premier550 import Premier550Driver
from arichds.acquisition.drivers.prometer100 import Prometer100Driver
from arichds.acquisition.drivers.saral305 import Saral305Driver

_DRIVERS = (Prometer100Driver, Saral305Driver, Premier550Driver)

#: The only D-value transitions a CEWE load-profile sibling may use (F7/F8):
#: interval energy (D=29) borrows cumulative energy (D=8); V/I averaging
#: (D=27) borrows the D=7 instantaneous sibling; total PF (D=24) borrows the
#: same D=7 family. A sibling whose D transition is not in this table is
#: either a typo or a genuinely new borrow this test has not been taught
#: about yet — either way it must not pass silently. ``dict.get`` returning
#: ``None`` for an unknown capture ``D`` fails closed: ``None`` never equals
#: an ``int`` sibling ``D``, so a brand-new borrow must be added here
#: deliberately rather than slipping through.
_ALLOWED_D_TRANSITIONS: dict[int, int] = {29: 8, 27: 7, 24: 7}

#: Columns explicitly known to have no working sibling — deliberate, listed
#: here with a reason, not a silent ``sibling_obis=None``. Empty today: every
#: column this issue's three drivers map has a declared sibling (D12 still
#: applies at read time if that sibling turns out to be unreadable on a real
#: meter — see ``avg_geo_pf``'s note in
#: ``docs/meter-notes/cewe-billing-capture-objects.md``).
_KNOWN_NO_SIBLING: frozenset[tuple[type, int, tuple[str, int]]] = frozenset()


def _shares_quantity_group(capture_obis: str, sibling_obis: str) -> bool:
    """Every OBIS byte except ``D`` must match: ``A.B.C.E.F`` identical, only
    ``D`` differs. Comparing ``A.B.C`` alone would miss a swap that also
    drags the ``E`` byte along with it (review probe M3: a sibling one
    tariff index off, e.g. ``…7.0.255`` mistyped as ``…7.1.255``) — this is
    the check the ``Unit`` guard at read time cannot make, since a
    tariff-shifted sibling usually still reports the right physical unit.
    """
    capture_parts = capture_obis.split(".")
    sibling_parts = sibling_obis.split(".")
    return capture_parts[:3] + capture_parts[4:] == sibling_parts[:3] + sibling_parts[4:]


def _d_transition_is_known(capture_obis: str, sibling_obis: str) -> bool:
    """The ``D`` byte is the *only* byte allowed to differ, and only along
    one of :data:`_ALLOWED_D_TRANSITIONS`'s known routes."""
    capture_d = int(capture_obis.split(".")[3])
    sibling_d = int(sibling_obis.split(".")[3])
    return _ALLOWED_D_TRANSITIONS.get(capture_d) == sibling_d


def _all_load_profile_columns():
    """Yield ``(driver_cls, logger_id, key, field, sibling_obis, unit)`` for
    every column every CEWE driver declares."""
    for driver_cls in _DRIVERS:
        for logger_id, column_map in driver_cls.LOAD_PROFILE_COLUMN_MAP.items():
            for key, (field, sibling_obis, unit) in column_map.items():
                yield driver_cls, logger_id, key, field, sibling_obis, unit


class TestSiblingSharesTheCaptureColumnsQuantityGroup:
    """The structural check the Unit guard cannot make: the sibling must be
    identical to its capture column in **every** OBIS byte except ``D`` —
    never a different phase, a different tariff index, a different C-group,
    or a different quantity entirely."""

    def test_every_declared_sibling_shares_every_byte_except_d(self) -> None:
        failures = []
        for driver_cls, logger_id, (capture_obis, _attr), field, sibling_obis, _unit in _all_load_profile_columns():
            if sibling_obis is None:
                continue
            if not _shares_quantity_group(capture_obis, sibling_obis):
                failures.append(
                    f"{driver_cls.__name__} logger {logger_id} field {field!r}: "
                    f"sibling {sibling_obis} is not identical to capture column {capture_obis} "
                    f"outside the D byte"
                )
        assert not failures, "\n".join(failures)

    def test_every_declared_siblings_d_transition_is_one_of_the_known_ones(self) -> None:
        failures = []
        for driver_cls, logger_id, (capture_obis, _attr), field, sibling_obis, _unit in _all_load_profile_columns():
            if sibling_obis is None:
                continue
            if not _d_transition_is_known(capture_obis, sibling_obis):
                capture_d = int(capture_obis.split(".")[3])
                sibling_d = int(sibling_obis.split(".")[3])
                failures.append(
                    f"{driver_cls.__name__} logger {logger_id} field {field!r}: "
                    f"capture D={capture_d} -> sibling D={sibling_d} is not a known transition "
                    f"(expected D={_ALLOWED_D_TRANSITIONS.get(capture_d)})"
                )
        assert not failures, "\n".join(failures)


#: Deliberately wrong ``(label, capture_obis, wrong_sibling)`` triples — each
#: one the guard must reject. Every case is a real mistake shape a future
#: edit could make, not an invented string: a phase transposition (review
#: probe M1/N9), a cross-quantity C-group swap, a tariff/``E``-byte drift
#: (review probe M3), and a ``D`` transition this table has never seen.
_DELIBERATELY_WRONG_PAIRS: list[tuple[str, str, str]] = [
    ("phase transposition (volt_l1 borrowing volt_l2's sibling)", "1.0.32.27.0.255", "1.0.52.7.0.255"),
    ("cross-quantity C-group swap (voltage capture, current sibling)", "1.0.32.27.0.255", "1.0.31.7.0.255"),
    ("tariff/E-byte drift (E=0 capture, E=1 sibling)", "1.0.31.27.0.255", "1.0.31.7.1.255"),
    ("unknown D transition (D=27 capture, D=8 sibling)", "1.0.32.27.0.255", "1.0.32.8.0.255"),
]


class TestTheGuardRejectsDeliberatelyWrongPairs:
    """Exercises the two real predicates above against wrong pairs, so
    "the guard catches a bad pair" is proven against the functions the live
    driver-map tests actually call — not asserted about string literals
    sitting inertly beside them (review probe M2)."""

    @pytest.mark.parametrize(("label", "capture_obis", "wrong_sibling"), _DELIBERATELY_WRONG_PAIRS)
    def test_the_wrong_pair_fails_at_least_one_real_check(
        self, label: str, capture_obis: str, wrong_sibling: str
    ) -> None:
        same_quantity_group = _shares_quantity_group(capture_obis, wrong_sibling)
        known_transition = _d_transition_is_known(capture_obis, wrong_sibling)
        assert not (same_quantity_group and known_transition), (
            f"{label}: {wrong_sibling} passed both checks — the guard would not have caught this"
        )

    def test_the_correct_pairs_in_the_wrong_table_still_pass(self) -> None:
        """Sanity check on the negative-case table itself: pairing each wrong
        pair's capture column with its *actual* correct sibling must pass
        both checks — otherwise a broken predicate could reject everything
        and the parametrized test above would be vacuously green."""
        correct_siblings = {
            "1.0.32.27.0.255": "1.0.32.7.0.255",
            "1.0.31.27.0.255": "1.0.31.7.0.255",
        }
        for capture_obis, sibling_obis in correct_siblings.items():
            assert _shares_quantity_group(capture_obis, sibling_obis)
            assert _d_transition_is_known(capture_obis, sibling_obis)


class TestNoSiblingIsExplicitlyAllowlisted:
    """A column with no declared sibling (``sibling_obis=None``) must be a
    deliberate, documented decision — never an oversight indistinguishable
    from "forgot to fill this in"."""

    def test_every_none_sibling_column_is_in_the_allowlist(self) -> None:
        offenders = []
        for driver_cls, logger_id, key, field, sibling_obis, _unit in _all_load_profile_columns():
            if sibling_obis is None and (driver_cls, logger_id, key) not in _KNOWN_NO_SIBLING:
                offenders.append(f"{driver_cls.__name__} logger {logger_id} field {field!r} ({key}) has no sibling")
        assert not offenders, "\n".join(offenders)
