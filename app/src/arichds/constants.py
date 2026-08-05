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
# The liveness cadence: prove every meter still answers a register, every 60 s.
# The tick stores nothing (ADR 0007); this is how often device status is
# refreshed, and ADR 0004's 3-strikes rule is written against it (~3 minutes to
# Offline), which is why SPEC §3.3 keeps it non-configurable.
POLL_INTERVAL_SEC: Final[int] = 60
# How long `Poller.stop()` waits for each worker to finish its current tick.
# Deliberately shorter than a worst-case DLMS read (TCP_READ_TIMEOUT_SEC): a
# worker mid-read is expected to outlast this and exit on its own afterwards,
# so shutdown and device add/remove stay responsive.
POLLER_STOP_JOIN_TIMEOUT_SEC: Final[float] = 5.0
# How long a Manual Read waits for a Transport Endpoint held by a background
# tick before giving up. Longer than one worst-case association
# (CONNECT_ASSOC_RETRY_ATTEMPTS x TCP_CONNECT_TIMEOUT_SEC) so a probe still
# waits out a slow-but-alive meter, and short enough that a wedged endpoint
# answers the operator instead of hanging the request (ADR 0006).
MANUAL_READ_LOCK_TIMEOUT_SEC: Final[float] = 120.0

# ─── Device status (ADR 0004) ─────────────────────────────────────────────────
# How many consecutive failed reads flip a device Offline. Three, not one: a
# single timeout on a GPRS link is normal, and flipping on it would flap the tree
# and write paired transition rows all day. At the fixed 60 s cadence this is
# ~3 minutes, and the cadence is deliberately not configurable (SPEC §3.3) so the
# two cannot drift apart.
OFFLINE_AFTER_CONSECUTIVE_FAILURES: Final[int] = 3

# ─── Read now jobs (SPEC §3.3) ────────────────────────────────────────────────
# The one job Read now runs at M3: an identity read that proves the meter
# answers a real register read, writing no Interval Reading (ADR 0007).
# M5 adds "load_profile" and M6 adds "billing" to this same list — the naming is
# fixed here now precisely so those two modules do not each invent one.
JOB_LIVENESS: Final[str] = "liveness"

# ─── Source (CONTEXT.md — a property of the reading, never a branch) ──────────
SOURCE_DLMS: Final[str] = "dlms"
SOURCE_MODBUS: Final[str] = "modbus"

# ─── Retry / backoff (v1 constants.py) ────────────────────────────────────────
# INNER association retry: absorbs a transient DLMS-association abort in place
# with a short fixed backoff.
CONNECT_ASSOC_RETRY_ATTEMPTS: Final[int] = 3  # incl. the first try
CONNECT_ASSOC_RETRY_BACKOFF_SEC: Final[float] = 0.5

# ─── Network / protocol (v1 constants.py) ─────────────────────────────────────
TCP_CONNECT_TIMEOUT_SEC: Final[int] = 30
TCP_READ_TIMEOUT_SEC: Final[int] = 60
DLMS_INTER_REQUEST_DELAY_MS: Final[int] = 200

# ─── Clock OBIS (v1 constants.py) ─────────────────────────────────────────────
# The DLMS clock object. **Nothing reads it today**: the driver-level
# reachability probe that did left with ADR 0007 (issue #8), and the liveness
# tick reads the Meter Serial instead — one register that proves both the
# association and a real read.
# Kept, not deleted, because it is a field-proven OBIS code from v1 and M6's
# billing period logic needs the meter's own clock.
HEALTH_CHECK_OBIS_CODE: Final[str] = "0.0.1.0.0.255"
HEALTH_CHECK_OBIS_ATTR: Final[int] = 2

# ─── Meter serial OBIS (v1 constants.py) ──────────────────────────────────────
METER_SERIAL_OBIS_CODE: Final[str] = "0.0.96.1.0.255"  # Device Serial Number (DLMS standard)
METER_SERIAL_OBIS_ATTR: Final[int] = 2

# ─── Unit normalization (REMAKE-PLAN §6.1 normalization contract) ─────────────
# DLMS registers report active energy in Wh; `load_profile_readings` is ALWAYS
# kWh. The division happens in the driver, at write time.
WH_TO_KWH_DIVISOR: Final[int] = 1000

# ─── Licensing ────────────────────────────────────────────────────────────────
# How stale the cached license state may get before a read re-evaluates it.
# ADR 0001: state must never be frozen at startup — a lease that lapses while
# the process runs takes effect without a restart.
LICENSE_RECHECK_INTERVAL_SEC: Final[float] = 60.0

# ─── Auth (SPEC §3.2) ─────────────────────────────────────────────────────────
# bcrypt 5.0 RAISES ValueError past this many *bytes* (older versions truncated
# silently). Passwords are validated against the UTF-8 encoded length, not the
# character count, so a short non-ASCII password cannot 500 the hash call.
BCRYPT_MAX_PASSWORD_BYTES: Final[int] = 72

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_FILE_MAX_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB
LOG_FILE_BACKUP_COUNT: Final[int] = 5

# ─── API error codes ──────────────────────────────────────────────────────────
ERROR_LICENSE_INVALID: Final[str] = "LICENSE_INVALID"
