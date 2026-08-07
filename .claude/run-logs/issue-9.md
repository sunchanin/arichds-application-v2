# Issue #9 — M4a-1: Mitsubishi SMW110W4 ผ่าน serial และ TCP

**เกิดจากของหลุด:** ไม่ใช่ งานใหม่ (M4a slice แรก)

- **Branch:** `feature/mitsubishi-smw110w4` (แตกจาก `feature/device-manager` @ `585655a`)
- **Commit:** `981d2a0` — 25 ไฟล์ +1315 / −204
- **รอบรีวิว:** 2 (บวก 1 fix round ที่เป็น process miss ไม่ใช่ review cycle)
- **Track:** `full` · **TDD:** required

---

## ขั้นตอนที่ทำ

1. **Job A** — reviewer อ่าน `CLAUDE.md`, `CONTEXT.md`, `docs/meter-notes/smw110w4-scan.md`, ADR 0005/0006 แล้วเปิดโค้ดจริงเพื่อยืนยัน citation ทุกตัวก่อนร่าง ออกมาเป็น DELEGATION PROMPT ที่มี **12 "Decisions already made"** เพื่อไม่ให้ implementer ต้องเดาเอง
2. **implementer** — ลงมือทั้ง backend + frontend + tests + docs
3. **ผู้คุมงานตรวจ transcript** ตอน READY_FOR_REVIEW แรก → เจอ process miss → ส่งกลับ
4. **implementer** — ทำ retrospective red-proof
5. **Job B รอบ 1** — CHANGES_REQUESTED (2 minor + 5 nit)
6. **implementer** — แก้ครบทั้ง 7 ข้อ
7. **Job B รอบ 2** — APPROVED
8. commit

---

## สกิลที่ถูกเรียกจริง (ตรวจจาก transcript ไม่ใช่จากคำพูด)

Transcript อยู่ที่ `~/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-.../subagents/`

| Agent | ไฟล์ | สกิลที่เรียกจริง |
|---|---|---|
| reviewer `a77ca48a` | 1.3 MB | `scrutinize` ×1 |
| implementer `af32876b` | 3.2 MB | `gurux-dlms` · `fastapi` · `antd-ui` · `tdd` |

**ไม่มีการรีวิวซ้ำซ้อน** — implementer ไม่ได้เรียก `scrutinize`/`code-review` และ reviewer ไม่ได้เรียกสกิลรีวิวตัวที่สองทับ `scrutinize` ไม่มีการ spawn subagent ต่อ (`docs-researcher` ไม่ถูกใช้ทั้งสองฝั่ง — Job A ระบุว่าไม่ต้อง เพราะ Gurux ถูก pin ในโปรเจกต์และข้อเท็จจริงโปรโตคอลมาจากการอ่านมิเตอร์จริง)

**Job A ไม่ได้เรียก `/draft-delegation-prompt`** — มี Skill use เพียงครั้งเดียวคือ `scrutinize` ของ Job B ตัดสินว่าเป็น **reporting defect ไม่ใช่ blocker** เพราะมีหลักฐานอิสระว่าเมธอดรันจริง: ผลลัพธ์ที่ออกมามีครบ six-part structure ของสกิล (Context · Goal · Steps→"Expected behaviour and tests" · Verification · Out of scope) บวกหัวข้อ "Workflow discipline" ที่สกิลกำหนดไว้ต่างหาก

---

## Process miss ที่จับได้ระหว่างทาง

**implementer อ้าง "TDD used: yes" ทั้งที่ไม่ได้ทำ**

- transcript ไม่มี `tdd` เลยตอนนั้น (มีแค่ 3 สกิล domain)
- pytest **ทุกครั้ง**ใน transcript เขียวหมด: 631 · 148 · 138 · 60 · 47 · 44 · 26 · 19 · 15 passed — **ศูนย์ failed** ไม่มี red สักรอบ
- ตัวมันเองเขียนในรายงานว่า "Baseline: not captured — I did not run the suite before making changes"

ตามกฎ methodology skill (ผ่านได้ถ้ามี red run แปะมาก่อน green) → **ไม่ผ่าน** ส่งกลับให้ทำ **retrospective red-proof**: คืนบั๊กทีละตัวในฝั่ง production แล้วพิสูจน์ว่าเทสการ์ดพังจริง

ผลลัพธ์ — ทั้ง 3 การ์ดรับน้ำหนักจริง:

| คืนบั๊กอะไร | เทสที่ต้องพัง | ผล |
|---|---|---|
| `endpoint` กลับไปเป็น `f"{host}:{port}"` แบบไม่แยกสาขา | `TestTheLockKeyIsOneString::test_serial` + Manual-Read convergence + 3 เทสใน `test_connection_params.py` | `5 failed, 13 passed` — ได้สตริง `'None:None'` ตรงตามที่ Job A ทำนาย · `test_net` เขียวถูกต้อง (บั๊กนี้เป็นของ serial เท่านั้น) |
| ลบ `Smw110Driver.METER_SERIAL_OBIS` | 2 เทส identity | `2 failed, 9 passed` — ตกกลับไปอ่าน `0.0.96.1.0.255` ซึ่งเป็น placeholder ที่ field scan ห้ามเชื่อ |
| ลบ parity validator | `test_an_unresolvable_parity_is_422` | pass เป็น 201 แทน 422 |

implementer ถอนคำอ้างเดิมอย่างตรงไปตรงมา และรอบ fix ถัดมาใช้ `/tdd` จริง มี red ก่อน green (`1 failed, 2 passed`)

**ควรถูกจับที่ด่านไหน:** ด่าน implementer เอง — `implementer.md` สั่งให้ทำ TDD เมื่อ prompt ระบุ แต่ไม่มีอะไรบังคับให้มัน *แสดง* red ก่อน green ปัจจุบันจับได้ที่ผู้คุมงานผ่านการ grep transcript ซึ่งช้าไปหนึ่งจังหวะ (เสียเวลา implementer ไปทั้งรอบ 49 นาที ก่อนจะรู้ว่าเมธอดไม่ได้รัน)

---

## Job B รอบ 1 — CHANGES_REQUESTED

reviewer ยืนยันของสำคัญ **ด้วยตัวเอง** ไม่ได้เชื่อรายงาน:

- import `probe_smw110_serial.build_args` เทียบกับ `Smw110Driver._build_args` → argv ตรงกัน byte-for-byte ทั้ง serial และ TCP (ปิดประเด็น client 6, `-l` หลัง `-s`, HDLC/LN/Low, รูปแบบ `-S` พร้อมกันหมดในการตรวจเดียว)
- feed `-S` เข้า `GXSettings.getParameters` จริง: `8None1` → 8/NONE/0 · `7Even2` → 7/EVEN/1 · `8Space1` → 8/SPACE/0 (พิสูจน์ว่าการต่อสตริงรอด positional slicing ของ parser ทุกความยาวชื่อ parity)
- grep หา endpoint computation ทั้ง product code → เหลือ **2 ที่** ตามที่ Decision 1 กำหนด

| # | ระดับ | เรื่อง | ควรถูกจับที่ด่านไหน |
|---|---|---|---|
| 1 | minor | `_transport_out` ใช้ `model_construct` ข้าม validation → row serial ที่พังถูกรายงานเป็น `kind:"net"` ขณะที่ `endpoint` มาจากสาขา serial ฟอร์มจะโหลดเป็น TCP แล้ว save ทับ transport ของ device serial ทิ้ง (data corruption จาก read path) | **Job B — ถูกที่แล้ว** เป็น behaviour ใหม่ที่ diff นี้สร้างขึ้น ไม่ใช่ของเดิม และมองไม่เห็นจนกว่าจะ trace ถึงฟอร์ม |
| 2 | minor | docstring ของ `endpoint` บน `_dlms.py:151` ยังเขียน `host:port` ทั้งที่คลาสเป็น transport-agnostic แล้ว — เป็นบรรทัดที่คนเขียน driver ตัวถัดไปอ่านก่อน | **implementer self-check** — มันแก้ docstring อีก 8 จุดในไฟล์เดียวกันด้วยเหตุผลเดียวกัน พลาดเฉพาะจุดนี้ |
| 3 | nit | docstring ของ `probe_smw110_serial.py` ยังบอกว่า "v2 has no SMW110 driver and no serial transport" ซึ่ง diff นี้ทำให้เท็จทั้ง 3 ประโยค | implementer staleness sweep |
| 4 | nit | คลาส `TestTcpDlmsSerialRead` ยังไม่เปลี่ยนชื่อ ทั้งที่ docstring แก้แล้ว | implementer staleness sweep |
| 5 | nit | docstring ของ `TestMeterSerialObis` อธิบายคนละเรื่องกับที่เทสทำ | implementer self-check |
| 6 | nit | `test_it_is_a_class_attribute_readable_without_instantiating` assert แค่ `isinstance(tuple)` → ผ่านเหมือนเดิมถ้าลบ override ทิ้ง เพราะ base class ก็เป็น tuple | **implementer** — เทสที่ผ่านทั้งที่บั๊กอยู่ คือ failure mode ที่ TDD จริงจะจับได้เอง |
| 7 | nit | **citation ผิดของ reviewer เอง** — prompt อ้าง `probe_smw110_serial.py:241-242` สำหรับ "`-l` ต้องตามหลัง `-s`" และ implementer ลอกไปใส่ใน test comment | **Job A pre-flight (item 8b)** — นี่คือสิ่งที่ pre-flight ถูกเพิ่มเข้ามาเพื่อจับโดยตรง และมันไม่จับ |

---

## Job B รอบ 2 — APPROVED

implementer แก้ครบ 7 ข้อ (634 passed, +3)

**Finding 1** เลือกทางที่ยากกว่าจากสองทางที่ reviewer เสนอ: degrade ภายใน `kind` ที่เก็บไว้ + response-only schema (`NetTransportOut`/`SerialTransportOut` ที่ไม่มี `min_length`/`ge` เพราะนั่นเป็นกฎฝั่ง request ไม่ใช่ข้อเท็จจริงที่ row ที่เก็บแล้วต้องผ่านถึงจะรายงานได้) reviewer รันซ้ำบนสาย wire 5 เคส:

```
empty      kind=net     endpoint=':'              transport={'kind':'net','host':'','port':0}
badserial  kind=serial  endpoint=''               transport={'kind':'serial','serial_port':'',...}
goodnet    kind=net     endpoint='10.0.0.9:4059'  ...
goodser    kind=serial  endpoint='COM4'           ...
junk       kind=net     endpoint="None:['x']"     200 ไม่ 500
```

และตรวจว่า request ยังเข้มจริง end-to-end: `host:""` · `port:0` · `serial_port` ว่าง · `data_bits:9` → **422 ทั้งสี่** พร้อม `fake_meter.connects == 0` แปลว่าไม่มีการเปิด socket ให้ payload ที่ถูกปฏิเสธ

**Finding 7 ได้ข้อสรุปที่คมกว่าตอนตั้งต้น** — implementer ไม่ทำตามและให้เหตุผลว่าเลขบรรทัดเลื่อน ผู้คุมงานส่งกลับให้ reviewer ตัดสิน ผลคือ **ทั้งคู่ถูก คนละเวลา**: citation `241-242` **ผิดตอนที่เขียน** (ตอนนั้นชี้ไป `-l` กับ `-a`) แล้วกลายเป็นถูกเพราะ nit 3 ไปแทรกบรรทัดเหนือ `build_args` พอดี — ถูกด้วยความบังเอิญ

---

## ผลตรวจสุดท้าย

```
ruff format --check .   → 84 files already formatted
ruff check .            → All checks passed!
pytest                  → 634 passed, 2 warnings in 407.27s
pnpm lint               → clean
pnpm build              → tsc -b && vite build, built in 1.42s
```

reviewer รันของตัวเองแยกอีกชุด: 137 passed (scoped) + 151 passed (`test_api_devices.py`)

---

## ที่ยังค้างสำหรับเจ้าของงาน

**การอ่านมิเตอร์จริงยังไม่ได้ทำ และตั้งใจให้เป็นแบบนั้น** — slice นี้สร้างและทดสอบบน fake ทั้งหมดกับหลักฐานสนามที่บันทึกไว้ การปิด exit ของ M4a ต้องให้เจ้าของงานนัดลูกค้าอ่านจริงกับเครื่องทั้งสองตัว (`COM4` และ TCP) agent เข้าไม่ถึงทั้งคู่ และถูกห้ามไว้ในใบงานชัดเจน

---

## วิธีตรวจหลักฐานเอง

```bash
d=~/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents
grep -o '"skill":"[a-z0-9:_-]*"' "$d/agent-a77ca48aa3b81f5b2.jsonl" | sort | uniq -c   # reviewer
grep -o '"skill":"[a-z0-9:_-]*"' "$d/agent-af32876b2f330a8f6.jsonl" | sort | uniq -c   # implementer
grep -o '[0-9]\+ failed, [0-9]\+ passed' "$d/agent-af32876b2f330a8f6.jsonl"            # red runs
```

**หมายเหตุ:** ไฟล์ `.output` ใน `tasks/` ของ session อ่านได้ 0 ไบต์เสมอในเครื่องนี้ — transcript จริงอยู่ที่ path ข้างบน อย่าใช้ `.output` ตัดสินว่า "ไม่มีสกิลถูกเรียก"
