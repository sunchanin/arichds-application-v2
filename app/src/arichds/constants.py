"""Named constants for ARICHDS.

No magic numbers anywhere: every timeout, retry count, delay and protocol code
is a named constant here. Values carried over from v1 (`cewe-worker/src/constants.py`)
are marked — they are proven on site and must not be "tuned" without evidence.
"""

from __future__ import annotations

import os
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
# no Interval Reading (ADR 0007). The naming is fixed here so each module does
# not invent its own — JOB_LOAD_PROFILE and JOB_BILLING below are its siblings.
JOB_LIVENESS: Final[str] = "liveness"
# The load-profile read (M5a-1, issue #15): stores Interval Readings. Reported
# as its own entry in `results` even when it could not run, because the Read now
# modal renders a row per entry and nothing at all for an absent one.
JOB_LOAD_PROFILE: Final[str] = "load_profile"
# The billing read (M6a, issue #21): stores Billing Readings. Same reporting
# rule as JOB_LOAD_PROFILE — its own `results` entry even when it could not run.
JOB_BILLING: Final[str] = "billing"

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

# ─── Billing (SPEC §3.6, ADR 0009, M6a issue #21) ─────────────────────────────
# How often the Scheduler runs the billing cycle over every device. A billing
# period is monthly and every read is a full-buffer read (ADR 0009 — there is
# no window, so no watermark and no catch-up to reason about); once a day is
# the SPEC-mandated cadence, not a tuned value.
#
# D12, ADR 0018, issue #43: since the Billing Change Check landed, this is a
# **backstop**, not the primary detection path — the check rides the Load
# Profile cycle's own connection every ~15 minutes and triggers the
# whole-buffer read the moment a period actually closes; this daily interval
# only matters if the check itself is ever wrong for a device (an unreadable
# buffer, an ordering assumption that turns out to be model-specific).
# **Do not "simplify" this to 900** — a separate association at that cadence
# is exactly the second-connection-per-tick cost ADR 0018 exists to avoid;
# the whole point of riding the Load Profile connection is to pay that cost
# once, not to make this interval redundant with it.
BILLING_INTERVAL_SEC: Final[int] = 86400

# ─── Battery (SPEC §3.7, M7-2, issue #29) ──────────────────────────────────────
# How often the Scheduler runs the battery cycle over every device. D1: the
# interval is one hour, not one day, because of `locks.py::try_acquire_background`
# — a background tick that cannot have the Transport Endpoint is *skipped, never
# queued* (ADR 0006), so a daily job that collides once with the load-profile
# cycle or a Manual Read on a shared line loses the whole day with no second
# attempt. Hourly, combined with the day-guard in `battery_cycle()` (a device
# already read today is skipped), gives 24 chances at exactly the same number
# of meter reads as a daily job, with no retry logic and no scheduler state.
# Do not "simplify" this back to daily — it would quietly delete the retry.
BATTERY_INTERVAL_SEC: Final[int] = 3600
JOB_BATTERY: Final[str] = "battery"

# ─── CSV export (SPEC §3.5/§3.7, M7 slice 3, issue #30, D-10) ─────────────────
# The Load Profile CSV auto-export job. Same cadence as `load_profile` on
# purpose (D-10): registered immediately behind it in `default_jobs()`, and
# the scheduler runs jobs in registry order within one pass, so this always
# runs right after that cycle without a second, independent interval to keep
# in sync.
CSV_EXPORT_INTERVAL_SEC: Final[int] = LOAD_PROFILE_INTERVAL_SEC
JOB_CSV_EXPORT: Final[str] = "csv_export"

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

# ─── Retention & backup (SPEC §5, M5c, issue #19) ─────────────────────────────
# How long rows are kept, for `load_profile_readings` (by `read_at`) and
# `device_events` (by `created_at`) alike. **One constant because it is one
# owner rule**, not two coincidences — and deliberately NOT reused from
# LOAD_PROFILE_BACKFILL_DAYS even though that is also 90: one says how far back a
# fresh device is read, this says how long any row survives. Tying them means
# tuning either one silently retunes the other.
RETENTION_DAYS: Final[int] = 90
# How many rows one DELETE statement removes, so the SQLite write lock is
# released between batches instead of held for the whole purge. **Measured**
# (2026-08-07, CPython's bundled SQLite 3.50.4) at REMAKE-PLAN §272's worst case
# — 20 all-Modbus meters, 28,800 rows/day, a 2.62 M-row / 375 MB table: one day's
# rows took 7 batches / 1.61 s at this size, planned as a covering-index scan on
# `ix_load_profile_readings_device_read_at`. That measurement is why no new index
# and no migration ship with this job.
RETENTION_DELETE_BATCH_SIZE: Final[int] = 5000
# How often the Scheduler purges expired rows, and how often it backs the
# database up. **Two constants, not one shared**: they are independent policies
# that happen to agree today, and sharing would mean retuning backup to 12 h
# silently retunes retention. Both are measured from service start (SPEC §5) —
# the registry's fixed interval, with no clock logic and no persisted state
# (ADR 0008).
RETENTION_INTERVAL_SEC: Final[int] = 86400
BACKUP_INTERVAL_SEC: Final[int] = 86400
# How many backup files survive rotation (SPEC §5).
BACKUP_KEEP_COUNT: Final[int] = 7
# The scheduler-registry names for both jobs. Deliberately not under "Read now
# jobs" above: neither ever appears in a Read now response.
JOB_RETENTION: Final[str] = "retention"
JOB_BACKUP: Final[str] = "backup"

# ─── Database Destination (SPEC §3.10, ADR 0016/0020/0021, M8-adjacent, #46) ──
# The sync that writes `load_profile_readings` and `billing_readings` into the
# customer's own MariaDB/MySQL — a Data-out Destination (CONTEXT.md), never our
# store.
#
# Its own interval, deliberately NOT aliased to LOAD_PROFILE_INTERVAL_SEC even
# though both are 900 today. CSV_EXPORT_INTERVAL_SEC above *does* alias it, and
# the reason is specific: that job is registered immediately behind the
# load-profile cycle and exists to run in the same pass, so one constant is one
# policy. This job is registered last and has no such relationship — it is a
# network write to a machine we do not own, on a cadence the owner picked for
# freshness. Sharing the constant would mean retuning the meter read silently
# retunes the customer's database, which is exactly what constants.py:126-129
# already refuses for RETENTION_DAYS / LOAD_PROFILE_BACKFILL_DAYS.
DBDEST_SYNC_INTERVAL_SEC: Final[int] = 900
# The wall-clock ceiling on one cycle, the shape LOAD_PROFILE_READ_BUDGET_SEC
# established. **Mandatory, not advisory** (SPEC §3.10): the scheduler runs
# every job sequentially on one thread, so a sync that hangs on an unreachable
# or locked customer database hangs the meter reads behind it. A cycle that
# runs out of budget stops cleanly and resumes on the next tick — which works
# only because the load-profile watermark lives in the destination rather than
# in a job record (ADR 0008), so a partial cycle is not a lost cycle.
DBDEST_SYNC_BUDGET_SEC: Final[float] = 60.0
# Per-connection timeouts, handed to PyMySQL. A Windows host that is simply not
# answering burns ~21 s on TCP retries alone, which is why the connect timeout
# is explicit rather than inherited from the OS.
DBDEST_CONNECT_TIMEOUT_SEC: Final[int] = 10
DBDEST_READ_TIMEOUT_SEC: Final[int] = 30
# Shorter than the two above because a *person* is waiting on the Test
# connection button, and a button that appears dead for twenty seconds gets
# pressed again. The sync job's own budget covers the background path.
DBDEST_TEST_CONNECT_TIMEOUT_SEC: Final[int] = 5
# How far the destination's own MAX(read_at) is rewound before we send. The
# safety margin ADR 0021 names: the watermark crosses a timezone boundary on
# every cycle, and re-sending an hour of rows that collapse onto themselves
# through ON DUPLICATE KEY UPDATE is a bounded waste, where an off-by-offset
# with no margin is a silent gap. Measured on the design probe (2026-08-24):
# one hour cost 28 re-sent rows and 0.4 s on the second cycle.
DBDEST_WATERMARK_REWIND_SEC: Final[int] = 3600
# Rows per source query, per executemany batch, and per purge `DELETE … LIMIT`.
# Matches RETENTION_DELETE_BATCH_SIZE's value for the same reason it was chosen
# there — a batch small enough that no single statement holds a lock long, big
# enough that the round trips disappear — but is its own constant: that one
# governs SQLite on our disk, this one governs a network round trip to someone
# else's server.
DBDEST_ROW_CHUNK: Final[int] = 5000
# The session sql_mode we set ourselves at connect, never inherited (SPEC
# §3.10, decision 7b). The reference server runs
# `NO_ZERO_IN_DATE,NO_ZERO_DATE,NO_ENGINE_SUBSTITUTION` with **no**
# `STRICT_TRANS_TABLES` (measured on MariaDB 10.4.32, 2026-08-24), which makes
# an over-long or out-of-range value truncate or clamp silently. Same argument
# ADR 0021 makes for DATETIME over TIMESTAMP: correctness must not live in the
# customer's `my.ini`. Nothing else belongs in here — ONLY_FULL_GROUP_BY in
# particular would break our own GROUP BY watermark query.
DBDEST_SESSION_SQL_MODE: Final[str] = "STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,NO_ENGINE_SUBSTITUTION"
# The scheduler-registry name. Deliberately **not** the same literal as the
# `database_destination` feature key below: one names a job in a log line, the
# other names an entitlement in a licence, and a grep that confuses them would
# be reading the wrong thing.
JOB_DBDEST_SYNC: Final[str] = "dbdest_sync"

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
# association and a real read. Kept, not deleted, because it is a field-proven
# OBIS code from v1. M6a's billing read (issue #21) needed the meter's own
# clock too, but reads it through the load-profile capture-column pattern's own
# local ``_CLOCK_OBIS`` in each driver, not this constant — the clock cell's
# *position* comes from the live captureObjects (D7), never assumed, so a
# shared constant here would only name the value, not save a read.
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
ERROR_FEATURE_DISABLED: Final[str] = "FEATURE_DISABLED"

# ─── Energy Summary (SPEC/CONTEXT.md, ADR 0012, M7-1 issue #28) ───────────────
# The Time-of-Use peak window, pre-shifted to UTC for ICT (local 09:00-22:00,
# METER_LOCAL_UTC_OFFSET_HOURS = +7) — carried over from v1
# `constants.py:299-300` (`TOU_PEAK_START_UTC` / `TOU_PEAK_END_UTC`). A
# product constant, never a request parameter or a `settings` key (ADR 0012:
# a second retroactive knob would move the numbers with nothing in the world
# to justify the move — unlike the Holiday table, which is the one knob that
# moves the summary toward the truth).
TOU_PEAK_START_UTC: Final[int] = 2
TOU_PEAK_END_UTC: Final[int] = 15

# ─── Feature entitlement (SPEC §3.9, M6b issue #22) ───────────────────────────
# Enabled = `.env FEATURES ∩ license features`. Ten sellable keys (M7 slice 4,
# issue #35, added `billing_image_export` — D1; issue #46 added
# `database_destination`, SPEC §3.10) plus one ops-only key that `.env` alone
# controls and the license never governs. `records` (not `instantaneous`) is
# the key that gates the Records page — owner decision 2026-08-09, SPEC §3.9.
# No licence has been issued yet (SPEC.md:1050-1053), so this key set is still
# free to change — which is why `database_destination` was added the moment the
# module was designed rather than when it shipped: adding it now is free and
# adding it after the first licence is issued is not.
SELLABLE_FEATURE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "billing",
        "load_profile",
        "energy_summary",
        "special_days",
        "records",
        "battery",
        "auto_capture",
        "billing_excel_export",
        "billing_image_export",
        "database_destination",
    }
)
FEATURE_KEYS: Final[frozenset[str]] = SELLABLE_FEATURE_KEYS | frozenset({"app_log"})

# ─── Capture write hardening (ADR 0010, M6b issue #22; v1 constants.py:13-21) ─
# Windows lacks O_NOFOLLOW (the symlink-open guard) — it degrades to 0 there.
# That is an honest degradation, not a silent one: creating a symlink on
# Windows needs admin/dev-mode privilege, and the `os.lstat` + `S_ISLNK`
# pre-check in `capture/write.py` is what actually carries the symlink guard
# on the platform this product ships on. O_BINARY is required on Windows for
# byte-exact PDF/xlsx output (the CRT's text-mode translation would otherwise
# corrupt binary data); it is 0 on POSIX, where there is no such mode.
O_NOFOLLOW: Final[int] = getattr(os, "O_NOFOLLOW", 0)
O_BINARY: Final[int] = getattr(os, "O_BINARY", 0)
