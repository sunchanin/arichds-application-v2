# Issue #15 — M5a-1: Read now stores load profile as Interval Readings

**สถานะ: DONE** · commit `f49cdfa` · branch `feature/load-profile` · รอบรีวิว **1** (APPROVED ทันที)

---

## ขั้นตอนที่เดินจริง

| ขั้น | agent | เวลา | token |
|---|---|---|---|
| Job A — ร่าง delegation prompt | reviewer | ~14.7 นาที | 154k |
| Implement | implementer | ~32.6 นาที | 270k |
| Job B — review + mutation probe | reviewer (ตัวเดิม, ต่อด้วย SendMessage) | ~9.5 นาที | 245k |

**Track: full** · ไฟล์ที่เปลี่ยน 19 ไฟล์ (แก้ 15 · ใหม่ 4)

---

## สกิลที่ถูกเรียกจริง — ยืนยันจาก transcript ไม่ใช่จากคำกล่าวอ้าง

| agent | สกิล | จำนวนครั้ง |
|---|---|---|
| reviewer (Job A + Job B) | `draft-delegation-prompt` | 1 |
| implementer | `tdd` · `gurux-dlms` · `fastapi` | อย่างละ 1 |

**คำกล่าวอ้างตรงกับ transcript ทุกข้อ** — ต่างจากแบตช์ #9–#10 ที่ subagent 3 ใน 4 ตัวอ้างสกิลที่ transcript ไม่มี นี่คือผลของการเปลี่ยนถ้อยคำใน `agents/*.md` เป็น *"invoke it — actually call it, do not reproduce its structure from memory"*

**ไม่มี review pass ซ้ำซ้อน** — implementer ไม่ได้เรียก `scrutinize` หรือ `code-review` ตามที่ห้ามไว้

หมายเหตุ: grep บน `output_file` ที่ระบบคืนมาได้ 0 ไบต์ตามปกติ · transcript จริงอยู่ที่
`~/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/<sessionId>/subagents/agent-<agentId>.jsonl`

---

## TDD

**ใช้ · ถูกบังคับใน delegation prompt · มีหลักฐาน red จริงครบทุกรอบ**

| รอบ | red | green |
|---|---|---|
| 1 — migration 0006 | 8 failed, 3 passed | 11 passed |
| 2 — capability + `logger_id`/`interval_sec` | 8 failed, 25 passed | 33 passed |
| 3 — the job | collection error → แล้วเจอบั๊กจริง (ด้านล่าง) | 17 → 20 passed |
| 4 — `read_now` | 5 failed, 5 passed | green |

**บั๊กจริงที่ TDD จับได้ระหว่างทาง** — chunk ที่ commit แล้วถูกนับเป็น 0 เพราะ exception unwind ผ่าน `_walk` ไป โดยที่ `through` ยังชี้ว่าข้อมูลลงตารางแล้ว แก้ด้วยการให้ `_walk` คืน error แทนที่จะ raise

**Baseline 659 passed → final 706 passed** (เพิ่ม 47 เทส) · `pytest -n auto` 37.10s · `ruff format --check` + `ruff check` ผ่าน

---

## Mutation probe — สิ่งที่ tune รอบล่าสุดเพิ่มเข้ามา

**implementer รัน 3 ครั้ง** (delegation prompt ระบุการกลายพันธุ์ให้ตรง ๆ):

| กลายพันธุ์ | ผล |
|---|---|
| `_walk` เดิน chunk จากใหม่ไปเก่า | 6 failed นำโดย `test_the_windows_ascend_and_start_at_the_watermark` |
| `_watermark` ใช้ `MAX` ระดับ device แทน `MIN` ของ per-logger maxima | 1 failed พอดี — `test_two_loggers_start_at_the_lagging_one` |
| `logger_id = 1` จากลำดับการค้นพบ | 1 failed พอดี — `test_every_row_carries_the_id_of_the_profile_that_was_read` |

**reviewer รันของตัวเองอีก 10 ครั้ง บน 9 เป้าหมายที่ไม่ซ้ำกับข้างบน** — upsert, unique constraint, per-chunk commit, watermark อ่านย้อนจากตาราง, budget (ทั้งแบบไม่เคยยิงและแบบยิงตั้งแต่ chunk แรก), server default, downgrade, device status · **revert จาก backup ในสแครชแพด ไม่ใช้ `git checkout --`**

---

## สิ่งที่ pre-flight และ review จับได้

**1. ใบ issue เองผิด — Job A จับได้ก่อนเริ่มเขียนโค้ด**
ใบ #15 เขียนว่า raw buffer ใน `docs/meter-notes/raw/` มี *"a full 24-hour window from each unit"* — **ไม่จริง** ชุดที่ต่อเนื่องยาวที่สุดคือ 24 แถว/6 ชั่วโมงต่อเครื่อง และพิมพ์แบบย่อ ("... 18 more ...") ส่วนความพยายามอ่าน 24 ชั่วโมงครั้งเดียวที่มีบันทึกไว้ **ล้มเหลว** ด้วย `Read-Write denied` เพราะมิเตอร์รุ่นนี้รับเฉพาะ entry access
→ สั่งให้ implementer ยึด `ANCHOR_ROW` ที่บันทึกไว้จริง แล้ว **สังเคราะห์** ช่วงที่ยาวกว่าโดยติดป้ายว่าสังเคราะห์ · บันทึกการแก้ความเชื่อนี้ไว้ใน docstring ของ `test_load_profile_job.py` เพื่อไม่ให้คนอ่านคนถัดไปเชื่อผิดซ้ำ

**2. Job A ยอมรับความผิดของตัวเองบนบันทึก**
Job A เขียนว่า "นี่คือรายการเทสเดิมที่จะพังทั้งหมด ผม grep แล้ว" — **ไม่ครบ** มีตัวที่หก (`test_migration_0005.py::TestDowngrade::test_the_deleted_rows_do_not_come_back` ที่ assert `SELECT interval` ด้วย raw SQL ใน fixture ที่วิ่งถึง head) grep ของมันครอบเฉพาะจุดสร้าง `LoadProfileReading(` กับ assertion บนคอลัมน์ ไม่ครอบ raw SQL
→ ตัวที่จับได้คือ **วาล์วที่มันเขียนไว้เอง**: *"if you find a sixth, say so in your report"* · Job B บันทึกไว้ว่า "วาล์วทำงาน แต่ sweep ควรจับได้ตั้งแต่แรก"

**3. implementer รายงานอุบัติเหตุของตัวเองแทนที่จะกลบ**
ตอน revert mutation ที่ 3 มันใช้ `git checkout -- smw110.py` ซึ่ง **ล้างงานจริงของไฟล์นั้นไปด้วย** มันทำใหม่ทั้ง 5 จุดแล้วรันเทสซ้ำ (61 passed) และรายงานเรื่องนี้ตรง ๆ
→ Job B ตรวจซ้ำตามที่สั่ง: `git diff` ของ `smw110.py` มีครบทั้ง 5 จุดพอดี ไม่มีการลบนอกฮังก์ **ไม่มีงานหาย**

**4. เทสที่ถูกเขียนใหม่ ยังแยกแยะได้จริงหรือไม่**
implementer ย้าย assertion ของเทส downgrade จาก `interval` ไป `volt_l1` (จำเป็น เพราะ 0006 ทิ้งคอลัมน์ label แบบกู้คืนไม่ได้) · Job B ไม่เชื่อคำกล่าวอ้าง แต่รัน mutation ที่ทำให้ `downgrade()` แทรกแถว 60 วินาทีกลับมาที่ `read_at` คนละค่า — ซึ่งคือความล้มเหลวที่ docstring ของเทสนั้นบอกว่าจะจับ · ผล: เทสนั้นเป็น **ตัวเดียว** ใน `TestDowngrade` ที่แดง → การเขียนใหม่ใช้ได้

---

## Invariants ที่ยืนยันแล้ว

- ไม่มี `if`/`elif` บนรุ่น/ยี่ห้อในเส้นทางใหม่ — `device.model` โผล่แค่ใน f-string
- ไม่มี `hasattr` — ที่เจอ 3 จุดเป็นข้อความอธิบายว่าทำไมถึงไม่ใช้
- **ADR 0004 ถูกตรึงด้วย mutation ไม่ใช่แค่ assert** — เติม `record_success`/`record_failure` เข้าไปแล้ว `TestItNeverTouchesDeviceStatus` แดงทั้งสองตัว
- **ADR 0008** — ไม่มีคอลัมน์ `read_end`/`last_read`/`*_through` หรือตาราง job ที่ไหนใน `app/src` · `_through()` อ่านค่าย้อนจากตารางจริง ไม่ใช่จากหน้าต่างที่ขอไป ซึ่งคือจุดที่ ADR เขียนขึ้นมาเพื่อป้องกันพอดี
- **ไม่มีรหัสผ่านรั่ว** — `str(exc)` ตัวเดียวที่ถึงผู้ใช้มาจาก `build_driver` ซึ่ง interpolate เฉพาะ `Device.transport` (คนละคอลัมน์กับ `Device.password`)

---

## Nit ที่ค้างไว้ให้เจ้าของ (ไม่บล็อก)

1. `test_load_profile_job.py:140-147` `test_reading_the_same_window_twice_stores_one_row` **ไม่แยกแยะด้วยตัวเอง** — เขียวทั้งตอน upsert→insert และตอนถอด constraint เพราะการเขียนครั้งที่สอง *error* แล้วแถวเดิมยังอยู่ · เกณฑ์ที่มันรับใช้ถูกตรึงซ้ำโดยอีกสองเทสอยู่แล้ว · เติม `assert result.error is None` จะทำให้ยืนได้เอง
2. `load_profile.py:177` `_ = exc` เป็นบรรทัดตาย
3. `load_profile.py:234` ความล้มเหลวจาก `_store` (เช่น FK violation) ถูกรายงานว่า *"The read of {endpoint} stopped after…"* ซึ่งชี้ผู้ใช้ไปที่มิเตอร์ทั้งที่เป็นปัญหาฐานข้อมูล
4. `load_profile.py:146` เรียก `_through()` บนเส้นทาง unsupported ทั้งที่ API ไม่ใช้ค่านั้น
5. **worst case ของปุ่ม Read now โตขึ้น** — lock acquisition สองครั้ง (ครั้งละไม่เกิน 120 วิ) + budget 60 วิ + chunk ที่ค้างอยู่ · เป็นผลของดีไซน์ที่ตกลงกันแล้ว (ปุ่มต้อง synchronous, #16 ย้ายเคสปกติไป scheduler) ไม่ใช่ข้อบกพร่อง แต่คือตัวเลขที่ต้องจับตาถ้าหน้างานบอกว่าปุ่มค้าง
6. `CLAUDE.md` ลิสต์ ADR หยุดที่ 0007 ไม่เคยพูดถึง 0008 — มีมาก่อนหน้านี้ ปล่อยไว้ถูกแล้ว
7. `SPEC.md:407-409` บอกว่าบรรทัด `devices` ใน §4 ผิดเรื่องคอลัมน์ JSON และควรแก้ "ตอนทำ M5a" — ยังค้าง
8. เวลาสวีท 16.6s → 37.1s จากเทสที่เพิ่ม 47 ตัว ไม่มีตัวไหนผิดปกติ (ช้าสุด 0.55s)

**ข้อสังเกตที่ตั้งใจ:** `_watermark` group จากแถวที่มีอยู่ ดังนั้น logger ที่ไม่เคยถูกอ่านเลยจะไม่มีกลุ่ม → ถ้าวันหนึ่ง driver เริ่มคืน logger ที่สองหลังจากตัวแรกถูกอ่านมานาน ประวัติที่อยู่หลัง watermark ร่วมจะไม่ถูกดึง · เป็น trade-off ของ D6 ที่รับไว้แล้ว บันทึกไว้ใน docstring ของ `_watermark` สำหรับคนทำ M4c แทนที่จะรื้อ D6

---

## สิ่งที่ **ไม่ได้** ทำ

- **ไม่ได้แตะมิเตอร์จริง** — SMW110W4 ทั้งสองตัวเข้าถึงได้จากเครื่องลูกค้าเท่านั้น · เส้นทางอ่านถูก validate ไปแล้วเมื่อ 2026-08-07 (`docs/meter-notes/smw110w4-scan.md:162-202`) ใบนี้พิสูจน์ชั้นจัดเก็บและ windowing ที่สร้างทับ
- ไม่ได้รัน `pnpm lint`/`pnpm build` — `web/` ไม่ถูกแตะ (modal เดิม render ทุก entry ใน `results` อยู่แล้ว)

---

## วิธีตรวจสอบเอง

```bash
git show f49cdfa --stat
cd app && pytest -n auto                    # ต้องได้ 706 passed
grep -rn "hasattr\|elif.*model" src/arichds/acquisition/load_profile.py
grep -rn "read_end\|last_read" src/arichds/     # ต้องไม่มี — ADR 0008
```

ตรวจ transcript ของ subagent:
```bash
d=~/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/<sessionId>/subagents
grep -o '"skill":"[a-zA-Z0-9:_-]*"' $d/agent-<agentId>.jsonl | sort | uniq -c
```
