# Ledger — Issue (file-upload #03): ไฟล์ไปถึง server ของทีมทาง HTTPS
รัน: 2026-09-17 19:12–20:27 · branch: feature/light-modules · ผลลัพธ์: APPROVED_WITH_FIXES (รอบ 1) · รอบรีวิว: 1 · ticket lint: pass · Job A: ข้าม

## ต้นทุน
| สเตจ | เวลา (นาที) | tokens |
|---|---|---|
| Job A | — | — |
| implementer build | 41.7 | 351,983 (สะสม) |
| ส่งกลับไปเรียก skill (ก่อนรีวิว) | 6.6 | 369,940 (สะสม) |
| reviewer รอบ 1 | 10.0 | 143,417 |
| แก้ minor/nit (ไม่รีวิวซ้ำ) | 13.5 | 421,719 (สะสม) |
| **รวม** | **71.8** (wall clock 75.0) | implementer 421,719 · reviewer 143,417 |

agent ตายกลางคัน: ไม่มี · lib-notes ของ paramiko/pyftpdlib ทำขนานด้วย agent อีกตัว (10.1 นาที, 196,005 tokens) commit แยก `4cee1e5`

## ผลรีวิว
- **ก่อนรีวิว:** implementer ไม่ได้เรียก `fastapi`/`antd-ui` ทั้งที่แตะ router และสองหน้า → ส่งกลับตามขั้นตอน /run-issue Step 2; skill `fastapi` ทำให้พบ 1 จุด (`result: str` → `Literal` ตาม sibling `DatabaseDestinationTestOut`) `antd-ui` ไม่มีอะไรต้องแก้
- **verdict รอบ 1: APPROVED_WITH_FIXES** — 0 blocker, 0 major, 5 minor, 3 nit
  - **ตัดสินเรื่อง Remote root กับ manifest (flag ของ implementer):** endpoint ตามตั๋วถูกแล้ว — Bearer token ระบุเครื่องอยู่แล้ว server จึงแยก manifest ตาม token; Remote root ถึง wire เฉพาะใน `PUT /v1/files/{relative path}`; story 10 ของ spec เป็นเรื่อง*ไฟล์*ชนกัน ไม่ใช่ manifest → เขียนเป็น decision ใน CLAUDE.md และเพิ่ม note ในเอกสาร Files (optional) ว่า key ของ manifest ไม่มี root prefix
  - **minor:** `put_file` อ่านไฟล์สองครั้ง (body กับ sha256) — export file ถูก `os.replace` ระหว่างสองครั้งได้ → อ่านครั้งเดียว digest จาก buffer · `connect()` ของ HTTP/HTTPS connection ซ้ำกันสองก้อนและก้อน HTTPS ไม่มีเทสต์ไหนเดินถึง `settimeout` → รวมเป็น mixin เดียว · ไม่มีเทสต์ pin ว่า Test connection ใช้ timeout สั้น (probe `900` เขียว) → endpoint ส่ง constant ชัดเจน + เทสต์จับ kwargs
  - **nit:** `logger` ไม่ได้ใช้ · assertion `!= "TypeError"` ซ้ำซ้อนกับ `pytest.raises` · **แท็บ HTTPS รับ URL `http://` ได้** (ตรง convention เดิมของ `CentralPushIn.url`/`db_dest_host`) → ไม่แก้ในตั๋วนี้ ออกเป็น `docs/issues/021`
- **probe ที่ reviewer ยิง: 3** — `check_hostname=True` กลับเข้าไปใน `https_open` → `TypeError` หลุด `pytest.raises` **แดง** (บั๊กเดิมของ M14 #08 ถูกเทสต์จับแล้ว) · `_remote_path` ไม่ใส่ root → แดง · timeout ของ Test connection = 900 → **เขียว** (นำไปสู่ minor 5)
- **problems ที่ค้าง:** ไม่มี (nit 7 = issue 021)

## Gate
| รอบ | คำสั่ง full-suite | เวลา | จาก repo doc? | summary line |
|---|---|---|---|---|
| build | `pytest -n auto -q` (app/) | 204.21s | ใช่ | 2388 passed, 55 skipped |
| หลังเรียก skill | `pytest -n auto -q` (app/) | 221.81s | ใช่ | 2388 passed, 55 skipped |
| แก้ minor | `pytest -n auto -q` (app/) | 265.84s | ใช่ | 2389 passed, 55 skipped |

ruff format/check ผ่าน · `pnpm lint` + `pnpm build` ผ่าน · orchestrator รัน scoped ซ้ำก่อน commit: 45 passed (2 ไฟล์) · ไม่มี `httpx`/`requests` ใน transport · ไม่มีอักษรไทยใน `web/src`

## ไฟล์ที่เปลี่ยน
- **prefactor (commit แยก):** `app/src/arichds/split_timeout_http.py` (ใหม่ — `build_split_timeout_opener(connect_timeout, read_timeout)`, mixin `connect()` เดียว), `centralpush/client.py` (delegate)
- **โค้ดใหม่:** `fileupload/https_transport.py` (`HttpsTransport`, `check_https_connection`, `SHA256_HEADER = X-ARICHDS-File-Sha256`)
- **โค้ดที่แก้:** `fileupload/cycle.py` (`_build_transport` คืน HTTPS จริง), `api/file_upload.py` (`POST /https/test`), `centralpush/contract.py` (Files (optional) จาก constant ของ transport), `constants.py` (3 timeout)
- **เทสต์:** `test_fileupload_https_transport.py` (ใหม่ 20 — รวม TLS-wrapped server ที่ปฏิเสธ self-signed), `fake_central_push_receiver.py` (3 endpoint ไฟล์), `test_fileupload_config_api.py`, `test_api_central_push.py` (`TestFilesSection`)
- **web:** `api.ts`, `pages/FileUploadDestination.tsx` (Test connection บนแท็บ HTTPS), `pages/CentralPush.tsx` (panel Files (optional))
- **เอกสาร:** `CLAUDE.md`, `SPEC.md`, `installer/README.md` (แถว troubleshooting)

## Commit
`4a39f52` refactor: the split-timeout urllib opener moves out of the push client (file-upload #03 prefactor)
`c35c3f2` feat: files reach the team's server over HTTPS (file-upload #03)

## กับดักที่เสียเวลา (ถ้ามี)
- implementer อนุมานเนื้อหา skill จาก precedent แทนการเรียก Skill tool — ต้องส่งกลับ 6.6 นาที และ skill ก็หาอะไรเจอจริง (type ของ `result`)
- ตั๋วเขียน "in its own commit" ให้ implementer ที่ห้าม commit — แก้ด้วยการให้รายงาน prefactor เป็นกลุ่มไฟล์แยก orchestrator commit สองก้อน
