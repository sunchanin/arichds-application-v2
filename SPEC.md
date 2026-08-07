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
  — **เลิกใช้แล้วตาม ADR 0007 ทั้งย่อหน้า**: (issue #6, M3-3) หน้า monitor เป็นนั่งร้าน M1 ไม่ใช่หน้า
  product ถูกถอดพร้อม `GET /api/devices/{id}/readings/latest` เมื่อหน้า Devices เข้ามาแทน · v2 ไม่มี
  หน้าแสดงค่า live · **(issue #8, M3-4) ทั้ง "อ่าน instantaneous set" และ "เก็บ DB" ก็เลิกด้วย**:
  tick อ่าน register เดียวคือ Meter Serial เพื่อพิสูจน์ว่ามิเตอร์ตอบจริงแล้วทิ้งค่า **ไม่เขียนแถวใด ๆ** ·
  เก็บข้อความเดิมไว้เป็นประวัติของการตัดสินใจ ไม่ใช่ของที่ยังมีอยู่
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
  **แสดงเฉพาะรุ่นที่มี driver จริง** — M3 = `prometer100` เท่านั้น · **M4a (issue #9, 2026-08-07)
  เพิ่ม `smw110`** · อีก 7 รุ่นที่เหลือโผล่เมื่อ M4c ลง driver
- **ไม่มีรุ่น SIM อีกต่อไป** — ยกเลิกจาก M1: `simulated.py` ออกจาก driver registry / catalog / README
  เหลือเป็น fake driver ที่เทส monkeypatch เข้าไปเท่านั้น (เทสห้ามยิงมิเตอร์จริง)
- **device ที่สร้างก่อน M3**: migration **ไม่ลบอะไร** — แถวที่ `model` ไม่มี driver แล้ว (เช่น `sim` เก่า)
  ถูกตั้ง `enabled=0` และ `site_name` เติมค่า placeholder ส่วน `meter_serial` ปล่อยว่างไว้
  = "ยังไม่ยืนยันตัวตน" จนกว่าคนจะกด Update (ซึ่ง probe เสมอ) · โค้ดห้ามสมมติว่า serial ไม่มีวันว่าง
- transport: **TCP อย่างเดียวใน M3** — ช่อง Serial มาพร้อม SMW110W4 ที่ **M4a (issue #9, 2026-08-07)**:
  **5 ช่อง** — COM port / baud rate / data bits / parity / stop bits · **ไม่มีช่อง flow control**
  (แก้จากรายการเดิมที่เคยเขียนไว้ 6 ช่อง — the argv seam `-S` ที่ `GXSettings` แยกไม่มีที่ให้ flow
  control เลย และหน่วยจริงทั้งสองที่ไซต์ลูกค้าใช้ค่า default "ไม่มี flow control" อยู่แล้ว ดู
  `docs/meter-notes/smw110w4-scan.md`) · คอลัมน์ `transport` เป็น JSON อยู่แล้วจึงไม่ต้อง migrate ตอน
  เพิ่มจริง (พิสูจน์แล้วที่ M4a) · **ไม่มีช่อง Source (dlms/modbus) ใน M3/M4a** — modbus มาหลังวันที่ 5
- auth: `password` + `block_cipher_key` + `authentication_key` ครบตั้งแต่ M3 (M3 ใช้แค่ password
  แต่ M4 ต้องใช้ทั้งสาม จึงไม่ต้องกลับมาแก้ model/ฟอร์ม/API รอบสอง) · สร้างใหม่ prefill password ด้วย
  `fixed_password` ของยี่ห้อ (CEWE = `ABCD0001`) · **ตอนแก้ เว้นว่าง = คงรหัสเดิม** (พฤติกรรม v1)
  — **ช่องกรอก 2 คีย์เลื่อนไป M4c** (issue #6 เลื่อนมา M4 · เลื่อนต่อ 2026-08-07): คอลัมน์กับ API
  พร้อมแล้วตั้งแต่ M3 แต่ฟอร์มมีแค่ IP / Port / Password เพราะยังไม่มีรุ่นที่ auth ด้วยคีย์ให้ทดสอบ ·
  ฟอร์มไม่ส่ง 2 ฟิลด์นี้ไปเลย และ API ถือว่า "ไม่ส่ง = คงของเดิม" ดังนั้น Update ลบคีย์ที่เก็บไว้ไม่ได้
  — **เหตุผลที่เลื่อนต่อ**: รุ่นเดียวที่ใช้คีย์คือ SMART TCC ซึ่งย้ายไป M4c แล้ว ส่วน SMW110W4 ของ M4a
  ใช้ auth Low + password ธรรมดา ⇒ ถ้าทำที่ M4a จะได้ช่องที่ไม่มีรุ่นไหนใช้และทดสอบไม่ได้
  — ⚠️ **และต้องตัดสินอีกครั้งตอน M4c ว่าจะทำจริงไหม**: v1 `smart_tcc.py` เก็บคีย์ TCC เป็น
  **module constant ในไดรเวอร์ ไม่ได้เก็บต่อ device** (ลูกค้ายืนยันว่าทุกเครื่อง TCC ใช้ชุดเดียวกัน)
  และไดรเวอร์ *"absorbs and ignores"* คีย์ที่ส่งมาจากฟอร์ม ⇒ เป็นไปได้ว่าสองช่องนี้ไม่ต้องมีเลย
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
  v2 ตัดทิ้งทั้งชุด: poller คุยกับมิเตอร์ทุก 60 วิอยู่แล้ว **ผลของ tick นั้นคือสัญญาณสถานะ** —
  ไม่เปิด connection ซ้ำไปที่มิเตอร์ และไม่มี job เพิ่มใน registry
- **tick อ่าน register เดียว: Meter Serial แล้วทิ้ง** (ADR 0007, issue #8) — seam เดียวกับ probe
  (ADR 0005) · การต่อเฉย ๆ ไม่พอ มิเตอร์ที่รับ association ได้แต่ตอบ register ไม่ได้จะขึ้น Online
  ทั้งที่ใช้งานไม่ได้ · ตอบกลับว่าง (serial = null) ก็นับเป็น **ล้มเหลว** ด้วยเหตุผลเดียวกัน ·
  **tick ไม่เขียนแถวลง `load_profile_readings` เลย** — สิ่งที่กฎ 3 ครั้งติดต้องการคือ *ผล* ไม่ใช่ *ค่า*
- 4 สถานะ: **Online · Offline · Paused · Unknown** — ไม่มี `Error` แยก (อ่านไม่สำเร็จคืออ่านไม่สำเร็จ
  สาเหตุอยู่ใน `detail`) · `Unknown` = ยังไม่มี tick หลัง Resume
- **Offline เมื่อพลาด 3 tick ติด** (~3 นาที) — กันสถานะกระพริบจาก timeout ชั่วคราว
- สร้างสำเร็จ = **Online ทันที** (probe เพิ่งต่อติดไปเมื่อกี้ ไม่ต้องรอ 60 วิ) · Resume = **Unknown**
  จนกว่า tick แรก (ระหว่าง pause ไม่มีใครคุยกับมิเตอร์ จึงไม่มีใครรู้ว่ามันยังอยู่ไหม)
- cadence **คงที่ 60 วิ ตั้งค่าไม่ได้** (env override ไว้แก้ปัญหาเท่านั้น) — ไม่มีคอลัมน์ `poll_interval_sec`

**`device_events` — เก็บเฉพาะตอนเปลี่ยน**:
- status transition (Online↔Offline) + การกระทำของคน (created / updated / paused / resumed /
  data cleared) พร้อมชื่อผู้สั่ง — **ไม่ใช่ heartbeat ทุก tick แบบ v1** (30 มิเตอร์ × 288 ครั้ง/วัน
  ≈ 8,600 แถว/วัน จะกลายเป็นตารางที่ใหญ่ที่สุดรองจาก `load_profile_readings` โดยไม่มีใครอ่าน)
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

**Read now — คืน "รายการ job" ไม่ใช่ค่าที่วัดได้ (M3-2, ADR 0007)**:
- M3 มี job เดียวชื่อ **`liveness`** = อ่านตัวตน (Meter Serial) หนึ่งรอบเพื่อพิสูจน์ว่ามิเตอร์ตอบ
  register จริง — ต่อ association เดียว อ่าน แล้วตัด · **ไม่เขียน Interval Reading** และ
  **ไม่ re-identify** (serial ที่ได้ทิ้ง ไม่ใส่ใน detail) เพราะเรื่อง serial ไม่ตรงเป็นหน้าที่ของ Update (ADR 0005)
- response เป็น **list** `{results: [{job, ok, detail}], status, checked_at}` — M5 เติม
  `load_profile` และ M6 เติม `billing` เข้า list เดิมโดยไม่ต้องแก้สัญญา (หลาย job สำเร็จบางส่วนได้
  ซึ่ง HTTP status เดียวบอกไม่ได้) · ตอบ **200 เสมอ** มิเตอร์ปฏิเสธ = `results[].ok = false`
  ตามแบบ Test connection
- **ห้ามมีค่าไฟฟ้าหลุดออกทางนี้เด็ดขาด** (ADR 0007 — v2 ไม่มีหน้าแสดงค่า live) · `detail` คือประโยค
  สำหรับคนอ่าน ไม่ใช่ค่าที่วัดได้ · Read now ที่ล้มนับเป็น 1 strike ตามกฎ 3 ครั้งติด เหมือน tick ปกติ

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
  **Delete all data** (ลบเฉพาะ `load_profile_readings` ของ device นั้น เก็บ `device_events` ไว้เป็น
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
  Mitsubishi SMW110 (**DLMS ทั้ง serial และ TCP** + Modbus) · SMART TCC st3c / st3cl / st33tl / st3tl / st3dh
- **เฟสแรก (ภายในวันที่ 5): SMW110W4 รุ่นเดียว เดินทะลุถึง billing** — รุ่นที่เหลือทั้งหมด
  (รวม Prometer100) ย้ายไป **M4c หลัง M6 จบ** (เจ้าของตัดสิน 2026-08-07 — เจาะลึกก่อนขยายกว้าง
  เพราะ SMW110W4 เป็นรุ่นเดียวที่มีข้อมูลภาคสนามครบทั้งเส้น ดู `docs/meter-notes/smw110w4-scan.md`)
  · เส้นทาง Modbus (พอร์ตจาก Go) ตามมาหลังวันที่ 5 — mapping modbus→COSEM ใช้ของ ADR 0005 (v1)
  ระหว่างรอลูกค้ายืนยัน
- **transport เป็นคุณสมบัติของการติดตั้ง ไม่ใช่ของรุ่น** — พิสูจน์ 2026-08-07: ไซต์ลูกค้ามี SMW110W4
  สองเครื่อง เครื่องหนึ่งต่อ COM port อีกเครื่องต่อ TCP ⇒ `catalog.py` ต้องเลิกผูก
  `supports_serial` / `default_port` ไว้กับรุ่น — **ทำแล้วที่ M4a (issue #9, 2026-08-07)**: ทั้งสองฟิลด์
  ตัดออกจาก `ModelSpec`/`CatalogEntry` จริง ทุกรุ่นในแคตตาล็อกเสนอทั้งสอง transport ให้คนเลือกต่อ device
- **client address ของ SMW110W4 = 6** (ไม่ใช่ 5 ที่ v1 ฮาร์ดโค้ด) — ถือเป็นค่าคงที่ของรุ่นไปก่อน
  (เจ้าของตัดสิน 2026-08-07) ทั้งสองเครื่องที่ไซต์ใช้ค่านี้ · ถ้าไซต์ไหนตอบที่ค่าอื่นให้กลับมาทบทวน
- ทุก driver เขียนลง `load_profile_readings` ตารางเดียว หน้าตา COSEM (แปลงตอนเขียน):
  **UTC เสมอ · kWh เสมอ · ชื่อคอลัมน์ตรงหน่วยจริง** (normalization contract — REMAKE-PLAN §6.1)
- Lock ต่อ **transport endpoint** (TCP: host:port · Serial: ชื่อ COM port) — อุปกรณ์บนสายเดียวกัน
  เข้าคิวกัน · manual read มี priority เหนือ background (ADR 0020 ของ v1) — **ทำไปแล้วที่ M3**
  (ADR 0006 ของ v2) เพราะ Read now / Test connection / probe เกิดขึ้นตั้งแต่ M3
- Scaler: เขียนให้ถูกต้องตั้งแต่ต้น โดยล็อกด้วย test case จากค่าที่ลูกค้ายืนยันแล้ว
  (ไม่ยกพฤติกรรม phantom ×10 ของ ADR 0010 มา แต่ผลลัพธ์สุดท้ายต้องตรง v1)
- **SMW110W4 อ่าน load profile (Logger 1) ได้แล้วที่ M4a-2 (issue #10, 2026-08-07)**:
  `Smw110Driver.read_load_profile()` อ่านผ่าน `readRowsByEntry` เท่านั้น (เมิเตอร์ปฏิเสธ
  `readRowsByRange`) คืนแถวเป็น UTC + kWh ผ่านมิเตอร์จริง 8 คอลัมน์ (ตัด 12 คอลัมน์ที่ยังไม่รู้
  ความหมายทิ้ง) — ยังไม่มีตาราง/scheduled job/หน้าเว็บ (ของ M5 ดูด้านล่าง)

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
- **Records** (ย้ายมาจาก M3 — grill M3 2026-08-05): ตารางตรวจความครบของข้อมูล แถว = มิเตอร์
  คอลัมน์ = วันที่ ช่อง = จำนวน interval ที่เก็บได้วันนั้น (ขาด = `N (-X)`, ไม่มีเลย = `0 (Missing)`)
  — v1 เรียกหน้านี้ว่า **Instantaneous Records** (เมนู "Records") แต่เป็นหน้าเปล่า:
  `DATES`/`DEVICE_ROWS` hardcode ว่าง ไม่มี API call และ worker ไม่มี endpoint รองรับ
  ⇒ v2 เป็นผู้เขียนหน้านี้ครั้งแรก และต้องมี load profile ก่อนจึงจะมีอะไรให้นับ จึงอยู่ที่ M5 ไม่ใช่ M3

#### ผลการ grill M5 (2026-08-07) — เคาะแล้ว 10 ข้อ

**เฟส** — M5 แตกเป็นสามใบตามบันไดโมดูล แต่ละเฟสมี gate ของตัวเอง:

| เฟส | เนื้องาน | Exit |
|---|---|---|
| **M5a** | migration · scheduler thread + job registry · LP job | replay parity จาก buffer ที่บันทึกไว้ **+ probe ยืนยันบนมิเตอร์จริง** |
| **M5b** | หน้า Load Profile (**ดูอย่างเดียว**) · หน้า Records · ปุ่มดึงย้อนหลัง | เลขบนจอตรงกับในตาราง |
| **M5c** | retention · backup รายวัน | job รันจริง ลบ/สำรองถูกต้อง |

**Exit ของ M5 ไม่ใช่ parity เทียบ v1** — `cewe/cewe-worker/src/drivers/smw110.py:119` ฮาร์ดโค้ด
client address 5 ส่วน SMW110W4 ทั้งสองเครื่องตอบเฉพาะ **6** ⇒ v1 ต่อมิเตอร์รุ่นนี้ไม่ติดเลย
ไม่มี output ของ v1 ให้เทียบ **parity ย้ายไปเป็น exit ของ M4c** ซึ่ง CEWE ทั้งสามรุ่นเดินจริงและ v1 อ่านได้
(และ CT ratio ยังไม่รู้ ⇒ parity ของพลังงานสัมบูรณ์อ้างไม่ได้อยู่ดี)

**สคีมา** — `load_profile_readings` เพิ่ม `logger_id` (int, not null, **ผูกกับ OBIS**:
`1.0.99.1.0.255`→`1`, `1.0.99.2.0.255`→`2` — อ่านจากมิเตอร์ ไม่ใช่จากลำดับที่เจอ ตามหลัก ADR 0005)
· เปลี่ยน `interval` (String) เป็น **`interval_sec` (int)** เก็บวินาทีจาก attr 4 ตรง ๆ ไม่แปลงเป็น label
(คอลัมน์เดิมไม่มีผู้ใช้ในโค้ดเลยและตารางว่าง ⇒ เปลี่ยนตอนนี้ฟรี) · unique key = `(device_id, logger_id, read_at)`
· **`NULL` ใช้ไม่ได้กับ `logger_id`** เพราะ SQLite ถือว่า `NULL != NULL` ⇒ unique key จะไม่กันซ้ำ

**การอ่าน** — แถวที่มีอยู่แล้ว **upsert ทับด้วยค่าใหม่** (ตาม v1 `INV-LP-01`) · watermark = `MAX(read_at)`
ต่อ (device, logger) **ไม่มีตาราง job** (ADR 0008) · backfill ตั้งต้น **90 วัน** หั่นเป็นก้อน **24 ชม.** ที่ตัว job
(ไม่ใช่ที่ driver — `read_load_profile()` ยิง `readRowsByEntry` ครั้งเดียวเสมอ) · **เดินจากเก่าไปใหม่เท่านั้น**
มิเตอร์ที่เพิ่งเพิ่มจึงเห็นข้อมูลเก่าก่อนและข้อมูลวันนี้มาถึงเป็นอันสุดท้าย — ยอมรับแล้ว เหตุผลใน ADR 0008

**scheduler** — เธรดเดียว รัน job ตาม registry `[(name, interval, fn)]` · LP job เดิน device
**แบบ sequential ตาม v1** และ **ข้าม device ที่สถานะ Offline** เพื่อไม่ให้มิเตอร์ตายกิน read timeout 60 วิ
ต่อรอบ (poller ยัง tick มันอยู่ตาม ADR 0004 มันจึงกลับมา Online ได้เอง แล้ว watermark ดึงช่วงที่ขาดให้)

**scheduler (ต่อ)** — LP job ลงทะเบียนที่ **900 วิ** ตาม v1 (`LP_READ_INTERVAL_SEC`)
⚠️ **เป็นสมมติฐาน ไม่ใช่ตัวเลขที่วัดแล้ว** — เรายังไม่รู้ว่าอ่าน LP หนึ่ง device ใช้เวลาเท่าไหร่จริง
ถ้าไซต์ไหนรอบเกิน 900 วิ ระบบไม่พัง (watermark กันไว้) แต่ job อื่นในเธรดเดียวกันจะไม่ได้คิว
ตัวลดความเสี่ยงที่มีแล้วคือการข้าม Offline · ถ้าจะเคาะด้วยตัวเลขจริง ให้ใส่การจับเวลาลง probe แล้ววัด
· job ตัวหนึ่ง exception ต้องไม่ฆ่าเธรด — ลอกแบบจาก `poller.py:351` (*"a worker must never die on
one bad tick"* พร้อม guard ซ้อนใน handler)

**capability** — job รู้ว่า driver ไหนอ่าน LP ได้ผ่าน **`MeterDriver.supports_load_profile()`**
(ค่าตั้งต้น `False`, `Smw110Driver` override เป็น `True`) ตาม invariant ของ `CLAUDE.md`
ที่ว่าความต่างระหว่างรุ่นอยู่หลัง capability method **ห้าม `hasattr` และห้ามธงใน catalog**
— `hasattr` ทำให้ driver ที่*ลืม*ใส่เมธอดกับที่*ตั้งใจ*ไม่มี หน้าตาเหมือนกันและพลาดแบบเงียบ
ส่วน catalog เพิ่งถอด `supports_serial` ออกไปด้วยเหตุผลว่าไม่ควรตัดสินพฤติกรรม driver (#9)
· **LP job ห้ามแตะสถานะ device** — ADR 0004 ให้สถานะมาจาก poller ทางเดียว การอ่าน LP ที่ล้ม
เป็นเรื่องของ log และจะปรากฏบนหน้า Records เป็นช่องว่างอยู่แล้ว

**Records** — "ครบวัน" คำนวณจาก **capture period จริงต่อ logger** ไม่ใช่ค่าคงที่ 96
(96 = 86400÷900 ซึ่งขัดกับข้อ "ห้ามสมมติ 900 วิ" ข้างบน — และผิดจริงกับ Prometer 100 Logger 2
ที่เป็น **300 วิ ⇒ ครบวัน = 288**) · **คำนวณสดด้วย `GROUP BY device_id, date(read_at)`
ไม่มีตาราง materialize** — หน้าที่เดียวของหน้านี้คือบอกว่าข้อมูลครบไหม การอ่านจากสำเนาที่อาจไม่ตรง
กับต้นฉบับทำลายเหตุผลที่มันมีอยู่ (v1 มี `records_96` แต่เป็นคนละอย่าง — กางค่าเป็น 96 slot ต่อวัน
และฮาร์ดโค้ด 96 ไว้ในชื่อตาราง) · ปริมาณจริง 90 วัน × 30 มิเตอร์ × 96 ≈ 259k แถว บน index
`(device_id, read_at)` ที่มีอยู่แล้ว · **คาบเปลี่ยนกลางวัน**: คาดหวังตามคาบที่พบมากที่สุดของวันนั้น
และถ้าวันไหนมีมากกว่าหนึ่งคาบ ให้ทำเครื่องหมาย *คาบเปลี่ยน* แทนการรายงานว่าขาด — ข้อมูลไม่ได้ขาด แค่ถี่ต่างกัน

**คอลัมน์วัดค่า — ขยายเป็น 12 ตัวที่ M5a** (เดิม 8) เพิ่ม `import_reactive_kvarh` ·
`export_active_kwh` · `export_reactive_kvarh` · `avg_geo_pf` ⇒ ครบชุดที่ **หน้า Load Profile ของ v1
แสดงให้ลูกค้าเห็นจริง** (`cewe-fe/src/pages/LoadProfile/index.tsx` — 14 คอลัมน์รวม Name/Date-Time)
เกณฑ์คือ *"v1 แสดงมันหรือเปล่า"* ไม่ใช่ *"COSEM มีอะไรบ้าง"* — v1 เก็บอีก ~14 คอลัมน์
(demand ทั้งสี่ทิศ · voltage L-L · phase angle · `record_status` · fundamental · reactive Q1–Q4)
ที่**ไม่มีหน้าจอไหนแสดง** ⇒ ยังบอกไม่ได้ว่าใครอ่าน จึงไม่มีสิทธิ์อยู่ (`REMAKE-PLAN:182`)

มีข้อมูลจริงรองรับ ไม่ใช่คอลัมน์ว่างถาวร: CEWE ทั้งสามรุ่นเก็บ `1.0.1/2/3/4.29.0.255`
(*active/reactive import & export energy, interval* — `load-profile-capture-objects.md:75`)
· PF: Prometer 100 มีทั้งรายเฟสและรวม (`1.0.13.24.0.255`) แต่ **Premier 550 Logger 2 มีเฉพาะรายเฟส**
⇒ `avg_geo_pf` ของรุ่นนั้นต้องคำนวณหรือปล่อยว่าง — **เคาะที่ M4c**
· ทั้งสี่คอลัมน์จะ **ว่างตลอด M5** เพราะ SMW110W4 ไม่ได้เก็บ — ยอมรับแล้ว เจ้าของคอลัมน์คือหน้าจอ v1 ที่ M4c
· `SPEC.md` §4 และ `REMAKE-PLAN:294` ที่เขียนว่า *"COSEM ~24 คอลัมน์"* **ไม่ตรงกับของจริง** — แก้เป็น 12
· รายการที่ `load-profile-capture-objects.md:91-93` ฝากให้ *"decide at M5"* (Saral 305:
`1.0.149.4.0.255` · `1.0.16.29.0.255` ที่ v1 อ่านแล้วทิ้ง) **ย้ายไป M4c ตามรุ่น**

**CSV export — ย้ายจาก M5c ไป M7 ทั้งก้อน** เพราะ **รูปแบบไฟล์ของมันเป็นค่าที่ผู้ใช้ตั้งได้**
(v1 เก็บ `csv_filename_tmpl` ใน settings + API `get_export_format`/`put_export_format` ที่
`settings/router.py:139,159`) และ **หน้า Export Format อยู่ที่ M7 อยู่แล้ว** (§3.7) — ฟีเจอร์ควรอยู่กับ
หน้าตั้งค่าของมัน ถ้าแยกกันจะได้ M5c ที่ฮาร์ดโค้ดรูปแบบแล้วต้องรื้อที่ M7 หรือได้ settings ที่ไม่มีใครแก้ได้
ผลพลอยได้: **M5c เหลืองานเบื้องหลังล้วนที่ไม่ต้องมี UI** และ **M5b จบในตัว ไม่มีปุ่มค้างรอเฟสหลัง**
⚠️ ต้นทุน: **ลูกค้าไม่มี CSV export จนถึง M7**

การตัดสินใจด้านล่างยังใช้ได้ แค่ไปเกิดที่ M7 — รวมถึงคอลัมน์ `csv_exported_through`
ที่**ไม่ต้องอยู่ใน migration ของ M5a อีกต่อไป**:

**CSV export (M7)** — ไฟล์ต่อมิเตอร์ เขียนต่อท้าย · UTF-8 BOM (Excel บนวินโดวส์) ·
`flush()` + `fsync()` แล้วค่อย commit watermark ⇒ เขียนพลาด watermark ไม่ขยับ แถวลองใหม่รอบหน้า ·
lock ต่อ device ให้ scheduler กับ Manual Read ไม่เขียนชนกัน · watermark เป็น **คอลัมน์
`csv_exported_through` บน `devices`** (แบบเดียวกับ `status_checked_at` — **ไม่เพิ่มตาราง คง 12**)
· **ไม่ merge logger และไม่มี logger-2 skew cap** — เลื่อนไป M4c พร้อมรุ่นที่มีสอง logger จริง
⚠️ ตอน M4c ต้องเคาะว่า CSV เป็นไฟล์ละ logger หรือไฟล์เดียวมีคอลัมน์ logger **ถ้าออกมาเป็นต่อ
(device, logger) คอลัมน์เดี่ยวจะไม่พอและต้องกลายเป็นตาราง**
> watermark ตัวนี้ **ไม่ขัด ADR 0008** — ADR นั้นห้าม marker ที่รายงานเกินจริงแล้วทำให้**ข้อมูลหายถาวร**
> ส่วนตัวนี้ถ้าเพี้ยน แถวหายจากไฟล์ CSV แต่ยังอยู่ในฐาน กู้ได้เสมอ

> 🔧 **`SPEC.md` §4 บรรทัด `devices` เขียนผิด** — บอกว่ารวม settings/status เป็น **JSON columns**
> แต่โค้ดจริงเก็บ `status` · `status_detail` · `status_checked_at` · ตัวนับ strike เป็น**คอลัมน์มีชนิด**
> (มีแค่ `transport` ที่เป็น JSON) ⇒ แก้ตอนทำ M5a

- CSV auto-export → **ย้ายไป M7** (ดูเหตุผลด้านล่าง) · manual read-now → **M5b**
- Retention (ตัวเลขเดิม v1) — job รายวัน → **M5c** (เคาะที่ grill M5):
  **ครอบเท่าที่มีตารางจริงตอน M5c** = `load_profile_readings` (**90 วัน**, ตัดตาม `read_at`)
  และ `device_events` (**90 วัน**, ตัดตาม `created_at`) · billing 365 วันเป็นของ **M6** ·
  `user_tokens` **ไม่ต้องมี** — `auth/service.py:162` เรียก `purge_expired_tokens()` ตอน login แล้ว
  · LP 90 วันเข้าคู่กับ backfill 90 วันพอดี: ดึงมาเท่าที่ตั้งใจเก็บ แล้ว retention ตัดหางไปเรื่อย ๆ
  · ลบ `device_events` **ทุกแถวเท่ากันหมด ไม่แยก `actor`** — เจ้าของงานเลือกความเรียบง่าย
  โดยรู้ตัวว่า **ร่องรอยการกระทำของคน (ใครสั่ง pause / clear data เมื่อไหร่) หายไปด้วยหลัง 90 วัน**
  ถ้าวันหนึ่งต้องตอบคำถามย้อนหลังเกินนั้น ต้องกลับมาทบทวนข้อนี้
  · **retention ห้ามขยับ watermark** — มันลบแถวเก่า ส่วน watermark คือ `MAX(read_at)` ซึ่งเป็นแถวใหม่สุด
  จึงไม่กระทบกัน และถ้าลบจนหมด (device ออฟไลน์เกิน 90 วัน) `MAX` เป็น `NULL` ⇒ กลับไป backfill
  90 วันใหม่เมื่อมันกลับมา ซึ่งถูกต้อง
- Backup อัตโนมัติรายวัน → **M5c** (เคาะที่ grill M5):
  `VACUUM INTO` · ปลายทางตั้งต้น **`%ProgramData%\ARICHDS\backup\`** และ **ตั้งค่าปลายทางได้**
  (backup ที่อยู่ดิสก์เดียวกับต้นฉบับกันได้แค่ "ลบผิด/ข้อมูลเสีย" **กันดิสก์พังไม่ได้**) ·
  **เก็บ 7 ชุด** หมุนเวียนลบ · **ทุก 24 ชม. นับจากบริการเริ่ม** (เข้ากับ registry ตรง ๆ
  ไม่ต้องเพิ่มตรรกะเวลานาฬิกา) · **เขียนเป็น `.tmp` แล้ว rename เมื่อสำเร็จ** — `VACUUM INTO`
  กินพื้นที่เท่าฐานทั้งก้อนชั่วคราว ถ้าดิสก์เต็มกลางทางจะได้ไฟล์ที่ไม่สมบูรณ์ และไฟล์ backup
  ที่พังแต่ดูเหมือนใช้ได้ แย่กว่าไม่มี backup
- หน้า: Load Profile · Records → **M5b**

**หน้า Load Profile (M5b) = ดูอย่างเดียว** — ตัวกรอง (group · brand · model · device) · ช่วงวันที่ ·
ตารางแบ่งหน้า **ฝั่งเซิร์ฟเวอร์เสมอ** · ปุ่ม **Read now** เท่านั้น
· **ช่วงวันที่บังคับ ตั้งต้นเป็นวันนี้** — v1 ปล่อยให้ว่างแล้วแปลว่า *ดึงทั้งหมด* ซึ่งที่ 90 วัน × 96
= 8,640 แถว/มิเตอร์ และถ้าเลือกทุกมิเตอร์คือ ~259,000 แถวยิงเข้าเบราว์เซอร์
· **ไม่พอร์ต `resolution`** ที่ v1 มีในพารามิเตอร์ query — ยังบอกไม่ได้ว่าใครใช้ (`REMAKE-PLAN:182`)
· ปุ่ม **Save CSV now** · สวิตช์ **auto-save** · ช่องเลือกโฟลเดอร์ → **ไปพร้อม CSV ที่ M7**

### 3.6 Billing (M6)

- Open period = upsert slot เดียวต่อ device (ADR 0018) · ปิดงวดตาม reset-reason / driver capability
- Backfill ประวัติจากมิเตอร์ · manual read · auto-read ตามเวลา (job ใน registry)
- Capture PDF/xlsx ลง filesystem (ตาม v1) — gated ด้วย feature `auto_capture` / `billing_excel_export`
- Modbus billing cut (ระบบตัดบิลแทนมิเตอร์ที่ตัดเองไม่ได้) — **เขียน ADR ใหม่** อ่านจาก
  `load_profile_readings` (กฎธุรกิจเดิมของ ADR 0019: ตัดที่ 00:00 ของวันบิล, catch-up, idempotent) —
  มากับเฟส modbus หลังวันที่ 5
- หน้า: Billing

### 3.7 โมดูลเบา (M7)

- Energy Summary (TOU buckets — ADR 0016) · Holidays (2 ชนิด) · Special Days · Battery status ·
  Export format settings · App Log (log viewer — log ผ่าน credential redaction filter เสมอ)
- **CSV auto-export ของ Load Profile (ย้ายมาจาก M5c ที่ grill M5 2026-08-07)** — มาพร้อมกันกับ
  หน้า ExportFormat ที่เป็นเจ้าของรูปแบบไฟล์: job เขียนต่อท้ายไฟล์ต่อมิเตอร์ · ปุ่ม **Save CSV now**
  · สวิตช์ **auto-save** ต่อมิเตอร์ · ช่องเลือกโฟลเดอร์ปลายทาง — ทั้งสามอย่างอยู่บนหน้า Load Profile
  ที่ M5b สร้างไว้แล้ว · รายละเอียดที่เคาะแล้ว (watermark, BOM, fsync, lock ต่อ device) อยู่ใน §3.5
- หน้า: EnergySummary · Holidays · SpecialDays · Battery · ExportFormat · AppLog
- **นับหน้าครบที่นี่**: 14 หน้า v1 → 12 หน้ามีเจ้าของใน M2–M7 + DatabaseSettings ถูกลบ (SQLite)
  + ApiConfig ถูกแทนด้วย push (M8)
- **หน้า monitor ไม่เคยอยู่ในบัญชีนี้** — มันเป็นนั่งร้าน M1 ที่ §3.1 สร้างขึ้นเอง ไม่ใช่หน้าของ v1
  ถูกถอดที่ M3-3 (ADR 0007) · ตัวเลข 14 → 12 จึงไม่ขยับเพราะเรื่องนั้น

### 3.8 Data-out / Sync (M8)

- โปรแกรม **push** ขึ้น server เดิมของทีม (เพิ่ม endpoint รับ) — outbound HTTPS ทางเดียว
  ไม่เปิด inbound port ที่ไซต์
- ข้อมูลที่ส่ง: **billing · load profile · energy summary · รายชื่อมิเตอร์ + สถานะ online/offline**
- Contract: JSON · รอบ 15 นาที · JWT ผูกกับ activation (site identity = machine token จาก portal
  — เฟสนี้ฝังใน license/config ตอน activate แบบ offline)
- ทนเน็ตหลุด: watermark เลื่อนเมื่อ server ACK เท่านั้น · ส่งย้อนหลัง **ครบทุกแถวเสมอ** ·
  `load_profile_readings`/energy ใช้ watermark append-only · `billing_readings` track ด้วย `updated_at`
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
- **Data model** (12 ตาราง): `devices` (รวม settings/status/capture_objects เป็น JSON columns) ·
  `device_events` · `load_profile_readings` (COSEM shape 12 คอลัมน์วัดค่า + `source` + `interval_sec`) ·
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
