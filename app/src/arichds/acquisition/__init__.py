"""Acquisition — drivers and the Poller.

One layer for every brand and transport. Whatever a meter says on the wire,
what leaves this package is already normalized: UTC and kWh (REMAKE-PLAN §6.1).
"""

from arichds.acquisition.connection_params import ConnectionParams, ConnectionType
from arichds.acquisition.drivers.base import InstantaneousReading, MeterDriver
from arichds.acquisition.drivers.factory import create_driver, supported_models
from arichds.acquisition.poller import EndpointLocks, Poller, poll_once

__all__ = [
    "ConnectionParams",
    "ConnectionType",
    "EndpointLocks",
    "InstantaneousReading",
    "MeterDriver",
    "Poller",
    "create_driver",
    "poll_once",
    "supported_models",
]
