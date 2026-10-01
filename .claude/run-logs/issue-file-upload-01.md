# Ledger — Issue (file-upload #01): ผู้ดูแลตั้งค่าหน้า FTP ได้ แต่ยังไม่ส่งอะไร
รัน: 2026-09-16 21:02–22:14 · branch: feature/light-modules · ผลลัพธ์: APPROVED_WITH_FIXES (รอบ 1) · รอบรีวิว: 1 · ticket lint: pass · Job A: ข้าม

## ต้นทุน
| สเตจ | เวลา (นาที) | tokens |
|---|---|---|
| Job A | — | — |
| implementer build | 41.7 | 360,613 (สะสม) |
| reviewer รอบ 1 | 12.3 | 165,175 |
| แก้ minor/nit (ไม่รีวิวซ้ำ) | 24.6 (10.1 + 14.5 หลัง resume) | 410,963 (สะสม) |
| **รวม** | **78.6** (wall clock 72.1 — reviewer กับช่วงรอ gate ซ้อนกันบางส่วน) | implementer 410,963 · reviewer 165,175 |

agent ตายกลางคัน: implementer หยุดรอ full gate ที่ตัวเองรันเป็น background (memory: *a subagent waiting on its own background task just stops*) — orchestrator เฝ้า process pytest จนจบ (22:06:46–22:11:48) แล้ว `SendMessage` ปลุกตัวเดิม ไม่ spawn ใหม่

## ผลรีวิว
- **verdict รอบ 1: APPROVED_WITH_FIXES** — 0 blocker, 0 major, 2 minor, 5 nit
  - **minor:** เทสต์ "จับ log ตอน save" สร้างบรรทัด log เอง ไม่ได้ยิง PUT จริง → เพิ่มเทสต์ที่ save จริงทั้ง 3 แท็บใต้ `caplog` + filter (probe ของ implementer: ใส่บรรทัด log รั่วในตัว endpoint → เทสต์ใหม่แดง เทสต์เก่าเขียว พิสูจน์ช่องว่างที่ reviewer ชี้)
  - **minor:** invariant ใน CLAUDE.md ยังบอกว่า filter ครอบ `password=`/`*_key=`/`token=` ทั้งที่ตั๋วนี้เองต้องเพิ่ม pattern `passphrase` → เพิ่ม `passphrase=` ในรายการ
  - **nit:** `api.ts` มี `fileUploadStatus()` ที่ไม่มีคนเรียก → ลบ · ตัวคั่น ` ·` หน้า digest 0025 ใน CLAUDE.md → เติม · spec ยังอ้าง "no new pattern" → เติมประโยคแก้ · gate 406 s ดูเหมือน serial → ยืนยันว่า `-n auto` (16 workers) ทั้งสองครั้ง ความต่างเป็น load ของเครื่อง · เทสต์ reserved-set สองตัวกลายเป็น vacuous หลังเซตว่าง → ใส่ docstring บอกว่า dormant + ข้อความ help ของ `--features` อ่านเซตสดแล้วแตกกิ่ง
- **probe ที่ reviewer ยิง: 3 — แดงครบ**
  - echo `password` กลับใน GET → `TestTheResponseNeverCarriesASecret` แดง
  - ขอบเขตพอร์ต `0..65536` → เทสต์ 422 แดง
  - พลิก nav entry กลับเป็น `never` → 5 เทสต์แดง (รวม gate sweep ของ nav contract)
- **ประเด็นที่ reviewer ตัดสินให้:** premise ของตั๋วเรื่อง redaction ผิด (`passphrase` ไม่ใช่ substring ของ `password`) การเพิ่ม pattern เป็นการแก้ที่ถูก ไม่ใช่ scope creep · PUT แยก 3 endpoint ต่อโปรโตคอลรับได้ · HTTPS ไม่มี username ถูกแล้ว (Bearer อย่างเดียวตาม ADR 0025) · การแคบ assertion `{"feature","always"}` ใน nav contract ไม่ใช่การอ่อนเกณฑ์ (ยัง exact-set + นับ 15 หน้า)
- **problems ที่ค้าง:** ไม่มี
- **ข้อสังเกตส่งต่อตั๋ว 02/03:** pattern ของ filter ต้องมี `=`/`:` ติดคำ — JSON body (`"password": "x"`) ไม่ถูก redact ถ้าวันหนึ่งมีการ log payload

## Gate
| รอบ | คำสั่ง full-suite | เวลา | จาก repo doc? | summary line |
|---|---|---|---|---|
| build | `pytest -n auto` (app/) | 406.63s | ใช่ | 2324 passed, 55 skipped |
| แก้ minor | `pytest -n auto -q` (app/) | 287.47s | ใช่ | 2325 passed, 55 skipped |

ruff format/check ผ่าน · `pnpm lint` + `pnpm build` ผ่าน · orchestrator รัน scoped ซ้ำก่อน commit: 116 passed (3 ไฟล์) · ตรวจไม่มีอักษรไทยใน `web/src` ยกเว้น `theme.ts` ที่มีมาก่อน

## ไฟล์ที่เปลี่ยน
- **โค้ดใหม่:** `app/src/arichds/fileupload/{__init__,config,status}.py`, `app/src/arichds/api/file_upload.py`
- **โค้ดที่แก้:** `constants.py` (RESERVED_FEATURE_KEYS ว่าง), `db/app_settings.py` (19 key), `logging_config.py` (pattern `passphrase`), `main.py`, `tools/arichds_vendor.py` (help text)
- **เทสต์ใหม่:** `app/tests/test_fileupload_config_api.py` (36)
- **เทสต์ที่แก้:** `test_nav_feature_contract.py`, `test_vendor_sign_features.py` (fixture `reserved_key`), `test_dataout_config_api.py` (docstring)
- **web:** `pages/FileUploadDestination.tsx` (เขียนใหม่ทั้งหน้า), `features.ts`, `components/AppShell.tsx` (label FTP), `App.tsx`, `api.ts`
- **เอกสาร:** `CLAUDE.md`, `SPEC.md`, `.scratch/file-upload/spec.md`

## Commit
`803684c` feat: an administrator configures the FTP page, and nothing is sent yet (file-upload #01)

## กับดักที่เสียเวลา (ถ้ามี)
- ตั๋วอ้างว่า filter ครอบ `passphrase` อยู่แล้ว — ผิด ผู้เขียนตั๋ว (orchestrator) เดาจากชื่อ pattern ไม่ได้ grep regex
- implementer peek header ของ gate ด้วย `| tee | head -20` → broken pipe ฆ่า pytest ที่ ~33% ต้องรันใหม่ (ห้าม pipe ผ่าน `head` บน gate run)
- implementer หยุดรอ background gate ของตัวเอง → orchestrator ต้องเฝ้า process แล้วปลุก (~5 นาทีที่เสียไป)
