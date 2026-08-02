# ARICHDS Application v2 — แผนงาน Remake (ฉบับร่าง)

> สถานะ: ร่างแรก 2026-08-02 — ยังไม่ผ่านการตัดสินใจข้อ [Open Decisions](#open-decisions)
> ต้นทาง: `C:\Users\HP\Documents\Work\cewe` (arichds-application v1)

---

## 1. Baseline — v1 มีอะไรอยู่จริง

ตัวเลขจากการสำรวจโค้ดจริง ใช้เป็นฐานวัดว่า "ลีนลง" แค่ไหน

| ส่วน | ของจริงใน v1 |
|---|---|
| `cewe-worker/` (Python, DLMS/COSEM) | 130 ไฟล์ `.py`, ~29,000 บรรทัด |
| `modbus-logger/` (Go, Modbus) | 31 ไฟล์ `.go`, ~4,400 บรรทัด — **คนละ service, คนละ DB, คนละวิธี activate** |
| `cewe-fe/` (React 19 + AntD 6 + Tailwind) | 49 ไฟล์ `.ts/.tsx`, ~10,000 บรรทัด, 14 หน้า |
| Database | **19 ตาราง** ใน MySQL `cewe` + **5 ตาราง** ใน SQLite `auth.db` + **3 ตาราง/brand** ใน MySQL `modbus_logger` (`meter_readings_<brand>_1m/_5m/_15m`) |
| Migration | 24 revision (core) + alembic แยก 2 ชุด (`alembic.ini` / `alembic_core.ini`) |
| Installer | 12 สคริปต์ `.ps1` + `.bat` คู่ทุกตัว + NSSM services + MySQL portable zip ที่ต้อง trim เอง + activation code แบบ offline |
| License | Ed25519 offline license file + machine fingerprint + limited mode + lease/renew/redeem (ทำไปครึ่งทาง) |
| Portal | `arichds-portal` แยกรีโป — มี `/activate` `/renew` `/redeem` แล้ว (ถึง milestone M1+, PR #30–#39) |

### หลักฐานของ over-engineering (ข้อ 3 ของคุณ)

**Thread/scheduler ซ้อนกัน 4 ชั้น** — main thread (uvicorn) → `BackgroundWorker` thread → `ThreadPoolExecutor` 1 thread/มิเตอร์ → daemon scheduler แยกอีก **7 ตัว**:
`load_profile_scheduler`, `billing_auto_reader`, `billing_backfill_scheduler`, `battery_reader`, `retention_scheduler`, `modbus_billing_cut_scheduler`, `lp_csv_exporter` + `license-recheck` thread อีก 1
→ ทุกตัวใช้ `daemon_scheduler.py` เป็นฐานเหมือนกันหมด แต่แตกเป็นคนละ thread เพราะ "แยกโมดูล" ไม่ใช่เพราะต้องการ concurrency

**ตารางที่แทบไม่ถูกใช้** — นับ reference นอก `models.py`:

| ตาราง | refs นอก models.py | ข้อสังเกต |
|---|---|---|
| `energy_register_readings` | 1 | เขียนอย่างเดียว ไม่มีใครอ่าน |
| `alarms` | 2 | สร้างตารางทิ้งไว้ |
| `logger_exports` | 2 | ตกยุค |
| `logger_confirmations` | 2 | ตกยุค |
| `device_connection_log` | 2 | ทับซ้อนกับ `device_heartbeats` |
| `records_96` | 7 | ทับซ้อนกับ `logger_readings` |

**ตารางที่ทำงานเดียวกันแต่แยกกัน** — `device_status` (1 row/device) vs `device_heartbeats` (time-series ของ status เดิม) vs `device_connection_log`; `logger_readings` vs `records_96` vs `meter_readings_<brand>_1m`; `device_settings` vs `format_settings` vs `billing_settings` vs `lp_csv_export_state` (ทั้งหมดคือ "settings")

---

## 2. หลักการออกแบบ v2 (design principles)

ห้าข้อนี้ใช้เป็นไม้บรรทัดตัดสินทุก PR ต่อจากนี้

1. **หนึ่ง process หนึ่ง binary หนึ่ง installer หนึ่ง license** — ไม่มี "worker คนละภาษากับ logger" อีก
2. **หนึ่ง database หนึ่ง schema** — จบ ADR 0004 (cross-DB read-only) และ dual-DB auth/core
3. **Lean by default** — ตาราง / thread / abstraction ต้อง "พิสูจน์ตัวเอง" ก่อนถึงมีสิทธิ์อยู่ ถ้าเพิ่ม ต้องบอกได้ว่าใครอ่าน
4. **Portal-first activation** — online เป็นทางหลัก, offline activation code เหลือเป็นทางหนีไฟถาวร
5. **UI ทันสมัยแต่ professional** — เน้น density แบบเครื่องมือวิศวกรรม ไม่ใช่ landing page

---

## 3. สถาปัตยกรรมเป้าหมาย

```
arichds-app.exe  (Python 3.13, PyInstaller onedir, 1 process)
├── api/            FastAPI — REST + เสิร์ฟ SPA จาก origin เดียวกัน
├── acquisition/    ชั้นเดียวสำหรับทุกยี่ห้อ/ทุก transport
│   ├── drivers/    MeterDriver ABC → dlms/* (Gurux), modbus/* (pymodbus)
│   ├── transport/  tcp / serial / gprs — value object
│   └── poller/     1 ThreadPoolExecutor + 1 lock/device (เหมือนเดิม อันนี้ถูกแล้ว)
├── jobs/           **scheduler ตัวเดียว** รัน periodic job ทุกตัวจาก job registry
├── domain/         billing / load_profile / energy / devices
├── licensing/      verify + enforcement + portal client (activate/renew/redeem)
└── db/             MySQL เดียว, Alembic ชุดเดียว
web/                React + <ไลบรารีใหม่> → build เป็น static เสิร์ฟจาก api/
```

### 3.1 การรวม Modbus เข้ามา (แก้ pain point ข้อ 2)

DLMS ผูกกับ Gurux ซึ่งมีแต่ Python/.NET → **ฝั่ง DLMS ย้ายไป Go ไม่ได้** ดังนั้นทิศทางการรวมมีทางเดียวที่คุ้ม:

**พอร์ต `modbus-logger` (Go, 4.4k บรรทัด) → Python ด้วย `pymodbus`** แล้วยัดเข้าหลัง `MeterDriver` ตัวเดียวกัน

- ได้: 1 exe, 1 installer, 1 license, 1 DB, 1 หน้า config, ไม่มี cross-DB SELECT อีก
- เสีย: ต้องเขียน register map ของ SMW110 / Prometer100 ใหม่ (แต่ map มีอยู่แล้วใน `internal/meter/*/registers.go` แปลตรง ๆ ได้)
- ความเสี่ยงเรื่อง performance: sampling 1 นาที/มิเตอร์ — Python รับไหวสบาย ไม่ใช่ hot path

> ทางเลือกสำรอง (ถ้าไม่อยากพอร์ต): ให้ worker spawn `modbus-logger.exe` เป็น child process และแชร์ license เดียวกัน → installer เดียวจริง แต่ยังเหลือ 2 binary 2 codebase 2 ภาษา — แก้ pain point ได้แค่ครึ่งเดียว **ไม่แนะนำ**

### 3.2 Thread model (แก้ pain point ข้อ 3)

| v1 | v2 |
|---|---|
| main + worker thread + pool/device + **7 daemon scheduler** + license recheck | main (uvicorn) + **1 poller pool** (1 lock/device) + **1 scheduler thread** ที่รันทุก periodic job จาก registry |
| ~10+ thread คงที่ | 2 thread คงที่ + n มิเตอร์ |

Job registry = ลิสต์เดียว `[(name, interval, fn)]` — เพิ่มงานใหม่ = เพิ่ม 1 บรรทัด ไม่ใช่ 1 ไฟล์ + 1 thread

### 3.3 Database (แก้ pain point ข้อ 1 + 3)

**24 ตาราง (2 DB) → เป้าหมาย ~12 ตาราง (1 DB `arichds`)**

| v2 | รวมมาจาก v1 |
|---|---|
| `devices` | `devices` + `device_settings` + `device_status` + `device_capture_objects` (ย้ายเป็น JSON column) |
| `device_events` | `device_heartbeats` + `device_connection_log` + `alarms` |
| `interval_readings` | `logger_readings` + `records_96` + `meter_readings_<brand>_1m` (มี `source`, `interval` เป็น column) |
| `interval_read_jobs` | `load_profile_reads` |
| `billing_readings` | `billing_readings` |
| `billing_captures` | `logger_exports` + `logger_confirmations` (ถ้ายังต้องใช้ — ไม่งั้นตัดทิ้ง) |
| `energy_snapshots` | `energy_register_readings` + `battery_readings` |
| `holidays` | `holidays` |
| `settings` (key/value) | `format_settings` + `billing_settings` + `lp_csv_export_state` |
| `users`, `user_tokens` | `users` + `user_tokens` (`roles`/`permissions`/`role_permissions` → ยุบเป็น enum column) |

- Alembic **ชุดเดียว** (v1 มี 2 ชุด แถมชุด auth ยัง 0 revision)
- ตัดทิ้งเลย: `energy_register_readings` (ไม่มีใครอ่าน), `alarms`, `device_connection_log`, `records_96`, aggregate `_5m/_15m` (คำนวณตอน query ได้)
- ชื่อ DB/ตาราง/env เปลี่ยนเป็น `arichds` / `ARICHDS_*` ได้หมด เพราะ v2 = install ใหม่ ไม่ต้องแบก ADR 0012 tier 3

### 3.4 Naming — ข้อจำกัดที่ยังต้องแบก

ADR 0012 (v1) แช่แข็งชื่อไว้ 2 ชั้น สำหรับ v2:

- **ปลดล็อกได้ทั้งหมด**: repo, exe, service name, env prefix, DB/table, UI, docs → เป็น `arichds` / `ARICHDS_*`
- **ห้ามแตะ**: ชื่อเชิง cryptographic ที่ผูกสัญญากับ portal — fingerprint salt `"CEWE|"`, signing version string ของ logger, keypair
  → ถ้าจะเปลี่ยน ต้องแก้ `arichds-portal` + `license-vectors` พร้อมกัน และ portal ต้องรองรับทั้งสองแบบตลอดอายุ license เก่า **ข้อเสนอ: อย่าเปลี่ยน** ซ่อนไว้ในโค้ดพร้อม comment ว่าทำไม

---

## 4. Roadmap

แต่ละ milestone มี exit criteria ชัด — ยังไม่ผ่านไม่ขึ้น milestone ถัดไป

### M0 — Spec & decisions
- ตอบ [Open Decisions](#open-decisions) ให้ครบ
- เขียน `SPEC.md` (ใช้ `/create-spec`) + ยกเฉพาะ ADR ที่ยัง**เป็นจริง**จาก v1 มา (0011 license lease, 0018 open period, 0019 modbus cut, 0020 manual gate) — ที่เหลือปล่อยตายไปกับ v1
- **Exit**: SPEC.md ผ่าน + ตาราง v2 ล็อกที่ ~12 ตาราง

### M1 — Skeleton
- โครง repo, FastAPI factory, config เดียว, MySQL + Alembic ชุดเดียว, auth (users+tokens), `ApiResponse` envelope, error hierarchy
- CI: ruff + pytest + build
- **Exit**: `arichds-app --migrate` แล้ว login ได้ผ่าน API

### M2 — Acquisition (หัวใจ)
- `MeterDriver` ABC + transport value object
- DLMS drivers: Prometer100, Saral305, Premier550, SMART TCC (ยก logic จาก v1 มาตรง ๆ — ส่วนนี้ผ่านการพิสูจน์หน้างานแล้ว **อย่าคิดใหม่**)
- Modbus drivers: SMW110, Prometer100 (พอร์ตจาก Go)
- Poller + 1 lock/device + manual-priority gate (ADR 0020)
- **Exit**: อ่านค่าจากมิเตอร์จริงครบ 3 ยี่ห้อผ่าน service เดียวกัน

### M3 — Domain modules
- Load profile (2 logger, merge `read_at`, CSV export)
- Billing (open period upsert slot, backfill, modbus billing cut, capture PDF/xlsx)
- Energy summary + TOU/holidays, battery status
- Job registry + retention
- **Exit**: ข้อมูล v2 ตรงกับ v1 บนมิเตอร์ตัวเดียวกัน (เทียบ side-by-side)

### M4 — Frontend
- ตั้งไลบรารีใหม่ + design system (typography scale, spacing, color, สถานะ device) ก่อนลงหน้า
- ไล่หน้าเดิม 14 หน้า → ตัด/ยุบตามโมดูลที่ตัดจริง
- **Exit**: ทุก flow ที่ v1 ทำได้ v2 ทำได้ + ผ่าน review ด้าน UX

### M5 — Packaging & activation (แก้ pain point ข้อ 2 เต็มตัว)
- installer เดียว (ดู [Open Decisions](#open-decisions) D3), online activation เป็น default, offline เป็น fallback
- license enforcement + lease renew + meter key redeem
- **Exit**: ติดตั้งบนเครื่องเปล่าจบใน **1 ขั้นตอน + 1 activation key** จับเวลาได้ < 10 นาที

### M6 — Migration & pilot
- สคริปต์ย้ายข้อมูลจาก `cewe` + `modbus_logger` → `arichds`
- ลงหน้างานลูกค้า 1 ราย ขนานกับ v1
- **Exit**: ลูกค้านำร่องรันบน v2 อย่างเดียวได้ 2 สัปดาห์

---

## 5. สิ่งที่ "ห้ามเขียนใหม่" — ยกจาก v1 มาตรง ๆ

Remake ไม่ได้แปลว่าคิดใหม่ทุกอย่าง ของพวกนี้แลกมาด้วยการดีบักหน้างาน อย่าไปแตะ:

- OBIS map / register map ของทุกไดรเวอร์ (`src/drivers/*`, `internal/meter/*/registers.go`) + เอกสารสแกน OBIS ใน `docs/requirements/`
- Gurux wrapper (`GX*.py`) — vendored ห้าม rename API
- ADR 0018 open-period upsert slot, ADR 0019 modbus billing cut, ADR 0020 manual-priority gate
- ADR 0010 scaler phantom ×10 — **ต้องตัดสินใจแยก**: v2 คือโอกาสแก้ให้ถูก แต่ต้องมีการวัดกับมิเตอร์จริงก่อน ไม่งั้นยกของเดิมมาพร้อม characterization test
- Ed25519 verify primitive + golden vectors (`license-vectors/`)
- Credential redaction filter

---

## <a id="open-decisions"></a>6. Open Decisions — ต้องตอบก่อน M1

| # | คำถาม | ข้อเสนอของผม |
|---|---|---|
| **D1** | รวม Modbus ยังไง — พอร์ต Go → Python, หรือ spawn เป็น child process | **พอร์ตเป็น Python** (§3.1) |
| **D2** | ยังใช้ MySQL ไหม หรือย้าย SQLite | ถ้า **ไม่มีใครนอกโปรแกรมต่อเข้า DB โดยตรง** (SCADA/BI/ลูกค้าเปิด HeidiSQL เอง) → **SQLite** ตัด bootstrap-mysql / vendor zip / user+grant / dual-DB ออกทั้งก้อน ลดงานติดตั้งได้มากที่สุดในบรรดาทุกข้อ |
| **D3** | รูปแบบ installer | exe เดียวจาก Inno Setup / MSIX แทนกอง `.ps1`+`.bat` 24 ไฟล์ |
| **D4** | ไลบรารี frontend | shadcn/ui + Tailwind + TanStack Table/Query — ทันสมัย คุม look ได้เต็ม, professional density |
| **D5** | ข้อมูลลูกค้าเดิม | ต้อง migrate เข้ามาไหม หรือ v2 ใช้กับลูกค้าใหม่ / เริ่มนับใหม่ |
| **D6** | v1 ยัง maintain ต่อระหว่างทำ v2 ไหม | ถ้าใช่ ต้องล็อกว่ารับเฉพาะ bug fix ไม่รับ feature ใหม่ |
| **D7** | scaler ×10 (ADR 0010) | แก้ให้ถูกใน v2 หรือยกของเดิมมา — ขึ้นกับว่ามีมิเตอร์ให้วัดไหม |
