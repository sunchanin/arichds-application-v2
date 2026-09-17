# Ledger — Issue (file-upload #05): ไฟล์ไปถึง FTPS server ผ่าน explicit TLS
รัน: 2026-09-17 21:44–22:54 · branch: feature/light-modules · ผลลัพธ์: APPROVED (รอบ 2) · รอบรีวิว: 2 · ticket lint: pass · Job A: ข้าม

## ต้นทุน
| สเตจ | เวลา (นาที) | tokens |
|---|---|---|
| Job A | — | — |
| implementer build | 31.7 | 344,878 (สะสม) |
| reviewer รอบ 1 | 9.7 | 161,251 |
| รอบ 2 — implementer / reviewer | 20.9 / 4.4 | 490,746 / 190,248 (สะสม) |
| **รวม** | **66.7** (wall clock 70.0) | implementer 490,746 · reviewer 190,248 |

agent ตายกลางคัน: ไม่มี

## ผลรีวิว
- **verdict รอบ 1: CHANGES_REQUESTED** — 0 blocker, 1 major, 4 minor, 1 nit
  - **major:** Test connection ใช้แค่ `cwd`+`SIZE` บน control channel ไม่เคยเปิด data channel — ปัญหา passive/NAT ที่ ADR 0025 ยกเป็นเหตุผลให้ตัด FTPS จึงจับไม่ได้ ("Connected" แล้ว STOR พังทุกครั้ง) → ใช้ `nlst` ผ่าน data channel ที่ PROT P + คืน `TYPE I` หลังจากนั้น (`nlst()` ส่ง `TYPE A` เอง — ไม่อยู่ใน digest, วัดเจอตอนแก้)
  - **minor:** `FILEUPLOAD_FTPS_READ_TIMEOUT_SEC` ไม่ถึง data connection (`ntransfercmd` อ่าน `self.timeout` ที่ `connect()` ตั้งไว้) → ตั้ง `ftps.timeout` ด้วย · `set_pasv(True)` ไม่มีเทสต์ pin (active mode ก็ผ่านบน loopback) → fake ตอบ 502 ต่อ `PORT`/`EPRT` · ทุก `error_perm` = `bad_credentials` — server ที่ปฏิเสธ `PROT P` (534) ถูกบอกว่ารหัสผิด → แยกตาม reply code 530/532 · `passive_ports` ใน fake ตั้งจาก premise ผิด (pyftpdlib โฆษณา address ของ control socket อยู่แล้ว) → ลบ + แก้ lib-note §3 พร้อม citation `dispatchers.py:45`
  - **nit:** branch `TimeoutError` ไม่มีเทสต์ → `_StallingServer` (ร่างแรก GC socket ที่ accept ทิ้งจึงได้ EOFError — บันทึกเป็น Gotcha)
- **verdict รอบ 2: APPROVED** — ไม่มี problem
- **probe ที่ reviewer ยิง**
  - รอบ 1: 3 — ตัด `auth()` ก่อน `login()` → แดง · `set_pasv(False)` → **เขียว** · ตัด branch `TimeoutError` → **เขียว** (สองตัวหลังนำไปสู่ minor 3 / nit 6)
  - รอบ 2: 3 — `set_pasv(False)` → แดง 8 · ตัด `TimeoutError` → แดง · ตัดการคืน `TYPE I` หลัง `nlst` → แดง
- **ประเด็นที่ reviewer ตัดสินให้:** `_mkdir_p` แบบ mkd-แล้วกลืน-550 รับได้ (ftplib ไม่มี stat ที่ถูกกว่า) · SPEC.md ไม่ต้องเขียน narrative ไทยเต็มของ 04/05 — SPEC เป็น baseline ของ scope, CLAUDE.md เป็น digest ของสิ่งที่ลง · root ว่างที่ตอบ 5xx ต่อ NLST จะได้ประโยค "does not exist yet" เกิน — ไม่ออก finding เพราะไม่มี server ไหนวัดได้ว่าทำแบบนั้น
- **problems ที่ค้าง:** ไม่มี

## Gate
| รอบ | คำสั่ง full-suite | เวลา | จาก repo doc? | summary line |
|---|---|---|---|---|
| build | `pytest -n auto` (app/) | 218.73s | ใช่ | 2456 passed, 55 skipped |
| รอบ 2 | `pytest -n auto` (app/) | 192.52s | ใช่ | 2464 passed, 55 skipped |

ruff format/check ผ่าน · `pnpm lint` + `pnpm build` ผ่าน · orchestrator รัน scoped ซ้ำก่อน commit: 47 passed · `pyftpdlib[ssl]` อยู่ใน dev เท่านั้น (runtime `dependencies` ไม่มี) · ไม่ต้อง build PyInstaller (ฝั่ง product เป็น `ftplib` + `ssl`) · ติดตั้ง pyftpdlib 2.2.0 / pyOpenSSL 26.4.0 / pyasyncore+pyasynchat 1.0.5 (มากับ conditional deps ของ pyftpdlib บน 3.14)

## ไฟล์ที่เปลี่ยน
- **โค้ดใหม่:** `app/src/arichds/fileupload/ftps_transport.py` (`FtpsTransport`, `check_ftps_connection`, `_reply_code`, `ssl_context` keyword seam ที่ product ไม่เคยส่ง)
- **โค้ดที่แก้:** `fileupload/cycle.py` (`_build_transport` ครบสามโปรโตคอล), `api/file_upload.py` (`POST /ftps/test`), `constants.py` (3 timeout), `fileupload/__init__.py`/`transport.py` (docstring), `app/pyproject.toml` (dev: `pyftpdlib[ssl]>=2.2`)
- **เทสต์:** `fake_ftps_server.py` (TLS_FTPHandler, `tls_data_required`, ปฏิเสธ active mode), `test_fileupload_ftps_transport.py` (ใหม่ 28), `test_fileupload_config_api.py`
- **web:** `api.ts`, `pages/FileUploadDestination.tsx` (Test connection บนแท็บ FTPS + certificate subject)
- **เอกสาร:** `CLAUDE.md`, `SPEC.md`, `docs/lib-notes/pyftpdlib-tls.md` (§3 แก้ + 3 Gotchas ใหม่), `installer/README.md`
- รวม ledger ของตั๋ว 04 ไว้ใน commit เดียวกัน

## Commit
`f011a8e` feat: files reach an FTPS server over explicit TLS (file-upload #05)

## กับดักที่เสียเวลา (ถ้ามี)
- "lists the remote root" ถูกทำให้ผ่านด้วยคำสั่งบน control channel — เกณฑ์ที่เขียนเป็นกริยา (list) ต้องไปดูว่ากลไกที่เกณฑ์มีไว้ป้องกัน (data channel ผ่าน NAT) ถูกเดินจริงไหม
- เทสต์บน loopback ทำให้ active/passive และ timeout แยกกันไม่ออก — fake ต้อง**ปฏิเสธ**ทางที่ห้าม ไม่ใช่แค่รองรับทางที่ถูก
