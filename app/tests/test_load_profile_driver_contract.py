"""The load-profile driver capability pair — ``supports_load_profile`` /
``load_profile_loggers`` (D2, M4c issue #24).

Mirrors ``test_billing_driver_contract.py``: a driver-contract test that, for
every model in the driver registry, ``load_profile_loggers()`` is non-empty
exactly when ``supports_load_profile()`` is ``True`` — so the two capability
signals cannot drift apart the way ``load_profile.py``'s own docstring warned
they might.
"""

from __future__ import annotations

import pytest

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms_profile import _SCALER_ATTRIBUTE
from arichds.acquisition.drivers.factory import _registry


@pytest.mark.parametrize("model", sorted(_registry()))
class TestLoadProfileLoggersMatchesSupportsLoadProfile:
    def test_non_empty_exactly_when_supported(self, model: str) -> None:
        driver_cls = _registry()[model]
        driver = driver_cls(ConnectionParams.net("198.51.100.9", 4059), password="secret")

        loggers = driver.load_profile_loggers()
        supported = driver.supports_load_profile()

        assert bool(loggers) == supported, (
            f"{model}: supports_load_profile()={supported} but load_profile_loggers()={loggers!r}"
        )

    def test_logger_ids_are_ascending(self, model: str) -> None:
        driver_cls = _registry()[model]
        driver = driver_cls(ConnectionParams.net("198.51.100.9", 4059), password="secret")

        loggers = driver.load_profile_loggers()

        assert list(loggers) == sorted(loggers)


class TestEveryDeclaredColumnCanActuallyBeResolved:
    """M13, issue 04 — the declaration carries a COSEM class per candidate now,
    and a class nobody knows the scaler attribute of would fail at read time on
    a real meter and nowhere else. This is the check that moves that failure to
    the suite."""

    def test_every_capture_class_has_a_known_scaler_attribute(self) -> None:
        for driver_cls in _registry().values():
            for logger_id, column_map in getattr(driver_cls, "LOAD_PROFILE_COLUMN_MAP", {}).items():
                for key, column in column_map.items():
                    if column.passthrough:
                        continue
                    assert column.capture_class in _SCALER_ATTRIBUTE, (
                        f"{driver_cls.__name__} logger {logger_id} {key}: "
                        f"no scaler attribute known for {column.capture_class.__name__}"
                    )

    def test_every_sibling_class_has_a_known_scaler_attribute(self) -> None:
        for driver_cls in _registry().values():
            for logger_id, column_map in getattr(driver_cls, "LOAD_PROFILE_COLUMN_MAP", {}).items():
                for key, column in column_map.items():
                    for obis, cosem_class in column.scaler_siblings:
                        assert cosem_class in _SCALER_ATTRIBUTE, (
                            f"{driver_cls.__name__} logger {logger_id} {key} -> {obis}: "
                            f"no scaler attribute known for {cosem_class.__name__}"
                        )

    def test_a_passthrough_column_never_declares_a_scaler_sibling(self) -> None:
        """A passthrough cell is not a scaled number, so a sibling to borrow a
        scaler from is a contradiction — one the declaration refuses to hold,
        asserted here so the refusal is not the only thing standing between a
        wrong declaration and a meter read."""
        for driver_cls in _registry().values():
            for column_map in getattr(driver_cls, "LOAD_PROFILE_COLUMN_MAP", {}).values():
                for key, column in column_map.items():
                    if column.passthrough:
                        assert not column.scaler_siblings, f"{driver_cls.__name__} {key}"
