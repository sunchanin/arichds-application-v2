# DLMS scaler is read correctly — v1's phantom ×10 compensating pair is not carried over

Status: accepted (2026-08-04, M1 implementation)

Reverses: v1 (`cewe`) ADR 0010 — "DLMS scaler misread as an exponent".

## What v1 did

`cewe-worker/src/drivers/_tcp_driver_base.py` read a register's **value first**
(attr 2), then its **scaler_unit** (attr 3), then multiplied:

```python
raw = self._reader.read(obj, 2)     # scaler still 1 -> unscaled
self._reader.read(obj, 3)           # now obj.scaler = 10**exponent
return Decimal(str(raw)) * Decimal(10) ** self._scaler_cache[obis_code]
```

Two mistakes stack there. Gurux Python populates `obj.scaler` with the
**multiplier** (`math.pow(10, exponent)`), not the exponent — and
`GXDLMSRegister.setValue` already applies it when attr 2 is parsed. So v1 both
denied itself the automatic scaling (by reading the value first) and then
treated the multiplier as an exponent: at meter exponent 0 the multiplier is
`1.0`, `int(1.0) == 1`, and the value silently gained a **phantom ×10**.

v1 knew, and compensated rather than fixed: `BILLING_VALUE_DIVISOR` divided by
10 000 so the pair cancelled to a net ÷1000 (Wh→kWh), while the energy-summary
path (÷1000) *depended* on the ×10 to come out right. v1's ADR 0010 documents
this as a deliberate frozen pair and warns against fixing either half alone.

## Decision

v2 reads **scaler_unit (attr 3) first, then the value (attr 2)**, and does no
manual scaling arithmetic at all — Gurux applies the meter's own multiplier:

```python
self._reader.read(obj, 3)      # obj.scaler = 10**exponent
return self._reader.read(obj, 2)  # Gurux multiplies inside setValue
```

The Wh→kWh conversion then happens exactly once, in the driver, at write time
(`WH_TO_KWH_DIVISOR`) — the normalization contract of REMAKE-PLAN §6.1. No
compensating pair anywhere.

SPEC §3.4 called for this explicitly: *"Scaler: เขียนให้ถูกต้องตั้งแต่ต้น …
ไม่ยกพฤติกรรม phantom ×10 ของ ADR 0010 มา แต่ผลลัพธ์สุดท้ายต้องตรง v1"*.

## Why this is safe against Output Parity

Every register on the deployed CEWE Prometer 100 reports **exponent 0** —
verified live on 2026-08-04 against the field meter at `203.170.151.152:4059`
with `app/scripts/probe_meter.py --show-scaler`:

```
volt_l1   1.0.32.7.0.255  exp=0  multiplier=1  scaled=239.7747
import    1.0.1.8.0.255   exp=0  multiplier=1  scaled=149643850.1760
```

At exponent 0 the correct path and v1's cancelled pair produce the **same
number** (`raw / 1000` kWh → 149 643.85 kWh, confirmed end to end). So the
reversal costs no parity on the current fleet, while being right for any meter
that reports a non-zero exponent — where v1's arithmetic would be wrong by a
decade.

## Consequence

The read order is load-bearing and is **locked by test**, per SPEC §3.4:
`app/tests/test_dlms_scaler.py` fails if the two `read()` calls are ever
swapped (verified by mutation: reversing them fails 4 tests, including a
raw-240 000-at-10⁻³ case that would otherwise silently shift by 1000×).

Anyone porting further v1 driver code must not bring `BILLING_VALUE_DIVISOR`'s
÷10 000 with it — in v2 that would divide energy by ten times too much. The
correct divisor is ÷1000, applied once, in the driver.
