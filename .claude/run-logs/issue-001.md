# Audit log — Issue #001: probe_meter ต้องพิมพ์รายงานต่อได้เมื่อมิเตอร์ปฏิเสธ Meter Serial

รัน: 2026-08-06 · branch: `feature/device-manager` · ผลลัพธ์: **APPROVED** · รอบรีวิว: **1**

> ใบนี้ถูกสร้างขึ้นเพื่อ**ทดสอบ pipeline ที่เพิ่งย้ายขึ้น `~/.claude`** เป็นครั้งแรก
> ไม่ใช่งานตามบันไดโมดูล — ตัวใบเองมาจาก nit ข้อ 3 ที่ค้างอยู่ใน `issue-8.md`
> รันในโหมด **local** (`docs/issues/001-*.md`) จึงไม่แตะ `gh` เลยตลอดทั้งรัน

## ทำอะไรไปบ้าง (ทีละขั้น)

1. **reviewer (Job A) — สร้าง prompt** (`/draft-delegation-prompt`) · 4.0 นาที / 68k tokens
   - Track: **full** — มีสามสาขาพฤติกรรม (raise / `None` / ปกติ) บวกสัญญาเรื่อง exit code ไม่ใช่งานเชิงกล
   - TDD required: **yes** — เทสเป็น acceptance criterion ของใบเอง และ assertion "ชุด register ยังถูกพิมพ์" พิสูจน์ว่าเคยแดงได้ทางเดียวคือเขียนเทสก่อน
   - Workflow discipline: **`/gurux-dlms`** — reviewer อ่าน `CLAUDE.md` เองแล้วตัดสินว่า `probe_meter.py` เข้าข่าย
     (import `gurux_dlms.objects` ที่บรรทัด 51) โดย orchestrator **ไม่ได้บอกคำตอบ** — กลไก generalized ทำงานแทน hardcode เดิมได้จริง
   - **จับได้ว่าใบเขียนผิด**: ใบอ้างว่า `test_dlms_scaler.py` เป็นตัวอย่างของเทสที่เข้าถึง `scripts/` — ไม่จริง มัน import จาก `src/` ที่อยู่บน `pythonpath` อยู่แล้ว
     ตัวอย่างจริงคือ fixture `vendor_cli` ใน `conftest.py` · reviewer สั่ง **ห้ามแก้ไฟล์ใบ** ให้บันทึกไว้ในรายงานแทน เหตุผล: "ใบงานคือบันทึกว่าถูกขออะไร แก้กลางทางทำให้ audit trail กำกวม"

2. **implementer — ลงมือ + ตรวจตัวเอง** (`/tdd` + `/gurux-dlms`) · **สองครั้ง** รวม 27.6 นาที / 183k tokens
   - **ครั้งที่ 1 ล้ม (9.9 นาที / 86k / 39 tool call)** — ดูหัวข้อ "process miss" ด้านล่าง
   - ครั้งที่ 2 (resume ตัวเดิม ไม่ได้ spawn ใหม่ context ยังครบ) · 17.7 นาที / 97k
   - ไฟล์ที่เปลี่ยน: `app/scripts/probe_meter.py` (+15 −3) · `app/tests/test_probe_meter_script.py` (ใหม่)
   - self-check เจออะไรเหนือ nit: ไม่มี · ไล่ครบ 4 เส้นทาง (raise / `None` / string จริง / `connect()` ล้ม)
   - ผลรันเทสต์: full suite **588 → 592 passed** ขยับ 4 พอดี · `ruff format --check` + `ruff check` เขียวทั้งคู่ · ไม่ใช่ `(cached)`
   - red step มีหลักฐาน paste จริง: เทส 2 กับ 3 fail ด้วยเหตุผลที่ถูก (`!!! FAILED:` แล้วไม่มีชุด register / พิมพ์คำว่า `None` เปล่า)

3. **reviewer (Job B) — รีวิว** (`/scrutinize` — ความละเอียดตาม track `full`) · 2.4 นาที / 87k
   - verdict: **APPROVED** · problems: nit 2 ข้อ ไม่บล็อก
   - รันเทสเอง **แบบ scoped ตาม `reviewer.md`** ไม่ใช่ full suite: `test_probe_meter_script` + `test_dlms_scaler` + `test_probe` + `test_poller` → 108 passed
     (ขยายขอบเขตเองเพราะการเปลี่ยนอยู่บนเส้นทางอ่าน Meter Serial ที่สองไฟล์หลังครอบด้วย)
   - **2b dependency-swap**: ไม่ทริกเกอร์ — ไม่มี callable/import ไหนถูกสลับ
   - **2c ADR conflict**: ทริกเกอร์ที่ ADR 0007 และผ่าน — ตรวจ*ข้อเท็จจริง*ในประโยคที่พิมพ์ ไม่ใช่ถ้อยคำ: ยืนยันกับ `poller.py:150-156` ว่า serial เป็น `None` คืน `TickOutcome.FAILED` จริง ประโยคใหม่จึงย้ำ ADR ไม่ได้ขัด
   - **2d documentation-consistency**: ทริกเกอร์และผ่าน — docstring ที่กลายเป็นเท็จถูกแก้ในการเปลี่ยนเดียวกัน · reviewer กวาด ADR อื่นเองแล้วไม่มีอะไรอ้างรูปแบบ output นี้
   - ตรวจว่าไม่มี socket จริง ๆ ด้วยการ**อ่านโค้ด**: `ConnectionParams.net()` เป็น dataclass ล้วน พอ patch `create_driver` แล้วไม่เหลือเส้นทางเปิด socket ในฟังก์ชัน — ไม่ได้เชื่อรายงาน

4. **รอบแก้:** ไม่มี — APPROVED รอบเดียว

## ✅ skill ที่เรียกจริง — ยืนยันจาก transcript (tamper-proof)

```
reviewer   (a3bc1ee9e7e4992a0.output, 336 KB)   1 draft-delegation-prompt · 1 scrutinize   (Skill call รวม 2)
implementer(a0a5ea753336c99fd.output, 470 KB)   1 gurux-dlms · 1 tdd                       (Skill call รวม 2)
```

ครบทุกตัวที่ถูกบังคับ · **ไม่มี `code-review`** ในฝั่ง reviewer ซึ่งถูกต้องตามการออกแบบใหม่ · ไม่มีการรีวิวซ้ำซ้อน (implementer ไม่ได้แตะ review skill ใด ๆ บน diff ตัวเอง)

## ⚠️ Process miss — implementer จบเทิร์นรอ background task ของตัวเอง

**เกิดอะไร**: ครั้งแรก implementer เขียนไฟล์เทสเสร็จ แล้ว**ย้ายไปเป็น `.bak`** เพื่อเก็บตัวเลข baseline ของ full suite ให้สะอาด
สั่ง `pytest` แบบ **background** แล้วตอบกลับมาว่า *"I'll stop issuing commands and wait for the background task notification to arrive."* — ซึ่งคือการจบเทิร์น
มันไม่ถูกปลุกกลับมา งานจึงหยุดค้าง ผลสุทธิ: 9.9 นาที / 86k / 39 tool call ได้ไฟล์ `.bak` ค้างหนึ่งไฟล์ และ `probe_meter.py` ที่ยังไม่ถูกแตะเลย

**แก้อย่างไร**: orchestrator ตรวจ tree เห็นสภาพจริง แล้ว `SendMessage` ให้ agent **ตัวเดิม** ทำต่อ (context ยังครบ ไม่ต้องเริ่มใหม่) พร้อมสั่งชัดว่า
ห้ามรันคำสั่งแบบ background · ให้กู้ `.bak` กลับมาแทนเขียนใหม่ · และถ้าไม่ได้จับ baseline ไว้ให้บอกตรง ๆ ได้

**ที่ยังค้าง**: ถึงจะถูกบอกว่าไม่ต้องวัด baseline ซ้ำ implementer ก็เลือกวัดจริงอยู่ดี โดยย้ายไฟล์เทสออกและถอด fix ออกจาก tree ชั่วคราวอีกครั้ง
ได้ตัวเลข 588 ที่เชื่อถือได้จริง แต่เป็น pattern เดิมที่ทำให้รอบแรกพัง — ถ้าตายกลางทางซ้ำ tree ก็ค้างซ้ำ

**ข้อเสนอต่อ `~/.claude/agents/implementer.md`** (ยังไม่ทำ รอเจ้าของตัดสิน):
1. ห้ามรันเทสแบบ background — suite นี้ใช้เวลาไม่กี่นาที การ block รอคือสิ่งที่ถูก
2. ห้ามย้าย/ถอดไฟล์ในโปรเจกต์ออกชั่วคราวเพื่อวัด baseline — ถ้าไม่ได้จับไว้ ให้รายงานว่าไม่ได้จับ แล้วรายงานเฉพาะตัวเลขสุดท้าย + จำนวนเทสที่เพิ่ม

## Nit ค้างให้เจ้าของ (2 — ไม่บล็อก)

1. `test_probe_meter_script.py:101` — `assert "!! RuntimeError: undefined object" in out` ไม่ได้ปักว่าอยู่**บรรทัดไหน**
   ไม่กำกวมเฉพาะวันนี้เพราะ stub ไม่มีทางโยนจากที่อื่น · เทส happy path เหนือขึ้นไปหนึ่งจอปักทั้งบรรทัด (`meter_serial      : ABC12345`) — ทำให้สมมาตรกันจะดีกว่าและไม่มีต้นทุน
2. `test_probe_meter_script.py:20-22` — `sys.path.insert(0, app/scripts)` ทำงานตอน import module จึงค้างหน้า `sys.path` ทั้ง session
   ต่างจาก `conftest.vendor_cli` ที่ insert ใน fixture · ไม่มีอันตรายตอนนี้ (`scripts/` มีแค่ 2 ไฟล์ ไม่บัง stdlib) แต่บันทึกไว้เพื่อว่าถ้าอนาคตมีสคริปต์ชื่อ `types.py` หรือ `logging.py` จะได้รู้ว่าเป็นเพราะอะไร

**การเปลี่ยนพฤติกรรมเงียบ ๆ ที่ reviewer ไล่แล้วตัดสินว่าตั้งใจ ไม่นับเป็น finding**: ถ้า TCP หลุด*ระหว่าง*อ่าน serial ตอนนี้จะพิมพ์ `!!` ทั้ง serial และทุก register แล้วออกด้วย **0** จากเดิม 1 — ตรงกับที่ใบระบุ ("มิเตอร์ที่ associate ได้แต่ปฏิเสธ ถือว่าเป็นการวินิจฉัยที่สำเร็จ") และ loop ข้างล่างก็ทำแบบนี้มาก่อนหน้าแล้ว การเปลี่ยนนี้จึงลบความไม่สอดคล้อง ไม่ได้สร้างขึ้น · `KeyboardInterrupt`/`SystemExit` ยังไม่ถูกจับ

## Commit

ยังไม่ commit — **รอมนุษย์ตัดสินใจ** · `app/scripts/probe_meter.py` (M) และ `app/tests/test_probe_meter_script.py` (ใหม่)
หมายเหตุ: working tree ยังมีงานคนละใบค้างอยู่ด้วย (การจัดบ้าน `.claude/` 38 deletion + `CLAUDE.md`) — อย่า `git add -A` รวดเดียว

## วิธีตรวจซ้ำด้วยตัวเอง (audit)

```
cd app && ruff format --check . && ruff check . && pytest        # 592 passed
git diff -- app/scripts/probe_meter.py
git status --short -- app/                                        # ต้องเห็นแค่ 2 path
```

หลักฐาน skill อยู่ใน transcript — ใช้ **path จริง** ที่จับไว้ตอน spawn (อย่าใช้ glob สำเร็จรูป):

```
grep -o '"skill":"[a-z0-9:_-]*"' <output_file ของ reviewer>    | sort | uniq -c
grep -o '"skill":"[a-z0-9:_-]*"' <output_file ของ implementer>  | sort | uniq -c
```

## ต้นทุนที่วัดได้ (สำหรับเทียบรอบหน้า)

| ขั้น | เวลา | tokens |
|---|---|---|
| reviewer Job A | 4.0 นาที | 68k |
| implementer ครั้งที่ 1 (ล้ม) | 9.9 นาที | 86k |
| implementer ครั้งที่ 2 | 17.7 นาที | 97k |
| reviewer Job B | 2.4 นาที | 87k |
| **รวม** | **~34 นาที** | **~338k** |

ถ้าไม่นับครั้งที่ล้ม: ~24 นาที / 252k สำหรับใบ track `full` ที่มี TDD บังคับและผ่านรอบเดียว
