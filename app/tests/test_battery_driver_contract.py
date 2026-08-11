"""The battery driver capability pair — ``supports_battery`` / ``read_battery_status``
(M7-2, issue #29; ADR 0011).

Mirrors ``TestTheCapabilityContract`` in ``test_billing_driver_contract.py``: a
non-abstract ``supports_battery()`` answering ``False`` by default, paired with
a non-abstract ``read_battery_status()`` that *raises* rather than being
absent — so ``hasattr`` is never the question a caller has to ask (CLAUDE.md:
no model branch in generic code).
"""

from __future__ import annotations

import pytest

from arichds.acquisition.drivers.base import MeterDriver


class _MinimalDriver(MeterDriver):
    """The bare minimum concrete subclass — implements only what
    :class:`MeterDriver` demands, nothing else. Used to test the *base
    class's own* defaults in isolation (mirrors
    ``test_billing_driver_contract.py``'s ``_MinimalDriver``)."""

    @property
    def model_name(self) -> str:
        return "minimal"

    @property
    def endpoint(self) -> str:
        return "198.51.100.9:4059"

    def get_obis_map(self) -> dict[str, tuple[str, int]]:
        return {}

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def read_meter_serial(self) -> str | None:
        return None


class TestTheCapabilityContract:
    def test_the_base_class_answers_no(self) -> None:
        driver = _MinimalDriver()
        assert driver.supports_battery() is False

    def test_calling_the_base_read_raises_rather_than_being_absent(self) -> None:
        driver = _MinimalDriver()
        with pytest.raises(NotImplementedError):
            driver.read_battery_status()
