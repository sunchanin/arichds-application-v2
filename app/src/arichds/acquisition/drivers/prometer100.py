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

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms import DlmsDriver
from arichds.acquisition.obis import INSTANTANEOUS_OBIS
from arichds.constants import DLMS_INTER_REQUEST_DELAY_MS, TCP_READ_TIMEOUT_SEC


class Prometer100Driver(DlmsDriver):
    """CEWE Prometer 100 over DLMS/COSEM WRAPPER."""

    _INTERFACE = "WRAPPER"
    _CLIENT_ADDRESS = "32"
    _SERVER_ADDRESS = "1"
    _AUTHENTICATION = "Low"

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
