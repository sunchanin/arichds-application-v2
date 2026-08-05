---
name: gurux-dlms
description: How to drive the gurux_dlms Python library (Gurux.DLMS.Python) in ARICHDS v2 — building a client via the vendored GXSettings, the connect→read→disconnect lifecycle over GXDLMSReader, reading Register/ExtendedRegister with scaler_unit, and pulling ProfileGeneric buffers (load profile & billing) by entry or date range. Use this whenever you touch app/src/arichds/acquisition/drivers/, app/src/arichds/vendor/gurux/, the probe or poller read paths, or any file importing gurux_dlms / gurux_net / gurux_common — and whenever you debug a DLMS read (scaler, GXDateTime, "inconsistent Class or object", timeouts, entries_in_use, selective access). For the meaning of an OBIS code or which model exposes which register, read docs/meter-notes/ instead; this skill is the *library API*, those are the *field-scanned register maps*.
---

# Gurux DLMS (Python) — library usage in ARICHDS v2

`gurux_dlms` is a port of Gurux's C# DLMS/COSEM stack. The API is camelCase, stateful,
and example-driven: [upstream](https://github.com/Gurux/Gurux.DLMS.Python) ships almost no
prose documentation and its README points you at
[gurux.fi/Gurux.DLMS.Client](https://www.gurux.fi/Gurux.DLMS.Client) for the protocol
lifecycle and [gurux.fi/Gurux.DLMS.Objects](https://www.gurux.fi/Gurux.DLMS.Objects) for
the COSEM classes. You learn the library from its sample files, which is why ARICHDS
vendors them.

**This skill = how to use the library.** For which OBIS code means what, and which model
actually exposes it, read `docs/meter-notes/` — those are scans off real meters, not
vendor datasheets.

Pinned in `app/pyproject.toml`: `gurux-dlms>=1.0.196`, `gurux-common>=1.0.13`,
`gurux-net>=1.0.23`, `gurux-serial>=1.0.21`. Installed and verified against
**gurux_dlms 1.0.201** (every import path in [api-reference.md](api-reference.md) was
executed against it, 2026-08-05).

## The three layers — work at the right one

| Layer | Files | Touch it when… |
|---|---|---|
| **driver layer** (preferred) | `app/src/arichds/acquisition/drivers/_dlms_tcp.py`, `prometer100.py`, `base.py` | Adding or changing meter behaviour. Override hooks (`_protocol_args`, `get_obis_map`, `read_*`, class attributes like `METER_SERIAL_OBIS`); do not reimplement the lifecycle. **No `if/elif` on meter model or brand in generic code** — that is a `CLAUDE.md` invariant; model differences live behind `MeterDriver` capability methods. |
| **ARICHDS wrappers around Gurux bugs** | `_gurux_net_patch.py`, `_gurux_trace.py` | Only when the upstream bug they fix changes. Read their docstrings before touching either — both exist because of production incidents, not taste. |
| **vendored Gurux** | `app/src/arichds/vendor/gurux/` — `GXSettings.py`, `GXDLMSReader.py`, `GXDLMSSecureClient2.py`, `GXCmdParameter.py` | Rarely. These are upstream samples copied **verbatim** (camelCase, lint-exempt in `pyproject.toml`). `CLAUDE.md` forbids renaming, reformatting or "improving" their APIs. Read them to understand a call. |

### The two wrappers, and why they exist

- **`_gurux_net_patch.py`** — gurux's `GXNet` listener thread busy-spins on a dead socket:
  a dropped link raises `ConnectionAbortedError` inside a generic `except` that loops with
  no break and no sleep, so one abort emits millions of stderr lines. In v1 that produced
  an **836 MB service log in two days**, and NSSM captures stderr directly — bypassing the
  app's rotating, credential-redacting logger entirely.
- **`_gurux_trace.py`** — `GXDLMSReader.__init__` opens `logFile.txt` and `writeTrace`
  writes to it **unconditionally**; the trace-level check gates only the `print`. So
  passing `-t Error` does *not* stop an unredacted frame trace — containing the password —
  from being written to disk next to the exe.

Both are load-bearing. If a read path stops going through them, those bugs come back.

## Core lifecycle (the one pattern everything follows)

ARICHDS never constructs `GXDLMSClient` by hand — it builds an argv-style list and lets
`GXSettings` parse it into a configured client + media. See
`_dlms_tcp.py::TcpDlmsDriver.connect()`.

```python
settings = GXSettings()
ret = settings.getParameters(args)          # argv-style list; returns 0 on success
if ret != 0:
    raise MeterConnectionError(...)
client = settings.client                    # GXDLMSSecureClient2
media  = settings.media                     # GXNet (TCP)
media.receiveTimeout = timeout_ms           # socket read timeout

reader = GXDLMSReader(client, media, settings.trace, settings.invocationCounter)
reader.waitTime = timeout_ms                # per-packet DLMS wait
silence_frame_trace(reader)                 # ARICHDS: close the unredacted logFile.txt

media.open()                                # TCP connect
reader.initializeConnection()               # SNRM/UA → AARQ/AARE → HLS auth
# ... reads ...
reader.close()                              # ALWAYS in finally
```

The protocol sequence matches what Gurux documents: SNRM/UA (HDLC), then AARQ/AARE to
establish the association and authentication mode, then — if the meter demands it — HLS
authentication, and a disconnect request at the end.

Rules baked into the driver base. Keep them; each has a reason in `CLAUDE.md` or an ADR:

- **Connect → read → disconnect per cycle.** No persistent sockets between polls.
- **`disconnect()` never raises.** It swallows everything and nulls `_reader/_client/_media`
  so a failed close cannot break a `finally`. `MeterDriver.disconnect` is contractually
  forbidden from raising (`base.py`) — code elsewhere relies on that.
- **Explicit timeout on every blocking I/O** — `media.receiveTimeout` *and* `reader.waitTime`.
- **Trace level `Error`, and the frame trace file closed** — see `_gurux_trace.py`.
- **Passwords and keys never in `repr`/`str` or logs.** `CLAUDE.md` invariant: the credential
  redaction filter is on every log handler, and `TcpDlmsDriver.__repr__` excludes the password.

### Reads happen under a lock — know this before you write one

Every read of a meter runs while holding that meter's **Transport Endpoint** lock
(`app/src/arichds/acquisition/locks.py`). The lock keys on `host:port` (or a COM port),
not on the device, so meters sharing a line queue behind one lock. And it is
**priority-aware** (ADR 0006): a Manual Read — the probe behind Create/Update, Test
connection, Read now — takes the endpoint ahead of a background poll tick, and a tick that
cannot get it is **skipped, not queued**.

Consequences for driver code: never open a second connection to an endpoint you already
hold, never hold the lock across anything slower than one read cycle, and do not add your
own retry loop around a read — `connect()` already has a bounded association retry, and a
longer one just wedges the endpoint for everyone else.

## Reading a single object

Instantiate the matching COSEM class, register it on the client, then `reader.read(obj, attr)`:

```python
obj = GXDLMSRegister("1.0.1.8.0.255")
client.objects.append(obj)        # the client must know the object before the read
value = reader.read(obj, 2)       # attr 2 = value
```

`reader.read` returns the parsed Python value (int / float / str / `GXDateTime` / bytes).
The trap is that **Register and ExtendedRegister return a *raw* integer at attr 2** — you
must also read **attr 3 (scaler_unit)** and apply `value * 10**scaler`. Getting this wrong
is exactly the v1 defect that **ADR 0002** exists to prevent from being reproduced; the
scaler behaviour is pinned by `app/tests/test_dlms_scaler.py`. See
[patterns.md](patterns.md) → "Register + scaler".

## Reading a ProfileGeneric (load profile, billing)

```python
pg = GXDLMSProfileGeneric("1.0.99.1.0.255")
client.objects.append(pg)
reader.read(pg, 3)                       # attr 3 = captureObjects → the column layout
n = int(reader.read(pg, 7))              # attr 7 = entries_in_use — read live, never assume
rows = reader.readRowsByEntry(pg, 1, n)  # by entry index
# or, by timestamp window:
rows = reader.readRowsByRange(pg, t_from, t_to)   # selective access by datetime
```

Gurux documents both access paths and warns that **not every meter supports both**. Read
`captureObjects` (attr 3) for the column layout rather than calling
`getAssociationView()`, which is far too slow on these meters.

> **ARICHDS has no ProfileGeneric read path yet.** Load profile arrives at **M5**, billing
> at **M6**. The patterns file documents how v1 did it — proven against the same meters —
> so you have a worked reference when you build it, not because the code exists here.
> `docs/meter-notes/load-profile-capture-objects.md` has the real capture lists and periods
> for three CEWE models, read off the meters on 2026-08-05.

## What exists in v2 today

- **One driver: `prometer100`** (`TcpDlmsDriver` subclass). The other eight catalogued
  models land at **M4** — adding one means adding a registry row in `factory.py` and a
  driver class, never an `if` at a call site.
- **`read_register(obis, attr=2)`** with correct scaler handling.
- **`read_meter_serial()`** — one register, driven by the `METER_SERIAL_OBIS` class
  attribute on `TcpDlmsDriver` so a model with a different serial OBIS overrides the
  attribute, not the method.
- **`read_instantaneous()`** — the eight-register live set. ADR 0007 stops persisting its
  output; check that ADR before building anything on it.
- **`probe.py`** — connect, read the serial, disconnect. It classifies failures into four
  operator-facing reasons, and `GXDLMSException` maps to `AUTH_FAILED`: a rejected
  association is what that exception means in practice.

## Before you write reader or driver code, read the reference files

- **[api-reference.md](api-reference.md)** — the library surface: verified import map,
  `GXDLMSReader` methods, COSEM object classes, the enums, and the `GXSettings` flag table.
  Read this to find *which* class, method or enum to use.
- **[patterns.md](patterns.md)** — copy-ready patterns and the gotchas that cost real
  debugging time: scaler/unit scaling, `GXDateTime.value`, meter-local time in
  `readRowsByRange`, the "inconsistent Class or object" ambiguous-class retry, `Decimal`
  vs float, and entry-order semantics. Read this before writing a read path.

Then read `CONTEXT.md` for the project's vocabulary and `docs/meter-notes/` for the OBIS
maps before changing the driver layer.
