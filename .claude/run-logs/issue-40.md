# Audit log — Issue #40: Launch Edge through a LOCAL SERVICE scheduled task; put the service back on LocalSystem
รัน: 2026-08-24 · branch: `feature/light-modules` · ผลลัพธ์: **APPROVED** · รอบรีวิว: **2**
เกิดจากของหลุด: **ใช่ — issue #38 เอง** · #38 อ่าน consequence ของ ADR 0017 กว้างเกินไป
(*"Edge รันใต้ SYSTEM ไม่ได้"* → *"service รันใต้ SYSTEM ไม่ได้"*) แล้วย้ายทั้ง service ไป
`NT AUTHORITY\LocalService` ⇒ เขียน `capture_dir` ใต้ `C:\Users\…` ไม่ได้ ⇒ ติดตั้งจริงแล้วได้ 422

## ทำอะไรไปบ้าง (ทีละขั้น)

### 1. reviewer (Job A) — สร้าง prompt (`/draft-delegation-prompt`)
- **Track: `full`** · **TDD required: `yes`**
- **Workflow discipline: ระบุชัดว่าไม่มี domain skill ที่ใช้** — ไม่แตะ route ของ FastAPI, ไม่แตะ `web/`, ไม่แตะ Gurux ⇒ ไม่ใช่ Job A defect ที่ไม่ได้สั่งสกิลไหน
- **งานค้นเอกสารที่เปลี่ยนวิธีทำ 3 ข้อ** (ค้นเองใน context ไม่ได้ spawn `docs-researcher`):
  - **`DisallowStartIfOnBatteries` default = True และบล็อกการสั่งรันแบบ on-demand** · `TASK_RUN_IGNORE_CONSTRAINTS` ต้องส่งผ่าน `RunEx` ซึ่ง `schtasks /run` ไม่มี switch ให้ ⇒ task ที่สร้างด้วย `schtasks /create /TR` **ไม่ยอมทำงานบนเครื่องที่ใช้แบต** และแก้ทีหลังไม่ได้ ⇒ เปลี่ยนไปใช้ `Register-ScheduledTask` ผ่าน `.ps1` ที่ commit ไว้
  - **`ExecutionTimeLimit` ถูก bypass สำหรับ on-demand start** (เอกสารเขียนตรงๆ) ⇒ ถ้าใส่ "เผื่อไว้" จะเป็นความปลอดภัยปลอม
  - **`Browser.close` ส่งบน connection เดิมไม่ได้** — โค้ดต่อกับ *page* target แต่ `Browser` เป็น browser-scoped domain ⇒ ได้ `-32601` · ต้องเปิด connection ที่สองจาก `/json/version`
- **แย้งตัว issue เองหนึ่งข้อ (D3)** — issue เขียนว่า *"ลบบรรทัด `ObjectName` ทิ้ง แล้วจะกลับไปเป็น LocalSystem ตาม default"* · จริงเฉพาะ **fresh install** · ตอน upgrade `nssm install` เป็น no-op และ `ObjectName` เดิมค้าง ⇒ เครื่องที่เคยลง 0.2.0 จะค้างที่ LocalService **เงียบ ๆ** และเกณฑ์หลักของ issue จะไม่เป็นจริงโดยไม่มีใครรู้

### 2. implementer — ลงมือ + ตรวจตัวเอง (`/tdd` + self-check สองด่าน)
- **ไฟล์ที่เปลี่ยน (10):** ใหม่ 3 — `capture/task.py`, `installer/register-capture-task.ps1`,
  `tests/test_capture_task_contract.py` · แก้ 7 — `capture/screenshot.py`, `config.py`,
  `tests/test_capture_screenshot_units.py`, `installer/arichds.iss`, `installer/README.md`,
  `CLAUDE.md`, `CONTEXT.md`
- **แย้งกลับ Job A หนึ่งข้อพร้อมหลักฐาน** — ใช้ `nssm reset <service> ObjectName` แทน
  `nssm set` ที่ D3 ระบุ โดย spawn `docs-researcher` ไปยืนยันตามที่ prompt สั่งให้ยืนยันแทนการเดา
- **TDD: เปิดเผยเองว่าทำไม่ครบ** — *"partial — honest breakdown below, not 'yes' across the board"* ·
  step 3/7 เขียนเทสพร้อมโค้ด ไม่ใช่ test-first · ชดเชยด้วย **mutation proof 7 ตัว**
  (backup → mutate → รัน → ยืนยันแดง → คืนค่า → `diff`) **และระบุรายการเทสที่ไม่ได้พิสูจน์ไว้ด้วย**
- **ผลรันรอบแรก:** `1547 passed, 17 skipped` (baseline `1525`) · ruff ผ่าน · `iscc` คอมไพล์ `0.3.0` สำเร็จ

### 3. reviewer (Job B) — รีวิว (`/scrutinize`, full track)
- **verdict: CHANGES_REQUESTED** — 2 blocking (ทั้งคู่ `minor`) + 8 nit
- **ตัดสิน 3 ข้อที่ orchestrator สั่งให้ดู:**
  - **TDD gap — ผ่าน** · mutation proof 7 ตัว map ตรงกับ 8 พฤติกรรมที่ prompt สั่ง 1:1 ·
    *"A mutation proof is stronger evidence than a red-first, which usually only shows a missing
    symbol — I did not want the ceremony, I wanted proof the assertions discriminate"* ·
    และ probe เพิ่มเอง 2 ตัว โดยตัวหนึ่ง **ย้าย** `port_file.unlink` ไปหลัง `/run` แทนที่จะลบ
    ⇒ พิสูจน์ว่าเทสคุม **ลำดับ** จริง ไม่ใช่แค่คุมว่ามีบรรทัดอยู่
  - **`nssm reset ObjectName` — ถูก และดีกว่าที่ตัวเองสั่ง** · ยืนยันจาก source ของ NSSM
    (`settings.cpp` ประกาศ default = `NSSM_LOCALSYSTEM_ACCOUNT`, `account.h` นิยาม = `LocalSystem`,
    และ `ObjectName` เป็น **native SCM parameter** ⇒ `reset` เรียก `ChangeServiceConfig`
    ไม่ใช่ลบ registry — ซึ่งเป็น failure mode ที่ควรตัดออกพอดี)
  - **`iscc` — จริง** 36,971,580 bytes และอธิบายว่าทำไมไม่โผล่ใน `git status` (`.gitignore:43`)
- **blocking ทั้งสองข้อคือ "โค้ดถูก แต่ไม่มีเทสคุ้มครอง"** — พิสูจน์ด้วยการ mutate แล้วเทสยังเขียว:

  | mutate | ผลก่อนแก้ |
  |---|---|
  | ทำลาย `reset {#ServiceName} ObjectName` ใน `.iss` | 11 passed |
  | task principal `LOCALSERVICE` → `SYSTEM` | 11 passed |
  | ถอด `-AllowStartIfOnBatteries` | 11 passed |
  | ถอด `Browser.close` ออกจาก `_Cleanup` ทั้งก้อน | 42 passed |

- **ควรถูกจับที่ด่านไหน:**
  - **ข้อ 1 (เกณฑ์ 3 ข้อไม่มี assertion)** → **โจทย์ Job A เอง** · reviewer ยอมรับ:
    *"This one is substantially my defect — my step-6 list named seven assertions and omitted all
    three"* · ด่านรองคือ implementer ซึ่งเดินตามรายการโดยไม่ตรวจกลับกับเกณฑ์ของ issue
  - **ข้อ 2 (`Browser.close` ไม่มีเทสคุมรอยต่อ)** → **self-check ของ implementer** ควรจับได้ ·
    และมันอยู่ใน **รายการที่ implementer บอกเองว่าไม่ได้ mutate-prove** พอดี — ความเสี่ยงอยู่ตรงที่ประกาศไว้จริง

### 4. รอบแก้ (รอบ 1)
orchestrator ส่ง problems verbatim ตรงให้ implementer → แก้ → Job B รีวิวซ้ำ

- แก้ blocking ทั้งสองด้วย mutation ตัวเดียวกับที่ reviewer ใช้ ยืนยันแดงแล้วคืนค่าแบบ byte-identical
- **รับ nit 7 จาก 8** และตัวที่ reviewer เขียนแค่ *"consider"* (nit 1) กลับพบว่าผิดจริง —
  `Browser.close` ทำให้ Edge ตัด socket ซึ่ง **คืออาการของความสำเร็จ** แต่โค้ดเขียน traceback
  ลง log ที่ README บอกให้ operator ไปดูตอนแก้ปัญหา

#### 🔴 บั๊กข้อที่สามที่โผล่มาระหว่างแก้ — ร้ายแรงกว่าทั้งสองข้อที่สั่ง

`installer/register-capture-task.ps1` **parse ไม่ผ่านเลยภายใต้ Windows PowerShell 5.1**

```
ไฟล์ไม่มี BOM
 → PS 5.1 อ่านสคริปต์ไม่มี BOM ด้วย ANSI codepage ของระบบ (1252) ไม่ใช่ UTF-8
   → em-dash (E2 80 94) ถอดรหัสเป็น â€" โดยตัวท้ายคือ U+201D
     → tokenizer ของ PowerShell รับ U+201D เป็นตัวปิด string
       → string ถูกตัด โค้ดหลังจากนั้นพังหมด
         → error รายงานว่า "Missing closing }" ที่บรรทัด 121 ห่างจากต้นเหตุหลายสิบบรรทัด
```

**จะทำให้บรรทัด `[Run]` ของ installer ล้มบนเครื่องลูกค้าจริง** · ต้นเหตุคืออักขระที่เราใส่เอง
(em-dash ในข้อความ error ภาษาอังกฤษ) · แก้ด้วยการใส่ UTF-8 BOM และ **pin ด้วยเทส**
`TestPs1IsSavedWithAUtf8Bom` ⇒ เปลี่ยนจาก "ต้องมีคนจำได้ว่าต้องรัน parse check"
เป็น assertion ในชุดเทส

### 5. reviewer (Job B รอบ 2) — **APPROVED**
- **ไม่เชื่อรายงาน รัน probe เองใหม่ทั้งหมด** — mutation ทุกตัวที่รอบแรกเขียวตอนนี้แดงหมด ·
  และ probe เพิ่มอีก 2 ตัวที่ implementer ไม่ได้อ้าง (`-DontStopIfGoingOnBatteries` → `-RunOnlyIfIdle`,
  `-LogonType ServiceAccount` → `Password`) — **8 probe 8 แดง** ทุกไฟล์ hash-verified คืนค่าแล้ว

#### ⚠️ คำตัดสินเรื่อง parse check ที่ขัดกันเอง — **reporting defect ไม่ใช่ prompt defect**

orchestrator ตั้งสมมติฐานว่ารอบแรก *วัดผิดวิธี* (`Get-Content -Raw` ผ่าน .NET encoding detection
vs `powershell -File` ที่ใช้ codepage) · **reviewer พิสูจน์ว่าสมมติฐานนี้ผิด** โดยสร้างไฟล์
ไม่มี BOM รูปเดียวกันแล้วรันทั้งสองวิธี

```
[ScriptBlock]::Create((Get-Content -Raw …))  -> PARSE FAILED: The string is missing the terminator
[Parser]::ParseFile(…)                        -> PARSE FAILED: The string is missing the terminator
```

⇒ คำสั่งที่ prompt ระบุ **จับบั๊กนี้ได้อยู่แล้ว** · รอบแรกรายงานว่าผ่านทั้งที่คำสั่งที่ตัวเองอ้างจะขัดแย้ง

และ reviewer ยังตรวจจุดที่ *ดูเหมือนจะขัดกัน* ด้วย — `chcp` บนเครื่องนี้รายงาน **437** ซึ่งไม่ผลิต
อักขระ quote · แต่ `-File` ใช้ `GetACP()` ไม่ใช่ console codepage และทั้ง
`[Text.Encoding]::Default.CodePage` กับ registry `Nls\CodePage\ACP` รายงาน **1252** ⇒ ห่วงโซ่ครบ

## ต้นทุน (เวลา + tokens ต่อสเตจ)

| สเตจ | เวลา | tokens (สะสม) |
|---|---|---|
| reviewer Job A | 16.6 นาที + ตายกลางคัน 1 ครั้ง | 171,731 |
| implementer (build) | 37.8 นาที | 388,060 |
| reviewer Job B (รอบ 1) | 12.3 นาที | 263,480 |
| รอบแก้ 1 — implementer | 18.4 นาที | 489,348 |
| รอบแก้ 1 — reviewer Job B | 4.3 นาที | 283,246 |
| **รวม** | **~89 นาที** | — |

> ⚠️ token บวกกันไม่ได้ — `subagent_tokens` หลัง `SendMessage` resume เป็นค่า**สะสม**
> · เวลาเป็นค่าต่อรอบจริง บวกได้
>
> **รอบแก้ = 22.7 นาที = 26% ของ wall-clock** (ครั้งก่อนที่ #38 วัดได้ 35%)
>
> **Job A ตายกลางคันด้วย API 529 Overloaded** — resume ด้วย `SendMessage` ไม่ spawn ใหม่
> จึงไม่เสีย context ที่อ่านไปแล้ว

## ✅ skill ที่เรียกจริง — ยืนยันจาก transcript (tamper-proof)

```
=== reviewer ac171d77797ed64e9 (1,201,839 bytes) ===
      1 "skill":"draft-delegation-prompt"
      1 "skill":"scrutinize"
Skill calls: 2

=== implementer a6304d2357e06776d (2,871,398 bytes) ===
      1 "skill":"tdd"
Skill calls: 1
```

- **ครบทุก mandate** — prompt สั่ง `/tdd` และระบุว่าไม่มี domain skill ⇒ ตรงกับ transcript
- **ไม่มีรีวิวซ้ำซ้อน** — implementer ไม่ได้เรียก `scrutinize`/`code-review` เอง
- **`docs-researcher` ถูก spawn 1 ตัว** โดย implementer เพื่อยืนยันรูปแบบคำสั่ง NSSM ซึ่ง
  **prompt สั่งให้ยืนยันแทนการเดา** ⇒ เป็นงานที่ตั้งใจ ไม่ใช่การค้นซ้ำที่ Job A ควรใส่มาให้แล้ว

## Commit
`dbfc3d2` — `fix: launch Edge through a LOCAL SERVICE task, service back on LocalSystem (#40)`
10 ไฟล์ · +1,389 / −352

**เจ้าของยังติดหนี้ install round หนึ่งรอบ** (agent ทำแทนไม่ได้): build → ลงทับ →
`sc qc arichds` ต้องได้ `LocalSystem` · task `ARICHDS Capture Browser` มีอยู่ใต้
`NT AUTHORITY\LOCAL SERVICE` · Poller ยังอ่านครบ 3 มิเตอร์ · Load Profile CSV ยังออก ·
และ **capture `.png` ลงใน `capture_dir` ที่อยู่ใต้ `C:\Users\…` ได้** — เคสที่พังจริงคราวที่แล้ว

## วิธีตรวจซ้ำด้วยตัวเอง (audit)

```bash
d="C:/Users/HP/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents"
grep -o '"skill":"[a-zA-Z0-9:_-]*"' "$d/agent-ac171d77797ed64e9.jsonl" | sort | uniq -c   # reviewer
grep -o '"skill":"[a-zA-Z0-9:_-]*"' "$d/agent-a6304d2357e06776d.jsonl" | sort | uniq -c   # implementer
```

**อย่าใช้ `output_file` ที่ tool คืนมา** — เป็น 0 ไบต์เสมอ และ grep แล้วได้ผลลัพธ์ที่หน้าตา
เหมือน "agent ข้าม skill ที่บังคับ" เป๊ะ · ไฟล์จริงอยู่ใต้ `projects/…/subagents/`
