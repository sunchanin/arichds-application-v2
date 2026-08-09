"""Resolve a model string to a concrete :class:`MeterDriver`.

Ported from ``cewe-worker/src/drivers/meter_factory.py``. A registry of lazy
imports, not an ``if/elif`` chain (SPEC §3.4) — adding the remaining eight models
in M4 means adding registry rows, never touching a call site.

Imports are deferred into :func:`_registry` so importing the factory does not
drag the Gurux stack in for callers that never talk to a meter.

There is deliberately **no registration API**. ``_registry`` being a plain
function that rebuilds a fresh dict on every call is what lets the test suite
swap in a fake driver with one ``monkeypatch.setattr`` — including for
:func:`supported_models` — without the product carrying a plugin seam nobody
ships.
"""

from __future__ import annotations

import logging
from typing import Any

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.base import MeterDriver

logger = logging.getLogger(__name__)


def _registry() -> dict[str, type[MeterDriver]]:
    """Lazily import and return the model → driver-class registry."""
    from arichds.acquisition.drivers.premier550 import Premier550Driver
    from arichds.acquisition.drivers.prometer100 import Prometer100Driver
    from arichds.acquisition.drivers.saral305 import Saral305Driver
    from arichds.acquisition.drivers.smw110 import Smw110Driver

    return {
        "prometer100": Prometer100Driver,
        "saral305": Saral305Driver,
        "premier550": Premier550Driver,
        "smw110": Smw110Driver,
    }


def supported_models() -> list[str]:
    """Return the model identifiers this build can drive, sorted."""
    return sorted(_registry())


def create_driver(model: str, conn: ConnectionParams, password: str = "", **kwargs: Any) -> MeterDriver:
    """Create a driver for *model*.

    The returned driver is **not connected** — the caller calls ``connect()``
    and ``disconnect()`` (in a ``finally``) itself.

    Args:
        model: Model identifier, case-insensitive (e.g. ``"prometer100"``).
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
