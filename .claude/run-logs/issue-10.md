# Issue #10 — M4a-2: `read_load_profile()` คืนแถว Interval Reading ที่ normalize แล้ว

**เกิดจากของหลุด:** ไม่ใช่ งานใหม่ (M4a slice ที่สอง)

- **Branch:** `feature/mitsubishi-smw110w4`
- **Commit:** `4ebfaa8` — 13 ไฟล์ +1008 / −47
- **รอบรีวิว:** 3 (APPROVED ที่รอบ 3, เพดาน 5)
- **Track:** `full` · **TDD:** required และ **ทำจริงตั้งแต่รอบแรก**

---

## สกิลที่ถูกเรียกจริง (ตรวจจาก transcript)

| Agent | ไฟล์ | สกิลที่เรียกจริง |
|---|---|---|
| reviewer `a448bf4c` | 933 KB | `draft-delegation-prompt` · `scrutinize` |
| implementer `a9164cbd` | 1.7 MB | `gurux-dlms` · `tdd` |

**ครบทุกตัวที่ถูก mandate ทั้งสองฝั่ง** ไม่มีการรีวิวซ้ำซ้อน ไม่มีการ spawn subagent ต่อ

เทียบกับ #9 ที่ทั้งสองฝั่งข้ามสกิล methodology — ต่างกันตรงที่รอบนี้ผู้คุมงานสั่งตรง ๆ ว่า *"invoke the skill, do not reproduce its structure from memory"* กับ reviewer และเตือน implementer ถึงความผิดของมันในใบก่อนหน้า **คำสั่งที่ระบุชัดได้ผล ส่วนการ mandate เฉย ๆ ไม่ได้ผล**

---

## TDD — ทำถูกต้อง มี red จริงทุกขั้น

| ขั้น | red | green |
|---|---|---|
| 3 · locked vectors | `AttributeError: 'Smw110Driver' object has no attribute 'read_load_profile'` → `3 failed` | (เขียวตอนขั้น 6) |
| 4 · `_entry_window` | `ImportError: cannot import name '_entry_window'` | `4 passed` |
| 5 · `_resolve_multiplier` | `AttributeError` → `4 failed` | `4 passed` |
| 6 · `read_load_profile` | `12 failed, 8 passed` | `20 passed` |

Baseline จับไว้ก่อนแตะอะไร (`634 passed`) → จบที่ `659 passed` = +25 ตรงกับจำนวนเทสที่เพิ่ม

**full suite รัน 4 ครั้งตลอด 3 รอบ** (267s · 288s · 302s · 299s) เทียบกับ #9 ที่รัน 4 ครั้งใน**รอบเดียว** — ผู้คุมงานสั่งให้ใช้ scoped ระหว่าง red→green และเก็บ full ไว้ตอนจบ ได้ผล

---

## Job B รอบ 1 — CHANGES_REQUESTED (3 minor)

reviewer ไม่ได้อ่านแล้วเชื่อ แต่ทำ **mutation probe** ด้วยสคริปต์ใน scratchpad (ไม่แตะ repo):

| พลิกอะไร | ผล | สรุป |
|---|---|---|
| `10 ** m` แทน `raw * m` | energy `131.3` · volt `228714.03` เทียบกับที่ assert `13.130` / `228.188` | locked vectors ปักเลขจริง ไม่ใช่แค่ผ่าน |
| ชี้ OBIS energy ไป power sibling | `import_active_kwh` เป็น `None` | verbatim row จับได้ |
| สลับ `volt_l1` / `volt_l2` | `225.989` / `228.188` | verbatim row จับได้ |

และอ่าน `_entry_window` เทียบ v1 บรรทัดต่อบรรทัด (`load_profile_reader.py:161-171`) ยืนยันว่า margin 2 กับ 4 ยังอยู่ครบ — เป็น Output Parity ground truth

| # | ระดับ | เรื่อง | ควรถูกจับที่ด่านไหน |
|---|---|---|---|
| 1 | minor | scale ก่อนเรียก `_normalize()` ทำให้ guard ที่กัน non-numeric ของมันไม่มีวันทำงาน · เซลล์ `bytearray` ทำให้ `read_load_profile` ระเบิดทั้งก้อน เสียทุกแถวใน buffer | **Job B** — implementer ป้องกัน clock cell ไว้แล้วด้วย `_coerce_clock_cell` แต่ไม่ได้ป้องกัน measurement cell มองไม่เห็นจนกว่าจะป้อน bytearray เข้าไปจริง |
| 2 | minor | **เทสที่แบกเกณฑ์รับข้อ 3 ไม่มีทางแดงได้** — ส่ง sibling OBIS เข้าไปเป็น argument เอง เมธอดจึงแตะ `1.0.1.7.0.255` ไม่ได้อยู่แล้ว เกณฑ์ผ่านจริงแต่ผ่านเพราะ fixture บังเอิญไม่มี sibling ตัวนั้น | **Job B เท่านั้นที่จับได้** — TDD จับไม่ได้ เพราะเทสนี้เคยแดงจริงตอนฟังก์ชันยังไม่มี |
| 3 | minor | สกิล `gurux-dlms` ยังประกาศ 3 อย่างที่ diff นี้ทำให้เท็จ สองอย่างอยู่ในไฟล์ที่ implementer แก้เอง | implementer staleness sweep |

**nit ที่ตามมาด้วย:** margin 2/4 ของ `_entry_window` ไม่มี assertion ไหนปักไว้เลย (เทสที่มีผ่านทั้งกับ margin 0/0) · `_resolve_multiplier` log warning สองบรรทัดต่อความล้มเหลวหนึ่งครั้ง

---

## Deviation ที่ implementer แจ้ง — และ reviewer ตัดสินว่ามันถูก

Job A ระบุให้แก้บั๊ก `10 ** scaler` ที่ `patterns.md:62-70` **ที่เดียว** implementer ไปเจอบั๊กเดียวกันอีก **สองที่** (`SKILL.md:113` และ `api-reference.md:87`) แล้วแก้ทั้งสาม พร้อมแจ้งว่าเกินขอบเขตที่สั่ง

reviewer ตรวจแล้วยืนยันว่าทั้งสามคือบั๊กเดียวกันจริง — `GXDLMSRegister.setValue` เซ็ต `self.scaler = math.pow(10, exponent)` ฉะนั้นทุกที่ที่เขียน `10 ** scaler` คือการยกกำลังให้ตัวคูณ ซึ่งคือ ADR 0002 เป๊ะ ๆ **ในไฟล์ที่โปรเจกต์บังคับให้อ่านก่อนแตะโค้ด DLMS**

reviewer เขียนไว้ตรง ๆ ว่า:

> *"My Traps section named only `patterns.md:62-70`; my pre-flight opened that block and stopped there instead of grepping the skill for the pattern. Two live copies of the bug survived my review of my own prompt."*

**ควรถูกจับที่ด่านไหน:** Job A pre-flight (item 8b) — เป็นครั้งที่สองในแบตช์นี้ที่จุดอ่อนที่สุดคือคำกล่าวอ้างที่ reviewer เขียนลง prompt เอง (ครั้งแรกคือ citation ผิดใน #9)

---

## Job B รอบ 2 — CHANGES_REQUESTED (1 minor) — fix สร้างบั๊กใหม่

implementer แก้ finding 1 ตามที่สั่ง โดยลอก `isinstance` tuple ของ `_normalize` มาใช้:

```python
if raw is None or multiplier is None or not isinstance(raw, (Decimal, int, float)):
```

แต่ **ไม่ได้ลอกบรรทัดถัดไป** (`value = float(raw)` ที่ `_dlms.py:375`) ซึ่งเป็นครึ่งที่ทำให้ `Decimal` ใช้ได้จริง ผลคือ guard **รับ `Decimal` เข้ามาแล้วไปตายตอนคูณ** เพราะ `multiplier` มาจาก `math.pow()` เป็น float เสมอ และ Python ไม่รองรับ `Decimal * float`

reviewer พิสูจน์ด้วยของจริง ไม่ใช่อนุมาน — ทั้ง multiplier `0.001` และ `1.0` พังเหมือนกัน:

```
RAISED TypeError : unsupported operand type(s) for *: 'decimal.Decimal' and 'float'
```

คือ failure mode เดียวกับที่ finding 1 ตั้งขึ้นมาแก้ ในนิพจน์เดียวกัน

**ควรถูกจับที่ด่านไหน:** implementer self-check — มันเพิ่ม `Decimal` เข้า guard เอง ซึ่งเป็นการประกาศว่ารองรับ แต่ไม่มีเทสสำหรับเคสที่ตัวเองเพิ่งประกาศ

---

## Job B รอบ 3 — APPROVED

fix บรรทัดเดียว: `self._normalize(field, float(raw) * multiplier)`

implementer พิสูจน์ว่า `int`/`float` ไม่เปลี่ยนแม้แต่บิตเดียว โดยเทียบ `.hex()` (IEEE-754 ดิบ) ไม่ใช่เทียบค่า

reviewer ไม่เชื่อรายงาน กวาดเองอีกรอบ **10,075 คู่ (cell, multiplier)** — multiplier `1.0 / 0.001 / 0.01 / 1e-3 / 100.0` · cell รวม locked vectors ทั้งสาม, ทุกเซลล์ใน verbatim row, `0`, `1`, `2**53+1`, `10**12`, `1e300`, `1e-300`, `0.1` และสุ่ม 40-bit อีก 2,000 ค่า → **mismatch 0**

และยืนยันว่าลำดับ **guard ก่อน coerce** ยังอยู่ (`bytearray` ไม่มีวันไปถึง `float()`) พร้อมรัน mutation probe ทั้ง 5 ตัวซ้ำกับ build ใหม่ ไม่มีอะไรถอยหลัง

---

## ผลตรวจสุดท้าย

```
ruff format --check .   → 85 files already formatted
ruff check .            → All checks passed!
pytest                  → 659 passed, 2 warnings in 299.09s
```

reviewer รันของตัวเองแยก: `55 passed` (scoped)

---

## ที่ยังค้างสำหรับเจ้าของงาน

**อ่านมิเตอร์จริงยังไม่ได้ทำ** — เหมือน #9 เข้าถึงไม่ได้จากเครื่องพัฒนา ต้องนัดลูกค้า

**Output Parity อ้างไม่ได้** — ป้ายเขียน `CT /5A` ค่าใน register เป็นฝั่ง secondary และยังไม่รู้ CT ratio สิ่งที่ใบนี้พิสูจน์คือเซลล์ดิบกลายเป็นหน่วยวิศวกรรมถูกต้องตาม vector ที่ล็อกไว้ **ไม่ใช่**ความถูกต้องของพลังงานสัมบูรณ์

**ข้อสังเกตของ reviewer ที่เป็นของ M5 ไม่ใช่ของใบนี้:**
- ถ้า clock OBIS หายไปจาก `captureObjects` จะได้ WARNING ต่อแถว — วันนี้ไม่มีปัญหาเพราะไม่มีใครเรียก แต่ backfill 90 วันคือ `rows_window ≈ 8640` บรรทัด M5 ต้องตัดสินว่าจะยุบเป็นบรรทัดสรุปไหม
- อ่าน sibling 7 ตัวก่อนดึงแถว ฉะนั้น window ที่ไม่มีข้อมูลก็ยังเสีย 7 round trip — สังเกตได้บนสาย serial 19200 baud

---

## วิธีตรวจหลักฐานเอง

```bash
d=~/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents
grep -o '"skill":"[a-z0-9:_-]*"' "$d/agent-a448bf4c4bf4bb32e.jsonl" | sort | uniq -c   # reviewer
grep -o '"skill":"[a-z0-9:_-]*"' "$d/agent-a9164cbdb2302f778.jsonl" | sort | uniq -c   # implementer
grep -o '[0-9]\+ failed[,)][^"]\{0,30\}' "$d/agent-a9164cbdb2302f778.jsonl" | sort -u  # red runs
```

**หมายเหตุ:** ไฟล์ `.output` ใน `tasks/` อ่านได้ 0 ไบต์เสมอบนเครื่องนี้ — transcript จริงอยู่ที่ path ข้างบน
