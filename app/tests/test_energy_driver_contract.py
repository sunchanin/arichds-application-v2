"""The Energy Registers / Special Days driver capability pairs —
``supports_energy_registers`` / ``read_energy_registers`` and
``supports_special_days`` / ``read_special_days`` (M7-1, issue #28).

Mirrors ``test_load_profile_driver_contract.py``: for every model in the
driver registry, built with ``ConnectionParams.net(...)`` and never
connected, each ``supports_*()`` matches the corresponding ``CATALOG`` flag —
so a flag turned on with no driver behind it fails here, not in production.
"""

from __future__ import annotations

import pytest

from arichds.acquisition.catalog import CATALOG
from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.factory import _registry


@pytest.mark.parametrize("model", sorted(_registry()))
class TestEnergyRegistersSupportMatchesCatalog:
    def test_supports_energy_registers_matches_catalog_flag(self, model: str) -> None:
        driver_cls = _registry()[model]
        driver = driver_cls(ConnectionParams.net("198.51.100.9", 4059), password="secret")

        assert driver.supports_energy_registers() == CATALOG[model].supports_energy_summary, (
            f"{model}: supports_energy_registers()={driver.supports_energy_registers()} but "
            f"CATALOG[{model!r}].supports_energy_summary={CATALOG[model].supports_energy_summary}"
        )

    def test_unsupported_driver_raises_not_implemented(self, model: str) -> None:
        driver_cls = _registry()[model]
        driver = driver_cls(ConnectionParams.net("198.51.100.9", 4059), password="secret")

        if driver.supports_energy_registers():
            pytest.skip(f"{model} supports energy registers — nothing to prove here")
        with pytest.raises(NotImplementedError):
            driver.read_energy_registers()


@pytest.mark.parametrize("model", sorted(_registry()))
class TestSpecialDaysSupportMatchesCatalog:
    def test_supports_special_days_matches_catalog_flag(self, model: str) -> None:
        driver_cls = _registry()[model]
        driver = driver_cls(ConnectionParams.net("198.51.100.9", 4059), password="secret")

        assert driver.supports_special_days() == CATALOG[model].supports_special_days, (
            f"{model}: supports_special_days()={driver.supports_special_days()} but "
            f"CATALOG[{model!r}].supports_special_days={CATALOG[model].supports_special_days}"
        )

    def test_unsupported_driver_raises_not_implemented(self, model: str) -> None:
        driver_cls = _registry()[model]
        driver = driver_cls(ConnectionParams.net("198.51.100.9", 4059), password="secret")

        if driver.supports_special_days():
            pytest.skip(f"{model} supports special days — nothing to prove here")
        with pytest.raises(NotImplementedError):
            driver.read_special_days()
