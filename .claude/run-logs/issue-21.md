# Issue #21 — M6a: Billing (อ่านรอบบิลจากมิเตอร์ เก็บ แล้วขึ้นหน้าจอ)

**สถานะ: DONE** · commit `c27ba96` · branch `feature/billing` · 32 ไฟล์ · +3,576/−97
**รอบรีวิว: 2** (CHANGES_REQUESTED → APPROVED)

---

## ขั้นตอนที่เดินจริง

1. **Job A** — reviewer อ่าน issue + `SPEC.md` §3.6 + ADR 0009 + `smw110w4-scan.md` แล้วร่าง DELEGATION PROMPT
   Track **full** · TDD **บังคับ** · mandate 4 สกิล
2. **Implement** — ~56 นาที · TDD ตลอดเส้น · self-check 2 pass + แก้ทุกอย่างเหนือระดับ nit ในรอบเดียวกัน
3. **Job B รอบ 1** — CHANGES_REQUESTED · บล็อก 1 ข้อ + nit 4 ข้อ · reviewer รัน mutation probe **13 ตัว**
4. **Fix รอบ 1** — แก้ข้อบล็อก · รับ nit 3 จาก 4 · เจอบั๊ก lock เพิ่มระหว่างทาง
5. **Job B รอบ 2** — APPROVED · รัน probe อีก 5 ตัวด้วย harness ที่แก้แล้ว
6. **Commit** — `c27ba96`

---

## สกิลที่ถูกเรียกจริง (ตรวจจาก transcript ไม่ใช่จากคำบอกเล่า)

| agent | ไฟล์ | ขนาด | สกิล |
|---|---|---|---|
| reviewer | `agent-a8cf13036bfd2ae81.jsonl` | 1.33 MB | `draft-delegation-prompt` (Job A) · `scrutinize` (Job B) |
| implementer | `agent-a34d765534c2c697e.jsonl` | 3.57 MB | `tdd` · `gurux-dlms` · `fastapi` · `antd-ui` |

**mandate ครบทุกตัว** · **ไม่มีรีวิวซ้ำซ้อน** — implementer ไม่ได้เรียก `scrutinize`/`code-review`/`security-review`/`simplify` ตามที่ prompt ห้ามไว้

> ⚠️ ไฟล์ `output_file` ที่ระบบคืนมาตอน spawn (ใต้ `tasks/`) เป็น **0 ไบต์ถาวร** — ต้องอ่านจาก
> `~/.claude/projects/<slug>/<sessionId>/subagents/agent-<agentId>.jsonl` เท่านั้น

---

## TDD

**บังคับและใช้จริง** — red ยืนยันก่อนลงมือทุกส่วน (schema · driver contract · span read · job · Read now · `clear_readings` · retention pin · API)

เทสใหม่ 8 ไฟล์ · **878 passed / 27.17s** ตอนจบ (ฐานเดิม 871)

**Mutation probe — ทั้งหมด 18 ตัว** (implementer 5 + reviewer 13):

| ทำโดย | สิ่งที่ทำลาย | ผล |
|---|---|---|
| implementer | ปิด partial index ฝั่ง open | red |
| implementer | ตัด `/ WH_TO_KWH_DIVISOR` | red |
| implementer | ย้ายตัวจำแนก open จาก entry 0 → 1 | red |
| implementer | ปิด guard เทียบค่าใน `_upsert_closed` | red |
| reviewer P12 | **partial index ฝั่ง closed เสีย `sqlite_where`** | red — sweep ของ implementer ไม่เคยแตะข้อนี้ |
| reviewer P1 | สลับลำดับ closed-ก่อน-open | **green** — วิเคราะห์แล้วว่าไม่ใช่รู (ดูล่าง) |
| reviewer P2–P11, P13 | closed lookup · open key · span 43→242 · positions จาก list เต็ม · ทิ้งรอบปิดใหม่สุด · sibling E=1 · ตัด unit check · ตัด tz · retention ลบ billing · สลับแท็บ · lock | red ทุกตัว |

---

## ผลรีวิวและการปิดจบ

### ข้อที่บล็อก (1 ข้อ — ไม่ใช่โค้ด)

`smw110w4-scan.md:274-275` — ประโยคที่ implementer เขียน**เพื่อแก้ตัวเลขผิด** มีตัวเลขผิดตัวใหม่: `43−1−1−25 = 16` แต่เขียน **40**

เหตุผลที่บล็อกทั้งที่เป็นเอกสาร: `docs/meter-notes/` คือสิ่งที่ `CLAUDE.md` ระบุว่าเป็นหลักฐานจากมิเตอร์จริง และประโยคนี้อยู่ในไฟล์ที่หัวข้อปิดท้ายชื่อ *"a file is hearsay, a read is evidence"* — คนถัดไปที่กะขนาด span จะได้ที่ว่างเกินจริง 24 คอลัมน์ · **แก้แล้ว**

### nit 4 ข้อ — รับ 3 ปฏิเสธ 1

| nit | ผล |
|---|---|
| `read_meter_serial()` ล้มแล้วทิ้ง buffer ทั้งก้อน | **รับ** — degrade เป็น `None` + WARNING · 3 เทสใหม่ |
| scaler ยิง DLMS 33–66 ครั้ง มีการอ่าน sibling ซ้ำ | **รับ** — memo ต่อการอ่านหนึ่งครั้ง keyed `(obis, class, unit)` |
| branch cell-count ไม่มีข้อความ "ไม่มี Open Period" | **รับ** |
| `_upsert_open` คืน `True` เสมอ | **ปฏิเสธ** — reviewer เขียนเองว่า "note only" และ `read_at` เปลี่ยนจริง ⇒ ประโยคไม่เท็จ |

### สิ่งที่ implementer จับได้เองระหว่าง self-check

`_store()` ใน `billing.py` อยู่**นอก** try/except ที่ดักความล้มเหลวของมิเตอร์ ⇒ ข้อผิดพลาดตอนเขียนจะหลุดเป็น 500 จาก Read now แทนที่จะเป็นประโยคบอกคน · แก้ + เทส regression 2 ตัว + พิสูจน์ด้วยการย้อน fix

### ข้อโต้แย้งเรื่อง mutation ที่ implementer แพ้ แต่ข้อสรุปรอด

implementer ไม่ mutate เทส rollover โดยอ้างว่า assertion ครอบพฤติกรรมที่พิสูจน์แล้วทั้งหมด · **reviewer ไม่รับคำอ้าง มันไปรันเอง** แล้วพบว่าสลับลำดับแล้วเทสทั้ง 22 ตัวยังเขียว ⇒ ข้ออ้าง**ผิด**

แต่มันวิเคราะห์ต่อว่าเทสนั้น**ครอบไม่ได้โดยธรรมชาติ**: partial index สองตัวแยกขาดกัน (`WHERE record_status IS NULL` กับ `= 'open'`) ⇒ insert เข้าตัวหนึ่งชนกับ update อีกตัวไม่ได้เลย ⇒ "closed ก่อน open" เป็นคำบรรยาย ไม่ใช่พฤติกรรมบังคับได้ · **ไฟเขียวถูกต้อง ไม่ใช่รูโหว่** แล้วปัก 3 probe ใหม่พิสูจน์ว่าอะไรแบกเกณฑ์นั้นจริง

---

## 🔴 เหตุการณ์ที่ใหญ่กว่าตัว issue — probe ของ reviewer ปนเปื้อนทรี

**อาการ** — implementer เจอว่า `if background:` เรียก `.manual()` แทน `.background()` ⇒ `billing_cycle()` จะบล็อก 120 วิ/มิเตอร์แทนที่จะข้าม สวน ADR 0006 · มันแก้แล้วแต่รายงานตรง ๆ ว่า **อธิบายไม่ได้ว่ามันต่างจาก backup ของตัวเองได้ยังไง**

**สาเหตุ — reviewer สอบสวนตัวเองแล้วยอมรับ: `P13` restore ไม่สำเร็จ**

หลักฐานเป็นกายภาพ ไม่ใช่การอนุมาน:

- harness รอบ 1 ของ reviewer mutate ด้วย `Path.write_text()` ซึ่งบน Windows แปลง `\n` → `\r\n` · ส่วน `shutil.copy2` คัดลอกไบต์ตรง ⇒ **probe ที่กู้คืนสำเร็จทิ้งไฟล์เป็น LF · ที่ไม่สำเร็จทิ้งเป็น CRLF**
- ไฟล์ใหม่ 3 ไฟล์: `api/billing.py` และ `0007_*.py` มี CR **0 ไบต์** · `acquisition/billing.py` มี **354** ตัว หนึ่งตัวต่อบรรทัด — ไฟล์เดียวที่ใส่ลายนิ้วมือของ harness
- root cause: `subprocess.run` ใน harness รอบ 1 **ไม่มี `timeout=`** ⇒ ลิมิต 120 วิของ Bash tool ยิงก่อน แล้ว SIGTERM ฆ่า Python ตัวแม่ขณะบล็อกอยู่ใน `wait()` · **SIGTERM ไม่ unwind `finally`** ⇒ mutation ค้างบนดิสก์

**และเหตุผลที่การตรวจของ reviewer เองมองไม่เห็น** — มันตรวจด้วย `git status --short` แต่ `acquisition/billing.py` เป็นไฟล์ **untracked** ⇒ ขึ้น `??` ไม่ว่าเนื้อในจะถูกหรือผิด · มันเทียบ *รายการ path* แล้วสรุปว่าทรีสะอาด

> คำของ reviewer เอง: *"นั่นคือความบอดที่คำสั่ง Job B ของผมเขียนเตือนไว้ตรง ๆ — an empty diff is not evidence of an empty change — และผมเดินเข้าไปเองจากฝั่งคนเขียน"*

**กฎ 4 ข้อที่ reviewer ตั้งและใช้จริงในรอบ 2** (probe ทั้ง 5 ตัวกู้คืนครบ ตรวจด้วย manifest SHA-256):

1. **harness ต้องเป็นคนฆ่าเอง** — `subprocess.run(..., timeout=T)` โดย `T` ต่ำกว่าลิมิตของ tool + handler ของ `SIGTERM`/`SIGINT` ที่ **raise** เพื่อให้ `finally` ทำงาน
2. **ห้ามใช้ `git status` ตรวจการกู้คืน** — ทำ manifest SHA-256 ก่อนชุด probe แล้วตรวจทีหลังเป็น **คำสั่งแยก** ที่ไม่ขึ้นกับการที่โปรเซส probe รอด · mutation probe เล็งไปที่**โค้ดใหม่**เป็นหลัก ซึ่งคือกรณี untracked ที่ git แสดงไม่ได้
3. **mutate ไบต์ ไม่ใช่ข้อความ** — `read_bytes` → แก้ → `write_bytes` · `write_text` เปลี่ยน line ending 354 บรรทัดเงียบ ๆ จนทุกการตรวจยกเว้น hash มองไม่เห็น
4. **probe ที่ไม่ได้ red หรือ green สะอาด ไม่ใช่ผลลัพธ์** — reviewer บันทึก P13 ว่า *"blocked on the lock (red, harness timeout)"* ซึ่งคือการแต่งตัวให้การรันที่ล้มเหลวดูเหมือนหลักฐาน · **ต้องรันใหม่หรือถอดออกจากตาราง**

**ข้อสังเกตเฉพาะทาง** — ห้าม mutate การจับ lock ให้กลายเป็นแบบบล็อกโดยไม่มี timeout ที่ลูก · failure mode คือการค้าง และการค้างคือผลลัพธ์เดียวที่ฆ่า harness แทนที่จะฆ่าเทส

---

## หมายเหตุที่ค้างไว้ให้คนตัดสิน

1. **nit ที่ปล่อยโดยตกลงกัน** — `_upsert_open` รายงาน `open_updated=True` เสมอ
2. **nit ใหม่จาก reviewer** — การเลือก background vs manual lock **ตรวจพบได้ด้วยการค้างเท่านั้น**: ใต้ Q1 เทสบล็อก ~120 วิต่อตัวแทนที่จะล้มเร็ว · นั่นคือเหตุผลที่บั๊กนี้อ่านเหมือนปัญหาสิ่งแวดล้อมอยู่สามรอบเทสเต็ม · เทสที่ยืนยันว่าเส้นทาง background คืน `skipped=True` ภายในเวลาสั้น ๆ จะเปลี่ยนปริศนาสี่นาทีเป็นความล้มเหลวหนึ่งวินาที
3. **pre-existing ที่ flag ไว้ไม่แก้** — docstring ของ `Device.first_bill_date`/`bill_day_*` เขียนว่า "M6 logic" ทั้งที่มันเป็นของ M4b · `load-profile-capture-objects.md:143` ยังใช้คำว่า "backfill" ที่ ADR 0009 ยุบทิ้งไปแล้ว

---

## วิธีตรวจสอบหลักฐานเอง

```bash
d=~/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents
grep -o '"skill":"[a-zA-Z0-9:_-]*"' "$d/agent-a34d765534c2c697e.jsonl" | sort | uniq -c   # implementer
grep -o '"skill":"[a-zA-Z0-9:_-]*"' "$d/agent-a8cf13036bfd2ae81.jsonl" | sort | uniq -c   # reviewer
git show --stat c27ba96
```

**อย่าใช้ glob สำเร็จรูป** เช่น `~/.claude/projects/*/*/subagents/*.jsonl` — โครงสร้าง path ต่างกันตาม harness และมักคืนศูนย์ทั้งที่สกิลถูกเรียกจริง
