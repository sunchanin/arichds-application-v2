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
  (`arichds.db`, license, logs, `backup\`) — **capture ไม่อยู่ในนี้**: มันเป็นที่เดียวที่โปรแกรม
  เขียนไฟล์ออกนอก `%ProgramData%\ARICHDS` เพราะปลายทางเป็น `capture_dir` ที่ admin ตั้งเอง
  (ADR 0010, M6b issue #22)
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
  — ✅ **ปิดแล้วที่ grill M4c (2026-08-09): ไม่ทำช่องกรอก** · v1 `smart_tcc.py:80-81` เก็บคีย์ TCC
  เป็น **module constant ในไดรเวอร์ ไม่ได้เก็บต่อ device** และ `__init__` เขียนไว้เองว่า
  *"Absorbs the block_cipher_key/authentication_key kwargs … these are ignored"* · คีย์ทั้งสอง
  คือ **ค่า default ของ DLMS Blue Book** (`D0D1D2…DF` / `000102…0F`) ที่มิเตอร์ยังใช้จากโรงงาน
  ⇒ ช่องกรอกจะไม่มีรุ่นไหนอ่านมันเลย ซึ่งเป็นเหตุผลเดียวกับที่ M4a เลื่อนมันมา · **คอลัมน์ DB
  ยังอยู่** วันที่มีไซต์หมุนคีย์จริง เพิ่มช่องบนฟอร์มเป็นงานเล็ก · ผลข้างเคียงที่รู้ตัว: การเข้ารหัส
  ของ TCC ยืนบนคีย์โรงงาน — แต่เราเป็นผู้อ่านอย่างเดียวและ invariant ห้ามเราแตะค่าบนมิเตอร์อยู่แล้ว
- billing: `first_bill_date` + `bill_day_feb28/29/30/31` — **ช่องบันทึกค่าล้วน ๆ เหมือน `site_code` /
  `customer` / `meter_number` ข้างบน: ห้ามประดิษฐ์พฤติกรรมให้** (เจ้าของยืนยัน grill M6, 2026-08-09) ·
  บรรทัดเดิมเขียนว่า *"ตรรกะการตัดงวดอยู่ M6"* ซึ่งผิด — ฝั่ง DLMS **มิเตอร์เป็นเจ้าของการตัดรอบเอง**
  (v1 ADR 0002) และของเดียวที่เคยอ่านห้าช่องนี้คือ modbus billing cut ซึ่งอยู่ **M4b** ·
  ชะตาของ modbus cut ยังไม่ตัดสิน — ดู §5 คำถามค้าง

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
  ความหมายทิ้ง) — **ตารางมีแล้วที่ M5a-1 (issue #15, 2026-08-07)**: Read now เขียนลง
  `load_profile_readings` จริง (migration 0006 + `acquisition/load_profile.py`) ·
  **scheduler thread + job registry มาแล้วที่ M5a-2 (issue #16)**: `jobs/scheduler.py`
  รัน `load_profile_cycle` ทุก 900 วิ (ข้าม device ที่ Offline/ปิดใช้งาน) ·
  **หน้าเว็บมาแล้วทั้งสองหน้า**: Load Profile (M5b-1, issue #17 — `GET /api/load-profile`)
  และ Records (M5b-2, issue #18 — `GET /api/records`)

#### ผลการ grill M4c (2026-08-09) — เคาะแล้ว 14 ข้อ

> ✅ **c1 landed with issue #24 (2026-08-09)** — Prometer 100 / Saral 305 / Premier 550 อ่าน
> load profile และ billing ได้แล้วผ่าน `acquisition/drivers/_dlms_profile.py` (ตรรกะร่วม —
> เดิมชื่อ `_cewe.py`, เปลี่ยนชื่อที่ issue #25 หลังมีรุ่นที่สองมาแชร์คลาสนี้) และไดรเวอร์
> เฉพาะรุ่นสามไฟล์ · billing schema ขยายจาก 40 → 60 คอลัมน์วัด (Demand Time + Cumulative
> Demand, import ฝั่งเดียว) · load-profile watermark เป็นราย `(device, logger)` จริงแล้ว
> (ดู ADR 0008's amendment) · รอบแรกที่อ่านจริง มิเตอร์ปฏิเสธ `scaler_unit` ที่คอลัมน์ของตัวเอง
> ทั้ง load profile และ Cumulative Demand (แพทเทิร์นเดียวกับ SMW110W4) ⇒ **แก้ในรอบเดียวกัน**
> ด้วย sibling-fallback resolver (v1-proven route, `cewe-worker/_tcp_driver_base.py:861-873`
> สำหรับ Cumulative Demand) แล้วอ่านซ้ำยืนยัน: billing resolve 48/60 บน Prometer 100 และ
> Premier 550 (เหลือแต่ rate_d ที่ฟลีทนี้ไม่มี tariff ที่ 4 จริง ๆ), 22/60 บน Saral 305
> (ค่าที่วัดจริงของฮาร์ดแวร์รุ่นนี้ — F10 — ไม่เกี่ยวกับ scaler) · load profile resolve ค่าจริง
> ครบทุกคอลัมน์ที่แมปไว้ ยกเว้น `avg_geo_pf` หนึ่งคอลัมน์บน Prometer 100 (sibling ก็ถูกปฏิเสธ
> เช่นกัน — ยังคง NULL ตาม D12) — ดู `docs/meter-notes/cewe-billing-capture-objects.md`.
>
> ✅ **c2 landed with issue #25 (2026-08-09) — code + replay tests only, live read still open.**
> `SmartTccDriver` (`acquisition/drivers/smart_tcc.py`) รวมทั้งห้ารุ่น SMART TCC ไว้ในคลาสเดียว
> (`st3c`/`st3cl`/`st33tl`/`st3tl`/`st3dh` ในรีจิสทรี) สืบทอดจาก `DlmsProfileDriver` ตัวเดียวกับ
> CEWE — ใช้ตรรกะ billing/load-profile ร่วมกันทั้งหมด สี่จุดที่ต่างจาก CEWE (billing profile OBIS,
> รายชื่อคอลัมน์ bill date, คีย์ reset-reason, คลาส COSEM ของ Cumulative Demand) กลายเป็นค่าที่
> ไดรเวอร์แต่ละตัวประกาศเองแล้ว (D5) แทนที่จะเป็น module constant ตัวเดียวที่ CEWE ผูกขาด — CEWE
> ทั้งสามรุ่นพฤติกรรมไม่เปลี่ยนเลย (ตรวจด้วยชุดเทสเดิม) **เพราะมิเตอร์ตัวเดียวที่เข้าถึงได้ (test 3CL,
> `203.170.148.103`) ยังไม่ตอบ** (timeout ทั้ง 4059/50001 ตั้งแต่ 2026-07-18 ถึง 2026-08-09, F13) —
> จึงไม่มี "อ่านซ้ำยืนยัน" แบบ c1 ให้รายงาน สิ่งที่พิสูจน์ได้แทนคือการ replay ต่อ layout ที่บันทึกไว้จริง
> (`docs/meter-notes/tcc-obis-scan.md`, สแกนรอบ 4, 18 ก.ค. 2026): pin เลย์เอาต์ 35/148 คอลัมน์ที่
> สแกนได้, คอลัมน์ที่ driver แมปทุกตัวอยู่ในเลย์เอาต์นั้นจริง, และ replay ค่า max-demand สังเคราะห์
> ยืนยันว่าค่า (attr 2) กับเวลา (attr 5) บน OBIS เดียวกันลงคนละฟิลด์ถูกต้อง — **นี่คือการตีความ
> "replay parity" ใหม่ที่ D12 บันทึกไว้**: เกณฑ์เดิมของใบ issue ขอ "แถวจริงจากมิเตอร์" ซึ่งไม่มีอยู่
> (สแกนบันทึกแค่เลย์เอาต์ ไม่มีค่าแถว) จึงแยกเป็นสามส่วนที่พิสูจน์ได้จริงแทน · **ยังค้าง**: การอ่านสด
> ทั้งไดรเวอร์ (D1 — ห้ามต่อมิเตอร์เด็ดขาดในใบนี้), สี่รุ่นที่ยังไม่เคยสแกน (`st3c`/`st33tl`/`st3tl`/
> `st3dh`, D14 — สมมติว่าเหมือน 3CL เพราะ v1 ใช้ driver เดียวคุมทั้งห้า ไม่ใช่เพราะวัดจริง), และข้อจำกัด
> ของ `resolve_billing_multiplier`'s `D=2 -> D=6` fallback ที่ยังไม่ทดสอบกับคลาส COSEM ที่ต่างจาก CEWE
> (D6) · exit ของ c2 ยังเป็นไปตามตารางเดิม: ค้างจนกว่าจะได้ลิงก์ไปมิเตอร์จริง

**เฟส — M4c แตกตาม "ยิงมิเตอร์ถึงหรือไม่" ไม่ใช่ตามยี่ห้อ** เพราะ exit ของมันคือ parity ซึ่ง
ต้องมีมิเตอร์จริง:

| เฟส | รุ่น | สถานะลิงก์ (ทดสอบ TCP 2026-08-09) | Exit |
|---|---|---|---|
| **c1** | Prometer 100 `203.170.151.152:4059` · Saral 305 `203.170.151.217:4059` · **Premier 550 `49.229.159.44:50001`** | ✅ เปิดทั้งสาม (187 / 38 / 66 ms) | เทียบสด v1 vs v2 ที่ระดับแถว + แช่ buffer เป็น replay fixture |
| **c2** | SMART TCC ×5 `203.170.148.103` | ❌ **timeout ทั้ง 4059 และ 50001** (15 วิ / 8 วิ) — *timeout ไม่ใช่ refused* ⇒ แพ็กเก็ตหายทั้งหมด เป็นเรื่องลิงก์/ไฟร์วอลล์ ไม่ใช่พอร์ตปิด · ยืนยันซ้ำจาก 2026-08-07 | เขียน driver + เทสด้วย fixture จากสแกน · **exit ค้างไว้จนกว่าจะได้ลิงก์** |

> ✅ **Premier 550 ย้ายเข้า c1 (2026-08-09, เจ้าของให้ endpoint มา)** — และมันเปลี่ยนคุณค่าของเฟสนี้
> มากกว่าที่ตัวเลขบอก เพราะ **มันคือรุ่นเดียวที่พิสูจน์เคส 2 logger "เชิงค่า" ได้**:
> Logger 1 ของมันมีแต่พลังงานล้วน ส่วน **V L-N ×3 และ I ×3 อยู่ใน Logger 2 ทั้งหมด**
> ⇒ ทั้งการเก็บแยกแถวและการรวม logger ตอนส่งออก CSV มีเหตุผลอยู่ที่รุ่นนี้รุ่นเดียว
> · Prometer 100 ยังคงเป็นเคสที่ยากกว่าใน**เชิงคาบ** (900/300 ⇒ 96 กับ 288)
> ⇒ **c1 ได้ทั้งสองครึ่งของการพิสูจน์ 2 logger** ซึ่งเป็นสิ่งที่แผนก่อนหน้านี้ทำไม่ได้
>
> **พอร์ต 50001 ไม่ใช่ 4059** — ตอกย้ำว่า transport เป็นคุณสมบัติของการติดตั้ง ไม่ใช่ของรุ่น
> และยืนยันว่า lock ที่คีย์ด้วย `host:port` (ไม่ใช่ host เปล่า) ถูกต้องอยู่แล้ว

**เคส 2 logger พิสูจน์ครบทั้งสองครึ่งใน c1** — **Prometer 100 = ครึ่งเชิงคาบ** (Logger 1 = 900 วิ ·
Logger 2 = 300 วิ ⇒ ครบวัน 96 กับ 288 คนละเลข) · **Premier 550 = ครึ่งเชิงค่า** (Logger 1 มีแต่
พลังงาน · V/I อยู่ใน Logger 2 ทั้งหมด)

> ⚠️ **แต่มันพิสูจน์ "ท่อ" ไม่ใช่ "ค่า" — ต้องรู้ตัวตอนเขียนเกณฑ์รับรอง**
> Logger 2 ของ Prometer 100 มี 8 คอลัมน์: clock · แรงดัน **L-L** `1.0.157/177/197.27.0.255` ·
> ความถี่ `1.0.14.27.0.255` · และรหัสที่ไม่มีใน map ใด ๆ อีกสามตัว
> (`load-profile-capture-objects.md:102-107`) · เทียบกับ 12 คอลัมน์ของเราแล้ว **ตรงตัวเดียวคือ
> `freq` ซึ่ง Logger 1 มีอยู่แล้ว** ⇒ แถวของ Logger 2 จะมีค่าจริงช่องเดียว
>
> **ตัดสินแล้วว่าเก็บ** (เจ้าของ, grill M4c) — ตรงกับ v1 ที่แมปตาม OBIS แล้วปล่อยที่เหลือเป็น NULL
> จึงไม่มีข้อยกเว้นเรื่อง parity · และมันคือสิ่งเดียวที่ออกกำลังท่อครบเส้นจริง: แถวแยกตาม
> `logger_id` · watermark ต่อ logger · Records นับ 96 กับ 288 บนเครื่องเดียว
> **ราคาที่รู้ตัว**: 288 แถว/วัน/เครื่อง ≈ 26,000 แถวต่อเครื่องที่ retention 90 วัน โดยมีค่าช่องเดียว ·
> และหน้า Records จะรายงาน Logger 2 ว่าครบทุกวัน ทั้งที่ไม่มีค่าวัดอะไรเลย — **ถูกต้องตามนิยาม
> ของหน้านั้น** (มันนับ *ความครบของ interval* ไม่ใช่ความครบของค่า) แต่ต้องเขียนกำกับไว้

**เอกสารที่ผิดและแก้แล้ว**: `REMAKE-PLAN` เคยระบุว่า `tcc-obis-scan.md` (เปลี่ยนชื่อไฟล์ที่
issue #25/D13 — ก่อนหน้านั้นชื่อไฟล์มีคำว่า "-partial" ต่อท้าย ซึ่งไม่ตรงกับเนื้อหาแล้ว)
*"ไม่เคยเห็นกลุ่ม ProfileGeneric เลย"* — ไฟล์นั้นจบด้วย `## Result: SCAN COMPLETE` และมีผลสแกน
รอบ 4 (18 ก.ค. 2026) ที่อ่าน captureObjects ได้ทั้ง LP และ billing ครบ · ความเสี่ยงจริงของ TCC
คือ **ลิงก์** ไม่ใช่ข้อมูล และไฟล์นั้นสแกนรุ่น **test 3CL รุ่นเดียวจากห้ารุ่น** (v1 ใช้ driver
เดียวคุมทั้งห้า)

**คีย์ — ไม่ทำช่องกรอก** `block_cipher_key` / `authentication_key` บนฟอร์ม Device (ปิดคำถามที่
เลื่อนมาสามรอบ M3 → M4 → M4c) · รุ่นเดียวที่ auth ด้วยคีย์คือ SMART TCC และ v1 เก็บคีย์เป็น
**module constant ในไดรเวอร์** (`smart_tcc.py:80-81` — และเป็น**คีย์ default ของ DLMS Blue Book**
ที่มิเตอร์ยังใช้ค่าจากโรงงาน) โดย `__init__` เขียนไว้เองว่า *"absorbs … these are ignored"* ⇒
ช่องกรอกจะไม่มีรุ่นไหนอ่าน · **คอลัมน์ DB ยังอยู่** (`db/models.py:111-112`) วันที่มีไซต์หมุนคีย์
จริงค่อยเพิ่มช่องบนฟอร์ม

**Gurux ที่ vendored ไว้พอแล้ว** — `vendor/gurux/GXSettings.py` รองรับ `-v` (invocation counter)
`-A` `-B` `-T` อยู่แล้ว ⇒ HighGMac + Suite 0 ของ TCC **ไม่ต้องแตะไฟล์ vendored**

**อย่าลืมปลดล็อกแคตตาล็อก** — `SPEC.md` §3.3 กำหนดว่าดรอปดาวน์เลือกรุ่นแสดง **เฉพาะรุ่นที่มี
driver จริง** ⇒ ทุกใบของ M4c ต้องแตะ `acquisition/catalog.py` และ `drivers/factory.py` ด้วย
มิฉะนั้นไดรเวอร์จะมีอยู่แต่ไม่มีใครเลือกใช้ได้ (เส้นแบ่งระหว่าง "เขียนเสร็จ" กับ "ใช้งานได้")

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
- **Records** (ย้ายมาจาก M3 — grill M3 2026-08-05): ตารางตรวจความครบของข้อมูล
  **แถว = มิเตอร์ + logger** (ไม่ใช่มิเตอร์อย่างเดียว — Prometer 100 เดิน Logger 1 ที่ 900 วิ
  และ Logger 2 ที่ 300 วิ พร้อมกันบนเครื่องเดียว ⇒ แถวระดับมิเตอร์ไม่มี "ครบวัน" ค่าเดียวให้เทียบ)
  คอลัมน์ = วันที่ ช่อง = จำนวน interval ที่เก็บได้วันนั้น (ขาด = `N (-X)`, ไม่มีเลย = `0 (Missing)`,
  คาบเปลี่ยนกลางวัน = `N (period changed)`)
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

> 🐛 **แก้แล้ว 2026-08-11 — backfill เริ่มที่บัฟเฟอร์ของมิเตอร์ ไม่ใช่ที่ 90 วันเสมอไป**
> `_walk` **ไม่จำตำแหน่งที่หยุด** (ถูกต้องตาม ADR 0008: watermark คือข้อมูล) ซึ่งหายเองได้
> **เฉพาะเมื่อเดินถึงแถวแรกก่อนหมด budget** · TCC บนสายอนุกรม 9600 ที่มีบัฟเฟอร์ ~22 ชม.
> ต้องเดิน 90 ก้อนถึงจะเจอแถวแรก แต่ `LOAD_PROFILE_READ_BUDGET_SEC = 60` ซื้อได้ **18 ก้อน**
> (ก้อนเปล่าละ ~3.3 วิ) ⇒ ไม่มีอะไรถูกเก็บ ⇒ watermark ยัง `None` ⇒ **รอบหน้าเดินซ้ำที่เดิม**
> วัดจาก log เครื่องลูกค้า: 9 รอบติดกันหยุดที่ 30 พ.ค.–1 มิ.ย. เท่ากันหมด และ Read now ตอบ `0 rows`
> **แก้**: `MeterDriver.load_profile_oldest_reading(logger_id)` อ่าน entry 1 (แถวเก่าสุด) แล้ว
> `_backfill_start()` เอามาเป็นจุดตั้งต้นแทน — **ถามเฉพาะตอน backfill (ไม่มี watermark)** ⇒ สถานะ
> ปกติไม่มีต้นทุน · ไดรเวอร์ที่ตอบไม่ได้คืน `None` แล้วเดินเต็ม 90 วันเหมือนเดิม · คำตอบที่อยู่นอกช่วง
> (อนาคต / เก่ากว่า 90 วัน) ถูกทิ้ง เพื่อไม่ให้นาฬิกามิเตอร์ที่เพี้ยนย่นการเดินจนข้ามข้อมูล ·
> **ไม่ขัด ADR 0008** — ไม่มีสถานะ scheduler ถูกเก็บ แค่ถามมิเตอร์ว่ามีของตั้งแต่เมื่อไหร่

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
ที่เป็น **300 วิ ⇒ ครบวัน = 288**) · **คำนวณสดด้วย
`GROUP BY device_id, logger_id, date(read_at, ±offset), interval_sec`
ไม่มีตาราง materialize** — หน้าที่เดียวของหน้านี้คือบอกว่าข้อมูลครบไหม การอ่านจากสำเนาที่อาจไม่ตรง
กับต้นฉบับทำลายเหตุผลที่มันมีอยู่ (v1 มี `records_96` แต่เป็นคนละอย่าง — กางค่าเป็น 96 slot ต่อวัน
และฮาร์ดโค้ด 96 ไว้ในชื่อตาราง) · จัด group **ต่อ logger** เพราะถ้า group แค่ระดับ device
Prometer 100 จะเจอสองคาบทุกวันและถูกทำเครื่องหมาย *คาบเปลี่ยน* ตลอดไป ·
วันคือ**วันตามเวลาท้องถิ่นของผู้ใช้** — client ส่ง `utc_offset_minutes` (นาทีที่ **บวก** เข้ากับ UTC,
ICT = `+420`) มาให้ bucket เพราะทุก timestamp บนจอแสดงเป็นเวลาท้องถิ่นอยู่แล้ว ถ้า bucket ด้วยวัน UTC
ค่าที่อ่านได้ระหว่างเที่ยงคืน-07:00 จะไปโผล่คอลัมน์วันก่อนหน้า ⇒ ช่องที่ขาดจริงจะชี้ผิดวัน ·
ช่วงที่ขอได้ครั้งละไม่เกิน **31 วัน** (นับปลายทั้งสองข้าง) — 90 คอลัมน์ไม่ใช่ตารางที่คนอ่านไหว
และรายละเอียดเบื้องหลังช่องที่น่าสงสัยอยู่ที่หน้า Load Profile ·
ปริมาณจริง 90 วัน × 30 มิเตอร์ × 96 ≈ 259k แถว — **query นี้ไม่ได้วิ่งบน index `(device_id, read_at)`**
(ไม่มีเงื่อนไข `device_id =` และ `read_at` ไม่ใช่คอลัมน์นำของ index นั้น ⇒ seek ไม่ได้)
วัดจริงบนสคีมาจริงที่ 259,200 แถวได้ `SCAN … USING INDEX sqlite_autoindex_load_profile_readings_1`
+ `USE TEMP B-TREE FOR GROUP BY` คือ**สแกนทั้งตารางไม่ว่าจะขอช่วงกี่วัน** ~70 ms ต่อครั้ง
(1 วัน ~31 ms) ⇒ **รับได้ ไม่ต้องเพิ่ม index** เพราะหน้านี้โหลดตามคำสั่งคนเท่านั้น
ส่วนการเพิ่ม index จะไปเพิ่มต้นทุนเขียนบนเส้นทางเก็บข้อมูลทุกแถว ·
**คาบเปลี่ยนกลางวัน**: คาดหวังตามคาบที่พบมากที่สุดของวันนั้น
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

**✅ เคาะแล้วที่ grill M4c (2026-08-09) — สามข้อที่ §3.5 ฝากไว้ ปิดหมด**

- **`avg_geo_pf` ของ Premier 550 (และ Saral 305) = ปล่อยว่าง ไม่คำนวณ** ·
  `load_profile_reader.py:262-268` แสดงว่า v1 แมป `1.0.13.7/24/27/29` ลงคอลัมน์นี้และเขียนกำกับ
  เองว่า *"LoggerReading has no per-phase PF columns"* ⇒ **v1 อ่าน PF รายเฟสมาแล้วทิ้ง ไม่เคย
  คำนวณ total** และสองรุ่นนี้ไม่มี `1.0.13.x` เลย ⇒ คอลัมน์นี้เป็น NULL ใน v1 อยู่แล้ว
  การปล่อยว่างคือ parity พอดี ส่วนการคำนวณ (`kWh / √(kWh² + kvarh²)`) จะเป็นเลขที่เราประดิษฐ์
- **รีจิสเตอร์ส่วนเกินของ Saral 305 = ทิ้งเหมือน v1** — `1.0.9/10.29.0.255` (apparent kVAh
  import/export) · `1.0.16.29.0.255` (\|A+\|+\|A−\|) · `1.0.149.4.0.255` (ช่วงของผู้ผลิต
  ไม่รู้ความหมาย ⇒ ตั้งชื่อคอลัมน์ให้ไม่ได้ด้วยซ้ำ) · เกณฑ์เดิม "v1 แสดงมันหรือเปล่า"
- **พลังงานสะสม `1.0.1/2/3/4.8.0.255` ของ Premier 550 Logger 2 = ไม่ map** · v1 แมปมันลง
  คอลัมน์เดียวกับพลังงานช่วง (`load_profile_reader.py:208-209`) ซึ่งทำให้ความหมายของคอลัมน์
  ขึ้นกับว่าแถวมาจาก logger ไหน — เป็น branch ตามรุ่นที่ซ่อนอยู่ในข้อมูล และทำให้การบวกคอลัมน์
  ทั้งวัน (ซึ่งหน้า Records ทำ) ไม่มีความหมาย · **ไม่มีราคาเชิง parity**: หน้า Load Profile ของ v1
  ฮาร์ดโค้ด `DEFAULT_LOGGER_ID = 1` ทั้งสามจุด ⇒ ค่านี้ไม่เคยขึ้นจอ และ CSV ก็เอาพลังงานจาก
  Logger 1 ⇒ Logger 2 ของรุ่นนี้เหลือหน้าที่เดียวคือจ่าย **V L-N ×3 และ I ×3**

**✅ watermark เปลี่ยนเป็นต่อ `(device, logger)` — landed with issue #24 (2026-08-09).** ของเดิมคือ
**ค่าน้อยที่สุดของ MAX(read_at) รายกลุ่ม logger** (M5a D6) ซึ่ง `acquisition/load_profile.py`
ฝากคำเตือนไว้เองว่า *"the fix is a per-logger read interface — which must be designed against a
model that actually has two"* · รุ่นนั้นมาถึงแล้วที่ M4c: `MeterDriver.read_load_profile()` รับ
`logger_id`, `load_profile_loggers()` บอกว่ามี logger อะไรบ้าง, และ `_walk_every_logger()` เดิน
ทีละ logger ด้วยหน้าต่าง/watermark ของตัวเองในการเชื่อมต่อครั้งเดียว (budget เดียวใช้ร่วมกันทั้ง
เที่ยว แต่ chunk แรกของทุก logger ผ่านเสมอ) · **`_through()` ตัดสินแล้วว่าเป็น MIN ข้าม
per-logger watermark** (D4, ADR 0008's amendment) — ไม่ใช่ MAX ระดับ device ซึ่งจะรายงานความครบ
เกินจริงตอนมี logger ค้าง; ทุกรุ่นที่มี logger เดียวไม่เห็นความต่างเลยเพราะ MIN==MAX ในกรณีนั้น

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
· **✅ เคาะแล้วที่ grill M4c (2026-08-09): ลอก v1 — ไฟล์เดียวต่อมิเตอร์ รวม logger ตอนส่งออก**
พร้อม skew cap แบบ v1 (หน่วงแถว Logger 1 ไว้จนกว่า Logger 2 จะตามทัน + ทางหนีเมื่อ Logger 2
ล้าหลังเกินเพดาน) · เหตุผล: CSV เป็นไฟล์ที่ลูกค้าเปิดใช้อยู่แล้วที่ไซต์ การเปลี่ยนรูปแบบพังทุกอย่าง
ที่เขาต่อท้ายไว้กับมัน · และ **การ merge ตอนส่งออกไม่ขัดกฎที่ว่า DB ห้าม merge** — แถวในฐานยังแยก
ตาม `logger_id` เหมือนเดิม
⇒ **`csv_exported_through` คงเป็นคอลัมน์เดียวบน `devices` ได้ จำนวนตารางคง 11**
· การ merge มีความหมายกับ **Premier 550 รุ่นเดียว** เมื่อทาบกับ 12 คอลัมน์ของเรา: Logger 2 ของ
Prometer 100 มีแต่แรงดัน L-L (ไม่มีคอลัมน์) กับความถี่ที่ Logger 1 มีอยู่แล้ว ส่วน Saral 305
ไม่มี Logger 2 ⇒ ตรงกับ `HAS_SECONDARY_LOGGER = True` ที่ v1 ตั้งไว้บน Premier 550 รุ่นเดียวพอดี
> watermark ตัวนี้ **ไม่ขัด ADR 0008** — ADR นั้นห้าม marker ที่รายงานเกินจริงแล้วทำให้**ข้อมูลหายถาวร**
> ส่วนตัวนี้ถ้าเพี้ยน แถวหายจากไฟล์ CSV แต่ยังอยู่ในฐาน กู้ได้เสมอ

> ✅ **แก้แล้วตอนปิด M5a (2026-08-07)** — §4 บรรทัด `devices` เคยบอกว่ารวม settings/status เป็น
> **JSON columns** ซึ่งไม่ตรงกับโค้ด: `status` · `status_detail` · `status_checked_at` ·
> `consecutive_failures` เป็น**คอลัมน์มีชนิด** มีแค่ `transport` ที่เป็น JSON และ `capture_objects`
> ไม่มีอยู่บนตารางนี้เลย · บรรทัดนั้นถูกแก้ให้ตรงกับ `db/models.py` แล้ว

- CSV auto-export → **ย้ายไป M7** (ดูเหตุผลด้านล่าง) · manual read-now → **M5b**
- Retention (ตัวเลขเดิม v1) — job รายวัน → **M5c** (เคาะที่ grill M5):
  **ครอบเท่าที่มีตารางจริงตอน M5c** = `load_profile_readings` (**90 วัน**, ตัดตาม `read_at`)
  และ `device_events` (**90 วัน**, ตัดตาม `created_at`) ·
  ~~billing 365 วัน~~ → ✅ **grill M6 (2026-08-09): `billing_readings` ไม่โดน retention เลย** —
  360 แถว/ปี (30 มิเตอร์ × 12 รอบ) ไม่ใช่ปัญหาพื้นที่ และมันคือหลักฐานทางธุรกิจที่ลูกค้าย้อนดู
  ต่างจาก interval reading ที่เป็นข้อมูลดิบ · ที่สำคัญกว่านั้น **365 วันทับพอดีกับความลึกของ buffer**
  (13 entry = 1 รอบเปิด + 12 รอบปิดรายเดือน) ⇒ รอบปิดที่เก่าที่สุดจะถูกลบแล้วถูกอ่านกลับมา insert ใหม่
  ทุกวัน พร้อม render capture ใหม่และ push ซ้ำ — เป็นตำแหน่งที่แย่ที่สุดที่จะวางเส้นตัด ·
  M6 จึงไม่แตะ `db/retention.py` เลย
  `user_tokens` **ไม่ต้องมี** — `auth/service.py:162` เรียก `purge_expired_tokens()` ตอน login แล้ว
  · LP 90 วันเข้าคู่กับ backfill 90 วันพอดี: ดึงมาเท่าที่ตั้งใจเก็บ แล้ว retention ตัดหางไปเรื่อย ๆ
  · ลบ `device_events` **ทุกแถวเท่ากันหมด ไม่แยก `actor`** — เจ้าของงานเลือกความเรียบง่าย
  โดยรู้ตัวว่า **ร่องรอยการกระทำของคน (ใครสั่ง pause / clear data เมื่อไหร่) หายไปด้วยหลัง 90 วัน**
  ถ้าวันหนึ่งต้องตอบคำถามย้อนหลังเกินนั้น ต้องกลับมาทบทวนข้อนี้
  · **retention ห้ามขยับ watermark** — มันลบแถวเก่า ส่วน watermark คือ `MAX(read_at)` ซึ่งเป็นแถวใหม่สุด
  จึงไม่กระทบกัน และถ้าลบจนหมด (device ออฟไลน์เกิน 90 วัน) `MAX` เป็น `NULL` ⇒ กลับไป backfill
  90 วันใหม่เมื่อมันกลับมา ซึ่งถูกต้อง
- Backup อัตโนมัติรายวัน → **M5c** (เคาะที่ grill M5):
  `VACUUM INTO` · ปลายทาง **`%ProgramData%\ARICHDS\backup\` ตายตัว ตั้งค่าไม่ได้**
  (backup ที่อยู่ดิสก์เดียวกับต้นฉบับกันได้แค่ "ลบผิด/ข้อมูลเสีย" **กันดิสก์พังไม่ได้**) ·
  **เก็บ 7 ชุด** หมุนเวียนลบ · **ทุก 24 ชม. นับจากบริการเริ่ม** (เข้ากับ registry ตรง ๆ
  ไม่ต้องเพิ่มตรรกะเวลานาฬิกา) · **เขียนเป็น `.tmp` แล้ว rename เมื่อสำเร็จ** — `VACUUM INTO`
  กินพื้นที่เท่าฐานทั้งก้อนชั่วคราว ถ้าดิสก์เต็มกลางทางจะได้ไฟล์ที่ไม่สมบูรณ์ และไฟล์ backup
  ที่พังแต่ดูเหมือนใช้ได้ แย่กว่าไม่มี backup

> ✅ **แก้แล้วตอนทำ M5c (issue #19)** — บรรทัดข้างบนเคยบอกว่า **ตั้งค่าปลายทางได้** ซึ่ง
> **M5c ล้มข้อนั้น**: ค่าที่ผู้ใช้ตั้งได้ต้องมีตาราง `settings` (ยังไม่มี — อยู่ในรายการตารางอนาคต §4)
> และหน้าตั้งค่าที่เป็นของ **M7** ⇒ ถ้าทำตอนนี้จะได้ค่าที่เก็บไว้แต่ไม่มีใครแก้ได้ ซึ่งคือครึ่งฟีเจอร์
> (เหตุผลเดียวกับที่ CSV export ถูกย้ายไป M7) · **M5c จึงฮาร์ดโค้ดปลายทางเป็น
> `%ProgramData%\ARICHDS\backup\`**
>
> ✅ **ปิดคำถามถาวรตอน grill M6 / ADR 0010 (2026-08-09)** — ตาราง `settings` มาจริงที่ M6b
> (issue #22) แต่ **ปลายทาง backup ยังคงตายตัว ไม่ตั้งค่าได้** เหตุผลเปลี่ยนจาก "ยังไม่มีตาราง"
> เป็นเหตุผลถาวร: backup เขียนเพื่อ "เครื่อง" (ผู้ใช้งานคนเดียวคือคนกู้คืน ซึ่งนั่งอยู่หน้าเครื่องอยู่แล้ว)
> ส่วน `capture_dir` เขียนเพื่อ "คน" ที่ต้องส่งไฟล์ต่อให้คนอื่น — มีแต่แบบหลังที่คุ้มค่าที่จะให้ operator
> เลือกปลายทางเอง (ADR 0010)

- หน้า: Load Profile · Records → **M5b**

**หน้า Load Profile (M5b) = ดูอย่างเดียว** — ตัวกรอง (group · brand · model · device) · ช่วงวันที่ ·
ตารางแบ่งหน้า **ฝั่งเซิร์ฟเวอร์เสมอ** · ปุ่ม **Read now** เท่านั้น
· **ช่วงวันที่บังคับ ตั้งต้นเป็นวันนี้** — v1 ปล่อยให้ว่างแล้วแปลว่า *ดึงทั้งหมด* ซึ่งที่ 90 วัน × 96
= 8,640 แถว/มิเตอร์ และถ้าเลือกทุกมิเตอร์คือ ~259,000 แถวยิงเข้าเบราว์เซอร์
· **ไม่พอร์ต `resolution`** ที่ v1 มีในพารามิเตอร์ query — ยังบอกไม่ได้ว่าใครใช้ (`REMAKE-PLAN:182`)
· ปุ่ม **Save CSV now** · สวิตช์ **auto-save** · ช่องเลือกโฟลเดอร์ → **ไปพร้อม CSV ที่ M7**

> **แก้บรรทัด "ปุ่ม Read now" (issue #17, M5b-1)** — สไลซ์แรกของหน้านี้ออกมาเป็น **ดูอย่างเดียวล้วน
> ไม่มีปุ่ม Read now บนหน้า Load Profile** เพราะ Manual Read มีอยู่แล้วบนหน้า Devices ตั้งแต่ #5 และ
> เก็บ load profile ลงตารางตั้งแต่ #15 — ปุ่มบนหน้านี้จึงเป็นทางลัดซ้ำ ไม่ใช่ความสามารถใหม่ และ
> ไม่มีเกณฑ์รับงานข้อไหนใน #17 รองรับ หน้านี้ **ไม่คุยกับมิเตอร์เลย** อ่านเฉพาะแถวที่เก็บไว้แล้ว
> ถ้าจะเพิ่มปุ่มนี้จริง ให้เปิดเป็นงานของตัวเองพร้อมเกณฑ์รับงาน

### 3.6 Billing (M6)

> เคาะทั้งหมดที่ **grill M6 (2026-08-09)** — 16 ข้อ · ที่ไม่ตรงกับ v1 มีเหตุผลกำกับทุกข้อ

> ⚠️ **การอ่าน billing ไม่ใช่การล้อ `read_load_profile` — มันต้องใช้กลไกอ่านคนละตัว**
> (พบตอน scrutinize แผน 2026-08-09 · ข้อนี้เปลี่ยนขนาดของงาน อย่าอ่านผ่าน)
>
> `smw110.py:378` อ่าน load profile ด้วย `self._reader.readRowsByEntry(pg, start, count)` เต็มความกว้าง
> แต่ **billing ของรุ่นนี้อ่านเต็มความกว้างไม่ได้** — ตอบ *"Data Block Unavailable"* ต้องส่ง span
> 43 คอลัมน์เท่านั้น (`smw110w4-scan.md:246-253`) · และ `vendor/gurux/GXDLMSReader.py:400`
> **ไม่มีช่องใส่ span** ส่วนการแก้ไฟล์ vendored ถูกห้ามโดย invariant ใน `CLAUDE.md`
>
> **ทางออกไม่ต้องแตะไฟล์ vendored เลย**: `GXDLMSClient.readRowsByEntry(pg, index, count, columns=None)`
> รับ span อยู่แล้ว และ `_dlms.py:255` แสดงว่า driver ถือ `self._client` อยู่ในมือ · พิสูจน์มาแล้วสองที่ —
> v1 `_tcp_driver_base.py:771` (พร้อม fallback ที่ :757-761) และสคริปต์ของเราเอง
> `app/scripts/probe_smw110_serial.py:534`
>
> **แต่มันไม่ฟรี**: เมธอดนั้นคืน **request** ไม่ใช่แถว ⇒ driver ต้องขับ data-block loop เอง สลับ
> `pg.captureObjects` → span ก่อน `updateValue` แล้วคืนค่าใน `finally` · และ `smw110.py:369-370`
> ที่สร้าง `positions` / `expected_cell_count` จาก `captureObjects` เต็ม ต้องอิง span แทน
> ⇒ **แยกเป็น issue ของตัวเอง** อ้างสคริปต์ probe เป็นต้นแบบ และบังคับ skill `gurux-dlms`
>
> ⚠️ **ลำดับ entry เป็นสมบัติของ "โปรไฟล์" ไม่ใช่ของ "มิเตอร์"** — `smw110.py:143` ฝังไว้ว่า
> load profile *"entry 1 is the OLDEST"* แต่ billing ของเครื่องเดียวกันเรียง **newest-first**
> (`scan:288`) · positional fallback ที่ใช้จำแนกรอบเปิดยืนอยู่บนข้อนี้พอดี — ห้ามใช้ค่าคงที่ลำดับ
> ร่วมกันสองโปรไฟล์

**เส้นทางอ่าน — มีเส้นเดียว** `read_and_store_billing(device_id, *, locks, background, now)`
รูปทรงภายนอกล้อ `acquisition/load_profile.py` (ลายเซ็น · lock · จุดเรียก) แต่**ข้างในเป็นกลไกอ่าน
คนละตัวตามกรอบข้างบน** · **อ่านทั้ง buffer ทุกครั้ง** ⇒ คำว่า "Backfill" หายไปเป็นแนวคิด
เพราะทุกการอ่านคือ backfill · ไม่มี endpoint backfill แยก ไม่มี `billing_backfilled_at`
ไม่มี is_latest reconciler · เหตุผล: ไม่มีรุ่นไหนที่ buffer ใหญ่พอจะเป็นข้ออ้างให้อ่านแค่ entry เดียว
(SMW110W4 = 13 · CEWE = 3/5/13 · TCC = 1) และสามเส้นทางของ v1 เป็นผลของ ADR 0002 → 0012 → 0013 → 0018
ที่ปะกันมาทีละชั้น ไม่ใช่การออกแบบ

**ตั้งเวลา** — job เดียวใน registry รอบคงที่ **1 วัน** เพิ่มหนึ่งบรรทัดใน `default_jobs()` ·
**ไม่มี HH:MM ไม่มี catch-up ไม่มี `last_auto_run_date`** — ADR 0008 ห้าม persisted scheduler state
และเหตุผลที่ v1 ต้องมีมัน (กันอ่านซ้ำทั้ง fleet หลัง restart) หายไปเมื่อการอ่านเป็น idempotent ·
job จับ lock แบบ `background=True` — ชนแล้ว**ข้าม ไม่ต่อคิว** (ADR 0006)

**ตาราง `billing_readings`** — คอลัมน์แบนชื่อตาม COSEM ล้อ `load_profile_readings` ·
ชุดฟิลด์ของ v1 **ขยายจาก 3 เป็น 4 อัตรา** (`rate_a`…`rate_d`) เพราะ SMW110W4 เผย `E=1..4` ซึ่งเป็น
เงื่อนไขที่ v1 ADR 0001 ตั้งไว้เองว่าจะรื้อเมื่อไร · **ไม่เติม `C=5`** (reactive Q1) เพราะไม่มีหน้าจอไหน
เคยแสดง — เส้นแบ่งคือ "เติมกลุ่มคอลัมน์ที่มีอยู่ให้ครบ" ไม่ใช่ "เพิ่มแนวคิดใหม่" ·
เวลา: `read_at` · `bill_date` · `created_at` · **`updated_at`** (จำเป็นสำหรับ push §3.8) ·
`meter_serial` snapshot ต่อแถว (path ของ capture ประกอบจากมัน)

> ⚠️ **ชุดคอลัมน์ขยาย 40 → 60 ที่ M4c (grill 2026-08-09) — เกณฑ์ของ §3.6 เองบังคับ**
>
> หน้า Billing ของ v1 (`cewe-fe/src/pages/Billing/index.tsx:75-102` — จอที่ลูกค้ายืนยันแล้ว)
> แสดง **9 คอลัมน์ที่ตารางนี้ไม่มีที่เก็บ**: เวลาที่เกิด max demand (`Time of kW Demand`
> A/B/C/Total + `Time of kVar Demand`) และ **Cumulative Demand** (`Cumul kW Demand` A/B/C +
> `Cumul kVar Demand Total`) · เกณฑ์ที่ §3.6 ใช้ตัด `C=5` ทิ้งคือ *"ไม่มีหน้าจอไหนเคยแสดง"* —
> เก้าตัวนี้ v1 **แสดงจริง** ⇒ สคีมาที่ลงที่ M6 ยังไม่ครบตามเกณฑ์ของมันเอง และ exit
> *"parity ของ billing"* จะพิสูจน์ไม่ได้ตั้งแต่ต้น
>
> **เพิ่ม 4 หมวด × (total + rate_a..d) = +20 คอลัมน์ เฉพาะฝั่ง import**: เวลาของ max demand
> import active/reactive · Cumulative Demand import active/reactive · **ไม่เพิ่มฝั่ง export**
> เพราะไม่มีหน้าจอไหนแสดงและไม่มีหลักฐานว่ามิเตอร์ตัวไหนมีบนสาย (เส้นเดียวกับที่ตัด `C=5`)
> · เติมอัตราให้ครบ a–d ตามกฎ *"เติมกลุ่มที่มีอยู่ให้ครบ"* — ถ้าตัดที่ C ตามที่ v1 มี จะได้กลุ่ม
> ที่ขาด rate_d อยู่กลางตารางที่ทุกกลุ่มมีครบ และต้อง migrate รอบสามวันที่เจอมิเตอร์ที่มี
>
> **10 ใน 20 คอลัมน์ใหม่เป็นเวลา ไม่ใช่ตัวเลข** ⇒ `capture/_render_shared.py::format_cell`
> · สคีมา API · payload ของ push §3.8 ต้องรองรับชนิดใหม่
>
> **และมันบังคับให้เปลี่ยนกุญแจ map คอลัมน์เป็น `(OBIS, attribute)`**: `smw110.py:603` สร้าง
> `positions` โดยคีย์ด้วย `logicalName` อย่างเดียว แต่ **ค่า max demand (attr 2) กับเวลาของมัน
> (attr 5) ใช้ OBIS เดียวกัน** ⇒ คีย์ด้วย OBIS จะทับกันเงียบ ๆ (ตัวหลังชนะ)
>
> ⚠️ **ไม่ใช่บั๊กของ M6 — อย่าอ่านเป็นอย่างนั้น**: span 43 คอลัมน์ของ SMW110W4 คือ Clock +
> counter + 25 คอลัมน์พลังงาน + 16 คอลัมน์**ค่า** demand · **ไม่มีคอลัมน์เวลาอยู่ในนั้นเลย**
> (`smw110w4-scan.md:271-285`) ⇒ ของที่ลงไปแล้วถูกต้องสำหรับรุ่นที่มันรองรับ · มันจะผิดก็ต่อเมื่อ
> รุ่นที่ capture attr 5 เข้ามา ซึ่งคือรุ่นของ M4c
>
> **v1 ทำแบบนี้อยู่แล้วและทิ้งแบบแปลนไว้ให้สองอย่าง**:
> `_tcp_driver_base.read_billing_profile_row()` คืน `dict[tuple[str, int], Any]` — คีย์ด้วย
> `(obis, attr)` เป๊ะ ซึ่งเป็นเหตุผลที่ v1 รับ layout 69/73/104/148 คอลัมน์ได้โดยไม่แตะโค้ดต่อรุ่น ·
> และ **span เป็น attribute ของไดรเวอร์ (`BILLING_SELECT_COLUMNS`) ไม่ใช่ค่าคงที่ระดับโมดูล**
> ⇒ v2 ควรย้าย `smw110.py:80 BILLING_COLUMN_SPAN = 43` ไปเป็นคุณสมบัติของไดรเวอร์ตอน M4c
> เพราะ M4c เป็นจุดที่มีรุ่นที่ไม่ต้องใช้ span เข้ามาเป็นครั้งแรก
>
> **การอ่านทั้ง buffer เต็มความกว้างพิสูจน์แล้ว ไม่ใช่ความหวัง** — `_tcp_driver_base.py:626-668`
> `read_billing_profile_rows()` ทำ `readRowsByEntry(pg, 1, entries_in_use)` เต็มความกว้างจริง
> (13 แถว × 104 คอลัมน์ บน Saral) โดยมี `BILLING_SELECT_COLUMNS` เป็นทางถอยเฉพาะมิเตอร์ที่ไม่ยอม

**billing ของรุ่น M4c — OBIS ต่อรุ่น อ่านเต็มความกว้าง** (หลักฐานจาก v1 + field probe):

| รุ่น | billing profile OBIS | entries ตอนจิ้ม | คอลัมน์ | span 43 ไหม |
|---|---|---|---|---|
| Prometer 100 | `1.0.98.2.0.255` | 5 | 69 | **ไม่ต้อง** — อ่านเต็มได้ |
| Saral 305 | `1.0.98.2.0.255` | 13 | 104 | ไม่ต้อง |
| Premier 550 | `1.0.98.2.0.255` | 3 | 73 | ไม่ต้อง |
| SMART TCC | **`0.0.98.1.0.255`** (Scheme 1) | 1 | 148 | ไม่ต้อง |
| SMW110W4 | `1.0.98.1.0.255` | 13 | 242 | **ต้อง** (43) |

⇒ **span 43 เป็นข้อจำกัดของ SMW110W4 ตัวเดียว ไม่ใช่รูปแบบร่วม** · `entries_in_use` อ่านสดทุกครั้ง
ห้าม hard-code (v1 บันทึกเองว่ามันเพิ่มทุกครั้งที่มิเตอร์ตัดบิล) · **entry 1 = ใหม่สุดทุกรุ่น**
(ยืนยันด้วยยอดรวมของแถวแรก ≈ ค่า live standalone register ทั้งสามรุ่น CEWE) ·
TCC อ่าน **Scheme 1 เท่านั้น** — Scheme 2 (`0.0.98.2.0.255`) เดินหน้าทุกวัน ไม่ใช่รอบบิล (v1 ADR 0018)

**ตัวจำแนกรอบเปิด/ปิด — ถามมิเตอร์ก่อน ไม่มีค่อยใช้ตำแหน่ง** (เคาะที่ grill M4c) ·
CEWE ทั้งสามรุ่นมี `0.0.0.1.12.255` (**reset reason** — `255` = ยังไม่รีเซ็ต = รอบเปิด) อยู่ใน
capture ของ billing profile ⇒ ใช้ตัวนั้น · SMART TCC **ไม่มี register นี้เลย** (field probe
2026-07-24) และ SMW110W4 ยังไม่มีใครพิสูจน์ ⇒ ทั้งคู่ใช้ตำแหน่งแบบ M6 (`is_open = position == 0`)
· ทั้งหมดอยู่หลัง `read_billing()` ของแต่ละ driver — ไม่มี if/elif ในโค้ดกลาง ·
**เหตุผล**: หลักการ ADR 0005 (สถานะมาจากมิเตอร์ ไม่ใช่จากที่เราอนุมาน) และ M6 พบเองว่า
ลำดับ entry *"เป็นสมบัติของโปรไฟล์ ไม่ใช่ของมิเตอร์"* ⇒ ถ้ารุ่นไหนเรียงกลับด้าน ตำแหน่งจะ mark ผิด
และ index `UNIQUE(device_id) WHERE record_status='open'` จะทำให้การเขียนล้มทั้งก้อน

⚠️ **คอลัมน์ใหม่ส่วนใหญ่จะเป็น NULL บน Saral 305 — เขียนลงเกณฑ์รับรอง อย่าให้ใครอ่านเป็นบั๊ก** ·
v1 `adr/0004-driver-abstraction-obis-map.md:232-239` วัดไว้แล้วว่า Saral ครอบ **19/25** ฟิลด์
และหกตัวที่ขาดคือ `cumul_kw_demand_rate_a/b/c` (`1.0.1.2.1/2/3`) · `kvar_demand_total` +
`kvar_demand_time` (`1.0.3.6.0` attr 2/5 — profile มี `1.0.1.6/2.6/9.6/10.6` แต่ไม่มี `3.6`) ·
`cumul_kvar_demand_total` (`1.0.3.2.0`) พร้อมคำตัดสินว่า *"Hardware/firmware does not track them"*
⇒ **3 ใน 4 หมวดใหม่ว่างบน Saral** และ **parity ของคอลัมน์ใหม่พิสูจน์ได้ที่ Prometer 100 ที่เดียว**
(รุ่นเดียวที่ครอบ 25/25)

**✅ หน้า Billing ขยายเป็น 60 คอลัมน์ — landed with issue #24 (2026-08-09)** (เจ้าของตัดสิน
grill M4c) — ของเดิมแสดงเฉพาะ 8 ตัว `_total` ส่วนรายอัตราอยู่แต่ในเอกสาร capture · ของใหม่แสดง
ครบทุกอัตราเหมือนหน้าจอ v1 ⇒ มี **หัวตารางแบบจัดกลุ่ม** (AntD `children`) · ตรึง Bill Date /
Device / Meter Serial ไว้ซ้าย · เลื่อนแนวนอนในกล่องของตัวเอง (`web/src/pages/Billing.tsx`) ·
`capture/_render_shared.py::ALL_SECTIONS` เพิ่ม **2 หมวดใหม่** ("Demand Time",
"Cumulative Demand") ไม่ใช่ 4 หมวดตามที่วางแผนไว้แต่แรก — เพราะ `_SECTION_DEMAND` เดิมรวม 4 กลุ่ม
เข้าหมวดเดียวอยู่แล้ว (import/export × active/reactive) ดังนั้นสองหมวดใหม่ก็รวม 2 กลุ่มเข้าหมวด
เดียวแบบเดียวกัน (import active / import reactive) เพื่อให้สอดคล้องกับรูปแบบไฟล์เดิม (D18,
issue #24)

✅ **งานฝั่ง API — landed with issue #24**: `api/billing.py`'s `BillingRowOut` โตจาก 8 ฟิลด์
(ทั้งหมด `_total`) เป็น 65 ฟิลด์ (id, device_id, device_name, bill_date, read_at, meter_serial +
60 ฟิลด์วัดค่า — 10 ในนั้นเป็น `datetime | None` สำหรับ Demand Time) พร้อม validator ที่แนบ UTC
ให้ทั้งฟิลด์บังคับและฟิลด์ที่เป็น `None` ได้

**คีย์ — สองตัว ไม่ใช่ตัวเดียว** (แก้ตอน scrutinize 2026-08-09):
`UNIQUE(device_id, bill_date) WHERE record_status IS NULL` สำหรับ dedup รอบปิด ·
`UNIQUE(device_id) WHERE record_status='open'` สำหรับบังคับ "1 open slot ต่อ device" ·
partial index ทั้งคู่ (SQLite รองรับ · Alembic batch mode เอาอยู่) · **เหตุผลสองข้อ**: (1) คีย์เดียว
แบบ v1 จะชนกันเองได้ — ทันทีหลังตัดรอบ entry 2 ถูกตราที่ `00:00:00` ส่วน entry 1 ตราด้วยเวลาที่อ่าน
การอ่านที่ตกวินาทีเดียวกันทำให้ upsert รอบเปิดโดน IntegrityError · (2) คีย์เดียว **ไม่ห้าม open slot
สองแถว** ซึ่งเป็นข้อสมมติที่ทั้งโมดูลยืนอยู่ — v1 ไม่เคยบังคับที่ DB จึงต้องมี is_latest reconciler
มาไล่ซ่อม (v1 ADR 0012 §Consequences · ADR 0013 §4) และ**เราเพิ่งลบ reconciler นั้นทิ้งไปในข้อ 2**
⇒ ต้องปิดรูที่มันเคยรองอยู่ด้วย constraint แทน

**รอบเปิด** — ยก ADR 0018 มา: 1 แถว/device ที่ `record_status="open"` **upsert ทับที่เดิม**
(หาแถวด้วย `device_id + record_status`, **ไม่ใช่** `bill_date` ซึ่งขยับทุกการอ่าน) · **ตัวจำแนกของ v1 ใช้กับ SMW110W4 ไม่ได้** —
reset-reason `0.0.0.1.12.255` ไม่อยู่ใน 43 คอลัมน์แรก ⇒ ใช้ positional fallback ที่ ADR 0018
เขียนรองรับไว้แล้ว (entry 1 = เปิด) ผ่าน driver capability ไม่ใช่ `if/elif` ตามรุ่น

**สเกล** — ÷1000 ครั้งเดียวที่ driver ตอน write ตาม ADR 0002 · **ห้ามยก ÷10000 ของ v1 มา** ·
ตรวจกับฟิสิกส์ของมิเตอร์เองแล้ว: Δ ระหว่าง entry 2→1 = 1,779,471 ใน 155.6 ชม. ⇒ ÷1000 ได้ 11.4 kW
เฉลี่ย เทียบ instantaneous 23.7 kW ตอน probe (สมเหตุสมผล) ส่วน ÷10000 ได้ 1.14 kW (ผิดราว 20 เท่า) ·
คอลัมน์ที่อ่าน `scaler_unit` ไม่ได้ให้ยืมจาก sibling `E=0` ของกลุ่ม `C.D` เดียวกันพร้อมเช็ค unit —
ยืมไม่ได้ก็ **เก็บเป็น NULL ห้ามเดา multiplier**

**แถวรอบปิดไม่เปลี่ยนหลังบันทึก** — เจอ `bill_date` ซ้ำแล้วค่าไม่ตรง = **ข้าม + WARN** ·
`billing_readings` **ไม่โดน retention เลย** (ดู §4) · ทางเดียวที่ลบได้คือปุ่ม **Delete all data**
ที่หน้า Devices ซึ่ง **M6 ขยายให้ครอบ `billing_readings` ด้วย** (เดิมลบเฉพาะ `load_profile_readings`)
· ⚠️ **และปุ่มนี้ลบแล้วข้อมูลกลับมา** — job รอบถัดไปอ่านทั้ง buffer (ข้อ "เส้นทางอ่าน") แล้ว insert
รอบปิดที่ยังอยู่ในมิเตอร์กลับมาครบ ~12 เดือน ⇒ มันซ่อมได้จริง**เฉพาะค่าที่ผิดเพราะฝั่งเรา**
(แก้สเกลแล้วอ่านใหม่ได้ค่าถูก) ส่วนค่าที่ผิดเพราะมิเตอร์รายงานมาแบบนั้น ปุ่มนี้เป็น no-op ·
อาการเดียวกับ LP ที่ `CONTEXT.md` เขียนกำกับไว้แล้ว — **ข้อความยืนยันบนปุ่มต้องบอกเรื่องนี้
ไม่งั้นปุ่มโกหก**

**Capture PDF/xlsx/PNG** — gate ด้วย `auto_capture` / `billing_excel_export` / **`billing_image_export`**
(M7 slice 4, issue #35, ADR 0014/0015) · เขียนลงโฟลเดอร์ที่ admin
ตั้งได้ (`capture_dir` ใน `settings`) แบบ v1 พร้อมงานตรวจ path/symlink/TOCTOU ทั้งชุด ·
path มาจาก convention **ไม่มีตาราง `billing_captures`** (ดู §4) · สร้าง **eager ตอน insert รอบปิด**
แบบ synchronous นอก endpoint lock — **รอบเปิดไม่สร้าง** · **ไม่มี regenerate endpoint**: endpoint
ดาวน์โหลด render ให้ตรงนั้นถ้าไฟล์หาย ⇒ ตัดทั้งสถานะ "capture พลาดถาวร" และ retry 2 วินาทีของ v1 ·
ข้อความในเอกสารเป็น**อังกฤษ** และค่าที่ operator พิมพ์ซึ่งไม่ใช่ ASCII แทนที่ด้วย `?` + WARN แบบ v1
(ไม่ฝังฟอนต์ไทย) · **`.png` ไม่เหมือน `.pdf`/`.xlsx`**: สองแบบแรกครอบคลุมแค่รอบเดียว ส่วน `.png`
วาดตาราง Billing History ครอบ **สิบรอบปิดล่าสุด** ของมิเตอร์นั้น (ชื่อไฟล์ stem เดียวกันทั้งสามแบบ —
ต่างกันแค่ extension, ADR 0015) · วาดด้วย Pillow ฝั่งเซิร์ฟเวอร์ ไม่ใช่ screenshot จริง (ADR 0014)

**Feature entitlement** — ✅ **ลงแล้วกับ issue #22 (M6b)** · ตอน grill M6 v2 ยังไม่มีกลไกนี้เลย
(license มี `features` แต่ไม่มีใครอ่าน) ·
**M6 สร้าง `require_feature` แล้วทาให้ครบทั้ง `billing` และ `load_profile`/`records` ที่ M5 ค้างไว้** —
gate ที่ทาครึ่งเดียวคือโรงงานผลิตบั๊ก · ✅ **คีย์ที่คุมหน้า Records ชื่อ `records`** — เจ้าของตัดสิน
2026-08-09 ปิดคำถามที่ §5 ค้างมาตั้งแต่ก่อน M5 · ชื่อคีย์เป็น contract กับ portal ไม่ใช่ของที่
implementer เลือกเอง จึงต้องปิดก่อนเขียน issue นี้ (พบตอน scrutinize 2026-08-09)

**ลำดับสไลซ์ — รอบปิดต้องลงก่อน open slot** (scrutinize 2026-08-09): รอบปิดไม่ต้องจำแนกอะไรเลย
มันคือสิ่งที่อยู่ใน buffer ที่ Clock หยุดนิ่ง dedup ด้วย natural key จบ · ส่วน open slot คือสิ่งที่ลาก
`record_status` · ตัวจำแนกเปิด/ปิด · driver capability · เส้นทาง upsert · คีย์ตัวที่สอง และ **probe gap
ข้อเดียวที่ไม่มีหลักฐานบางส่วนรองรับเลย** (พฤติกรรมตอนมิเตอร์ตัดรอบจริง) มาทั้งพวง ⇒ ถ้าตัวจำแนก
ผิดตอนเจอ reset จริง จะกระทบสไลซ์เดียว และลูกค้ายังมีบิลที่ถูกต้องอยู่ในมือ

> **M6 ใหญ่กว่า M5** — M5 ใช้ 5 issue โดยไม่มีของใหม่ระดับ "ตารางที่ยังไม่เคยมี" หรือ "กลไกที่ยัง
> ไม่เคยมี" เลย · M6 มีสาม: กลไกอ่านแบบ span · ตาราง `settings` · `require_feature` — บวก capture
> อีก ~400 บรรทัดที่พอร์ตมา `/to-issues` ต้องรู้ก่อนตัดสไลซ์

**หน้า Billing — สองแท็บแบบ v1** · History = รอบปิดเท่านั้น · Current = open slot เท่านั้น
(แยกด้วย `record_status` ตาม ADR 0018) · แบ่งหน้าฝั่งเซิร์ฟเวอร์ · ปุ่มดาวน์โหลด capture ต่อแถว ·
ฟอร์ม `capture_dir` (admin) · **ไม่มีปุ่มคุยกับมิเตอร์บนหน้านี้** — Read now อยู่ที่หน้า Devices และ
M6 เติม job `billing` เข้า list เดิม (§3.3) โดย **billing ที่ล้มไม่นับ strike** (มีแต่ `liveness`
ที่แตะสถานะ device)

**Modbus billing cut — ไม่อยู่ใน M6** (อยู่ M4b) และ**ชะตายังไม่ตัดสิน**: เจ้าของยืนยันที่ grill M6 ว่า
*"เราไม่มีตรรกะตัดงวด … เรามีหน้าที่อ่านค่าจาก meter (read only) เท่านั้น"* ซึ่งขัดกับตัวฟีเจอร์
(มันเป็นการตัดงวดฝั่งระบบ แม้จะไม่เขียนอะไรลงมิเตอร์ก็ตาม) · **ปิดคำถามตอน grill M4b** — ดู §5

### 3.7 โมดูลเบา (M7)

- Energy Summary (TOU buckets — ADR 0016) · Holidays (2 ชนิด) · Special Days · Battery status ·
  Export format settings · App Log (log viewer — log ผ่าน credential redaction filter เสมอ)
- **CSV auto-export ของ Load Profile (ย้ายมาจาก M5c ที่ grill M5 2026-08-07)** — มาพร้อมกันกับ
  หน้า ExportFormat ที่เป็นเจ้าของรูปแบบไฟล์: job เขียนต่อท้ายไฟล์ต่อมิเตอร์ · ปุ่ม **Save CSV now**
  · สวิตช์ **auto-save** — ✅ **ทั้งเครื่อง ไม่ใช่ต่อมิเตอร์ (grill M7, 2026-08-11)**: v1 เก็บใน
  `format_settings` แถวเดียวต่อ `setting_type` และ 1 ลูกค้า = 1 เครื่อง = มิเตอร์ที่ตั้งเหมือนกันหมด ·
  บรรทัดนี้เคยเขียนว่า "ต่อมิเตอร์" ซึ่งไม่ตรงกับ v1 และจะบังคับให้เพิ่มคอลัมน์บน `devices`
  เพื่อแก้ปัญหาที่ยังไม่มีใครเจอ — เพิ่มทีหลังง่ายกว่าถอด
  · ช่องเลือกโฟลเดอร์ปลายทาง — ทั้งสามอย่างอยู่บนหน้า Load Profile
  ที่ M5b สร้างไว้แล้ว · รายละเอียดที่เคาะแล้ว (watermark, BOM, fsync, lock ต่อ device) อยู่ใน §3.5
  · ✅ **landed with issue #30 (M7 slice 3)**: `db/load_profile_query.py` (the shared
  Logger 1/2 merge, D-2) · `export/format.py` (row/filename formatting, corrected headers,
  D-3/D-4) · `export/csv_export.py` (the skew cap, the per-device lock, the watermark column,
  the hardened write) · `devices.csv_exported_through` (migration 0012) ·
  `GET`/`PUT /api/settings/export-format` and `POST /api/load-profile/export` ·
  `pages/ExportFormat.tsx` and the auto-save/output-folder/Save-CSV-now controls on
  `pages/LoadProfile.tsx`. `output_csv` was dropped from the ported set at implementation
  time (D-5, see the not-ported list below).
- หน้า: EnergySummary · Holidays · SpecialDays · Battery · ExportFormat · AppLog

#### เคาะที่ grill M7 (2026-08-11)

**Energy Summary = สองฟีเจอร์ในหน้าเดียว สองแท็บแบบ v1** (`pages/EnergySummary/index.tsx:509`) —
ชื่อในแผนเดิมคลุมสองอย่างที่ไม่แชร์ข้อมูลกันเลย และ `CONTEXT.md` แยกศัพท์ให้แล้ว:

| แท็บ | คือ | เก็บที่ไหน |
|---|---|---|
| **Summary Report** | Energy Summary — TOU buckets รวมสดจาก `load_profile_readings` | **ไม่เก็บ** |
| **Meter Registers** | Energy Registers — ทะเบียนสะสม `D=8` อ่านจากมิเตอร์ | `energy_register_readings` |

**ทำไมต้องมีแท็บ Meter Registers ทั้งที่ `billing_readings` เก็บ `1.0.1.8.E` ไว้แล้ว**: เพราะ
**มิเตอร์ที่ยังไม่เคยตัดบิลไม่มีตัวเลขพลังงานให้ดูเลยสักตัว** — TCC ST-3CL ที่หน้างานคืนค่า
`entries_in_use: 0` บน billing profile (`docs/meter-notes/tcc-3cl-serial-scan.md`) ขณะที่ทะเบียน
สะสมอ่านได้ทันที · แท็บนี้คือทางเดียวที่จะเห็นตัวเลขก่อนงวดแรกปิด
(เหตุผลเดิมที่เคยเขียนไว้ตอน grill คือ "SPEC วางตารางไว้ตั้งแต่ต้น" ซึ่งเป็นการอ้างอำนาจ
ไม่ใช่เหตุผล — แทนที่ตอน scrutinize แผน M7)

ทั้งคู่ใช้คีย์ `energy_summary` ตัวเดิม **ไม่เพิ่มคีย์ที่ 9** (เพิ่มทีหลังได้เสมอ — หน้าต่างที่ปิดถาวร
คือการ *เปลี่ยนชื่อ* คีย์ ไม่ใช่การเพิ่ม) · **หน้า Holidays ใช้คีย์เดียวกันนี้ด้วย** เพราะวันหยุดมีอยู่
เพื่อแบ่งถัง TOU อย่างเดียว — ปล่อยไม่ gate จะได้หน้ากรอกที่กรอกแล้วไม่มีผลกับอะไร

**TOU**: หน้าต่าง Peak **เป็นค่าคงที่ ตั้งไม่ได้** (local 09:00–22:00 เท่า v1) · นับ **active
อย่างเดียว** import + export = 6 ช่อง เท่า v1 (reactive มีข้อมูลแต่ไม่มีใครขอ และไม่มีอะไรให้เทียบ
parity) · ⚠️ **ผลลัพธ์ย้อนหลังไม่นิ่ง** — ดู `CONTEXT.md` → Energy Summary

⚠️ **SQL ต้องเขียนใหม่ และ ADR 0016 เขียนไว้ไม่ครบ — อย่าทำตามตัว ADR** (พบตอน scrutinize แผน M7):
ตัว ADR ระบุ predicate ว่า `DAYOFWEEK(read_at) ∈ {1,7}` ซึ่ง **ตกการแปลงเขตเวลา** ที่โค้ดจริงมี —
`load_profile/repository.py` ใช้ `DAYOFWEEK(ADDTIME(lr.read_at, :tz_shift)) IN (1, 7)` พร้อมคอมเมนต์
อธิบายว่า *"else the 00:00–06:59 ICT slice — still the previous UTC day — is mis-dated by 7 h"*
⇒ **v1 ไม่มีบั๊กนี้ ตัวเอกสารต่างหากที่ไม่ครบ** · สองกับดักที่ต้องอยู่ในเกณฑ์รับงาน:

| | MySQL (v1) | SQLite (v2) |
|---|---|---|
| เสาร์อาทิตย์ | `DAYOFWEEK ∈ {1,7}` — 1=อาทิตย์ | `strftime('%w') ∈ {'0','6'}` — **0=อาทิตย์** |
| เลื่อนเขตเวลา | ใส่ที่ **วัน / เดือน / วันที่** เท่านั้น | เหมือนกัน — **ห้ามใส่ที่ชั่วโมง** |

ชั่วโมงอยู่ UTC เพราะค่าคงที่ peak ถูกเลื่อนไว้ล่วงหน้าแล้ว · ใส่เลข `{1,7}` ทื่อ ๆ ลง SQLite =
**ถังพลังงานเพี้ยนทุกสุดสัปดาห์แบบเงียบ ๆ** ⇒ เทสต้องมีเคส **วันเสาร์ ICT 00:30 (= UTC ศุกร์ 17:30)**
บวก 3 เคสของ ADR 0016 (เสาร์อาทิตย์ · annual ข้ามปี · public)

**ธง capability ในแค็ตตาล็อกไม่ตรงกับความจริง — แก้ที่ M7** (ดู ADR ที่คู่กับหัวข้อนี้):

| | แค็ตตาล็อกประกาศ | v1 implement จริง | M7 ทำ |
|---|---|---|---|
| `supports_battery` | 9 รุ่น | 3 (CEWE — `_cewe_battery.py`) | CEWE 3 — ✅ **landed with issue #29 (M7-2)**: `read_battery_status()` on `MeterDriver`, implemented on the three CEWE models via the shared `_dlms.py` free function `read_battery_status_via()` |
| `supports_energy_summary` | 6 รุ่น | **1** (`smw110`) | `smw110` + TCC ×5 — ยืนยันแล้วด้วย probe ST-3CL จริง 2026-08-11: ทะเบียนสะสม `1.0.{1,2,3,4}.8.{0..4}.255` ตอบครบ 20/20 (`E=1..4` รวมอยู่ในนั้นด้วย) |
| `supports_special_days` | 6 รุ่น | **1** (`smw110`) | `smw110` + TCC ×5 — probe ST-3CL เดียวกันอ่าน `0.0.11.0.0.255` ได้ 82 รายการ |

`read_battery_status()` / `read_energy_registers()` / `read_special_days()` เป็น **capability method
บน `MeterDriver`** default โยน `NotImplementedError` — generic code ถามไดรเวอร์ ไม่ถามแค็ตตาล็อก

**ตารางใหม่ 3 ตัว (7 → 10 ตาราง เพดาน 13)**:
`energy_register_readings` **กว้าง 20 คอลัมน์** (4 ชนิด × total + rate_a..d) ตั้งชื่อล้อ
`billing_readings` — **ไม่ใช่ EAV แบบ v1** ที่เก็บ `obis`/`label`/`value`/`unit` เป็นแถว: `label` คือ
ข้อความบนจอ ห้ามฝังลงข้อมูล และ M8 ต้องการสัญญา field ที่นิ่ง ·
`battery_readings` = `status` เท่านั้น (`id`/`device_id`/`read_at`/`created_at` ข้างเคียง) — **ไม่มี
`remaining_seconds`** ✅ **ตัดออก — landed with issue #29 (M7-2)**: ไดรเวอร์ v2 ไม่มีตัวไหนผลิตค่า
remaining-time ได้เลย — v1's เส้นทาง CEWE ปล่อย `remaining_minutes`/`remaining_seconds` เป็น `NULL`
โดยตั้งใจอยู่แล้ว (`storage_service.py:266-269`), รีจิสเตอร์ที่อ่าน (`0.0.96.6.1.255`) เป็นจอ
charge/status ไม่ใช่ duration (ไม่ใช่ `0.0.96.6.0.255` ซึ่งเป็น "battery use time counter" ตัวจริง),
และ `smw110` มีแต่แบต *voltage* ไม่ใช่แบตนี้อยู่แล้ว — ใส่คอลัมน์ที่ไม่มีไดรเวอร์ไหนเติมได้ ผิดกฎ
เดียวกับ ADR 0011 เอง (ธงที่ไม่มีไดรเวอร์หนุนหลัง) เพียงแค่คนละไฟล์ · `holidays` ตาม ADR 0016
(`kind` ∈ {annual, public}, ไม่มี `device_id`)
· **Special Days ไม่มีตาราง** — อ่านสดแสดงผลอย่างเดียวเหมือน v1 (`special_days/service.py:2`)
  แต่ **v2 ต่อท่อเพิ่มทางเดียว: มิเตอร์กลายเป็น "แหล่งนำเข้า" ของตาราง `holidays`** (พบตอน
  scrutinize แผน M7 จากผล probe 2026-08-11) — ST-3CL คืน **82 รายการ** เป็นปฏิทินวันหยุดไทย
  ครบถึงปี 2041 และ**แยกเป็นสองก้อนตรงกับ `kind` ของ ADR 0016 พอดี** (`01/01` `04/13` `12/05`
  ไม่มีปี = annual · `02/12/25` `03/03/26` มีปี = public) ⇒ ปุ่ม "นำเข้าจากมิเตอร์" แทนการให้คน
  พิมพ์ 82 แถว · ยังเป็น**ทางเดียว**: `holidays` คงเป็นเจ้าของความจริงของ TOU ฝั่งเรา เพราะตาราง
  ในมิเตอร์เป็นของ**ต่อมิเตอร์** (สองตัวขัดกันได้) · CEWE ไม่มีตารางนี้เลย · และ `dayId` เป็นรหัส
  ตารางค่าไฟของมิเตอร์เอง ไม่ใช่คำว่า "หยุด" ของเรา
  ⚠️ **อ่านวันจากฟิลด์ของ `GXDate` ห้ามอ่านจาก `str()`** — `02/12/25` ยืนยันว่าเป็น MM/DD/YY ได้
  จากการที่มันตรงกับมาฆบูชา 2025 ซึ่งเป็นความหมาย ไม่ใช่สัญญาของไลบรารี และ `12/05` กับ `05/12`
  เป็นวันหยุดไทยจริงทั้งคู่ สลับแล้วไม่มีอะไรฟ้อง
· `energy_register_readings` **upsert บน `(device_id, read_at)` ไม่ใช่ insert** — กดปุ่มรัวสองครั้ง
ในวินาทีเดียวกันต้องไม่ชน unique constraint และการอ่านสองครั้งในวินาทีเดียวคือค่าเดียวกันอยู่แล้ว

**Energy Registers + Special Days = กดปุ่ม** — เข้าเส้นทาง Manual Read เดิม ⇒ ได้สิทธิ์แซง
background tick ตาม ADR 0006 ฟรี (ยืนยันแล้วว่ามีของจริงให้ใช้: `acquisition/locks.py` มี
`acquire_manual()` / `manual()` อยู่แล้ว ไม่ต้องเขียนกลไกใหม่)

**Battery = job ใน registry** เพราะคุณค่าอยู่ที่แนวโน้ม ไม่ใช่ค่า ณ นาทีนั้น และแบตหมด =
นาฬิกามิเตอร์เพี้ยน = `read_at` ผิดทั้งชุด · **battery ที่ล้มไม่นับ strike** (มีแต่ `liveness`
ที่แตะสถานะ device เหมือนที่ M6 ตัดสินให้ billing)
· ⚠️ **interval = 1 ชั่วโมง ไม่ใช่ 1 วัน แล้วให้ job ข้าม device ที่มีแถวของวันนี้แล้ว
(แก้ตอน scrutinize แผน M7)** — `locks.py:87` `try_acquire_background()` *"Never blocks. Refuses
while the endpoint is held or while any Manual Read [is waiting]"* ⇒ tick ที่ไม่ได้ lock **ถูกข้าม
ไม่เข้าคิว** · job รายวันที่ชนกับ LP scheduler หรือคนกด Read now บนสายร่วม จะเสียข้อมูลทั้งวัน
โดยไม่มีรอบสอง (LP รอดเพราะรันทุก 15 นาที มีโอกาสแก้ตัว 96 ครั้ง — แบตมีครั้งเดียว) ·
รายชั่วโมง + ข้ามถ้ามีแล้ว ให้โอกาสแก้ตัว 24 ครั้ง โดย**ไม่เพิ่มการคุยกับมิเตอร์แม้แต่ครั้งเดียว**
และไม่ต้องมีตรรกะ retry แยก

**หน้า Export Format** — พอร์ตจาก `format_settings` ของ v1 แต่**ไม่เอาสองช่อง**:
- ❌ `divide_by_1000` — v1 เก็บเป็น Wh แล้วหารตอนส่งออก · v2 หารตั้งแต่ตอนเขียนลงฐาน (ไดรเวอร์)
  ⇒ ไม่มีอะไรให้หารอีก
  · ⚠️ **CSV เป็น kWh/kvarh เสมอ — ไม่ฟังสวิตช์ kW/W (แก้ตอน scrutinize แผน M7, 2026-08-11)**
  การเคาะรอบแรกให้ไฟล์ตามสวิตช์ ซึ่ง**ผิด**: หัวคอลัมน์เขียนครั้งเดียวตอนสร้างไฟล์ (§3.5 — "สร้าง
  ไฟล์พร้อม BOM + หัว เมื่อไฟล์ไม่มีหรือว่าง") แต่แถวต่อท้ายไปเรื่อย ๆ ⇒ กดสวิตช์เดือนที่ 4 จะได้
  ไฟล์ที่หัวบอก `(kWh)` แต่แถวใหม่เป็น Wh ต่างกัน 1000 เท่าโดยไม่มีอะไรบอก · และคนกดสวิตช์กำลัง
  คิดเรื่อง**หน้าจอ** ไม่มีเหตุให้นึกถึงไฟล์เลย — v1 กันไว้แล้วด้วยการวางปุ่มนี้บนหน้า Export Format
  ซึ่งเป็นบริบทของไฟล์ และการ "รวมสองปุ่มให้เหลือปุ่มเดียว" ทำการกันนั้นหายไป
  > **เส้นแบ่ง**: ไฟล์ที่**เขียนต่อท้ายข้ามเวลา**เป็น *สัญญา* — หน่วยคงที่ · หน้าจอและเอกสารที่
  > **สร้างใหม่ทุกครั้ง**เป็น *มุมมอง* — ตามสวิตช์ได้ · ใช้เส้นนี้ตัดสินทุกครั้งที่มีปลายทางใหม่
- ❌ `output_txt` / `txt_filename_tmpl` — ค่าเริ่มต้นปิดใน v1 ⇒ **เจ้าของต้องถามลูกค้าก่อนตัดถาวร**
- ❌ **`output_csv` — ย้ายมาไว้ในกลุ่มไม่พอร์ต ตอน implement issue #30 (เจ้าของตัดสิน 2026-08-11,
  overrule รายการพอร์ตเดิมด้านล่างที่เคยระบุไว้ผิด)**: grep ทั้ง v1 พบผู้ใช้ค่านี้จุดเดียวคือ
  `use_txt = output_txt and not output_csv` — ตัวเลือก CSV-vs-TXT — และ `output_txt` ไม่ได้พอร์ต
  ⇒ flag ที่ไม่มีใครอ่านอีกต่อไป ทางเดียวที่จะทำให้มันมีความหมายคือ "ปิดแล้วหยุด export" ซึ่งกลายเป็น
  **สวิตช์ตัวที่สองบนแกนเดียวกับ `auto_save_enabled`** — บั๊กแบบเดียวกับที่ ADR 0013 มีไว้กันพอดี
  (คนละไฟล์กับที่ #29 ตัดออกก็ด้วยเหตุผลเดียวกัน — flag ที่ไม่มี driver รองรับ)
- ✅ พอร์ต: `date_format` (พร้อมระบบแปลง token) · `csv_filename_tmpl` (`[meter].csv`) ·
  `auto_save_enabled` · `output_dir`

**หัวคอลัมน์ CSV — แก้ให้ถูก ไม่ลอกที่ผิด** (เจ้าของตัดสิน 2026-08-11) · **ลำดับคอลัมน์เหมือน v1
เป๊ะ** เพื่อให้แถวใหม่ยังลงตรงช่องถ้าชี้ไปที่ไฟล์เดิม:

| v1 | v2 |
|---|---|
| `Import kWh Reactive` | `Import Reactive (kvarh)` — reactive ไม่ใช่ kWh |
| `Export kWh Re` | `Export Reactive (kvarh)` — ผิดทั้งชื่อและหน่วย |
| `Import kWh Active` / `Export kWh Active` | `Import Active (kWh)` / `Export Active (kWh)` |

อีก 10 คอลัมน์คงเดิม · หัวเป็น kWh/kvarh ตายตัวเหมือนแถว (ดูข้อ `divide_by_1000` ข้างบน)

⚠️ **exporter ต้องรวม logger ด้วยฟังก์ชันตัวเดียวกับที่ API หน้า Load Profile ใช้** (พบตอน
scrutinize แผน M7) — commit `eb9bfee` เพิ่งเปลี่ยน logic รวมของหน้านั้นเป็น `outerjoin` + `coalesce`
บน `read_at` ที่ตรงกันเป๊ะ · ถ้า exporter เขียนของตัวเอง วันหนึ่งจะมีคนแก้ที่เดียวแล้วเลขบนจอกับ
ในไฟล์ต่างกัน โดยไม่มีเทสจับเพราะแต่ละฝั่งเทสของตัวเอง ⇒ **เกณฑ์รับงาน: มีเทสที่ยืนยันว่าไฟล์กับ
endpoint ให้แถวเท่ากันบนข้อมูลชุดเดียวกัน** — ✅ **landed with issue #30**: `db/load_profile_query.py`
เป็นฟังก์ชันเดียวที่ทั้งสองฝั่งเรียก และ `test_api_load_profile_export.py::TestEndpointAndFileAgree`
เป็นเทสที่เกณฑ์นี้ต้องการ

**หน้า Holidays**: export/import เป็น **ดาวน์โหลด/อัปโหลดไฟล์ธรรมดา ไม่ใช่ folder picker** —
ADR 0016 วางไว้ว่าใช้ `showDirectoryPicker` โดยอ้างว่าลูกค้าเข้าผ่าน localhost แต่ **v2 เปิดพอร์ต
8000 ให้เข้าจาก LAN** ซึ่งไม่ใช่ secure context ⇒ ปุ่มจะพังทันทีที่เปิดจากเครื่องอื่น ·
ไม่ขัด ADR 0010: capture เป็นไฟล์ที่ server สร้างเองตามรอบจึงต้องรู้ปลายทางล่วงหน้า ส่วนไฟล์วันหยุด
เกิดตอนคนกดปุ่มพอดี · **Import = แทนที่ทั้งชุด + กล่องยืนยันที่บอกจำนวนแถวที่จะหาย** (ลูกค้าใช้คำว่า
"copy" = อยากให้เหมือนกัน; merge จะต้องมีกฎว่าชื่อไหนชนะเมื่อวันซ้ำ ซึ่งไม่มีใครขอ)

**หน้า App Log — ไม่มีอะไรให้พอร์ต** `pages/AppLog/index.tsx` ของ v1 เป็น**หน้าเปล่า**: `logs`
ตั้งเป็น `[]` แล้วไม่มีอะไรมาเติม · ไม่มี fetch · ไม่มีโมดูลหลังบ้าน (grep ได้ศูนย์) · ปุ่ม Refresh
กับ Clear เป็นฟังก์ชันเดียวกันคือ `setLogs([])` ⇒ หน้านี้ขึ้น "No log entries." ตลอดกาล
(หน้าเปล่าหน้าที่สองของ v1 ถัดจาก Instantaneous) ⇒ **"output parity กับ v1" ใช้กับหน้านี้ไม่ได้
ต้องเขียนเกณฑ์รับงานเอง** · v2 ทำเป็น **ตัวอ่านไฟล์ `%ProgramData%\ARICHDS\logs\`** — ท้ายไฟล์ N
บรรทัด · กรองตามระดับ · **ไม่มีตาราง ไม่มีปุ่ม Clear** (ลบหลักฐานชิ้นเดียวที่มีตอนไล่ปัญหา และของ v1
ก็ไม่ได้ลบไฟล์จริงอยู่แล้ว) · ไฟล์ผ่าน redaction filter ตั้งแต่ตอนเขียน (M1) ⇒ อ่านมาโชว์ได้เลย
· ✅ **landed with issue #31 (M7 slice 4)**: `log_reader.py` (the reader counterpart to
`logging_config.py` — header/continuation parsing, filter-before-tail) · `api/logs.py`
(`GET /api/logs`) · `pages/AppLog.tsx`. Decisions the grill text above did not pin down:
**no filename parameter** — the endpoint always reads exactly `settings.log_dir / "arichds.log"`,
never a request-supplied path, so rotated siblings (`arichds.log.1` … `.5`) are unreachable
through the API · **admin-only** — the log's content is machine-internal (usernames, Transport
Endpoints, file paths, tracebacks), unlike the meter data every other read page shows ·
`min_level` is a **minimum**, not an exact match (WARNING returns WARNING+ERROR+CRITICAL) ·
a line that is not a parseable header is joined onto the previous entry's message — the concrete
form of "a traceback survives a level filter", since a traceback is N level-less lines following
one header.

**ห้าก้อนของ M7 และลำดับ** (ให้ `/to-issues` ใช้):

```
1 Holidays + Energy Summary  →  3 Battery  →  2 Export Format + CSV  →  5 App Log  →  4 Energy Registers + Special Days
```

ก้อน 1 ไม่แตะมิเตอร์เลยและเป็นของที่ลูกค้าส่ง mockup มาขอเอง (ADR 0016 — *"ยังเลือกดูไม่ได้"*)
⇒ เริ่มได้ทันทีไม่ต้องพึ่งใคร · **ก้อน 4 อยู่ท้ายเพราะเรื่องการเข้าถึง ไม่ใช่เพราะ dependency**:
มิเตอร์ที่ทำสองฟีเจอร์นี้ได้ (Mitsubishi `192.168.1.31`, TCC `COM3`) **อยู่บนเครื่องลูกค้าทั้งคู่** —
โค้ดเขียนและเทสด้วย fake meter ได้ปกติ แต่การ**ตัดสินว่าเปิดธงให้ TCC กี่รุ่น**ต้องรอผล probe
(`scripts/probe_tcc.py` ตอบทั้งสองข้อในรอบเดียวแล้ว)
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
- **Feature entitlement**: enabled = `.env FEATURES ∩ license features` · sellable 9 ตัว (M7 slice 4,
  issue #35 เพิ่ม `billing_image_export`; เดิม 8 ตัวเท่า v1):
  `billing` `load_profile` `energy_summary` `special_days` **`records`** `battery` `auto_capture`
  `billing_excel_export` `billing_image_export` · ops-only (ใน .env เท่านั้น): `app_log`
  (`api_config` ของ v1 ตายไปกับหน้า ApiConfig)
  — ✅ **`instantaneous` → `records` (เจ้าของตัดสิน grill M6, 2026-08-09)**: หน้าที่คีย์นี้คุมชื่อ
  **Records** ตั้งแต่ grill M3 · คีย์ชื่อเดิมขัด `CONTEXT.md` (ซึ่ง `_Avoid_: instantaneous records`
  ไว้ตรง ๆ) และขัด ADR 0007 ที่ตัดสินว่า v2 **ไม่มีอะไรที่เป็น instantaneous เลย** ·
  เปลี่ยนได้ฟรีเพราะยังไม่มี license ใบไหนระบุ `features` — หน้าต่างนี้ปิดถาวรตอนออกใบแรก
  — ⚠️ **`auto_read_billing` และ `auto_backfill` ถูกถอดออกจาก ops-only**: `auto_backfill` ตายไปกับ
  ADR 0009 (ไม่มี backfill เป็นแนวคิดอีกแล้ว) และ `auto_read_billing` ไม่มีอะไรให้คุม — job billing
  เป็นรายการหนึ่งใน registry ที่ `ARICHDS_POLL_ENABLED` กับ Limited Mode คุมอยู่แล้วเหมือนทุก job
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
- **Data model** (11 ตาราง): `devices` (`transport` เป็น JSON column เดียว — status/strike เป็นคอลัมน์มีชนิด) ·
  `device_events` · `load_profile_readings` (COSEM shape 12 คอลัมน์วัดค่า + `source` + `interval_sec`) ·
  `billing_readings` · `energy_register_readings` · `battery_readings` ·
  `holidays` · `settings` (key/value) · `users` · `user_tokens` · `sync_state`
  — **`billing_captures` ถูกตัดออกที่ grill M6 (2026-08-09)**: มัน**ไม่เคยมีอยู่ใน v1** (grep ทั้งรีโป
  ได้ศูนย์ผลลัพธ์) และถูกนับเข้ามาตอนวางแผนโดยเข้าใจผิดว่ายกมาจาก v1 · v1 ตัดสินไว้ที่
  `billing/docs/adr/0003` ว่า *"ไม่เก็บ path ใน DB — derive จาก convention ทุกครั้ง"* แล้วเดินแบบนั้นจริง
  ⇒ v2 ทำตาม พร้อมเช็คว่าไฟล์มีอยู่จริงตอน list
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
- ~~**`billing_captures`**~~ — ✅ **ปิดแล้วที่ grill M6 (2026-08-09): ไม่สร้างตาราง** · derive path
  จาก convention เหมือน v1 ADR 0003 · จำนวนตารางใน §4 ลดจาก 12 เป็น 11
- **ชะตาของ modbus billing cut** (เปิดที่ grill M6, 2026-08-09) — เจ้าของระบุว่า *"เราไม่มีตรรกะ
  ตัดงวด … เรามีหน้าที่อ่านค่าจาก meter (read only) เท่านั้น"* ซึ่งขัดกับฟีเจอร์นี้โดยตรง: มันคือ
  **การตัดงวดที่ระบบทำแทนมิเตอร์** (แม้จะไม่เขียนอะไรลงมิเตอร์ — มันอ่านค่าสะสมของ modbus logger
  แล้วเขียนแถวใน DB เรา) · ราคาของการยกเลิก: **device ฝั่ง modbus จะไม่มีข้อมูล billing เลยตลอดไป**
  เพราะมิเตอร์กลุ่มนั้นไม่มี billing ProfileGeneric ให้อ่าน — และ v1 บันทึกว่านี่เป็นคำขอจากลูกค้า
  โดยตรง (ux-dual-source ก.ค. 2026) · **ปิดคำถามตอน grill M4b** ก่อนเฟส modbus เริ่ม
- **Portal v2** — timeline ยังไม่กำหนด · M9 บล็อกอยู่จนกว่า portal จะมี `/activate` `/renew` `/redeem`
  ตาม contract ที่ v2 นิยาม (ระหว่างนั้น lease renew ยังทำไม่ได้ → license ที่ออกช่วงนี้ต้องเป็น
  offline mode ไม่มี lease หรือ lease ยาวพิเศษ — **ต้องเลือกก่อนออก license จริงตัวแรก**)
- (assumed) **SMW110 DLMS-over-serial อยู่ในเป้า 5 วัน** — เป็นรุ่น DLMS จึงจัดอยู่เฟสแรก
  แต่ถ้าการต่อ serial จริงช้ากว่าแผน ให้เลื่อนไปกับเฟส modbus ได้โดยไม่กระทบรุ่น TCP
- ~~**ชื่อ feature key `instantaneous`**~~ — ✅ **ปิดแล้วที่ grill M6 (2026-08-09): เปลี่ยนเป็น
  `records`** · ดู §3.9 · ข้อความเดิมเก็บไว้ข้างล่างเป็นบันทึกว่าคำถามนี้เคยค้างมาตั้งแต่ก่อน M5
  > *ข้อความเดิม:* หน้าที่มันคุมถูกเปลี่ยนชื่อเป็น **Records** และย้ายไป M5 (grill M3) แต่ key
  > ยังชื่อเดิมตาม v1 · CONTEXT.md บังคับให้ใช้คำเดียวกันทุกชั้น ⇒ ควรเปลี่ยนเป็น `records` หรือไม่
  > — เป็นการแก้ contract กับ portal ที่ v2 เป็นผู้นิยาม (§3.9) จึงเปลี่ยนได้ฟรี **ตราบใดที่ยังไม่มี
  > license ตัวไหนระบุ `features`** · ต้องตัดสินก่อน M5 และก่อนออก license ที่ใส่ features จริงตัวแรก
  >
  > *คำถามนี้ค้างข้าม M5 มาทั้ง milestone — ไม่มีใครสะดุด เพราะ M5 ไม่ได้ทา gate เลย
  > มันถูกบังคับให้ตอบตอน M6 เพราะ M6 เป็นโมดูลแรกที่สร้าง `require_feature` ขึ้นมาจริง*
