# gurux_dlms API reference (the subset ARICHDS uses)

Quick map of the library surface. All names are camelCase (it is a C# port).

Pinned in `app/pyproject.toml`: `gurux-dlms>=1.0.196`, `gurux-common>=1.0.13`,
`gurux-net>=1.0.23`, `gurux-serial>=1.0.21`. **Every import below was executed against the
installed `gurux_dlms 1.0.201` on 2026-08-05** — they are verified, not remembered.

Upstream has no API reference. The two pages worth opening are
[gurux.fi/Gurux.DLMS.Client](https://www.gurux.fi/Gurux.DLMS.Client) (protocol lifecycle)
and [gurux.fi/Gurux.DLMS.Objects](https://www.gurux.fi/Gurux.DLMS.Objects) (COSEM classes);
everything else you learn from the samples vendored at `app/src/arichds/vendor/gurux/`.

## Table of contents
- [Import map](#import-map)
- [GXDLMSReader methods](#gxdlmsreader-methods)
- [COSEM object classes](#cosem-object-classes)
- [Enums](#enums)
- [GXSettings flags](#gxsettings-flags)
- [Client / media objects](#client--media-objects)

## Import map

The package nests its modules oddly — copy these paths rather than guessing:

```python
from gurux_dlms import GXDLMSClient, GXDLMSException
from gurux_dlms.GXByteBuffer import GXByteBuffer
from gurux_dlms.GXDateTime import GXDateTime
from gurux_dlms.enums import Authentication, DateTimeSkips, InterfaceType, Security, Standard
from gurux_dlms.enums.DataType import DataType
from gurux_dlms.enums import ObjectType            # also: from gurux_dlms.enums.ObjectType import ObjectType
from gurux_dlms.objects.enums import SecuritySuite
from gurux_dlms.objects import (
    GXDLMSObject,
    GXDLMSData,                 # class 1  — generic value
    GXDLMSRegister,             # class 3  — value + scaler_unit
    GXDLMSExtendedRegister,     # class 4  — register + capture_time
    GXDLMSProfileGeneric,       # class 7  — buffered series (LP / billing)
    GXDLMSClock,                # class 8  — clock
    GXDLMSSpecialDaysTable,     # class 11 — Special Days Table (M7-1, issue #28)
    GXDLMSCaptureObject,        # capture-object descriptor for ProfileGeneric
)
from gurux_dlms.GXDate import GXDate                # a date-only GXDateTime subclass; entry.date's type

# Networking / common (separate packages)
from gurux_net import GXNet
from gurux_net.enums import NetworkType
from gurux_common.enums import TraceLevel
from gurux_serial.GXSerial import GXSerial          # serial meters — SMW110 at M4
```

ARICHDS re-exports the vendored samples through `app/src/arichds/vendor/gurux/__init__.py`:

```python
from arichds.vendor.gurux import GXDLMSReader, GXSettings
```

## GXDLMSReader methods

`GXDLMSReader` is an upstream **sample**, vendored at
`app/src/arichds/vendor/gurux/GXDLMSReader.py`. It wraps the read/write services. The ones
ARICHDS calls, or will call at M4–M6:

| Method | Purpose |
|---|---|
| `initializeConnection()` | SNRM/UA (HDLC) → AARQ/AARE association → HLS authentication. Call once after `media.open()`. |
| `read(item, attributeIndex)` | GET one attribute of one COSEM object. Returns the parsed value. `item` must already be in `client.objects`. |
| `readList(list_)` | GET many attributes in one round-trip (`[(obj, attr), …]`). Cuts latency when reading many registers. |
| `write(item, attributeIndex)` | SET one attribute. **ARICHDS never writes to a meter** — the test meters are read-only and `CLAUDE.md` says so. |
| `readRowsByEntry(pg, index, count)` | Read `count` rows of a ProfileGeneric from 1-based entry `index`. Entry order is meter-defined — v1 found entry 1 = **newest** on Premier 550 billing. |
| `readRowsByRange(pg, start, end)` | Read ProfileGeneric rows by selective access on the sort range. `start`/`end` are datetimes **in meter-local time** (see patterns.md). |
| `readByAccess(list_)` | ACTION-based bulk read. |
| `close()` | RELEASE + DISC, closes media. Wrap it — it must never raise in cleanup. |
| `disconnect()`, `release()` | Lower-level pieces of `close()`. |
| `readScalerAndUnits()`, `getProfileGenericColumns()`, `getAssociationView()` | Discovery helpers. **Avoid `getAssociationView()`** in production paths — far too slow on these meters; read `captureObjects` (attr 3) instead. It is fine in a diagnostic script (`app/scripts/probe_capture_objects.py` uses it deliberately). |
| `readAll()`, `getReadOut()`, `getProfileGenerics()` | Whole-meter dumps from the upstream sample. Diagnostics only. |
| `updateFrameCounter()`, `initializeOpticalHead()` | Invocation-counter pre-read and optical-head mode E. Unused today. |

Attributes ARICHDS sets: `reader.waitTime = timeout_ms` (per-packet DLMS wait).

## COSEM object classes

Construct with the OBIS code string; `read(obj, attr)` fills the matching Python attribute.

| Class | COSEM id | Key attributes (index) | Notes |
|---|---|---|---|
| `GXDLMSData` | 1 | `value` (2) | Generic fallback for anything not a register or profile. |
| `GXDLMSRegister` | 3 | `value` (2), `scaler`/`unit` (3) | attr 2 is **raw** if read before attr 3; `scaler` is already the multiplier (`10**exponent`), not the exponent — read attr 3 first and Gurux scales attr 2 for you (ADR 0002). |
| `GXDLMSExtendedRegister` | 4 | `value` (2), `scaler`/`unit` (3), `captureTime` (5) | Demand registers (D=6 max, D=2 cumulative) carry a capture time. |
| `GXDLMSClock` | 8 | `time` (2) | The clock object `0.0.1.0.0.255` — also the timestamp column of every load profile. |
| `GXDLMSProfileGeneric` | 7 | `buffer` (2), `captureObjects` (3), `capturePeriod` (4), `entriesInUse` (7), `profileEntries` (8) | Read attr 3 first for the column layout. |
| `GXDLMSSpecialDaysTable` | 11 | `entries` (2) | Read attr 2; Gurux parses onto `obj.entries` (a list of `GXDLMSSpecialDay`), never onto `read()`'s return value. `insert()`/`delete()` exist but **must never be called** (write methods, CLAUDE.md). See patterns.md → "Special Days Table (class 11) and the wildcard year". |
| `GXDLMSCaptureObject` | — | `attributeIndex`, `dataIndex` | Each `captureObjects` entry is a `(GXDLMSObject, GXDLMSCaptureObject)` pair. |

v1 selected the class by OBIS D-field (D=8 → Register, D=6/2 → ExtendedRegister, clock
OBIS → Clock, else Data). **ARICHDS has no such helper yet** — `_dlms.read_register()`
uses `GXDLMSRegister` and `GXDLMSExtendedRegister` directly. Add one when M6's billing path
needs it, and put it behind a driver method, not an `if` chain.

## Enums

```python
Authentication.{NONE, LOW, HIGH, HIGH_MD5, HIGH_SHA1, HIGH_GMAC, HIGH_SHA256, HIGH_ECDSA}
Security.{NONE, AUTHENTICATION, ENCRYPTION, AUTHENTICATION_ENCRYPTION}
SecuritySuite.{SUITE_0, SUITE_1, SUITE_2}          # from gurux_dlms.objects.enums
InterfaceType.{HDLC, WRAPPER, HDLC_WITH_MODE_E, PLC, PLC_HDLC}
NetworkType.TCP                                     # from gurux_net.enums
Standard.{DLMS, INDIA, ITALY, SAUDI_ARABIA, IDIS}  # India/Italy/SA set useUtc2NormalTime
TraceLevel.{OFF, ERROR, WARNING, INFO, VERBOSE}    # from gurux_common.enums
DataType.{…, DATETIME, …}                           # for GXDLMSClient.changeType()
ObjectType(<class_id>)                              # int → COSEM object type
```

The catalog records that **SMART TCC uses HighGMAC + Security Suite 0** and carries no
simple password (`fixed_password=None`) — its keys belong to its driver at M4, not to the
device row.

## GXSettings flags

`GXSettings.getParameters(args)` parses an argv-style list (index 0 = dummy script name)
and configures `settings.client` + `settings.media`. Returns `0` on success, `1` on
help/parse fallthrough. ARICHDS drivers build this list in `_build_args()` /
`_protocol_args()`.

| Flag | Sets | Example |
|---|---|---|
| `-h` | host / IP (creates `GXNet` TCP) | `-h 203.170.151.152` |
| `-p` | TCP port | `-p 4059` |
| `-i` | interface type | `-i HDLC` / `-i WRAPPER` |
| `-c` | client address | `-c 32` |
| `-s` | server (physical) address | `-s 1` |
| `-l` | logical server address (combined with `-s`) | `-l 0` |
| `-n` | server address from serial number | `-n 12345678` |
| `-a` | authentication level | `-a Low` / `-a HighGMac` |
| `-P` | password (ASCII, or `0x…` hex) | `-P ABCD0001` |
| `-C` | security level | `-C AuthenticationEncryption` |
| `-V` | security suite | `-V Suite0` |
| `-T` / `-M` | client / meter system title (hex) | `-T 4775727578313233` |
| `-A` / `-B` / `-D` | authentication / block-cipher / dedicated key (hex) | `-A D0D1…` |
| `-v` | invocation-counter OBIS (pre-read) | `-v 0.0.43.1.0.255` |
| `-r` | referencing: `ln` (logical) or `sn` (short) | `-r ln` |
| `-t` | trace level | `-t Error` |
| `-S` | serial port (instead of `-h`/`-p`) | `-S COM3:19200:8None1` |

Anything here can also be set directly on `settings.client` (e.g. `client.authentication`,
`client.ciphering.security`, `client.ciphering.blockCipherKey = GXByteBuffer.hexToBytes(…)`)
— that is all `getParameters` does under the hood.

> Mitsubishi SMW110W4 (issue #9, TCP or serial) is documented in
> `docs/meter-notes/smw110w4-scan.md` as **HDLC, LN referencing, 19200 8N1 on serial,
> auth Low, client 6** (not v1's hardcoded 5 — neither live unit answers on it)
> **, physical server 1 and logical server 0** — the last part meaning `-l 0` must be
> passed, which is easy to miss. The password is `MITSU_SMW110_FIXED_PASSWORD` in
> `app/src/arichds/acquisition/catalog.py` — read it there rather than from a copy
> here, because the copy that used to sit on this line went stale when the customer
> retired the meter it belonged to.

## Client / media objects

- `GXDLMSSecureClient2(useLogicalNameReferencing=True)` — the vendored subclass of
  `GXDLMSSecureClient` (adds crypto/PDU notifier hooks; see `GXDLMSSecureClient2.py`).
  Relevant fields: `.objects` (the collection you append read targets to),
  `.clientAddress`, `.serverAddress`, `.authentication`, `.interfaceType`,
  `.useLogicalNameReferencing`, `.ciphering.{security, securitySuite, systemTitle,
  authenticationKey, blockCipherKey, dedicatedKey}`, `.password`.
- `GXNet(NetworkType.TCP, host, port)` — TCP media. `.open()` / `.close()`,
  `.receiveTimeout`, `.hostName`, `.port`. **Patched by `_gurux_net_patch.py`** — see the
  skill file for why.
- `GXSerial` — serial media, unused until SMW110 at M4.
- `GXByteBuffer.hexToBytes("D0D1…")` — convert hex key/title strings to bytes.
