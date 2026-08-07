# Audit log — issue #5 · M3-2: Device status from the Poller, events, pause/resume, Read now

**สถานะ**: DONE · **commit**: `3b49340` · **รอบรีวิว**: 1 (APPROVED รอบแรก)
**วันที่**: 2026-08-05 · batch `/run-batch 5-8` บน `feature/device-manager`

## ขั้นตอนที่ทำ

1. Reviewer (Job A) อ่าน issue + ADR 0004/0007 + โค้ดจริง แล้วเขียน DELEGATION PROMPT ผ่าน `/draft-delegation-prompt` — ปิดการตัดสินใจไว้ 15 ข้อ (D1–D15) ที่สำคัญ: ตัวนับพลาดอยู่ใน DB (`devices.consecutive_failures`) เพราะขี่ UPDATE เดียวกับ `status_checked_at` และรอดทั้ง `restart()` และ service restart · pause/resume เรียก `poller.restart()` หลัง commit · Read now = `probe_meter()` ทำให้ "ไม่มีค่าไฟฟ้ารั่วออก API" จริงโดยโครงสร้าง ไม่ใช่โดย filter
2. Implementer ทำตาม TDD 4 รอบ red→green: migration 0004 → `acquisition/status.py` (state machine) → wiring poller → API 5 endpoints
3. Reviewer (Job B) `/scrutinize` + `/code-review` — รัน gate เองทั้งหมด ไม่เชื่อรายงาน implementer

## การตัดสินใจ TDD

**บังคับใช้** — เหตุผลของ reviewer: ใบนี้เป็นกฎพฤติกรรมแทบล้วน (กฎ 3 ครั้ง, ตัวนับรอด restart, SKIPPED เฉื่อยสองทิศ, pause ขณะ worker วิ่ง) ซึ่งเป็นชนิดที่ "เขียนเทสทีหลังแล้วกฎไม่จริงโดยเงียบ ๆ"

## Skill ที่ตรวจจาก transcript จริง

- **Reviewer** (`acb58ff567771c9f4.output`): `draft-delegation-prompt` · `scrutinize` · `code-review:code-review` — ครบ 3 ✓
- **Implementer** (`a2914d5f8aa4aaf1e.output`): **transcript ยัง 0 bytes ตอนเขียน log นี้** (flush ช้า — ดู memory `subagent-transcripts-often-empty`) · prompt บังคับ `/tdd` + `fastapi` · รายงานของ implementer อ้าง TDD 4 รอบพร้อมตัวเลข red ต่อรอบ (8/33/6/6+15+19) · **ต้อง grep ซ้ำตอนปิด batch** — ห้ามสรุปว่า "0 skills"

## ผลรีวิว (Job B)

**APPROVED รอบเดียว** · reviewer รันเอง: `ruff format --check` ✓ · `ruff check` ✓ · `pytest` → **582 passed** (baseline 464, +118) · ไล่ acceptance checklist ทีละข้อพร้อมชื่อเทสที่พิสูจน์ — ครบทุกข้อ รวมข้อกันเทสหลอก (pause ต้อง start poller ก่อน · ห้าม assert ศูนย์ tick · เทส schema disjoint ต้อง derive จาก `InstantaneousReading` และ assert ว่า set ไม่ว่างก่อน)

**มิเตอร์จริง**: CEWE `203.170.151.152:4059` → `ProbeResult(meter_serial='WP079074', latency_ms=516)` — อ่านอย่างเดียว 1 association · reviewer ไม่รันซ้ำ (ไม่เปิด association ที่สองบนมิเตอร์ลูกค้าโดยไม่จำเป็น) — จัดเป็น owner-verified-pending ฝั่ง reviewer แต่หลักฐานสอดคล้องกับโค้ด

**ของแถมที่ไม่ได้สั่ง 1 จุด — reviewer ตัดสินว่าชอบธรรม**: nested guarded `except` รอบ `record_failure` ใน `_worker` last-resort handler — ไม่มีมันแล้ว DB error จะฆ่า worker thread ซึ่งละเมิด invariant ที่ docstring ประกาศ

## Nit ค้างให้เจ้าของ (ไม่ block)

1. `poller.py::_worker` — `self._record()` อยู่ใน `try` เดียวกับ `poll_fn` ⇒ ถ้า tick **สำเร็จ**แต่ `record_success` โยน (SQLite lock ชั่วคราวเกิน busy_timeout 5 วิ) จะถูกบันทึกเป็น strike แทน · หายเองใน tick ถัดไป · แก้ 1 บรรทัด: ย้าย `_record` ออกมา guard แยก · **ต้นเหตุคือ delegation prompt ของ reviewer เอง** (สั่งให้วางใน try เดิม)
2. `api/devices.py::update_device` — Update ที่ probe สำเร็จไม่รีเซ็ต status/ตัวนับ (ต่างจาก Create) · ไม่ใช่ defect เพราะ `restart()` ยิง tick แรกทันทีจึงแก้ตัวเองใน 1 tick · แต่ความไม่สมมาตรควรถูกตัดสินใจโดยเจตนาภายหลัง

## ตรวจสอบซ้ำ (self-audit)

```
cd app && ruff format --check . && ruff check . && pytest   # 582 passed
git show --stat 3b49340
grep -o '"skill":"[a-z:_-]*"' <output_file ทั้งสองไฟล์ข้างบน> | sort | uniq -c
```
