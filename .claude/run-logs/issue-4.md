# Audit log — Issue #4: M3-1 shared priority lock, probe-first CRUD, catalog, quota

รัน: 2026-08-05 · branch: `feature/device-manager` · ผลลัพธ์: **APPROVED** · รอบรีวิว: **2** · commit: `65338e2`

## ทำอะไรไปบ้าง (ทีละขั้น)

1. **reviewer (Job A) — สร้าง delegation prompt** · TDD required: **yes**

   เหตุผลที่ reviewer ให้: สไลซ์นี้เปลี่ยน **semantics ของ concurrency** (priority lock ที่เขียนเอง
   คือจุดเดียวใน v2 ที่พฤติกรรม lock ไม่ใช่ค่า default ของภาษา) และเพิ่มเส้นทางปฏิเสธที่คุณค่าทั้งหมด
   อยู่ที่ **"ต้องไม่มีแถวถูกเขียน"** — สองอย่างนี้มองด้วยตาไม่เห็น ต้องมีเทสก่อนโค้ดถึงจะตรึงได้

   **reviewer ตัดสิน 14 ข้อแทน (D1–D14)** ทุกข้อมีเหตุผลกำกับ ที่สำคัญ:
   - **D3 `poll_once` คืน `TickOutcome` (STORED/FAILED/SKIPPED)** แทน `int | None` — เพราะ ADR 0006
     บอกว่า tick ที่ถูกข้ามต้องไม่นับเข้ากฎ 3 ครั้งติดของใบ #5 ถ้าทั้งคู่คืน `None` ใบ #5 จะไม่มีสัญญาณ
     ที่ซื่อสัตย์ และการกด Read now จะกลายเป็นวิธีทำให้มิเตอร์ตัวเองขึ้น Offline
   - **D4 กรอง device ที่ resolve driver ไม่ได้ที่ `Poller.start()`** ไม่ใช่ที่ `poll_once` — ได้ผลเหมือนกัน
     (log ครั้งเดียวต่อ start) โดยไม่ต้องมี memo state ต่อ device และ device ที่ใช้ไม่ได้ไม่กิน thread
   - **D5 ย้าย `read_meter_serial` ไป `TcpDlmsDriver` + class attribute** — แย้ง issue ที่สั่งให้ทำบน
     `Prometer100Driver` เหตุผล: อีก 8 รุ่นที่ M4 ใช้โค้ดเดียวกันเป๊ะ มีแค่ SMW110 ที่ OBIS ต่าง
     ซึ่ง class attribute ครอบให้แล้ว (v1 `smw110.py:172` พิสูจน์รูปแบบนี้) ถ้าวางที่ leaf = การันตี
     ว่าจะมี 8 สำเนาที่ M4
   - **D7 probe ล้ม = failure envelope + 502** ไม่ใช่ HTTPException — เพราะ `api.ts` อ่าน
     `error.code/message/reason` **ก่อน**ดู HTTP status อยู่แล้ว จึงได้สาเหตุที่เครื่องอ่านได้โดยไม่ต้อง
     แก้ client และ 502 ตรงความหมาย (อุปกรณ์ต้นทางพัง ไม่ใช่ request ผิด)
   - **D13 migration hardcode รายชื่อรุ่น ห้าม import `supported_models()`** — migration ต้องแช่แข็ง
     โลก ณ วันที่เขียน ไม่งั้นวันที่ M4 เพิ่ม 8 รุ่น migration เดิมจะทำงานต่างออกไปบนเครื่องที่ยังไม่ได้รัน

2. **implementer — ลงมือ (`/tdd`)** · เทส **313 → 458 (+145)**
   - ไฟล์ใหม่: `locks.py` · `catalog.py` · `probe.py` · migration `0003` · `tests/fakes.py` + 4 โมดูลเทส
   - ลบ `simulated.py` ออกจากตัวสินค้า · เทสใช้ fake driver ผ่าน monkeypatch `_registry`
   - **probe มิเตอร์จริงสำเร็จ**: `203.170.151.152:4059` → `serial WP079074` latency 237 ms
   - **รายงานความผิดพลาดของตัวเองโดยไม่มีใครถาม**: เผลอรัน `alembic upgrade head` ซึ่ง resolve ผ่าน
     `env.py` ไปที่ `app/data/arichds.db` ตัวจริง (prompt สั่งห้ามแตะ) แล้ว downgrade กลับพร้อม verify

3. **reviewer (Job B รอบ 1) — CHANGES_REQUESTED** (1 major + 1 minor + 3 nit)
   - **[major] priority lock ไม่มีเทสคุมครึ่งที่สำคัญ** — reviewer ไม่ได้แค่บอกว่าเทสไม่ครอบ แต่
     **ลบกฎออกจากโค้ดจริงแล้วรันทั้งชุด**: `16 passed` · `51 passed` — เทส "priority" ทุกตัวถือ lock
     ไว้ก่อนแล้วค่อย assert ซึ่ง mutual exclusion ธรรมดาก็ผ่านหมด · สถานะที่ `_manual_waiting` มีผล
     มีอยู่สถานะเดียว (**lock ว่าง + มีคนรอ**) และไม่มีเทสไหนสร้างมัน · reviewer วัดเทสที่เสนอให้ด้วย:
     **0/300 กับโค้ดจริง · 300/300 เมื่อลบกฎ**
   - **[minor] `probe_meter` รอ lock แบบไม่มี timeout อยู่ใน HTTP handler** — background tick ถือ
     endpoint ตลอด connect + อ่าน 8 register (retry 3 × timeout 30/60 วิ) มิเตอร์ที่กำลังตายถือได้เป็นนาที
     ระหว่างนั้น `POST /api/devices` ค้างใน threadpool ไม่ตอบอะไร — และ "มิเตอร์ไม่ตอบ" คือโหมดพัง
     ที่พบบ่อยที่สุดของโปรแกรมนี้
   - reviewer ไปตรวจ **dev DB ที่ implementer เผลอ migrate เอง** ยืนยัน byte-identical กับ snapshot
     ที่มันถ่ายไว้ก่อนเริ่ม ไม่มี index ตกค้าง ไม่มีคอลัมน์เหลือ · induce probe ล้มทั้ง 4 แบบด้วย password
     จริงเพื่อตรวจว่าไม่มีรหัสหลุด · รัน 275 เทสเองรวมไฟล์ที่ไม่ได้แก้

4. **รอบแก้ (cycle 2)** — implementer เพิ่มเทส discriminator + `MANUAL_READ_LOCK_TIMEOUT_SEC = 120.0`
   + แปลง `TimeoutError` เป็น `ProbeError(TIMEOUT)` · เพิ่ม tripwire ใน docstring ชี้ชื่อเทสที่ตรึงกฎไว้
   - deviation ที่รายงานเอง: snippet ของ reviewer closure ทับ loop variable ซึ่ง ruff `B023` ปฏิเสธ
     → bind เป็น default argument แทน
   - **reviewer ทำ mutation เองไม่เชื่อคำบอกเล่า**: `1 failed, 16 passed` (เทสใหม่เป็นตัวเดียวที่รู้ว่ากฎหาย)
     · รันเทสใหม่ **20 รอบ × 50 = 1,000 รอบ ไม่ล้มสักครั้ง** พิสูจน์ว่า flaky ด้านเดียว
     · สร้าง driver ที่โยน `TimeoutError` จาก `connect()` และ `read_meter_serial()` เพื่อพิสูจน์ว่าข้อความ
     "สายไม่ว่าง" ไม่มีทางไปโผล่กับมิเตอร์ที่แค่ช้า → **APPROVED**

## ✅ skill ที่เรียกจริง — ยืนยันจาก transcript

ครั้งนี้ transcript **ไม่ว่าง** (1.2 MB / 2.0 MB) ต่างจากใบ #1–#2 — เพราะ grep หลัง agent จบแล้ว
ไม่ใช่ตอนมันเพิ่งตอบ (ดู memory `subagent-transcripts-often-empty`)

| agent | skill |
|---|---|
| reviewer `ab7a8123991988ff7` | `draft-delegation-prompt` ×1 · `scrutinize` ×1 · `code-review` ×1 |
| implementer `a06a005129b6fd000` | `tdd` ×1 · `fastapi` ×1 · `antd-ui` ×1 |

**ครบทุกตัวที่ reviewer บังคับไว้ใน delegation prompt** — ไม่มี process miss

## Gates

`464 passed` · `ruff format --check` 72 files · `ruff check` clean · `pnpm lint` clean · `pnpm build` ✓
· probe มิเตอร์จริงได้ serial · migration พิสูจน์บนสำเนา DB ที่มีแถว `sim` จริง

## Commit

`65338e2` — `feat: shared priority endpoint lock, probe-first device CRUD, catalog and quota (#4)`
· 29 ไฟล์ +3,611/−530

## Nit คงค้าง (ไม่ block — ตัดสินตอน merge)

1. `GET /api/devices/models` ตอบ **405 ไม่ใช่ 404** เพราะ `PUT/DELETE /{device_id}` match path ก่อน
   (`api/devices.py:583,681`) — endpoint ถูกลบจริง ไม่มีผู้เรียกเหลือ
2. `list_catalog` รับ `session: SessionDep` โดยไม่ใช้ (`api/devices.py:453`) เปิด DB session ทิ้งทุก
   request สำหรับ response ที่เป็นค่าคงที่ — สืบทอดมาจาก `list_supported_models` ของ M1
3. `fake_meter` ไม่ใช่ autouse (`tests/conftest.py:53`) — ถูกต้องวันนี้ แต่เทสใหม่ที่ลืมขอ fixture
   จะเปิด TCP จริงไปยัง host ที่ payload ระบุโดยเงียบ ๆ
4. quota ใช้ `used >= max_meters` ปฏิเสธการสร้าง แต่ `used > max_meters` สำหรับ `over_quota` —
   ตั้งใจ และมีเทสตรึงไว้แล้ว (`test_exactly_at_the_limit_refuses_but_is_not_over_quota`)

## สิ่งที่เกิดขึ้นนอกไปป์ไลน์ระหว่างใบนี้ (กระทบใบ #5/#6)

- **ADR 0007** — เจ้าของตัดสินว่า v2 **ไม่มีหน้าแสดงค่าสด** ⇒ Monitor เป็นนั่งร้าน ต้องถอดที่ใบ #6 ·
  poller tick อ่าน serial เพื่อพิสูจน์ว่ามิเตอร์ยังอยู่ แล้วทิ้ง · เลิกเขียนแถว instantaneous · **ไม่มี cache**
  ⇒ `TickOutcome.STORED` จะกลายเป็นชื่อโกหกและต้องเปลี่ยน
- **`docs/meter-notes/`** — probe มิเตอร์จริง 3 รุ่นแล้วพบว่า SPEC §3.5 ผิด 3 ข้อ (merge Logger 1/2
  ทำไม่ได้) ⇒ ตารางที่ M5 จะสร้างต้องมี `logger_id`

**ใบ #5 และ #6 ต้องแก้เนื้อหาก่อนรัน** — batch หยุดที่นี่ตามคำสั่งเจ้าของ

## วิธีตรวจซ้ำด้วยตัวเอง (audit)

    T="%LOCALAPPDATA%/Temp/claude/C--Users-HP-Documents-Work-arichds-application-v2/e6d49371-8cab-471a-be73-524d52bc5b24/tasks"
    grep -o '"skill":"[a-z:_-]*"' "$T/ab7a8123991988ff7.output" | sort | uniq -c   # reviewer
    grep -o '"skill":"[a-z:_-]*"' "$T/a06a005129b6fd000.output" | sort | uniq -c   # implementer
    git show 65338e2 --stat
