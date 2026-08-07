"""Transport-agnostic connection parameters.

Ported from ``cewe-worker/src/drivers/connection_params.py``. It stays the
SINGLE place that branches on transport — no ``if/elif connection_type``
scattered across call sites (SPEC §3.4). Issue #9 landed the ``serial``
variant this docstring always said was coming.

A driver composes its GXSettings argv as::

    [script] + conn.transport_args() + driver._protocol_args()

so the transport fragment (``-h/-p`` or ``-S``) is entirely data-driven and
identical across every model on a given transport.

Immutable (``frozen=True``) so it can be shared across Poller threads without a
lock. Carries no secrets — the password lives on the driver.

**This module is also the single place a stored/submitted transport dict
becomes a :class:`ConnectionParams`** — :func:`connection_params_from_transport`.
Before issue #9, ``poller.build_driver`` did this conversion inline for ``net``
only, while ``Device.transport_endpoint`` (``db/models.py``) independently
handled ``serial`` — two implementations of the same mapping is how a Manual
Read and a background tick came to compute two different lock keys for the
same serial device (issue #9). One function, used everywhere a transport dict
needs to become a connection, is the fix.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

#: SMW110W4 field-confirmed serial line settings (docs/meter-notes/smw110w4-scan.md):
#: 19200 8N1, no flow control. Used as fallbacks when a stored transport dict is
#: missing a key — every dict written through the validated API schema carries
#: all of these explicitly, so the fallback only matters for a hand-built row.
DEFAULT_SERIAL_BAUD_RATE: Final[int] = 19200
DEFAULT_SERIAL_DATA_BITS: Final[int] = 8
DEFAULT_SERIAL_PARITY: Final[str] = "None"
DEFAULT_SERIAL_STOP_BITS: Final[int] = 1


class ConnectionType(StrEnum):
    """The transports ARICHDS speaks."""

    NET = "net"
    SERIAL = "serial"


@dataclass(frozen=True)
class ConnectionParams:
    """Immutable transport identity for a single meter connection.

    Construct via :meth:`net` or :meth:`serial` rather than the raw
    constructor.

    Attributes:
        connection_type: Which transport this is.
        host: TCP host (net only).
        port: TCP port (net only).
        serial_port: COM port name, e.g. ``"COM4"`` (serial only).
        baud_rate: Baud rate (serial only).
        data_bits: Data bits, a single digit 5-8 (serial only) — the
            ``-S`` argv format GXSettings parses takes exactly one character
            for this field (``GXSettings.py:224-244``).
        parity: One of ``None``/``Odd``/``Even``/``Mark``/``Space`` (serial
            only) — the names ``gurux_common.io.Parity`` resolves.
        stop_bits: Stop bits as the human count, 1 or 2 (serial only) —
            GXSettings subtracts 1 to reach the ``StopBits`` enum
            (``ONE == 0``, ``TWO == 1``).
    """

    connection_type: ConnectionType
    host: str | None = None
    port: int | None = None
    serial_port: str | None = None
    baud_rate: int | None = None
    data_bits: int | None = None
    parity: str | None = None
    stop_bits: int | None = None

    @classmethod
    def net(cls, host: str, port: int) -> ConnectionParams:
        """Build a TCP/IP transport for ``host:port``."""
        return cls(connection_type=ConnectionType.NET, host=host, port=port)

    @classmethod
    def serial(
        cls,
        serial_port: str,
        *,
        baud_rate: int = DEFAULT_SERIAL_BAUD_RATE,
        data_bits: int = DEFAULT_SERIAL_DATA_BITS,
        parity: str = DEFAULT_SERIAL_PARITY,
        stop_bits: int = DEFAULT_SERIAL_STOP_BITS,
    ) -> ConnectionParams:
        """Build a serial transport for *serial_port*.

        Defaults are the SMW110W4 field-confirmed line settings (19200 8N1) —
        callers building from a stored/submitted transport always pass every
        field explicitly; see :func:`connection_params_from_transport`.
        """
        return cls(
            connection_type=ConnectionType.SERIAL,
            serial_port=serial_port,
            baud_rate=baud_rate,
            data_bits=data_bits,
            parity=parity,
            stop_bits=stop_bits,
        )

    def transport_args(self) -> list[str]:
        """Return the GXSettings transport argv fragment.

        Net → ``["-h", host, "-p", str(port)]``.
        Serial → ``["-S", "PORT:BAUD:<databits><Parity><stopbits>"]`` — the
        exact format ``GXSettings.py:224-244`` parses: one character of data
        bits, then the parity name (``Parity[name.upper()]``), then the human
        stop-bit count as the final character. String concatenation of the
        three fields (rather than a fixed-width format) is what makes that
        slicing work regardless of the parity name's length.
        """
        if self.connection_type is ConnectionType.SERIAL:
            fmt = f"{self.data_bits}{self.parity}{self.stop_bits}"
            return ["-S", f"{self.serial_port}:{self.baud_rate}:{fmt}"]
        return ["-h", str(self.host), "-p", str(self.port)]

    @property
    def endpoint(self) -> str:
        """The Transport Endpoint — the Poller's lock key (CONTEXT.md).

        ``host:port`` for TCP, the bare COM port name for serial
        (CONTEXT.md — "a COM port name for serial"; never
        ``"COM4:19200"`` — that string is a human label in a field report, not
        a lock key). Must never diverge from ``Device.transport_endpoint``
        (``db/models.py``), which is the whole point of issue #9.

        Never a secret (the password lives on the driver), so it is safe to
        log.
        """
        if self.connection_type is ConnectionType.SERIAL:
            return str(self.serial_port)
        return f"{self.host}:{self.port}"

    def __repr__(self) -> str:
        """Transport identity only — no secrets are held here."""
        kind = "serial" if self.connection_type is ConnectionType.SERIAL else "net"
        return f"ConnectionParams({kind} {self.endpoint})"


def connection_params_from_transport(transport: Mapping[str, Any]) -> ConnectionParams:
    """Build a :class:`ConnectionParams` from a stored/submitted transport mapping.

    The single place that turns ``{"kind": "net"|"serial", ...}`` into a
    :class:`ConnectionParams` — used by the Poller (``poller.build_driver``)
    and every Manual Read path in the API (``probe_meter`` callers), so a
    device's lock key can never diverge between callers. *That divergence,
    for serial, is the defect issue #9 fixes* — see the module docstring.

    Args:
        transport: A ``Device.transport`` dict, or a validated
            ``NetTransport``/``SerialTransport``'s ``model_dump()``.

    Returns:
        The matching :class:`ConnectionParams`.

    Raises:
        ValueError: If the mapping carries no usable transport — no host/port
            for ``net``, or no serial port for ``serial``.
    """
    if transport.get("kind") == "serial":
        serial_port = transport.get("serial_port")
        if not serial_port:
            raise ValueError(f"No usable serial transport: {transport!r}")
        return ConnectionParams.serial(
            str(serial_port),
            baud_rate=int(transport.get("baud_rate") or DEFAULT_SERIAL_BAUD_RATE),
            data_bits=int(transport.get("data_bits") or DEFAULT_SERIAL_DATA_BITS),
            parity=str(transport.get("parity") or DEFAULT_SERIAL_PARITY),
            stop_bits=int(transport.get("stop_bits") or DEFAULT_SERIAL_STOP_BITS),
        )

    host = transport.get("host")
    port = transport.get("port")
    if not host or not port:
        raise ValueError(f"No usable net transport: {transport!r}")
    return ConnectionParams.net(str(host), int(port))
