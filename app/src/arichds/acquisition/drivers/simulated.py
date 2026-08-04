"""Simulated meter driver — the chain is testable without hardware.

Same ABC, same normalization contract (UTC + kWh), plausible drifting values.
It exists so the whole walking skeleton — Poller → database → API → web UI —
can be exercised on a machine with no meter attached, and so the acquisition
tests do not need a network.

Selected as brand/model ``"SIM"``. Its Source is ``sim``, never ``dlms``, so
simulated rows are always distinguishable from real ones in the database.
"""

from __future__ import annotations

import math
import random
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers.base import InstantaneousReading, MeterDriver
from arichds.constants import SOURCE_SIMULATED

#: Nominal values the simulation drifts around — a 400 V / 50 Hz three-phase
#: service, which is what the real fleet looks like.
_NOMINAL_VOLTAGE = 230.0
_NOMINAL_CURRENT = 12.0
_NOMINAL_FREQUENCY = 50.0

_VOLTAGE_SWING = 4.0
_CURRENT_SWING = 3.0
_FREQUENCY_SWING = 0.08

#: kWh added per tick, so the cumulative import register actually advances.
_ENERGY_STEP_KWH = 0.25


@dataclass
class _SimState:
    """The drifting state of one simulated meter.

    Attributes:
        tick: How many samples this endpoint has produced — drives the sine phase.
        energy_kwh: The cumulative import register.
    """

    tick: int = 0
    energy_kwh: float = 0.0


# Simulation state lives at MODULE scope, keyed by Transport Endpoint — not on
# the driver instance.
#
# The Poller builds a brand-new driver on every tick (`poll_once` → `build_driver`),
# so per-instance counters reset each time: the cumulative register would never
# advance and the voltage sine would be frozen at the tick-1 phase forever. SIM
# is user-visible (it is offered in the Monitor model dropdown and named in the
# empty-state hint), so a frozen simulation reads as a broken product.
#
# Keyed on the endpoint so two simulated devices drift independently, and
# guarded because poller threads share this dict.
_SIM_STATE: dict[str, _SimState] = {}
_SIM_STATE_GUARD = threading.Lock()


def reset_simulated_state() -> None:
    """Forget every endpoint's simulation state.

    For tests that need a known starting point; never called in production.
    """
    with _SIM_STATE_GUARD:
        _SIM_STATE.clear()


def _advance(endpoint: str) -> _SimState:
    """Advance and return a snapshot of *endpoint*'s state.

    Returns a copy so the caller can read it without holding the lock.
    """
    with _SIM_STATE_GUARD:
        state = _SIM_STATE.get(endpoint)
        if state is None:
            # Seed the register from the endpoint so two simulated devices do
            # not report identical cumulative energy.
            state = _SimState(energy_kwh=float(abs(hash(endpoint)) % 10_000))
            _SIM_STATE[endpoint] = state
        state.tick += 1
        state.energy_kwh += _ENERGY_STEP_KWH
        return _SimState(tick=state.tick, energy_kwh=state.energy_kwh)


class SimulatedDriver(MeterDriver):
    """A meter that always answers, with values that drift plausibly.

    The drift is a slow sine plus a little noise rather than a random walk, so
    the monitor page shows something that looks like a live meter. State is held
    per Transport Endpoint at module scope, because the Poller discards and
    rebuilds the driver every tick.
    """

    source = SOURCE_SIMULATED

    def __init__(self, conn: ConnectionParams, password: str = "", **kwargs: Any) -> None:
        """Initialise the simulation.

        Args:
            conn: Transport identity, used only for the endpoint label.
            password: Ignored — kept so the factory signature is uniform.
            **kwargs: Absorbed for forward compatibility.
        """
        self._conn = conn
        self._connected = False

    @property
    def model_name(self) -> str:
        """Human-readable model identifier."""
        return "sim"

    @property
    def endpoint(self) -> str:
        """The Transport Endpoint this simulated meter claims to live at."""
        return self._conn.endpoint

    def get_obis_map(self) -> dict[str, tuple[str, int]]:
        """No wire protocol — the simulation has no OBIS codes."""
        return {}

    def connect(self) -> None:
        """Mark the simulated connection open."""
        self._connected = True

    def disconnect(self) -> None:
        """Mark the simulated connection closed. Never raises."""
        self._connected = False

    def read_instantaneous(self) -> InstantaneousReading:
        """Return the next simulated sample — UTC and kWh, like any driver.

        Returns:
            A normalized sample with values drifting around nominal.
        """
        state = _advance(self._conn.endpoint)
        tick = state.tick
        energy = state.energy_kwh

        def drift(nominal: float, swing: float, phase: float) -> float:
            """Slow sine around *nominal* plus a little noise."""
            wave = math.sin((tick / 12.0) + phase) * swing
            noise = random.uniform(-swing / 10.0, swing / 10.0)  # noqa: S311 — not cryptographic
            return round(nominal + wave + noise, 2)

        return InstantaneousReading(
            read_at=datetime.now(UTC),
            source=self.source,
            volt_l1=drift(_NOMINAL_VOLTAGE, _VOLTAGE_SWING, 0.0),
            volt_l2=drift(_NOMINAL_VOLTAGE, _VOLTAGE_SWING, 2.09),
            volt_l3=drift(_NOMINAL_VOLTAGE, _VOLTAGE_SWING, 4.19),
            current_l1=drift(_NOMINAL_CURRENT, _CURRENT_SWING, 0.5),
            current_l2=drift(_NOMINAL_CURRENT, _CURRENT_SWING, 2.6),
            current_l3=drift(_NOMINAL_CURRENT, _CURRENT_SWING, 4.7),
            freq=drift(_NOMINAL_FREQUENCY, _FREQUENCY_SWING, 1.0),
            import_active_kwh=round(energy, 3),
        )

    def health_check(self) -> bool:
        """A simulated meter is always reachable."""
        return True
