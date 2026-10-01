# Ledger — Issue (file-upload #02): รอบอัปโหลดส่งสิ่งที่ Upload Manifest ยังไม่มี ผ่าน transport ในหน่วยความจำ
รัน: 2026-09-16 22:15–23:46 · branch: feature/light-modules · ผลลัพธ์: APPROVED_WITH_FIXES (รอบ 2) · รอบรีวิว: 2 · ticket lint: pass · Job A: ข้าม

## ต้นทุน
| สเตจ | เวลา (นาที) | tokens |
|---|---|---|
| Job A | — | — |
| implementer build | 38.4 | 407,222 (สะสม) |
| reviewer รอบ 1 | 9.9 | 142,590 |
| รอบ 2 — implementer / reviewer | 22.9 / 6.8 | 546,212 / 187,586 (สะสม) |
| แก้ nit หลังรอบ 2 (ไม่รีวิวซ้ำ) | 8.4 | 566,084 (สะสม) |
| **รวม** | **86.4** (wall clock 90.5) | implementer 566,084 · reviewer 187,586 |

agent ตายกลางคัน: ไม่มี

## ผลรีวิว
- **verdict รอบ 1: CHANGES_REQUESTED** — 0 blocker, 1 major, 2 minor, 3 nit
  - **major:** cycle คำนวณชื่อไฟล์ export ซ้ำจาก template ด้วยมือแทนอ่านโฟลเดอร์ → reviewer เปลี่ยน `export/format.py::render_filename` แล้วเทสต์ทั้งไฟล์ยังเขียว 14/14 · และ `[date]` token ถูก render เป็นวันนี้ ทำให้ไฟล์วันก่อนๆ มองไม่เห็น**ตั้งแต่วันนี้** · แก้: `filename_tokens.py` ที่ package top (precedent `interval_status.py`) ให้ `render_filename` delegate + `export_filename_pattern` (regex anchored, `[date]` = wildcard ISO date) และ `_export_candidates` list โฟลเดอร์แล้ว match, ตัด `.stem.*.tmp` ของ writer ออก
  - **minor:** Upload now หมดเวลารอแล้วตอบ 200 พร้อม status เก่า หน้าโชว์ success → ตอบ `{finished, status}` หน้าโชว์ "Still running — press Refresh in a moment." · cycle ที่ไม่ได้ตั้งค่าไม่ publish status → outcome `not_configured`
  - **nit:** ชื่อเทสต์ scheduler ค้าง · label แถว "Files skipped" ที่จริงนับ device · เขียน manifest ซ้ำทุกรอบแม้ไม่ส่งอะไร
- **verdict รอบ 2: APPROVED_WITH_FIXES** — 2 nit (docstring ขัดโค้ดเรื่อง status null · dedupe candidate ที่ match สอง template) แก้แล้ว ไม่รีวิวซ้ำ
- **probe ที่ reviewer ยิง**
  - รอบ 1: 3 — manifest rebuild แดง · digest compare แดง · **`render_filename` เปลี่ยนแล้วเขียว** (ตัวที่นำไปสู่ major)
  - รอบ 2: 3 — probe เดิม `render_filename` แดง 9/18 · `[date]` match เฉพาะวันนี้ แดง 2 · `finished = True` ตายตัว แดง 1
- **ประเด็นที่ reviewer ตัดสินให้:** เปลี่ยน `logger.exception` → `logger.warning` (class name) ถูกต้อง เพราะ `CredentialRedactionFilter` เขียนทับแค่ `record.msg` ไม่แตะ `exc_info` · ตัด path-containment check ออกได้เพราะ `iterdir()` ให้แค่ direct children · ปุ่ม Upload now บน status card รับได้ · การ re-index เทสต์ "second to last" ไม่ได้อ่อนเกณฑ์
- **problems ที่ค้าง:** ไม่มี
- **finding นอกขอบเขต (ทั้ง implementer และ reviewer ชี้):** `centralpush/cycle.py` ใช้ `logger.exception` ใน generic except → `exc_info` เลี่ยง redaction filter · ออกเป็น `docs/issues/020`

## Gate
| รอบ | คำสั่ง full-suite | เวลา | จาก repo doc? | summary line |
|---|---|---|---|---|
| build | `pytest -n auto -q` (app/) | 313.89s | ใช่ | 2344 passed, 55 skipped |
| รอบ 2 | `pytest -n auto -q` (app/) | 270.41s | ใช่ | 2358 passed, 55 skipped |
| แก้ nit | `pytest -n auto -q` (app/) | 247.97s | ใช่ | 2359 passed, 55 skipped |

ruff format/check ผ่าน · `pnpm lint` + `pnpm build` ผ่าน · orchestrator รัน scoped ซ้ำก่อน commit: 89 passed (4 ไฟล์) · ไม่มีอักษรไทยใน `web/src` · `fileupload/` ไม่ import `arichds.export`/`arichds.capture`

## ไฟล์ที่เปลี่ยน
- **โค้ดใหม่:** `app/src/arichds/filename_tokens.py`, `app/src/arichds/fileupload/{cycle,manifest,transport}.py`
- **โค้ดที่แก้:** `export/format.py` (delegate), `fileupload/status.py` (3 skip fields + `not_configured`), `api/file_upload.py` (`POST /upload-now`, `FileUploadUploadNowOut`), `constants.py` (`FILEUPLOAD_INTERVAL_SEC`/`FILEUPLOAD_BUDGET_SEC`/`JOB_FILE_UPLOAD`), `jobs/scheduler.py` (job ที่ 11 ท้ายสุด)
- **เทสต์ใหม่:** `test_fileupload_cycle.py` (19), `test_filename_tokens.py`
- **เทสต์ที่แก้:** `test_fileupload_config_api.py`, `test_scheduler.py`
- **web:** `api.ts`, `pages/FileUploadDestination.tsx` (ปุ่ม Upload now, status card 3 เหตุผล skip, ประโยค not_configured)
- **เอกสาร:** `CLAUDE.md`, `SPEC.md`
- รวม ledger ของตั๋ว 01 ไว้ใน commit เดียวกัน

## Commit
`9cb424f` feat: the upload cycle sends what the Upload Manifest lacks, against an in-memory transport (file-upload #02)

## กับดักที่เสียเวลา (ถ้ามี)
- implementer "อ่านโฟลเดอร์" โดยการทำนายชื่อไฟล์จาก template แล้ว `exists()` — ผ่านเทสต์ทุกตัวเพราะ fixture ก็ hardcode ชื่อเดียวกัน (สาม copy ของกฎเดียว ไม่มีอะไรผูกกัน) · reviewer จับได้ด้วย probe ที่ mutate โค้ด**นอก**ตั๋ว (`export/format.py`) — probe ที่ดีคือ mutate ฝั่งที่ตั๋วอ้างว่าเป็น contract
- `logger.exception` ทำให้ secret รั่วผ่าน `exc_info` — เทสต์ที่ implementer เขียนตาม note ของ reviewer ตั๋ว 01 จับได้เอง
