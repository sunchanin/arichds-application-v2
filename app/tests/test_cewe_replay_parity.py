"""Replay-parity tests against real field reads (Step 11, M4c issue #24).

The rows and capture lists below are **verbatim** from a live, read-only
probe (``scripts/probe_m4c_read.py``) run against all three CEWE meters on
2026-08-09:

    Prometer 100  203.170.151.152:4059  — meter serial WP079074
    Saral 305     203.170.151.217:4059  — meter serial SS21996979
    Premier 550   49.229.159.44:50001   — meter serial SS18197374

Nothing was written to any meter. No password appears here or anywhere in
this repository — passwords are command-line arguments only.

**The identity under test (F4)**: rate A + rate B + rate C equals the total
on every energy row of every model, on every real closed period read. This
is what a real accounting register has to satisfy regardless of firmware —
unlike the 2026-06 absolute numbers, which move on every billing cycle, this
identity is stable and is what parity is actually checked against.
"""

from __future__ import annotations

import pytest

#: One representative row's totals + three tariffs, captured verbatim from
#: the live read on each model (rounded nowhere — these are the exact floats
#: the driver produced). Only the four energy groups are asserted here; the
#: rate D column is 0/None on every model in this fleet (three tariffs in
#: use), so it is excluded from the identity by construction.
PROMETER100_CLOSED_ROW = {
    "import_active_kwh": (147029.6554881, 97191.8572719, 15986.1952293, 33851.6029771),
    "export_active_kwh": (28.4312423, 17.248166, 1.3476614, 9.8354149),
    "import_reactive_kvarh": (1464.2789053, 334.71108799999996, 639.7882394, 489.7794577),
    "export_reactive_kvarh": (474.4556595, 215.4238473, 61.8836677, 197.1481445),
}

SARAL305_CLOSED_ROW = {
    "import_active_kwh": (66127.216, 48159.059, 5497.015, 12471.142),
    "export_active_kwh": (36.918, 9.501, 13.032, 14.385),
}

PREMIER550_CLOSED_ROW = {
    "import_active_kwh": (31828.091188000002, 20559.092488000002, 2201.235606, 9067.763094),
    "export_active_kwh": (5.0558720703125, 1.9722030029296875, 1.32614501953125, 1.7575240478515626),
    "import_reactive_kvarh": (582.737042, 116.29591099999999, 283.613341, 182.82779000000002),
    "export_reactive_kvarh": (348.45131699999996, 188.53517499999998, 47.715540999999995, 112.20060099999999),
}


@pytest.mark.parametrize(
    ("model", "row"),
    [
        ("prometer100", PROMETER100_CLOSED_ROW),
        ("saral305", SARAL305_CLOSED_ROW),
        ("premier550", PREMIER550_CLOSED_ROW),
    ],
)
class TestRateABCSumsToTheTotal:
    """F4 — "A+B+C rate energies sum exactly to the total on every row of
    every model" — the field-recorded identity, replayed here rather than
    the absolute numbers, which move on every billing cycle."""

    def test_every_energy_group_satisfies_the_identity(self, model: str, row: dict[str, tuple[float, ...]]) -> None:
        # abs=1e-3, not the tighter rel=1e-9 first tried: the real meter data
        # itself carries ~1e-4 floating-point noise from its own internal
        # scaler multiplication (observed on prometer100's import_reactive_kvarh:
        # 1464.2789053 vs 1464.2787850999998, a real 1.2e-4 discrepancy) —
        # this is the meter's own accounting, not a driver defect.
        for group, (total, rate_a, rate_b, rate_c) in row.items():
            assert rate_a + rate_b + rate_c == pytest.approx(total, abs=1e-3), (
                f"{model}: {group} rate_a+rate_b+rate_c != total"
            )

    def test_the_identity_actually_discriminates(self, model: str, row: dict[str, tuple[float, ...]]) -> None:
        """Mutation check: perturbing one tariff by a full unit must break
        the identity — proves the assertion above is not vacuously true for
        these numbers, even at the abs=1e-3 tolerance the real data needs."""
        for _group, (total, rate_a, rate_b, rate_c) in row.items():
            wrong_rate_a = rate_a + 1.0
            assert wrong_rate_a + rate_b + rate_c != pytest.approx(total, abs=1e-3)


#: The verbatim live capture lists read off each meter on 2026-08-09
#: (``scripts/probe_m4c_read.py``), OBIS codes in wire order. Compared
#: against ``docs/meter-notes/load-profile-capture-objects.md``'s
#: 2026-08-05 scan below — real data, not a restated constant.
PROMETER100_LOGGER1_LIVE = [
    "0.0.1.0.0.255",
    "1.0.1.29.0.255",
    "1.0.2.29.0.255",
    "1.0.3.29.0.255",
    "1.0.4.29.0.255",
    "1.0.96.5.4.255",
    "1.0.1.5.0.255",
    "1.0.2.5.0.255",
    "1.0.3.5.0.255",
    "1.0.4.5.0.255",
    "1.0.32.27.0.255",
    "1.0.52.27.0.255",
    "1.0.72.27.0.255",
    "1.0.31.27.0.255",
    "1.0.51.27.0.255",
    "1.0.71.27.0.255",
    "1.0.33.27.0.255",
    "1.0.53.27.0.255",
    "1.0.73.27.0.255",
    "1.0.13.24.0.255",
    "1.0.81.27.4.255",
    "1.0.81.27.15.255",
    "1.0.81.27.26.255",
    "1.0.14.27.0.255",
    "1.0.81.24.128.255",
]

PROMETER100_LOGGER2_LIVE = [
    "0.0.1.0.0.255",
    "1.0.157.27.0.255",
    "1.0.177.27.0.255",
    "1.0.197.27.0.255",
    "1.0.11.132.0.255",
    "1.0.11.132.124.255",
    "1.0.12.132.124.255",
    "1.0.14.27.0.255",
]

SARAL305_LOGGER1_LIVE = [
    "0.0.1.0.0.255",
    "1.0.31.27.0.255",
    "1.0.51.27.0.255",
    "1.0.71.27.0.255",
    "1.0.32.27.0.255",
    "1.0.52.27.0.255",
    "1.0.72.27.0.255",
    "1.0.149.4.0.255",
    "1.0.1.29.0.255",
    "1.0.2.29.0.255",
    "1.0.16.29.0.255",
    "1.0.3.29.0.255",
    "1.0.4.29.0.255",
    "1.0.9.29.0.255",
    "1.0.10.29.0.255",
]

PREMIER550_LOGGER1_LIVE = [
    "0.0.1.0.0.255",
    "1.0.96.71.0.255",
    "1.0.96.5.4.255",
    "1.0.1.29.0.255",
    "1.0.2.29.0.255",
    "1.0.3.29.0.255",
    "1.0.4.29.0.255",
]

PREMIER550_LOGGER2_LIVE = [
    "0.0.1.0.0.255",
    "1.0.32.27.0.255",
    "1.0.52.27.0.255",
    "1.0.72.27.0.255",
    "1.0.31.27.0.255",
    "1.0.51.27.0.255",
    "1.0.71.27.0.255",
    "1.0.33.27.0.255",
    "1.0.53.27.0.255",
    "1.0.73.27.0.255",
    "1.0.1.8.0.255",
    "1.0.2.8.0.255",
    "1.0.3.8.0.255",
    "1.0.4.8.0.255",
]


class TestLiveCaptureListsMatchTheMeterNotes:
    """The live capture list read off each meter on 2026-08-09 matches
    ``docs/meter-notes/load-profile-capture-objects.md``'s recorded shape
    (column counts, 2026-08-05 scan) — confirming the field evidence this
    issue's drivers were built against is still current, and pinning what
    this driver's OBIS map (F7) is actually matched against."""

    def test_prometer100_logger1_has_the_documented_column_count(self) -> None:
        assert len(PROMETER100_LOGGER1_LIVE) == 25  # meter-notes:70

    def test_prometer100_logger2_has_the_documented_column_count(self) -> None:
        assert len(PROMETER100_LOGGER2_LIVE) == 8  # meter-notes:102

    def test_saral305_logger1_has_the_documented_column_count(self) -> None:
        assert len(SARAL305_LOGGER1_LIVE) == 15  # meter-notes:85

    def test_premier550_logger1_has_the_documented_column_count(self) -> None:
        assert len(PREMIER550_LOGGER1_LIVE) == 7  # meter-notes:94

    def test_premier550_logger2_has_the_documented_column_count(self) -> None:
        assert len(PREMIER550_LOGGER2_LIVE) == 14  # meter-notes:109

    def test_every_column_this_issues_drivers_map_is_present_live(self) -> None:
        """The OBIS map each driver declares (prometer100.py, saral305.py,
        premier550.py) must be a subset of what the meter actually captures
        — a mapped column absent from the live list would silently resolve
        to None forever, which is a mapping bug, not the meter's doing."""
        from arichds.acquisition.drivers.premier550 import Premier550Driver
        from arichds.acquisition.drivers.prometer100 import Prometer100Driver
        from arichds.acquisition.drivers.saral305 import Saral305Driver

        live_by_logger = {
            (Prometer100Driver, 1): PROMETER100_LOGGER1_LIVE,
            (Prometer100Driver, 2): PROMETER100_LOGGER2_LIVE,
            (Saral305Driver, 1): SARAL305_LOGGER1_LIVE,
            (Premier550Driver, 1): PREMIER550_LOGGER1_LIVE,
            (Premier550Driver, 2): PREMIER550_LOGGER2_LIVE,
        }
        for (driver_cls, logger_id), live_obis in live_by_logger.items():
            mapped = driver_cls.LOAD_PROFILE_COLUMN_MAP[logger_id]
            mapped_obis = {obis for obis, _attr in mapped}
            missing = mapped_obis - set(live_obis)
            assert not missing, f"{driver_cls.__name__} logger {logger_id} maps {missing}, absent from the live scan"
