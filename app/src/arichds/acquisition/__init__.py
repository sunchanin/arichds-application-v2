"""Acquisition — drivers, the Poller, the model catalog, and the Probe.

One layer for every brand and transport. Whatever a meter says on the wire,
what leaves this package is already normalized: UTC and kWh (REMAKE-PLAN §6.1).

Two things about a meter come from here rather than from a caller: its
**identity**, read off the meter by :func:`~arichds.acquisition.probe.probe_meter`
before any row exists (ADR 0005), and the **order** in which callers get its
Transport Endpoint — Manual Reads ahead of background ticks (ADR 0006).
"""

from arichds.acquisition.catalog import CATALOG, Brand, ModelSpec, get_model_spec
from arichds.acquisition.connection_params import ConnectionParams, ConnectionType
from arichds.acquisition.drivers.base import IntervalReading, MeterDriver
from arichds.acquisition.drivers.factory import create_driver, supported_models
from arichds.acquisition.locks import EndpointLocks, PriorityEndpointLock, endpoint_locks
from arichds.acquisition.poller import Poller, TickOutcome, poll_once
from arichds.acquisition.probe import ProbeError, ProbeFailure, ProbeResult, probe_meter

__all__ = [
    "CATALOG",
    "Brand",
    "ConnectionParams",
    "ConnectionType",
    "EndpointLocks",
    "IntervalReading",
    "MeterDriver",
    "ModelSpec",
    "Poller",
    "PriorityEndpointLock",
    "ProbeError",
    "ProbeFailure",
    "ProbeResult",
    "TickOutcome",
    "create_driver",
    "endpoint_locks",
    "get_model_spec",
    "poll_once",
    "probe_meter",
    "supported_models",
]
