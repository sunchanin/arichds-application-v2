# Audit log — Issue #28: M7-1: Energy Summary — both tabs, and the calendar behind them
รัน: 2026-08-11 · branch: `main` (**ยังไม่ commit** — งานค้างบน main, ต้องแตกกิ่งก่อน) · ผลลัพธ์: **APPROVED** · รอบรีวิว: **2**
เกิดจากของหลุด: ไม่ใช่ งานใหม่ — สไลซ์แรกของ M7 ที่ grill เมื่อ 2026-08-11 แล้ว scrutinize สองรอบก่อนเปิดใบ

## ทำอะไรไปบ้าง (ทีละขั้น)

1. **reviewer (Job A) — สร้าง prompt** (`/draft-delegation-prompt`)
   - Track: **full** — ~40 ไฟล์ ครอบ schema / driver read path / 3 router / 3 หน้า พร้อมกับดักพฤติกรรม 6 จุดที่แต่ละจุดต้องมีเทสที่แยกแยะได้จริง
   - TDD required: **yes** — กฎถัง TOU, การแยก annual/public จาก GXDate, การปฏิเสธ 29 ก.พ. และ upsert วินาทีเดียวกัน ล้วนเป็น branch logic ที่ assertion ผิดแล้วมองไม่เห็น
   - ยืนยันสกิลของโปรเจคก่อนเริ่ม: `fastapi` · `antd-ui` · `gurux-dlms` โหลดได้ทั้งสามตัว
   - **ของที่ reviewer หามาเองแล้วมีค่า**: ไปอ่าน `gurux_dlms 1.0.201` ที่ติดตั้งจริง แล้วพบสัญญาของไลบรารีที่ตัว issue ยังไม่มี — `_GXCommon.py:466-472` ปีบนสายเป็น `0xFFFF` จะตั้ง `DateTimeSkips.YEAR` แล้ว**ยัดปี 2000 ลงใน `.value` เป็นตัวหลอก** ⇒ annual ⟺ บิตนั้น ไม่ใช่การเดาจากสตริง · และเจอว่า `GXDLMSSpecialDaysTable` มี `.insert()`/`.delete()` ที่เขียนมิเตอร์จริง จึงใส่ไว้ใน out-of-scope แบบชี้ชัด
   - **ไม่มี `docs-researcher` ถูก spawn** ทั้งรอบ — reviewer ใช้ซอร์สที่ pin ไว้ในเครื่องตามที่ CLAUDE.md สั่ง

2. **implementer — ลงมือ + ตรวจตัวเอง** (`/tdd` + `gurux-dlms` + `antd-ui` + `fastapi` + self-check สองด่าน)
   - ไฟล์ที่เปลี่ยน: **37** — BE ใหม่ 6 (`migrations/0010_*`, `api/energy.py`, `api/holidays.py`, `api/special_days.py`, `acquisition/energy_registers.py`, `acquisition/special_days.py`) · BE แก้ 7 (`db/models.py`, `drivers/base.py`, `drivers/_dlms.py`, `smw110.py`, `smart_tcc.py`, `catalog.py`, `constants.py`, `main.py`) · เทสใหม่ 8 ไฟล์ · เทสแก้ 4 ไฟล์ · FE ใหม่ 3 หน้า + แก้ 3 · เอกสาร 4
   - **แหกคำสั่งของ Job A หนึ่งจุดโดยมีเหตุผล**: step 5 สั่งให้ใส่โค้ดอ่านไว้ใน `smw110.py` และ `smart_tcc.py` · implementer ย้ายไป `_dlms.py` เป็น **free function ไม่ใช่ method** เพราะ method บนคลาสแม่จะถูกไดรเวอร์ CEWE ทั้งสาม (ที่ `supports_*()` เป็น `False`) สืบทอดไปแล้ว**เรียกได้และทำงานได้จริง** ⇒ พังสัญญา `supports_X()==False ⟹ read_X() raises` ที่ `base.py` เขียนไว้ · มันเจอเองตอน driver-contract test แดง · **reviewer ตรวจเหตุผลแล้วรับ**
   - self-check เจออะไรเหนือ nit และแก้อย่างไร:
     - **404 กลายเป็น 500** — router ทั้งสามเรียก job function ที่โยน `ValueError` เมื่อ `device_id` ไม่มีจริง โดยไม่เช็คก่อน ⇒ เพิ่มการเช็ค + เทส regression
     - **HTTP 502 ขัดธรรมเนียมโปรเจค** — ร่างแรกตอบ 502 เวลามิเตอร์ล้ม ซึ่งขัดแบบแผน "ตอบ 200 เสมอ คำตัดสินอยู่ใน payload" ของ Test Connection / Read Now ⇒ ออกแบบใหม่เป็น `{row|entries, error}` · จงใจเว้น `holidays.py` import-from-meter ให้โยน `HTTPException` เพราะมันเป็นการแทนที่แบบทำลายหลัง `Modal.confirm` และ FE ใช้ `.catch()` แยก "ไม่มีอะไรถูกแทนที่" ออกจาก "สำเร็จ" — **reviewer ไล่โค้ดแล้วรับ**
   - ผลรันเทสต์ (จริง ไม่ใช่ cached): baseline `1155 passed, 1 skipped` → รอบสร้าง `1257 passed, 13 skipped (54.19s)` → หลังแก้ `1262 passed, 13 skipped (49.40s)` · `ruff format --check` 170 ไฟล์ผ่าน · `ruff check` ผ่าน · `pnpm lint` 0 error · `pnpm build` ผ่าน

3. **reviewer (Job B) — รีวิว** (`/scrutinize`)
   - รอบ 1 verdict: **CHANGES_REQUESTED** — 5 problems (ทั้งหมด minor) + 4 nits
   - **ห้าในหกข้อไม่ใช่ "โค้ดผิด" แต่เป็น "เทสจับไม่ได้"** และทุกข้อมีหลักฐาน mutation ที่เทสยังเขียว
   - รอบ 2 verdict: **APPROVED** — reviewer ยิง mutation **9 แกนใหม่** ที่ทั้งสองฝ่ายยังไม่เคยใช้: สลับคู่ reactive `C=3`/`C=4` (แดง) · สลับ `rate_a`/`rate_b` (แดง) · ลบ `/ WH_TO_KWH_DIVISOR` (แดง) · เปลี่ยน D-field `D=8`→`D=6` (แดง) · ตรึง aggregate ไว้ที่ Logger 2 (แดง 7 เคส) · `%m`/`%d` กับ fixture ใหม่ (แดง) · ปิดการตรวจ public shape (แดง) · ขอบ peak `<`→`<=` (แดง) · ตัด `h.kind` ออกจาก annual branch (**เขียว — และถูกต้อง**: แถว public มี `month`/`day` เป็น NULL จึงเข้าเงื่อนไข annual ไม่ได้อยู่แล้ว = equivalent mutant ไม่ใช่ช่องโหว่)
   - ยืนยันว่าโค้ด production ไม่ถูกแตะในรอบแก้: `energy.py`, `holidays.py`, `_dlms.py` hash เท่าเดิมกับรอบ 1

   - **ควรถูกจับที่ด่านไหน** (reviewer เป็นคนตอบเอง รวม nit):

     | # | problem | ด่านที่ควรจับ |
     |---|---|---|
     | 1 | `SPEC.md:888-889` ตารางความสามารถยังถามคำถามที่ใบนี้ตอบไปแล้ว | **Job A (ของ reviewer เอง)** — มันชี้ไป §4 แล้วบอกให้ "ยืนยัน อย่าแก้" โดยไม่เคยส่งไป §3.7 ทั้งที่ decision 2 ของมันเองตั้งอยู่บนการรู้ว่าตารางนั้นเป็นค่าชั่วคราว |
     | 2 | `patterns.md` เขียนว่า wildcard year แสดงเป็น `"2000"` ซึ่งไม่จริง | **self-check ของ implementer** — มันรันไลบรารีตัวนั้นอยู่แล้วตอนทำเทส classification · `python -c` บรรทัดเดียวหักล้างได้ · มันตรวจ**โค้ดเทียบไลบรารี** แต่ไม่เคยตรวจ**ข้อความที่ตัวเองเขียนถึงไลบรารี** |
     | 3 | `read_energy_registers_via()` ไม่มีเทสรันผ่านเลย | **self-check ของ implementer — ชั้น mutation sweep** · ยิง 6 ครั้ง ไม่มีครั้งไหนเล็งมาที่ฟังก์ชันอ่านที่แชร์กัน และ diff ของ `fakes.py` เองก็แสดงว่า fake override ทั้งเมธอด · ด่านที่ขาดคือคำถาม "โค้ด production ใหม่ตัวไหนที่ไม่มีเทสรันผ่านเลยสักตัว" |
     | 4 | fixture วันหยุดประจำปี `1/1` สลับ `%m`/`%d` แล้วไม่ตาย | **แบ่งกัน** — Job A ระบุเคส "annual ข้ามปี" แต่ไม่เคยบอกว่า fixture ต้องไม่สมมาตร ทั้งที่ Findings ของมันเองมี `04/13` และคำเตือน `12/05`/`05/12` อยู่ · ส่วน sweep ของ implementer ยิงแต่โค้ด ไม่ยิงอำนาจแยกแยะของ fixture |
     | 5 | ข้อจำกัด Logger 1 ไม่ถูกตรึง | **Job A (ของ reviewer เอง)** — decision 6 เขียนกฎและเหตุผลไว้ แต่ไม่ใส่ลงในรายการเทสที่บังคับ ⇒ ไม่มีอะไรร้องขอเคส exclude logger 2 |
     | 6 | nit — การตรวจ shape ของ public ไม่ถูกตรึง | **self-check ของ implementer — และมันจับได้จริง** ประกาศไว้เองแทนที่จะแก้ · ซื่อสัตย์ และค่าแก้แค่เทสเดียว |
     | 7 | nit — `GET /api/energy/registers` ไม่มีขอบเขต | **Job A (ของ reviewer เอง)** — ระบุ endpoint ว่า "stored rows" โดยไม่ใส่ขอบ ทั้งที่ทุก row endpoint ในรีโปนี้แบ่งหน้าฝั่งเซิร์ฟเวอร์ |
     | 8 | nit — `Descriptions` children API ที่ AntD v6 เลิกรองรับ | **Job B เท่านั้น** — compile ผ่าน lint ผ่าน ทำงานได้ · ต้องเปิด `.d.ts` ที่ติดตั้งถึงจะเห็น |
     | 9 | nit — ตัวเลือกช่วงวันเกิน 31 วันถูกทิ้งเงียบ | **Job B เท่านั้น** — เป็นการตัดสิน UX ไม่มี artifact ที่แดงรองรับ |

4. **รอบแก้ (1 รอบ):** orchestrator ส่ง problems verbatim ตรงให้ implementer (ไม่วนกลับ Job A) → implementer **ทำ mutation ของ reviewer ซ้ำเองก่อนเขียนเทสใหม่ทุกข้อ** (ข้อ 3: 2/3 เทสใหม่แดง ขณะที่ 19 เทสเดิมยังเขียว = ตรงกับหลักฐานเดิมเป๊ะ) → คืนค่าและ verify byte-identical ทุกครั้ง → รันชุดเต็ม → reviewer Job B รีวิวซ้ำ → APPROVED
   - nit ที่เอา: 6, 8, 9 · **nit ที่ข้าม: 7** — reviewer ตัดสินว่า**ข้ามได้ แต่ห้ามหายเงียบ** ⇒ เปิดเป็น `docs/issues/002-energy-registers-endpoint-is-unbounded.md`

## ต้นทุน (เวลา + output tokens ต่อสเตจ)

| สเตจ | เวลา | tool calls | subagent_tokens (สะสม ไม่ใช่ต่อรอบ) |
|---|---|---|---|
| reviewer Job A | 14.1 นาที | 74 | 210,616 |
| implementer (build) | **54.0 นาที** | 283 | 601,537 |
| reviewer Job B รอบ 1 | 13.3 นาที | 35 | 333,692 |
| รอบแก้ 1 — implementer | 9.8 นาที | 344 (สะสม, +61) | 638,187 |
| รอบแก้ 1 — reviewer Job B | 4.4 นาที | 8 | 353,056 |
| **รวมเวลาจริง** | **95.6 นาที** | | |

⚠️ `subagent_tokens` **นับซ้ำข้าม SendMessage** — เป็นค่าสะสมของ agent ตัวนั้น ไม่ใช่ต้นทุนต่อสเตจ ห้ามเอามาบวกกัน (memory: `subagent-token-counts-are-not-additive`) · ตัวเลข output tokens จริงต่อสเตจ **ไม่ได้วัด**

**เทียบกับค่ากลางของไปป์ไลน์** (168 รอบ): implementer ปกติ 15.3 นาที / 75 tool calls ⇒ รอบนี้ **3.5 เท่าทั้งสองแกน** · ไม่ได้ช้าต่อหน่วยงาน แต่เป็นงานที่ใหญ่ 3.5 เท่า — ผลโดยตรงจากการยุบ 8 ใบเหลือ 4 ตามที่เจ้าของสั่งตอน scrutinize

**รอบแก้ราคาถูกกว่ารอบสร้างมาก** — 9.8 นาที เทียบ 54 นาที (18%) และรีวิวซ้ำ 4.4 นาที เทียบ 13.3 (33%) · การต่อ agent เดิมด้วย SendMessage แทนการ spawn ใหม่คือเหตุผล

## ✅ skill ที่เรียกจริง — ยืนยันจาก transcript (tamper-proof)

```
reviewer   agent-aeeaa817b7f83db4b.jsonl  (1.5M)
      1 "skill":"draft-delegation-prompt"
      1 "skill":"scrutinize"
Skill calls: 2

implementer  agent-a06e656316a043f51.jsonl  (3.7M)
      1 "skill":"antd-ui"
      1 "skill":"fastapi"
      1 "skill":"gurux-dlms"
      1 "skill":"tdd"
Skill calls: 4
```

**ไม่มีงานซ้ำซ้อน** — implementer ไม่เรียก `scrutinize`/`code-review` และ reviewer ไม่เรียกสกิลรีวิวตัวที่สองทับ `scrutinize` · สกิลที่ Workflow-discipline บังคับไว้ถูกเรียกครบทั้งสามตัว

⚠️ **`output_file` ที่ระบบคืนมาตอน spawn เป็น 0 ไบต์ถาวร** — ถ้าเชื่อตามนั้นจะรายงานผิดว่า "ไม่เรียกสกิลเลย" · transcript จริงอยู่ที่ `~/.claude/projects/<slug>/<session>/subagents/agent-<id>.jsonl` (memory: `subagent-transcripts-often-empty`)

## Commit

**ยังไม่ commit — รอเจ้าของตัดสินใจ** · 39 ไฟล์ค้างอยู่บน `main` (37 จาก implementer + `docs/issues/002-*.md` + audit log ใบนี้)

⚠️ **อยู่บน `main`** เพราะ PR #33 (`fix/load-profile-backfill-stall`) เพิ่งถูก merge เข้าไป ⇒ ต้องแตกกิ่งก่อน commit · ชื่อที่เสนอ: `feature/energy-summary`

## วิธีตรวจซ้ำด้วยตัวเอง (audit)

หลักฐานจริงอยู่ใน subagent transcript — **ใช้ path จริงด้านล่าง อย่าใช้ glob สำเร็จรูป**:

```
D=~/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents
grep -o '"skill":"[a-z0-9:_-]*"' $D/agent-aeeaa817b7f83db4b.jsonl | sort | uniq -c   # reviewer
grep -o '"skill":"[a-z0-9:_-]*"' $D/agent-a06e656316a043f51.jsonl | sort | uniq -c   # implementer
grep -c '"name":"Skill"' $D/agent-a06e656316a043f51.jsonl                            # จำนวน Skill call ทั้งหมด
```

## สิ่งที่ควรเสริม (จากตาราง "ควรถูกจับที่ด่านไหน")

**สี่ในเก้าข้อ (1, 5, 7 และครึ่งหนึ่งของ 4) ย้อนไปที่ prompt ของ Job A** และทุกข้อเป็น**รายการที่ไม่ครบแบบที่รายการมักไม่ครบ** — เอกสารไหนต้องแตะ, เทสไหนบังคับ, endpoint ควรมีรูปร่างอย่างไร

**อีกสองข้อ (2, 3) ย้อนไปที่ mutation sweep ของ implementer** ที่เล็งแต่โค้ดที่ตัวเองเพิ่งเขียน ไม่เคยถามว่า **"โค้ด production ใหม่ตัวไหนที่ไม่มีเทสรันผ่านเลย"** และไม่เคยตรวจ**ข้อความที่ตัวเองเขียนถึงไลบรารี** ทั้งที่รันไลบรารีนั้นอยู่แล้ว

สองด่านนี้คือที่ที่ควรเสริม · รีวิวจับได้ทั้งหมด แต่จับที่จุดที่แพงที่สุด
