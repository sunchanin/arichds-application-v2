"""DLMS/COSEM driver for the CEWE Saral 305 (M4c, issue #24).

Connection parameters (F9, from v1's ``drivers/saral305.py:58-61,100-124`` —
the **code** that talked to the deployed fleet):

    Interface:            HDLC
    Client address:       32
    Server address:       1
    Authentication:       Low (LLS — password only)
    TCP read timeout:     60 s

One logger only (D15, ``docs/meter-notes/load-profile-capture-objects.md``):
Logger 1 (``1.0.99.1.0.255``, 900 s) — the four energy columns, V/I per phase.
No frequency column, no power-factor column on this model's Logger 1 — those
two fields stay ``None`` on every row, which is a fact about the meter, not a
gap in the mapping. Three more registers on the wire
(``1.0.9/10.29.0.255`` — apparent kVAh — and ``1.0.149.4.0.255``, a
manufacturer-range register with no nameable meaning) are dropped by decision
(D16) — no screen shows them.

**The measured billing NULL set is real, not a bug** (F10): v1 recorded this
fleet at 19/25 ``BILLING_FIELDS`` populated, with six fields the firmware does
not track at all — ``cumul_kw_demand_rate_a/b/c``, ``kvar_demand_total``,
``kvar_demand_time``, ``cumul_kvar_demand_total`` (v1
``drivers/saral305.py:63-67``; corroborated by v1
``adr/0004-driver-abstraction-obis-map.md:232-239``). Nothing in this driver
special-cases that — the shared :mod:`~arichds.acquisition.drivers._cewe`
billing read simply finds no position for those OBIS codes in the live
capture list and leaves the corresponding fields ``None``, exactly as it does
for any column absent from a model's own capture list.
"""

from __future__ import annotations

from typing import Any

from gurux_dlms.enums import Unit

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._cewe import CeweDriver
from arichds.acquisition.obis import INSTANTANEOUS_OBIS
from arichds.constants import TCP_READ_TIMEOUT_SEC

#: Logger 1 (F7, meter-notes:85-92) — energy + V/I only. No frequency, no
#: power factor on this model's Logger 1 (D16) — ``freq`` and ``avg_geo_pf``
#: stay ``None`` on every row because no column maps to them, not because of
#: a special case in the read path. Every mapped column carries a sibling
#: OBIS (review finding 1) — the live 2026-08-09 scan showed this model
#: denies every own-address ``scaler_unit`` read, the same pattern the
#: SMW110W4 already documents for load profile.
_LOGGER_1_COLUMNS: dict[tuple[str, int], tuple[str, str | None, Unit]] = {
    ("1.0.1.29.0.255", 2): ("import_active_kwh", "1.0.1.8.0.255", Unit.ACTIVE_ENERGY),
    ("1.0.2.29.0.255", 2): ("export_active_kwh", "1.0.2.8.0.255", Unit.ACTIVE_ENERGY),
    ("1.0.3.29.0.255", 2): ("import_reactive_kvarh", "1.0.3.8.0.255", Unit.REACTIVE_ENERGY),
    ("1.0.4.29.0.255", 2): ("export_reactive_kvarh", "1.0.4.8.0.255", Unit.REACTIVE_ENERGY),
    ("1.0.32.27.0.255", 2): ("volt_l1", "1.0.32.7.0.255", Unit.VOLTAGE),
    ("1.0.52.27.0.255", 2): ("volt_l2", "1.0.52.7.0.255", Unit.VOLTAGE),
    ("1.0.72.27.0.255", 2): ("volt_l3", "1.0.72.7.0.255", Unit.VOLTAGE),
    ("1.0.31.27.0.255", 2): ("current_l1", "1.0.31.7.0.255", Unit.CURRENT),
    ("1.0.51.27.0.255", 2): ("current_l2", "1.0.51.7.0.255", Unit.CURRENT),
    ("1.0.71.27.0.255", 2): ("current_l3", "1.0.71.7.0.255", Unit.CURRENT),
}


class Saral305Driver(CeweDriver):
    """CEWE Saral 305 over DLMS/COSEM HDLC."""

    _INTERFACE = "HDLC"
    _CLIENT_ADDRESS = "32"
    _SERVER_ADDRESS = "1"
    _AUTHENTICATION = "Low"

    LOAD_PROFILE_COLUMN_MAP: dict[int, dict[tuple[str, int], tuple[str, str | None, Unit]]] = {1: _LOGGER_1_COLUMNS}

    def __init__(self, conn: ConnectionParams, password: str, **kwargs: Any) -> None:
        """Initialise the driver.

        Args:
            conn: Transport identity (net) for this connection.
            password: DLMS authentication password. Never logged.
            **kwargs: Absorbed for forward compatibility.
        """
        super().__init__(conn=conn, password=password, **kwargs)

    @property
    def model_name(self) -> str:
        """Human-readable model identifier."""
        return "saral305"

    def _read_timeout_ms(self) -> int:
        """TCP read / DLMS waitTime timeout: 60 s."""
        return TCP_READ_TIMEOUT_SEC * 1000

    def _protocol_args(self) -> list[str]:
        """Return the Saral 305 protocol flags, after the transport args."""
        return [
            "-i",
            self._INTERFACE,
            "-c",
            self._CLIENT_ADDRESS,
            "-s",
            self._SERVER_ADDRESS,
            "-a",
            self._AUTHENTICATION,
            "-P",
            self._password,
            "-t",
            "Error",
        ]

    def get_obis_map(self) -> dict[str, tuple[str, int]]:
        """No instantaneous set for this model in v2 (ADR 0007).

        Mirrors :class:`~arichds.acquisition.drivers.prometer100.Prometer100Driver`
        — no production caller, kept only to satisfy the abstract interface.
        """
        return dict(INSTANTANEOUS_OBIS)
