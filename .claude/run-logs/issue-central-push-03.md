# Ledger — Issue (central-push #03): ออกและตรวจสอบ Push Token ได้
รัน: 2026-09-14 12:53–13:27 · branch: feature/light-modules · ผลลัพธ์: APPROVED_WITH_FIXES (รอบ 2) · รอบรีวิว: 2 · ticket lint: pass · Job A: ข้าม

## ต้นทุน
| สเตจ | เวลา (นาที) | tokens |
|---|---|---|
| Job A | — | — |
| implementer build | 15.5 | 185,817 (สะสม) |
| reviewer รอบ 1 | 2.9 | 73,678 (สะสม) |
| รอบ 2 — implementer / reviewer | 6.5 / 1.3 | 236,849 / 86,519 (สะสม) |
| แก้ minor หลังรอบ 2 (ไม่รีวิวซ้ำ) | 2.7 + 5.8 (resume) | 244,628 (สะสม) |
| **รวม** | **34.7** (wall clock 33.7) | ค่าสุดท้ายต่อ agent: implementer 244,628 · reviewer 86,519 |

agent ตายกลางคัน: implementer จบ turn ขณะรอ full suite ที่ตัวเองสั่งรันเบื้องหลัง (ไม่ใช่ตาย) · resume ตัวเดิมด้วย SendMessage ให้รันแบบ foreground
หมายเหตุเวลา: ผลรวมของเวลาที่ agent แจ้งมาสูงกว่า wall clock ~1 นาที เพราะ `duration_ms` ของรอบที่ resume อาจนับซ้อนกัน จึงใช้ wall clock เป็นตัวหลัก

## ผลรีวิว
- **verdict รอบ 1: CHANGES_REQUESTED** — 1 blocker, 1 major, 1 minor
  - **blocker:** `jwt.decode` ตรวจ `iat` แบบไม่เผื่อเวลาเลย token ที่ `iat` ล้ำหน้านาฬิกาเครื่องที่ตรวจเพียง 5 วินาทีจึงถูกปฏิเสธเป็น MALFORMED — reviewer ทดลองแล้วเกิดจริง
  - **major:** Activation Code ถูกปฏิเสธด้วยเหตุผลเดียวกับข้อความมั่ว ขัดกับเกณฑ์ "a distinct reason for each"
  - **minor:** เทสต์ "ไม่มี `exp`" ตรวจผ่าน helper แทนผลลัพธ์จริงของ `sign-push`
- **verdict รอบ 2: APPROVED_WITH_FIXES** — minor 2 ข้อ เป็นเอกสารล้วน (comment บน `MALFORMED` กับ digest ของ ADR 0024 ใน CLAUDE.md)
- **probe ที่ reviewer ยิง:**
  - รอบ 1: 3 ตัว → แดง 2 เขียว 1 (ตัวที่เขียวคือเพิ่ม `exp` เข้าไปใน `cmd_sign_push`)
  - รอบ 2: 3 ตัว → แดงทั้ง 3
- **ความผิดพลาดของ implementer รอบ build:** รายงานว่าไม่ได้ทำ mutation probe กับ logic เลย red ที่แสดงมาเป็นแค่ red จากสัญลักษณ์ที่ยังไม่มี และตีความ "distinct reason" เองโดยยุบเหตุผลรวมกัน
- **problems ที่ค้าง:** ไม่มี

## Gate
| รอบ | คำสั่ง full-suite | เวลา | จาก repo doc? | summary line |
|---|---|---|---|---|
| build | `.venv\Scripts\pytest -n auto -q` | 136.85s | ใช่ | 2171 passed, 57 skipped |
| รอบ 2 | `.venv/Scripts/pytest -n auto -q` | 146.24s | ใช่ | 2172 passed, 57 skipped |
| แก้เอกสาร | `.venv/Scripts/pytest -n auto -q` | 156.07s | ใช่ | 2172 passed, 57 skipped |

- รอบ build รอบแรกมีเทสต์ล้ม 1 ตัว: `test_capture_renderers.py::TestDisplayUnitScalePdf::test_kilo_is_the_default` เป็นไฟล์ที่ตั๋วนี้ไม่ได้แตะ รันเดี่ยวผ่าน รันซ้ำก็ผ่าน ลักษณะตรงกับ docs/issues/008 (PDF bytes มี timestamp)
- ruff ผ่านทุกรอบ

## ไฟล์ที่เปลี่ยน
- `app/src/arichds/licensing/push_token.py` (ใหม่)
- `app/tests/test_push_token.py` (ใหม่)
- `app/src/arichds/licensing/__init__.py`
- `tools/arichds_vendor.py` (`sign-push`)
- `CLAUDE.md`
- commit นี้รวม ledger ของตั๋ว 02 ไปด้วย

## Commit
`cb173cf` feat: a Push Token can be issued and verified (central-push #03)

## กับดักที่เสียเวลา (ถ้ามี)
- **token ถูกปฏิเสธเพราะนาฬิกาต่างกัน:** PyJWT ตรวจ `iat` เป็นค่าตั้งต้น ถ้าไม่ปิด token ที่ถูกต้องจะถูกปฏิเสธเมื่อนาฬิกาเครื่องลูกค้าช้ากว่าเครื่อง vendor — implementer ไม่เห็นเอง reviewer จับได้จากการทดลอง
- **implementer หยุดรอ suite ที่รันเบื้องหลังเอง** ต้อง resume ตัวเดิมด้วย SendMessage
- **ไม่ได้ทำ Q1 เพิ่ม:** ห้าม `keygen` และทุก probe ใช้ key ชั่วคราว
