"""Private base for DLMS/COSEM meter drivers reached over TCP.

Internal to :mod:`arichds.acquisition.drivers` — external code imports a
concrete driver or goes through the factory, never this module.

Ported from ``cewe-worker/src/drivers/_tcp_driver_base.py``, reduced to the
lifecycle M1 needs (connect / disconnect / read the instantaneous set). The
load-profile and billing-profile read paths stay behind in v1 until M5/M6 ask
for them.

Invariants carried over from v1, all of them earned the hard way:

* ``reader.close()`` always runs in a ``finally``.
* Connect → read → close per cycle; no persistent sockets.
* Every blocking I/O has an explicit timeout.
* Gurux trace level ``Error`` in production, or the log file grows unbounded.
* The password never appears in ``__repr__``/``__str__``.

**Scaler handling differs from v1 on purpose.** v1 read the value (attr 2)
first and then multiplied by ``10 ** int(obj.scaler)`` — but in Gurux Python
``obj.scaler`` is the *multiplier* (``10**exponent``), not the exponent, so at
meter exponent 0 that produced a phantom ×10 which a compensating divisor
elsewhere cancelled (v1 ADR 0010; the reversal is recorded in this project's
``docs/adr/0002-scaler-read-correctly-no-phantom-x10.md`` and locked by
``tests/test_dlms_scaler.py``). SPEC §3.4 says to write the scaler correctly
from the start. So: read ``scaler_unit`` (attr 3) **first**, which populates
``obj.scaler``, then read the value (attr 2) — Gurux applies the multiplier
itself in ``setValue`` and returns engineering units directly. No manual
arithmetic, no compensating pair.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import abstractmethod
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from gurux_dlms.objects import GXDLMSData, GXDLMSExtendedRegister, GXDLMSRegister

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers import _gurux_net_patch  # noqa: F401 — import applies the patch
from arichds.acquisition.drivers._gurux_trace import silence_frame_trace
from arichds.acquisition.drivers.base import InstantaneousReading, MeterConnectionError, MeterDriver
from arichds.acquisition.obis import ENERGY_COLUMNS_WH
from arichds.constants import (
    CONNECT_ASSOC_RETRY_ATTEMPTS,
    CONNECT_ASSOC_RETRY_BACKOFF_SEC,
    HEALTH_CHECK_OBIS_CODE,
    METER_SERIAL_OBIS_ATTR,
    METER_SERIAL_OBIS_CODE,
    SOURCE_DLMS,
    WH_TO_KWH_DIVISOR,
)
from arichds.vendor.gurux import GXDLMSReader, GXSettings

logger = logging.getLogger(__name__)


def _cosem_class(obis_code: str) -> Any:
    """Select the COSEM object class for an OBIS code.

    Ported from v1's ``_cosem_class``. Selection follows the COSEM Blue Book
    §4.5.3 (Register, class 3) and §4.5.4 (Extended Register, class 4):

    * ``A=1, D=6`` (max demand) or ``D=2`` (cumulative demand) → Extended Register
    * ``A=1, D=8`` (energy) → Register
    * ``A=1, D=7`` (instantaneous) → Register
    * anything else → Data (fallback)

    Args:
        obis_code: OBIS code string, e.g. ``"1.0.1.8.0.255"``.

    Returns:
        An instantiated COSEM object for *obis_code*.
    """
    parts = obis_code.split(".")
    if len(parts) == 6 and parts[0] == "1":
        d = parts[3]
        if d in ("6", "2"):
            return GXDLMSExtendedRegister(obis_code)
        if d in ("7", "8"):
            # D=7 instantaneous (V/I/frequency), D=8 cumulative energy — both
            # carry a scaler_unit and are plain Registers.
            return GXDLMSRegister(obis_code)
    return GXDLMSData(obis_code)


class TcpDlmsDriver(MeterDriver):
    """Base for DLMS meters reached over TCP.

    Subclasses supply only ``model_name``, ``_protocol_args()`` and
    ``_read_timeout_ms()`` — everything transport-shaped comes from
    :class:`~arichds.acquisition.connection_params.ConnectionParams`.

    **The Meter Serial read lives here, not on a leaf driver.** All nine
    catalogued models read the same DLMS-standard register the same way, and the
    one model that differs (SMW110, whose standard register returns a factory
    placeholder — v1 ``smw110.py``) differs only in *which* register. So the
    register is a class attribute a subclass overrides and the read itself is
    written once: putting it on Prometer100 would guarantee eight copies of
    identical code when M4 lands the rest. A capability flag, not an if/elif
    model chain (v1 ``base_driver.py``).

    Attributes:
        last_latency_ms: Round-trip latency of the most recent probe read.
    """

    source = SOURCE_DLMS

    #: Which ``(obis, attr)`` register carries the Meter Serial. The
    #: DLMS-standard Device Serial Number by default; read off the CLASS without
    #: instantiating. Only SMW110 will override it (M4).
    METER_SERIAL_OBIS: tuple[str, int] = (METER_SERIAL_OBIS_CODE, METER_SERIAL_OBIS_ATTR)

    def __init__(self, conn: ConnectionParams, password: str, **kwargs: Any) -> None:
        """Initialise connection state. Does NOT open a socket.

        Args:
            conn: Transport identity for this connection.
            password: DLMS authentication password (never logged).
            **kwargs: Absorbed for forward compatibility with model-specific
                keys (cipher keys arrive with the HLS models in M4).
        """
        self._conn = conn
        self._password = password
        self._reader: Any | None = None
        self._client: Any | None = None
        self._media: Any | None = None
        self.last_latency_ms: int | None = None
        self._shutdown_event: threading.Event | None = None

    # ── Identity ─────────────────────────────────────────────────────────────

    @property
    def endpoint(self) -> str:
        """The Transport Endpoint — ``host:port``."""
        return self._conn.endpoint

    def __repr__(self) -> str:
        """Password excluded from repr."""
        return f"{self.__class__.__name__}({self._conn.endpoint})"

    __str__ = __repr__

    def set_shutdown_event(self, event: threading.Event) -> None:
        """Inject the Poller's shutdown event.

        Lets the inner association-retry backoff abort immediately on shutdown
        instead of sleeping it out.
        """
        self._shutdown_event = event

    # ── Hooks subclasses implement ───────────────────────────────────────────

    @abstractmethod
    def _protocol_args(self) -> list[str]:
        """Return the per-model GXSettings flags that follow the transport args.

        Everything after the transport fragment — interface / referencing /
        addressing / auth flags plus ``-P <password>`` and ``-t Error``.
        """

    @abstractmethod
    def _read_timeout_ms(self) -> int:
        """TCP receive / DLMS waitTime timeout in milliseconds."""

    def _build_args(self) -> list[str]:
        """Return the full GXSettings argv: script + transport + protocol flags."""
        return [f"{self.model_name}_driver.py", *self._conn.transport_args(), *self._protocol_args()]

    # ── Connection lifecycle ─────────────────────────────────────────────────

    def connect(self) -> None:
        """Open the TCP connection and complete the DLMS handshake.

        Wraps the association in a bounded inner retry that absorbs a transient
        abort — a ``ValueError("Invalid connection.")`` or a terminal
        ``ConnectionAbortedError`` / ``ConnectionResetError`` — by tearing down
        the half-open socket and rebuilding a fresh settings→client→media→reader
        before re-opening. When the attempts are exhausted the original
        exception propagates unchanged.

        Raises:
            MeterConnectionError: If GXSettings rejects the parameter list.
        """
        if self._reader is not None:
            logger.warning(
                "%s already connected to %s — closing stale connection before reconnecting",
                self.model_name,
                self._conn.endpoint,
            )
            self.disconnect()

        for attempt in range(1, CONNECT_ASSOC_RETRY_ATTEMPTS + 1):
            try:
                self._open_association()
                logger.info("Connected to %s %s", self.model_name, self._conn.endpoint)
                return
            except (ValueError, ConnectionAbortedError, ConnectionResetError) as exc:
                if isinstance(exc, ValueError) and "Invalid connection" not in str(exc):
                    self.disconnect()
                    raise
                self.disconnect()
                if attempt >= CONNECT_ASSOC_RETRY_ATTEMPTS:
                    raise
                logger.warning(
                    "%s association to %s aborted (%s) — retrying (attempt %d/%d)",
                    self.model_name,
                    self._conn.endpoint,
                    type(exc).__name__,
                    attempt,
                    CONNECT_ASSOC_RETRY_ATTEMPTS,
                )
                if self._backoff_aborted_by_shutdown(CONNECT_ASSOC_RETRY_BACKOFF_SEC):
                    raise

    def _open_association(self) -> None:
        """Build a fresh client/media/reader and complete one DLMS handshake.

        A fresh ``GXSettings`` is built on every call so each attempt gets a
        client whose ciphering invocation counter starts clean — never a
        half-mutated one from a failed attempt.
        """
        settings = GXSettings()
        if settings.getParameters(self._build_args()) != 0:
            raise MeterConnectionError(f"GXSettings parameter error for {self.model_name} at {self._conn.endpoint}")

        self._client = settings.client
        self._media = settings.media

        timeout_ms = self._read_timeout_ms()
        if hasattr(self._media, "receiveTimeout"):
            self._media.receiveTimeout = timeout_ms

        self._reader = GXDLMSReader(self._client, self._media, settings.trace, settings.invocationCounter)
        # The vendored reader writes an UNREDACTED frame trace (password
        # included) to ./logFile.txt regardless of trace level. Redirect it
        # before a single frame is exchanged — see _gurux_trace for the detail.
        silence_frame_trace(self._reader)
        # Per-packet response wait (ms).
        self._reader.waitTime = timeout_ms

        self._media.open()
        self._reader.initializeConnection()

    def _backoff_aborted_by_shutdown(self, backoff_sec: float) -> bool:
        """Wait out the inner-retry backoff, aborting early on shutdown.

        Returns:
            True if a shutdown was signalled during the wait (stop retrying).
        """
        if self._shutdown_event is None:
            time.sleep(backoff_sec)
            return False
        return self._shutdown_event.wait(backoff_sec)

    def disconnect(self) -> None:
        """Close the connection and release all socket resources.

        Swallows and logs every exception — this method MUST NOT raise so that
        ``finally`` blocks always complete cleanly.
        """
        try:
            if self._reader is not None:
                self._reader.close()
        except Exception:  # noqa: BLE001
            logger.warning(
                "Error closing reader for %s %s",
                self.model_name,
                self._conn.endpoint,
                exc_info=True,
            )
        finally:
            self._reader = None
            self._client = None
            self._media = None

    # ── Data access ──────────────────────────────────────────────────────────

    def read_register(self, obis_code: str, attr: int = 2) -> Any | None:
        """Read one DLMS register by OBIS code, in engineering units.

        Assumes :meth:`connect` succeeded.

        For Register / ExtendedRegister read at attr 2, ``scaler_unit`` (attr 3)
        is read **first** so Gurux applies the meter's own multiplier when it
        parses the value. The scaler is read once per register per connection.

        Args:
            obis_code: OBIS code string.
            attr: COSEM attribute index (2 = value).

        Returns:
            The value in engineering units, or None if not connected.
        """
        if self._reader is None or self._client is None:
            logger.warning("read_register(%r) called on a disconnected driver %s", obis_code, self)
            return None

        obj = _cosem_class(obis_code)
        self._client.objects.append(obj)

        if isinstance(obj, (GXDLMSRegister, GXDLMSExtendedRegister)) and attr == 2:
            try:
                # Populates obj.scaler with the multiplier (10**exponent).
                self._reader.read(obj, 3)
            except Exception:  # noqa: BLE001
                # Unreadable scaler → treat as exponent 0 (multiplier 1).
                obj.scaler = 1
                logger.warning("Could not read scaler_unit for %s; no scaling applied", obis_code)
            # Gurux multiplies by obj.scaler inside setValue for attr 2.
            return self._reader.read(obj, 2)

        return self._reader.read(obj, attr)

    def read_meter_serial(self) -> str | None:
        """Read the Meter Serial off the meter. Assumes connect() succeeded.

        Ported from v1's ``connection_manager._probe_meter_serial``: read the
        register named by :attr:`METER_SERIAL_OBIS`, decode ``bytes`` as ASCII,
        trim, and treat a blank as nothing. ``errors="replace"`` rather than
        ``strict`` because a meter that returns one odd byte should still
        identify itself instead of failing the whole add.

        Returns:
            The trimmed serial, or None when the meter answered with nothing or
            a blank.
        """
        obis_code, attr = self.METER_SERIAL_OBIS
        raw = self.read_register(obis_code, attr)
        if raw is None:
            logger.warning("Meter serial read returned nothing — %s %s", self.model_name, self._conn.endpoint)
            return None

        serial = bytes(raw).decode("ascii", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)

        serial = serial.strip()
        if not serial:
            # A blank serial is indistinguishable from a failed probe for the
            # caller's purposes, so it must not be reported as an identity.
            logger.warning("Meter serial read was blank — %s %s", self.model_name, self._conn.endpoint)
            return None
        return serial

    def read_instantaneous(self) -> InstantaneousReading:
        """Read the instantaneous set and normalize it (UTC + kWh).

        A register that the meter does not expose is logged and left ``None``
        rather than failing the whole tick — a partial reading is far more
        useful than no reading (v1's "degrade gracefully" behaviour).

        Returns:
            The normalized sample.
        """
        started = time.monotonic()
        values: dict[str, float | None] = {}

        for column, (obis_code, attr) in self.get_obis_map().items():
            try:
                raw = self.read_register(obis_code, attr)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "%s %s: read failed for %s (%s)",
                    self.model_name,
                    self._conn.endpoint,
                    column,
                    obis_code,
                    exc_info=True,
                )
                values[column] = None
                continue
            values[column] = self._normalize(column, raw)

        self.last_latency_ms = int((time.monotonic() - started) * 1000)

        # UTC always. The read timestamp is the host's clock, not the meter's:
        # M1 samples an instantaneous set, which has no meter-side capture time.
        return InstantaneousReading(read_at=datetime.now(UTC), source=self.source, **values)

    def _normalize(self, column: str, raw: Any) -> float | None:
        """Coerce *raw* to a float in the unit the column name promises.

        Energy registers report Wh on the wire and are stored as kWh — the
        division happens here, at write time, exactly once (REMAKE-PLAN §6.1).
        """
        if raw is None:
            return None
        if not isinstance(raw, (Decimal, int, float)):
            # A register whose value is not a number (e.g. a GXDateTime) has no
            # place in a measurement column — store NULL rather than a coerced lie.
            logger.warning("%s: non-numeric value %r for %s — storing NULL", self.model_name, raw, column)
            return None
        value = float(raw)

        if column in ENERGY_COLUMNS_WH:
            return value / WH_TO_KWH_DIVISOR
        return value

    def health_check(self) -> bool:
        """Connect, read the clock object, disconnect.

        Cheaper than the full instantaneous set — one round trip.

        Returns:
            True if the meter answered, False on any error.
        """
        try:
            self.connect()
            start = time.monotonic()
            self.read_register(HEALTH_CHECK_OBIS_CODE, 2)
            self.last_latency_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "Health check OK — %s %s latency=%dms",
                self.model_name,
                self._conn.endpoint,
                self.last_latency_ms,
            )
            return True
        except Exception:  # noqa: BLE001
            logger.warning(
                "Health check FAILED — %s %s",
                self.model_name,
                self._conn.endpoint,
                exc_info=True,
            )
            return False
        finally:
            self.disconnect()
