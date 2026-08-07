# gurux_dlms patterns & gotchas

Copy-ready patterns and the traps that cost real debugging time.

Two provenances are marked throughout, and the difference matters:

- **In v2 today** — the pattern is live in `app/src/arichds/`, with a file reference. Read
  the real code; it wins over this page.
- **v1-proven, not in v2 yet** — the pattern comes from `cewe`, which ran against these same
  meters and whose numbers the customer confirmed. It is a worked reference for M4–M6, not
  a description of code that exists here. **Do not cite it as if v2 had it.**

## Table of contents
- [Connect / disconnect lifecycle](#connect--disconnect-lifecycle) — *in v2*
- [Register + scaler (the #1 trap)](#register--scaler-the-1-trap) — *in v2*
- [Reading one identity register](#reading-one-identity-register) — *in v2*
- [ProfileGeneric by entry (billing)](#profilegeneric-by-entry-billing) — *mechanism in v2
  today (SMW110 load profile); billing subject still v1-proven*
- [ProfileGeneric by range (load profile)](#profilegeneric-by-range-load-profile) — *v1-proven*
- [GXDateTime handling](#gxdatetime-handling) — *v1-proven*
- [Meter-local time in selective access](#meter-local-time-in-selective-access) — *v1-proven*
- [Ambiguous COSEM class retry](#ambiguous-cosem-class-retry) — *v1-proven*
- [Gotcha checklist](#gotcha-checklist)

## Connect / disconnect lifecycle

*In v2*: `app/src/arichds/acquisition/drivers/_dlms.py` → `connect()` / `disconnect()`.

```python
settings = GXSettings()
if settings.getParameters(self._build_args()) != 0:
    raise MeterConnectionError(...)
self._client = settings.client
self._media = settings.media
if hasattr(self._media, "receiveTimeout"):
    self._media.receiveTimeout = timeout_ms
self._reader = GXDLMSReader(self._client, self._media, settings.trace, settings.invocationCounter)
self._reader.waitTime = timeout_ms
silence_frame_trace(self._reader)      # ARICHDS: closes the unredacted logFile.txt
self._media.open()
self._reader.initializeConnection()    # has a bounded association retry — do not add another
```

`disconnect()` swallows every exception and nulls `_reader`/`_client`/`_media` so a failed
close cannot break a `finally`. Always pair `connect()`/`disconnect()` around a **single**
read cycle — never hold the socket open between polls.

`connect()` already retries the association a bounded number of times and honours a
shutdown event (`set_shutdown_event`) so a stopping Poller does not sit through a full
retry ladder. Adding your own retry on top wedges the Transport Endpoint lock for every
other device on that line.

## Register + scaler (the #1 trap)

*In v2*: `_dlms.py` → `read_register()`. Pinned by `app/tests/test_dlms_scaler.py`.

`reader.read(register, 2)` returns the **raw integer** stored in the meter. The real value
is `raw * scaler`, where `scaler` comes from **attr 3 (scaler_unit)** and is already the
*multiplier* (`10**exponent`), **not** the exponent itself. Skipping it gives values off by
orders of magnitude — and treating it as an exponent (`10 ** int(obj.scaler)`) is exactly the
v1 defect **ADR 0002** exists to stop v2 from reproducing: at exponent 0 that computes
`10 ** int(1.0) == 10`, a phantom ×10 (v1 carried a compensating ÷10000 elsewhere to cancel
it back out — do not carry either half over; v2 must be correct *and* still match v1's
confirmed output at v1's default settings — Output Parity).

**Read attr 3 *before* attr 2** — this is the order the whole scheme rests on:

```python
obj = GXDLMSRegister(obis_code)
client.objects.append(obj)
reader.read(obj, 3)                  # populates obj.scaler (a MULTIPLIER, not an exponent) / obj.unit
value = reader.read(obj, 2)          # Gurux applies obj.scaler inside setValue — no manual arithmetic
```

Reading attr 2 first parses it with the default multiplier of 1 — `obj.scaler` has not been
populated yet — which silently yields a raw, unscaled integer with no error to signal it.
This page carried exactly that ordering bug (attr 2 then attr 3, plus the `10**` exponent
treatment above) until issue #10 fixed it; `_dlms.py::read_register()` has always read attr 3
first and is the pattern to copy. Treat an unreadable scaler as multiplier 1 and log a
warning rather than failing the read.

*v1-proven, not in v2 yet*: v1 cached the scaler per connection because attr 3 is constant
for a register and re-reading it every cycle cost roughly **500 ms per field on Premier
550**. v2 has no such cache — worth adding when M5's load profile makes the round-trips
add up, not before.

## Reading one identity register

*In v2*: `_dlms.py` → `read_meter_serial()`, driven by the class attribute
`METER_SERIAL_OBIS` so a model with a different serial OBIS overrides the **attribute**,
not the method. That is the shape every per-model difference should take (`CLAUDE.md`:
no `if/elif` on model in generic code).

Decode defensively: the meter may answer with `bytes`/`bytearray` (decode ASCII with
`errors="replace"`), something else entirely (`str()` it), and a blank or whitespace-only
answer means **no identity** — which the probe reports as `NO_SERIAL`, not as success.

## ProfileGeneric by entry (billing)

**The read-by-entry mechanism itself is *in v2 today***, for the SMW110W4 load profile —
`app/src/arichds/acquisition/drivers/smw110.py::Smw110Driver.read_load_profile()` (issue #10,
M4a-2). What follows in this section is still *v1-proven, not in v2 yet* for its actual
subject, **billing** (M6); read `read_load_profile()` for the load-profile version of this
same access pattern, including live-schema handling (D7) and the scaler-borrowing resolver
this meter needs because it denies `scaler_unit` on every load-profile capture column.
Source for the billing pattern below: v1
`src/drivers/_tcp_driver_base.py::read_billing_profile_row()`.

```python
pg = GXDLMSProfileGeneric(self.billing_profile_obis)   # e.g. "1.0.98.2.0.255"
client.objects.append(pg)
reader.read(pg, 3)                                     # populate pg.captureObjects

columns = [(str(obj.logicalName), int(cap.attributeIndex)) for obj, cap in pg.captureObjects]

entries_in_use = int(reader.read(pg, 7))               # read live — never assume capacity
rows = reader.readRowsByEntry(pg, 1, entries_in_use)   # v1 found entry 1 = NEWEST on Premier 550
```

Each row is a list aligned to `columns`. Scale numeric `attr == 2` cells the same way as a
standalone register; v1 resolved the scaler from the `E=0` total sibling OBIS (energy D=8
and demand D=6 are standalone-readable; cumulative-demand D=2 borrows the D=6 scaler — same
physical unit).

> Mitsubishi SMW110's billing profile is **`1.0.98.1.0.255`** — prefix `1.0`, not the `0.0`
> that SMART TCC uses (`docs/meter-notes/mitsu-obis-scan.md`).

## ProfileGeneric by range (load profile)

*v1-proven, not in v2 yet* — this **by-range** mechanism specifically, not load profile as a
whole: the SMW110W4 load profile is read in v2 today (see the callout above and
`read_load_profile()`), but by *entry*, because this meter refuses `readRowsByRange`. A
model that accepts range access still needs this pattern. Source: v1
`src/worker/load_profile_reader.py`.

```python
pg = GXDLMSProfileGeneric(logger_obis)     # 1.0.99.1.0.255 = Logger 1, 1.0.99.2.0.255 = Logger 2
client.objects.append(pg)
# Restore the captured column schema so Gurux can parse the binary buffer:
for co in cap_objects:
    obj = GXDLMSObject(ObjectType(co.class_id))
    obj.logicalName = co.obis_code
    pg.captureObjects.append((obj, GXDLMSCaptureObject(co.attribute_index, 0)))

raw_buffer = reader.readRowsByRange(pg, read_from_local, read_to_local)   # local time!
```

Notes:

- Read `capturePeriod` (attr 4) to know the interval seconds. **Do not assume 900.** Probed
  2026-08-05: Prometer 100 Logger 1 = 900 s but Logger 2 = **300 s**; Premier 550 has both
  at 900 s; Saral 305 has no Logger 2 at all
  (`docs/meter-notes/load-profile-capture-objects.md`).
- Firmware may return rows up to one capture period **beyond** `read_to` — filter to the
  requested window yourself.
- If the buffer column count ≠ the cached `captureObjects`, refresh the schema cache and
  retry: capture lists change when a meter is re-commissioned.
- On some meters the `…128.255` companion profile answers **"Read-Write denied"** for the
  capture period while still returning its capture list. A period read failing is not a
  dead profile.

## GXDateTime handling

*v1-proven*. `reader.read` returns `GXDateTime` for clock/time attributes — the Python
`datetime` is on **`.value`**, not the object itself. Coerce defensively: the value can also
arrive as a plain `datetime`, a raw `bytearray` (uncached schema), or `None` (a
time-compressed row).

```python
def to_dt(val):
    if val is None: return None
    if isinstance(val, datetime): return val
    if hasattr(val, "value") and isinstance(val.value, datetime): return val.value
    if isinstance(val, (bytes, bytearray)):
        gx = GXDLMSClient.changeType(val, DataType.DATETIME)   # decode raw bytes
        if gx and isinstance(getattr(gx, "value", None), datetime): return gx.value
    return None
```

## Meter-local time in selective access

*v1-proven*. `readRowsByRange` sends your `start`/`end` to the meter **as-is** for the
selective-access filter, and these meters store buffer timestamps in **local time
(ICT, UTC+7)** — not UTC.

```python
read_from_local = read_from_utc + _TZ_OFFSET     # +7h
read_to_local   = read_to_utc   + _TZ_OFFSET
raw_buffer = reader.readRowsByRange(pg, read_from_local, read_to_local)
```

Forgetting this returns an empty buffer (the window misses) or rows off by seven hours.

**This is the one place where v2's UTC-always rule meets a non-UTC wire format.** The
`CLAUDE.md` invariant is that Interval Readings are UTC, normalized **at write time in the
driver** — so the conversion belongs inside the driver, at the boundary, and a timestamp
must never leave the driver in local time.

## Ambiguous COSEM class retry

*v1-proven*. Some OBIS codes are exposed as different COSEM classes across meter samples
(v1 found `0.0.0.1.2.255` bill_date was a Register on the deployed Premier 550 fleet but
Clock/Data on others). Try candidate classes in order; a `GXDLMSException` whose message
contains **"inconsistent Class or object"** means "wrong class, try the next one" — anything
else ("undefined object", auth, framing) is a real error and must propagate.

```python
for cls in (GXDLMSRegister, GXDLMSClock, GXDLMSData):
    obj = cls(obis_code)
    client.objects.append(obj)
    try:
        return reader.read(obj, attr)
    except GXDLMSException as exc:
        if "inconsistent Class or object" in str(exc):
            continue                 # wrong class — next candidate
        raise                        # real error
```

Cache the winning class per connection so you do not re-pay the failed round-trips.

**Careful in v2**: `probe.py` maps `GXDLMSException` to `ProbeFailure.AUTH_FAILED`. If you
add an ambiguous-class retry to a path the probe uses, swallow the "inconsistent Class"
case *inside* the retry — otherwise a class mismatch surfaces to the operator as "the meter
rejected the credentials", sending them to fix a password that was never wrong.

## Gotcha checklist

- **`client.objects.append(obj)` before `reader.read(obj, …)`** — the client must know the
  object or the read fails.
- **Registers need attr 3 scaling.** The raw attr-2 value is unscaled. Use `Decimal` (ADR 0002).
- **`entries_in_use` (attr 7) is read live**, never assumed from `profileEntries` (capacity).
- **Entry order is a property of the profile, not the meter or model** — verify per profile,
  do not assume. Entry 1 = newest on Premier 550 billing (v1). Entry 1 = **oldest** on the
  SMW110W4 load profile (`smw110.py`, issue #10, field-confirmed 2026-08-07) — the opposite,
  on the very same physical meter that also has a billing profile.
- **`readRowsByRange` wants meter-local datetimes** (UTC+7), not UTC — and the conversion
  back happens in the driver.
- **`GXDateTime` carries the datetime on `.value`**, not the object itself.
- **Read `capturePeriod`; do not assume 900 s.** Logger 2 on a Prometer 100 is 300 s.
- **Avoid `getAssociationView()`** in production paths — read `captureObjects` (attr 3).
- **`reader.close()` must never raise** in cleanup — `MeterDriver.disconnect` is
  contractually forbidden from raising, and other code relies on it.
- **Trace `Error` is not enough** — `writeTrace` writes to `logFile.txt` unconditionally;
  `silence_frame_trace()` is what actually stops the unredacted, password-bearing dump.
- **Never write to a meter.** The test meters are read-only at a normal 60 s cadence
  (`CLAUDE.md`); `reader.write()` has no legitimate caller in this product.
- **Don't rename the vendored `GX*.py` APIs** — upstream samples, lint-exempt in
  `pyproject.toml`, copied verbatim on purpose.
- **Don't branch on model or brand** in generic code — add a driver hook or a class
  attribute (`CLAUDE.md` invariant; `METER_SERIAL_OBIS` is the worked example).
- **Reads run under the Transport Endpoint lock** and Manual Reads outrank background ticks
  (ADR 0006) — do not open a second connection to an endpoint you already hold.
