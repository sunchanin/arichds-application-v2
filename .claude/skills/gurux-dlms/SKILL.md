---
name: gurux-dlms
description: How to drive the gurux_dlms Python library (Gurux.DLMS.Python) the way cewe-worker does — building a client via GXSettings, the connect→read→close lifecycle over GXDLMSReader, reading Register/ExtendedRegister with scaler_unit, and pulling ProfileGeneric buffers (billing & load profile) by entry or date range. Use this whenever you touch the meter driver / reader layer (src/drivers/*, GX*.py, src/worker/load_profile_reader.py, src/billing/reader.py), debug a DLMS read (scaler, GXDateTime, "inconsistent Class or object", timeouts, entries_in_use, selective access), or write code that imports from gurux_dlms / gurux_net / gurux_common. For the meaning of an OBIS code or which model exposes a register, use the cewe-docs skill instead; this skill is the *library API*, that one is the *spec*.
---

# Gurux DLMS (Python) — library usage in cewe-worker

`gurux_dlms` is a port of Gurux's C# DLMS/COSEM stack. The API is camelCase, stateful,
and example-driven (upstream has almost no prose docs — you learn it from the sample
files). cewe-worker vendors the upstream samples at the worker root (`GXSettings.py`,
`GXDLMSReader.py`, `GXDLMSSecureClient2.py`, `GXCmdParameter.py`) and wraps them behind
the `MeterDriver` strategy classes in `src/drivers/`.

**This skill = how to use the library.** For OBIS codes, register meanings, per-model
coverage, and the Blue/Green Book spec, use the **cewe-docs** skill.

## The two layers — work at the right one

| Layer | Files | Touch it when… |
| ----- | ----- | -------------- |
| **cewe driver layer** (preferred) | `src/drivers/_tcp_driver_base.py`, `prometer100.py`, `saral305.py`, `premier550.py` | Adding/changing meter behaviour. Override hooks (`_build_args`, `get_obis_map`, `read_*`); don't reimplement the lifecycle. **No `if/elif model_name`** — add a driver method (`RULES.md §3.3`). |
| **vendored Gurux** | `GXSettings.py`, `GXDLMSReader.py`, `GXDLMSSecureClient2.py` | Rarely. These are upstream samples (camelCase, lint-exempt in `ruff.toml`). Don't rename their APIs; read them to understand a call. |

## Core lifecycle (the one pattern everything follows)

cewe never constructs `GXDLMSClient` by hand — it builds an argv-style list and lets
`GXSettings` parse it into a configured client + media. See `_tcp_driver_base.connect()`.

```python
settings = GXSettings()
ret = settings.getParameters(args)          # argv-style list; returns 0 on success
if ret != 0:
    raise MeterConnectionError(...)
client = settings.client                    # GXDLMSSecureClient2
media  = settings.media                     # GXNet (TCP)
media.receiveTimeout = timeout_ms           # socket read timeout (INV-SOCK-05)

reader = GXDLMSReader(client, media, settings.trace, settings.invocationCounter)
reader.waitTime = timeout_ms                # per-packet DLMS wait

media.open()                                # TCP connect
reader.initializeConnection()              # SNRM/UA → AARQ/AARE → HLS auth
# ... reads ...
reader.close()                              # ALWAYS in finally (INV-SOCK-01)
```

Invariants baked into the driver base (keep them):
- **Connect → read → close per cycle.** No persistent sockets (INV-SOCK-03).
- **`reader.close()` lives in a `finally`/`disconnect()` that never raises** (INV-SOCK-01).
- **Explicit timeout on all blocking I/O** via `media.receiveTimeout` + `reader.waitTime` (INV-SOCK-05).
- **Trace = `Error` in production** — higher levels grow the log file unbounded (INV-MEM-01).
- **Passwords/keys never in repr/str or logs** (INV-MEM-02; `CredentialRedactionFilter`).

## Reading a single object

Instantiate the matching COSEM class, register it on the client, then `reader.read(obj, attr)`:

```python
obj = GXDLMSRegister("1.0.1.8.0.255")
client.objects.append(obj)        # client must know the object before read
value = reader.read(obj, 2)       # attr 2 = value
```

`reader.read` returns the parsed Python value (int/float/str/`GXDateTime`/bytes). The
trap is **Register/ExtendedRegister return a *raw* integer at attr 2** — you must also
read **attr 3 (scaler_unit)** and apply `value * 10**scaler`. cewe does this once per
connection and caches it. See `references/patterns.md` → "Register + scaler".

## Reading a ProfileGeneric (load profile, billing)

```python
pg = GXDLMSProfileGeneric("1.0.98.2.0.255")
client.objects.append(pg)
reader.read(pg, 3)                       # attr 3 = captureObjects → column layout
n = int(reader.read(pg, 7))              # attr 7 = entries_in_use (read live, never assume)
rows = reader.readRowsByEntry(pg, 1, n)  # by entry index (1 = newest, per ADR 0004)
# or, by timestamp window:
rows = reader.readRowsByRange(pg, t_from, t_to)   # selective access by datetime
```

Do **not** call `getAssociationView()` to discover columns — it's far too slow on these
meters. Read `captureObjects` (attr 3) instead. Full worked examples (billing entry read,
load-profile range read, timestamp handling) are in [patterns.md](patterns.md).

## Before you write reader/driver code, read the reference files

- **[api-reference.md](api-reference.md)** — the library surface: import map, `GXDLMSReader`
  methods, COSEM object classes, the enums (`Authentication`, `Security`, `InterfaceType`,
  `ObjectType`, `DataType`, `SecuritySuite`), and the `GXSettings` flag table. Read this
  to find *which* class/method/enum to use.
- **[patterns.md](patterns.md)** — copy-ready cewe patterns and the gotchas that cost real
  debugging time: scaler/unit scaling, `GXDateTime.value`, meter-local timezone in
  `readRowsByRange`, the "inconsistent Class or object" ambiguous-class retry, `Decimal`
  vs float, and entry-order semantics. Read this before writing a read path.

Pull the relevant module's `CONTEXT.md` for domain language, and `cewe-docs` for the OBIS
map, before changing the billing/driver layer.
