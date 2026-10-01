# Audit log — Issue 012: ซ่อนเมนูที่ license ไม่อนุญาต (CR — กลับการตัดสินใจที่บันทึกไว้)

รัน: 2026-08-26 · branch: `feature/light-modules` · ผลลัพธ์: **APPROVED** · รอบรีวิว: **2**
เกิดจากของหลุด: **ไม่ใช่** — เจ้าของขอเอง ระหว่างทดสอบการจำกัดฟีเจอร์ · เป็น CR ที่**กลับการตัดสินใจ
ที่เขียนไว้แล้ว** ที่ `AppShell.tsx:84-87` โดยตั้งใจ ไม่ใช่การแก้บั๊ก

## ทำอะไรไปบ้าง (ทีละขั้น)

### 1. reviewer (Job A) — สร้าง prompt (`/draft-delegation-prompt`)
- **Track: full** · **TDD required: yes** — การ resolve ฝั่ง backend มีสามกิ่ง (`None` / `[]` /
  license ไม่ valid) ซึ่งการสับสนระหว่างกันคือกับดักที่ตัว issue ตั้งชื่อไว้เอง
- **Workflow discipline: `fastapi` + `antd-ui`** (`gurux-dlms` ระบุว่าไม่เกี่ยว)

**reviewer คว่ำเกณฑ์ในตัว issue เอง พร้อมเหตุผลสามข้อ (D1/D2/D3):** ผมเขียน issue ไว้ว่าให้ส่ง
รายการ license ดิบโดย `null` แปลว่า "ทุกอย่าง" · reviewer แย้งว่า (ก) ส่ง `null` = ย้ายกับดักของ
issue เองขึ้นสายไปโผล่ในภาษาที่สอง · (ข) ฝั่ง client ต้อง copy คีย์ทั้งสิบมาไว้ใน TypeScript เพื่อขยาย
`null` ⇒ เพิ่มคีย์ใหม่ทีต้องแก้สองภาษา ซึ่งคือบั๊กที่ 010 เพิ่งแก้ · (ค) **รายการดิบไม่นับ `.env
FEATURES`** ⇒ เครื่องที่ `.env` ไม่เปิดคีย์นั้นจะยังโชว์เมนู แล้วหน้าเพจปฏิเสธ — **คือพฤติกรรมที่
CR นี้มีไว้เพื่อกำจัดพอดี** · แทนด้วย `enabled_features: list[str]` ที่ resolve แล้ว เรียงแล้ว
ไม่มีวันเป็น null · และตั้งชื่อไม่ให้ชนกับ `features` เดิมที่มีความหมายต่างกัน

**ตัดสินข้อย่อยที่ issue เปิดค้างให้ครบ:** `app_log` ใช้กฎเดียวกับคีย์อื่น (D6) · File Upload
**ไม่โฆษณาเลย** จนกว่า M8 จะให้ transport (D7) · หัวข้อกลุ่มหายเมื่อลูกทั้งหมดถูกซ่อน (D8) ·
**ซ่อนสนิท ไม่มีลิงก์ชวนซื้อ** (D9) · และ **ข้อความ "ไม่ได้เปิดใช้" ตัวเดียวใน `App.tsx` ที่ render
จาก mapping เดียวกับที่ใช้ซ่อนเมนู (D10)** ⇒ กฎซ่อนกับกฎ fallback เป็นกฎเดียวกัน ขัดกันเองไม่ได้

### 2. implementer — ลงมือ + ตรวจตัวเอง (`tdd` + `fastapi` + `antd-ui`)
- ไฟล์: `api/license.py` · `features.ts` (ใหม่ — ย้าย `Page`/`PAGES`/`toPage` มาไว้ด้วย) ·
  `test_nav_feature_contract.py` (ใหม่) · `AppShell.tsx` · `App.tsx` · `api.ts` · `LicenseCard.tsx` ·
  `SPEC.md` §3.9 · ตัว issue เอง
- **รายงาน mutation ข้อ 4 ว่า "ยังเขียว" ทั้งที่ไม่มีใครจับได้** — ชี้หน้า Billing ไปคีย์ที่มีอยู่จริงแต่ผิด
  ไม่มีเทสตัวไหนร้อง · จับได้ทางเดียวคือ render จริงแล้วเห็นว่าหน้า Billing หายไป
- **เจอสิ่งที่โจทย์ไม่ได้บอก:** หน้า Export Format ถูกกั้นด้วยคีย์ `load_profile` (ไม่ใช่คีย์ของตัวเอง)
  — ไปเปิด router อ่านเองแทนที่จะเดา
- **เจอกับดักที่ audit log ของ issue 17 เคยบันทึกไว้** (`Page`/`PAGES` แทรกระหว่าง docstring กับ
  `export default function App()` ทำให้ docstring กำพร้า มองไม่เห็นทั้งจาก lint และ build) และ
  ชนกับดักเดียวกันใน `AppShell.tsx` ระหว่างทาง แล้วแก้ก่อน build
- ผลรันเทสต์: **1799 → 1829 passed** (+30)

**หลักฐาน render สามแบบ (`renderToStaticMarkup`)** — ไม่มี test runner ใน `web/` เกณฑ์หลักจึงพิสูจน์
ทางอื่นไม่ได้:

| license | เมนู | หัวข้อกลุ่ม |
|---|---|---|
| ทุกคีย์ | 13 รายการ | Data-out Destination |
| `load_profile, billing, database_destination` (ใบทดสอบจริงของเจ้าของ) | Devices · Load Profile · **Billing** · Export Format · User Management · Settings · Database | Data-out Destination |
| ตัด `database_destination` | 6 รายการ | **หายไป** |

File Upload ไม่โผล่ทั้งสามแบบ แม้เป็น admin (D7) · **หน้า Billing ยังอยู่ครบภายใต้ใบทดสอบ** — กับดัก
ที่กลัวที่สุดไม่เกิด

### 3. reviewer (Job B) — รีวิว (`/scrutinize`)
- verdict: **CHANGES_REQUESTED** — 2 minor + 2 nit · **ทั้งสอง minor เป็น defect ของโจทย์ที่ reviewer
  เขียนเอง ไม่ใช่งานของ implementer** และมันประกาศเช่นนั้น
- **minor 1 — ครึ่ง `.env FEATURES` ของการ resolve ไม่มีเทสคุมเลย** · reviewer รัน probe P1: เปลี่ยน
  `get_settings().enabled_feature_keys()` เป็นค่าคงที่ คือ**ลบการ intersect ทิ้งทั้งดุ้น** → **เทส
  เขียวหมด 84 ตัว** · แรงกว่าการขาด coverage ธรรมดา เพราะครึ่งนั้นคือ*เหตุผล*ที่เลือกส่ง effective set
  แทนรายการดิบ (เหตุผล ค ข้างบน) · docstring ยืนยันพฤติกรรมนั้นไว้ แต่ไม่มีอะไรบังคับ
- **minor 2 — tripwire พิสูจน์ว่าคีย์*มีจริง* ไม่เคยพิสูจน์ว่าเป็นคีย์ที่*ถูก*** · reviewer **กลับคำตัดสิน
  ของตัวเอง**: แถวที่ 4 ในตาราง mutation ของมันเขียนอนุญาตไว้ล่วงหน้าว่า "ถ้าจับไม่ได้ก็รายงานไป" ·
  ตอนนี้บอกว่า *"ผมกำลังคว่ำแถวของตัวเอง การ์ดตัวนี้ทำได้ในราคาที่รับได้"*
- **วิธีที่ reviewer คิดออก ฉลาดกว่าที่ orchestrator เสนอ:** แทนที่จะเขียนคู่ Billing→`billing` ด้วยมือ
  ให้เอาคีย์จาก `features.ts` ไปเทียบกับคีย์ที่ **เซิร์ฟเวอร์พูดเอง** ผ่าน `FeatureDisabledError.reason`
  ⇒ **ไม่มีสำเนาที่สองให้เก่า** เหลือเขียนมือแค่ตาราง path

**ควรถูกจับที่ด่านไหน (ต่อ problem):**
- minor 1 (`.env` ไม่ถูกคุม) — **ไม่มีด่านก่อนหน้าจับได้** · Job B เท่านั้น และจับได้เพราะ reviewer
  รัน mutation ของตัวเองบนเป้าที่ implementer ไม่ได้ครอบ
- minor 2 (tripwire ตื้นไป) — **โจทย์ Job A** · มันอนุญาตช่องนี้ไว้เองในตาราง mutation
- nit 3, 4 — Job B เท่านั้น

### 4. รอบแก้ (1 รอบ) — เทสกับ docstring เท่านั้น
- **ไม่มีบรรทัดโค้ดจริงขยับเลย** — `api/license.py` และ `features.ts` byte-identical กับก่อนรอบแก้
  (reviewer เทียบ hash เอง: `efdbf22e…` และ `bdf7695f…`) · diff ฝั่งโค้ดจริงมีแต่ข้างใน `"""…"""`
- mutation ทั้งสองที่เคยเขียว **แดงแล้ว** และตัวที่สองแดง**ทั้งสองทิศ**
- **implementer เจอบั๊กในเทสที่ตัวเองเพิ่งเขียน:** `response.json().get("error", {}).get("reason")`
  — ซองที่สำเร็จส่ง `error: null` มา ไม่ใช่ไม่มีคีย์ ⇒ `.get("error", {})` คืน `None` ไม่ใช่ `{}` ⇒
  ถ้าเจอ 200 ที่ไม่คาดคิดจะระเบิดเป็น `AttributeError` **แทนที่จะบอกว่าอะไรไม่ตรง** · แก้เป็น
  `(… .get("error") or {})`
- nit ทั้งสองทำครบ ไม่ข้าม

### 5. reviewer (Job B รอบ 2) — **APPROVED**
- รัน mutation 4 ตัวเอง แดงหมด รวมสองตัวใหม่ที่ทดสอบว่า**การ์ดตัวใหม่หลอกไม่ได้**: เปลี่ยน path
  ในตารางเป็น path อื่นที่มีจริง → แดงสองที่ · ขยาย `UNSWEPT_PAGES` ให้ใหญ่ขึ้น → แดง (เพราะ assert
  เป็น **set equality** ไม่ใช่ subset)
- ยืนยันว่าทิศบวกของ tripwire ไม่ได้ผ่านด้วยเหตุผลที่ไม่เกี่ยว และอธิบายว่าทำไมสองทิศต้องมีคู่กัน
- **ตอบคำถามเรื่อง capture mode:** ไม่ใช่ regression และไม่แตะ ADR 0017 — `Result` ถูกส่งเป็น
  `children` จึง render **ข้างใน** `AppShell` ⇒ `.ant-layout` ยังอยู่ `mounted` ยังจริง · ถ้า render
  *แทน* shell จะพัง contract แต่มันไม่ได้ทำ
- **erratum ของตัวเอง:** รอบ 1 มันเขียนว่า `Billing.tsx` เรียก `/api/settings/billing` ซึ่งไม่มี
  `require_feature` · ที่จริงคือ `/api/billing/settings` ซึ่งอยู่ใต้ router ที่กั้นด้วย `billing` ·
  **ข้อสรุปถูก แต่เหตุผลที่เขียนผิด** และมันเจอเพราะ probe ของตัวเองยิงไป path ที่มันแต่งขึ้นแล้วได้ 404

## ต้นทุน (เวลา + tool calls + tokens)

| สเตจ | เวลา | tool calls | tokens (ดูหมายเหตุ) |
|---|---|---|---|
| reviewer Job A | 8.7 นาที | 33 | 129,027 |
| implementer (build) | 21.5 นาที | 82 | 190,959 |
| reviewer Job B | ตายเพราะ session limit → resume | 0 | 189,597 |
| รอบแก้ 1 — implementer | 8.0 นาที | 21 | 215,542 |
| รอบแก้ 1 — reviewer Job B | 4.5 นาที | 9 | 220,867 |

**หมายเหตุ tokens:** `subagent_tokens` บวกกันตรงๆ ไม่ได้ — double-count ข้าม SendMessage resume

**เหตุการณ์:** reviewer ชนลิมิต session **ขณะกำลังรัน mutation probe** ซึ่งเป็นจังหวะอันตรายที่สุด ·
orchestrator ตรวจ tree ก่อนปลุก: `git status` ตรงกับที่ implementer รายงาน, `features.ts` ยังอ่านว่า
`billing: { key: "billing" }` (เป้าของ probe 4 คืนสภาพแล้ว), gate รันซ้ำได้ 1829 เท่าเดิม ·
**ตรวจไฟล์ untracked ด้วยมือ เพราะ git มองไม่เห็น mutation ในไฟล์ที่มันยังไม่ track**
(memory `mutation-probe-can-leave-the-mutation-on-disk`)

## ✅ skill ที่เรียกจริง — ยืนยันจาก transcript (tamper-proof)

```
=== IMPLEMENTER (1.1M) ===
      1 "skill":"antd-ui"
      1 "skill":"fastapi"
      1 "skill":"tdd"
Skill calls: 3

=== REVIEWER (904K) ===
      1 "skill":"draft-delegation-prompt"
      1 "skill":"scrutinize"
Skill calls: 2
```

**สะอาด** — implementer เรียกครบทั้งสามที่โจทย์บังคับ และไม่ได้เรียกสกิลรีวิวมาตรวจงานตัวเอง ·
reviewer เรียก `draft-delegation-prompt` + `scrutinize` อย่างละครั้ง · ไม่มีใคร spawn `docs-researcher`

## Commit

`7164545` — **feat: hide menu entries the licence does not allow (issue 012)**
stage แบบระบุชื่อไฟล์ ไม่ใช้ `git add -A` เพื่อไม่ให้ `docs/issues/013-*.md` หลุดเข้าไป

## ของที่ยังค้าง (ไม่บล็อก)

1. **เทสช้าลง ~7.7 วินาที** (64.1 → 71.7) เพราะ `test_a_licence_granting_only_that_key_is_not_refused`
   วนเก้าหน้า และแต่ละเคส relicense ผ่าน endpoint Ed25519 จริง · reviewer บอกว่านี่คือราคาซื่อสัตย์
   ของการ์ดที่มันเรียกร้องเอง และยอมจ่ายอีก **แต่เป็นที่แรกที่ควรดูถ้าวันหน้าต้องลดเวลา gate**
2. **`PAGE_API_PATHS` ยังเป็นครึ่งที่เขียนมือ** โดยจำเป็น — ไม่มีอะไรในสองฝั่งบันทึกว่าหน้าไหนเรียก
   API ตัวใด · ตอนนี้มีการ์ดคุมสองด้านแล้ว แต่ยังเป็นแถวที่หน้าใหม่ในอนาคตจะลืม
3. **issue 013** จะแตะแถว `file-upload-destination` ในตารางนั้น เมื่อคีย์ `file_upload_destination`
   เข้า `SELLABLE_FEATURE_KEYS` — เป็นงานของ 013 ไม่ใช่ของใบนี้ · D7 ไม่เปลี่ยนพฤติกรรม

## วิธีตรวจซ้ำด้วยตัวเอง (audit)

    d="C:/Users/HP/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents"
    grep -o '"skill":"[a-z0-9:_-]*"' "$d/agent-a7473caa418454c04.jsonl" | sort | uniq -c   # implementer
    grep -o '"skill":"[a-z0-9:_-]*"' "$d/agent-a84c88157b4717cd5.jsonl" | sort | uniq -c   # reviewer
    grep -c '"name":"Skill"' "$d/agent-a7473caa418454c04.jsonl"
