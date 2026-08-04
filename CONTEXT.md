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
users exist, then permanently closed. Precedes Login, which precedes Activation.
_Avoid_: registration, sign-up

### Data

**Interval Reading**:
One row of time-series meter data in COSEM shape — always UTC, always kWh — regardless of
whether the source was DLMS or Modbus. The normalization happens at write time, in the driver.
_Avoid_: load profile row (that's the feature, not the row), sample, logger reading

**Source**:
Which acquisition path produced a reading: `dlms` or `modbus`. A property of the reading,
never a branch in read-path code.

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
The background thread pool that reads meters on a fixed cadence and writes Interval Readings.
One worker per device, one lock per Transport Endpoint.
