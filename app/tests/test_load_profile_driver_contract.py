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
