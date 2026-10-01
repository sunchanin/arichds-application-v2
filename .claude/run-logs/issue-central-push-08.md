# Ledger — Issue (central-push #08): เครื่อง push ขึ้น central server ทุกรอบ
รัน: 2026-09-14 19:51–21:05 · branch: feature/light-modules · ผลลัพธ์: APPROVED_WITH_FIXES (รอบ 2) · รอบรีวิว: 2 · ticket lint: pass · Job A: ข้าม

## ต้นทุน
| สเตจ | เวลา (นาที) | tokens |
|---|---|---|
| Job A | — | — |
| implementer build | 36.8 | 420,043 (สะสม) |
| reviewer รอบ 1 | 4.6 | 114,710 (สะสม) |
| รอบ 2 — implementer / reviewer | 16.6 / 3.2 | 524,104 / 146,533 (สะสม) |
| แก้ minor หลังรอบ 2 (ไม่รีวิวซ้ำ) | 11.1 | 534,417 (สะสม) |
| **รวม** | **72.3** (wall clock 74.8) | ค่าสุดท้ายต่อ agent: implementer 534,417 · reviewer 146,533 |

agent ตายกลางคัน: ไม่มี

## ผลรีวิว
- **verdict รอบ 1: CHANGES_REQUESTED** — 1 blocker, 1 major, 2 minor, 1 nit
  - **blocker:** `client.py` ส่ง `check_hostname=` ให้ `http.client.HTTPSConnection` ซึ่ง Python 3.12 ตัดพารามิเตอร์นี้ออกแล้ว ทุก URL `https://` จึงล้มด้วย `TypeError` และ status แสดงเป็น skipped ดูเหมือนเครือข่ายขัดข้อง ทั้งที่ central server จริงเป็น HTTPS · เทสต์ทุกตัวใช้ `http://` จึงไม่มีตัวไหนผ่านทาง HTTPS
  - **major:** ตรวจงบเวลาเฉพาะตอนเปลี่ยนชนิดข้อมูล · reviewer ตั้งงบ 0.6s แต่รอบใช้จริง 2.69s · query ของ billing และ Energy Summary ไม่มี `ORDER BY` ถ้าหยุดกลางคัน แถวที่ `updated_at` เก่ากว่าอาจไม่ถูกส่งอีกเลย
  - **minor:** ไม่มีเทสต์ยืนยันว่ารายชื่อมิเตอร์ที่ว่างยังถูกส่ง · `SPEC.md:1276` ยังอธิบายเป็น watermark ที่เลื่อนตาม ACK
  - **nit:** มีเทสต์ "ลงทะเบียนเป็นลำดับสุดท้าย" ซ้ำกันสองไฟล์
- **verdict รอบ 2: APPROVED_WITH_FIXES**
  - **minor:** comment อ้างว่าการเรียงลำดับทำให้ "ส่งไปแค่บางส่วนก็ปลอดภัยเสมอ" ซึ่งไม่จริงเมื่อหลายแถวมี `updated_at` เท่ากัน · recompute ประทับเวลาเดียวทั้งรอบ ปัญหานี้จะเกิดได้ก็ต่อเมื่อชนิดข้อมูลหนึ่งมีเกิน 5,000 แถว · แก้เฉพาะ comment ไม่แตะพฤติกรรม
  - **nit:** มี `return 0` ซ้ำ
- **probe ที่ reviewer ยิง**
  - รอบ 1: 3 ตัว → แดง 2, เขียว 1 (ตัวที่เขียวคือ `send_when_empty` ของรายชื่อมิเตอร์)
  - รอบ 2: 5 ตัว ผลตามคาดครบ
    - probe งบเวลาเดิมลดจาก 2.69s เหลือ 0.88s
    - HTTPS ล้มเป็น `URLError` แทน `TypeError`
    - load profile ส่งครบ 16/16 แถว ไม่มีแถวซ้ำ
    - หยุดกลางคันแล้วรอบถัดไปส่งต่อได้ครบ 12/12
    - `send_when_empty` ตอนนี้แดงแล้ว
- **ประเด็นที่ reviewer ตัดสินให้**
  - แยกเกณฑ์ "รอบที่สองส่งแค่รายชื่อมิเตอร์" สำหรับ load profile ออกมา → ตีความตรงกับตั๋ว ไม่ได้ลดเกณฑ์ลง
  - rewind 60s → รับได้
  - ไม่เรียก skill `fastapi` → ถูกต้อง เพราะไม่ได้แตะ route
- **problems ที่ค้าง:** ไม่มี
- **ข้อควรทราบก่อนใช้งานจริง:** ยังไม่เคยทดสอบกับ server จริง ต้องส่ง contract จากหน้า API ให้ทีมปลายทาง และปลายทางต้องมีทั้ง `GET /v1/holdings` และ `POST /v1/push`

## Gate
| รอบ | คำสั่ง full-suite | เวลา | จาก repo doc? | summary line |
|---|---|---|---|---|
| build | `.venv/Scripts/python -m pytest -n auto -q` | 169.25s | ใช่ | 2250 passed, 57 skipped |
| รอบ 2 | `.venv/Scripts/python -m pytest -n auto -q` | 209.79s | ใช่ | 2255 passed, 57 skipped |
| แก้ minor | `.venv/Scripts/python -m pytest -n auto -q` | 310.79s | ใช่ | 2255 passed, 57 skipped |

รอบแก้ minor ครั้งแรกเจอ flake ที่รู้จักอยู่แล้ว (`test_kilo_is_the_default`, docs/issues/008) รันแยกเดี่ยวผ่าน รันทั้งชุดใหม่ก็ผ่าน · ruff ผ่าน · ไม่ได้แตะ `web/`

## ไฟล์ที่เปลี่ยน
- **โค้ดใหม่:** `app/src/arichds/centralpush/client.py`, `app/src/arichds/centralpush/cycle.py`
- **โค้ดที่แก้:** `centralpush/status.py`, `constants.py`, `jobs/scheduler.py`
- **เทสต์ใหม่:** `app/tests/fake_central_push_receiver.py`, `app/tests/test_central_push_cycle.py`
- **เทสต์ที่แก้:** `test_scheduler.py`
- **เอกสาร:** `CLAUDE.md`, `SPEC.md`, ADR 0024
- รวม ledger ของตั๋ว 07 ไว้ใน commit เดียวกัน

## Commit
`93bf70e` feat: the machine pushes to the central server every cycle (central-push #08)

## กับดักที่เสียเวลา (ถ้ามี)
- implementer เขียน HTTPS handler จากความจำของ stdlib รุ่นเก่า และเทสต์ทั้งหมดใช้ http จึงไม่มีเทสต์ไหนเดินผ่านทางนั้น · reviewer จับได้ด้วยการเรียกฟังก์ชันกับ `https://` ตรงๆ
- ตรวจงบเวลาแค่ระหว่างชนิดข้อมูล เพราะเข้าใจผิดว่าเท่ากับที่ `dataout/sync.py` ทำ ทั้งที่ของเดิมตรวจทุก chunk
