# Audit log — Issue 010: `arichds_vendor.py sign` รับชื่อฟีเจอร์อะไรก็ได้

รัน: 2026-08-26 · branch: `feature/light-modules` · ผลลัพธ์: **APPROVED** · รอบรีวิว: **2**
เกิดจากของหลุด: **ใช่** — เจอตอนออก Activation Code ทดสอบให้เจ้าของเอง ไม่ได้เจอจากการอ่านโค้ด
`tools/` ไม่มี reviewer และไม่มี linter คั่นระหว่างมันกับลูกค้าเลย (ดู "ของที่ยังค้าง")

## ทำอะไรไปบ้าง (ทีละขั้น)

### 1. reviewer (Job A) — สร้าง prompt (`/draft-delegation-prompt`)
- **Track: full** — เป็นพฤติกรรมแตกกิ่ง (ชื่อไม่รู้จัก / `app_log` / ช่องว่าง / เว้นวรรค / รักษา `None`) บนเส้นทาง licensing ไม่ใช่การแก้เชิงกล
- **TDD required: yes** — คุณค่าทั้งหมดของงานคือชุดกิ่งการปฏิเสธ
- **Workflow discipline: ไม่มี domain skill ไหนเกี่ยวข้อง** — ระบุทั้งสามตัว (`fastapi` ไม่มี API, `antd-ui` ไม่มี UI, `gurux-dlms` ไม่มี meter I/O) เพื่อไม่ให้การไม่เรียกอ่านเป็นความพลาด
- **ตัดสินใจล่วงหน้าให้ครบ 13 ข้อ (D1–D13)** แทนที่จะปล่อยให้ implementer เดา — จุดที่สำคัญที่สุดคือ **D8**: `features: None` แปลว่า "เปิดทุกคีย์ที่ขายได้" ส่วน `[]` แปลว่า "ไม่ได้ขายอะไรเลย" (`licensing/features.py:47`) ถ้าเผลอ normalize จะพังทุก licence ที่ออกโดยไม่ระบุ `--features`
- **D9 ฉลาด** — ให้ assert ด้วย `is` ไม่ใช่ `==` เพราะรายการที่ copy มือจะ *equal* แต่ไม่ *identical*
- reviewer ตรวจเองว่า `SELLABLE_FEATURE_KEYS` เป็น object เดียวกันทั้งสองเส้นทาง import จริง จึงเขียนเกณฑ์นี้ได้

### 2. implementer — ลงมือ + ตรวจตัวเอง (`/tdd`)
- ไฟล์: `tools/arichds_vendor.py` (+65/-2) · `app/tests/test_vendor_sign_features.py` (ใหม่ 19 เทส)
- **red จริง 5 รอบ พร้อม output ที่แปะมา** และ**ยอมรับตรงๆ ว่าอีก 6 แถวเป็นเทสที่เขียวตั้งแต่เขียน** เพราะคุมพฤติกรรมที่มีอยู่แล้ว — ไม่ได้สร้าง red ปลอม ใช้ mutation เป็นหลักฐานแทน
- **เจอบั๊กใน mutation harness ของตัวเอง แล้วรายงาน:** รอบแรกบอกว่าแดงครบ แต่แถว D7 บรรทัดสรุปว่าง ความจริงคือ `collected 0 items` — วางเทสผิด indent ไปอยู่คนละคลาส node id เลยไม่ match อะไร แล้ว driver อ่าน exit code ที่ไม่ใช่ 0 ของ pytest ว่า "แดง" · **2 ใน 14 แถวไม่เคยถูกพิสูจน์ และดูจาก output ไม่มีทางรู้** · แก้โดยเพิ่มการ์ดสองชั้น (node ต้อง collect ≥1 เทสตอนยังไม่ mutate + รอบ mutate ต้องมีคำว่า `failed` จริง) แล้วทดสอบว่าการ์ดตัวเองยิง
- **ดีเวียชันสองข้อ รายงานแทนที่จะทำเงียบๆ:** (1) format ไฟล์เทสใหม่ของตัวเองด้วย ruff เพราะมันอยู่ในขอบเขต gate — `tools/` ไม่แตะ พิสูจน์ด้วย hash · (2) เปลี่ยนข้อความ error เป็น ASCII ล้วน หลังเห็นว่า em-dash เพี้ยนเป็น `?` บนคอนโซล `cp1252` และสแกน AST แล้วพบว่าเครื่องมือนี้ไม่เคยมีสตริงที่พิมพ์ออกจอเป็น non-ASCII เลย
- ผลรันเทสต์: **1771 → 1790 passed, 57 skipped** (+19) · ruff สะอาด

### 3. reviewer (Job B) — รีวิว (`/scrutinize`)
- verdict: **CHANGES_REQUESTED** — 1 minor, 2 nit
- **minor** — `tools/arichds_vendor.py:238` ตัวคัดแยกในคอมพรีเฮนชัน `unrecognised` **ไม่มีเทสคุมเลย ลบทิ้งแล้วเทสผ่านหมด 19 ตัว** · reviewer รัน mutation ของตัวเอง 2 ตัวที่ไม่อยู่ในตารางเดิม:
  - ลบ `and name != OPS_ONLY_FEATURE_KEY` → `app_log` ไปโผล่ใต้ *"unrecognised feature name"* ด้วย ซึ่งคือ**สิ่งที่เกณฑ์ข้อ 2 เขียนมาเพื่อห้ามโดยเฉพาะ**
  - ลบ `name and` → ช่องว่างเปล่าถูกรายงานเป็นชื่อไม่รู้จัก ได้ข้อความว่างไร้ประโยชน์ — ตรงกับ output ก่อนแก้ใน screenshot red รอบ 3 ของ implementer เอง
- nit — ตาราง mutation แถว D5 รายงาน `2 failed` ของจริง `4 failed` (ตัวเลขค้างจากก่อนย้ายเทสที่วางผิดคลาส)
- nit — `tools/` อยู่นอกทุกการตรวจอัตโนมัติ (ส่งต่อให้เจ้าของ)

**ควรถูกจับที่ด่านไหน (ต่อ problem):**
- minor (ตัวคัดแยกไม่มีเทสคุม) — **ไม่มีด่านก่อนหน้าจับได้** · เป็นช่องที่อยู่*ระหว่าง*การตัดสินใจสองข้อ ซึ่งตาราง "หนึ่งแถวต่อหนึ่งการตัดสินใจ" มองไม่เห็นตามนิยาม — และกรอบนั้นคือสิ่งที่ **โจทย์ Job A สั่งเอง** จึงเป็นข้อจำกัดของโจทย์ ไม่ใช่ความพลาดของ implementer
- nit D5 count — **self-check ของ implementer** ควรจับได้ ถ้าเทียบตัวเลขกับจำนวน param
- nit `tools/` นอก gate — implementer เจอเองและรายงานถูกต้องแล้ว

### 4. รอบแก้ (1 รอบ)
- แก้เฉพาะเทส **ไม่แตะโค้ดจริงเลย** — hash `e7b4b373…` เท่ากันก่อนและหลัง, `diff` รายงาน IDENTICAL
- เพิ่ม assert เชิงลบ 3 จุด · mutation ทั้งสามตัวแดงแล้ว (1, 1, 4 failed)
- **รันตาราง mutation ใหม่ทั้งใบ 17 แถว** ไม่ยกตัวเลขเก่ามาใช้ซ้ำ · ทุกตัวเลขตรงกับจำนวนเทสใน node แล้ว
- คำอธิบายของ implementer เองว่าทำไมพลาด และเป็นบทเรียนที่ใช้ต่อได้: *"เทสของผม assert ว่าข้อความที่ต้องมีนั้นมี แต่ไม่เคย assert ว่าข้อความที่ไม่ควรมีนั้นไม่มี"*

### 5. reviewer (Job B รอบ 2) — **APPROVED**
- รัน mutation ทั้งสองตัวเองซ้ำแทนที่จะอ่านตาราง — ได้ 2 failed และ 4 failed
- ตอบคำถามที่ orchestrator ถามว่า "คลาสนี้ปิดหมดหรือยัง": **แคบลง ยังไม่ปิดสนิท** — ยังเหลือทิศตรงข้าม (การปฏิเสธพ่นถังที่ไม่ควรพ่นเพิ่ม) ซึ่ง reviewer probe แล้วเขียว **แต่จัดเป็น nit เพราะพฤติกรรมรับ/ปฏิเสธถูกคุมครบ** — probe แรกของมันที่ทำให้ list ที่ถูกต้องโดนปฏิเสธ **แดงทันที (3 failed)** จาก `TestAcceptedLists` จึงไม่มีทางเซ็นผิดหรือปฏิเสธผิดเงียบๆ สิ่งที่ไม่ถูกคุมคือหน้าตาข้อความ error เท่านั้น

## ต้นทุน (เวลา + tool calls + tokens)

| สเตจ | เวลา | tool calls | tokens (ดูหมายเหตุ) |
|---|---|---|---|
| reviewer Job A | 10.8 นาที | 32 | 97,421 |
| reviewer Job A (แจ้งเตือน tree ไม่สะอาด — false alarm) | 28.8 นาที | 35 | 113,133 |
| implementer (build) | 20.5 นาที | 70 | 143,747 |
| reviewer Job B | 5.2 นาที | 9 | 154,927 |
| รอบแก้ 1 — implementer | 5.2 นาที | 8 | 146,762 |
| รอบแก้ 1 — reviewer Job B | 2.7 นาที | 3 | 168,047 |

**หมายเหตุ tokens:** `subagent_tokens` **บวกกันตรงๆ ไม่ได้** — double-count ข้าม SendMessage resume
(memory `subagent-token-counts-are-not-additive`) ตัวเลขแถวหลังๆ เป็นยอดสะสมของ agent ตัวนั้น

**ข้อสังเกตเรื่องเวลา:** Job A ใช้เวลารวม ~40 นาที ผิดปกติมาก และทำให้ reviewer เห็น tree เปลี่ยน
ใต้เท้าตัวเอง จนแจ้งเตือนผิดว่า "tree ไม่สะอาด อาจเป็นงานค้างจากรอบก่อน" — ความจริงคือ implementer
ที่ orchestrator ส่งไปตามโจทย์ของมันเองกำลังทำงาน · orchestrator ยืนยันจาก mtime กับ `git status`
ที่เหลือศูนย์ตอน commit จึงไม่ต้อง reset อะไร

## ✅ skill ที่เรียกจริง — ยืนยันจาก transcript (tamper-proof)

```
=== IMPLEMENTER (724K) ===
      1 "skill":"tdd"
Skill calls: 1

=== REVIEWER (632K) ===
      1 "skill":"draft-delegation-prompt"
      1 "skill":"scrutinize"
Skill calls: 2
```

**สะอาด** — implementer เรียก `tdd` ตามที่โจทย์บังคับ และ**ไม่ได้เรียกสกิลรีวิวมาตรวจงานตัวเอง** ·
reviewer เรียก `draft-delegation-prompt` (Job A) + `scrutinize` (Job B) อย่างละครั้ง ไม่ซ้อนสกิลที่สอง ·
ไม่มีใคร spawn `docs-researcher` — ถูกต้อง งานนี้ไม่มี library ภายนอกให้ค้น

## Commit

`77ccf8a` — **fix: refuse a feature name that is not sellable (issue 010)**

## ของที่ยังค้าง (ไม่บล็อก แต่เจ้าของควรตัดสิน)

1. **`tools/` อยู่นอกทุกการตรวจอัตโนมัติ** — ruff config อยู่ใน `app/pyproject.toml` ตัว gate รันจาก
   `app/` จึงไม่เคยลงไปถึง `tools/` เลย · **นี่คือเหตุผลที่บั๊กใบนี้รอดมาถึงเครื่องมือที่หันหน้าเข้าหาลูกค้า**
   ทั้ง implementer และ reviewer เห็นตรงกันว่าควรมี issue ของตัวเอง — บันทึกใน audit log ไม่มีผลบังคับ
2. **ทิศตรงข้ามของ assert เชิงลบยังไม่ถูกคุม** — การปฏิเสธชื่อที่ไม่รู้จักสามารถพ่นบรรทัด `ops-only`
   หรือ `empty feature name` เกินมาได้โดยไม่มีเทสร้อง (reviewer probe แล้ว 19 ผ่าน) · ปิดได้ด้วย
   assert สองบรรทัดใน `test_unknown_name_is_refused_and_nothing_is_signed` · reviewer ไม่บล็อก
   เพราะพฤติกรรมรับ/ปฏิเสธถูกคุมครบแล้ว เสี่ยงแค่ข้อความ error สับสน
3. **`--max-meters` / `--lease-days` เป็น `type=int` ไม่มีการตรวจช่วง** — `--max-meters -5` เซ็นผ่าน ·
   คนละคลาสกับใบนี้ implementer จึงไม่ขยายขอบเขต

## วิธีตรวจซ้ำด้วยตัวเอง (audit)

หลักฐานจริงอยู่ใน subagent transcript — **ใช้ path จริงใต้ `subagents/` ไม่ใช่ `output_file` ที่ spawn คืนมา**
(ตัวหลังเป็น 0 ไบต์ตลอดกาล — memory `subagent-transcripts-often-empty`):

    d="C:/Users/HP/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents"
    grep -o '"skill":"[a-z0-9:_-]*"' "$d/agent-ad8599dd879e94803.jsonl" | sort | uniq -c   # implementer
    grep -o '"skill":"[a-z0-9:_-]*"' "$d/agent-a679308513cd5fc19.jsonl" | sort | uniq -c   # reviewer
    grep -c '"name":"Skill"' "$d/agent-ad8599dd879e94803.jsonl"
