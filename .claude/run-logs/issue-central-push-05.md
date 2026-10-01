# Ledger — Issue (central-push #05): Load Profile CSV เก็บเพียง 90 วัน
รัน: 2026-09-14 14:10–14:47 · branch: feature/light-modules · ผลลัพธ์: APPROVED_WITH_FIXES (รอบ 2) · รอบรีวิว: 2 · ticket lint: pass · Job A: ข้าม

## ต้นทุน
| สเตจ | เวลา (นาที) | tokens |
|---|---|---|
| Job A | — | — |
| implementer build | 13.3 | 196,018 (สะสม) |
| reviewer รอบ 1 | 4.1 | 79,425 (สะสม) |
| รอบ 2 — implementer / reviewer | 9.7 / 3.4 | 253,085 / 100,726 (สะสม) |
| แก้ minor หลังรอบ 2 (ไม่รีวิวซ้ำ) | 4.6 | 271,232 (สะสม) |
| **รวม** | **35.1** (wall clock 37.1) | ค่าสุดท้ายต่อ agent: implementer 271,232 · reviewer 100,726 |

agent ตายกลางคัน: ไม่มี

## ผลรีวิว
- **verdict รอบ 1: CHANGES_REQUESTED** — 1 major, 2 minor, 1 nit
  - **major:** job ตัดไฟล์รายวันปล่อยให้ไฟล์เก็บข้อมูลเกิน 90 วันไปตลอดในสองกรณี
    - มิเตอร์ที่ถูก pause ถูกข้าม ทั้งที่ job นี้ไม่อ่านมิเตอร์เลย
    - มิเตอร์ที่ Logger 1 ถูก retention ลบหมดแล้ว `_resolve_export_context` คืน `None` ทำให้ไฟล์ไม่ถูกแตะอีก
  - **minor:** ไม่มีเทสต์ที่ยืนยันว่า job ตัดไฟล์รายวันเคารพสวิตช์ auto-save
  - **minor:** ลำดับ scheduler ใน spec ไม่มี job นี้
- **verdict รอบ 2: APPROVED_WITH_FIXES** — 1 minor, 2 nit
  - **minor:** เงื่อนไข "ไม่สร้างไฟล์ใหม่" ครอบแค่กรณีไม่มี Logger 1 ทำให้ job สร้างไฟล์ให้มิเตอร์ที่ pause ได้ ซึ่งเป็นงานของรอบ export
  - **nit 3** (ย้ายการตรวจโฟลเดอร์ขึ้นก่อน ทำให้ log warning ทุก 15 นาทีในกรณีขอบ): implementer เลือกไม่แก้ พร้อมให้เหตุผล
- **probe ที่ reviewer ยิง**
  - รอบ 1: 3 ตัว → แดง 2 เขียว 1 (ตัวที่เขียวคือ `require_auto_save` ของตัว job)
  - รอบ 2: 3 ตัว → แดง 2 เขียว 1 (ตัวที่เขียวคือเงื่อนไขกันการสร้างไฟล์)
- **ข้อบกพร่องของ implementer ตอน build**
  - ไม่ได้ทำ mutation probe กับ logic เลย red ทั้งหมดเกิดจากสัญลักษณ์ที่ยังไม่มี
  - เขียนเทสต์ล็อกพฤติกรรมที่ผิดไว้ คือ "ข้ามมิเตอร์ที่ pause"
  - รอบแก้ทั้งสองรอบส่ง red ภายใต้ mutation มาครบ
- **problems ที่ค้าง:** ไม่มี

## Gate
| รอบ | คำสั่ง full-suite | เวลา | จาก repo doc? | summary line |
|---|---|---|---|---|
| build | `.venv/Scripts/pytest -n auto -q` | 156.28s | ใช่ | 2176 passed, 57 skipped |
| รอบ 2 | `.venv/Scripts/pytest -n auto -q` | 200.99s | ใช่ | 2178 passed, 57 skipped |
| แก้ minor | `.venv/Scripts/pytest -n auto -q` | 117.01s | ใช่ | 2179 passed, 57 skipped |

ruff ผ่านทุกรอบ

## ไฟล์ที่เปลี่ยน
- `app/src/arichds/export/csv_export.py`
- `app/src/arichds/constants.py`
- `app/src/arichds/jobs/scheduler.py`
- `app/tests/test_csv_export.py`
- `app/tests/test_scheduler.py`
- `CLAUDE.md`
- ADR 0023
- `.scratch/central-push/spec.md`

commit นี้รวม ledger ของตั๋ว 04 ไปด้วย

## Commit
`7663e83` feat: the Load Profile CSV keeps 90 days (central-push #05)

## กับดักที่เสียเวลา (ถ้ามี)
- **implementer ลอก filter `enabled` มาจาก `csv_export_cycle` โดยไม่ดูเหตุผล** ตัว export ข้ามมิเตอร์ที่ pause เพื่อไม่ให้แถวข้อมูลหาย แต่ job ตัดไฟล์ไม่มีแถวอะไรจะหาย เพราะ retention ลบแถวเก่าออกไปแล้ว
- **เทสต์ของ cycle ไม่เคยเรียก `purge_expired`** ขณะที่ production รัน retention ทันทีก่อน job ตัดไฟล์ กรณี "Logger 1 ถูกลบหมด" จึงไม่เคยถูกทดสอบ
