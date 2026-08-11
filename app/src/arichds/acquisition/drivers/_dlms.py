"""Private base for DLMS/COSEM meter drivers, reached over TCP or serial.

Internal to :mod:`arichds.acquisition.drivers` — external code imports a
concrete driver or goes through the factory, never this module.

Ported from ``cewe-worker/src/drivers/_tcp_driver_base.py``, reduced to the
lifecycle M3 needs: connect / disconnect / read one register. The instantaneous
set went with ADR 0007 (issue #8) — v2 stores nothing instantaneous, so the only
register anything reads today through *this* base is the Meter Serial, for the
Probe and for the Poller's liveness tick. The SMW110W4's load-profile read path
landed at M4a-2 (issue #10) — but on the leaf driver
(:class:`~arichds.acquisition.drivers.smw110.Smw110Driver`), not here, per that
issue's D1: one model's field evidence does not justify a shared method yet.
The billing-profile read path (M6a, issue #21) landed on the same leaf driver,
for the same reason — this base class still supplies only the register lifecycle
every DLMS model shares.

**Transport-agnostic since issue #9** (module renamed from ``_dlms_tcp.py``,
class renamed from ``TcpDlmsDriver``): the transport fragment of the argv comes
entirely from :class:`~arichds.acquisition.connection_params.ConnectionParams`
(``-h/-p`` for net, ``-S`` for serial), so this base never itself branches on
which one a subclass is using — :class:`Smw110Driver` runs over either.

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
from decimal import Decimal
from typing import Any

from gurux_dlms.enums import DateTimeSkips
from gurux_dlms.objects import GXDLMSData, GXDLMSExtendedRegister, GXDLMSRegister, GXDLMSSpecialDaysTable

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers import _gurux_net_patch  # noqa: F401 — import applies the patch
from arichds.acquisition.drivers._gurux_trace import silence_frame_trace
from arichds.acquisition.drivers.base import EnergyRegisterReading, MeterConnectionError, MeterDriver, SpecialDayEntry
from arichds.acquisition.obis import ENERGY_COLUMNS_WH
from arichds.constants import (
    CONNECT_ASSOC_RETRY_ATTEMPTS,
    CONNECT_ASSOC_RETRY_BACKOFF_SEC,
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


#: The COSEM class-11 Special Days Table — one address, shared by every model
#: that exposes it (``smw110``, the SMART TCC family — M7-1, issue #28;
#: gurux-dlms skill "Special Days Table").
SPECIAL_DAYS_OBIS = "0.0.11.0.0.255"

#: `C` -> the :class:`~arichds.acquisition.drivers.base.EnergyRegisterReading`
#: field prefix, for the twenty standalone cumulative energy registers
#: (COSEM ``D=8``, class 3 Register) — M7-1, issue #28. Shared by every
#: driver that opts in via :meth:`DlmsDriver.supports_energy_registers`.
_ENERGY_REGISTER_PREFIX_BY_C: dict[int, str] = {
    1: "import_active_kwh",
    2: "export_active_kwh",
    3: "import_reactive_kvarh",
    4: "export_reactive_kvarh",
}
_ENERGY_REGISTER_RATE_SUFFIX: dict[int, str] = {0: "total", 1: "rate_a", 2: "rate_b", 3: "rate_c", 4: "rate_d"}


def _special_day_entry_from_gx(entry: Any) -> SpecialDayEntry | None:
    """Classify one wire ``GXDLMSSpecialDay`` into a :class:`SpecialDayEntry`
    (M7-1, issue #28, finding 1) — a pure function, callable and testable
    with no meter and no driver instance.

    **annual ⟺ the wire year field was a wildcard** —
    ``entry.date.skip & DateTimeSkips.YEAR`` is non-zero, which is how Gurux
    (``_GXCommon.getDate``) marks a wire year of ``0xFFFF``. Gurux then
    substitutes the placeholder year ``2000`` into ``entry.date.value`` — a
    wire artefact, and it is never read out of this function; only
    ``.month``/``.day`` are taken from ``.value`` in that case.

    **public ⟺ that bit is clear** — the real ``.value.year`` is taken as-is.

    Args:
        entry: One ``GXDLMSSpecialDay`` off ``obj.entries`` after reading
            attribute 2 — ``.date`` is a ``GXDate`` or ``None``.

    Returns:
        The classified entry, or ``None`` when the entry carries no usable
        date — dropped structurally, the same way every other read path in
        this codebase drops a row it cannot classify rather than storing
        something invented.
    """
    gx_date = entry.date
    if gx_date is None or gx_date.value is None:
        return None

    is_annual = bool(gx_date.skip & DateTimeSkips.YEAR)
    return SpecialDayEntry(
        index=int(entry.index),
        day_id=int(entry.dayId),
        year=None if is_annual else gx_date.value.year,
        month=gx_date.value.month,
        day=gx_date.value.day,
    )


def read_energy_registers_via(driver: DlmsDriver) -> EnergyRegisterReading:
    """Read the twenty standalone cumulative energy registers
    (``1.0.{1,2,3,4}.8.{0..4}.255``, COSEM ``D=8``) off *driver* — M7-1,
    issue #28.

    A free function, not a :class:`DlmsDriver` method, on purpose: the read
    shape (loop :meth:`DlmsDriver.read_register`, which already applies the
    scaler per ADR 0002) is identical for every model that exposes these
    registers (``smw110``, the SMART TCC family), but the capability pairing
    this codebase uses everywhere (``base.py``'s module docstring) requires
    ``read_energy_registers()`` to *raise* on a driver whose
    ``supports_energy_registers()`` is ``False`` — and every CEWE model
    shares this same ``DlmsDriver`` base. Putting the mechanism on the base
    class would have made it silently callable (and working) on a CEWE
    driver too, which is exactly the "``hasattr`` is never the question"
    contract ``base.py`` exists to prevent. Each opting-in leaf driver
    (``smw110.py``, ``smart_tcc.py``) calls this from its own
    ``read_energy_registers()`` override instead.

    Each address is read independently — one that refuses leaves its field
    ``None`` and never aborts the other nineteen. Values divide by
    :data:`~arichds.constants.WH_TO_KWH_DIVISOR` **unconditionally** after
    :meth:`DlmsDriver.read_register` (decision 11) — v1's proven behaviour,
    confirmed by the 2026-08-11 TCC probe where all 20 of 20 addresses
    answered with correct units.

    Returns:
        The snapshot, or an all-``None`` one when *driver* is disconnected.
    """
    if driver._reader is None or driver._client is None:  # noqa: SLF001 — same module, DlmsDriver's own internals.
        logger.warning("read_energy_registers() called on a disconnected driver %s", driver)
        return EnergyRegisterReading(source=driver.source, meter_serial=None)

    fields: dict[str, float | None] = {}
    for c, prefix in _ENERGY_REGISTER_PREFIX_BY_C.items():
        for e, suffix in _ENERGY_REGISTER_RATE_SUFFIX.items():
            obis = f"1.0.{c}.8.{e}.255"
            field = f"{prefix}_{suffix}"
            try:
                raw = driver.read_register(obis, 2)
            except Exception:  # noqa: BLE001 — a refused address must not abort the other nineteen.
                logger.warning("%s: could not read energy register %s (%s) — left None", driver.model_name, obis, field)
                fields[field] = None
                continue
            if raw is None or not isinstance(raw, (Decimal, int, float)):
                fields[field] = None
            else:
                fields[field] = float(raw) / WH_TO_KWH_DIVISOR

    try:
        meter_serial = driver.read_meter_serial()
    except Exception:  # noqa: BLE001 — an annotation field must not cost the whole read.
        logger.warning(
            "%s: meter serial read failed after the energy registers were already read — "
            "row stored with meter_serial=None",
            driver.model_name,
        )
        meter_serial = None

    return EnergyRegisterReading(source=driver.source, meter_serial=meter_serial, **fields)


def read_special_days_via(driver: DlmsDriver) -> list[SpecialDayEntry]:
    """Read *driver*'s whole COSEM class-11 Special Days Table
    (``0.0.11.0.0.255``) — M7-1, issue #28.

    A free function for the same reason as :func:`read_energy_registers_via`
    above — shared mechanism, per-model capability flag.
    :meth:`DlmsDriver.read_register` cannot read a class-11 object (it would
    fall through to ``GXDLMSData`` and fail with "inconsistent Class or
    object"); a ``GXDLMSSpecialDaysTable`` is constructed directly, appended
    to the client's object list, and read at attribute 2. Gurux parses the
    wire array onto ``obj.entries`` — never the ``read()`` return value.

    **Never calls ``insert()``/``delete()``** — the product only ever reads
    a meter (CLAUDE.md).

    Returns:
        Every entry the meter holds, classified through
        :func:`_special_day_entry_from_gx` — an entry with no usable date is
        dropped, and an empty table is a valid answer, not a failure.
    """
    if driver._reader is None or driver._client is None:  # noqa: SLF001 — same module, DlmsDriver's own internals.
        logger.warning("read_special_days() called on a disconnected driver %s", driver)
        return []

    obj = GXDLMSSpecialDaysTable(SPECIAL_DAYS_OBIS)
    driver._client.objects.append(obj)  # noqa: SLF001
    driver._reader.read(obj, 2)  # noqa: SLF001

    classified: list[SpecialDayEntry] = []
    for entry in obj.entries or []:
        mapped = _special_day_entry_from_gx(entry)
        if mapped is not None:
            classified.append(mapped)
    return classified


class DlmsDriver(MeterDriver):
    """Base for DLMS meters, reached over TCP or serial.

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
        last_latency_ms: Round-trip latency of the most recent timed read.
            **Always None today**: the method that set it left with ADR 0007,
            and :func:`~arichds.acquisition.probe.probe_meter` measures its own
            latency on purpose (it must include the wait for the endpoint, which
            a driver cannot see). Kept for M5's load-profile read, which is the
            next read slow enough to be worth timing.
    """

    source = SOURCE_DLMS

    #: Which ``(obis, attr)`` register carries the Meter Serial. The
    #: DLMS-standard Device Serial Number by default; read off the CLASS without
    #: instantiating. Only SMW110 overrides it (issue #9).
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
        """The Transport Endpoint — ``host:port`` for net, the bare COM port
        name for serial (CONTEXT.md). This is the string the Poller takes its
        lock key from (``poller.py``)."""
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
        """Receive / DLMS waitTime timeout in milliseconds."""

    def _build_args(self) -> list[str]:
        """Return the full GXSettings argv: script + transport + protocol flags."""
        return [f"{self.model_name}_driver.py", *self._conn.transport_args(), *self._protocol_args()]

    # ── Connection lifecycle ─────────────────────────────────────────────────

    def connect(self) -> None:
        """Open the connection (TCP or serial) and complete the DLMS handshake.

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
