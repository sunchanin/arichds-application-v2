# Audit log — Issue #015: Let a licence name which meter models the machine may add

รัน: 2026-08-27 · branch: `feature/light-modules` · ผลลัพธ์: **APPROVED** · รอบรีวิว: **2**
เกิดจากของหลุด: ไม่ใช่ — งานใหม่ เจ้าของสั่งเมื่อ 2026-08-27 ("สามารถเลือกให้ license ล็อคยี่ห้อของ meter ด้วยได้ไหม" → "สามารถเลือกได้ถึงจำนวนรุ่นเลยไหม")

## ทำอะไรไปบ้าง (ทีละขั้น)

1. **reviewer (Job A) — สร้าง prompt** (`/draft-delegation-prompt`)
   - Track: **full** — เปลี่ยนพฤติกรรมข้ามชั้น (payload ที่เซ็น → verifier → license service → API handler สองตัว → status API → SPA → vendor CLI → เอกสารสองไฟล์) และมีกฎที่แตกกิ่งหลายทาง (`None`/`[]`/`""`, Create/Update, union/dedup/sort)
   - TDD required: **yes** — ทุก decision D1–D8 เป็นพฤติกรรมที่มีเทสต์แยกแยะได้ และสามข้อ (`None` vs `[]`, licence ใบก่อนเปลี่ยน, "ปฏิเสธก่อนเปิด socket") เป็นชนิดที่ถ้าเขียนเทสต์ทีหลังจะผ่านโดยบังเอิญ
   - Workflow discipline: `fastapi` (ด่านใหม่ + `LicenseServiceDep` บน `update_device` + ฟิลด์ `LicenseStatus`), `antd-ui` (`LicenseCard`), และระบุชัดว่า `gurux-dlms` **ไม่** เกี่ยว
   - **reviewer ตรวจทุก citation ในตัว issue กับไฟล์จริง** แล้วเจอว่า D5 ผิด 1 จุด (ดูหัวข้อถัดไป)

2. **implementer — ลงมือ + ตรวจตัวเอง** (`/tdd` + self-check สองด่าน: error-path audit, empty/absent/zero-value trace)
   - ไฟล์ที่เปลี่ยน (14 tracked + 1 ใหม่): `licensing/activation_code.py`, `licensing/service.py`, `api/devices.py`, `api/license.py`, `tools/arichds_vendor.py`, `web/src/api.ts`, `web/src/components/LicenseCard.tsx`, `app/tests/conftest.py`, `test_activation_code.py`, `test_api_devices.py`, `test_license_roundtrip.py`, **`test_vendor_sign_models.py` (ใหม่)**, `SPEC.md`, `CONTEXT.md`, `README.md`
   - รวม **670 insertions / 16 deletions**
   - รัน mutation table ครบ **19/19 แถว** ด้วย copy → mutate → restore (ยืนยันการคืนค่าด้วย hash) ไม่ใช้ `git checkout` แม้แต่ครั้งเดียว
   - self-check เจอเหนือ nit: ไม่มี — แต่**ชูสองเรื่องแทนที่จะเงียบ**: `README.md` stale อยู่ก่อนแล้ว (ไม่แก้เพราะอยู่นอก list ของ prompt) และเห็นด้วยว่า `devices.brand` ควรมี issue ของตัวเอง
   - ผลรันเทสต์: **1903 passed / 57 skipped ใน 75.82s** (baseline ก่อนแก้: 1869/57) · `ruff format --check` 218 files formatted · `ruff check` ผ่าน · `pnpm lint` ศูนย์ problem · `pnpm build` ✓

3. **reviewer (Job B) รอบ 1 — รีวิว** (`/scrutinize`)
   - verdict: **CHANGES_REQUESTED** — 2 minor + 3 nit
   - **ไม่เชื่อรายงาน รันเองซ้ำ**: อ่าน `git diff` เต็มรวมไฟล์ untracked, รันเทสต์เอง 387 ตัว, `pnpm lint`/`pnpm build` เอง, และ**ยิง input โหดใส่ CLI เอง 8 แบบ** ที่เทสต์ไม่ครอบคลุม (`--models "prometer100,"`, `--brands "cewe,"`, ค่าเว้นวรรคล้วน, `Prometer100`, `CEWE`, เอา brand ใส่ช่อง model และกลับกัน) — **ทุกอันปฏิเสธก่อนเซ็น** ไม่มีทางไหนได้ `models: []` หรือ `null` แบบเงียบ
   - **ควรถูกจับที่ด่านไหน**:
     - **P1 `README.md` stale** → **โจทย์ Job A เอง** — Step 8 ระบุเอกสารไว้ 2 ไฟล์และ **ไม่ได้แนบ count valve** · reviewer ประกาศเป็นความผิดตัวเองบนบันทึกและยกข้อห้ามแบบแคบ · implementer เจอและรายงานถูกต้องแล้ว ไม่ใช่ความผิดมัน
     - **P2 case-insensitivity ไม่มีเทสต์คุ้ม** → **ไม่มีด่านก่อนหน้าจับได้ นอกจาก mutation** — ทั้ง 11 เทสต์เขียวภายใต้ mutation `model.lower()` → `model` · reviewer พิสูจน์ว่าเข้าถึงได้จริงโดยเรียก `_require_known_model("Prometer100")` ตรงๆ แล้วพบว่า**ผ่าน** แปลว่า operator ที่พิมพ์ตัวใหญ่บนเครื่องที่มี licence ถูกต้องจะโดนปฏิเสธ พร้อมข้อความที่ระบุรุ่นที่อยู่ใน licence ของเขาเอง
     - **P3 ลำดับใน error message ไม่ถูก pin** → self-check ของ implementer ควรจับได้ (assertion เช็คแค่ membership)
     - **P4 `create_device` อ่าน licence สองครั้ง** → self-check 4a ของ implementer ควรจับได้
     - **P5 เทสต์ licence ใบเก่าไม่ assert `models is None`** → self-check ของ implementer ควรจับได้ (assert สิ่งที่มันมีไว้พิสูจน์)

4. **รอบแก้ 1:** orchestrator ส่ง problems verbatim ตรงให้ implementer (ไม่ผ่าน Job A ซ้ำ) → แก้ครบ 5 ข้อ → reviewer Job B รอบ 2
   - **implementer จับ false positive ของตัวเองได้ก่อนรายงาน**: เทสต์ pin ลำดับข้อความรอบแรกใช้ list 2 ตัว ซึ่ง `sorted()` กับ `reversed()` ให้สตริงเดียวกัน — เทสต์จึงแยกแยะไม่ได้เลย · เปลี่ยนเป็น 3 ตัวแล้วยืนยันแดงจริง
   - `.lower()` ฝั่ง licensed ถูก**ลบทิ้งพร้อมเขียนเหตุผลใน docstring** แทนเขียนเทสต์คุ้ม dead code — ตามที่ reviewer สั่งว่าอย่าเพิ่มเทสต์เพื่อปั๊มตัวเลข
   - Job B รอบ 2: **APPROVED** · reviewer รัน mutation ซ้ำเองทั้งสองอันที่เคยเขียว → **แดงทั้งคู่** · บวก probe ใหม่ของตัวเองอีก 2 อัน (`payload.get("models") or []` ทำให้ 2 เทสต์แดง — พิสูจน์ว่าเส้นแบ่ง `None` vs `[]` ที่ D2 ยืนอยู่ ถูก pin จริง; ตัด `license_state` ออกจาก `_enforce_quota` ทำให้ 3 เทสต์ `TestQuota` แดง — พิสูจน์ว่า nit P4 ไม่ได้พังด่านเดิม)
   - เทสต์สุดท้าย: **1904 passed / 57 skipped**

## ข้อผิดพลาดในตัว issue ที่ reviewer จับได้ (ไม่ได้แก้ไฟล์ issue — เป็นมาตรฐานที่ใช้ตัดสิน)

D5 เขียนว่า *"licence ที่เซ็นบนเครื่องนี้เมื่อ 2026-08-27 สำหรับ `f46b6763…b57e0`"* — **ผิดทั้งวันที่และ machine ID**
- `grep -rn "f46b6763" .` ทั้ง tree เจอที่เดียวคือบรรทัด 107 ของ issue เอง (ใบนั้นเซ็นให้เครื่อง**ลูกค้า** ไม่ได้ติดตั้งที่นี่)
- ใบที่ติดตั้งจริงคือ `C:\ProgramData\ARICHDS\license\license.lic` (491 ตัวอักษร) ของ `50aa2362…` ออกเมื่อ `2026-08-26T08:20:10Z`, `mode: offline`, `expires_at: null`, `max_meters: null`, `features: ["load_profile","billing","database_destination"]` — **ไม่มี key `models`**
- **ข้อสรุปของ D5 ถูกและตอนนี้ยืนยันกับไฟล์จริงแล้ว** — ไม่มี licence ใบไหนในสนามที่มี key `models` ดังนั้นการใส่มันลง `_REQUIRED_FIELDS` จะทำให้ทุกใบพังจริง
- prompt สั่งให้ใช้ licence ใบจริงนั้นเป็น **literal constant** ในเทสต์ (`PRE_MODELS_LICENCE`) ไม่ใช่สร้าง payload ปลอมที่ลบ key ออก — เพราะ payload ปลอมพิสูจน์อะไรไม่ได้เกี่ยวกับโค้ดที่อยู่ในมือลูกค้า · และต้องส่ง `public_key_pem=` เอง เพราะ `_trust_vendor_key` ใน conftest เป็น **autouse** และ patch ตัวโหลดคีย์ทิ้ง

## decision ที่ reviewer ปิดให้ (issue เปิดค้างไว้)

| | ตัดสินว่า | เหตุผล |
|---|---|---|
| D7 `GET /api/devices/catalog` | **ไม่กรองตาม licence** | มันป้อน `Battery.tsx` ด้วย ซึ่งเป็นเรื่อง *ความสามารถ* ไม่ใช่สิทธิ์ · ภายใต้ D6 มิเตอร์รุ่นที่ licence ไม่ครอบยังถูก poll และยังผลิตข้อมูล — กรองแล้วหน้า Battery จะทิ้งเครื่องที่ข้อมูลยังไหลอยู่ · และการซ่อนตัวเลือกไม่ได้บอก operator ว่าทำไม |
| status code | **422** | ตรงกับ `_require_known_model` ที่ตอบคำถามเดียวกันกับฟิลด์เดียวกัน · 403 ถูกจองโดย role guard + Limited Mode · 409 แปลว่า "ชนกับ state ที่มีอยู่" ซึ่งลบ device แล้วหาย แต่ลบยังไงก็ไม่ทำให้รุ่นนั้นมี licence |
| ชื่อฟิลด์ API | `licensed_models` ดิบ ไม่ resolve | `enabled_features` ต้อง resolve เพราะรวมสองแหล่ง (`.env FEATURES ∩ licence`) · models มีแหล่งเดียว |
| label map ใน TS | **ไม่มี** | `test_nav_feature_contract.py` มีอยู่เพราะ `features.ts` เคยผิดกฎนี้ครั้งหนึ่ง — map ใหม่จะสร้างสัญญาข้ามภาษาอันที่สองที่ต้องมี tripwire ของตัวเอง |

## ต้นทุน (เวลา + tokens ต่อสเตจ)

| สเตจ | เวลา | tokens |
|---|---|---|
| reviewer Job A | 10.5 นาที (630s) | 144,379 (harness `subagent_tokens`) |
| reviewer Job A — background search ปิดท้าย | ไม่ได้วัดแยก (แจ้งกลับเป็นค่าสะสม 1,884s) | 158,700 สะสม |
| implementer (build) | 28.6 นาที (1,718s) | 355,160 สะสม |
| reviewer Job B รอบ 1 | 9.0 นาที (541s) | 217,463 สะสม |
| รอบแก้ 1 — implementer | 7.6 นาที (456s) | 355,517 สะสม |
| รอบแก้ 1 — reviewer Job B รอบ 2 | 5.1 นาที (309s) | 240,282 สะสม |

**คำเตือนเรื่องตัวเลข token — อย่าเอาไปบวกกัน** `subagent_tokens` ที่ harness แจ้งเป็น**ค่าสะสมต่อ agent** ไม่ใช่ต่อรอบ (สังเกตจาก implementer: 355,160 → 355,517 หลังทำงานเพิ่ม 7.6 นาที ซึ่งเป็นไปไม่ได้ถ้าเป็นค่าต่อรอบ) · ค่าจริงต่อ agent คือตัวสุดท้าย: reviewer **240,282**, implementer **355,517**
การ grep `output_tokens` จาก transcript ให้ผลที่**ขัดแย้งกันเองและใช้ไม่ได้**ในรอบนี้ — reviewer ได้ 25,809 จาก 131 turn ส่วน implementer ได้ 9,601 จาก 433 turn ซึ่งกลับหัวกับความจริง (implementer เขียนโค้ด 670 บรรทัด) · น่าจะเพราะ transcript บันทึกเป็น streaming delta · **บันทึกไว้ว่าวัดไม่ได้ ไม่ใช่เดา**
เวลาที่แจ้งกลับก็ไม่สม่ำเสมอ: รอบที่ resume ด้วย `SendMessage` ดูเป็นเวลาต่อรอบ แต่ Job A รอบสองเป็นค่าสะสมตั้งแต่ spawn

## ✅ skill ที่เรียกจริง — ยืนยันจาก transcript (tamper-proof)

```
reviewer  (agent-a0eef22b68d1b7f5d.jsonl, 628,111 bytes)
      1 "skill":"draft-delegation-prompt"
      2 "skill":"scrutinize"
    Skill calls ทั้งหมด: 3

implementer (agent-a73166d6f412416ca.jsonl, 1,916,928 bytes)
      1 "skill":"antd-ui"
      1 "skill":"fastapi"
      1 "skill":"tdd"
    Skill calls ทั้งหมด: 3
```

**ไม่มีการรีวิวซ้ำซ้อน** — implementer ไม่ได้เรียก `scrutinize`/`code-review` บนงานตัวเอง · reviewer เรียก `scrutinize` 2 ครั้งซึ่งถูกต้อง (Job B รอบ 1 และรอบ 2) ไม่ใช่การซ้อนสกิลรีวิวสองตัวในรอบเดียว
**skill ที่ prompt บังคับถูกเรียกครบทั้ง 3** (`tdd`, `fastapi`, `antd-ui`) — ตรวจตั้งแต่ implementer รายงาน READY_FOR_REVIEW ครั้งแรก ไม่ได้รอถึงตอนเขียน log

**หมายเหตุเรื่อง path ของ transcript** — `output_file` ที่ harness คืนมาตอน spawn (`…\Temp\claude\…\tasks\<id>.output`) **เป็น 0 byte ตลอดสำหรับ implementer** ทั้งที่ agent จบแล้ว · ไฟล์จริงอยู่ที่
`C:\Users\HP\.claude\projects\C--Users-HP-Documents-Work-arichds-application-v2\c36a49e7-7c61-4e55-be90-6cd16b5a941a\subagents\agent-<id>.jsonl`
โดย `c36a49e7…` คือ **session id ของ orchestrator** ไม่ใช่ id ที่โผล่ในตัว `output_file` (ซึ่งเป็น `e3f953ca…`) — สอง id นี้ไม่ตรงกัน จึงหาไม่เจอถ้าเดาจาก path ของ `output_file`

## Commit

**ยังไม่ commit** — รอมนุษย์ตัดสินใจ
tree มี `installer/arichds.iss` (bump `AppVersion` 0.4.0 → 0.5.0) ค้างจากงานอื่นอยู่ด้วย **ไม่ใช่ส่วนหนึ่งของ issue นี้** — ทั้ง reviewer และ implementer ถูกสั่งให้เว้นไว้และเว้นจริง

## วิธีตรวจซ้ำด้วยตัวเอง (audit)

หลักฐานจริงอยู่ใน subagent transcript — ตรวจว่า skill ถูกเรียกจริงกี่ครั้ง / ชื่ออะไร
(ใช้ **path จริง** ด้านล่าง — **อย่าใช้ glob สำเร็จรูป** และอย่าใช้ค่า `output_file` ที่ harness คืนมา เพราะเป็น 0 byte):

    D="C:/Users/HP/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents"
    grep -o '"skill":"[a-z0-9:_-]*"' "$D/agent-a0eef22b68d1b7f5d.jsonl" | sort | uniq -c   # reviewer
    grep -o '"skill":"[a-z0-9:_-]*"' "$D/agent-a73166d6f412416ca.jsonl" | sort | uniq -c   # implementer
    grep -c '"name":"Skill"' "$D/agent-a73166d6f412416ca.jsonl"                            # จำนวน Skill call ทั้งหมด
