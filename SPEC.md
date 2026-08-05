# ARICHDS Application — SPEC

> Baseline specification. Status: draft · Last updated: 2026-08-03
> เอกสารอ้างอิงหลักของโปรเจค — คำถาม "อยู่ใน scope ไหม" ให้กลับมาที่นี่
> รายละเอียดเชิงเหตุผล/หลักฐานของทุกการตัดสินใจอยู่ที่ [docs/REMAKE-PLAN.md](docs/REMAKE-PLAN.md)

## 1. ภาพรวม (Overview)

**ARICHDS Application** คือโปรแกรมติดตั้งบนเครื่อง Windows ที่ไซต์ลูกค้า ทำหน้าที่อ่านข้อมูลจากมิเตอร์ไฟฟ้า
9 รุ่น 3 ยี่ห้อ (CEWE · Mitsubishi · SMART TCC ผ่าน DLMS/COSEM และ Modbus) เก็บ load profile /
billing / energy summary ลงฐานข้อมูลในเครื่อง แสดงผลบนเว็บ UI ภายในไซต์ และ **push** ข้อมูลขึ้น
server กลางเพื่อแสดงบนเว็บไซต์ของทีม

เป็นการ remake จาก v1 (`cewe` — demo ผ่านลูกค้าแล้วแต่ยังไม่เคยใช้งานจริง) เพื่อแก้ 4 ปัญหา:
ชื่อโปรเจคไม่ตรงของจริง · การติดตั้งยุ่งยาก (2 service คนละภาษา + MySQL) · over-engineering
(~30 ตาราง, 10+ threads) · frontend ไม่ทันสมัย — โดย **business logic ของ v1 คือ ground truth**
(ลูกค้ายืนยันหน้างานแล้ว) แต่ internals เขียนใหม่ได้อิสระ

## 2. เป้าหมาย & สิ่งที่ไม่ทำ (Goals & Non-Goals)

### เป้าหมาย

- **ติดตั้งจบใน < 10 นาที** บนเครื่อง Windows เปล่า ด้วย installer exe ตัวเดียว + activation code
  หนึ่งบรรทัด โดยไม่มีคำถามเรื่องฐานข้อมูลเลยสักข้อ
- **1 process · 1 exe · 1 database · 1 license** ครอบทั้ง DLMS และ Modbus (v1 มี 2 service คนละภาษา)
- **Output parity กับ v1** — ตัวเลข load profile / billing / energy summary ที่แสดงต้องตรงกับ v1
  บนมิเตอร์ตัวเดียวกัน **ที่ค่า setting default ของ v1** (`divide_by_1000=on` → kWh) —
  ใช้เป็นเกณฑ์เทสได้เพราะ v1 ผ่านการยืนยันจากลูกค้าแล้ว
- **เว็บไซต์กลางได้ข้อมูลผ่าน push เท่านั้น** — ไม่มีโปรแกรมภายนอกอ่านตารางฐานข้อมูลอีก
  และ API ตัวกลางบนเครื่องลูกค้าถูกถอนทิ้ง
- **Lean**: ตาราง ≤ 13 · thread คงที่ 2 + n มิเตอร์ (v1: ~30 ตาราง, 10+ threads)
- **กรอบเวลา**: วันที่ 5 = M1–M6 ครบ (เส้นทาง DLMS ทุกรุ่น + installer) · วันที่ 14 = M8 จบ
  (push ขึ้นเว็บได้ + ครบทุกหน้า)

### สิ่งที่ไม่ทำ (Non-Goals)

- **ไม่ ship Linux** — Windows เท่านั้นในเฟสนี้ (โค้ดเขียนให้ portable ไม่ผูก Windows API
  เพื่อเปิดทาง Linux ทีหลัง แต่ไม่มี artifact/installer/testing ฝั่ง Linux)
- **ไม่มี online activation ใน 14 วัน** — M9 ถูก gate ด้วย portal v2 ซึ่งยังไม่เริ่ม
  (offline activation คือทางหลักของเฟสนี้ และเป็นทางหนีไฟถาวรตลอดไป)
- **ไม่มี inbound API สำหรับ 3rd party** — ตัดกลไก `X-API-Key` (M2M) ของ v1 ทิ้ง
  auth เหลือ JWT ของผู้ใช้ทางเดียว · ไม่มี Open API / webhook (หน้า ApiConfig ของ v1 ตายไปกับ push)
- **ไม่มี i18n** — UI อังกฤษล้วน (กวาดข้อความไทยที่ปนใน v1 ออกให้หมด)
- **ไม่มี GPRS เป็น transport แยก** — transport มีแค่ TCP/IP + Serial (มิเตอร์ที่ต่อผ่าน GPRS
  เข้ามาเป็น TCP อยู่แล้วจากฝั่งโมเด็ม)
- **ไม่เก็บ register modbus นอก mapping** — เก็บเฉพาะ ~14 คอลัมน์ที่ map เป็น COSEM
  (register อีก ~77 ตัวของ CEWE modbus ไม่เก็บ — ดู Open Questions เรื่องตาข่ายกันตก)
- **ไม่ migrate ข้อมูลจาก v1 · ไม่ maintain v1 คู่ขนาน** — v1 ไม่เคยมี production install
- **ไม่มี auto-update ในตัวโปรแกรม** — อัปเดตเวอร์ชัน = รัน installer ตัวใหม่ทับ
  (ตรวจของเดิม เก็บ DB/license รัน migration อัตโนมัติ)
- **ไม่ optimize เกิน 30 มิเตอร์/ไซต์** — สเกลจริงคือ 10–30 ตัว/ไซต์
- **ไม่เปลี่ยน divide_by_1000 เป็น option** — ตัดทิ้ง แสดง kWh เสมอ (หน่วยเดียวทั้งระบบ)

## 3. ความต้องการเชิงฟังก์ชัน (Functional Requirements)

จัดกลุ่มตามบันไดโมดูล M2–M8 (ลำดับ implement) — ทุกโมดูล = backend + หน้า FE ของมัน + เทสผ่าน
จึงเริ่มโมดูลถัดไป

### 3.1 Skeleton & ติดตั้ง (M1) — grill แล้ว 2026-08-03, 9 ข้อ

**โครง repo**: `app/` (Python backend, `src/` ข้างใน) · `web/` (React + AntD) · `installer/`
(Inno script + ของประกอบ build) · `tools/` (vendor CLI)

**Installer & service**:
- **Inno Setup** สร้าง `setup.exe` ตัวเดียว (wizard/uninstall/upgrade ในตัว) + **NSSM** ห่อ
  `arichds.exe` เป็น Windows service (สูตรเดียวกับ v1 ที่พิสูจน์แล้ว: auto-start, restart on exit,
  log rotation 50 MB)
- ที่อยู่: โปรแกรม `Program Files\ARICHDS` · ข้อมูลทั้งหมด `%ProgramData%\ARICHDS\`
  (`arichds.db`, license, logs, captures, backups)
- พอร์ต **8000** · bind LAN ได้ — installer เปิด firewall rule ให้เครื่องอื่นในไซต์เข้า
  `http://<ip>:8000` ได้
- **Migration รันอัตโนมัติตอน service start** (alembic upgrade head ก่อนเปิด API) —
  installer/updater ไม่ต้องมี step migrate แยก

**Activation (offline)**:
- **หน้าเว็บ first-run**: โปรแกรมเริ่มใน limited mode → หน้า Activation โชว์ Machine ID
  (ปุ่ม copy) + ช่องวาง activation code → verify แล้ว**มีผลทันที ไม่ต้อง restart**
  (enforcement ออกแบบให้ re-evaluate ใน process — ต่างจาก v1 ที่ต้อง restart) —
  หน้าเดียวกันใช้ซ้ำตอนต่อ/เปลี่ยน license และเป็นที่อยู่ของ online activation ใน M9
- Machine fingerprint คำนวณใน Python — **พอร์ตสูตรเดิมจาก Go** (`modbus-logger/internal/license/fingerprint.go`:
  collect → combine → SHA-256; ฝั่ง Windows องค์ประกอบเดียวคือ registry `MachineGuid`)
  เปลี่ยนเฉพาะ salt/ชื่อเป็น ARICHDS แล้ว**แช่แข็งตั้งแต่วันแรก** (เปลี่ยนสูตรทีหลัง = license ทุกใบพัง)
- Vendor CLI ใน `tools/`: สร้าง keypair + เซ็น license (ยกจาก `tools/generate_key.py` ของ v1
  มาเปลี่ยนชื่อ) — license ทดสอบ/ช่วงก่อน portal ออกเป็น `mode: offline`

**Skeleton ที่มองเห็น**:
- App shell (AntD **re-theme: deep teal · compact density · light**) — theme tokens วางที่นี่
  ครั้งเดียว ทุกโมดูลถัดไปสืบทอด
- หน้า Activation + หน้า monitor เดียว: เพิ่มมิเตอร์ Prometer100 แบบ minimal →
  **poller อ่าน instantaneous set เล็ก ๆ (V/I รายเฟส, freq, total import kWh) ทุก 60 วิ →
  เก็บ DB → API → หน้าเว็บ auto-refresh** โชว์ค่าล่าสุด + เวลาอ่าน — พิสูจน์ chain เต็มเส้น
- SPA เสิร์ฟจาก FastAPI origin เดียวกัน — ไม่มี nginx, ไม่มี CORS
- **M1 ไม่มี auth โดยเจตนา** — M2 ติด guard ย้อนหลัง
- เช็คคุณภาพเป็น local ทั้งหมด (ruff + pytest + build ตาม gate ต่อโมดูล) — **CI เพิ่มหลังพ้นช่วงเร่ง**

### 3.2 Auth & User Management (M2) — grill แล้ว 2026-08-04, 4 ข้อ

**First-run flow (เครื่องใหม่)**: **Setup admin → Login → Activation** —
- หน้า Setup สร้าง admin คนแรก เปิดโล่งเฉพาะตอน user = 0 (ยก pattern `check-setup`/`setup`
  ของ v1 มาตรง ๆ: นับ user + UNIQUE กันซ้ำ, atomic)
- endpoint ยกเว้น auth มีแค่ **health · check-setup · setup · login** (+ static SPA) —
  ที่เหลือ JWT ทั้งหมด รวมถึง `/api/license/*`: ดู status = user ใดก็ได้ที่ login แล้ว,
  **activate/เปลี่ยน license = admin เท่านั้น** (เปลี่ยนจาก M1 ที่เปิดโล่ง — M2 ติด guard ย้อนหลัง
  ทับหน้า Activation ด้วย) — กันคนใน LAN แตะ license โดยไม่มีสิทธิ์
- Login ใช้งานได้แม้อยู่ใน limited mode (auth endpoints ไม่ถูก license gate บัง — ไม่งั้น
  เครื่องที่ lease ขาดจะ activate ใหม่ไม่ได้)

**Session & token** (ยก mechanics v1 ที่พิสูจน์แล้ว):
- JWT อายุ **8 ชม.** (`ARICHDS_TOKEN_EXPIRE_MINUTES` override ได้) · หมดแล้ว login ใหม่
  ไม่มี refresh/remember-me (จอ dashboard ค้างถาวรเป็น feature อนาคตถ้าหน้างานขอ)
- เก็บเฉพาะ **SHA-256 hash ของ token** ใน `user_tokens` (INV-AUTH-04 ของ v1) ·
  revoke ตอน logout · เปลี่ยนรหัส = revoke token อื่นทั้งหมดของ user นั้น
- bcrypt + constant-time login (dummy-hash path เมื่อไม่พบ user — INV-AUTH-02/03 ของ v1)
- **JWT secret สร้างเองตอนติดตั้งแล้วเก็บที่ `%ProgramData%\ARICHDS\secret\jwt_secret.key`**
  (ต่างจาก v1 ที่บังคับ env — ดู ADR 0003) · override ได้ด้วย `ARICHDS_JWT_SECRET` และ
  `ARICHDS_TOKEN_EXPIRE_MINUTES` · ลบไฟล์ key = revoke ทุก token (คือกลไก rotate)

**Role** (2 ระดับ, enum column — เส้นแบ่งตาม v1 เป๊ะ):
- `admin`: จัดการมิเตอร์ (เพิ่ม/แก้/ลบ) · จัดการ user · ตั้งค่าระบบ · license
- `user`: ดูข้อมูลทุกหน้า · สั่งอ่าน manual · export CSV/PDF

**Password**: ขั้นต่ำ 8 ตัวอักษร (และไม่เกิน 72 **ไบต์** — ขีดจำกัดของ bcrypt 5) ไม่บังคับ complexity ·
ลืมรหัส = admin ตั้งใหม่ให้จากหน้า User Management (ไม่มี email infra) · admin คนเดียวลืมเอง =
ทางหนีไฟผ่าน vendor CLI บนเครื่อง (**ยังไม่ได้ทำ** — `tools/arichds_vendor.py` มีแค่
keygen/sign/fingerprint) · **ไม่มี lockout/rate-limit** — บันทึก failed login ลง log
(โผล่ App Log ใน M7); bcrypt ช้าพอเป็น rate-limit ธรรมชาติ และเครื่องอยู่ใน LAN ปิด

**User Management** (M2-2 — admin เท่านั้นทุก endpoint):
- CRUD: list · create (ระบุ role เสมอ ไม่มี default) · เปลี่ยน role · reset password · delete
  (v2 ไม่มีคอลัมน์ `is_active` — "ปิดการใช้งาน" ของ v1 คือ **ลบแถวจริง** แล้ว token ของคนนั้น
  หายไปด้วย FK cascade → session ที่เปิดค้างตาย 401 ทันที)
- **กฎกันล็อกตัวเอง 3 ข้อ (400 ทั้งหมด)** — admin ห้าม **ลบตัวเอง** (INV-AUTHZ-02 ของ v1) ·
  ห้าม **เปลี่ยน role ตัวเอง** · ห้าม **reset password ตัวเอง** (ต้องใช้ Change password ซึ่งถาม
  รหัสเดิม) · **ไม่ต้องนับ admin** — ทุก endpoint ต้องเป็น admin อยู่แล้วและ actor ถอดความเป็น
  admin ของตัวเองไม่ได้ จำนวน admin จึงลงถึง 0 ไม่ได้ · **ไม่มีสิทธิพิเศษให้ admin คนแรก** —
  id 1 เป็นแถวธรรมดา admin อีกคนลบ/ลดขั้นได้ (ไม่งั้นบัญชีแรกที่ลืมรหัส/ถูกยึดจะลบไม่ได้ตลอดกาล)
- **admin reset password ให้คนอื่น = revoke ทุก token ของ user นั้น** (ต่างจาก v1 ที่ไม่ revoke
  อะไรเลย) — คนเปลี่ยนไม่ใช่เจ้าของรหัส จึงเป็นเคสลืมรหัสหรือสงสัยว่าถูกยึด ปล่อย session ค้างไว้
  เสียเป้าหมายทั้งสองทาง · session ของ admin ผู้สั่งไม่ถูกแตะ
- **เปลี่ยน role ไม่ revoke token** — `require_admin` อ่าน role จากแถวใน DB ทุก request
  (claim `role` ใน JWT เป็นข้อมูลประกอบ ไม่ใช้ตัดสินสิทธิ์) การลด/เพิ่มขั้นจึงมีผลที่ request
  ถัดไปด้วย token เดิม ไม่ต้อง login ใหม่
- **เปลี่ยนรหัสตัวเอง** (`POST /api/auth/change-password`, ทุก role ใช้ได้): ตรวจรหัสเดิมก่อนเสมอ
  (INV-DATA-04 ของ v1) · รหัสใหม่ต้องต่างจากเดิม (422) · **revoke token อื่นทั้งหมดของ user นั้น
  แต่เก็บ token ที่ยื่นมาไว้** — คนที่เพิ่งกดเปลี่ยนต้องไม่หลุด session · รหัสเดิมผิดตอบ **400 ไม่ใช่
  401** (SPA เคลียร์ session ทุก 401 ที่มี token — ตอบ 401 = พิมพ์ผิดแล้วถูก sign out) ·
  อยู่ใต้ `/api/auth` จึงใช้ได้แม้เครื่องอยู่ใน limited mode ส่วน `/api/users` ถูก license gate ปกติ

**หน้า**: Setup (first-run) · Login · User Management

### 3.3 Device Manager (M3)

grill รอบ M3 (2026-08-05) — 31 ข้อตัดสิน อ้างอิง v1 `devices` (30 คอลัมน์), ADR 0009 ของ v1,
`catalog.py`, `meter_slots.py` และหน้า Devices ของ v1

**ตัวตนของ device** — ยกชุดฟิลด์ v1 มาครบ:
- `name` (unique) · `meter_serial` (unique, **อ่านจากมิเตอร์ ไม่ใช่คนกรอก**) · `site_name` (**บังคับกรอก**
  ใช้จัดกลุ่มใน tree) · `site_code` · `customer` · `meter_number` · `group_name`
- **สามช่อง `site_code` / `customer` / `meter_number` เป็นช่องบันทึกล้วน ๆ** — v1 ไม่มี logic ใดผูกอยู่
  (มีแค่ validator แล้วเก็บ) ห้ามประดิษฐ์พฤติกรรมให้ · `group_name` มี query ดึงค่า distinct ไปทำ dropdown
- brand/model จาก catalog 9 รุ่น (ยก `catalog.py` ของ v1 มาพร้อม capability flags) แต่ช่อง Model
  **แสดงเฉพาะรุ่นที่มี driver จริง** — M3 = `prometer100` เท่านั้น อีก 8 รุ่นโผล่เมื่อ M4 ลง driver
- **ไม่มีรุ่น SIM อีกต่อไป** — ยกเลิกจาก M1: `simulated.py` ออกจาก driver registry / catalog / README
  เหลือเป็น fake driver ที่เทส monkeypatch เข้าไปเท่านั้น (เทสห้ามยิงมิเตอร์จริง)
- **device ที่สร้างก่อน M3**: migration **ไม่ลบอะไร** — แถวที่ `model` ไม่มี driver แล้ว (เช่น `sim` เก่า)
  ถูกตั้ง `enabled=0` และ `site_name` เติมค่า placeholder ส่วน `meter_serial` ปล่อยว่างไว้
  = "ยังไม่ยืนยันตัวตน" จนกว่าคนจะกด Update (ซึ่ง probe เสมอ) · โค้ดห้ามสมมติว่า serial ไม่มีวันว่าง
- transport: **TCP อย่างเดียวใน M3** — ช่อง Serial (COM/baud/data bits/parity/stop bits/flow control)
  มาพร้อม SMW110 ที่ M4 เพราะ M3 ไม่มีรุ่น serial ให้เลือก จึงเทสไม่ได้ · คอลัมน์ `transport` เป็น JSON
  อยู่แล้วจึงไม่ต้อง migrate ตอนเพิ่ม · **ไม่มีช่อง Source (dlms/modbus) ใน M3** — modbus มาหลังวันที่ 5
- auth: `password` + `block_cipher_key` + `authentication_key` ครบตั้งแต่ M3 (M3 ใช้แค่ password
  แต่ M4 ต้องใช้ทั้งสาม จึงไม่ต้องกลับมาแก้ model/ฟอร์ม/API รอบสอง) · สร้างใหม่ prefill password ด้วย
  `fixed_password` ของยี่ห้อ (CEWE = `ABCD0001`) · **ตอนแก้ เว้นว่าง = คงรหัสเดิม** (พฤติกรรม v1)
- billing: `first_bill_date` + `bill_day_feb28/29/30/31` — ช่องอยู่ที่นี่ ตรรกะการตัดงวดอยู่ M6

**Probe-first identity (ADR 0005)** — `meter_serial` มาจากมิเตอร์เสมอ:
- **Create ต่อมิเตอร์จริงก่อนเขียนแถว** อ่าน serial มาใส่ให้ · probe ล้ม (timeout / auth / unreachable)
  = **ปฏิเสธพร้อมสาเหตุ ไม่สร้างแถว** ⇒ ทุกแถวใน DB มี serial เสมอ
- serial ซ้ำกับ device ที่**ยังอยู่** = 409 บอกชื่อ device เดิม (ย้าย IP ต้องแก้ที่แถวเดิม) ·
  ลบ device ไปแล้ว serial นั้นเพิ่มใหม่ได้ — **ไม่มี tombstone** (ไม่งั้นกรอกผิดครั้งเดียวตันถาวร)
- **Update ก็ probe ซ้ำ** — ถ้า serial ที่ได้ต่างจากเดิม = ชี้ไปมิเตอร์คนละตัว ปฏิเสธ (กันข้อมูล 2 มิเตอร์
  ปนกันในแถวเดียว) · แก้ได้ทุกช่องรวม brand/model

**สถานะ — มาจาก Poller ไม่มี health-check loop แยก (ADR 0004)**:
- v1 มี health-check thread ของตัวเองทุก 5 นาที + ตาราง `device_status` + `device_heartbeats` ·
  v2 ตัดทิ้งทั้งชุด: poller อ่านค่าจริงทุก 60 วิอยู่แล้ว **ผลของ tick นั้นคือสัญญาณสถานะ** —
  ไม่เปิด connection ซ้ำไปที่มิเตอร์ และไม่มี job เพิ่มใน registry
- 4 สถานะ: **Online · Offline · Paused · Unknown** — ไม่มี `Error` แยก (อ่านไม่สำเร็จคืออ่านไม่สำเร็จ
  สาเหตุอยู่ใน `detail`) · `Unknown` = ยังไม่มี tick หลัง Resume
- **Offline เมื่อพลาด 3 tick ติด** (~3 นาที) — กันสถานะกระพริบจาก timeout ชั่วคราว
- สร้างสำเร็จ = **Online ทันที** (probe เพิ่งต่อติดไปเมื่อกี้ ไม่ต้องรอ 60 วิ) · Resume = **Unknown**
  จนกว่า tick แรก (ระหว่าง pause ไม่มีใครคุยกับมิเตอร์ จึงไม่มีใครรู้ว่ามันยังอยู่ไหม)
- cadence **คงที่ 60 วิ ตั้งค่าไม่ได้** (env override ไว้แก้ปัญหาเท่านั้น) — ไม่มีคอลัมน์ `poll_interval_sec`

**`device_events` — เก็บเฉพาะตอนเปลี่ยน**:
- status transition (Online↔Offline) + การกระทำของคน (created / updated / paused / resumed /
  data cleared) พร้อมชื่อผู้สั่ง — **ไม่ใช่ heartbeat ทุก tick แบบ v1** (30 มิเตอร์ × 288 ครั้ง/วัน
  ≈ 8,600 แถว/วัน จะกลายเป็นตารางที่ใหญ่ที่สุดรองจาก `interval_readings` โดยไม่มีใครอ่าน)
- แลกมาด้วย: คำนวณ uptime % ย้อนหลังแบบละเอียดไม่ได้ — ยอมรับ ไม่มีใครขอ
- แสดงผ่าน **drawer** ที่เปิดจากปุ่ม History บน panel ขวา (เลย์เอาต์ tree+form ไม่มีที่ว่างเหลือ)

**Pause / Resume — คอลัมน์เดียว**:
- ใช้ `enabled` ที่มีอยู่แล้ว **ไม่มี `polling_paused` แยก** — v1 ต้องมี 2 คอลัมน์เพราะ `is_active`
  คือ soft-delete ที่ซ่อน device ออกจากทุก list ส่วน v2 ลบคือลบจริง เจตนาของ ADR 0009
  (หยุด background ทุกชนิดแบบ persistent ข้าม restart, ไม่ปิด socket กลางคัน) คงไว้ครบ
- คำสั่งอ่านที่คนสั่ง **ไม่ถูก pause บัง** (ตาม v1) — pause คุมเฉพาะ background

**คำสั่งคนมาก่อน background (ADR 0006)**:
- M3 มี 4 เส้นทางที่คนสั่งคุยกับมิเตอร์: probe ตอน Create · re-probe ตอน Update · Test connection ·
  Read now — ทุกเส้นแย่ง lock ต่อ Transport Endpoint กับ poller
- **priority lock: งานที่คนสั่งได้คิวก่อน background tick เสมอ** (tick ที่ข้ามไปคือค่าที่ขาดไป 1 นาที
  ไม่ใช่เรื่องใหญ่ ส่วนคนที่กดปุ่มค้างรอคือเรื่องใหญ่) — ยก ADR 0020 ของ v1 มาทำที่ M3 ไม่ใช่ M4
  ตามที่ §3.4 เคยเขียนไว้ · ต้องมีเทสเรื่อง starvation

**Quota — นับจำนวนอย่างเดียวใน M3**:
- เพิ่ม device ได้เมื่อ `count(devices) < max_meters` (ไม่มี `max_meters` = ไม่จำกัด) —
  **ไม่มีช่อง Meter Key ในฟอร์ม M3** เพราะ redeem ต้องใช้ portal ซึ่งมาที่ M9 (ดู §3.9)
- ลบ device แล้ว slot คืนทันที — ข้อ "slot ไม่คืน" ใน §3.9 เป็นกติกาของ portal ไม่ใช่ของ count backstop
- license ใหม่ที่ `max_meters` น้อยกว่าจำนวนที่มีอยู่: **ของเดิมทำงานต่อครบทุกตัว ห้ามเพิ่มใหม่**
  หัว tree ขึ้นเตือน `10 / 5 — over quota` (ตัดข้อมูลลูกค้ากลางคันเพราะเลข license เปลี่ยนคือสิ่งที่ห้ามทำ)

**หน้า Devices** — tree ซ้าย + ฟอร์มขวา (โครงเดิมของ v1 คนหน้างานใช้ต่อได้ทันที):
- tree: กลุ่มตาม `site_name` · จุดสถานะสี · หัว tree มี ช่องค้นหา + กรองสถานะ + กรองรุ่น/ยี่ห้อ +
  ชิปโควต้า `X / Y meters`
- ปุ่ม: Create · Update · New Device (copy) · Pause/Resume · **Read now** (สั่งอ่านทันที) ·
  **Test connection** (ทดสอบค่าในฟอร์มโดยไม่เขียนแถว) · History · Delete ·
  **Delete all data** (ลบเฉพาะ `interval_readings` ของ device นั้น เก็บ `device_events` ไว้เป็น
  หลักฐานว่าใครลบ · **ต้องพิมชื่อ device ให้ตรงก่อนกดยืนยัน** เพราะกู้คืนไม่ได้)
- สิทธิ์: อ่าน/Read now = ทุก role · เพิ่ม/แก้/ลบ/pause/Delete all data = admin (§3.2) ·
  **Test connection = admin** — §3.2 ให้ทุก role อ่านได้และให้ admin เท่านั้นแก้ได้ แต่ Test connection
  ไม่ใช่ทั้งสองอย่าง จึงตัดสินแยก: มันคือครึ่งวินิจฉัยของฟอร์ม Create/Update ที่เป็น admin อยู่แล้ว และมันเล็ง
  socket ของเครื่องนี้ไปที่ `host:port` อะไรก็ได้ที่คนกรอก
- **หน้า: Devices หน้าเดียว** — หน้า Instantaneous ย้ายไป M5 (ดู §3.5)

### 3.4 Acquisition (M4)

- `MeterDriver` abstraction เดียว ครอบ DLMS (Gurux vendored) + Modbus (pymodbus)
  — **ห้ามมี if/elif ตามรุ่นในโค้ดกลาง** (หลักการ ADR 0004 ของ v1)
- รุ่นที่รองรับ (9 รุ่น เท่า v1): CEWE Prometer100 / Saral305 / Premier550 ·
  Mitsubishi SMW110 (DLMS serial + Modbus) · SMART TCC st3c / st3cl / st33tl / st3tl / st3dh
- **เฟสแรก (ภายในวันที่ 5): เส้นทาง DLMS/COSEM ครบทุกรุ่น** · เส้นทาง Modbus (พอร์ตจาก Go)
  ตามมาหลังวันที่ 5 — mapping modbus→COSEM ใช้ของ ADR 0005 (v1) ระหว่างรอลูกค้ายืนยัน
- ทุก driver เขียนลง `interval_readings` ตารางเดียว หน้าตา COSEM (แปลงตอนเขียน):
  **UTC เสมอ · kWh เสมอ · ชื่อคอลัมน์ตรงหน่วยจริง** (normalization contract — REMAKE-PLAN §6.1)
- Lock ต่อ **transport endpoint** (TCP: host:port · Serial: ชื่อ COM port) — อุปกรณ์บนสายเดียวกัน
  เข้าคิวกัน · manual read มี priority เหนือ background (ADR 0020 ของ v1) — **ทำไปแล้วที่ M3**
  (ADR 0006 ของ v2) เพราะ Read now / Test connection / probe เกิดขึ้นตั้งแต่ M3
- Scaler: เขียนให้ถูกต้องตั้งแต่ต้น โดยล็อกด้วย test case จากค่าที่ลูกค้ายืนยันแล้ว
  (ไม่ยกพฤติกรรม phantom ×10 ของ ADR 0010 มา แต่ผลลัพธ์สุดท้ายต้องตรง v1)

### 3.5 Load Profile (M5)

- อ่าน load profile จาก Logger 1 (`1.0.99.1.0.255`) และ Logger 2 (`1.0.99.2.0.255`)
  **เก็บเป็นคนละแถว** มี `logger_id` เป็นตัวแยก unique key = `(device_id, logger_id, read_at)`
  ตามที่ v1 ทำ (ADR-6 ของ v1) — **ประโยคเดิมที่เขียนว่า "รวมแถวด้วย `read_at`" ผิด**
  พิสูจน์แล้วด้วยการ probe มิเตอร์จริง 3 รุ่นเมื่อ 2026-08-05
  (`docs/meter-notes/load-profile-capture-objects.md`) — merge ไม่ได้ทั้งสามรุ่น คนละเหตุผล:
  - **Prometer 100**: Logger 1 = **900 วิ** · Logger 2 = **300 วิ** ⇒ timestamp ไม่ตรงกันเลย
    ไม่มี `read_at` ร่วมให้ merge · และความถี่ (`1.0.14.27.0.255`) อยู่ใน**ทั้งสอง** logger
  - **Premier 550**: รอบตรงกันทั้งคู่ (900 วิ) แต่ Logger 1 เก็บ `1.0.1.29.0.255` ส่วน Logger 2
    เก็บ `1.0.1.8.0.255` ซึ่ง v1 แมป**ลงคอลัมน์เดียวกัน** (ค่าช่วง vs ค่าสะสม) ⇒ merge = ทับกันเงียบ ๆ
  - **Saral 305**: ไม่มี Logger 2
  ⇒ ข้อความเดิมที่ว่า "Logger 2 เป็นของ Premier 550" และ "Logger 1 = energy, Logger 2 = V/I/PF"
  **ผิดทั้งคู่** — Prometer 100 ก็มี Logger 2 · และ Logger 1 ของมันมีทั้งพลังงานและ V/I/PF/freq
- **ห้ามสมมติว่า capture period คือ 900 วิ** — อ่าน attr 4 ของ ProfileGeneric ทุกครั้ง
- CSV auto-export ต่อ device (watermark pattern) + manual read-now
- Retention: LP 90 วัน · billing 365 วัน · events 90 วัน (ตัวเลขเดิม v1) — job รายวัน
- Backup อัตโนมัติรายวัน: `VACUUM INTO` ไปโฟลเดอร์ backup + หมุนเวียนลบของเก่า
- **Records** (ย้ายมาจาก M3 — grill M3 2026-08-05): ตารางตรวจความครบของข้อมูล แถว = มิเตอร์
  คอลัมน์ = วันที่ ช่อง = จำนวน interval ที่เก็บได้วันนั้น (ครบวัน = **96**, ขาด = `N (-X)`,
  ไม่มีเลย = `0 (Missing)`) — v1 เรียกหน้านี้ว่า **Instantaneous Records** (เมนู "Records")
  แต่เป็นหน้าเปล่า: `DATES`/`DEVICE_ROWS` hardcode ว่าง ไม่มี API call และ worker ไม่มี endpoint รองรับ
  ⇒ v2 เป็นผู้เขียนหน้านี้ครั้งแรก และต้องมี load profile ก่อนจึงจะมีอะไรให้นับ จึงอยู่ที่ M5 ไม่ใช่ M3
- หน้า: Load Profile · Records

### 3.6 Billing (M6)

- Open period = upsert slot เดียวต่อ device (ADR 0018) · ปิดงวดตาม reset-reason / driver capability
- Backfill ประวัติจากมิเตอร์ · manual read · auto-read ตามเวลา (job ใน registry)
- Capture PDF/xlsx ลง filesystem (ตาม v1) — gated ด้วย feature `auto_capture` / `billing_excel_export`
- Modbus billing cut (ระบบตัดบิลแทนมิเตอร์ที่ตัดเองไม่ได้) — **เขียน ADR ใหม่** อ่านจาก
  `interval_readings` (กฎธุรกิจเดิมของ ADR 0019: ตัดที่ 00:00 ของวันบิล, catch-up, idempotent) —
  มากับเฟส modbus หลังวันที่ 5
- หน้า: Billing

### 3.7 โมดูลเบา (M7)

- Energy Summary (TOU buckets — ADR 0016) · Holidays (2 ชนิด) · Special Days · Battery status ·
  Export format settings · App Log (log viewer — log ผ่าน credential redaction filter เสมอ)
- หน้า: EnergySummary · Holidays · SpecialDays · Battery · ExportFormat · AppLog
- **นับหน้าครบที่นี่**: 14 หน้า v1 → 12 หน้ามีเจ้าของใน M2–M7 + DatabaseSettings ถูกลบ (SQLite)
  + ApiConfig ถูกแทนด้วย push (M8)

### 3.8 Data-out / Sync (M8)

- โปรแกรม **push** ขึ้น server เดิมของทีม (เพิ่ม endpoint รับ) — outbound HTTPS ทางเดียว
  ไม่เปิด inbound port ที่ไซต์
- ข้อมูลที่ส่ง: **billing · load profile · energy summary · รายชื่อมิเตอร์ + สถานะ online/offline**
- Contract: JSON · รอบ 15 นาที · JWT ผูกกับ activation (site identity = machine token จาก portal
  — เฟสนี้ฝังใน license/config ตอน activate แบบ offline)
- ทนเน็ตหลุด: watermark เลื่อนเมื่อ server ACK เท่านั้น · ส่งย้อนหลัง **ครบทุกแถวเสมอ** ·
  `interval_readings`/energy ใช้ watermark append-only · `billing_readings` track ด้วย `updated_at`
  (open period ถูก upsert ที่เดิม + backfill แทรกย้อนหลัง — watermark ธรรมดาใช้ไม่ได้) ·
  รายชื่อมิเตอร์ + สถานะ = **snapshot ทั้งชุดทุกรอบ** (ข้อมูลเล็ก ไม่ต้อง track diff)
- เมื่อ M8 เสร็จ: ถอน API ตัวกลางออกจากเครื่องลูกค้า

### 3.9 Licensing (คร่อมทุกโมดูล — enforcement ตั้งแต่ M1)

- License = ไฟล์เซ็นด้วย Ed25519 ผูก machine fingerprint · **lease 45 วัน renew รายวันผ่าน portal**
  (kill-switch ไม่ใช่ subscription) · offline activation เป็นทางหนีไฟถาวร (payload `mode` รองรับ)
- Limited mode เมื่อ license ขาด/หมด/fingerprint ไม่ตรง: API ตอบ 403 `LICENSE_INVALID`
  (health + SPA ยังเข้าถึงได้เพื่อแสดง error) · polling หยุด · process ไม่ตาย
- **Meter Key** (โมเดลเดิม v1 #145): 1 key = 1 device slot ผูก serial มิเตอร์ผ่าน probe-first redeem ·
  ลบ device แล้ว slot ไม่คืน · เกิน `max_meters` ต้องใช้ key — **ทั้งย่อหน้านี้เริ่มมีผลที่ M9**
  (redeem ต้องมี portal) · **M3 บังคับด้วยการนับจำนวนอย่างเดียว ไม่มีช่อง Meter Key ในฟอร์ม** (§3.3)
- **Feature entitlement**: enabled = `.env FEATURES ∩ license features` · sellable 8 ตัว (เท่า v1):
  `billing` `load_profile` `energy_summary` `special_days` `instantaneous` `battery` `auto_capture`
  `billing_excel_export` · ops-only (ใน .env เท่านั้น): `auto_read_billing` `auto_backfill` `app_log`
  (`api_config` ของ v1 ตายไปกับหน้า ApiConfig)
- ชื่อเชิง cryptographic ทั้งหมดเปลี่ยนเป็น ARICHDS (fingerprint salt, signing version, keypair ใหม่)
  — ทำได้เพราะไม่มี license v1 ในสนาม · **v2 คือผู้นิยาม contract แล้ว portal v2 ทำตาม**

## 4. เทคนิค & สถาปัตยกรรม (Technical & Architecture)

- **Stack**: Python 3.14 (floor `>=3.13`; เครื่อง dev/build จริงคือ 3.14.6 — M1) + FastAPI
  (API + เสิร์ฟ SPA) · PyInstaller onedir → `arichds.exe` ·
  React + TypeScript + **Ant Design v6 แบบ re-theme** (ConfigProvider tokens ใหม่ทั้งชุด — primary/density/radius
  ไม่ใช่ default look; ตัดสิน 2026-08-03 หลังเทียบ mockup กับ Mantine และ shadcn/ui —
  `mockups/devices-lib-compare/`) · **ไม่มี Tailwind** (M1 ไม่ต้องใช้ — AntD tokens + layout
  primitives พอแล้ว) · **SQLAlchemy 2** (ORM — ไม่ใช้ SQLModel แม้ FastAPI skill จะแนะนำ
  เพราะ Alembic autogenerate + batch mode คือเส้นทางหลักของ schema; ตัดสิน M1) ·
  SQLite (WAL) + Alembic ชุดเดียว (`render_as_batch=True` ตั้งแต่ migration แรก) ·
  Gurux DLMS (vendored `GX*.py` ห้ามแก้ API) · pymodbus · Ed25519 (`cryptography`)
- **สถาปัตยกรรม**: 1 process — main thread (uvicorn) + poller pool (1 thread/มิเตอร์, lock ต่อ
  transport endpoint) + scheduler thread เดียวรันทุก periodic job จาก registry
  `[(name, interval, fn)]` (LP scheduler, billing auto-read, retention, backup, sync, license recheck)
  — **ไม่มี health-check job**: สถานะมิเตอร์เป็นผลพลอยได้จาก poller tick (ADR 0004)
- **Data model** (13 ตาราง): `devices` (รวม settings/status/capture_objects เป็น JSON columns) ·
  `device_events` · `interval_readings` (COSEM shape + `source` + `interval`) · `interval_read_jobs` ·
  `billing_readings` · `billing_captures` · `energy_register_readings` · `battery_readings` ·
  `holidays` · `settings` (key/value) · `users` · `user_tokens` · `sync_state`
- **Interfaces**:
  - ขาออก: push endpoint บน server เดิมของทีม (JSON/15min/JWT) — field-level contract ออกแบบร่วม
    ฝั่ง server ที่ M8 · portal v2 (`/activate` `/renew` `/redeem`) — contract นิยามที่ M0 ใช้จริง M9
  - ขาเข้า: ไม่มี (REST ของโปรแกรมเป็น internal สำหรับ SPA เท่านั้น)
- **ข้อจำกัด**: Windows-first แต่โค้ด portable (ไม่ผูก Windows API นอกชั้น installer/service) ·
  transport = TCP + Serial · เวลาใน DB = UTC เสมอ · พลังงาน = kWh เสมอ · UI อังกฤษล้วน ·
  ชื่อทุกชั้นเป็น `arichds`/`ARICHDS_*` · log ทุกตัวผ่าน credential redaction ·
  สเกลออกแบบที่ 10–30 มิเตอร์/ไซต์ · ทุกไซต์มีเน็ตแต่ไม่นิ่ง (ทุกอย่างที่แตะเน็ตต้อง retry ได้)

## 5. Milestones & คำถามค้าง (Milestones & Open Questions)

### Milestones

กติกา: หนึ่ง milestone = หนึ่งโมดูลจบในตัว (BE + FE + เทส) ผ่านแล้วจึงไปต่อ — นิยาม "เทสผ่าน"
และ exit criteria ราย M อยู่ใน REMAKE-PLAN §4

| ช่วง | เป้า |
|---|---|
| **วันที่ 1–5** | M0 (spec นี้ + เลือกไลบรารี FE จาก mockup) → M1 skeleton + installer → M2 auth → M3 devices → M4 **เส้นทาง DLMS ครบ 9 รุ่น** → M5 LP → M6 billing — จบด้วย demo ได้จริงจากเครื่องที่ติดตั้งด้วย installer |
| **วันที่ 6–14** | M4-modbus (พอร์ต Go + modbus billing cut) → M7 โมดูลเบา 6 หน้า → M8 push ขึ้นเว็บ + ถอน API ตัวกลาง |
| **หลัง 14 วัน** | M9 online activation (gate: portal v2) → M10 hardening + pilot ลูกค้า 1 ราย 2 สัปดาห์ |

### คำถามค้าง (Open Questions)

- **Mapping modbus→COSEM** — เดินหน้าด้วย mapping DERIVED ของ ADR 0005 ระหว่างรอลูกค้ายืนยัน
  (โดยเฉพาะช่องว่างของ SMW110) · ต้องปิดก่อนเฟส modbus เขียนข้อมูลจริง — และตอนนั้นค่อยตัดสินว่า
  ต้องมีตารางตาข่าย raw modbus (retention 7 วัน) ไหม
- **Field-level contract ของ push** — โครงตัดสินแล้ว (JSON/15min/JWT/ครบทุกแถว) แต่รายชื่อ field
  ต่อ payload ออกแบบร่วมฝั่ง server ตอน M8 — รวมถึง **วิธีที่ server verify JWT ที่ออกแบบ offline**
  (ช่วงไม่มี portal, vendor CLI เป็นผู้ออก token → server ต้องมี key สำหรับ verify)
- **`billing_captures`** — ยังไม่ยืนยันว่าจำเป็นเป็นตารางแยก หรือเก็บ metadata ใน filesystem พอ
  (ตัดสินตอน M6)
- **Portal v2** — timeline ยังไม่กำหนด · M9 บล็อกอยู่จนกว่า portal จะมี `/activate` `/renew` `/redeem`
  ตาม contract ที่ v2 นิยาม (ระหว่างนั้น lease renew ยังทำไม่ได้ → license ที่ออกช่วงนี้ต้องเป็น
  offline mode ไม่มี lease หรือ lease ยาวพิเศษ — **ต้องเลือกก่อนออก license จริงตัวแรก**)
- (assumed) **SMW110 DLMS-over-serial อยู่ในเป้า 5 วัน** — เป็นรุ่น DLMS จึงจัดอยู่เฟสแรก
  แต่ถ้าการต่อ serial จริงช้ากว่าแผน ให้เลื่อนไปกับเฟส modbus ได้โดยไม่กระทบรุ่น TCP
- **ชื่อ feature key `instantaneous`** — หน้าที่มันคุมถูกเปลี่ยนชื่อเป็น **Records** และย้ายไป M5
  (grill M3) แต่ key ยังชื่อเดิมตาม v1 · CONTEXT.md บังคับให้ใช้คำเดียวกันทุกชั้น ⇒ ควรเปลี่ยนเป็น
  `records` หรือไม่ — เป็นการแก้ contract กับ portal ที่ v2 เป็นผู้นิยาม (§3.9) จึงเปลี่ยนได้ฟรี
  **ตราบใดที่ยังไม่มี license ตัวไหนระบุ `features`** · ต้องตัดสินก่อน M5 และก่อนออก license
  ที่ใส่ features จริงตัวแรก
