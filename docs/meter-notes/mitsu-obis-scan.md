> **ยกมาจาก v1 โดยไม่แก้เนื้อหา** (`cewe/docs/requirements/mitsu-obis-scan.md`) เมื่อ 2026-08-05
> เป็นผลสแกนจากมิเตอร์จริง ไม่ใช่เอกสารของผู้ผลิต — v2 ใช้เป็นแหล่งอ้างอิง OBIS ตอนพอร์ต driver ที่ M4
> ทุกบรรทัดข้างล่างคือของเดิม รวมทั้งข้อจำกัดที่มันประกาศไว้เอง · ก่อนเชื่อค่าใด ให้ดูหัวข้อ "สถานะ/ข้อจำกัด" ของมันก่อน
> เมื่อจะแตะโค้ด Gurux ให้ใช้ skill `gurux-dlms` คู่กับเอกสารนี้ — เอกสารนี้บอก *อะไร* ส่วน skill บอก *อย่างไร*

# Mitsubishi SMW110 — OBIS จากมิเตอร์จริง (สแกนสำเร็จ 18 ก.ค. 2026)

ที่มา: `cewe-worker/scripts/test_mitsu_serial.exe --port COM3 --scan` บนเครื่อง mini PC หน้างาน
(รายงานดิบเต็ม 720 objects เป็น artifact ที่เครื่องหน้างาน — ไม่ได้ commit; เอกสารนี้คือสรุปที่กลั่นแล้ว ใช้เป็นแหล่งอ้างอิงหลัก)

## การเชื่อมต่อ (ยืนยันกับมิเตอร์จริง — ต่อติด อ่านค่าได้)

- Serial **19200 8N1** (⚠ ไม่ใช่ 9600 ตาม screenshot vendor) · HDLC + LN
- **auth Low, password `00000000000000000003` (ASCII)** · client 5 · **physical server 1 + logical server 0 (ต้องส่ง `-l 0` ด้วย)**
- อ่านได้จริง: Clock, meter number `1252008102`, Import kWh (`raw=106662 scaler×10 unit=30/Wh` → 1066.62 kWh)

## ProfileGeneric (จาก 720-object list)

| OBIS | บทบาท |
|------|-------|
| **`1.0.99.1.0.255`** | **Load Profile** (recording period 1) — LP หลักของ driver |
| **`1.0.98.1.0.255`** | **Billing** (Data of billing period Scheme 1) — ⚠ prefix `1.0` ไม่ใช่ `0.0` แบบ TCC |
| `1.0.99.98.0-5.255` | Event logs #1–#6 |
| `0.0.97.98.255.255` | Alarm register profile |
| `1.0.94.66.0.255` | Identifiers for Thailand |

> ~~ยังไม่ได้อ่าน captureObjects (attr 3) ของ 2 profile หลัก~~ **ปิดแล้ว 23 ก.ค. 2026** — probe 3 รอบกับมิเตอร์จริง (`test_mitsu_serial.exe --probe-profiles`) + association export `swm.xml`:
>
> - **LP `1.0.99.1.0.255`**: 19 คอลัมน์ · capturePeriod 900s · buffer เต็ม 8640/8640 (~90 วัน) · **รับเฉพาะ readRowsByEntry** (byRange → "Read-Write denied") — driver ใช้ `LP_SELECTIVE_ACCESS="entry"` (commit 8f40351) · chunk 96 แถวพิสูจน์แล้ว
> - **ไม่มี logger 2** (`1.0.99.2.0.255` → "undefined object") — reader ถือเป็น buffer ว่าง
> - **Billing `1.0.98.1.0.255`**: 242 คอลัมน์ · entriesInUse 10/13 · **entry 1 = รอบบิลใหม่สุด** (ยืนยันจาก billing-period counter 10..1 — ตรง ADR 0004) · full-column อ่านไม่ได้ทุกวิธี ("Data Block Unavailable") · **column selection เป็น prefix-only**: ต้องเริ่มคอลัมน์ 1 เสมอ (เริ่มกลางตาราง = ล้มแม้คอลัมน์เดียว) และเพดานสิทธิ์ = **43 คอลัมน์** (55/68 → "scope of access violated") — driver ใช้ **prefix ladder** (`BILLING_SELECT_COLUMNS`, commits 41db61e + 254fa63 + bb19a28); field คอลัมน์ 55..93 (cumulative + demand capture-time) = None ถาวรบนรุ่นนี้ · บิลจริงที่อ่านได้: 10 รอบ พ.ย. 2025–ก.ค. 2026 (ตัดทุกวันที่ 1)
> - **ไม่มีคอลัมน์ bill_date `0.0.0.1.2.255` และ reset-reason `0.0.0.1.12.255`** ใน 242 คอลัมน์ — bill_date ใช้คอลัมน์ 1 (Clock = เวลาตัดรอบ) แทน; reset_reason degrade เป็น None (positional fallback, Issue #74)
> - ตำแหน่งคอลัมน์ที่ billing reader ใช้ (1-based): clock=1 · energy 3..19 · demand 28..43 · cumulative 55..68 · capture-time 78..93

## OBIS รายค่า (ปิดช่องว่างที่ workbook เว้นว่าง)

**Energy (Register, D=8)** — quadrant มาตรฐาน IEC ยืนยันจาก description:
- Import active `1.0.1.8.{0-4}.255` · Export active `1.0.2.8.{0-4}.255`
- Import reactive `1.0.3.8.x` · Export reactive `1.0.4.8.x` (rate 0=total, 1-4=TOU)

**Demand:**
- Active power import (avg) `1.0.1.4.x` · export `1.0.2.4.x` · reactive `1.0.3.4.x`/`1.0.4.4.x` (DemandRegister)
- **Max demand `1.0.1.6.{0-4}.255` (ExtendedRegister — มี captureTime ที่ attr 5)** · Cumulative `1.0.1.2.x` (Register)

**Instantaneous:**
- Voltage L-N: L1 `1.0.32.7.0.255`, L2 `1.0.52.7.0.255`, L3 `1.0.72.7.0.255` (`.h` = harmonics)
- Current: L1 `1.0.31.7.0.255`, L2 `1.0.51.7.0.255`, L3 `1.0.71.7.0.255`
- PF `1.0.13.7.0.255` · **Frequency `1.0.14.7.0.255`** (เดิม workbook ไม่มี — ปิดแล้ว)

**Phase angle (ปิดช่องว่าง — description ชัด):**
- I(L1)-U(L1) = Ph-A `1.0.81.7.4.255` · I(L2)-U(L2) = Ph-B `1.0.81.7.15.255` · **I(L3)-U(L3) = Ph-C `1.0.81.7.26.255`**
- (⚠ แผนเดิมเดา Ph-C = `1.0.81.7.16` ผิด — ของจริง `.26`)

**Battery — เซอร์ไพรส์สำคัญ:**
- `0.0.96.6.3.255` = **"Battery voltage" (DATA class) ไม่ใช่ "remaining hours"** → Mitsu อ่าน remaining-hours ตรงๆ ไม่ได้ มีแค่แรงดันแบต · เกณฑ์ alarm ของลูกค้า "เหลือ < 1 ชม." ใช้กับ Mitsu ไม่ได้ตรงๆ ต้องถามลูกค้าว่าจะใช้ threshold แรงดันแทนไหม

**SpecialDays:** `0.0.11.0.0.255` (+ `.1` table #2) · ActivityCalendar `0.0.13.0.0.255`

## ช่องที่ยังไม่มี / ต้องเคาะ

- **Voltage L-L (L1-L2, L2-L3)** — มิเตอร์ให้แค่ L-N (`32/52/72.7`) ไม่มี register L-L ตรงๆ (สอดคล้อง workbook ที่เว้นว่างช่องนี้ของ Mitsu) → export เว้นว่างเหมือน frequency ของ TCC หรือคำนวณเอง (ต้องเคาะ)
- **captureObjects (ลำดับคอลัมน์จริง) ของ LP/billing** — ยังไม่ดึง (object list พอสร้าง OBIS map, แต่ลำดับคอลัมน์ต้องอ่าน attr 3 เพิ่ม)
- **Device name `0.0.41.0.0.255`** อ่านคืน None (SAP assignment) — ใช้ meter number `0.0.96.1.0.255` เป็น identity แทน
