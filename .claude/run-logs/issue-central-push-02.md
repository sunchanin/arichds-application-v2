# Ledger — Issue (central-push #02): ไฟล์ export ถูกแทนที่ในขั้นเดียว และมีหัวไฟล์ชุดเดียว
รัน: 2026-09-14 12:12–12:53 · branch: feature/light-modules · ผลลัพธ์: APPROVED_WITH_FIXES · รอบรีวิว: 1 · ticket lint: pass · Job A: ข้าม

## ต้นทุน
| สเตจ | เวลา (นาที) | tokens |
|---|---|---|
| Job A | — | — |
| implementer build | 25.1 | 292,855 (สะสม) |
| reviewer รอบ 1 | 4.1 | 106,380 (สะสม) |
| แก้ minor (ไม่รีวิวซ้ำ) | 10.2 | 331,719 (สะสม) |
| รอบ 2 — implementer / reviewer | — | — |
| **รวม** | **39.4** (wall clock 40.7) | ค่าสุดท้ายต่อ agent: implementer 331,719 · reviewer 106,380 |

agent ตายกลางคัน: ไม่มี

## ผลรีวิว
- verdict รอบ 1: APPROVED_WITH_FIXES — minor 4 ข้อ
  1. `tempfile.mkstemp` อยู่นอก `try` ถ้าสร้างไฟล์ชั่วคราวไม่ได้ error จะหลุดไปถึง API แล้วตอบ 500
  2. skew cap ในทาง rewrite ไม่มีเทสต์ที่จับได้
  3. comment และ docstring ฝั่ง backend ยังพูดถึงการ roll เป็นไฟล์ติดวันที่
  4. ข้อความบนหน้า `ExportFormat.tsx` ยังบอก operator ว่าจะมีไฟล์ติดวันที่
- probe ที่ reviewer ยิง: 3 ตัว
  - P1 ขอบ 90 วัน → แดง
  - P2 skew cap → **เขียว** (กลายเป็น problem ข้อ 2)
  - P3 เขียนไฟล์ทับตรงๆ ไม่ผ่านไฟล์ชั่วคราว → แดง
- รอบแก้: เพิ่มเทสต์ 2 ตัว implementer ส่งผลแดงภายใต้ mutation มาครบทั้งสองตัว · orchestrator ตรวจแล้วว่าบรรทัดสรุป full suite เป็นของจริงและผ่าน
- problems ที่ค้าง: ไม่มี

## Gate
| รอบ | คำสั่ง full-suite | เวลา | จาก repo doc? | summary line |
|---|---|---|---|---|
| build | `.venv/Scripts/pytest -n auto -q` | 127.74s | ใช่ | 2143 passed, 57 skipped |
| แก้ minor | `.venv/Scripts/pytest -n auto -q` | 229.25s | ใช่ | 2145 passed, 57 skipped |

ruff ผ่าน · `pnpm lint` ผ่าน · `pnpm build` ผ่าน (ใช้ 39.88s)

## ไฟล์ที่เปลี่ยน
**Backend**
- `export/writer.py`, `export/csv_export.py`, `export/billing_csv.py`, `export/energy_csv.py`
- `export/format.py`, `db/billing_query.py`

**เทสต์**
- `tests/test_export_writer.py` (ใหม่)
- `test_csv_export.py`, `test_billing_csv_export.py`, `test_energy_csv_export.py`

**Web และเอกสาร**
- `web/src/pages/ExportFormat.tsx`
- `CLAUDE.md`, ADR 0012, ADR 0023

รวม commit นี้ 15 ไฟล์ +958/−211 ซึ่งนับ ledger ของตั๋ว 01 รวมเข้าไปด้วย

## Commit
`5401ca7` refactor: export files are replaced in one step and carry exactly one head (central-push #02)

## กับดักที่เสียเวลา (ถ้ามี)
- full suite รอบแก้ใช้ 229s สูงกว่าปกติเกือบเท่าตัว น่าจะเพราะรันพร้อม `pnpm build`
- ledger ของตั๋ว 01 ไม่ได้ commit แยก จึงติดไปกับ commit ของตั๋วนี้
