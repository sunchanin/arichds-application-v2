# ARICHDS Application

Windows-installed meter-monitoring application: reads electricity meters (DLMS/COSEM + Modbus),
stores readings locally, serves a local web UI, and pushes data to the team's central server.
Single context — one program, one database.

## Language

### Licensing

**Machine ID**:
The stable fingerprint of one customer machine (SHA-256 over collected hardware components,
`MachineGuid` on Windows). Shown to the user to send to the vendor; every license binds to it.
_Avoid_: fingerprint (in UI text), hardware ID

**Activation Code**:
A one-line base64 string containing the signed license, issued by the vendor (CLI now, portal
later). Pasting it into the first-run page activates the machine — effective immediately, no
service restart.
_Avoid_: license key, serial number

**Limited Mode**:
The state when no valid license is present: API returns 403 `LICENSE_INVALID` (health + SPA
still reachable), polling stays off, the process stays alive. Leaving Limited Mode is immediate
upon successful activation.
_Avoid_: trial mode, locked mode

**Lease**:
The 45-day validity window of a license, renewed daily via the portal. A kill-switch, not a
subscription — sites survive offline up to the lease length.

**Meter Key**:
A vendor-issued key for one additional device slot beyond `max_meters`, serial-bound at redeem
time. Slots are not returned when a device is deleted.

**Setup**:
The one-time first-run step that creates the bootstrap admin account — open only while zero
users exist, then permanently closed. Precedes Login, which precedes Activation. Re-running
Setup after it is closed returns 409 — "already done" is a conflict, not a permissions problem.
_Avoid_: registration, sign-up

**Role**:
A user's authorization level: `admin` (manage meters, users, settings, license) or `user`
(read every page, manual read, export). An enum column on `users` — there are no roles or
permissions tables.
_Avoid_: permission, group

**Access Token**:
The 8-hour JWT a Login returns, sent as `Authorization: Bearer …` on every request. Only its
SHA-256 hash is stored, in `user_tokens`; logout revokes that row. Expiry means signing in
again — there is no refresh.
_Avoid_: session cookie, API key

### Data

**Interval Reading**:
One row of time-series meter data in COSEM shape — always UTC, always kWh — regardless of
whether the source was DLMS or Modbus. The normalization happens at write time, in the driver.
The rows live in the `load_profile_readings` table, mapped by the `LoadProfileReading` class:
the term names the row and its contract, the table names what is in it — every interval the
meter itself recorded, since ADR 0007 stopped anything else being written there. A row is
identified by `(device, logger, read_at)` and carries the meter's own capture period in
`interval_sec` — two loggers on one meter are separate rows, never merged **in storage**. The
Load Profile page's list endpoint is the one deliberate exception (owner ruling, 2026-08-11,
`app/src/arichds/api/load_profile.py`): it projects Logger 1 and Logger 2 onto one row per
`read_at` for display, Logger 1 winning on a column both capture — the stored rows themselves
are untouched.
_Avoid_: load profile row (that's the feature, not the row), sample, logger reading

**Source**:
Which acquisition path produced a reading: `dlms` or `modbus`. A property of the reading,
never a branch in read-path code.

**Meter Serial**:
The serial number read **off the meter**, never typed by an operator. Unique across the
devices that currently exist — two rows may not point at the same physical meter. Deleting a
device frees its serial for reuse; there is no tombstone.
_Avoid_: device id (that's the surrogate key), meter number (that's an operator-entered label)

**Device Event**:
One row recorded when something *changes*: a status transition, or an operator action
(created, updated, paused, resumed, data cleared) with the name of who did it. Not a
per-tick heartbeat — a meter that stays online all month writes no rows.
_Avoid_: heartbeat, log entry

**Records**:
The page that answers whether the stored data is *complete* — one row per
**meter and logger**, one column per local calendar day, each cell counting that
day's Interval Readings. A complete day is `86400 / interval_sec` from the
meter's own capture period, never the constant 96 — a Prometer 100's Logger 2
runs at 300 s, so a complete day for it is 288, and that is why the row is per
logger and not per meter. A cell is exactly one of `complete` · `short` ·
`missing` · `period changed` (`missing` means no rows at all, so there is no
period to expect against; `period changed` means the day carried more than one
capture period and is counted against the most common one). The counts are
computed live from `load_profile_readings` on every request.
_Avoid_: records_96, completeness table, instantaneous records

**Billing Reading**:
One row of `billing_readings` — the register snapshot the meter itself froze when it closed a
billing period. Like an Interval Reading it is UTC, kWh, and COSEM-named flat columns
normalized at write time in the driver; unlike one it is **not** on a fixed cadence, because
the meter decides when a period ends. The energy and demand columns carry a total plus **four
tariffs** (`rate_a`…`rate_d`) — v1 stopped at three because CEWE sites use three, and the
SMW110W4 exposes `E=1..4`. Registers a meter reports but no screen shows are read and dropped,
not stored — which is why M4c added Demand Time and Cumulative Demand: v1's Billing page shows
both, so by that same rule they were missing, not excluded.
_Avoid_: bill row, billing record, meter snapshot

**Demand Time**:
When a maximum demand actually occurred — the COSEM `capture_time` an Extended Register carries
at **attribute 5**, alongside the value at attribute 2. It shares its OBIS code with the value
it belongs to, which is why a billing profile's columns are identified by `(OBIS, attribute)`
and never by OBIS alone: keyed by OBIS the value and its time collapse onto one another.
_Avoid_: peak time, demand timestamp, MD time

**Cumulative Demand**:
The running sum of a meter's maximum demands across billing periods (COSEM `D=2`) — a different
quantity from the Maximum Demand of one period (`D=6`), not a total of it. Stored per tariff
like every other billing group.
_Avoid_: total demand, accumulated demand, sum of demand

**Bill Date**:
The timestamp the **meter** stamped on a billing period, and the natural key of a closed one:
`(device, bill_date)` is unique, so reading the same buffer twice stores nothing new. It comes
from the meter's clock, never the server's — a period read a day late still belongs to the day
the meter cut it.
_Avoid_: read time (that's `read_at`), cut date, period date

**Open Period**:
The billing period a meter is still accumulating into — at most one per device, held in a
single row that every read **overwrites in place**. It gets a slot rather than a new row
because its Bill Date is the meter's live clock and advances on every read: keyed normally it
would write one junk row per read, which is exactly what it did in v1 until ADR 0018. It is
provisional by definition, and it is the one place billing shows a number that is not yet a
bill.
_Avoid_: current billing, running row, latest reading (that's whichever period is newest)

**Energy Summary**:
Interval Readings added up into **Time-of-Use buckets** — Peak, Off-Peak and Holiday — per
device and local calendar day. It is **derived, never stored and never read from a meter**:
the numbers are aggregated out of `load_profile_readings` on every request, exactly as the
Records page counts its cells live. Peak is a local clock window on days that are not Holiday;
Holiday is one bucket that swallows weekends and both kinds of Holiday alike, so a Saturday
inside the peak window is Holiday energy, not Peak energy (ADR 0016). Only **active** energy is
counted, import and export; the reactive columns exist on the row and are deliberately ignored.
Because nothing is stored, **an Energy Summary is not reproducible over time**: adding a Holiday
today changes what last January reports tomorrow. That is a property of the design, not a
fault — the Holiday table is the one knob that moves it, and it moves it toward the truth. The
peak window is a constant for the same reason: a second retroactive knob would move the
numbers with nothing in the world to justify the move.
_Avoid_: TOU report, energy report, meter energy (that's Energy Registers)

**Energy Registers**:
A meter's **cumulative** energy counters (COSEM `D=8` — import/export, active/reactive) read
straight off the meter and kept as a dated snapshot in `energy_register_readings`. It is the
other half of the Energy Summary page and shares its licence key, but it shares no data with
it: one is arithmetic over rows we already hold, the other is a fresh association to a meter.
Cumulative counters are not instantaneous values, which is why displaying them does not
reopen ADR 0007 — a running total since the meter was commissioned says nothing about *now*.
_Avoid_: energy summary (that's the buckets), live energy, instantaneous energy

**Battery Reading**:
One row of `battery_readings` — the raw charge/status value a CEWE meter reports at
`0.0.96.6.1.255`, **stored verbatim and never interpreted**: no scaling, no threshold, no
colour classification. Written by an hourly background job that skips a device already read
today (UTC calendar day); a failed read stores no row at all — that is what makes the hourly
cadence a retry rather than a duplicate. It is a trend, not an instantaneous value, so
displaying it does not reopen ADR 0007 the way a live measurement would. `supports_battery`
is `True` for exactly the three CEWE models — the drivers that implement the read — never a
per-brand guess.
_Avoid_: remaining time, battery percentage, battery health (nothing in this build computes
any of them — the register is a display code, not a duration)

**App Log** (M7-4, issue #31):
The **rotating application log file** (`%ProgramData%\ARICHDS\logs\arichds.log`) the process
itself writes — read-only, tail-only, never written to or deleted by the product. Every line
already passed `CredentialRedactionFilter` at write time (M1), so the App Log page shows it as
read: there is no second redaction pass on read. A line that is not a parseable header (e.g. a
traceback line) is joined onto the previous entry's message rather than becoming its own
level-less entry, so filtering to a minimum level does not hide the traceback body a matching
ERROR produced.
_Avoid_: Device Event, audit log (`device_events` is a different thing with different
retention — a status transition or an operator action, not a line of process output; the two
are easy to conflate and must not be)

**Holiday**:
A day the Energy Summary counts into the Holiday bucket. Three things make a day one and they
are equal in force: it is a Saturday or Sunday, or it matches an **annual** Holiday (month and
day, recurring every year), or it matches a **public** Holiday (one exact date). Holidays are
machine-wide — there is no per-device set — and the whole set travels between machines as one
JSON file. 29 February is refused as annual, because in a non-leap year it would match nothing
and say nothing about why.
_Avoid_: day off, non-working day, weekend flag (a weekend is a Holiday, not a separate kind)

**Special Day**:
A row in a **meter's own** COSEM class-11 Special Days Table (`0.0.11.0.0.255`) — the calendar
the meter uses to switch its internal tariff, carrying an index, a date and a `dayId`. It is
**read and displayed, never written**, and never stored: the Special Days page shows what the
meter holds right now.

It is not a Holiday, and the difference is who owns it. A Holiday is ours and decides our TOU
buckets; a Special Day is the meter's and decides the meter's. They meet at exactly one place:
an operator may **import** a meter's Special Days as the starting set of Holidays, because a
meter in service already carries the local calendar (an ST-3CL served 82 entries to 2041). That
import is one-way and it is a convenience, not a sync — nothing afterwards keeps the two in
step, and a `dayId` is the meter's tariff code, not our word for "holiday".
_Avoid_: meter holiday, special date, holiday table (that's ours)

**Retention**:
The daily job that deletes rows past 90 days — Interval Readings by `read_at`, Device Events by
`created_at`. **Device Events go uniformly**: a status transition the machine wrote and an
operator action carrying a username expire alike, so after 90 days there is no record of who
paused a meter or cleared its data. That simplicity was chosen deliberately, knowing the cost.
It cannot disturb the load-profile watermark, which is the *newest* row; a device purged empty
simply backfills 90 days again on its next read.
_Avoid_: cleanup, archiving (nothing is archived — the rows are gone), purge job

**Daily Backup**:
The daily job that writes the whole database to `%ProgramData%\ARICHDS\backup\` with
`VACUUM INTO` — a file copy would not be a database, because WAL means `.db` + `-wal` + `-shm`.
Seven files are kept, named by UTC timestamp and rotated by name. It sits on **the same disk as
the original**, so it protects against a wrong delete or a corrupted database and **not** against
the disk failing. The destination is fixed, not a setting.
_Avoid_: snapshot, dump, export (that's the CSV feature), replica

**Capture**:
A PDF (and, when sold, an xlsx) document for one closed Billing Reading, written to a folder an
admin chooses (`capture_dir`, ADR 0010) — never a fixed path, because the folder **is** the
handoff mechanism: the operator hands the file to a customer through whatever their own
workflow already reaches (a network share, a synced folder, their mail client's watched
directory). Its path is derived from convention every time —
`<capture_dir>/<meter_serial>/<bill_date>.pdf` — and never stored in the database, so changing
`capture_dir` orphans every existing capture by design: old files stay exactly where they are
and simply stop being reachable from the Billing page. Created eagerly, synchronously, the
moment a closed period is inserted; a missing one is rendered again on download rather than
tracked as a failure. The Open Period never has one.
_Avoid_: report, export (that's a different feature), snapshot

**Export Format**:
The four machine-wide settings that govern the Load Profile CSV auto-export (M7 slice 3, issue
#30) — the timestamp token format, the filename template, the auto-save switch, and the output
folder. **Machine-wide, not per-meter**: one customer's site runs meters set up identically, so
a per-device value would solve a problem nobody has hit (grill M7, 2026-08-11). The timestamp
format and the filename template live on their own ExportFormat page; the auto-save switch and
the output folder sit on the Load Profile page instead, next to "Save CSV now" and the table
they export.

**The CSV they govern is always kWh/kvarh — it never follows the Display unit setting**
(ADR 0013). The file is a contract an operator's downstream tooling appends to for months; the
Display unit setting is a view, re-rendered on every request. A destination with a past on disk
cannot retroactively agree with a switch flipped today.
_Avoid_: divide by 1000 (v1's setting; not ported — write-time normalization already made it
vacuous), per-meter format (rejected — see above)

**Output Parity**:
The acceptance rule for domain modules: numbers shown by v2 must equal v1's output at v1's
default settings (`divide_by_1000=on` → kWh) on the same meter. Internals may differ freely.
**It is judged on stored rows, not on screens** (grill M4c, 2026-08-09) — the two products
present the same data differently on purpose, and v1 has no screen at all for a second logger,
so a screen-to-screen comparison would fail on presentation choices and would leave the
two-logger case unmeasurable. Comparing v1's tables to v2's is also the only form of the test
that can be frozen as a replay fixture and re-run without a meter.

### Acquisition

**Transport Endpoint**:
The physical channel a meter is reached through — `host:port` for TCP, a COM port name for
serial. Concurrency locks key on the endpoint, not the device: devices sharing a serial line
queue behind one lock.
_Avoid_: connection (ambiguous), socket

**Poller**:
The background thread pool that reads every meter on a fixed cadence (60 s, not configurable)
to prove it still answers. One worker per device, one lock per Transport Endpoint. Its tick
runs the Liveness job — one identity register, discarded — and **writes no row at all**
(ADR 0007); its outcome is where device status comes from, and there is no separate health
check.

**Scheduler**:
The single background thread that runs every periodic job from a registry of
`(name, interval, fn)` — one thread for all of them, not one per job. Jobs run sequentially in
registry order, each on its own interval, and a job that throws costs only its own cycle: it is
logged and runs again at its next interval. It stops in Limited Mode and starts on activation,
without a restart. **Not all of its jobs read meters**: it runs the load-profile cycle (every
enabled device that is not Offline) alongside Retention and the Daily Backup, which touch no
meter at all. Every meter read it does make is background work — a device whose Transport
Endpoint is busy is skipped and read next cycle, never queued ahead of a person.
_Avoid_: cron, worker, background service, a per-module scheduler (v1 had seven)

**Probe**:
Talking to a meter to read its identity before committing anything. Creating or updating a
device probes first: no serial, no row. A probe is not a reading — it writes no Interval
Reading.
_Avoid_: test, ping, health check

**Liveness**:
The job a tick and Read now run to prove a meter answers a real register read — one
association, one identity register, disconnect. It is not a data read: it produces no Interval
Reading, and it never reports a measured value. M5 and M6 name their jobs (`load_profile`,
`billing`) against this one.
_Avoid_: ping, health check

**Manual Read**:
A read a person asked for — Read now, Test connection, or the probe behind Create/Update.
Manual Reads take the Transport Endpoint lock ahead of the Poller: a skipped background tick
costs one minute of data, a person waiting on a button costs trust.
_Avoid_: on-demand read, forced read

**Pause**:
Stopping every background read of one device while leaving it fully visible — the `enabled`
column, persisted so it survives a service restart. Manual Reads still work on a paused
device. Resume puts it back to Unknown until the next tick proves otherwise.
_Avoid_: disconnect, disable, deactivate
