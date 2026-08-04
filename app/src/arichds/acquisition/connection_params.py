"""Transport-agnostic connection parameters.

Ported from ``cewe-worker/src/drivers/connection_params.py``, trimmed to the
``net`` variant M1 needs. It stays the SINGLE place that branches on transport —
no ``if/elif connection_type`` scattered across call sites (SPEC §3.4). Serial
lands in M3/M4 by adding a variant here, not by branching elsewhere.

A driver composes its GXSettings argv as::

    [script] + conn.transport_args() + driver._protocol_args()

so the transport fragment (``-h/-p``) is entirely data-driven and identical
across every model on a given transport.

Immutable (``frozen=True``) so it can be shared across Poller threads without a
lock. Carries no secrets — the password lives on the driver.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConnectionType(StrEnum):
    """The transports ARICHDS speaks. M1 ships ``NET`` only (SPEC §2)."""

    NET = "net"
    SERIAL = "serial"


@dataclass(frozen=True)
class ConnectionParams:
    """Immutable transport identity for a single meter connection.

    Construct via :meth:`net` rather than the raw constructor.

    Attributes:
        connection_type: Which transport this is.
        host: TCP host (net only).
        port: TCP port (net only).
    """

    connection_type: ConnectionType
    host: str | None = None
    port: int | None = None

    @classmethod
    def net(cls, host: str, port: int) -> ConnectionParams:
        """Build a TCP/IP transport for ``host:port``."""
        return cls(connection_type=ConnectionType.NET, host=host, port=port)

    def transport_args(self) -> list[str]:
        """Return the GXSettings transport argv fragment.

        Net → ``["-h", host, "-p", str(port)]``.
        """
        return ["-h", str(self.host), "-p", str(self.port)]

    @property
    def endpoint(self) -> str:
        """The Transport Endpoint — the Poller's lock key (CONTEXT.md).

        ``host:port`` for TCP. Never a secret (the password lives on the
        driver), so it is safe to log.
        """
        return f"{self.host}:{self.port}"

    def __repr__(self) -> str:
        """Transport identity only — no secrets are held here."""
        return f"ConnectionParams(net {self.endpoint})"
