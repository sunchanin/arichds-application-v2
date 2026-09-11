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
* Logger 2 (``1.0.99.2.0.255``, 300 s) — line-to-line voltage plus frequency
  again. Until M13 (issue 06) only ``freq`` mapped to a column and the profile
  was stored anyway (D17), to exercise the per-logger watermark and the
  96-vs-288-row Records case; the three line-to-line voltages now map too, so
  this logger is the only source of ``volt_l1_l2``/``volt_l2_l3``/``volt_l3_l1``
  on this model.

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
from gurux_dlms.objects import GXDLMSDemandRegister, GXDLMSExtendedRegister, GXDLMSRegister

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms import read_battery_status_via
from arichds.acquisition.drivers._dlms_profile import DlmsProfileDriver, LpColumn
from arichds.acquisition.obis import INSTANTANEOUS_OBIS
from arichds.constants import DLMS_INTER_REQUEST_DELAY_MS, TCP_READ_TIMEOUT_SEC

#: Logger 1 (F7, meter-notes:70-83) — energy, V/I, frequency, total PF. Every
#: column carries a sibling OBIS to borrow ``scaler_unit`` from (review
#: finding 1), because the own-address read is refused on all but one of them —
#: the same denial the SMW110W4 already documents for load profile.
#:
#: D=29 interval energy borrows from D=8 cumulative energy, D=27 V/I borrows
#: from the D=7 instantaneous sibling, D=24 (total PF) borrows from D=7 too —
#: same pattern SMW110W4's ``_MAPPED_CAPTURE_COLUMNS`` already uses.
#:
#: **The one exception is ``freq``**, whose own address answers (``FREQUENCY``
#: (44), scaler 1.0, measured 2026-09-11), so its declared sibling is never
#: reached. Earlier text here and in the 2026-08-09 notes said *every*
#: own-address read was refused; that was true of every target those scans
#: covered, and ``freq`` was not one of them. Corrected rather than deleted,
#: because the blanket claim is repeated elsewhere — see
#: ``docs/meter-notes/lp-new-columns-scan.md``.
_LOGGER_1_COLUMNS: dict[tuple[str, int], LpColumn] = {
    ("1.0.1.29.0.255", 2): LpColumn(
        "import_active_kwh", Unit.ACTIVE_ENERGY, scaler_siblings=(("1.0.1.8.0.255", GXDLMSRegister),)
    ),
    ("1.0.2.29.0.255", 2): LpColumn(
        "export_active_kwh", Unit.ACTIVE_ENERGY, scaler_siblings=(("1.0.2.8.0.255", GXDLMSRegister),)
    ),
    ("1.0.3.29.0.255", 2): LpColumn(
        "import_reactive_kvarh", Unit.REACTIVE_ENERGY, scaler_siblings=(("1.0.3.8.0.255", GXDLMSRegister),)
    ),
    ("1.0.4.29.0.255", 2): LpColumn(
        "export_reactive_kvarh", Unit.REACTIVE_ENERGY, scaler_siblings=(("1.0.4.8.0.255", GXDLMSRegister),)
    ),
    ("1.0.32.27.0.255", 2): LpColumn("volt_l1", Unit.VOLTAGE, scaler_siblings=(("1.0.32.7.0.255", GXDLMSRegister),)),
    ("1.0.52.27.0.255", 2): LpColumn("volt_l2", Unit.VOLTAGE, scaler_siblings=(("1.0.52.7.0.255", GXDLMSRegister),)),
    ("1.0.72.27.0.255", 2): LpColumn("volt_l3", Unit.VOLTAGE, scaler_siblings=(("1.0.72.7.0.255", GXDLMSRegister),)),
    ("1.0.31.27.0.255", 2): LpColumn("current_l1", Unit.CURRENT, scaler_siblings=(("1.0.31.7.0.255", GXDLMSRegister),)),
    ("1.0.51.27.0.255", 2): LpColumn("current_l2", Unit.CURRENT, scaler_siblings=(("1.0.51.7.0.255", GXDLMSRegister),)),
    ("1.0.71.27.0.255", 2): LpColumn("current_l3", Unit.CURRENT, scaler_siblings=(("1.0.71.7.0.255", GXDLMSRegister),)),
    ("1.0.14.27.0.255", 2): LpColumn("freq", Unit.FREQUENCY, scaler_siblings=(("1.0.14.7.0.255", GXDLMSRegister),)),
    # Total power factor — Prometer 100 only (SPEC §3.5:477-481); Saral 305
    # and Premier 550 read only per-phase PF, which v1 discards, so NULL on
    # those two models is parity, not a gap (D16).
    #
    # The unit is NO_UNIT (255), not NONE (0) — measured on WP079074,
    # 2026-09-09 (M13, issue 05). Declaring NONE made the sibling's multiplier
    # fail the unit check, so this column was NULL on all 87,000+ stored rows
    # with nothing logged. The two are different members of one enumeration;
    # only the meter can say which it uses.
    ("1.0.13.24.0.255", 2): LpColumn("avg_geo_pf", Unit.NO_UNIT, scaler_siblings=(("1.0.13.7.0.255", GXDLMSRegister),)),
    # ── M13, issue 06 — eight of the eleven, all already in this buffer ──────
    # Phase angles. v1 maps only `1.0.81.7.*`, the instantaneous register this
    # meter does not capture, which is why v1's phase-angle columns are NULL on
    # every CEWE row (meter-notes, "v1 silently drops the Prometer 100's phase
    # angles"). D=27 is the interval average; its D=7 sibling carries the scaler.
    ("1.0.81.27.4.255", 2): LpColumn(
        "phase_angle_a", Unit.PHASE_ANGLE_DEGREE, scaler_siblings=(("1.0.81.7.4.255", GXDLMSRegister),)
    ),
    ("1.0.81.27.15.255", 2): LpColumn(
        "phase_angle_b", Unit.PHASE_ANGLE_DEGREE, scaler_siblings=(("1.0.81.7.15.255", GXDLMSRegister),)
    ),
    ("1.0.81.27.26.255", 2): LpColumn(
        "phase_angle_c", Unit.PHASE_ANGLE_DEGREE, scaler_siblings=(("1.0.81.7.26.255", GXDLMSRegister),)
    ),
    # The Interval Status word — a class-1 Data object with no scaler of any
    # kind, so it is a passthrough column and never asks the meter for one.
    # Stored raw, decoded at render time (CONTEXT.md — Interval Status).
    ("1.0.96.5.4.255", 2): LpColumn("interval_status_flag", Unit.NO_UNIT, passthrough=True),
    # Average power. **Captured at attribute 3 of a class-5 Demand Register** —
    # attribute 3 there is `last_average_value`, the average over the closed
    # demand interval, which is the quantity being asked for; that class carries
    # its scaler at attribute 4, which `_SCALER_ATTRIBUTE` knows.
    #
    # The import and export pairs do NOT resolve the same way, measured
    # read-only on WP079074, 2026-09-09: the import columns' D=7 siblings answer
    # as plain Registers, while both export D=7 siblings are denied and only the
    # D=6 max-demand siblings answer — and only when read as an Extended
    # Register. Same physical quantity and unit, a different statistic; the
    # billing path already borrows a max-demand scaler this way, and ADR 0002
    # holds because the scaler is read rather than assumed.
    ("1.0.1.5.0.255", 3): LpColumn(
        "import_active_kw",
        Unit.ACTIVE_POWER,
        capture_class=GXDLMSDemandRegister,
        scaler_siblings=(("1.0.1.7.0.255", GXDLMSRegister),),
    ),
    ("1.0.2.5.0.255", 3): LpColumn(
        "export_active_kw",
        Unit.ACTIVE_POWER,
        capture_class=GXDLMSDemandRegister,
        scaler_siblings=(("1.0.2.6.0.255", GXDLMSExtendedRegister),),
    ),
    ("1.0.3.5.0.255", 3): LpColumn(
        "import_reactive_kvar",
        Unit.REACTIVE_POWER,
        capture_class=GXDLMSDemandRegister,
        scaler_siblings=(("1.0.3.7.0.255", GXDLMSRegister),),
    ),
    ("1.0.4.5.0.255", 3): LpColumn(
        "export_reactive_kvar",
        Unit.REACTIVE_POWER,
        capture_class=GXDLMSDemandRegister,
        scaler_siblings=(("1.0.4.6.0.255", GXDLMSExtendedRegister),),
    ),
}

#: Logger 2 (F7, meter-notes:102-107) — only frequency maps to a stored
#: column; line-to-line voltage and the three unmapped codes are dropped
#: structurally, the same way SMW110W4 drops its twelve unmapped columns.
#: Stored anyway (D17) — the point is exercising per-logger watermarks and
#: the 96-vs-288-row Records case, not the one populated column.
_LOGGER_2_COLUMNS: dict[tuple[str, int], LpColumn] = {
    ("1.0.14.27.0.255", 2): LpColumn("freq", Unit.FREQUENCY, scaler_siblings=(("1.0.14.7.0.255", GXDLMSRegister),)),
    # ── M13, issue 06 — the other three of the eleven ────────────────────────
    # Line-to-line voltage lives in **Logger 2** on this model, not Logger 1 —
    # the one place in this product where a column's logger is not the obvious
    # one. C=157/177/197 are CEWE's own non-standard groups for L1-L2, L2-L3
    # and L3-L1 (v1 records the same three). Their D=7 siblings carry the
    # scaler, like every other measurement column here.
    ("1.0.157.27.0.255", 2): LpColumn(
        "volt_l1_l2", Unit.VOLTAGE, scaler_siblings=(("1.0.157.7.0.255", GXDLMSRegister),)
    ),
    ("1.0.177.27.0.255", 2): LpColumn(
        "volt_l2_l3", Unit.VOLTAGE, scaler_siblings=(("1.0.177.7.0.255", GXDLMSRegister),)
    ),
    ("1.0.197.27.0.255", 2): LpColumn(
        "volt_l3_l1", Unit.VOLTAGE, scaler_siblings=(("1.0.197.7.0.255", GXDLMSRegister),)
    ),
}


class Prometer100Driver(DlmsProfileDriver):
    """CEWE Prometer 100 over DLMS/COSEM WRAPPER."""

    _INTERFACE = "WRAPPER"
    _CLIENT_ADDRESS = "32"
    _SERVER_ADDRESS = "1"
    _AUTHENTICATION = "Low"

    LOAD_PROFILE_COLUMN_MAP: dict[int, dict[tuple[str, int], LpColumn]] = {
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
