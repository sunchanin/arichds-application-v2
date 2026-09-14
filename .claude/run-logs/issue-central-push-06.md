# Ledger — Issue (central-push #06): บันทึกการเปลี่ยนวันหยุด และหน้าเว็บแจ้งว่า summary จะคำนวณใหม่
รัน: 2026-09-14 14:48–15:37 · branch: feature/light-modules · ผลลัพธ์: APPROVED_WITH_FIXES · รอบรีวิว: 1 · ticket lint: pass · Job A: ข้าม

## ต้นทุน
| สเตจ | เวลา (นาที) | tokens |
|---|---|---|
| Job A | — | — |
| implementer build | 21.1 | 272,049 (สะสม) |
| implementer ถูกส่งกลับไปเรียก skill (ก่อนรีวิว) | 14.5 | 329,681 (สะสม) |
| reviewer รอบ 1 | 3.9 | 102,508 (สะสม) |
| แก้ minor (ไม่รีวิวซ้ำ) | 7.8 | 357,947 (สะสม) |
| รอบ 2 — implementer / reviewer | — | — |
| **รวม** | **47.3** (wall clock 48.6) | ค่าสุดท้ายต่อ agent: implementer 357,947 · reviewer 102,508 |

agent ตายกลางคัน: ไม่มี

## ผลรีวิว
**ก่อนรีวิว**
- implementer แก้ `api/holidays.py` และ `Holidays.tsx` แต่รายงาน SKILLS INVOKED ว่าไม่ได้เรียก skill ใดเลย orchestrator จึงส่งกลับไปเรียก `fastapi` และ `antd-ui` ตาม Step 2
- ผลคือเจอข้อบังคับ #5 ของ antd-ui ที่ละเมิดอยู่จริง: ลิ้นชัก Change history โหลดทั้งตารางโดยไม่แบ่งหน้า
- แก้เป็นแบ่งหน้าฝั่ง server ตามแบบลิ้นชัก History ของหน้า Devices

**verdict รอบ 1: APPROVED_WITH_FIXES** — minor 2, nit 1
1. docstring ของเทสต์ commit-failure เคลมว่าพิสูจน์ transaction เดียวกัน แต่ probe แยก commit แล้วเทสต์ยังเขียว
2. เทสต์ App Log ครอบ 2 จาก 5 ทาง และ assertion เป็น substring หลวมๆ
3. comment `createHoliday` ใน `api.ts` ค้างมาจากตั๋ว 04

**probe ของ reviewer: 3 ตัว**
- แยกเป็นสอง commit → แดง 1 ตัว (write-failure) และเขียว 1 ตัว (commit-failure)
- บันทึก delete ซ้ำสองครั้ง → แดง
- บันทึก edit ก่อน assign ค่าใหม่ → แดง

**รอบแก้**
- เทสต์ log ทำเป็น parametrize ครบ 5 ทาง
- mutation ลบ log ของทาง edit ทำให้แดงเฉพาะเคส edit
- orchestrator ตรวจแล้วว่า summary line ของ full suite เป็นของจริง

**ข้อสังเกตอื่น**
- implementer ทำ mutation probe กับ logic ตั้งแต่รอบ build ครั้งแรกในชุดนี้ที่ทำครบตั้งแต่แรก
- การตัดสินใจที่ reviewer ส่งให้เจ้าของ: edit บันทึกเฉพาะวันใหม่ ไม่บันทึกวันเดิม ซึ่งตรงกับ spec
- problems ที่ค้าง: ไม่มี

## Gate
| รอบ | คำสั่ง full-suite | เวลา | จาก repo doc? | summary line |
|---|---|---|---|---|
| build | `.venv/Scripts/pytest -n auto -q` | 103.98s | ใช่ | 2196 passed, 57 skipped |
| หลังเรียก skill | `.venv/Scripts/pytest -n auto -q` | 175.97s | ใช่ | 2197 passed, 57 skipped |
| แก้ minor | `.venv/Scripts/pytest -n auto -q` | 205.96s | ใช่ | 2200 passed, 57 skipped |

ruff ผ่าน · `pnpm lint` และ `pnpm build` ผ่านทุกรอบ

## ไฟล์ที่เปลี่ยน
**Backend**
- `app/src/arichds/migrations/versions/0019_holiday_changes.py` (ใหม่)
- `app/src/arichds/db/models.py`
- `app/src/arichds/db/retention.py`
- `app/src/arichds/api/holidays.py`

**Tests**
- `app/tests/test_migration_0019.py` (ใหม่)
- `test_api_holidays.py`
- `test_db.py`
- `test_retention.py`

**Web**
- `web/src/api.ts`
- `web/src/pages/Holidays.tsx`

**Docs**
- `CLAUDE.md`
- `SPEC.md`
- ADR 0022

commit นี้รวม ledger ของตั๋ว 05 ไปด้วย

## Commit
`524c609` feat: Holiday changes are recorded, and the page says the summary will be recalculated (central-push #06)

## กับดักที่เสียเวลา (ถ้ามี)
- **ไม่เรียก skill:** implementer ไม่เรียก skill เพราะคิดว่าเลียนแบบโค้ดข้างเคียงก็พอ แต่โค้ดข้างเคียงไม่ได้บอกกฎเรื่องแบ่งหน้า เสียไป 14.5 นาที แต่กันไม่ให้บั๊กจริงหลุดไปถึง reviewer
- **`caplog` สะสม log จาก request ตั้งต้นด้วย:** เพราะ app ตั้ง log_level=INFO ต้องเรียก `caplog.clear()` ก่อน
- **เจ้าของสั่งหยุด batch หลังตั๋วนี้:** ตั๋ว 07 และ 08 ยังไม่เริ่ม และยังไม่ได้ทำ closing passes (learn & record / docs sweep)
