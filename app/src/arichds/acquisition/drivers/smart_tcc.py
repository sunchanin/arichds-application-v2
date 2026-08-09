"""DLMS/COSEM driver for the SMART TCC meter family — HighGMAC + Security
Suite 0 (M4c, issue #25). The first driver on this repo's encrypted path.

**One class, five catalog keys** (D2): ``st3c``, ``st3cl``, ``st33tl``,
``st3tl``, ``st3dh`` all resolve to :class:`SmartTccDriver` in
``factory._registry()`` — v1 serves the whole family from one driver class
(v1 ``smart_tcc.py:3-5``) because they share one connection profile and one
OBIS set, and this class does the same. :attr:`model_name` returns
``"smart_tcc"`` — the family name, matching v1 and
:attr:`~arichds.acquisition.catalog.Brand.SMART_TCC` — deliberately *not* one
of the five catalog keys, because one class serves five. This is safe:
``model_name`` reaches only log lines and the synthetic ``argv[0]`` in
``_build_args()`` (:mod:`~arichds.acquisition.drivers._dlms`); nothing
compares it to a catalog key.

**D14 — the four unscanned models are an assumption, and this is where it is
recorded.** ``st3c``, ``st33tl``, ``st3tl``, ``st3dh`` are assumed identical
to the scanned 3CL (``st3cl``) *because v1 serves all five from one driver
class* — not because anyone has measured them. The whole family is
unverified against hardware in v2: the only unit ever probed is the 3CL at
``203.170.148.103``, and it has been unreachable (timeout, not refused) on
every check since 2026-07-18 (F13, D1). No test in this repository connects
to it.

Connection parameters (F1, v1 ``smart_tcc.py:110-129,166-215``, proven
against the real 3CL on 2026-07-18): TCP/IP · HDLC · LN referencing · client
address 1 · physical server 127, logical server 127 (``-s`` then ``-l``, in
that order — order is load-bearing, see :meth:`_protocol_args`) · HighGMAC ·
AuthenticationEncryption · Security Suite 0 · system title ``"ABCDEFGH"`` ·
auth key and block cipher key below · invocation-counter OBIS
``0.0.43.1.0.255`` pre-read via ``-v`` (the base's
:meth:`~arichds.acquisition.drivers._dlms.DlmsDriver._open_association`
already forwards ``settings.invocationCounter`` into the reader — no explicit
pre-read code is needed here, F2) · **no ``-P``** — HighGMAC carries no LLS
password. Read timeout 90 s, inter-frame delay 500 ms (F1).

Key material (auth key, block cipher key, system title) is customer-confirmed
identical for every TCC meter, so it is owned by this driver as module
constants — **never** stored per-device, **never** in the API payload, and
**never** a Device-form field (D9, closed at the M4c grill,
``SPEC.md``:368-373). ``__init__`` absorbs and ignores whatever kwargs the
factory forwards (``block_cipher_key``/``authentication_key``), exactly as
v1's does. The keys and the argv are never logged — ``DlmsDriver.__repr__``
already excludes the password, and ``_protocol_args()`` has no caller that
logs it.

Load profile reads Logger 1 only (D7) — three reasons: v1's TCC driver reads
``1.0.99.1.0.255`` only (Output Parity, v1 ``smart_tcc.py:39-42``); Logger 2
(``1.0.99.2.0.255``) captures purely **instantaneous** registers (F4), and
ADR 0007 says v2 displays no live value and persists nothing instantaneous;
and at a 60 s capture period it would write 1440 rows/device/day — five times
Prometer 100's Logger 2 (288/day, the widest case the owner has accepted,
``SPEC.md``:345-356) — for values the product has decided not to store.

Billing reads Scheme 1 (``0.0.98.1.0.255``) only — Scheme 2
(``0.0.98.2.0.255``) is a daily 00:00 snapshot, not a bill cut (F8): all
eight of its rows were found byte-identical to each other and to the live
standalone registers, with the period counter stuck at 1.

**D6 — a known, accepted limitation of the inherited scaler-resolution
fallback.** :func:`~arichds.acquisition.drivers._dlms_profile.resolve_billing_multiplier`'s
``D=2 -> D=6`` borrow (for Cumulative Demand) passes one COSEM class for
every candidate it tries. On this family, a ``D=2`` column is
``GXDLMSRegister`` (F9) but its ``D=6`` borrow candidates are queried as
whatever class the *original* column was — if that borrow path ever fires
here, it would query a ``GXDLMSRegister``-shaped address under the wrong
class and resolve to ``None``. This is accepted, not fixed, for three
reasons: F10 records that TCC's own-address scaler reads succeeded on every
register checked (exponent 0 throughout), so this fallback should never need
to fire on this family; the borrow exists to serve a Premier 550 failure
mode, not this one; and the failure outcome — ``None`` — is exactly the
documented "unresolvable -> NULL, never guess" rule, not a wrong number.
Widening shared resolution code that three live-verified CEWE drivers depend
on, to fix a path on a meter nobody can currently reach, is not a trade this
issue takes. This is a **live-verification item** — nobody may "fix" this
blind before a real TCC billing read confirms whether it ever actually
fires.
"""

from __future__ import annotations

from typing import Any

from gurux_dlms.enums import Unit
from gurux_dlms.objects import GXDLMSRegister

from arichds.acquisition.connection_params import ConnectionParams
from arichds.acquisition.drivers._dlms_profile import DlmsProfileDriver
from arichds.acquisition.obis import INSTANTANEOUS_OBIS

#: SMART TCC key material — driver-owned, customer-confirmed identical
#: fleet-wide (F1, D9). These are the DLMS Blue Book default keys, which
#: every meter in this fleet still uses at the factory setting. **Never
#: logged** (module docstring) and never read from a ``Device`` column.
_TCC_SYSTEM_TITLE_HEX = "4142434445464748"  # "ABCDEFGH" (ASCII) as hex
_TCC_AUTH_KEY = "D0D1D2D3D4D5D6D7D8D9DADBDCDDDEDF"
_TCC_BLOCK_CIPHER_KEY = "000102030405060708090A0B0C0D0E0F"
_TCC_INVOCATION_COUNTER_OBIS = "0.0.43.1.0.255"

#: F1 — this family's own read timeout and inter-frame delay, wider than the
#: CEWE default (60 s / 200 ms): the GPRS link is slow and the HighGMAC
#: handshake costs more round trips.
_READ_TIMEOUT_SEC = 90
_INTER_FRAME_DELAY_MS = 500

#: Logger 1 only (D7) — 11 of the 35 columns the round-4 scan recorded
#: (F3, ``docs/meter-notes/tcc-obis-scan.md``:648-684) are mapped; the other
#: 24 (per-phase interval energy, the V/I `x.24.124` set, phase angles,
#: record status, the profile self-reference) have no ``IntervalReading``
#: column and are dropped structurally, the way ``saral305.py``'s three
#: unmapped columns are. ``freq`` maps to nothing (F3 — only the
#: instantaneous ``1.0.14.7.0.255`` exists, not a capture column) and stays
#: ``None`` on every row.
_LOGGER_1_COLUMNS: dict[tuple[str, int], tuple[str, str | None, Unit]] = {
    ("1.0.1.29.0.255", 2): ("import_active_kwh", "1.0.1.8.0.255", Unit.ACTIVE_ENERGY),
    ("1.0.2.29.0.255", 2): ("export_active_kwh", "1.0.2.8.0.255", Unit.ACTIVE_ENERGY),
    ("1.0.3.29.0.255", 2): ("import_reactive_kvarh", "1.0.3.8.0.255", Unit.REACTIVE_ENERGY),
    ("1.0.4.29.0.255", 2): ("export_reactive_kvarh", "1.0.4.8.0.255", Unit.REACTIVE_ENERGY),
    ("1.0.32.27.0.255", 2): ("volt_l1", "1.0.32.7.0.255", Unit.VOLTAGE),
    ("1.0.52.27.0.255", 2): ("volt_l2", "1.0.52.7.0.255", Unit.VOLTAGE),
    ("1.0.72.27.0.255", 2): ("volt_l3", "1.0.72.7.0.255", Unit.VOLTAGE),
    ("1.0.31.27.0.255", 2): ("current_l1", "1.0.31.7.0.255", Unit.CURRENT),
    ("1.0.51.27.0.255", 2): ("current_l2", "1.0.51.7.0.255", Unit.CURRENT),
    ("1.0.71.27.0.255", 2): ("current_l3", "1.0.71.7.0.255", Unit.CURRENT),
    ("1.0.13.27.0.255", 2): ("avg_geo_pf", "1.0.13.7.0.255", Unit.NONE),
}


class SmartTccDriver(DlmsProfileDriver):
    """Shared DLMS driver for all five SMART TCC models — HighGMAC + Suite 0.

    See the module docstring for the connection profile, key ownership,
    Logger 1-only rationale, Scheme-1-only billing, D14's unscanned-models
    caveat and D6's accepted scaler-fallback limitation.
    """

    _INTERFACE = "HDLC"
    _REFERENCE = "ln"
    _CLIENT_ADDRESS = "1"
    _PHYSICAL_SERVER_ADDRESS = "127"  # 0x7F
    _LOGICAL_SERVER_ADDRESS = "127"  # 0x7F
    _AUTHENTICATION = "HighGMac"
    _SECURITY = "AuthenticationEncryption"
    _SECURITY_SUITE = "Suite0"

    #: D5 — Scheme 1 (F5); Scheme 2 (`0.0.98.2.0.255`) is a daily snapshot,
    #: never a bill cut (F8), and is never read by this driver.
    BILLING_PROFILE_OBIS = "0.0.98.1.0.255"

    #: D5/F6 — Clock only. CEWE's own bill-date column (``0.0.0.1.2.255``) is
    #: absent from this family's capture list ("undefined object" standalone);
    #: the near-miss ``1.0.0.1.2.255`` is a capture column but reads
    #: UNSET/year-2000 in the buffer and gives one value for every row —
    #: neither is usable.
    BILL_DATE_CANDIDATES: tuple[tuple[str, int], ...] = (("0.0.1.0.0.255", 2),)

    #: D5/F7 — declared absent: this family has no reset-reason register at
    #: all (``0.0.0.1.12.255`` is not a capture column). Declaring ``None``
    #: (rather than leaving the base's CEWE default, which would be
    #: *discovered* absent on every read) is what keeps
    #: :meth:`~arichds.acquisition.drivers._dlms_profile.DlmsProfileDriver.read_billing`
    #: silent about it — a WARNing that would otherwise fire on every read
    #: forever, for a condition that is this family's documented normal
    #: state, not a fault.
    RESET_REASON_KEY: tuple[str, int] | None = None

    #: D5/F9 — Register, not ExtendedRegister: the one COSEM-class difference
    #: this family has from CEWE. Max demand (``D=6``) stays ExtendedRegister
    #: on both, unaffected by this declaration.
    CUMUL_DEMAND_COSEM_CLASS: type = GXDLMSRegister

    LOAD_PROFILE_COLUMN_MAP: dict[int, dict[tuple[str, int], tuple[str, str | None, Unit]]] = {1: _LOGGER_1_COLUMNS}

    def __init__(self, conn: ConnectionParams, password: str, **kwargs: Any) -> None:
        """Initialise the driver.

        Args:
            conn: Transport identity (net) for this connection.
            password: Accepted for interface parity with every other driver,
                but **unused** — HighGMAC is keyless, so no ``-P`` flag is
                ever emitted (never logged, never sent).
            **kwargs: Absorbed and ignored — the factory forwards
                ``block_cipher_key``/``authentication_key`` kwargs meant for
                other HLS models; this driver uses its own fixed module
                constants instead (D9).
        """
        super().__init__(conn=conn, password=password, **kwargs)

    @property
    def model_name(self) -> str:
        """The family name, not a catalog key (D2) — one class serves all
        five SMART TCC models."""
        return "smart_tcc"

    def _read_timeout_ms(self) -> int:
        """TCP read / DLMS waitTime timeout: 90 s (F1 — GPRS latency + GMAC
        crypto)."""
        return _READ_TIMEOUT_SEC * 1000

    def _protocol_args(self) -> list[str]:
        """Return the SMART TCC protocol flags, after the transport args.

        Mirrors the proven v1 argv exactly (order is load-bearing — F1,
        v1 ``smart_tcc.py:166-215``): HDLC + LN referencing, client 1,
        physical server 127 (``-s``) then logical server 127 (``-l`` —
        must follow ``-s``, ``GXSettings.py``:343-349) · HighGMAC +
        AuthenticationEncryption + Suite 0 · **no** ``-P`` (keyless) ·
        system title, auth key, block cipher key · invocation-counter OBIS.
        """
        return [
            "-i",
            self._INTERFACE,
            "-r",
            self._REFERENCE,
            "-c",
            self._CLIENT_ADDRESS,
            "-s",
            self._PHYSICAL_SERVER_ADDRESS,
            "-l",
            self._LOGICAL_SERVER_ADDRESS,
            "-a",
            self._AUTHENTICATION,
            "-C",
            self._SECURITY,
            "-V",
            self._SECURITY_SUITE,
            "-T",
            _TCC_SYSTEM_TITLE_HEX,
            "-A",
            _TCC_AUTH_KEY,
            "-B",
            _TCC_BLOCK_CIPHER_KEY,
            "-v",
            _TCC_INVOCATION_COUNTER_OBIS,
            "-t",
            "Error",
        ]

    def get_obis_map(self) -> dict[str, tuple[str, int]]:
        """No instantaneous set for this model in v2 (ADR 0007).

        D10 — truthful, not a placeholder: all eight of the shared
        ``INSTANTANEOUS_OBIS`` codes are present in this family's
        association view. No production caller since ADR 0007 removed the
        instantaneous read.
        """
        return dict(INSTANTANEOUS_OBIS)

    def get_inter_frame_delay_ms(self) -> int:
        """Inter-frame delay: 500 ms (F1) — this family's own value, wider
        than the CEWE default (200 ms), to pace requests over the slow GPRS
        link."""
        return _INTER_FRAME_DELAY_MS
