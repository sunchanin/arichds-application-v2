# gurux_dlms API reference (the subset cewe uses)

Quick map of the library surface. All names are camelCase (C# port). Verified against
the version pinned in `cewe-worker/requirements.txt` (`gurux-dlms>=1.0.196`,
`gurux-common`, `gurux-net`, `gurux-serial`).

## Table of contents
- [Import map](#import-map)
- [GXDLMSReader methods](#gxdlmsreader-methods)
- [COSEM object classes](#cosem-object-classes)
- [Enums](#enums)
- [GXSettings flags](#gxsettings-flags)
- [Client / media objects](#client--media-objects)

## Import map

These are the exact import paths cewe uses (copy them — the package nests modules oddly):

```python
from gurux_dlms import GXDLMSClient, GXDLMSException
from gurux_dlms.GXByteBuffer import GXByteBuffer
from gurux_dlms.GXDateTime import GXDateTime
from gurux_dlms.enums import Authentication, InterfaceType, Security, Standard
from gurux_dlms.enums.DataType import DataType
from gurux_dlms.enums import ObjectType            # also: from gurux_dlms.enums.ObjectType import ObjectType
from gurux_dlms.objects.enums import SecuritySuite
from gurux_dlms.objects import (
    GXDLMSObject,
    GXDLMSData,                 # class 1  — generic value
    GXDLMSRegister,             # class 3  — value + scaler_unit
    GXDLMSExtendedRegister,     # class 4  — register + capture_time
    GXDLMSClock,                # class 8  — clock (health-check)
    GXDLMSProfileGeneric,       # class 7  — buffered series (LP/billing)
    GXDLMSCaptureObject,        # capture-object descriptor for ProfileGeneric
)

# Networking / common (separate packages)
from gurux_net import GXNet
from gurux_net.enums import NetworkType
from gurux_common.enums import TraceLevel
from gurux_serial.GXSerial import GXSerial          # only for serial meters
```

## GXDLMSReader methods

The vendored `GXDLMSReader` (worker root) wraps the read/write services. The ones cewe
calls:

| Method | Purpose |
| ------ | ------- |
| `initializeConnection()` | SNRM/UA (HDLC) → AARQ/AARE association → HLS authentication. Call once after `media.open()`. |
| `read(item, attributeIndex)` | GET one attribute of one COSEM object. Returns the parsed value. `item` must already be in `client.objects`. |
| `readList(list_)` | GET many attributes in one round-trip (`[(obj, attr), ...]`). Use when reading many registers to cut latency. |
| `write(item, attributeIndex)` | SET one attribute (writes `item`'s current attr value). |
| `readRowsByEntry(pg, index, count)` | Read `count` rows of a ProfileGeneric starting at 1-based entry `index`. Entry order is meter-defined (on Premier 550 billing, entry 1 = newest — ADR 0004). |
| `readRowsByRange(pg, start, end)` | Read ProfileGeneric rows by selective access on the sort range. `start`/`end` are datetimes **in meter-local time** (see patterns.md). |
| `readByAccess(list_)` | ACTION-based bulk read. |
| `close()` | RELEASE + DISC, closes media. Idempotent-ish but wrap in try/except — must not raise in cleanup. |
| `readScalerAndUnits()`, `getProfileGenericColumns()`, `getAssociationView()` | Discovery helpers. **Avoid `getAssociationView()`** on these meters — far too slow; read `captureObjects` (attr 3) directly instead. |

Key attributes set by cewe: `reader.waitTime = timeout_ms` (per-packet DLMS wait).

## COSEM object classes

Construct with the OBIS code string; `read(obj, attr)` fills the matching Python attribute.

| Class | COSEM id | Key attributes (index) | Notes |
| ----- | -------- | ---------------------- | ----- |
| `GXDLMSData` | 1 | `value` (2) | Generic fallback for anything not a register/profile. |
| `GXDLMSRegister` | 3 | `value` (2), `scaler`/`unit` (3) | attr 2 is **raw**; scale by `value * 10**scaler`. |
| `GXDLMSExtendedRegister` | 4 | `value` (2), `scaler`/`unit` (3), `captureTime` (5) | Demand registers (D=6 max, D=2 cumulative) carry capture_time. |
| `GXDLMSClock` | 8 | `time` (2) | Health-check reads attr 2 of `0.0.1.0.0.255`. |
| `GXDLMSProfileGeneric` | 7 | `buffer` (2), `captureObjects` (3), `capturePeriod` (4), `entriesInUse` (7), `profileEntries` (8) | Read attr 3 first for the column layout. |
| `GXDLMSCaptureObject` | — | `attributeIndex`, `dataIndex` | Each `captureObjects` entry is `(GXDLMSObject, GXDLMSCaptureObject)`. |

`_cosem_class()` in `_tcp_driver_base.py` shows cewe's class-selection rule by OBIS D-field
(D=8 → Register, D=6/2 → ExtendedRegister, clock OBIS → Clock, else Data).

## Enums

```python
Authentication.{NONE, LOW, HIGH, HIGH_MD5, HIGH_SHA1, HIGH_GMAC, HIGH_SHA256, HIGH_ECDSA}
Security.{NONE, AUTHENTICATION, ENCRYPTION, AUTHENTICATION_ENCRYPTION}
SecuritySuite.{SUITE_0, SUITE_1, SUITE_2}          # from gurux_dlms.objects.enums
InterfaceType.{HDLC, WRAPPER, HDLC_WITH_MODE_E, PLC, PLC_HDLC}
NetworkType.TCP                                     # from gurux_net.enums
Standard.{DLMS, INDIA, ITALY, SAUDI_ARABIA, IDIS}  # India/Italy/SA set useUtc2NormalTime
TraceLevel.{OFF, ERROR, WARNING, INFO, VERBOSE}    # from gurux_common.enums
DataType.{..., DATETIME, ...}                       # for GXDLMSClient.changeType()
ObjectType(<class_id>)                              # int → COSEM object type
```

## GXSettings flags

`GXSettings.getParameters(args)` parses an argv-style list (index 0 = dummy script name)
and configures `settings.client` + `settings.media`. Returns `0` on success, `1` on
help/parse fallthrough. cewe drivers build this list in `_build_args()`.

| Flag | Sets | Example |
| ---- | ---- | ------- |
| `-h` | host / IP (creates `GXNet` TCP) | `-h 192.168.1.102` |
| `-p` | TCP port | `-p 4059` |
| `-i` | interface type | `-i HDLC` / `-i WRAPPER` |
| `-c` | client address | `-c 32` |
| `-s` | server (physical) address | `-s 1` |
| `-l` | logical server address (combined with `-s`) | `-l 0` |
| `-n` | server address from serial number | `-n 12345678` |
| `-a` | authentication level | `-a Low` / `-a HighGMac` |
| `-P` | password (ASCII, or `0x..` hex) | `-P AAAAAAAA` |
| `-C` | security level | `-C AuthenticationEncryption` |
| `-V` | security suite | `-V Suite0` |
| `-T` / `-M` | client / meter system title (hex) | `-T 4775727578313233` |
| `-A` / `-B` / `-D` | authentication / block-cipher / dedicated key (hex) | `-A D0D1...` |
| `-v` | invocation-counter OBIS (pre-read) | `-v 0.0.43.1.0.255` |
| `-r` | referencing: `ln` (logical) or `sn` (short) | `-r ln` |
| `-t` | trace level | `-t Error` |
| `-S` | serial port (instead of `-h/-p`) | `-S COM1:9600:8None1` |

You can also set any of these directly on `settings.client` (e.g. `client.authentication`,
`client.ciphering.security`, `client.ciphering.blockCipherKey = GXByteBuffer.hexToBytes(...)`)
— that's all `getParameters` does under the hood.

## Client / media objects

- `GXDLMSSecureClient2(useLogicalNameReferencing=True)` — cewe's subclass of
  `GXDLMSSecureClient` (adds crypto/PDU notifier hooks; see `GXDLMSSecureClient2.py`).
  Relevant fields: `.objects` (collection you append read targets to),
  `.clientAddress`, `.serverAddress`, `.authentication`, `.interfaceType`,
  `.useLogicalNameReferencing`, `.ciphering.{security, securitySuite, systemTitle,
  authenticationKey, blockCipherKey, dedicatedKey}`, `.password`.
- `GXNet(NetworkType.TCP, host, port)` — TCP media. `.open()` / `.close()`,
  `.receiveTimeout`, `.hostName`, `.port`.
- `GXByteBuffer.hexToBytes("D0D1...")` — convert hex key/title strings to bytes.
