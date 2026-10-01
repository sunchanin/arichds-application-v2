# Ledger — Issue (central-push #04): เขียนไฟล์ Energy และ Billing ใหม่ทั้งไฟล์ทุกรอบ
รัน: 2026-09-14 13:28–14:10 · branch: feature/light-modules · ผลลัพธ์: APPROVED_WITH_FIXES · รอบรีวิว: 1 · ticket lint: pass · Job A: ข้าม

## ต้นทุน
| สเตจ | เวลา (นาที) | tokens |
|---|---|---|
| Job A | — | — |
| implementer build | 30.5 | 318,461 (สะสม) |
| reviewer รอบ 1 | 4.6 | 120,594 (สะสม) |
| แก้ minor (ไม่รีวิวซ้ำ) | 6.0 | 346,090 (สะสม) |
| รอบ 2 — implementer / reviewer | — | — |
| **รวม** | **41.1** (wall clock 42.1) | ค่าสุดท้ายต่อ agent: implementer 346,090 · reviewer 120,594 |

agent ตายกลางคัน: ไม่มี · implementer ส่งแจ้งเตือนจบงานสองครั้ง ครั้งที่สองเป็นแค่การยืนยันผล grep ซ้ำ ไม่ใช่งานเพิ่ม

## ผลรีวิว
- verdict รอบ 1: APPROVED_WITH_FIXES — minor 2 ข้อ
  1. เทสต์ "matches the page" ไม่ได้ export ก่อนเพิ่มวันหยุด จึงแยกไฟล์ค้างออกจากไฟล์ใหม่ไม่ได้ (probe 1 เขียว)
  2. docstring ใน `api/billing.py` และ `web/src/api.ts` ยังอธิบายการ append แบบใช้ watermark
- probe ที่ reviewer ยิง: 3 ตัว
  - ไม่เขียนทับไฟล์เดิม → แดง 3 เทสต์ แต่เทสต์ matches-the-page เขียว
  - Save to file อ่านแบบ live → แดง
  - Billing จำกัดไว้ 90 วัน → แดง 24 เทสต์
- รอบแก้: implementer ยืนยันว่าเทสต์ที่แก้แล้วแดงภายใต้ mutation ที่ reviewer ระบุ · orchestrator ตรวจแล้วว่าบรรทัดสรุป full suite เป็นของจริง
- scope ที่ reviewer ยอมให้ยกขึ้นมาทำก่อน: ถอด `affected_date` / `energy_files_written_past` ออกจาก Holiday response และถอดคำเตือนไฟล์ค้างบนหน้า Holidays เพราะเกณฑ์ "ไม่มีโค้ดอ่านคอลัมน์ที่ถูก drop" บังคับให้ต้องทำ · ส่วนที่เหลือของตั๋ว 06 (ตาราง `holiday_changes`, endpoint อ่าน, notice) ยังเป็นงานของตั๋ว 06
- พฤติกรรมที่เปลี่ยนโดยตั้งใจ
  - Energy file รวมวันนี้ด้วย ให้ตรงกับหน้าต่างของตาราง
  - ถ้าหน้าต่างว่างทั้งหมด ไฟล์เดิมจะถูกเก็บไว้
  - `rows_written` ของ Billing หมายถึงจำนวนแถวทั้งไฟล์ ไม่ใช่ส่วนที่เพิ่ม
- problems ที่ค้าง: ไม่มี

## Gate
| รอบ | คำสั่ง full-suite | เวลา | จาก repo doc? | summary line |
|---|---|---|---|---|
| build | `pytest -n auto -q` | 225.10s | ใช่ | 2167 passed, 57 skipped |
| แก้ minor | `.venv/Scripts/pytest -n auto -q` | 153.53s | ใช่ | 2167 passed, 57 skipped |

ruff ผ่าน · `pnpm lint` และ `pnpm build` ผ่าน
จำนวนเทสต์ลดลง 5 ตัว (2172 → 2167): เทสต์ของ Energy file ลดจาก 30 เหลือ 22 · reviewer ไล่ครบทุกตัวที่หายไป ทุกตัวเป็นพฤติกรรมที่ถูกลบจริง

## ไฟล์ที่เปลี่ยน
- migration และ model
  - `migrations/versions/0018_drop_billing_and_energy_export_watermarks.py` (ใหม่)
  - `db/models.py`
- export
  - `export/energy_csv.py`
  - `export/billing_csv.py`
  - `db/energy_query.py`
- API
  - `api/holidays.py`
  - `api/billing.py`
- web
  - `web/src/api.ts`
  - `web/src/pages/Holidays.tsx`
- เทสต์
  - `tests/test_migration_0018.py` (ใหม่)
  - `test_energy_csv_export.py`
  - `test_billing_csv_export.py`
- เอกสาร
  - `CLAUDE.md`
  - ADR 0022, ADR 0023

รวม 16 ไฟล์ +678/−775 (นับ ledger ของตั๋ว 03 รวมไปด้วย)

## Commit
`f8a4004` feat: the Energy and Billing files are rewritten whole every cycle (central-push #04)

## กับดักที่เสียเวลา (ถ้ามี)
- ตั๋ว 04 กับตั๋ว 06 แตะโค้ดส่วนเดียวกัน คือฟังก์ชันที่คำนวณคำเตือนไฟล์ค้าง ซึ่งอ่านคอลัมน์ที่ถูก drop · ตอนเขียนตั๋วไม่ได้จับคู่นี้ไว้ ควรปรับ /to-tickets
