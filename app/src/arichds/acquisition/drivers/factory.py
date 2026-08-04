"""Resolve a model string to a concrete :class:`MeterDriver`.

Ported from ``cewe-worker/src/drivers/meter_factory.py``. A registry of lazy
imports, not an ``if/elif`` chain (SPEC §3.4) — adding the remaining eight models
in M4 means adding registry rows, never touching a call site.

Imports are deferred into :func:`_registry` so importing the factory does not
drag the Gurux stack in — which matters for the simulated path and for tests
that never touch DLMS.
"""

from __future__ import annotations

import logging
from typing import Any

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.base import MeterDriver

logger = logging.getLogger(__name__)


def _registry() -> dict[str, type[MeterDriver]]:
    """Lazily import and return the model → driver-class registry."""
    from arichds.acquisition.drivers.prometer100 import Prometer100Driver
    from arichds.acquisition.drivers.simulated import SimulatedDriver

    return {
        "prometer100": Prometer100Driver,
        # The hardware-free driver used for dev and tests (brand/model "SIM").
        "sim": SimulatedDriver,
    }


def supported_models() -> list[str]:
    """Return the model identifiers this build can drive, sorted."""
    return sorted(_registry())


def create_driver(model: str, conn: ConnectionParams, password: str = "", **kwargs: Any) -> MeterDriver:
    """Create a driver for *model*.

    The returned driver is **not connected** — the caller calls ``connect()``
    and ``disconnect()`` (in a ``finally``) itself.

    Args:
        model: Model identifier, case-insensitive (e.g. ``"prometer100"``, ``"SIM"``).
        conn: Transport identity.
        password: DLMS authentication password. Never logged.
        **kwargs: Model-specific keyword arguments passed through.

    Returns:
        A concrete, unconnected driver.

    Raises:
        ValueError: If *model* is not registered.
    """
    key = model.lower()
    registry = _registry()
    if key not in registry:
        raise ValueError(f"Unknown meter model {model!r}. Supported models: {sorted(registry)}")

    logger.debug("Creating %s driver for %s", key, conn.endpoint)
    return registry[key](conn=conn, password=password, **kwargs)
