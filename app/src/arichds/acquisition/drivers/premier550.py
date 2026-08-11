"""DLMS/COSEM driver for the CEWE Premier 550 (M4c, issue #24).

Connection parameters (F9, from v1's ``drivers/premier550.py:73-80,120-148`` —
the **code** that talked to the deployed fleet):

    Interface:            HDLC
    Client address:       32
    Server address:       1, logical server 0 (``-l 0`` sent explicitly)
    Authentication:       Low (LLS — password only)
    TCP read timeout:     90 s — this model alone; every other CEWE model
                           uses the shared 60 s default
    Inter-frame delay:    500 ms — this model alone; the shared default is
                           200 ms (:data:`~arichds.constants.DLMS_INTER_REQUEST_DELAY_MS`)

Two loggers (D15, ``docs/meter-notes/load-profile-capture-objects.md``), both
900 s:

* Logger 1 (``1.0.99.1.0.255``) — the four energy columns only. Nothing
  electrical; that lives in Logger 2.
* Logger 2 (``1.0.99.2.0.255``) — V/I per phase. **Its cumulative energy
  columns (``1.0.1/2/3/4.8.0.255``) are deliberately NOT mapped** (D16,
  SPEC §3.5:485-490): they collide with Logger 1's interval energy columns —
  a *cumulative total* landing in the same column the Records page sums as
  *interval* energy would make that daily sum meaningless. Per-phase power
  factor is captured but not mapped either, for the same reason Saral 305's
  is not: v1 reads per-phase PF and discards it, so a total PF column staying
  ``NULL`` on this model is parity, not a gap.
"""

from __future__ import annotations

from typing import Any

from gurux_dlms.enums import Unit

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms import read_battery_status_via
from arichds.acquisition.drivers._dlms_profile import DlmsProfileDriver
from arichds.acquisition.obis import INSTANTANEOUS_OBIS

#: This model's own read timeout — 90 s, wider than every other CEWE model's
#: shared 60 s default (F9). A local constant, not
#: :data:`~arichds.constants.TCP_READ_TIMEOUT_SEC`, because it is a property
#: of this one model, not a cross-cutting product default.
#: **Inherited from v1, unmeasured against v2's own connection** (review
#: finding 7): v1 attributes the wider timeout to slower GMAC-crypto
#: handshakes, but this driver connects with ``Low`` auth (no GMAC), so that
#: premise may not hold here — carried over rather than narrowed without a
#: measurement, not evidence that 90 s is actually needed.
_READ_TIMEOUT_SEC = 90

#: Logger 1 (F7, meter-notes:94-98) — energy only, nothing electrical. Every
#: column carries a sibling OBIS (review finding 1) — the live 2026-08-09
#: scan showed this model denies every own-address ``scaler_unit`` read.
_LOGGER_1_COLUMNS: dict[tuple[str, int], tuple[str, str | None, Unit]] = {
    ("1.0.1.29.0.255", 2): ("import_active_kwh", "1.0.1.8.0.255", Unit.ACTIVE_ENERGY),
    ("1.0.2.29.0.255", 2): ("export_active_kwh", "1.0.2.8.0.255", Unit.ACTIVE_ENERGY),
    ("1.0.3.29.0.255", 2): ("import_reactive_kvarh", "1.0.3.8.0.255", Unit.REACTIVE_ENERGY),
    ("1.0.4.29.0.255", 2): ("export_reactive_kvarh", "1.0.4.8.0.255", Unit.REACTIVE_ENERGY),
}

#: Logger 2 (F7, meter-notes:109-113) — V/I only. Cumulative energy
#: (``1.0.1/2/3/4.8.0.255``) and per-phase power factor are captured by the
#: meter but deliberately not mapped here — see the module docstring (D16).
_LOGGER_2_COLUMNS: dict[tuple[str, int], tuple[str, str | None, Unit]] = {
    ("1.0.32.27.0.255", 2): ("volt_l1", "1.0.32.7.0.255", Unit.VOLTAGE),
    ("1.0.52.27.0.255", 2): ("volt_l2", "1.0.52.7.0.255", Unit.VOLTAGE),
    ("1.0.72.27.0.255", 2): ("volt_l3", "1.0.72.7.0.255", Unit.VOLTAGE),
    ("1.0.31.27.0.255", 2): ("current_l1", "1.0.31.7.0.255", Unit.CURRENT),
    ("1.0.51.27.0.255", 2): ("current_l2", "1.0.51.7.0.255", Unit.CURRENT),
    ("1.0.71.27.0.255", 2): ("current_l3", "1.0.71.7.0.255", Unit.CURRENT),
}


class Premier550Driver(DlmsProfileDriver):
    """CEWE Premier 550 over DLMS/COSEM HDLC."""

    _INTERFACE = "HDLC"
    _CLIENT_ADDRESS = "32"
    _SERVER_ADDRESS = "1"
    _LOGICAL_SERVER_ADDRESS = "0"
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
        return "premier550"

    def _read_timeout_ms(self) -> int:
        """TCP read / DLMS waitTime timeout: 90 s — wider than the shared
        60 s default (F9); no measured reason is recorded beyond the field
        connection profile, so it is carried over rather than narrowed."""
        return _READ_TIMEOUT_SEC * 1000

    def _protocol_args(self) -> list[str]:
        """Return the Premier 550 protocol flags, after the transport args.

        ``-l 0`` must follow ``-s`` — same ordering requirement
        :class:`~arichds.acquisition.drivers.smw110.Smw110Driver` documents
        (``GXSettings.py:348-349``).
        """
        return [
            "-i",
            self._INTERFACE,
            "-c",
            self._CLIENT_ADDRESS,
            "-s",
            self._SERVER_ADDRESS,
            "-l",
            self._LOGICAL_SERVER_ADDRESS,
            "-a",
            self._AUTHENTICATION,
            "-P",
            self._password,
            "-t",
            "Error",
        ]

    def get_obis_map(self) -> dict[str, tuple[str, int]]:
        """No instantaneous set for this model in v2 (ADR 0007).

        Mirrors :class:`~arichds.acquisition.drivers.prometer100.Prometer100Driver`
        — no production caller, kept only to satisfy the abstract interface.
        """
        return dict(INSTANTANEOUS_OBIS)

    def get_inter_frame_delay_ms(self) -> int:
        """Inter-frame delay: 500 ms — this model alone (F9); every other
        CEWE model uses :data:`~arichds.constants.DLMS_INTER_REQUEST_DELAY_MS`
        (200 ms)."""
        return 500

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
