# Issue #25 — M4c-2: SMART TCC, ไดรเวอร์เดียวคุมทั้งห้ารุ่น บนเส้นทางเข้ารหัส

**สถานะ: DONE** · commit `1d85cab` · branch `feature/remaining-meter-models` · 2 รอบรีวิว

---

## ขั้นตอนที่เดินจริง

1. **Job A** — reviewer เขียน `DELEGATION PROMPT` ผ่าน `/draft-delegation-prompt` · Track = `full` · TDD = required
2. **Implement** → **Job B รอบ 1** → CHANGES_REQUESTED (minor 2 · nit 3)
3. **แก้รอบ 1** → **Job B รอบ 2** → **APPROVED**

---

## สกิลที่เรียกจริง — ตรวจจาก transcript

| Agent | ไฟล์ | สกิลที่พบ |
|---|---|---|
| reviewer | `agent-a2bf159613d21d11c.jsonl` (1.13 MB) | `draft-delegation-prompt` ×1 · `scrutinize` ×1 · **Skill call รวม 2** |
| implementer | `agent-a06eb045be4c67081.jsonl` (2.45 MB) | `gurux-dlms` ×1 · **`tdd` ×1** · **Skill call รวม 2** |

**มาตรฐานครบทั้งสองตัว** — ต่างจาก #24 ที่ `/tdd` ไม่ปรากฏใน transcript · **ไม่มีการรีวิวซ้ำซ้อน**

---

## TDD

- **ตัดสิน: required** โดย Job A · เหตุผล: การ map คอลัมน์ · การแยก `(OBIS, attr)` ระหว่างค่ากับเวลา · ทางถอยเปิด/ปิด · และ seam ต่อไดรเวอร์ทั้งสี่ ล้วนมีกิ่ง และ **ไม่มีอันไหนตรวจกับฮาร์ดแวร์ได้เลย**
- implementer รายงานว่า **"ผสม แจกแจงตามพฤติกรรม"** — red→green จริงสำหรับ `smart_tcc.py` และการลงทะเบียนใน factory · ส่วนกลไก seam ของ D5 เป็น **retrospective** เพราะเขียนพร้อมกับการเปลี่ยนชื่อคลาส (docstring ของการเปลี่ยนชื่อต้องอธิบายกลไกที่มันถูกเปลี่ยนชื่อเพื่อรองรับ) แล้วพิสูจน์ย้อนหลังด้วย mutation แทน
- **reviewer ตัดสินว่ารับได้ และรับได้เพราะมันแจกแจงเอง** — *"the D5 seam was retrospective — but backed by a mutation probe which is stronger evidence than a missing-symbol red would have been. Reporting 'mixed, per behaviour' instead of 'yes' is what makes that judgeable."*
- เทส **1061 → 1112 ผ่าน** (1 skipped) · เพิ่ม 41 เทสใน 3 ไฟล์ใหม่

---

## สิ่งที่รีวิวจับได้

### minor 1 — การเปลี่ยนชื่อเอกสารทำให้ทุกการอ้างอิงในโค้ดที่เขียนรอบเดียวกันชี้ผิด

การแก้หัวไฟล์ `tcc-obis-scan.md` ทำให้เนื้อในเลื่อนลง **18 บรรทัด** · โค้ดและเทสที่เขียนใหม่ในรอบเดียวกันอ้างเลขบรรทัด**ก่อนเลื่อน** 9 จุด ⇒ คนที่ตามลิงก์ไปจะโผล่กลางตาราง association view แทนรายการ capture

นี่คือห่วงโซ่หลักฐานที่ `CLAUDE.md` สั่งไว้เองว่า *"อ่านก่อนเชื่อค่าใด ๆ"* — และความเท็จถูกสร้างโดยการเปลี่ยนแปลงที่ย้ายเป้าหมายเอง

reviewer ไล่หาเลขบรรทัดปัจจุบันมาให้ครบทั้ง 9 จุด และชี้ว่าจุดหนึ่งใน `REMAKE-PLAN` **ชี้ไปยังข้อความที่ diff นี้ลบไปแล้ว** ⇒ การใส่เลขใหม่จะผิด ต้องเขียนใหม่ให้บอกว่าอ้างถึงสภาพก่อน #25 · implementer ทำตามนั้น

### minor 2 — ค่าคงที่ซ้ำสองที่ โดยที่สคริปต์ยิงมิเตอร์จริงพึ่งตัวหนึ่งอยู่

`BILLING_PROFILE_OBIS` มีทั้งค่าคงที่ระดับโมดูลและ class attribute ที่พิมพ์ literal เดียวกันโดยไม่อ้างอิงกัน · **ตัวโมดูลไม่ได้ตาย** — `probe_m4c_read.py` import ไปเปิด association กับมิเตอร์ลูกค้าจริง และ**ไม่มีเทสคุมสคริปต์นั้นเลย** ⇒ แก้ที่หนึ่งไม่แก้อีกที่ = สคริปต์ภาคสนามหลุดจากไดรเวอร์แบบเงียบ ๆ

แก้โดยเปลี่ยนชื่อตัวโมดูลเป็น `CEWE_BILLING_PROFILE_OBIS` แล้วให้ class attribute อ้างอิงมัน · **reviewer ยืนยันด้วย `is` ไม่ใช่ `==`** — `DlmsProfileDriver.BILLING_PROFILE_OBIS is CEWE_BILLING_PROFILE_OBIS` → True ⇒ ทั้งสองแยกจากกันไม่ได้อีก

---

## สิ่งที่ implementer ทำแล้วผมคิดว่าถูกต้อง

**จับเทสกลวงของตัวเองได้** — mutation ที่พลิก billing OBIS ไป Scheme 2 เผยว่า `FakeTccBillingReader` ไม่เคยบันทึกว่าถูกขอโปรไฟล์ไหน ⇒ เทสผ่านได้ทั้งที่อ่านผิดโปรไฟล์ · แก้แล้วยืนยันใหม่ · **reviewer ตรวจต่อว่าเป็นรูปแบบหรืออุบัติเหตุ** แล้วยืนยันว่า fake อีกสองตัวบันทึกอยู่แล้ว จึงไม่ลาม

**หาเจอสองไฟล์ที่ prompt พยากรณ์ผิด** — D4 บอกว่ากระทบ 8 ไฟล์ ของจริง 10 · สองไฟล์ที่ขาดคือ meter-notes ที่อ้างพาธ `_cewe.py` ในเนื้อความ

**ปฏิเสธที่จะประกาศว่าผ่านเกณฑ์ที่ทำไม่ได้จริง** — Step 8 สั่งให้ `grep` ชื่อไฟล์เก่าแล้วต้องไม่เจอ แต่มีสองที่ที่สตริงนั้นอยู่ใน**ประโยคที่กำลังยกมาเล่าว่าของเดิมเขียนผิดไว้อย่างไร** ⇒ เลือกไม่ลบ แล้วยกให้ตัดสิน

---

## สองข้อที่ reviewer ประกาศว่าเป็นความผิดของตัวเอง

1. **รายการไฟล์ที่การเปลี่ยนชื่อกระทบ บอกว่า 8 ของจริง 10** — *"That is my Job A defect, not yours — the count valve is the only reason they surfaced, which is the **third batch running** where a list I asserted was complete was not."*
2. **เกณฑ์ `grep` ทำให้สำเร็จไม่ได้จริง** — *"The instruction was wrong, not your work — I wrote a `grep`-returns-nothing check for a change whose whole point is a document that must quote the old name."*

---

## Mutation probe

**15 probe อิสระ** (implementer 5 ตามที่ใบสั่ง + reviewer 10 ที่เล็งจุดที่ implementer ไม่ได้แตะ) · **แดงทุกตัว** · ยืนยันการคืนค่าด้วย SHA-256 manifest ไม่ใช่ `git status` · ไม่มีของค้างบนดิสก์

reviewer เล็งไปที่ base `CUMUL_DEMAND_COSEM_CLASS` · ลำดับ `BILL_DATE_CANDIDATES` · base billing OBIS · คลาสของกลุ่ม `D=6` · sibling ของ `volt_l1` และ `avg_geo_pf` · การถอด override ของ TCC สองตัว · `model_name` · และลำดับ `-l`/`-s` ใน argv

---

## ของที่ยังค้าง — เป็นข้อจำกัดที่รู้ตัว ไม่ใช่ข้อบกพร่อง

1. **ทั้งไดรเวอร์ไม่เคยเดินกับฮาร์ดแวร์เลย** — `203.170.148.103` timeout ทั้ง 4059 และ 50001 · เป็นเรื่องลิงก์ ไม่ใช่โค้ด · การยืนยันจริงเป็นส่วนหนึ่งของ exit ของ M4c
2. **สี่รุ่นที่ไม่เคยสแกน** (`st3c` `st33tl` `st3tl` `st3dh`) สมมติว่าเหมือน 3CL **เพราะ v1 ใช้ไดรเวอร์เดียวคุมทั้งห้า ไม่ใช่เพราะมีใครวัด** — เขียนไว้ใน docstring ของคลาสด้วยถ้อยคำนี้ ไม่ใช่แค่ในรายงาน
3. **ทางถอย `D=2 → D=6` ของ scaler ไม่เคยเดินภายใต้ `GXDLMSRegister`** — ถ้าเกิดเดินบนรุ่นนี้จะได้ `None` ไม่ใช่เลขผิด · จงใจไม่ขยาย เพราะการแก้โค้ดที่ไดรเวอร์สามตัวซึ่งยืนยันกับมิเตอร์จริงแล้วพึ่งอยู่ เพื่อเส้นทางบนมิเตอร์ที่ไม่มีใครเข้าถึงได้ ไม่ใช่การแลกที่คุ้ม
4. **nit ที่เหลือ** — `test_smart_tcc_replay.py:274` อ้าง `tcc-obis-scan.md:650` แต่ตัวจริงอยู่ `:651` (คลาดหนึ่งบรรทัด อยู่ในบล็อกเดียวกัน) · reviewer ตัดสินว่าไม่คุ้มอีกรอบ

---

## วิธีตรวจสอบหลักฐานเอง

```bash
D="$HOME/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents"
grep -o '"skill":"[a-zA-Z0-9:_-]*"' "$D/agent-a06eb045be4c67081.jsonl" | sort | uniq -c   # implementer
grep -o '"skill":"[a-zA-Z0-9:_-]*"' "$D/agent-a2bf159613d21d11c.jsonl" | sort | uniq -c   # reviewer
git show --stat 1d85cab
```

⚠️ **อย่าใช้ `output_file` ที่ tool คืนมา** — บนเครื่องนี้เป็น 0 ไบต์เสมอ · `sessionId` ในพาธคือของ session หลัก ไม่ใช่ UUID ของโฟลเดอร์ `tasks/`
