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
`interval_sec` — two loggers on one meter are separate rows, never merged.
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

**Output Parity**:
The acceptance rule for domain modules: numbers shown by v2 must equal v1's output at v1's
default settings (`divide_by_1000=on` → kWh) on the same meter. Internals may differ freely.

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
