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
The background thread pool that reads meters on a fixed cadence (60 s, not configurable) and
writes Interval Readings. One worker per device, one lock per Transport Endpoint. Its tick
result is also where device status comes from — there is no separate health check.

**Probe**:
Talking to a meter to read its identity before committing anything. Creating or updating a
device probes first: no serial, no row. A probe is not a reading — it writes no Interval
Reading.
_Avoid_: test, ping, health check

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
