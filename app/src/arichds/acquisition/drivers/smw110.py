"""DLMS/COSEM driver for the Mitsubishi SMW110W4 (issue #9, milestone M4a).

Field-confirmed connection profile — probed against two live units on
2026-08-07, one on serial ``COM4``, one on TCP ``192.168.1.31:4059``,
identical otherwise (``docs/meter-notes/smw110w4-scan.md``):

    Interface:      HDLC
    Referencing:    LN (logical name)
    Client address: 6 — a per-model constant for now (owner's call,
                    2026-08-07); v1's hardcoded 5 answers on neither unit
                    at this site.
    Server address: physical 1, logical 0 — ``-l 0`` sent explicitly
                    (easy to miss: it must follow ``-s``).
    Authentication: Low (LLS, password only)
    Security:       none
    Serial line:    19200 8N1, no flow control
    TCP:            port 4059

**Transport is a property of the installation, not of the model** — the
customer's site runs one unit of this model on serial and one on TCP with an
otherwise identical profile, which is why this driver accepts either a
:meth:`~arichds.acquisition.connection_params.ConnectionParams.net` or a
:meth:`~arichds.acquisition.connection_params.ConnectionParams.serial`
connection with no branch of its own — the base class already handles that.

**The Meter Serial lives on a Mitsubishi manufacturer register, not the
DLMS-standard one.** ``0.0.96.1.0.255`` — the base class default — answers the
factory placeholder ``99999999`` on both units; the real serial (matching the
nameplate ID code) is on ``1.0.199.128.134.255``.

Usage::

    driver = Smw110Driver(ConnectionParams.serial("COM4"), password="…")
    # or: ConnectionParams.net("192.168.1.31", 4059)
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
from arichds.constants import TCP_READ_TIMEOUT_SEC


class Smw110Driver(DlmsDriver):
    """Mitsubishi SMW110W4 over DLMS/COSEM HDLC — serial or TCP."""

    _INTERFACE = "HDLC"
    _REFERENCING = "ln"
    _CLIENT_ADDRESS = "6"
    _SERVER_ADDRESS = "1"
    _LOGICAL_SERVER_ADDRESS = "0"
    _AUTHENTICATION = "Low"

    #: The Mitsubishi manufacturer register carrying the real Meter Serial.
    #: Overrides the DLMS-standard default on the base class — see the module
    #: docstring; the standard register answers the factory placeholder
    #: ``99999999`` on this model.
    METER_SERIAL_OBIS: tuple[str, int] = ("1.0.199.128.134.255", 2)

    def __init__(self, conn: ConnectionParams, password: str, **kwargs: Any) -> None:
        """Initialise the driver.

        Args:
            conn: Transport identity (net or serial) for this connection.
            password: DLMS authentication password. Never logged.
            **kwargs: Absorbed for forward compatibility.
        """
        super().__init__(conn=conn, password=password, **kwargs)

    @property
    def model_name(self) -> str:
        """Human-readable model identifier — the catalog's locked key."""
        return "smw110"

    def _read_timeout_ms(self) -> int:
        """Receive / DLMS waitTime timeout: 60 s.

        Same generous timeout as :class:`Prometer100Driver`. The field probe
        defaulted to 10 s, but that is a diagnostic's impatience, not a
        measured requirement — a longer timeout costs nothing on a healthy
        meter and stays comfortably inside ``MANUAL_READ_LOCK_TIMEOUT_SEC``.
        """
        return TCP_READ_TIMEOUT_SEC * 1000

    def _protocol_args(self) -> list[str]:
        """Return the SMW110W4 protocol flags, after the transport args.

        ``-l 0`` must follow ``-s`` — ``GXSettings`` combines the logical
        server address into ``serverAddress`` using whatever physical address
        ``-s`` already set (``GXSettings.py:348-349``).
        """
        return [
            "-i", self._INTERFACE,
            "-r", self._REFERENCING,
            "-c", self._CLIENT_ADDRESS,
            "-s", self._SERVER_ADDRESS,
            "-l", self._LOGICAL_SERVER_ADDRESS,
            "-a", self._AUTHENTICATION,
            "-P", self._password,
            "-t", "Error",
        ]  # fmt: skip

    def get_obis_map(self) -> dict[str, tuple[str, int]]:
        """No instantaneous set for this model in v2 (ADR 0007).

        Nothing calls this in production — kept only to satisfy
        :class:`~arichds.acquisition.drivers.base.MeterDriver`'s abstract
        interface, the same way :class:`Prometer100Driver`'s implementation
        has no production caller either.
        """
        return {}
