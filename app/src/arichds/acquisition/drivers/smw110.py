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
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from gurux_dlms import GXDLMSClient
from gurux_dlms.enums import Unit
from gurux_dlms.enums.DataType import DataType
from gurux_dlms.objects import GXDLMSProfileGeneric, GXDLMSRegister

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms import DlmsDriver
from arichds.acquisition.drivers.base import IntervalReading
from arichds.acquisition.obis import logger_id_for_profile
from arichds.constants import METER_LOCAL_UTC_OFFSET_HOURS, TCP_READ_TIMEOUT_SEC

logger = logging.getLogger(__name__)

#: Logger 1 — the only load profile this model serves over entry access. Logger
#: 2 (``1.0.99.2.0.255``) answers "undefined object" on both field units
#: (docs/meter-notes/smw110w4-scan.md:176-181) — out of scope entirely.
LOAD_PROFILE_OBIS = "1.0.99.1.0.255"

#: The Clock capture column — always column 1 on this profile, but its
#: position is still resolved from the live-read ``captureObjects`` (D7) rather
#: than assumed.
_CLOCK_OBIS = "0.0.1.0.0.255"

#: The seven mapped capture columns that carry a measurement, keyed by their
#: own OBIS: ``{capture_obis: (IntervalReading field, sibling OBIS to borrow
#: scaler_unit from, the Unit that sibling must report)}``. Twelve more capture
#: columns exist on the wire (status word, six PERCENTAGE, five
#: PHASE_ANGLE_DEGREE) and are deliberately dropped — see
#: docs/meter-notes/smw110w4-scan.md:85-137,162-174; D3/D4 in issue #10.
_MAPPED_CAPTURE_COLUMNS: dict[str, tuple[str, str, Unit]] = {
    # D=29 interval energy borrows from D=8 cumulative energy — NOT from the
    # D=7 instantaneous-power sibling, which shares the same C-group and
    # answers first on the real meter (smw110w4-scan.md:129-137).
    "1.0.1.29.0.255": ("import_active_kwh", "1.0.1.8.0.255", Unit.ACTIVE_ENERGY),
    "1.0.32.27.0.255": ("volt_l1", "1.0.32.7.0.255", Unit.VOLTAGE),
    "1.0.52.27.0.255": ("volt_l2", "1.0.52.7.0.255", Unit.VOLTAGE),
    "1.0.72.27.0.255": ("volt_l3", "1.0.72.7.0.255", Unit.VOLTAGE),
    "1.0.31.27.0.255": ("current_l1", "1.0.31.7.0.255", Unit.CURRENT),
    "1.0.51.27.0.255": ("current_l2", "1.0.51.7.0.255", Unit.CURRENT),
    "1.0.71.27.0.255": ("current_l3", "1.0.71.7.0.255", Unit.CURRENT),
}


def _coerce_clock_cell(value: Any) -> datetime | None:
    """Defensively coerce a load-profile clock cell to a plain ``datetime``.

    Gurux hands back a clock cell as a ``GXDateTime`` (the value lives on
    ``.value``, never the object itself — gurux-dlms skill, patterns.md's
    "GXDateTime handling"), a plain ``datetime``, a raw ``bytearray`` when the
    schema was not fully typed, or ``None`` for a time-compressed row. ``None``
    out means the row has no usable timestamp — the caller skips it rather
    than inventing one.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "value") and isinstance(value.value, datetime):
        return value.value
    if isinstance(value, (bytes, bytearray)):
        decoded = GXDLMSClient.changeType(value, DataType.DATETIME)
        if decoded is not None and isinstance(getattr(decoded, "value", None), datetime):
            return decoded.value
    return None


def _meter_local_to_utc(local_dt: datetime) -> datetime:
    """Convert a load-profile clock reading to timezone-aware UTC.

    The buffer stores meter-local time (ICT, UTC+7 — no DST) rather than UTC
    (gurux-dlms skill, "Meter-local time in selective access";
    :data:`~arichds.constants.METER_LOCAL_UTC_OFFSET_HOURS`). A naive cell is
    the normal case on this meter; an aware one is handled the same way
    ``datetime.astimezone`` always is, rather than assumed away.
    """
    if local_dt.tzinfo is not None:
        return local_dt.astimezone(UTC)
    offset = timedelta(hours=METER_LOCAL_UTC_OFFSET_HOURS)
    return (local_dt - offset).replace(tzinfo=UTC)


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

    def read_load_profile(self, start_utc: datetime, end_utc: datetime) -> list[IntervalReading]:
        """Read Logger 1 (``1.0.99.1.0.255``) over ``[start_utc, end_utc]``.

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
        # the order profiles were discovered in (D5).
        logger_id = logger_id_for_profile(LOAD_PROFILE_OBIS)

        pg = GXDLMSProfileGeneric(LOAD_PROFILE_OBIS)
        self._client.objects.append(pg)

        self._reader.read(pg, 3)  # populates pg.captureObjects — read live, never cached (D7)
        capture_period_sec = int(self._reader.read(pg, 4))
        entries_in_use = int(self._reader.read(pg, 7))

        window = _entry_window(entries_in_use, capture_period_sec, start_utc, end_utc, datetime.now(UTC))
        if window is None:
            return []
        start, count = window

        positions = {str(obj.logicalName): i for i, (obj, _cap) in enumerate(pg.captureObjects)}
        expected_cell_count = len(pg.captureObjects)
        clock_pos = positions.get(_CLOCK_OBIS)

        multipliers = {
            capture_obis: self._resolve_multiplier(sibling_obis, unit, field)
            for capture_obis, (field, sibling_obis, unit) in _MAPPED_CAPTURE_COLUMNS.items()
        }

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

            local_dt = _coerce_clock_cell(row[clock_pos]) if clock_pos is not None else None
            if local_dt is None:
                logger.warning("%s: row has no usable timestamp — skipping", self.model_name)
                continue
            read_at = _meter_local_to_utc(local_dt)
            if read_at < start_utc or read_at > end_utc:
                continue

            fields: dict[str, float | None] = {}
            for capture_obis, (field, _sibling_obis, _unit) in _MAPPED_CAPTURE_COLUMNS.items():
                pos = positions.get(capture_obis)
                multiplier = multipliers.get(capture_obis)
                raw = row[pos] if pos is not None else None
                # A cell that is not a number (e.g. a raw bytearray or GXDateTime
                # landing in a measurement column) must not reach `raw * multiplier`
                # — that would raise and lose the whole row. Guard it the same way
                # `_normalize()` already guards its own input, before the multiply
                # rather than after, so a bad cell degrades to None for that column
                # only (issue #10 review round 1, finding 1).
                #
                # `multiplier` is always a float (`obj.scaler` comes from
                # `math.pow`), and `Decimal * float` is unsupported — coerce with
                # `float(raw)` first, exactly like `_normalize()`'s own next line
                # (`_dlms.py`), so an admitted `Decimal` cell is also a handled one
                # rather than a second crash (issue #10 review round 2, finding 1).
                if raw is None or multiplier is None or not isinstance(raw, (Decimal, int, float)):
                    fields[field] = None
                else:
                    fields[field] = self._normalize(field, float(raw) * multiplier)

            readings.append(
                IntervalReading(
                    read_at=read_at,
                    source=self.source,
                    logger_id=logger_id,
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
