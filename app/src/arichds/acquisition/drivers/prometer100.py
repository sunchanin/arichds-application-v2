"""DLMS/COSEM driver for the CEWE Prometer 100.

Ported from ``cewe-worker/src/drivers/prometer100.py``. The connection
parameters below are the ones the **code** used against the deployed fleet
(WRAPPER, client address 32, server address 1, Low authentication) — v1's
module docstring described a different, aspirational setup (client 16,
HIGH_SHA256); the code is what talked to real meters, so the code is what was
carried over.

Connection parameters:
    Interface:            WRAPPER (TCP/IP)
    Client address:       32
    Server address:       1
    Authentication:       Low (LLS — password only)
    Inter-frame delay:    200 ms
    TCP read timeout:     60 s

The OBIS subset is byte-identical to v1's map — see
:mod:`arichds.acquisition.obis`. It is proven on site and is not to be tuned.

**Load profile and billing landed at M4c (issue #24)**, sharing their
transport and column-mapping logic with the other two CEWE models through
:mod:`~arichds.acquisition.drivers._dlms_profile` (D6). This model captures **two**
loggers (D15, ``docs/meter-notes/load-profile-capture-objects.md``):

* Logger 1 (``1.0.99.1.0.255``, 900 s) — the four energy columns, V/I per
  phase, frequency and total power factor.
* Logger 2 (``1.0.99.2.0.255``, 300 s) — line-to-line voltage (not stored,
  no column) plus frequency again. Only ``freq`` maps to a column, and it is
  stored anyway (D17): the point is exercising the per-logger watermark and
  the 96-vs-288-row Records case, not the one populated column.

Usage::

    driver = Prometer100Driver(ConnectionParams.net("203.0.113.10", 4059), password="…")
    try:
        driver.connect()
        serial = driver.read_meter_serial()
    finally:
        driver.disconnect()
"""

from __future__ import annotations

from typing import Any

from gurux_dlms.enums import Unit

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms import read_battery_status_via
from arichds.acquisition.drivers._dlms_profile import DlmsProfileDriver
from arichds.acquisition.obis import INSTANTANEOUS_OBIS
from arichds.constants import DLMS_INTER_REQUEST_DELAY_MS, TCP_READ_TIMEOUT_SEC

#: Logger 1 (F7, meter-notes:70-83) — energy, V/I, frequency, total PF. Every
#: column carries a sibling OBIS to borrow ``scaler_unit`` from (review
#: finding 1) — the live 2026-08-09 scan showed every own-address read
#: refused, the same denial the SMW110W4 already documents for load profile.
#: D=29 interval energy borrows from D=8 cumulative energy, D=27 V/I borrows
#: from the D=7 instantaneous sibling, D=24 (total PF) borrows from D=7 too —
#: same pattern SMW110W4's ``_MAPPED_CAPTURE_COLUMNS`` already uses.
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
    ("1.0.14.27.0.255", 2): ("freq", "1.0.14.7.0.255", Unit.FREQUENCY),
    # Total power factor — Prometer 100 only (SPEC §3.5:477-481); Saral 305
    # and Premier 550 read only per-phase PF, which v1 discards, so NULL on
    # those two models is parity, not a gap (D16).
    ("1.0.13.24.0.255", 2): ("avg_geo_pf", "1.0.13.7.0.255", Unit.NONE),
}

#: Logger 2 (F7, meter-notes:102-107) — only frequency maps to a stored
#: column; line-to-line voltage and the three unmapped codes are dropped
#: structurally, the same way SMW110W4 drops its twelve unmapped columns.
#: Stored anyway (D17) — the point is exercising per-logger watermarks and
#: the 96-vs-288-row Records case, not the one populated column.
_LOGGER_2_COLUMNS: dict[tuple[str, int], tuple[str, str | None, Unit]] = {
    ("1.0.14.27.0.255", 2): ("freq", "1.0.14.7.0.255", Unit.FREQUENCY),
}


class Prometer100Driver(DlmsProfileDriver):
    """CEWE Prometer 100 over DLMS/COSEM WRAPPER."""

    _INTERFACE = "WRAPPER"
    _CLIENT_ADDRESS = "32"
    _SERVER_ADDRESS = "1"
    _AUTHENTICATION = "Low"

    LOAD_PROFILE_COLUMN_MAP: dict[int, dict[tuple[str, int], tuple[str, str | None, Unit]]] = {
        1: _LOGGER_1_COLUMNS,
        2: _LOGGER_2_COLUMNS,
    }

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
        return "prometer100"

    def _read_timeout_ms(self) -> int:
        """TCP read / DLMS waitTime timeout: 60 s."""
        return TCP_READ_TIMEOUT_SEC * 1000

    def _protocol_args(self) -> list[str]:
        """Return the Prometer 100 protocol flags, after the transport args.

        The transport ``-h/-p`` fragment is supplied by ConnectionParams via the
        base ``_build_args``. ``-t Error`` keeps the Gurux trace at error level;
        anything chattier grows the log without bound.
        """
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
        """Return the instantaneous OBIS map (V/I per phase, freq, import kWh).

        No production caller since ADR 0007 removed the instantaneous read — see
        :mod:`arichds.acquisition.obis`. ``scripts/probe_meter.py`` walks it, and
        M5's load-profile reader needs the same column-to-OBIS pairs.
        """
        return dict(INSTANTANEOUS_OBIS)

    def get_inter_frame_delay_ms(self) -> int:
        """Inter-frame delay: 200 ms."""
        return DLMS_INTER_REQUEST_DELAY_MS

    def supports_battery(self) -> bool:
        """Yes — the CEWE battery-status register (``0.0.96.6.1.255``, M7-2,
        issue #29)."""
        return True

    def read_battery_status(self) -> str | None:
        """Read the battery status — the shared
        :func:`~arichds.acquisition.drivers._dlms.read_battery_status_via`
        mechanism; this model needs no override of the read itself, only of
        the capability flag."""
        return read_battery_status_via(self)
