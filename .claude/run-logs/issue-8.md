# Audit log — issue #8 · M3-4: Stop persisting instantaneous reads (ADR 0007) and rename the readings table

**สถานะ**: DONE · **commit**: `7c8b508` · **รอบรีวิว**: 1 (APPROVED รอบแรก)
**วันที่**: 2026-08-05 · batch `/run-batch 5-8` (ท่อนหลัง resume หลังเจ้าของสั่งหยุดที่ #6) บน `feature/device-manager`

## ใบนี้รันด้วย pipeline ปรับใหม่ (เจ้าของอนุมัติ 2026-08-05)

1. **Job A แบบ delta** — issue ผ่าน scrutinize 3 รอบจนเกรด prompt แล้ว reviewer จึงเขียนเฉพาะ "สิ่งที่ใบไม่รู้" (โค้ดเปลี่ยนหลัง #5/#6): **5.5 นาที / 89k tokens** เทียบ Job A เต็มรูปของ #5 (8.4/129k) และ #6 (7.7/110k) — เร็วขึ้น ~30% และ**จับ seam ที่ grep ของใบมองไม่เห็น**: `app/scripts/probe_meter.py:99` ยังเรียก `read_instantaneous()`
2. **Job B แบบ scoped** ตาม `reviewer.md:54` (เลิก override ให้รัน full suite): **7.4 นาที / 174k** เทียบ 10.3/210k ของ #5
3. ผมเสนอให้ implementer ข้าม baseline pytest โดยอ้าง `f644f59` ที่ยืนยันเขียวแล้ว — **implementer เลือกรัน baseline อยู่ดี** (ยึด `implementer.md:18`) — ข้อมูลตัดสินใจ: จะตัด baseline จริงต้องแก้ไฟล์นิยาม ไม่ใช่สั่งผ่าน prompt

## การตัดสินใจ TDD

**บังคับ** — เปลี่ยนพฤติกรรมระดับ branch (outcome mapping, เคสล้มใหม่, migration ทำลายข้อมูล) · ทำจริง 5 vertical cycles มี red step ทุกรอบ (paste ไว้ในรายงาน: 4 failed → เขียว ฯลฯ)

## Skill ที่ตรวจจาก transcript จริง

- **Reviewer** (`a1f61f464ed34d9a2.output`, 730 KB): `scrutinize` ✓ · `code-review:code-review` ✓ · **`draft-delegation-prompt` ไม่ถูกเรียก** — process miss จากโหมด delta (spawn message ของ orchestrator ไม่ได้สั่ง invoke ชัด ๆ) · ผลลัพธ์ไม่เสียหาย (prompt คุณภาพสูง จับ seam ได้) แต่รอบหน้า delta-instruction ต้องเขียน "invoke /draft-delegation-prompt" กำกับด้วย
- **Implementer** (`aca0d886e1658fbef.output`): **transcript 0 bytes ถาวร** (เหมือน #5 — implementer 2 ใน 3 ตัวของ batch ไม่ flush) → **unavailable** ห้ามตีความว่า 0 skills · หลักฐานแวดล้อม: prompt บังคับ `gurux-dlms` + `/tdd` และรายงานมี red-step ทุก cycle พร้อมพฤติกรรมที่สอดคล้องกับเนื้อหา skill (ไม่แตะ `GX*.py`, label "in v2 today")

## ผลรีวิว (Job B — APPROVED รอบเดียว)

Reviewer รันเอง (scoped): 107 + 189 เทสของพื้นที่ที่เปลี่ยน + ruff ทั้งคู่ ✓ · เดิน `poll_once` ใหม่ทีละบรรทัด (lock ยัง `.background()` — ADR 0006 ไม่กลับหัว) · ตรวจ migration 0005 (DELETE → rename → index สองตัว · downgrade คืนรูปทรงไม่คืนข้อมูล — ตั้งใจ) · dependency-swap check: `read_meter_serial()` คืน `str | None` และโยน exception ทะลุ — ทั้งสองเคสถูก handle · **การเปลี่ยนพฤติกรรมหนึ่งเดียวคือเจตนาของใบ**: register เดียวล้มตอนนี้ทำให้ tick ล้ม (เดิมกลืนราย column) — คือสิ่งที่กัน "มิเตอร์รับ association แต่อ่านไม่ได้" ไม่ให้ขึ้น Online

**คำตัดสินที่ถูกขอชัด ๆ**: grep carve-out ที่ `test_migration_0005.py` (11 จุดชื่อตารางเก่า) **ชอบธรรม** — เทสพิสูจน์ rename ต้องเอ่ยชื่อต้นทาง จะ assert ว่าชื่อเก่าหายไปโดยไม่เขียนชื่อเก่าไม่ได้ · deviation 2 จุดใน D10 (เปลี่ยนชื่อเทสที่จะ stale + แยก assertion divide-once เป็นสองครึ่ง) **ถูกทั้งคู่**

**มิเตอร์จริง — PASSED**: CEWE `203.170.151.152:4059` อ่านอย่างเดียว 4 tick จังหวะ 60 วิจริง · แถว `load_profile_readings` ก่อน=0 หลัง=0 · unknown→online จากการอ่าน serial · INFO log ไม่มีค่าไฟฟ้าและไม่มี serial (ADR 0007 ยืนยันบนสายจริง) · reviewer ยืนยันเชิงโครงสร้าง: `session_scope()` เดียวที่เหลือใน poller คือ SELECT — ไม่มี INSERT ให้ tick ไปถึงได้เลย

**ผลเต็มชุด (implementer)**: baseline 578 → final **588 passed** (−4 +4 +10 ตรงบัญชีเป๊ะ) · ADR 0002: 21→20 checks โดย 1 ที่หายคือ tzinfo pin ที่อนุมัติแล้ว

## Nit ค้างให้เจ้าของ (4 — ไม่ block)

1. `HEALTH_CHECK_OBIS_CODE/_ATTR` ไม่มีผู้เรียกแล้ว — เก็บไว้เพราะ M6 ต้องใช้ meter clock · ควร rename เป็น `CLOCK_OBIS_*` ตอน M6 ให้ caller
2. `last_latency_ms` ไม่มีใครเขียนค่าแล้ว — เก็บรอ M5 พร้อม docstring บอกตรง ๆ
3. `probe_meter.py`: serial read อยู่ใน `try` เดียวกับ register dump — มิเตอร์ที่ปฏิเสธ serial จะไม่พิมพ์รายงาน scaler เลย (เดิมพิมพ์) — dev-only
4. `probe_meter.py` เรียก `driver._normalize()` (private) — reviewer อนุมัติเองตอนเขียน prompt เพราะเป็นทางเดียวให้ตัวเลขตรงกับที่ M5 จะเก็บ

## ตรวจสอบซ้ำ (self-audit)

```
cd app && ruff format --check . && ruff check . && pytest    # 588 passed
git show --stat 7c8b508
python -m alembic history   # 0001..0005
grep -rn "interval_readings" app/src app/tests web/src --include="*.py" | grep -v migrations  # เหลือเฉพาะ test_migration_0005 + ประโยคประวัติใน 0004
```
