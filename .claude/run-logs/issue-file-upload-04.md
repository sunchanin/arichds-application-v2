# Ledger — Issue (file-upload #04): ไฟล์ไปถึง SFTP server โดย pin host key
รัน: 2026-09-17 20:29–21:43 · branch: feature/light-modules · ผลลัพธ์: APPROVED (รอบ 2) · รอบรีวิว: 2 · ticket lint: pass · Job A: ข้าม

## ต้นทุน
| สเตจ | เวลา (นาที) | tokens |
|---|---|---|
| Job A | — | — |
| implementer build (รวม PyInstaller build 2 รอบ) | 41.2 | 402,455 (สะสม) |
| reviewer รอบ 1 | 9.4 | 156,084 |
| รอบ 2 — implementer / reviewer | 17.2 / 4.4 | 496,227 / 183,740 (สะสม) |
| **รวม** | **72.2** (wall clock 74.0) | implementer 496,227 · reviewer 183,740 |

agent ตายกลางคัน: ไม่มี

## ผลรีวิว
- **verdict รอบ 1: CHANGES_REQUESTED** — 1 blocker, 0 major, 2 minor, 3 nit
  - **blocker:** key file ที่มี passphrase ใช้ไม่ได้เลย — `PKey.from_path(password=str)` ของ paramiko 5.0.0 ต้องการ `bytes` ทั้งที่ annotation เขียน `str | None` → `TypeError: password must be bytes` ทุกครั้ง; ไม่มีเทสต์ไหนใช้ passphrase จึงเขียวทั้งชุด; reviewer reproduce เองกับ fake server (Ed25519 เข้ารหัส) · แก้: `.encode("utf-8")` + classify `ValueError`/`TypeError` ตอนโหลด key เป็น `bad_credentials` + เทสต์ `TestEncryptedKeyPassphrase` 5 ตัว (ถูก/ผิด/ไม่ใส่ passphrase + caplog)
  - **minor:** `docs/lib-notes/paramiko-sftp.md` ที่ implementer เพิ่งแก้เป็น "verified" อ้างว่า passphrase ผิดจะได้ `PasswordRequiredException` — ผิดสำหรับ `from_path` (อันนั้นเป็นของ `from_private_key_file`) → แก้ §2 ด้วยค่าที่วัดจริง 4 แถว · CLAUDE.md สองประโยคยังบอกว่า SFTP คืน `None` → แคบเหลือ FTPS
  - **nit:** help text ไม่บอกว่า key file ชนะเมื่อใส่ทั้งคู่ · signature 8 positional scalar สองจุด → keyword-only · Test connection กลืน remote root ที่ไม่มีอยู่เงียบๆ → คง `ok` แต่เติมประโยค
- **verdict รอบ 2: APPROVED** — ไม่มี problem
- **probe ที่ reviewer ยิง**
  - รอบ 1: 3 — `_build_transport` sftp ปิด → แดง · `write_manifest` เขียน `{}` → แดง · fingerprint จาก `get_base64()` แทน `.fingerprint` → แดง 2 (สองตัวแรกอยู่ในรายการที่ implementer ไม่ได้ probe)
  - รอบ 2: 3 — คืน `password=str` → เทสต์ passphrase ถูกต้องแดง · ปิด branch classify → แดง 2 · `if True` ที่ remote-root clause → แดง
- **ประเด็นที่ reviewer ตัดสินให้:** key file ชนะ password เมื่อใส่ทั้งคู่ (SSH convention) รับได้ · reconnect ต่อ `put_file` รับได้ในตั๋วนี้ (HTTPS ก็ทำแบบเดียวกัน; ถ้าเปลืองงบค่อย cache ใน transport โดยไม่แตะ seam) · remote root ที่ยังไม่มี = `ok` ตาม ADR 0025 decision 4 · `(ValueError, TypeError)` arm ครอบกว้างกว่า loader แต่แค่ shape ข้อความ ไม่ใช่ control flow — บันทึกไว้ไม่ออก finding
- **problems ที่ค้าง:** ไม่มี

## Gate
| รอบ | คำสั่ง full-suite | เวลา | จาก repo doc? | summary line |
|---|---|---|---|---|
| build | `pytest -n auto` (app/) | 260.12s | ใช่ | 2426 passed, 55 skipped |
| รอบ 2 | `pytest -n auto` (app/) | 286.72s | ใช่ | 2432 passed, 55 skipped |

ruff format/check ผ่าน · `pnpm lint` + `pnpm build` ผ่าน · orchestrator รัน scoped ซ้ำก่อน commit: 51 passed · **PyInstaller onedir**: ก่อน 75,894,788 → หลัง 77,018,224 bytes (+1,123,436 ≈ 1.07 MiB) · `_internal/nacl/_sodium.pyd` 405,504 bytes อยู่ใน onedir ผ่าน `hook-nacl.py` ของ hooks-contrib ไม่ต้องแก้ build.ps1 · paramiko 5.0.0 / PyNaCl 1.6.2

## ไฟล์ที่เปลี่ยน
- **โค้ดใหม่:** `app/src/arichds/fileupload/sftp_transport.py` (`SftpTransport`, `check_sftp_connection`, `HostKeyMismatchError`/`HostKeyNotPinnedError`, classifier เดียว)
- **โค้ดที่แก้:** `fileupload/cycle.py` (`_build_transport` คืน SFTP จริง), `api/file_upload.py` (`POST /sftp/test`, `POST /sftp/host-key`), `constants.py` (3 timeout), `app/pyproject.toml` (`paramiko>=5.0`, `pynacl>=1.5`)
- **เทสต์:** `fake_sftp_server.py` (paramiko server in-process, ephemeral port, host key ของตัวเอง), `test_fileupload_sftp_transport.py` (ใหม่ 31), `test_fileupload_config_api.py`
- **web:** `api.ts`, `pages/FileUploadDestination.tsx` (Test connection + fingerprint + "Pin this key")
- **เอกสาร:** `CLAUDE.md`, `docs/lib-notes/paramiko-sftp.md` (แก้ §2 ให้ตรงของจริง), `installer/README.md`

## Commit
`9a29b9b` feat: files reach an SFTP server, with the host key pinned (file-upload #04)

## กับดักที่เสียเวลา (ถ้ามี)
- annotation ของ library โกหก (`password: str | None` แต่ต้องการ bytes) และ "ไม่มีเทสต์ที่ใช้ passphrase" ทำให้ทั้งชุดเขียว — เทสต์ที่ใช้ key **ไม่เข้ารหัส** ไม่เคยแตะ `password=` เลย
- lib-notes ที่ implementer ปรับเป็น "verified" หลังติดตั้ง แต่ verify แค่ signature ไม่ได้ verify พฤติกรรม exception — reviewer จับได้เพราะลองยิงของจริง
