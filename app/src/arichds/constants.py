"""Named constants for ARICHDS.

No magic numbers anywhere: every timeout, retry count, delay and protocol code
is a named constant here. Values carried over from v1 (`cewe-worker/src/constants.py`)
are marked — they are proven on site and must not be "tuned" without evidence.
"""

from __future__ import annotations

from typing import Final

# ─── Product identity ─────────────────────────────────────────────────────────
PRODUCT_NAME: Final[str] = "arichds"

# ─── Poller (SPEC §3.1) ───────────────────────────────────────────────────────
# M1's monitor cadence: read the instantaneous set every 60 s.
POLL_INTERVAL_SEC: Final[int] = 60
# How long `Poller.stop()` waits for each worker to finish its current tick.
# Deliberately shorter than a worst-case DLMS read (TCP_READ_TIMEOUT_SEC): a
# worker mid-read is expected to outlast this and exit on its own afterwards,
# so shutdown and device add/remove stay responsive.
POLLER_STOP_JOIN_TIMEOUT_SEC: Final[float] = 5.0
# Interval label written to `interval_readings.interval` for the M1 monitor
# cadence. Load-profile rows (M5) will carry "15m".
INTERVAL_LABEL_INSTANTANEOUS: Final[str] = "60s"

# ─── Source (CONTEXT.md — a property of the reading, never a branch) ──────────
SOURCE_DLMS: Final[str] = "dlms"
SOURCE_MODBUS: Final[str] = "modbus"
SOURCE_SIMULATED: Final[str] = "sim"

# ─── Retry / backoff (v1 constants.py) ────────────────────────────────────────
# INNER association retry: absorbs a transient DLMS-association abort in place
# with a short fixed backoff.
CONNECT_ASSOC_RETRY_ATTEMPTS: Final[int] = 3  # incl. the first try
CONNECT_ASSOC_RETRY_BACKOFF_SEC: Final[float] = 0.5

# ─── Network / protocol (v1 constants.py) ─────────────────────────────────────
TCP_CONNECT_TIMEOUT_SEC: Final[int] = 30
TCP_READ_TIMEOUT_SEC: Final[int] = 60
DLMS_INTER_REQUEST_DELAY_MS: Final[int] = 200

# ─── Health-check OBIS (v1 constants.py) ──────────────────────────────────────
HEALTH_CHECK_OBIS_CODE: Final[str] = "0.0.1.0.0.255"
HEALTH_CHECK_OBIS_ATTR: Final[int] = 2

# ─── Meter serial OBIS (v1 constants.py) ──────────────────────────────────────
METER_SERIAL_OBIS_CODE: Final[str] = "0.0.96.1.0.255"  # Device Serial Number (DLMS standard)
METER_SERIAL_OBIS_ATTR: Final[int] = 2

# ─── Unit normalization (REMAKE-PLAN §6.1 normalization contract) ─────────────
# DLMS registers report active energy in Wh; `interval_readings` is ALWAYS kWh.
# The division happens in the driver, at write time.
WH_TO_KWH_DIVISOR: Final[int] = 1000

# ─── Licensing ────────────────────────────────────────────────────────────────
# How stale the cached license state may get before a read re-evaluates it.
# ADR 0001: state must never be frozen at startup — a lease that lapses while
# the process runs takes effect without a restart.
LICENSE_RECHECK_INTERVAL_SEC: Final[float] = 60.0

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_FILE_MAX_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB
LOG_FILE_BACKUP_COUNT: Final[int] = 5

# ─── API error codes ──────────────────────────────────────────────────────────
ERROR_LICENSE_INVALID: Final[str] = "LICENSE_INVALID"
