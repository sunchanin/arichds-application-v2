# Audit log — Issue #38: Billing capture image — screenshot the real page, and take the service off LocalSystem (ADR 0017)
รัน: 2026-08-22 · branch: `feature/light-modules` · ผลลัพธ์: **APPROVED** · รอบรีวิว: **2**
เกิดจากของหลุด: **ใช่ — issue #35 (ADR 0014)** ปล่อย Pillow renderer ผ่านไปทั้งที่ premise ของ ADR 0014
(*"ไม่มีหน้าจอให้ถ่ายตอนไม่มีคนดู"*) ผิดทั้ง 4 ข้อ และตารางเทียบราคาของมันไม่มีแถวที่ชนะเลย
(คิดราคาไว้ที่การ **bundle** Chromium ~250 MB แต่การขับ Edge ที่ Windows ลงมาให้แล้วราคา 0 MB)
prototype วันที่ 2026-08-22 ล้มมันลง → ADR 0017 → issue นี้

## ทำอะไรไปบ้าง (ทีละขั้น)

### 1. reviewer (Job A) — สร้าง prompt (`/draft-delegation-prompt`)
- **Track: `full`** — สองซีกที่ผูกกัน (installer + subsystem ใหม่), มี branch, มี failure mode ใหม่, ~15 ไฟล์ข้าม `app/` `web/` `installer/` และเอกสาร
- **TDD required: `yes`** — row-selection authority, verification gate, failure/cleanup path และ selector contract ล้วนเป็น logic ที่มี branch
- **Workflow discipline:** สั่ง `/fastapi` (ก่อนแตะ `api/billing.py`) และ `/antd-ui` (ก่อนแตะ `Billing.tsx`, `App.tsx`) — section นี้มีครบ ไม่ใช่ Job A defect
- ค้นเอกสารจริงมาใส่ prompt (ไม่ได้ spawn `docs-researcher` แยก — ทำเองใน context ตัวเอง):
  - **Inno Setup 6**: SID identifier `service` = "Local service account" ⇒ `Permissions: service-modify` ใช้ได้ ไม่ต้อง `icacls` · แต่ **Inno ไม่ documented เรื่อง inheritance เลย** ⇒ สั่งให้ส่งต่อเป็น check ของเจ้าของ ห้ามเขียน README ยืนยัน
  - **NSSM**: `ObjectName` **ต้องส่ง password เสมอ** แม้ LocalService ⇒ ใช้รูปแบบ blank `""` ตามเอกสาร
  - **`websockets` 17.0.1**: `max_size` default 1 MiB (เล็กเกินสำหรับ screenshot) และ `proxy=True` default (เครื่องที่ตั้ง `HTTP_PROXY` จะ route loopback ผ่าน proxy) ⇒ ต้องตั้งเองทั้งคู่
  - **`@rc-component/table` 1.10.4**: `BodyRow.js:125` ใส่ `data-row-key` ทุกแถว, measure row ไม่มี ⇒ `tr[data-row-key]` กรองให้เอง
- **จุดที่ Job A แก้ทิศทางโจทย์เดิม (และถูก):** issue เขียนว่าให้ assert *row count + `bill_date` แถวแรก* · Job A เปลี่ยนเป็น **เทียบ list ของ row id ตามลำดับ** (แข็งแรงกว่า ไม่ขึ้นกับ timezone/format) และเปลี่ยนจาก *คลิก UI* เป็น **seed `window.__ARICHDS_CAPTURE__` ก่อน SPA boot** เพราะ **สิบรอบบิลเป๊ะๆ กดจาก UI ไม่ได้** (`PAGE_SIZE_OPTIONS` ไม่มีเลข 10) — ผลพลอยได้คือบั๊กที่ prototype เสียเวลาที่สุด 2 ตัวหายไปเพราะไม่ต้องคลิกอะไรเลย

### 2. implementer — ลงมือ + ตรวจตัวเอง (`/tdd` + self-check สองด่าน)
- **ไฟล์ที่เปลี่ยน (29):** ใหม่ 8 — `capture/dom.py`, `capture/screenshot.py`, `web/src/capture.ts`, และเทส 5 ไฟล์ · ลบ 2 — `capture/png.py`, `test_capture_png.py` · แก้ 21 — `capture/service.py`, `api/billing.py`, `config.py`, `_render_shared.py`, `pyproject.toml`, `App.tsx`, `Billing.tsx`, `api.ts`, `installer/arichds.iss`, `installer/README.md`, `CLAUDE.md`, `CONTEXT.md`, `SPEC.md`, ADR 0014, `pillow-imagedraw.md` + เทสเดิม 4 ไฟล์
- **self-check เจออะไรเหนือ nit และแก้อย่างไร:**
  - **major (แก้แล้ว):** `Page.addScriptToEvaluateOnNewDocument` **ไม่ทำงานเลยถ้าไม่เรียก `Page.enable` ก่อน — และเงียบสนิท ไม่ error** · เจอจากการรัน integration test กับ Edge จริง (`mounted: False`, `localStorage` ว่าง) ไม่ใช่จากการอ่านโค้ด · ถ้าไม่มี test นี้จะผ่าน unit test ทุกตัวแล้วไป timeout 90 วินาทีบนเครื่องลูกค้าทุกครั้ง
  - **minor (แก้แล้ว):** `mint_token` / `profile_dir.mkdir` อยู่นอก `try/finally` ⇒ ถ้าพังระหว่างสองอย่างนี้ token row จะรั่ว
- **ผลรันเทสต์ (รอบแรก):** `1513 passed, 17 skipped, 18 warnings in 59.68s` — ตัวเลขจริง ไม่ใช่ `(cached)`
- **integration test กับ Edge จริง:** `1920x1080 px, 39068 bytes` · ไม่มี `msedge.exe` ค้าง

### 3. reviewer (Job B) — รีวิว (`/scrutinize`, full track)
- **verdict: CHANGES_REQUESTED** — 1 blocker, 1 major, 3 minor, 3 nit
- **blocker:** `screenshot.py:416` seed `pageSize = max(len(rows), 10) + 40` = **50** แต่ `_png_source_rows()` จำกัด 10 ⇒ หน้าเว็บ render ทุกรอบบิล ส่วน `expected_ids` มี 10 ⇒ `ids_match` เป็นจริงไม่ได้เลย ⇒ ไหม้ budget 90 วิ แล้วโยน `BrowserCaptureError` ⇒ **ไม่มี capture ออกมาเลยสำหรับ device ที่มีรอบบิลเกิน 10**
  - พิสูจน์ด้วยการรัน ไม่ใช่อนุมาน — seed 12 รอบบิลแล้วรัน query จริงของหน้าเว็บด้วยพารามิเตอร์ที่ seed จริง: `_png_source_rows` ได้ 10 แถว, หน้าเว็บได้ 12 แถว, `ids_match() = False`
  - **mutation probe P1: แก้เป็นค่าที่ถูกต้องแล้วเทสยังเขียว 77 ตัว** ⇒ ไม่มีเทสตัวไหนคุมเลขนี้เลย
- **major:** budget 90 วิเป็นแค่คำแนะนำ — `_WebSocketCdpTransport.request` วน `recv()` ไม่มี deadline และเพราะเปิด `Page.enable` Edge ส่ง event มาเรื่อยๆ ⇒ renderer ที่ค้างใน JS เลี้ยงลูปนี้ไว้ตลอดกาล ⇒ **Scheduler thread (ADR 0008 มีเธรดเดียว) ตายถาวร** ⇒ ขัด criterion ของ issue ตรงๆ · reviewer ชี้กับดักล่วงหน้าด้วยว่าใส่ `wait_for` แล้ว `finally` จะรันใน cancelled context ทำให้ `await connection.close()` โยน `CancelledError` แล้วข้าม kill/ลบ profile/ลบ token ทั้งหมด
- **minor ×3:** geometry ของ screenshot ไม่มีเทสที่ fail ได้ (probe P2/P3/P4 เขียวหมด รวมกรณีที่ภาพได้แค่แถวที่พอดี 1080px), docstring ของ `service.py` และ `_render_shared.py` อธิบายสิ่งที่ไม่จริงแล้ว
- **ควรถูกจับที่ด่านไหน:**
  - **blocker (pageSize)** → **โจทย์ Job A เอง** · reviewer ยอมรับเอง: *"My delegation prompt specified a `pageSize` field and never said what value `app/` must put in it, and my mandated-probe list named four targets, none of which touched it."* prompt ที่ตั้ง criterion ว่า "สิบเป๊ะ" แต่ไม่ระบุตัวเลขที่ทำให้เกิดสิบ = under-specified · **ด่านรองที่ควรจับได้คือ integration test** ซึ่ง seed แค่ 1 รอบบิล ⇒ fixture เล็กกว่ากฎที่มันกำลังพิสูจน์
  - **major (budget)** → **self-check 4a ของ implementer** (error-path audit) ควรจับได้ เพราะเป็น path ที่ docstring ตัวเองสัญญาไว้ตรงข้าม
  - **minor (geometry)** → **ไม่มี — Job B เท่านั้นที่จับได้** ต้องรัน mutation probe ถึงจะเห็นว่า assertion ไม่ discriminate
  - **minor (docstring ×2)** → self-check ของ implementer (มันแก้ docstring เดียวกันนั้นในรอบเดียวกันแล้วปล่อยย่อหน้าข้างบนไว้)

### 4. รอบแก้ (รอบ 1)
orchestrator ส่ง problems verbatim ตรงให้ implementer (ไม่ผ่าน Job A ซ้ำ) → implementer แก้ → Job B รีวิวซ้ำ

- **blocker:** `pageSize = len(rows)` + เทส pin ค่า · **เขียน integration test ใหม่ให้ seed 13 รอบบิล** (เดิม 1) ⇒ ได้หลักฐานบวกจาก Edge จริง `1920x1080 px, 49793 bytes, 10 rows`
- **major:** `_run_capture_with_hard_deadline` ครอบด้วย `asyncio.wait_for` + `asyncio.shield` ใน cleanup
  - **จุดที่ implementer ทำถูกและควรบันทึก:** เทสตัวแรกที่มันเขียน**ผ่านทั้งที่ยังไม่ได้แก้** เพราะ fake `_record_close()` ไม่เคย suspend จริง จึงไม่มีทางเจอ `CancelledError` · มันจับได้แล้ว**ทิ้งเทสนั้น** เขียนใหม่ให้ suspend จริง แทนที่จะเก็บสีเขียวไว้
- **minor ×3:** เพิ่ม `TestDriveCaptureScreenshotGeometry` (4 เทส) · แก้ docstring `_render_shared.py`
- **ข้อ 4 — implementer ปฏิเสธคำสั่ง reviewer พร้อมหลักฐาน:** reviewer สั่งให้เขียนว่า fallback *"now raises"* · implementer พิสูจน์ว่าพอแก้ blocker แล้ว `pageSize = len(rows)` ⇒ กรณี fallback (`rows = [row]`) ได้ `pageSize = 1` ⇒ **fallback ยังทำงานได้จริง ไม่ raise** · แจ้งขอแย้งแทนที่จะทำเงียบๆ
- **nit:** รับ `--hide-scrollbars` · **ปฏิเสธ `--no-sandbox`** เพราะเป็นการลดความปลอดภัยโดยไม่มีหลักฐานว่าจำเป็น
- **ผลรัน:** `1525 passed, 17 skipped in 113.34s` · ruff ผ่าน · `pnpm lint && pnpm build` ผ่าน
  - *(113 วิ vs 60 วิ รอบแรก — implementer ตรวจแล้วว่าเป็นเพราะโปรแกรมอื่นกิน CPU ไม่ใช่ regression · ไฟล์เทสใหม่รันเดี่ยวๆ 15 วิ)*

### 5. reviewer (Job B รอบ 2) — **APPROVED**
- ตรวจซ้ำเองไม่เชื่อรายงาน — seed 13 รอบบิลเอง ยืนยัน `ids_match=True`
- **reviewer ถอนข้อ 4 ของตัวเอง:** *"you were right, I was wrong"* — พิสูจน์เองด้วย probe แยก (`limit=1` ผูกกับ `bill_date + 1s` คืนแถวเดียวจริง แม้มีรอบบิลเก่ากว่าอยู่) และบอกว่า docstring ที่ implementer เขียน **ดีกว่าที่ตัวเองสั่ง** เพราะระบุว่า `pageSize == len(rows)` คือสิ่งที่ทำให้มันจริง ⇒ กลายเป็น tripwire แทนคำกล่าวอ้าง
- **รับเหตุผล `--no-sandbox`:** ชี้ว่า sandbox บน Windows ทำงานด้วย **restricted token** + alternate desktop + job object ซึ่ง LocalService ทำได้ทั้งหมด ไม่ต้อง elevate · `--no-sandbox` เป็น idiom ของ Linux-root/container · และ browser ตัวนี้ถือ **admin JWT ที่ยังไม่หมดอายุใน `localStorage`** ซึ่งคือสิ่งที่ sandbox กำลังปกป้องอยู่
- **nit ที่เหลือให้มนุษย์:** (1) `_launch_edge` docstring ชี้ไป `installer/README.md` แต่ตาราง Troubleshooting ไม่มีแถวสำหรับ *"เจอ Edge แต่ไม่เขียน `DevToolsActivePort`"* ซึ่งคือ signature ของความเสี่ยงที่การปฏิเสธ `--no-sandbox` เดิมพันอยู่ (2) `TestHardTimeoutCeiling` pin backstop ไม่ได้ pin ตัวหลัก — probe Q2 เขียว (3) `asyncio.shield` ไม่มีเทสคุม — probe Q4 เขียว (ตัว `except CancelledError` ต่างหากที่ทำให้เทสผ่าน)
- **Q1 ไม่นับเป็นผล:** ถอด `wait_for` แล้วเทสไม่จบใน 75 วิ · reviewer รายงานตรงๆ ว่า *"a hang is not a red"* แทนที่จะนับเป็นแดง

## ต้นทุน (เวลา + tokens ต่อสเตจ)

| สเตจ | เวลา | tokens |
|---|---|---|
| reviewer Job A | 16.2 นาที | 160,891 |
| implementer (build) | 48.9 นาที | 510,697 |
| reviewer Job B (รอบ 1) | 9.8 นาที | 245,990 |
| รอบแก้ 1 — implementer | 28.0 นาที | 606,002 |
| รอบแก้ 1 — reviewer Job B | 12.3 นาที | 278,799 |
| **รวม** | **~115 นาที** | — |

> ⚠️ **ตัวเลข token บวกกันไม่ได้** — `subagent_tokens` ที่ harness คืนมาหลัง `SendMessage` resume เป็นค่า**สะสม** ไม่ใช่ค่าของรอบนั้น (606,002 ของรอบแก้รวม 510,697 ของรอบ build ไว้แล้ว)
> ตัวเลขที่บวกได้ต้อง `grep '"output_tokens"'` จาก transcript เอง · เวลาเป็นค่าต่อรอบจริง บวกได้
>
> **รอบแก้มีราคาจริง ๆ:** 40.3 นาที = **35% ของ wall-clock ทั้งหมด** — เป็นครั้งแรกที่ pipeline นี้วัดค่ารอบแก้ได้ (9 runs ก่อนหน้าไม่เคยวัด)

## ✅ skill ที่เรียกจริง — ยืนยันจาก transcript (tamper-proof)

```
=== reviewer aa1c5e2288c7da482 (1,241,153 bytes) ===
      1 "skill":"draft-delegation-prompt"
      1 "skill":"scrutinize"
Skill calls total: 2

=== implementer a0b88361cbd3f0561 (3,906,335 bytes) ===
      1 "skill":"antd-ui"
      1 "skill":"fastapi"
      1 "skill":"tdd"
Skill calls total: 3
```

- **ครบทุก mandate** — implementer เรียก `tdd`/`fastapi`/`antd-ui` ครบตามที่ Job A สั่ง (ตรวจตอน READY_FOR_REVIEW ครั้งแรก ไม่ได้รอถึงตอนนี้)
- **ไม่มีรีวิวซ้ำซ้อน** — implementer ไม่ได้เรียก `scrutinize`/`code-review` เอง · reviewer เรียก `scrutinize` ครั้งเดียว
- **ไม่มี `docs-researcher` ถูก spawn** ทั้งสองฝั่ง — Job A ค้นเอกสารในบริบทตัวเองแล้วเขียนลง Findings ⇒ implementer ไม่ต้องค้นซ้ำ (นี่คือพฤติกรรมที่ต้องการ)

### ⚠️ กับดัก path ของ transcript
`output_file` ที่ tool คืนมาตอน spawn (`…\tasks\<id>.output`) **เป็น 0 ไบต์ตลอดกาล** — grep แล้วได้ `Skill calls: 0` ซึ่งหน้าตาเหมือน "agent ข้าม skill ที่บังคับ" เป๊ะ
ไฟล์จริงอยู่ที่ `~/.claude/projects/<slug>/<session>/subagents/agent-<id>.jsonl` และอ่านได้ทันที ไม่ต้องรอ flush

## Commit
ยังไม่ commit — รอมนุษย์ตัดสินใจ · working tree มี 21 modified · 2 deleted · 8 untracked
(`git diff --stat`: 468 insertions, 526 deletions ในไฟล์ที่ track อยู่)

**เจ้าของยังติดหนี้ install round หนึ่งรอบ** ซึ่ง agent ทำแทนไม่ได้:
1. `powershell -File app/packaging/build.ps1` แล้ว `iscc installer\arichds.iss`
2. รัน `installer\Output\arichds-setup-0.2.0.exe` ทับ install จริง (หรือ VM สะอาด)
3. `sc qc arichds` → คาดว่า `NT AUTHORITY\LocalService`
4. `icacls C:\ProgramData\ARICHDS` → คาดว่ามี ACE ของ `NT AUTHORITY\LOCAL SERVICE` พร้อม `(OI)(CI)(M)` — **นี่คือข้อเดียวที่ Inno ไม่ documented จึงเป็นข้อเดียวที่พังเงียบได้**
5. หน้า Activation ยังแสดง Machine ID (พิสูจน์ว่า `reg query MachineGuid` อ่านได้ภายใต้ LocalService)
6. มีไฟล์ `.png` โผล่ใน `capture_dir` ครบทั้ง 3 มิเตอร์ที่ต่อถึง แล้วดูด้วยตาเทียบกับหน้า Billing จริง

**หมายเหตุสำหรับข้อ 6:** `CaptureSettingsCard` ถูกซ่อนตอน capture mode (decision 8 ของ Job A) ⇒ **รูปที่ได้จะต่างจาก prototype ที่เจ้าของอนุมัติไปแล้ว** (ไม่มีการ์ด "Capture folder" ด้านบน) — ตั้งใจ ไม่ใช่บั๊ก

## วิธีตรวจซ้ำด้วยตัวเอง (audit)

```bash
d="C:/Users/HP/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents"
grep -o '"skill":"[a-zA-Z0-9:_-]*"' "$d/agent-aa1c5e2288c7da482.jsonl" | sort | uniq -c   # reviewer
grep -o '"skill":"[a-zA-Z0-9:_-]*"' "$d/agent-a0b88361cbd3f0561.jsonl" | sort | uniq -c   # implementer
grep -c '"name":"Skill"' "$d/agent-a0b88361cbd3f0561.jsonl"                                # จำนวน Skill call ทั้งหมด
```

**อย่าใช้ glob สำเร็จรูป** และ**อย่าใช้ `output_file` ที่ tool คืนมา** — ทั้งสองอย่างให้ผลเป็นศูนย์ทั้งที่ skill ถูกเรียกจริง
