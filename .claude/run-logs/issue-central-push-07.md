# Ledger — Issue (central-push #07): ผู้ดูแลตั้งค่า Central Push บนหน้า API
รัน: 2026-09-14 18:58–19:50 · branch: feature/light-modules · ผลลัพธ์: APPROVED_WITH_FIXES (รอบ 2) · รอบรีวิว: 2 · ticket lint: pass · Job A: ข้าม

## ต้นทุน
| สเตจ | เวลา (นาที) | tokens |
|---|---|---|
| Job A | — | — |
| implementer build | 28.0 | 324,673 (สะสม) |
| reviewer รอบ 1 | 3.8 | 119,173 (สะสม) |
| รอบ 2 — implementer / reviewer | 11.3 / 1.9 | 400,969 / 138,611 (สะสม) |
| แก้ nit หลังรอบ 2 (ไม่รีวิวซ้ำ) | 5.1 | 415,659 (สะสม) |
| **รวม** | **50.1** (wall clock 52.1) | ค่าสุดท้ายต่อ agent: implementer 415,659 · reviewer 138,611 |

agent ตายกลางคัน: ไม่มี

## ผลรีวิว
**verdict รอบ 1: CHANGES_REQUESTED** — 1 major, 5 minor, 2 nit

- **major:** `render_contract` แสดงฟิลด์ของ item เพียงสี่ชนิด ไม่ได้ไล่ `PushEnvelope` และ `HoldingsResponse` ทำให้ contract ขาด `machine_id`, `sent_at`, `items`, `newest_read_at`, `newest_updated_at` ทีม server จึงสร้าง endpoint ทั้งสองตัวจากหน้านี้ไม่ได้
- **minor**
  - เทสต์ชื่อ "tampered" จริงๆ ใช้ key อื่นเซ็น ไม่ได้แก้ bytes
  - ไม่มีเทสต์ยืนยันว่า URL ไม่ถูกเขียนเมื่อ token ถูกปฏิเสธ (probe 1 เขียว)
  - `Alert message=` เป็น prop ที่ antd v6 deprecate แล้ว
  - คำอธิบาย `updated_at` ใน contract บอกว่าเป็น UTC ขัดกับ note เรื่อง offset
  - หัวข้อ error ตอนบันทึกเขียนตายตัวว่า token ถูกปฏิเสธ
- **nit:** ชื่อ class เทสต์ผิด · ชื่อ `CycleOutcome` ยังไม่ตรงกับ spec (ยกไปทำในตั๋ว 08)

**verdict รอบ 2: APPROVED_WITH_FIXES** — nit 1: ชนิดข้อมูลใน contract ยังโชว์ชื่อภายในของ Python (แก้แล้ว พร้อมเทสต์ที่แดงภายใต้ mutation)

**probe ที่ reviewer ยิง**
- รอบ 1: 3 ตัว → แดง 2, เขียว 1 (commit URL ก่อนตรวจ token)
- รอบ 2: 3 ตัว → แดงทั้ง 3

**probe ที่ถูกบล็อก:** implementer ลองให้ API คืน token จริงของเทสต์ แต่ classifier ของ sandbox บล็อกไว้ · reviewer ยิงซ้ำด้วยค่าหลอก `"x"` แล้วได้แดง

**problems ที่ค้าง:** nit เรื่อง `CycleOutcome` ส่งต่อไปตั๋ว 08

## Gate
| รอบ | คำสั่ง full-suite | เวลา | จาก repo doc? | summary line |
|---|---|---|---|---|
| build | `.venv/Scripts/python -m pytest -n auto -q` | 210.29s | ใช่ | 2225 passed, 57 skipped |
| รอบ 2 | `.venv/Scripts/python -m pytest -n auto -q` | 190.43s | ใช่ | 2228 passed, 57 skipped |
| แก้ nit | `.venv/Scripts/python -m pytest -n auto -q` | 192.05s | ใช่ | 2229 passed, 57 skipped |

ruff ผ่าน · `pnpm lint` และ `pnpm build` ผ่านทุกรอบ

## ไฟล์ที่เปลี่ยน
**ไฟล์ใหม่**
- `api/central_push.py`
- `centralpush/__init__.py`, `centralpush/contract.py`, `centralpush/status.py`
- `tests/test_api_central_push.py`
- `web/src/pages/CentralPush.tsx`

**ไฟล์ที่แก้**
- `db/app_settings.py`, `constants.py`, `main.py`
- `tests/test_nav_feature_contract.py`
- `web/src/App.tsx`, `api.ts`, `components/AppShell.tsx`, `features.ts`
- `CLAUDE.md`, ADR 0024

รวม 16 ไฟล์ +1585/−8

## Commit
`565bde5` feat: an administrator configures the Central Push on the API page (central-push #07)

## กับดักที่เสียเวลา (ถ้ามี)
- **เกณฑ์ "rendered from those models":** implementer ตีความว่าหมายถึงเฉพาะ item model ทั้งที่เกณฑ์บรรทัดก่อนหน้าระบุชื่อ holdings response และ push envelope ไว้ด้วย
- **probe ที่ย้าย `set_setting` ไปก่อนตรวจ token แต่ไม่ commit** ยังเขียว เพราะ session rollback ตอนปิด ต้องใส่ commit ด้วยจึงจำลองบั๊กจริงได้
- **ตั๋วใบนี้ไม่ได้เขียน ledger ตอนตั๋ว 06 จบแล้ว batch หยุด:** ตั๋ว 07 เริ่มใน session ใหม่ ซึ่ง command แทนค่าอาร์กิวเมนต์เพี้ยนอีกครั้ง (แสดงเป็น "#8 ถึง #$2") orchestrator จึงรันตามที่เจ้าของสั่งไว้ คือตั๋ว 07–08
