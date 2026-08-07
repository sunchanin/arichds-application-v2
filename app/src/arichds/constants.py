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
# The identity read that proves the meter answers a real register read, writing
# no Interval Reading (ADR 0007). M6 adds "billing" to this same list — the
# naming is fixed here so each module does not invent its own.
JOB_LIVENESS: Final[str] = "liveness"
# The load-profile read (M5a-1, issue #15): stores Interval Readings. Reported
# as its own entry in `results` even when it could not run, because the Read now
# modal renders a row per entry and nothing at all for an absent one.
JOB_LOAD_PROFILE: Final[str] = "load_profile"

# ─── Load profile (SPEC §3.5, ADR 0008) ───────────────────────────────────────
# How far back the walk starts on a device with no stored rows.
LOAD_PROFILE_BACKFILL_DAYS: Final[int] = 90
# The window is walked in chunks this wide, oldest first, each written before
# the next is fetched (v1's LP_READ_CHUNK_HOURS).
LOAD_PROFILE_CHUNK_HOURS: Final[int] = 24
# How long the whole walk may keep going. Checked before starting each chunk
# except the first — a DLMS read cannot be interrupted mid-flight, and a call
# that reads nothing at all makes no progress against the watermark.
# Half of MANUAL_READ_LOCK_TIMEOUT_SEC on purpose: the walk holds the Transport
# Endpoint under ONE Manual Read acquisition, and a concurrent Manual Read waits
# that long, so this leaves room for the in-flight chunk to finish without
# timing the other caller out. Nobody has measured how long one chunk takes on
# this hardware — which is exactly why this is a budget and not a chunk count.
LOAD_PROFILE_READ_BUDGET_SEC: Final[float] = 60.0
# How often the Scheduler runs the load-profile cycle over every device
# (M5a-2, issue #16). 900 s is v1's `LP_READ_INTERVAL_SEC` carried over as an
# **assumption, not a measured number**: nobody has measured how long one
# device's LP read takes on this hardware, let alone a whole site's. If a site's
# cycle overruns 900 s nothing breaks — the watermark is the data (ADR 0008), so
# the next cycle resumes exactly where this one stopped — but the jobs queued
# behind it in the same thread are delayed by the overrun. That is the trigger to
# measure, not to add a second thread.
LOAD_PROFILE_INTERVAL_SEC: Final[int] = 900

# ─── Scheduler (SPEC §4, M5a-2) ───────────────────────────────────────────────
# How long `Scheduler.stop()` waits for the one job thread to finish the job it
# is inside. Deliberately shorter than a worst-case load-profile cycle (which is
# LOAD_PROFILE_READ_BUDGET_SEC per device, times however many devices a site
# has): the thread is expected to outlast this and exit on its own afterwards,
# because its shutdown event is already set. Mirrors
# POLLER_STOP_JOIN_TIMEOUT_SEC and for the same reason — shutdown stays
# responsive instead of waiting out a meter.
SCHEDULER_STOP_JOIN_TIMEOUT_SEC: Final[float] = 5.0
# The floor on the scheduler's sleep between passes. Only ever reached by a job
# whose interval is zero or negative — a real one is 900 s — and it exists so
# such a job costs a busy-ish loop instead of a hot one that pins a core.
SCHEDULER_MIN_SLEEP_SEC: Final[float] = 0.01

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

# ─── Meter clock offset (a property of the SITE, not of the model) ────────────
# Every SMW110W4 in service today runs an ICT (UTC+7, no DST) clock — the meter
# clock matched host clock exactly in the 2026-08-07 field probe
# (docs/meter-notes/raw/smw110w4-serial-probe-2026-08-07.txt:40-41). A site
# outside ICT is the trigger to make this per-device rather than one constant.
METER_LOCAL_UTC_OFFSET_HOURS: Final[int] = 7

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
