# Issue #35 — Billing capture image: PNG ที่ครอบ 10 รอบบิล

**สถานะ: DONE** · commit `883fe19` · branch `feature/light-modules` · รีวิว 2 รอบ (เพดาน 5)

## สิ่งที่ทำ

Capture รูปแบบที่สาม ต่อจาก PDF และ xlsx — ภาพ PNG ของตาราง Billing History วาดฝั่ง server
ด้วย Pillow เป็น renderer ตัวที่ 3 บน `_render_shared` ครอบ **10 รอบบิลที่ปิดล่าสุด** ของมิเตอร์นั้น

เขียนโดยเส้นทาง eager เดิมที่เขียนอีกสองรูปแบบอยู่แล้ว ⇒ เกิดขึ้นเองโดยไม่ต้องเปิดเบราว์เซอร์
ซึ่งคือคุณสมบัติที่ลูกค้าขอจริง ๆ และผลิตภัณฑ์มีมาตั้งแต่ M6 · คุมด้วย sellable key ใหม่
`billing_image_export` (รวมเป็น 9 ตัว)

หน้า Billing เสียคอลัมน์ Capture ต่อแถวไป เหลือปุ่มเดียวบน toolbar ที่เขียนไฟล์ลง `capture_dir`
แล้วส่งให้เบราว์เซอร์โหลด · PDF/xlsx ไม่ถูกแตะ · `ALL_SECTIONS` ออกมาเหมือนเดิมทุกไบต์

กำกับโดย **ADR 0014** (วาด ไม่ใช่ถ่ายจอ) และ **ADR 0015** (สามนามสกุลใช้ชื่อร่วมกัน แต่ `.png`
ครอบ 10 รอบ)

## สกิลที่เรียกจริง — ตรวจจาก transcript ไม่ใช่จากคำบอกเล่า

`.output` ที่ spawn คืนมาเป็น **0 ไบต์** ตามที่ memory บันทึกไว้ ⇒ ต้องไปอ่านตัวจริงที่
`~/.claude/projects/<slug>/<session>/subagents/agent-<id>.jsonl`

| agent | ขนาด | สกิล |
|---|---|---|
| reviewer `ab9db6b22b8b03063` | 1 MB | `draft-delegation-prompt` ×1 (Job A) · `scrutinize` ×1 (Job B) |
| implementer `a6be3a4d050e10c4d` | 3 MB | `tdd` ×1 · `antd-ui` ×1 · `fastapi` ×1 |

**ครบทุก mandate · ไม่มีรอบรีวิวซ้ำซ้อน** — implementer ไม่ได้เรียก `scrutinize`/`code-review`
และ reviewer ไม่ได้เรียกสกิลรีวิวตัวที่สองทับ `scrutinize`

## TDD

**บังคับ · ใช้จริง** สำหรับ Step 1-5 (backend) · frontend ไม่มี test framework ใช้
`pnpm lint && pnpm build` เป็น gate ตาม CLAUDE.md

Red จริงที่ paste มาก่อน green: 3-tuple ของ `capture_target_paths` (`ValueError: not enough
values to unpack`) · โมดูล `capture.png` (`ModuleNotFoundError` แล้วตามด้วย assertion แดงของ
T2/T3) · `write_image`/`write_png_capture` (`TypeError`, `AttributeError`) · endpoint ใหม่
(เทสทั้ง 9 ตัว 422 จริงเพราะ route ชนกัน)

**ข้อยกเว้นที่ implementer แจ้งเอง**: T1 กับเทส eager-path ของ D4 ไม่มี red ที่มีความหมาย
เพราะ D8 ไม่เปลี่ยนเนื้อหา `ALL_SECTIONS` และ query ถูกเขียนพร้อมเทสในรอบเดียว ⇒ พิสูจน์ด้วย
mutation probe แทนการสร้าง red ปลอม ซึ่งตรงตามที่ pipeline อนุญาต

## รีวิวรอบที่ 1 — CHANGES_REQUESTED

reviewer **ไม่พบบั๊กในโค้ดที่ shipped เลย** ทุกเกณฑ์รับงานผ่านด้วยโค้ดจริง · ที่พังคือตาข่ายเทส

**เทส 3 ตัวที่ไม่มีวันแดง** — พิสูจน์ด้วยการกลายพันธุ์โค้ดจริงแล้วรัน suite เต็ม ยังเขียวทุกครั้ง

| # | เทส | สิ่งที่หลุด |
|---|---|---|
| 1 | T7 Open Period ห้ามโผล่ | fixture ตั้ง Open Period ให้ **ใหม่กว่า** anchor ⇒ `bill_date <=` กันไว้อยู่แล้ว `record_status IS NULL` ไม่เคยถูกทดสอบ · และเพราะ `<=` รวมค่าเท่ากัน ตอนมิเตอร์ปิดรอบ Open Period ใหม่อาจมี `bill_date` เท่ากันพอดี ตัวกรองนั้นจึงเป็นสิ่งเดียวที่กันรอบที่ยังไม่ปิดออกจากเอกสารที่ส่งลูกค้า |
| 2 | T3 หัวคอลัมน์ Rate | เช็กแค่ฝั่ง label ⇒ สลับ `rate_a`↔`rate_b` แล้วค่าของ Rate B ไปพิมพ์ใต้หัว "Rate A" ทั้ง 12 กลุ่มโดยเทสเขียว · T2 ก็ไม่จับเพราะเช็กเป็น set ซึ่งการสลับไม่เปลี่ยน set |
| 3 | T17 หน่วยแสดงผล | ลบ `scale_value` ออกจาก `_cell_text` ทิ้ง suite ยังเขียว ⇒ ระบบยอมให้พิมพ์ `42.5` ใต้หัว `Wh` — กับดัก invariance ที่ prompt เตือนไว้เป๊ะ |

**บวกโค้ดจริง 1 ข้อ**: `object_session()` **คืน `None`** (ไม่ raise) เมื่อเจอ ORM row ที่หลุด session
ต่างจาก `SimpleNamespace` ที่ raise `UnmappedInstanceError` ⇒ การรวมสองกรณีไว้ที่ `session is None`
ทำให้ได้ไฟล์ชื่อ `<bill_date>.png` ที่สัญญา 10 รอบ แต่มีรอบเดียว เงียบไม่มี log ·
ยังไม่เกิดจริง (ทั้งสอง caller ถือ session อยู่) แต่เป็นกับดักรอไว้

บวกนิต 2 ข้อ: default ของ `write_image` และ import ที่อยู่ในฟังก์ชัน

## รีวิวรอบที่ 2 — APPROVED

reviewer **รัน mutation ของตัวเองซ้ำเอง** ไม่รับ red ที่ paste มา

| mutation | รอบ 1 | รอบ 2 |
|---|---|---|
| ลบ `record_status.is_(None)` | 🟢 `1472 passed` | 🔴 `1 failed, 1477 passed` |
| สลับ `_RATE_SUFFIXES` | 🟢 `1472 passed` | 🔴 `1 failed, 1477 passed` |
| `_cell_text` → `ascii_cell(raw)` | 🟢 `1472 passed` | 🔴 `1 failed, 1477 passed` |

**แต่ละอันล้มแค่ 1 เทส** ⇒ แก้ตรงจุด ไม่ใช่การผูกกันมั่วที่จะทำให้ suite ส่งเสียงตอนแก้เรื่องอื่น

บวก probe อีก 2 ตัวบนโค้ดใหม่ที่ implementer ไม่ได้รัน: ลบ `logger.warning` → แดง ·
บังคับ `if session is None:` → `if False:` → แดง ⇒ แขนงถูกยึดจากทั้งสองด้าน

**reviewer ถอนข้อเสนอของตัวเอง 1 ข้อ** — มันเคยเสนอให้ยก `_cell_text` เป็น public แต่ไปตรวจ
convention ของ repo แล้วพบว่า **มีเทสเดิม 4 ไฟล์ที่ import symbol private จาก `src` อยู่แล้ว**
(`factory._registry`, `_dlms._special_day_entry_from_gx`) ⇒ CLAUDE.md สั่งให้ตามสไตล์เดิม
การยกเป็น public ต่างหากที่จะเป็นการแหวกแนว · การตีความของ implementer ถูก

## Gate

```
ruff format --check .   →  195 files already formatted
ruff check .            →  All checks passed!
pytest -n auto          →  1478 passed, 16 skipped, 18 warnings in 55.84s
pnpm lint && pnpm build →  clean (รอบแรก, frontend ไม่ถูกแตะรอบที่สอง)
```

จาก 1439 ก่อน batch ⇒ **+39 เทส** · 16 skip เป็นของเดิมยืนยันด้วย `-rs` (15 driver-contract
"nothing to prove" · 1 Windows symlink privilege) · reviewer วัด `git diff -U0 app/tests/` ได้
**เพิ่ม `def test_` 26 ตัว ลบ 0 ตัว** ⇒ ตัวเลขไม่ได้มาจากการย้ายไฟล์

## ค้างอยู่ — ต้องมนุษย์ทำ

🔴 **HITL gate: เจ้าของต้องเปิดไฟล์ PNG ที่ render ออกมาดูเอง แล้วยืนยันว่ามันอ่านออกว่าเป็น
ตารางของโปรแกรมเรา** — ไม่มีเทสไหนแทนได้ และทั้ง implementer และ reviewer ไม่ได้อ้างว่าทำแทนแล้ว
issue ยังปิดไม่ได้จนกว่าจะผ่านข้อนี้

## วิธีตรวจหลักฐานเอง

```bash
d=~/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents
grep -o '"skill":"[a-z0-9:_-]*"' $d/agent-ab9db6b22b8b03063.jsonl | sort | uniq -c   # reviewer
grep -o '"skill":"[a-z0-9:_-]*"' $d/agent-a6be3a4d050e10c4d.jsonl | sort | uniq -c   # implementer
```

**อย่าใช้ path `.output` ที่ spawn คืนมา** — มันเป็น 0 ไบต์เสมอ และจะทำให้สรุปผิดว่า
"ไม่ได้เรียกสกิลเลย"
