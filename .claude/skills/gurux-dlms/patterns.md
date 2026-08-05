# gurux_dlms patterns & gotchas (as proven in cewe-worker)

Copy-ready patterns and the traps that cost real debugging time. All of these are
extracted from working cewe code — file references included so you can read the full
context. Prefer adding to the driver layer over hand-rolling these.

## Table of contents
- [Connect / disconnect lifecycle](#connect--disconnect-lifecycle)
- [Register + scaler (the #1 trap)](#register--scaler-the-1-trap)
- [ProfileGeneric by entry (billing)](#profilegeneric-by-entry-billing)
- [ProfileGeneric by range (load profile)](#profilegeneric-by-range-load-profile)
- [GXDateTime handling](#gxdatetime-handling)
- [Meter-local timezone in selective access](#meter-local-timezone-in-selective-access)
- [Ambiguous COSEM class retry](#ambiguous-cosem-class-retry)
- [Gotcha checklist](#gotcha-checklist)

## Connect / disconnect lifecycle

Source: `src/drivers/_tcp_driver_base.py` `connect()` / `disconnect()`.

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
self._media.open()
self._reader.initializeConnection()
```

`disconnect()` swallows every exception and nulls `_reader/_client/_media` so a failed
close can't break a `finally`. Always pair `connect()`/`disconnect()` around a single
read cycle — never hold the socket open between polls (INV-SOCK-03).

## Register + scaler (the #1 trap)

`reader.read(register, 2)` returns the **raw integer** stored in the meter. The real
value is `raw * 10**scaler`, where `scaler` comes from **attr 3 (scaler_unit)**. Skipping
this gives values off by orders of magnitude. Use `Decimal`, not float, so billing totals
don't drift.

Source: `_tcp_driver_base.read_register()`.

```python
obj = GXDLMSRegister(obis_code)
client.objects.append(obj)
raw = reader.read(obj, 2)
if not isinstance(raw, (int, float, Decimal)):
    return raw                       # e.g. a Register that actually holds a GXDateTime
reader.read(obj, 3)                  # populates obj.scaler / obj.unit
value = Decimal(str(raw)) * Decimal(10) ** int(obj.scaler)
```

Cache the scaler per connection (`_scaler_cache`) — attr 3 is constant for a register, so
re-reading it every cycle wastes ~500 ms/field on Premier 550. Treat an unreadable scaler
as exponent 0 (no scaling) and log a warning, rather than failing the read.

## ProfileGeneric by entry (billing)

Source: `_tcp_driver_base.read_billing_profile_row()` / `read_billing_profile_rows()`.

```python
pg = GXDLMSProfileGeneric(self.billing_profile_obis)   # e.g. "1.0.98.2.0.255"
client.objects.append(pg)
reader.read(pg, 3)                                      # populate pg.captureObjects

columns = [(str(obj.logicalName), int(cap.attributeIndex)) for obj, cap in pg.captureObjects]

entries_in_use = int(reader.read(pg, 7))               # read live — never assume capacity
rows = reader.readRowsByEntry(pg, 1, entries_in_use)   # entry 1 = NEWEST (ADR 0004)
```

Each row is a list aligned to `columns`. Scale numeric `attr==2` cells the same way as a
standalone register; the scaler is resolved from the `E=0` total sibling OBIS (energy D=8
and demand D=6 are standalone-readable; cumulative-demand D=2 borrows the D=6 scaler —
same physical unit). See `_profile_scaler()`.

## ProfileGeneric by range (load profile)

Source: `src/worker/load_profile_reader.py` (~line 800+).

```python
pg = GXDLMSProfileGeneric(logger_obis)
client.objects.append(pg)
# Restore the captured column schema so Gurux can parse the binary buffer:
for co in cap_objects:
    obj = GXDLMSObject(ObjectType(co.class_id))
    obj.logicalName = co.obis_code
    pg.captureObjects.append((obj, GXDLMSCaptureObject(co.attribute_index, 0)))

raw_buffer = reader.readRowsByRange(pg, read_from_local, read_to_local)   # local time!
```

Notes:
- Read `capturePeriod` (a `GXDLMSData`, attr 2) to know the interval seconds.
- Firmware may return rows up to one capture period **beyond** `read_to` — filter to the
  requested window yourself (INV-LP-14).
- If the buffer column count ≠ cached `captureObjects`, refresh the schema cache and retry
  (INV-LP-08) — capture lists change when the meter is re-commissioned.

## GXDateTime handling

`reader.read` returns `GXDateTime` for clock/time attributes — the Python `datetime` is on
`.value`. Coerce defensively; the value can also arrive as a plain `datetime`, raw
`bytearray` (uncached schema), or `None` (time-compressed row).

Source: `load_profile_reader._to_python_dt()`.

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

## Meter-local timezone in selective access

`readRowsByRange` sends your `start`/`end` to the meter **as-is** for the selective-access
filter, and these meters store buffer timestamps in **local time (ICT, UTC+7)** — not UTC
(ADR-8). So convert your UTC window to meter-local before the call, and convert returned
timestamps back:

```python
read_from_local = read_from_utc + _TZ_OFFSET     # +7h
read_to_local   = read_to_utc   + _TZ_OFFSET
raw_buffer = reader.readRowsByRange(pg, read_from_local, read_to_local)
```

Forgetting this returns an empty buffer (window misses) or off-by-7h rows.

## Ambiguous COSEM class retry

Some OBIS codes are exposed as different COSEM classes across meter samples (e.g.
`0.0.0.1.2.255` bill_date is Register on the deployed Premier 550 fleet but Clock/Data on
others). Try candidate classes in order; a `GXDLMSException` whose message contains
**"inconsistent Class or object"** means "wrong class, try the next one" — anything else
("undefined object", auth, framing) is a real error and must propagate.

Source: `_tcp_driver_base.py` `_AMBIGUOUS_CLASSES` + `read_register()`.

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

Cache the winning class per connection so you don't re-pay the failed round-trips.

## Gotcha checklist

- **`client.objects.append(obj)` before `reader.read(obj, ...)`** — the client must know the
  object or the read fails.
- **Registers need attr 3 scaling.** Raw attr-2 value is unscaled. Use `Decimal`.
- **`entries_in_use` (attr 7) is read live**, never assumed from `profileEntries` (capacity).
- **Entry 1 = newest** on Premier 550 billing (ADR 0004) — don't assume oldest-first.
- **`readRowsByRange` wants meter-local datetimes** (UTC+7), not UTC (ADR-8).
- **`GXDateTime` carries the datetime on `.value`**, not the object itself.
- **Avoid `getAssociationView()`** — read `captureObjects` (attr 3) for the column layout.
- **`reader.close()` must never raise** in cleanup — wrap it (INV-SOCK-01).
- **Trace level `Error` in prod** (INV-MEM-01); keys/passwords never logged (INV-MEM-02).
- **Don't rename the vendored `GX*.py` APIs** — they're upstream samples, lint-exempt.
- **Don't branch on `model_name`** in generic code — add a driver hook (`RULES.md §3.3`).
