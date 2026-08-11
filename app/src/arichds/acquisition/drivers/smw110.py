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

import logging
import math
from datetime import UTC, datetime
from typing import Any

from gurux_dlms import GXReplyData
from gurux_dlms.enums import Unit
from gurux_dlms.objects import GXDLMSExtendedRegister, GXDLMSProfileGeneric, GXDLMSRegister

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms import DlmsDriver, read_energy_registers_via, read_special_days_via
from arichds.acquisition.drivers._profile import (
    build_fields,
    coerce_clock_cell,
    meter_local_to_utc,
    positions_by_obis_attr,
)
from arichds.acquisition.drivers.base import BillingReading, EnergyRegisterReading, IntervalReading, SpecialDayEntry
from arichds.acquisition.obis import logger_id_for_profile
from arichds.constants import TCP_READ_TIMEOUT_SEC, WH_TO_KWH_DIVISOR

logger = logging.getLogger(__name__)

#: Logger 1 — the only load profile this model serves over entry access. Logger
#: 2 (``1.0.99.2.0.255``) answers "undefined object" on both field units
#: (docs/meter-notes/smw110w4-scan.md:176-181) — out of scope entirely.
LOAD_PROFILE_OBIS = "1.0.99.1.0.255"

#: The Clock capture column — always column 1 on this profile, but its
#: position is still resolved from the live-read ``captureObjects`` (D7) rather
#: than assumed.
_CLOCK_OBIS = "0.0.1.0.0.255"

#: The billing profile (M6a, issue #21) — prefix ``1.0``, not the ``0.0``
#: SMART TCC uses (docs/meter-notes/smw110w4-scan.md:228-238).
BILLING_PROFILE_OBIS = "1.0.98.1.0.255"

#: `E` (capture-column tariff index) -> the ``billing_readings`` column suffix.
_BILLING_RATE_SUFFIX: dict[int, str] = {0: "total", 1: "rate_a", 2: "rate_b", 3: "rate_c", 4: "rate_d"}

#: `C` (OBIS quantity group) -> (field prefix, required Unit), for energy
#: (``D=8``, class 3 Register) columns. ``C=5`` (reactive Q1) is deliberately
#: absent — no screen has ever shown it (SPEC §3.6).
_BILLING_ENERGY_BY_C: dict[int, tuple[str, Unit]] = {
    1: ("import_active_kwh", Unit.ACTIVE_ENERGY),
    2: ("export_active_kwh", Unit.ACTIVE_ENERGY),
    3: ("import_reactive_kvarh", Unit.REACTIVE_ENERGY),
    4: ("export_reactive_kvarh", Unit.REACTIVE_ENERGY),
}

#: `C` -> (field prefix, required Unit), for maximum-demand (``D=6``, class 4
#: ExtendedRegister) columns. Same four quantities as the energy map above.
_BILLING_DEMAND_BY_C: dict[int, tuple[str, Unit]] = {
    1: ("max_demand_import_active_kw", Unit.ACTIVE_POWER),
    2: ("max_demand_export_active_kw", Unit.ACTIVE_POWER),
    3: ("max_demand_import_reactive_kvar", Unit.REACTIVE_POWER),
    4: ("max_demand_export_reactive_kvar", Unit.REACTIVE_POWER),
}

#: Every mapped billing capture column, keyed on ``(OBIS, attribute)`` (D5):
#: ``{(capture_obis, attr): (BillingReading field, COSEM class, required Unit)}``.
#: Every column here is attribute 2 (the value) — this model maps no capture
#: time (attribute 5), so it never hits the OBIS+attribute collision F2
#: documents; the keying is still ``(obis, attr)`` so the position map it is
#: read against (:func:`~arichds.acquisition.drivers._profile.positions_by_obis_attr`)
#: is the same shape on every driver. Spelled out from the two prefix maps
#: above rather than hand-typed forty times, but the **result** — the field
#: set on :class:`BillingReading` — is still spelled out there (step 2). A
#: capture column absent from this dict (``C=5``, the Clock, the period
#: counter) is dropped structurally, exactly as the twelve unmapped
#: load-profile columns are (D3/D4, issue #10).
_MAPPED_BILLING_COLUMNS: dict[tuple[str, int], tuple[str, type, Unit]] = {
    **{
        (f"1.0.{c}.8.{e}.255", 2): (f"{prefix}_{suffix}", GXDLMSRegister, unit)
        for c, (prefix, unit) in _BILLING_ENERGY_BY_C.items()
        for e, suffix in _BILLING_RATE_SUFFIX.items()
    },
    **{
        (f"1.0.{c}.6.{e}.255", 2): (f"{prefix}_{suffix}", GXDLMSExtendedRegister, unit)
        for c, (prefix, unit) in _BILLING_DEMAND_BY_C.items()
        for e, suffix in _BILLING_RATE_SUFFIX.items()
    },
}

#: The seven mapped capture columns that carry a measurement, keyed on
#: ``(OBIS, attribute)`` (D5): ``{(capture_obis, attr): (IntervalReading
#: field, sibling OBIS to borrow scaler_unit from, the Unit that sibling must
#: report)}``. Every column here is attribute 2. Twelve more capture columns
#: exist on the wire (status word, six PERCENTAGE, five PHASE_ANGLE_DEGREE)
#: and are deliberately dropped — see
#: docs/meter-notes/smw110w4-scan.md:85-137,162-174; D3/D4 in issue #10.
_MAPPED_CAPTURE_COLUMNS: dict[tuple[str, int], tuple[str, str, Unit]] = {
    # D=29 interval energy borrows from D=8 cumulative energy — NOT from the
    # D=7 instantaneous-power sibling, which shares the same C-group and
    # answers first on the real meter (smw110w4-scan.md:129-137).
    ("1.0.1.29.0.255", 2): ("import_active_kwh", "1.0.1.8.0.255", Unit.ACTIVE_ENERGY),
    ("1.0.32.27.0.255", 2): ("volt_l1", "1.0.32.7.0.255", Unit.VOLTAGE),
    ("1.0.52.27.0.255", 2): ("volt_l2", "1.0.52.7.0.255", Unit.VOLTAGE),
    ("1.0.72.27.0.255", 2): ("volt_l3", "1.0.72.7.0.255", Unit.VOLTAGE),
    ("1.0.31.27.0.255", 2): ("current_l1", "1.0.31.7.0.255", Unit.CURRENT),
    ("1.0.51.27.0.255", 2): ("current_l2", "1.0.51.7.0.255", Unit.CURRENT),
    ("1.0.71.27.0.255", 2): ("current_l3", "1.0.71.7.0.255", Unit.CURRENT),
}


def _entry_window(
    entries_in_use: int,
    capture_period_sec: int,
    start_utc: datetime,
    end_utc: datetime,
    now_utc: datetime,
) -> tuple[int, int] | None:
    """Compute the ``readRowsByEntry`` ``(start, count)`` window for a UTC range.

    Ported from v1's ``load_profile_reader._entry_window`` — Output Parity
    ground truth for the margins below, adapted to timezone-aware UTC
    datetimes (issue #10, Step 4). Entry-access semantics on this profile:
    entry 1 is the OLDEST row, entry ``entries_in_use`` the NEWEST
    (``docs/meter-notes/smw110w4-scan.md:74`` — the opposite of Premier 550
    billing; ordering is a property of the profile, not the model). Walking
    back from the newest entry with a margin (2 rows on the start side, 4 on
    the count side) means a slightly-stale ``entries_in_use`` or clock skew
    never clips real data — over-fetching is safe because the caller's row
    filter trims anything outside ``[start_utc, end_utc]`` regardless.

    This function only clamps to the buffer's index bounds — it has no way to
    know whether the requested time range actually overlaps the buffer's real
    contents, so a window entirely outside the buffer can still come back
    non-``None``. The row filter in :meth:`Smw110Driver.read_load_profile` is
    what makes that case return no rows.

    Args:
        entries_in_use: Live ``entriesInUse`` (attr 7). ``<= 0`` (or a
            non-positive capture period) means an empty buffer — ``None``.
        capture_period_sec: Live ``capturePeriod`` (attr 4), seconds per row.
        start_utc: Inclusive lower bound of the requested window.
        end_utc: Inclusive upper bound of the requested window.
        now_utc: "Current time" for the offset-from-newest calculation,
            passed in explicitly so this function stays pure and testable
            without a clock.

    Returns:
        1-based ``(start, count)`` for ``readRowsByEntry``, or ``None`` when
        there is nothing to read.
    """
    if entries_in_use <= 0 or capture_period_sec <= 0:
        return None

    rows_window = math.ceil((end_utc - start_utc).total_seconds() / capture_period_sec)
    offset_newest = max(0, math.floor((now_utc - end_utc).total_seconds() / capture_period_sec))
    start = max(1, entries_in_use - offset_newest - rows_window - 2)
    count = min(entries_in_use - start + 1, rows_window + 4)

    if count <= 0:
        return None
    return start, count


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

    #: The widest column prefix this profile will serve — a full-width read
    #: answers "Data Block Unavailable"; 43 is the measured ceiling
    #: (docs/meter-notes/smw110w4-scan.md:240-267). Moved off the module scope
    #: onto the driver at M4c (D7) — the base class default is ``None``; the
    #: three CEWE billing drivers leave it ``None`` and read full width.
    BILLING_COLUMN_SPAN: int | None = 43

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

    def _resolve_multiplier(self, sibling_obis: str, required_unit: Unit, column: str) -> float | None:
        """Read a sibling's ``scaler_unit`` (attr 3) and return its multiplier.

        This meter denies ``scaler_unit`` on every load-profile capture column
        ("Read-Write denied" — smw110w4-scan.md:110-113), so each mapped column
        borrows its scaler from a sibling OBIS measuring the same physical
        quantity a different way (D5, issue #10). Picking the sibling by
        **unit**, not by whichever answers first, is what stops the energy
        column from borrowing the power sibling's scaler
        (smw110w4-scan.md:129-137): a fresh :class:`GXDLMSRegister` defaults to
        ``scaler=1, unit=Unit.NONE``, so an unreadable sibling fails the same
        unit check as a wrong-quantity one — one branch covers both (D5).

        Returns:
            The multiplier, or ``None`` if the sibling could not be read or
            reports a unit other than *required_unit* — the column is left
            ``None`` on every row rather than storing an unscaled number that
            looks like data (D6).
        """
        obj = GXDLMSRegister(sibling_obis)
        self._client.objects.append(obj)
        readable = True
        try:
            self._reader.read(obj, 3)
        except Exception:  # noqa: BLE001 — an unreadable sibling degrades to Unit.NONE below, never guessed.
            readable = False

        if not readable:
            logger.warning(
                "%s: could not read scaler_unit for %s (sibling for %s) — %s stays unscaled (None)",
                self.model_name,
                sibling_obis,
                column,
                column,
            )
            return None
        if obj.unit != required_unit:
            logger.warning(
                "%s: sibling %s for %s reports unit %s, expected %s — %s stays unscaled (None)",
                self.model_name,
                sibling_obis,
                column,
                obj.unit,
                required_unit,
                column,
            )
            return None
        return obj.scaler

    def supports_load_profile(self) -> bool:
        """Yes — Logger 1, by entry access (M5a-1, D3).

        Overriding the base class's ``False`` is the **only** way the
        load-profile job learns this model can be read: no catalog flag (the
        catalog stopped deciding driver behaviour when issue #9 removed
        ``supports_serial``) and no ``hasattr``.
        """
        return True

    def load_profile_loggers(self) -> tuple[int, ...]:
        """Logger 1 only (D2, M4c issue #24) — Logger 2 answers "undefined
        object" on both field units (smw110w4-scan.md:176-181)."""
        return (logger_id_for_profile(LOAD_PROFILE_OBIS),)

    def read_load_profile(self, logger_id: int, start_utc: datetime, end_utc: datetime) -> list[IntervalReading]:
        """Read Logger 1 (``1.0.99.1.0.255``) over ``[start_utc, end_utc]``.

        *logger_id* is accepted for interface symmetry with every other driver
        (D2) but not branched on: this model has exactly one logger, named by
        :meth:`load_profile_loggers`, so there is nothing to select between.

        **Overrides** :meth:`~arichds.acquisition.drivers.base.MeterDriver.read_load_profile`,
        which is where the method's contract now lives (M5a-1, D3). It was on
        this leaf driver alone at issue #10 (D1) because nothing called it and
        one model's evidence is a poor shape for a shared abstraction; the
        load-profile job is that caller now, and it has to ask every driver the
        same question, so the contract moved up while this implementation stayed
        exactly where the field evidence is.

        Selective access is by entry: this meter refuses ``readRowsByRange``
        with "Read-Write denied" (smw110w4-scan.md:73,186-188), and entry 1 is
        the OLDEST row on this profile — the opposite of Premier 550 billing;
        entry ordering is a property of the *profile*, not the model.

        Capture objects, capture period and entries-in-use are read live on
        every call (D7, SPEC §3.5) — never cached, never assumed to be 900 s.

        Args:
            start_utc: Inclusive lower bound, timezone-aware UTC.
            end_utc: Inclusive upper bound, timezone-aware UTC.

        Returns:
            Rows already normalized to UTC timestamps and kWh energy, oldest
            first, filtered to the requested window, each stamped with the
            ``logger_id`` derived from :data:`LOAD_PROFILE_OBIS` and the live
            capture period as ``interval_sec``. Twelve capture columns are
            dropped structurally (issue #10, D3) and ``freq`` is always ``None``
            — this model's load profile has no frequency column.

        Raises:
            ValueError: If either bound is a naive datetime (D8).
        """
        if start_utc.tzinfo is None or end_utc.tzinfo is None:
            raise ValueError("read_load_profile() requires timezone-aware UTC datetimes")

        if self._reader is None or self._client is None:
            logger.warning("read_load_profile() called on a disconnected driver %s", self)
            return []

        # Derived once per call from the OBIS actually being read, never from
        # the order profiles were discovered in (D5). *logger_id* the caller
        # passed in is not used — see the docstring above.
        row_logger_id = logger_id_for_profile(LOAD_PROFILE_OBIS)
        _ = logger_id

        pg = GXDLMSProfileGeneric(LOAD_PROFILE_OBIS)
        self._client.objects.append(pg)

        self._reader.read(pg, 3)  # populates pg.captureObjects — read live, never cached (D7)
        capture_period_sec = int(self._reader.read(pg, 4))
        entries_in_use = int(self._reader.read(pg, 7))

        window = _entry_window(entries_in_use, capture_period_sec, start_utc, end_utc, datetime.now(UTC))
        if window is None:
            return []
        start, count = window

        positions = positions_by_obis_attr(pg.captureObjects)
        expected_cell_count = len(pg.captureObjects)
        clock_pos = positions.get((_CLOCK_OBIS, 2))

        multipliers = {
            capture_key: self._resolve_multiplier(sibling_obis, unit, field)
            for capture_key, (field, sibling_obis, unit) in _MAPPED_CAPTURE_COLUMNS.items()
        }
        column_map = {key: field for key, (field, _sibling, _unit) in _MAPPED_CAPTURE_COLUMNS.items()}

        rows = self._reader.readRowsByEntry(pg, start, count) or []
        readings: list[IntervalReading] = []
        for row in rows:
            if len(row) != expected_cell_count:
                logger.warning(
                    "%s: row has %d cells, live capture-object count is %d — skipping",
                    self.model_name,
                    len(row),
                    expected_cell_count,
                )
                continue

            local_dt = coerce_clock_cell(row[clock_pos]) if clock_pos is not None else None
            if local_dt is None:
                logger.warning("%s: row has no usable timestamp — skipping", self.model_name)
                continue
            read_at = meter_local_to_utc(local_dt)
            if read_at < start_utc or read_at > end_utc:
                continue

            # A cell that is not a number (e.g. a raw bytearray or GXDateTime
            # landing in a measurement column) must not reach `raw * multiplier`
            # — that would raise and lose the whole row. `build_fields` guards
            # it the same way `_normalize()` already guards its own input,
            # before the multiply rather than after, so a bad cell degrades to
            # None for that column only (issue #10 review round 1, finding 1;
            # D6, issue #24 — the loop itself moved to the shared module).
            fields = build_fields(row, positions, column_map, multipliers, scale=self._normalize)

            readings.append(
                IntervalReading(
                    read_at=read_at,
                    source=self.source,
                    logger_id=row_logger_id,
                    interval_sec=capture_period_sec,
                    volt_l1=fields.get("volt_l1"),
                    volt_l2=fields.get("volt_l2"),
                    volt_l3=fields.get("volt_l3"),
                    current_l1=fields.get("current_l1"),
                    current_l2=fields.get("current_l2"),
                    current_l3=fields.get("current_l3"),
                    freq=None,
                    import_active_kwh=fields.get("import_active_kwh"),
                )
            )
        return readings

    def supports_billing(self) -> bool:
        """Yes — the billing profile (``1.0.98.1.0.255``), by a 43-column span
        (M6a, issue #21, D3/ADR 0009)."""
        return True

    def _read_scaler_unit(
        self,
        obis: str,
        cosem_class: type,
        required_unit: Unit,
        cache: dict[tuple[str, type, Unit], float | None],
    ) -> float | None:
        """Read *obis*'s own ``scaler_unit`` (attr 3) as an object of *cosem_class*.

        Memoized per *cache* — a fresh dict :meth:`read_billing` builds once
        per call and threads through every column, so the ``E=0`` sibling a
        whole tariff group falls back to is read once, not once per tariff
        (review finding on issue #21: up to four redundant reads of the same
        address per group, each holding the Transport Endpoint a DLMS
        round trip longer for no new information).

        Returns:
            The multiplier, or ``None`` if the object could not be read or
            reports a unit other than *required_unit*.
        """
        key = (obis, cosem_class, required_unit)
        if key in cache:
            return cache[key]

        obj = cosem_class(obis)
        self._client.objects.append(obj)
        try:
            self._reader.read(obj, 3)
        except Exception:  # noqa: BLE001 — an unreadable object degrades to Unit.NONE below, never guessed.
            multiplier = None
        else:
            multiplier = obj.scaler if obj.unit == required_unit else None

        cache[key] = multiplier
        return multiplier

    def _billing_multiplier(
        self,
        capture_obis: str,
        cosem_class: type,
        required_unit: Unit,
        column: str,
        cache: dict[tuple[str, type, Unit], float | None],
    ) -> float | None:
        """Resolve *capture_obis*'s multiplier: its own ``scaler_unit`` first,
        then the ``E=0`` (total) sibling of the same ``C.D`` group (step 3.7).

        Unlike the load-profile path (which this meter denies ``scaler_unit``
        on for *every* capture column), the billing energy total
        (``1.0.1.8.0.255``) is known readable (Finding 5) — so the "own
        object" attempt is tried first here, and the sibling is the fallback,
        not the only path.

        Returns:
            The multiplier, or ``None`` if neither attempt resolves — the
            column is left ``None`` on every row rather than storing an
            unscaled number that looks like data.
        """
        multiplier = self._read_scaler_unit(capture_obis, cosem_class, required_unit, cache)
        if multiplier is None:
            parts = capture_obis.split(".")
            sibling_obis = ".".join([*parts[:4], "0", parts[5]])
            if sibling_obis != capture_obis:
                multiplier = self._read_scaler_unit(sibling_obis, cosem_class, required_unit, cache)

        if multiplier is None:
            logger.warning(
                "%s: could not resolve a scaler for %s (%s) — %s stays unscaled (None) on every row",
                self.model_name,
                capture_obis,
                column,
                column,
            )
        return multiplier

    def read_billing(self) -> list[BillingReading]:
        """Read the whole billing buffer (``1.0.98.1.0.255``) through a
        43-column span (M6a, issue #21).

        A full-width ``readRowsByEntry`` answers "Data Block Unavailable" on
        this profile (docs/meter-notes/smw110w4-scan.md:240-267) — the vendored
        :class:`~arichds.vendor.gurux.GXDLMSReader` has no span parameter, and
        editing it is forbidden (CLAUDE.md). The way through, without touching
        any vendored file, is the installed ``GXDLMSClient.readRowsByEntry``
        (which does take a ``columns`` span) reached through ``self._client``
        — that method returns a **request**, not rows, so the data block is
        driven by hand and the reply parsed against the span, exactly as
        ``scripts/probe_smw110_serial.py:530-543`` does.

        Returns:
            Every row the meter holds, newest first (the order this profile
            returns them in) — the first row is the device's Open Period
            (``is_open=True``); every other row is a closed period.
        """
        if self._reader is None or self._client is None:
            logger.warning("read_billing() called on a disconnected driver %s", self)
            return []

        pg = GXDLMSProfileGeneric(BILLING_PROFILE_OBIS)
        self._client.objects.append(pg)

        self._reader.read(pg, 3)  # populates pg.captureObjects — live, never cached (D7)
        entries_in_use = int(self._reader.read(pg, 7))
        if entries_in_use <= 0:
            return []

        full_capture_objects = list(pg.captureObjects)
        span = full_capture_objects[: self.BILLING_COLUMN_SPAN]

        positions = positions_by_obis_attr(span)
        expected_cell_count = len(span)
        clock_pos = positions.get((_CLOCK_OBIS, 2))

        # One cache for the whole call, so a tariff group's shared E=0 sibling
        # is read once no matter how many of its tariff columns fall back to
        # it (review finding — up to four redundant reads of the same address
        # per group otherwise, each holding the Transport Endpoint one more
        # DLMS round trip for no new information).
        scaler_cache: dict[tuple[str, type, Unit], float | None] = {}
        multipliers = {
            capture_key: self._billing_multiplier(capture_key[0], cosem_class, unit, field, scaler_cache)
            for capture_key, (field, cosem_class, unit) in _MAPPED_BILLING_COLUMNS.items()
            if capture_key in positions
        }
        column_map = {key: field for key, (field, _cosem_class, _unit) in _MAPPED_BILLING_COLUMNS.items()}

        original_capture_objects = pg.captureObjects
        try:
            request = self._client.readRowsByEntry(pg, 1, entries_in_use, span)
            reply = GXReplyData()
            self._reader.readDataBlock(request, reply)
            pg.captureObjects = span
            rows = self._client.updateValue(pg, 2, reply.value) or []
        finally:
            pg.captureObjects = original_capture_objects

        try:
            meter_serial = self.read_meter_serial()
        except Exception:  # noqa: BLE001 — an annotation column must not cost the whole read.
            logger.warning(
                "%s: meter serial read failed after the billing buffer was already read — "
                "rows stored with meter_serial=None",
                self.model_name,
            )
            meter_serial = None

        readings: list[BillingReading] = []
        for position, row in enumerate(rows):
            if len(row) != expected_cell_count:
                logger.warning(
                    "%s: billing row has %d cells, span width is %d — skipping",
                    self.model_name,
                    len(row),
                    expected_cell_count,
                )
                if position == 0:
                    logger.warning(
                        "%s: entry 1 (the running billing period) was malformed — "
                        "no Open Period will be recorded from this read",
                        self.model_name,
                    )
                continue

            local_dt = coerce_clock_cell(row[clock_pos]) if clock_pos is not None else None
            if local_dt is None:
                if position == 0:
                    logger.warning(
                        "%s: the running billing period (entry 1) has no usable timestamp — "
                        "no Open Period will be recorded from this read",
                        self.model_name,
                    )
                else:
                    logger.warning("%s: billing row has no usable timestamp — skipping", self.model_name)
                continue
            bill_date = meter_local_to_utc(local_dt)

            # Same guard as the load-profile loop above (now the shared
            # `build_fields`, D6): a non-numeric cell must not reach
            # `raw * multiplier`, and the billing path divides every column by
            # WH_TO_KWH_DIVISOR unconditionally — unlike `_normalize()`, which
            # only divides the load profile's frozen ENERGY_COLUMNS_WH set
            # (step 8; these columns are a different table with a different
            # contract). This model maps no Demand Time column, so nothing
            # here is a passthrough key.
            fields = build_fields(
                row, positions, column_map, multipliers, scale=lambda _field, value: value / WH_TO_KWH_DIVISOR
            )

            readings.append(
                BillingReading(
                    bill_date=bill_date,
                    source=self.source,
                    is_open=position == 0,
                    meter_serial=meter_serial,
                    **fields,
                )
            )
        return readings

    def supports_energy_registers(self) -> bool:
        """Yes — the twenty standalone ``D=8`` energy registers (M7-1, issue
        #28)."""
        return True

    def read_energy_registers(self) -> EnergyRegisterReading:
        """Read the twenty standalone energy registers — the shared
        :func:`~arichds.acquisition.drivers._dlms.read_energy_registers_via`
        mechanism; this model needs no override of the read itself, only of
        the capability flag."""
        return read_energy_registers_via(self)

    def supports_special_days(self) -> bool:
        """Yes — the COSEM class-11 Special Days Table (``0.0.11.0.0.255``,
        M7-1, issue #28)."""
        return True

    def read_special_days(self) -> list[SpecialDayEntry]:
        """Read the Special Days Table — the shared
        :func:`~arichds.acquisition.drivers._dlms.read_special_days_via`
        mechanism."""
        return read_special_days_via(self)
