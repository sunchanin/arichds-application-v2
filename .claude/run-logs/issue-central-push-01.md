# Ledger — Issue (central-push #01): Energy Summary ถูกเก็บลงตาราง และคำนวณใหม่ทั้งหน้าต่าง 90 วันทุกรอบ
รัน: 2026-09-14 11:29–12:11 · branch: feature/light-modules · ผลลัพธ์: APPROVED · รอบรีวิว: 2 · ticket lint: pass · Job A: ข้าม

## ต้นทุน
| สเตจ | เวลา (นาที) | tokens |
|---|---|---|
| Job A | — | — |
| implementer build | 26.8 | 327,297 (สะสม) |
| reviewer รอบ 1 | 4.4 | 107,718 (สะสม) |
| แก้ minor (ไม่รีวิวซ้ำ) | — | — |
| รอบ 2 — implementer / reviewer | 7.7 / 1.8 | 371,104 / 122,951 (สะสม) |
| **รวม** | **40.7** (wall clock 42.4) | ค่าสุดท้ายต่อ agent: implementer 371,104 · reviewer 122,951 |

agent ตายกลางคัน: ไม่มี

## ผลรีวิว
- verdict รอบ 1: CHANGES_REQUESTED — 1 blocker, 2 minor, 2 nit
  - **blocker:** recompute ไม่ลบแถวของวันที่ไม่มี reading แล้ว เช่นหลังกด **Delete all data** หรือเมื่อ interval ทั้งวันกลายเป็น all-invalid ค่าผิดจึงค้างบนหน้าได้ถึง 90 วัน ขัดกับ ADR 0022 ที่ว่า "invalidates nothing"
  - **minor 1:** เอกสารสี่จุดเขียนว่า Energy Export File "live โดยตั้งใจ" ซึ่งขัดกับ ADR 0022/0023
  - **minor 2:** เทสต์ Retroactive เพิ่ม Holiday ผ่าน ORM ทั้งที่เกณฑ์ระบุว่าให้ผ่าน API
  - **nit:** docstring ของ migration อ้าง `onupdate` ที่ไม่มีอยู่จริง · log ของ retention พิมพ์ cutoff ผิดตัว
- verdict รอบ 2: APPROVED — ไม่มี problem
- probe ที่ reviewer ยิง
  - รอบ 1: 3 ตัว แดงทั้ง 3
  - รอบ 2: 3 ตัว แดง 2 เขียว 1 ตัวที่เขียวคือเอาเงื่อนไข `>= window_start` ออก reviewer ตัดสินว่าไม่มีผลต่อสิ่งที่ผู้ใช้เห็น เพราะเท่ากับ cutoff ของ Retention
- problems ที่ค้าง: ไม่มี

## Gate
| รอบ | คำสั่ง full-suite | เวลา | จาก repo doc? | summary line |
|---|---|---|---|---|
| build | `.venv/Scripts/pytest -n auto -q` | 128.62s | ใช่ | 2126 passed, 57 skipped |
| รอบแก้ | `.venv/Scripts/pytest -n auto -q` | 103.12s | ใช่ | 2127 passed, 57 skipped |

ruff format --check และ ruff check ผ่านทั้งสองรอบ

## ไฟล์ที่เปลี่ยน
**ไฟล์ใหม่**
- `db/energy_summary_store.py`
- `migrations/versions/0017_energy_summary_days.py`
- `tests/test_energy_summary_store.py`
- `tests/test_migration_0017.py`

**ไฟล์ที่แก้**
- `api/energy.py`, `constants.py`, `db/energy_query.py`, `db/models.py`, `db/retention.py`, `export/energy_csv.py`, `jobs/scheduler.py`
- `tests/test_api_energy.py`, `test_db.py`, `test_retention.py`, `test_scheduler.py`
- `CLAUDE.md`, ADR 0022

รวม 17 ไฟล์ +1087/−61

## Commit
`9efb1f6` feat: the Energy Summary is stored and recomputed over the whole window every cycle (central-push #01)

## กับดักที่เสียเวลา (ถ้ามี)
- implementer ปฏิบัติตาม "Simplicity First" ตรงตัวเกินไป เลยไม่ลบแถวที่ค้าง แต่ตั้งเป็น flag ไว้เอง แล้ว reviewer ยกเป็น blocker สุดท้ายต้องใช้หนึ่งรอบรีวิว
- docstring อ้าง `export/format.py:474` ผิด ปัญหานี้มีอยู่ก่อนตั๋วนี้แล้ว ยังไม่ได้แก้
