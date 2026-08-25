# Audit log — Issue #46: Database Destination — sync Load Profile และ Billing เข้า MariaDB ของลูกค้า (ADR 0020, 0021)

รัน: 2026-08-25 · branch: `feature/light-modules` · ผลลัพธ์: **APPROVED** · รอบรีวิว: **2**
เกิดจากของหลุด: ไม่ใช่ งานใหม่ — เป็นการรวม draft #46 (config) กับ #47 (sync) เข้าด้วยกันตามที่เจ้าของสั่ง หลังผมรายงานผิดว่าเครื่องนี้ไม่มี MySQL

## ทำอะไรไปบ้าง (ทีละขั้น)

### 0. orchestrator — ตรวจก่อนเริ่ม
- label `ready-for-agent` · skill ของ repo (`fastapi`, `antd-ui`, `gurux-dlms`) เข้าถึงได้จาก session นี้
- **ตรวจ MariaDB เองก่อนจ่ายงาน** — `10.4.32-MariaDB`, `arichds_dest` มีอยู่, `@@sql_mode` ไม่มี `STRICT_TRANS_TABLES` (ตรงกับที่ issue เขียน)
- **เจอสองอย่างที่ตัว issue เขียนไว้ผิด/เก่า แล้วส่งต่อให้ reviewer:**
  - `arichds_dest` **ไม่ว่าง** — มีตารางจาก probe ค้าง `load_profile_readings` 60,379 แถว + `billing_readings` 28 แถว **ใต้ชื่อตารางเดียวกับที่โค้ดจริงจะสร้าง** ⇒ เกณฑ์ข้อแรก ("สร้างสองตารางบน destination ที่ยังไม่มีตาราง") ทดสอบกับสภาพปัจจุบันไม่ได้
  - baseline เทสใน issue เขียน 1613 ซึ่งเก่ากว่าความจริง (#43/#44/#45 ลงไปแล้ว) → **1690**

### 1. reviewer (Job A) — สร้าง prompt (`/draft-delegation-prompt`)
- **Track: full** — endpoint ใหม่ 3 ตัว, job ใหม่บน scheduler, DDL ยิงเข้า database engine อื่น, `DELETE` ในฐานข้อมูลของคนอื่น, เลขคณิต timezone ที่พังแบบเงียบ, และ licence gating
- **TDD required: yes** — เกือบทุกการตัดสินใจเป็น branch ที่มี edge case
- **Workflow discipline** ระบุครบ: `fastapi` (Step 2), `antd-ui` (Step 6), และระบุชัดว่า `gurux-dlms` ไม่เกี่ยว เพื่อไม่ให้การไม่เรียกอ่านเป็นความพลาด
- **reviewer จับ citation ของ issue ผิดเอง 3 จุด** ด้วยการเปิดไฟล์จริง: `constants.py:236`→`:247-259` · `constants.py:191`→`:202` · `scheduler.py:236-254`→`:349-367` (ที่อ้างเดิมอยู่ข้างใน `_run` คนละเรื่องกัน)
- ใส่ **valve** ตามที่ orchestrator สั่ง — บทเรียนตรงจาก #45 ที่โจทย์ปิดรายการไว้แล้วกลบบั๊กจริง
- ใส่ **mutation table 30 แถว** เป็นข้อบังคับ แทน scenario list

### 2. implementer — ลงมือ + ตรวจตัวเอง (`/tdd` + `fastapi` + `antd-ui`)
- ไฟล์ที่เปลี่ยน: 13 แก้ + package ใหม่ `dataout/` (`__init__`, `destination`, `schema`, `status`, `sync` — 1,344 บรรทัด) + เทสใหม่ 4 ไฟล์ (1,960 บรรทัด) · tracked diff 855 insertions / 73 deletions
- **self-check เจอเหนือ nit 2 ข้อ แก้เอง:**
  1. purge ถูก budget ที่หมดแล้วอดตาย — เช็ค budget *ก่อน* batch แรก ⇒ backfill ยาวๆ ทำให้ Mirror Window เลื่อน ซึ่ง ADR 0020 ห้าม · แก้เป็นรัน batch แรกก่อน
  2. billing budget check `return` ออกจาก cycle ทั้งอัน ⇒ budget 0 ข้ามทั้ง append และ purge
- **mutation 39 แถว — 3 แถวกลับมาเขียว และเป็นเทสบกพร่องจริงที่แก้แล้ว** (ดูหัวข้อ "ของที่จับได้เพราะ mutation" ข้างล่าง)
- **ใช้ valve จริง — รายงานกลับ 3 ข้อแทนที่จะเลี่ยงเงียบๆ:**
  1. **ดีไซน์ Step 3 ของ reviewer มีบั๊ก** — SQLAlchemy เขียน `UniqueConstraint` ไว้ใน `CREATE TABLE` แต่ส่ง `Index` ธรรมดาเป็น statement แยก ⇒ ตารางปลายทาง**ไม่มี secondary index เลย** ทั้งที่เทสฝั่ง Python ผ่าน · จับได้ด้วย `SHOW CREATE TABLE` เท่านั้น
  2. PyMySQL คืน error **2003 สำหรับ host ที่ resolve ไม่ได้** ไม่ใช่ 2005 ตามที่โจทย์บอก
  3. `pymysql.__version__` คืน `2.2.8` ซึ่งเป็นเวอร์ชัน *client protocol* ไม่ใช่แพ็กเกจ (1.2.0)
- ผลรันเทสต์: **1764 passed, 57 skipped in 66.16s** (จาก baseline 1690/17) · ruff สะอาด · `pnpm lint`/`build` สะอาด · integration **40 passed** เมื่อตั้ง `ARICHDS_TEST_MYSQL_URL` และ **40 skipped** เมื่อไม่ตั้ง — รันจริงทั้งสองทาง ไม่ใช่ผลที่ cache ไว้

### 3. reviewer (Job B) — รีวิว (`/scrutinize`)
- verdict: **CHANGES_REQUESTED** — 1 major, 1 minor, 3 nit
- **major** — `POST …/test` ตอบ `ok / Connected.` ให้ destination ที่ยังไม่ได้ตั้งค่า PyMySQL แปลง host ว่างเป็น `localhost` เงียบๆ และบนเครื่องลูกค้าซึ่งรัน XAMPP อยู่บนเครื่องเดียวกัน `root` ไม่มีรหัส **มันต่อติดจริง** · ทางที่ผู้ใช้เดินเข้าไปเจอคือทางปกติที่สุด: กรอกฟอร์ม → กด Test ก่อน Save → endpoint อ่านค่าที่ *บันทึกไว้* ตามดีไซน์ จึงเทสค่าว่าง → เขียว → sync ไม่เคยรัน และการ์ดสถานะขึ้นว่า "ยังไม่มี sync" ซึ่งอ่านเหมือน "ยังไม่ถึงรอบ"
- **minor** — `CLAUDE.md:296-297` ใน section **Invariants** ระบุว่า "Data leaves the box via the push sync module only" ซึ่งงานนี้ทำให้เป็นเท็จ · บรรทัดนี้เท่ากับบอกว่า `dataout/` ไม่ควรมีอยู่ · staleness sweep ของ implementer ละเอียดแต่ยึดกับ *สตริงที่ถูกลบ/เปลี่ยนชื่อ* จึงมองข้ามร้อยแก้วที่กลายเป็นเท็จ
- nit: purge ค้างเมื่อปิด feature `load_profile` · `COUNT(*)` ทั้งตารางทุก cycle เพื่อ log ที่แทบไม่เคยยิง · คอมเมนต์ `NOT NULL` เคลมเกินจริงไปหนึ่งวรรค
- **reviewer ตรวจเองไม่ใช่เชื่อรายงาน** — รัน integration ซ้ำทั้งสองทาง · อ่าน DDL ที่ลงจริงด้วย client ของ XAMPP **นอก Python** · รัน **mutation ของตัวเอง 12 ตัวบนเป้านอกลิสต์ 39 ตัว** (แดง 11 เขียว 1 ซึ่งเขียวถูกต้อง) · ยิง 6000 แถวทดสอบ `@@max_allowed_packet` ที่ 1 MB พอดี

**ควรถูกจับที่ด่านไหน (ต่อ problem):**
- major (`/test` ตอบ ok ทั้งที่ไม่ได้ตั้งค่า) — **โจทย์ Job A** · reviewer ยอมรับเองว่า Step 4 ตัดสิน "ไม่ได้ตั้งค่า → ออกทันที" ไว้กับ *ตัว cycle* แล้วไม่ได้ลากมาถึง endpoint · และ **เกณฑ์รับงานของ issue ระบุ 5 outcome ซึ่งไม่มีข้อนี้อยู่เลย** — ด่านที่ควรจับคือตอนเขียน issue
- minor (invariant ใน CLAUDE.md) — **self-check ของ implementer** · sweep ของมันยึดสตริงที่ถูกลบ/เปลี่ยนชื่อ ซึ่งจับ "ร้อยแก้วที่ยังอยู่แต่กลายเป็นเท็จ" ไม่ได้ตามนิยาม
- nit 3–5 — **ไม่มี** · Job B เท่านั้นที่จับได้
- **บั๊ก index หาย** — จับได้ที่ implementer เอง (ผ่าน valve) · ด่านที่ควรจับคือ Job A ตอนออกแบบ Step 3

### 4. รอบแก้ (1 รอบ)
- orchestrator ส่ง problems **verbatim** ตรงให้ implementer เดิม (ไม่ผ่าน Job A ซ้ำ)
- implementer **ตายกลางทางเพราะชนลิมิต session** ตอนกำลังตรวจงานตัวเองหลังแก้เสร็จ · orchestrator ตรวจ tree แล้วพบว่าโค้ดลงครบ ไม่ค้างกลางการแก้ (ruff สะอาด, เทส dataout 79 ผ่าน) → **resume ตัวเดิม ไม่ spawn ใหม่** หลังลิมิตรีเซ็ต
- **implementer พบว่าบั๊กที่ reviewer เจอ กว้างกว่าที่ reviewer รายงาน** — `database` ว่างก็ขึ้นเขียวเหมือนกัน เพราะ PyMySQL ต่อติดโดยไม่เลือก schema ⇒ guard ครอบทั้งสองช่อง + ค่าที่มีแต่ช่องว่าง · **ถ้าทำตามที่ reviewer เขียนเป๊ะ จะได้การแก้แค่ครึ่งเดียว**
- **staleness sweep ของตัวการแก้เอง เจออีก 2 รู:**
  1. เทสวนลูปบน tuple **5 ตัวที่เขียนมือ** ⇒ เพิ่ม outcome ที่ 6 แล้วเทสยังผ่าน เพราะเทสแค่ 5/6 เงียบๆ · แก้โดยให้ derive จาก `get_args(ConnectionResult)` + `assert len == 6` **จึงเก่าซ้ำไม่ได้**
  2. docstring ของ `classify_connect_error` **หลวมอยู่ก่อนรอบนี้แล้ว** — เขียนว่าคืน "หนึ่งในห้า" ทั้งที่คืนแค่สาม
- กับดัก "กด Test ก่อน Save" แก้ทั้งสองทาง: เปลี่ยนชื่อปุ่มเป็น **Test saved connection** + ปิดปุ่มเมื่อฟอร์มยังไม่บันทึก + ล้างผลเก่าเมื่อแก้ฟอร์ม (กันเครื่องหมายถูกเขียวค้างใต้ฟอร์มที่เปลี่ยนแล้ว)
- nit ทั้ง 3 ทำครบ ไม่ข้ามข้อไหน
- **mutation รวม 40 แถว แดงหมด** — รันซ้ำ 24 แถวที่โค้ดขยับจริง และ**พิสูจน์ด้วย diff** ว่าอีก 16 แถวโค้ดไม่ขยับหรือขยับแต่คอมเมนต์ แทนที่จะเคลมเฉยๆ
- gate หลังแก้: **1771 passed, 57 skipped in 70.42s** · ruff/eslint/build สะอาด

### 5. reviewer (Job B รอบ 2) — **APPROVED**
- ยิง 9 เคสจริงผ่าน `check_destination_connection` — 5 เคสที่ไม่ได้ตั้งค่าคืน `not_configured` ครบ และ **4 outcome เดิมไม่ถูกกระทบ** (ok / database_missing / auth_failed / unreachable)
- **รัน mutation ของตัวเองอีก 4 ตัว แดงหมด** รวมถึงตัวที่สำคัญที่สุด: **บีบ guard ให้เหลือแค่ host** ซึ่งคือจุดบอดของ reviewer เอง — ตอนนี้ทำให้เทสแดง **จึงถอยกลับไปเป็นสิ่งที่ reviewer สั่งตอนแรกไม่ได้อีก**
- reviewer บันทึกความผิดตัวเองไว้ตรงๆ: *"ผมตั้งชื่อเคส host ว่างเพราะเป็นเคสที่ผมทำซ้ำได้ แล้วเดาเอาเรื่อง default ของ PyMySQL โดยไม่ตรวจว่า database มีสมบัติเดียวกันไหม · มันมี · โจทย์ที่ผมเขียนจะอนุญาตให้แก้แค่ครึ่งเดียว"*

## ของที่จับได้เพราะ mutation ไม่ใช่เพราะเทสผ่าน

3 แถวที่กลับมาเขียวรอบแรก และเป็นเทสบกพร่องจริง:
- **แถว 26** — assert `max(seen) <= DBDEST_ROW_CHUNK` โดยใช้ค่าคงที่ที่ **import มา (5000)** ขณะที่เทส patch โมดูลเป็น 10 ⇒ `30 <= 5000` ผ่านทั้งที่ลบ `LIMIT` ออกแล้ว · นี่คือรูปแบบ "จริงแต่ไม่แยกแยะ" เป๊ะๆ
- **แถว 11** — `group_by(meter_serial)` ทำให้ logger ตัวที่สอง**ไม่มี watermark เลย** จึง backfill ใหม่ทั้งหมดแล้วจำนวนแถวดันตรง · เปลี่ยน mutation เป็น "ยุบเป็น MAX ข้าม logger" ให้ซื่อตรง
- **แถว 14** — anchor พลาดหลัง `ruff format` ตัดบรรทัด f-string ใหม่

## ต้นทุน (เวลา + output tokens ต่อสเตจ)

| สเตจ | เวลา | tool calls | tokens (ดูหมายเหตุ) |
|---|---|---|---|
| reviewer Job A | 10.0 นาที | 50 | 160,543 |
| implementer (build) | 49.3 นาที | 192 | 377,936 |
| reviewer Job B | 11.3 นาที | 28 | 268,946 |
| รอบแก้ 1 — implementer | 5.7 นาที (+ ตายเพราะลิมิต แล้ว resume) | 239 | 390,973 |
| รอบแก้ 1 — reviewer Job B | 5.1 นาที | 11 | 294,628 |
| **รวมเวลา agent** | **~81 นาที** | **520** | — |

**หมายเหตุ tokens:** ตัวเลขที่ harness รายงานเป็น `subagent_tokens` **บวกกันตรงๆ ไม่ได้** — มัน double-count ข้าม SendMessage resume (บันทึกไว้ใน memory `subagent-token-counts-are-not-additive`) แถวรอบแก้จึงเป็นยอดสะสมของ agent ตัวนั้น ไม่ใช่ส่วนเพิ่ม · ยอดรวมจริงต้อง grep `output_tokens` จาก transcript ซึ่งรอบนี้ไม่ได้ทำ

## ✅ skill ที่เรียกจริง — ยืนยันจาก transcript (tamper-proof)

```
=== IMPLEMENTER (2.4M) ===
      1 "skill":"antd-ui"
      1 "skill":"fastapi"
      1 "skill":"tdd"
Skill calls: 3          docs-researcher spawns: 0

=== REVIEWER (1.4M) ===
      1 "skill":"draft-delegation-prompt"
      1 "skill":"scrutinize"
Skill calls: 2          docs-researcher spawns: 0
```

**สะอาดทุกด้าน:** implementer เรียกครบทั้ง 3 สกิลที่โจทย์บังคับ และ **ไม่ได้เรียก `scrutinize`/`code-review` รีวิวงานตัวเอง** ซึ่งเป็นของแพงที่สุดที่ pipeline นี้ทำซ้ำได้ · reviewer เรียก `draft-delegation-prompt` (Job A) + `scrutinize` (Job B) อย่างละครั้ง ไม่ซ้อนสกิลรีวิวตัวที่สอง · ไม่มีใคร spawn `docs-researcher` เลย — ถูกต้อง เพราะ repo pin PyMySQL/SQLAlchemy ไว้เองอยู่แล้ว

**หมายเหตุเรื่อง path:** `output_file` ที่ตัว spawn คืนมา (ใต้ `tasks/`) เป็น **0 ไบต์ตลอดกาล** ต้องใช้ JSONL จริงใต้ `projects/…/subagents/agent-<id>.jsonl` (ตรงกับ memory `subagent-transcripts-often-empty`) · ถ้า grep ที่ path แรกจะได้ "0 skills" ทั้งที่เรียกครบ

## Commit

`8d28779` — **feat: sync Load Profile and Billing into the customer's database (#46)** ·
22 ไฟล์ 4,159 insertions / 73 deletions · เจ้าของสั่ง commit หลังรีวิวผ่าน 2026-08-25

`docs/issues/008-*.md` (เทส PDF ที่แกว่ง) แยก commit ต่างหาก เพราะเป็นข้อบกพร่องคนละเรื่อง
ที่บังเอิญเจอระหว่างทาง ไม่ใช่ส่วนหนึ่งของ #46 · ยังไม่ push

## nit ที่ reviewer ไม่บล็อก แต่ควรตัดสินก่อน merge

1. **ข้อความ + สีของ `not_configured`** — *"No host and database is saved yet"* ควรเป็น *"or"* เมื่อว่างทั้งคู่ · และหน้าเพจ render ทุก outcome ที่ไม่ใช่ `ok` เป็น `type="error"` สีแดง ทั้งที่ `not_configured` เป็นการ *เตือนให้ทำต่อ* ไม่ใช่ความผิดพลาด — `warning` เหมาะกว่า
2. **ปุ่ม Refresh ล้างสิ่งที่ยังไม่บันทึกทิ้งเงียบๆ** — Refresh บนการ์ด Last sync เรียก `load()` → `apply()` ซึ่งเขียนทับฟอร์มด้วยค่าที่เก็บไว้ · คนที่พิมพ์ host ใหม่แล้วกด Refresh เพื่อดูสถานะ sync จะเสียสิ่งที่พิมพ์ไปโดยไม่มีคำเตือน · **มาตั้งแต่รอบแรกของ diff นี้ ไม่ใช่ของใหม่จากรอบแก้** · ทางแก้: gate `load()` ด้วย `dirty` หรือแยก Refresh เป็นการดึงเฉพาะสถานะ

## วิธีตรวจซ้ำด้วยตัวเอง (audit)

หลักฐานจริงอยู่ใน subagent transcript — **ใช้ path จริงใต้ `subagents/` ไม่ใช่ `output_file` ที่ spawn คืนมา**:

    d="C:/Users/HP/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents"
    grep -o '"skill":"[a-z0-9:_-]*"' "$d/agent-aed99190679ec93f3.jsonl" | sort | uniq -c   # implementer
    grep -o '"skill":"[a-z0-9:_-]*"' "$d/agent-aede2adc6529650ba.jsonl" | sort | uniq -c   # reviewer
    grep -c '"name":"Skill"' "$d/agent-aed99190679ec93f3.jsonl"
