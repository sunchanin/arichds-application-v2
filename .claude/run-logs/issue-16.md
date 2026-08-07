# Issue #16 — M5a-2: the scheduler runs the load-profile job, and stops in Limited Mode

**สถานะ: DONE** · commit `a56cfc8` · branch `feature/load-profile` · รอบรีวิว **2**

---

## ขั้นตอนที่เดินจริง

| ขั้น | agent | เวลา |
|---|---|---|
| Job A — ร่าง delegation prompt | reviewer | 9.5 นาที |
| Implement รอบ 1 | implementer | 25.3 นาที |
| Job B รอบ 1 — **CHANGES_REQUESTED** | reviewer | 7.5 นาที |
| Fix รอบ 1 | implementer (ตัวเดิม) | 6.6 นาที |
| Job B รอบ 2 — **APPROVED** | reviewer (ตัวเดิม) | 24.3 นาที |
| **รวม** | | **73.2 นาที** |

**Track: full** · ไฟล์ 14 ไฟล์ (ใหม่ 3: `jobs/__init__.py`, `jobs/scheduler.py`, `test_scheduler.py`)
**เทส 706 → 737** (+31)

---

## สกิลที่ถูกเรียกจริง — ยืนยันจาก transcript

| agent | สกิล |
|---|---|
| reviewer | `draft-delegation-prompt` |
| implementer | `tdd` · `fastapi` |

`gurux-dlms` **ไม่ถูกบังคับในใบนี้และไม่ถูกเรียก** — ถูกต้อง ใบนี้ไม่แตะ driver หรือเส้นทาง DLMS เลย · ไม่มี review pass ซ้ำซ้อน

---

## บั๊กสำคัญที่รอบรีวิวจับได้ — และเป็นความผิดของ delegation prompt เอง

### Blocker: background job ถือ endpoint ด้วยสิทธิ์ Manual Read

`load_profile_cycle` → `read_and_store_load_profile(device_id)` → `registry.get(endpoint).manual(...)` ที่ `load_profile.py:156`

**ก่อนใบนี้ ฟังก์ชันนั้นมีผู้เรียกเดียวคือปุ่ม Read now** ซึ่งเป็น Manual Read จริง ๆ invariant จึงยังยืนอยู่ · **ใบ #16 คือสิ่งที่สร้างผู้เรียกที่สอง** — background job — แต่ยังใช้ `.manual()` เหมือนเดิม

ผลที่ผู้ใช้เห็น: คนกดปุ่ม Read now / Test connection บน endpoint ที่ background walk กำลังถืออยู่ จะ **รอ** นานสุด 120 วินาที และอาจล้มเหลวด้วยข้อความ "the line was still busy" — ซึ่งตรงข้ามกับ `CLAUDE.md` § Invariants ที่เขียนว่า *"a background tick that cannot have the endpoint is **skipped**, never queued"*

**นี่ไม่ใช่เคสมุม แต่คือวันติดตั้ง** — pass แรกรัน backfill 90 วันทันทีตอน boot (D10) และมิเตอร์สองตัวหลัง gateway เดียวกันหรือบนสายอนุกรมเดียวกันใช้ endpoint ร่วมกัน การเพิ่มเครื่องที่สองจึงอาจล้มเพราะ background job ถือสายอยู่

**หลักฐาน ไม่ใช่การอนุมาน:**

| | รอบ 1 | รอบ 2 (หลังแก้) |
|---|---|---|
| จับ endpoint ด้วย Manual Read แล้ววัดว่า cycle ใช้เวลาเท่าไหร่ | **1.31 วิ** (รอ) | **0.01 วิ** (ข้าม) |
| เรียกแบบไม่ใส่ flag (เส้นทางของปุ่ม) | — | **รอครบ 2.00 วิ** แล้วเขียนแถวจริง |

**การตัดสิน: แก้โค้ด ไม่ใช่บันทึกเป็นข้อยกเว้น** — reviewer ห้ามแตะ ADR 0006, การแจกแจง Manual-Read path ใน `locks.py` และรายการ **Manual Read** ใน `CONTEXT.md` โดยให้เหตุผลว่า *"โค้ดคือสิ่งที่ผิด เอกสารถูกอยู่แล้ว"* — ถ้าปล่อยให้แก้เอกสารตามจะเป็นการทำให้การละเมิดถูกกฎหมายย้อนหลัง · ตรวจแล้ว `git diff` ของทั้งสามว่าง

**ทางแก้:** `background: bool = False` แบบ keyword-only บน `read_and_store_load_profile` ที่ค่าเริ่มต้นรักษาพฤติกรรมเดิมเป๊ะ + แยก `_read_while_holding` ออกมาเพื่อให้สองเส้นทางต่างกัน**เฉพาะวิธีจับล็อก** · เมื่อ `background()` คืน `False` → คืน `skipped=True`, `error=None` (ข้ามไม่ใช่ล้มเหลว) และ log ระดับ INFO

**ค่าใช้จ่ายของสองทางเลือก ที่ reviewer ชั่งไว้ชัด:** ปล่อยไว้ = คนกดปุ่มล้มเพราะงานเบื้องหลังที่มองไม่เห็น · แก้ = อุปกรณ์หนึ่งเครื่องถูกข้ามหนึ่งรอบ แล้วอ่านใหม่ใน 900 วินาทีโดย watermark ยังอยู่ครบและไม่มีแถวหาย — ซึ่งคือ trade ที่ ADR 0006 กับ 0008 ตกลงและเขียนไว้แล้ว

### ความผิดถูกชี้กลับไปที่ต้นทางอย่างตรงไปตรงมา

reviewer เขียนบนบันทึกเองว่า **นี่คือข้อบกพร่องของ Job A ที่มันเขียน**: out-of-scope list ห้ามแก้ signature ของ `read_and_store_load_profile` และ D6 ตรึงการเรียกไว้ที่ค่าเริ่มต้นล้วน — จึง**ไม่เหลือทางที่ถูกกฎให้ทำถูกต้อง** · มันยกเลิกข้อห้ามของตัวเองในรอบแก้

implementer เองก็ทำถูกที่ **ไม่แก้เอง** และไม่แก้เอกสารให้เข้ากับพฤติกรรมใหม่ โดยให้เหตุผลว่า *"การทำให้การละเมิด ADR ถูกกฎหมายในเอกสารไม่ใช่หน้าที่ของ implementer และเป็นการชิงตัดสินผลลัพธ์"*

---

## เทสที่ผ่านแต่จับอะไรไม่ได้ — mutation probe จับได้

**กฎ D11 (job ที่รันเกิน interval ต้องไม่ซ้อนคิว) ไม่ถูกตรึงด้วยเทสใดเลย**

reviewer เปลี่ยน `scheduler.py:205` จาก `due[index] = time.monotonic() + interval` เป็น `due[index] = due[index] + interval` — คือคำนวณจากเวลาที่*ควรจะ*เริ่มแทนเวลาที่*ทำเสร็จ* — แล้ว **เทสทั้ง 25 ตัวยังเขียว**

ถ้าปล่อยไป: job ที่รันเกิน interval จะตกหลัง `now` ถาวร แล้ว**รันทุก pass** โดยห่างกันแค่ `SCHEDULER_MIN_SLEEP_SEC` = 0.01 วินาที — load-profile cycle จะไล่อ่านมิเตอร์ทุกตัวติด ๆ กันตลอดไปพร้อมถือ endpoint ไว้ทั้งหมด · และนี่คือ registry ที่ M6/M7/M8 สืบทอดทั้งหมด

**สำคัญ:** ไม่มีอะไรในกระบวนการอื่นจับตัวนี้ได้ — ไม่ใช่ TDD (red มาจากสัญลักษณ์ที่ยังไม่มี), ไม่ใช่ self-check, ไม่ใช่ full suite เขียว · **เฉพาะการทำลาย logic แล้วดูว่าเทสแดงไหม เท่านั้นที่เห็น**

---

## Mutation probe ทั้งหมดในใบนี้

**implementer (4):** กลับเงื่อนไข `if state.valid` · ถอด `enabled` guard · เติม `record_success()` เข้า cycle · ถอด empty-registry guard — แดงทุกตัว

**reviewer รอบ 1 (7):** เลื่อน first pass · ลบ per-job `shutdown.is_set()` break · ถอด Offline filter · เปลี่ยน `shutdown.wait` เป็น `time.sleep` · กลับลำดับ walk · memoise device list — **6 ตัวแดง 1 ตัวไม่แดง** (D11 ข้างบน)

**reviewer รอบ 2 (5):** เปลี่ยน default เป็น `background=True` · ให้ manual branch ใช้ `.background()` · ให้ `background()` คืน `False` แล้วอ่านต่อไปเลย · ใส่ mutant D11 เดิมซ้ำ · ให้ skip พก `error` sentence

ผลรอบ 2 ที่มีค่าที่สุด: **การทำลาย default path แดงที่เทสสองตัวที่เป็นอิสระต่อกัน** — ตัวใหม่ `test_read_now_keeps_its_priority_and_still_waits` และตัวเดิม `test_a_busy_endpoint_is_reported_as_the_line_not_the_meter` · แปลว่าครึ่งที่ "ไม่ควรเปลี่ยน" ถูกเฝ้าจริง ไม่ใช่แค่คำกล่าวอ้าง

**ตัวเดียวที่ไม่แดง (บันทึกไว้ ไม่ใช่ข้อบกพร่อง):** ให้ skip พก `error` sentence — ไม่มีเทสไหนเปลี่ยน เพราะวันนี้**ไม่มีใครมองเห็นผลของ skip ได้เลย** (cycle ทิ้งค่าที่คืนมา, handler ของปุ่มเข้าไม่ถึงเส้นทาง background) · จะเริ่มมีค่าให้เขียนเทสตอน M5b ที่หน้า Records เอาสิ่งที่ cycle ทำมาแสดง

---

## Invariants ที่ยืนยันแล้ว

- **ADR 0006 กลับมายืน** — วัดจริงทั้งสองด้าน (0.01 วิ สำหรับ background, 2.00 วิ สำหรับคน)
- **ADR 0004** — เติม `record_success()` เข้า cycle แล้วเทสสองตัวแดง
- **ADR 0008** — ไม่มี `last_run_at`, `read_end` หรือตาราง job ที่ไหน · due time อยู่ในหน่วยความจำและหายตอน restart โดยเจตนา
- ไม่มี base class ร่วมกับ `poller.py` — ถ้ามีก็คือ `_DaemonScheduler` ของ v1 กลับเข้าประตูหลัง
- ไม่มี dependency ใหม่ · thread เดียวชื่อ `arichds-scheduler` · ไม่มี thread รอดข้าม app
- `skipped=True, stored=0` ถูกเข้าใจผิดเป็นความล้มเหลวไม่ได้ — ไล่เส้นทางแล้วผู้บริโภคเดียวคือ handler ของปุ่ม ซึ่งเข้าไม่ถึงเส้นทาง background

---

## สิ่งที่ implementer จับได้เกินรายการที่ถูกสั่ง

`app/README.md:56` — ตาราง environment variable มี `ARICHDS_POLL_ENABLED` อยู่ด้วย เป็นจุดที่ **7** ที่ sweep ของ Job A พลาด (reviewer ยอมรับว่า grep ของมัน glob `*.md` แค่ระดับ root จึงไม่ครอบ `app/`) · ส่วน `app/src/arichds.egg-info/PKG-INFO:72` เป็นสำเนาที่ generate ขึ้นและ `.gitignore` อยู่ — ปล่อยไว้ถูกแล้ว

---

## Nit ที่ค้างไว้ให้เจ้าของ

1. mutation "ให้ skip พก error sentence" ไม่แดงที่เทสใดเลย — ไม่ใช่ช่องโหว่วันนี้ แต่ควรมีเทสตอน M5b
2. `LOAD_PROFILE_INTERVAL_SEC = 900` เป็น **สมมุติฐานที่ยกมาจาก v1 ไม่ใช่ตัวเลขที่วัด** — ยังไม่มีใครวัดว่าอ่าน LP หนึ่งเครื่องบนฮาร์ดแวร์นี้ใช้เวลาเท่าไหร่ · บันทึกไว้ในคอมเมนต์ของค่าคงที่แล้ว
3. worst case ของปุ่ม Read now ที่บันทึกไว้ตั้งแต่ #15 ยังอยู่เหมือนเดิม

---

## สิ่งที่ **ไม่ได้** ทำ

- **ไม่ได้แตะมิเตอร์จริง** — ทุกอย่างพิสูจน์ด้วย `FakeSmw110Driver` · delegation prompt เขียนไว้ตรง ๆ ว่า *"เทส scheduler ที่ต้องใช้มิเตอร์จริงคือเทสที่วัดผิดเรื่อง"*
- ไม่ได้รัน `pnpm lint`/`pnpm build` — `web/` ไม่ถูกแตะ

---

## วิธีตรวจสอบเอง

```bash
git show a56cfc8 --stat
cd app && pytest -n auto                        # ต้องได้ 737 passed
grep -n "background()" src/arichds/acquisition/load_profile.py
git diff HEAD~1 HEAD -- docs/adr/0006-*.md src/arichds/acquisition/locks.py   # ต้องว่าง
grep -rn "last_run_at\|read_end" src/arichds/    # ต้องไม่มี — ADR 0008
```
