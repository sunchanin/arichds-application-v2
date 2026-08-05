# Audit log — issue #6 · M3-3: Devices page — tree, form, actions, history drawer, retire Monitor

**สถานะ**: DONE · **commit**: `f644f59` · **รอบรีวิว**: 2 (CHANGES_REQUESTED → APPROVED)
**วันที่**: 2026-08-05 · batch `/run-batch 5-8` บน `feature/device-manager`

## ขั้นตอนที่ทำ

1. Reviewer (Job A) เขียน DELEGATION PROMPT — การตัดสินใจสำคัญ: ลำดับงานสร้างหน้า Devices ให้ครบก่อนแล้วค่อยถอด Monitor เป็นขั้นสุดท้าย (ADR 0007 "Not before") · one-list-call ห้าม N+1 · **ระบุชะตากรรมเทส backend ทีละไซต์** — 10 ไซต์ที่ใช้ `/readings/latest` แยกเป็น ลบ 4 / ชี้ไป `/events` 2 / เขียนใหม่ให้นับแถว DB 5 — กันทางลัด "ลบให้เขียวแล้ว coverage หด"
2. Implementer สร้าง `Devices.tsx` + ขยาย `api.ts` + ถอด Monitor + ลบ endpoint + rework เทส + กวาดเอกสาร 16 ไฟล์
3. Job B รอบ 1: CHANGES_REQUESTED (minor 2) → fix → รอบ 2: APPROVED

## การตัดสินใจ TDD

**ไม่ใช้** — `web/` ไม่มี test runner และห้ามเพิ่ม (dependency decision ที่ issue ไม่ได้อนุญาต) · ฝั่ง backend เป็นงานลบ + เขียนเทสเดิมใหม่แบบผ่าตัด ไม่ใช่ red→green

## Skill ที่ตรวจจาก transcript จริง

- **Reviewer** (`aa6b7eb808c0ad696.output`, 863 KB): `draft-delegation-prompt` · `scrutinize` · `code-review:code-review` — ครบ ✓
- **Implementer** (`a84987d0fea6b6475.output`, 1.5 MB): `antd-ui` ✓ · `frontend-design:frontend-design` ✓ — ครบทั้งสอง domain skill ที่บังคับ · `/tdd` ไม่ถูกเรียก = ถูกต้องตาม Job A · fastapi skill ถูกสั่งเป็น "read" ไม่ใช่ "invoke" จึงไม่ปรากฏใน transcript
- **หมายเหตุ #5**: transcript implementer #5 (`a2914d5f8aa4aaf1e.output`) ยัง 0 bytes ถาวรแม้ #6 flush ปกติ — บันทึกเป็น **transcript unavailable** (ห้ามตีความว่า 0 skills)

## ผลรีวิว

**รอบ 1 — CHANGES_REQUESTED** (minor 2, reviewer รัน gate เองทั้งหมด: pytest 578 ✓ lint/build ✓ grep ครบ):
1. 422 validation array → `String(body.detail)` → ผู้ใช้เห็น `[object Object],[object Object]` + Test connection ยิงโดยไม่ validate ฟอร์มก่อน (reviewer **ลองกดจริง**จนเห็นผล)
2. `CLAUDE.md` ยังเขียนว่า ADR 0007 "not yet implemented" ซึ่งใบนี้ทำให้เป็นเท็จ

**รอบ fix**: implementer แก้ข้อ 1 (`formatDetail()` ใน `api.ts` + `validateFields` guard) แต่**ปฏิเสธข้อ 2 อย่างถูกต้อง** — กติกาของ implementer ห้ามแก้ `CLAUDE.md` จากอำนาจของ agent ด้วยกัน · orchestrator แก้เองแทน (กติกา batch มอบ docs sweep รวม `CLAUDE.md` ให้ orchestrator) · reviewer รอบ 2 บันทึกว่าการปฏิเสธนี้คือพฤติกรรมที่ถูกต้อง ไม่ใช่การเลี่ยงงาน

**รอบ 2 — APPROVED**: reviewer อ่าน `formatDetail` ยืนยัน string detail ผ่าน verbatim (ประโยค 409/duplicate-serial ไม่โดนกระทบ) · envelope branch ไม่ถูกแตะ (`PROBE_FAILED`/`isLicenseLapsed` ยังทำงาน) · trace loading state ว่าปุ่มไม่ค้าง · `git diff --stat -- app/` byte-identical ⇒ ผล 578 passed ยังยืน ไม่ต้องรัน pytest ซ้ำ

## จุดแข็งที่ reviewer ชี้

- Action row อยู่**นอก** `<Form>` โดยเจตนา — `Form disabled` ทะลุถึง Button ลูกทุกตัว ถ้าอยู่ในฟอร์ม role `user` จะเสีย Read now/History ที่ issue ให้สิทธิ์ไว้ — บั๊กที่จับได้ด้วยการ reasoning ไม่ใช่เทส
- Timer 15 วิ ไม่มีทางเขียนทับฟอร์มที่กำลังพิมพ์ (state เก็บ `selectedId` ไม่ใช่ object · `fill()` รันจาก explicit action เท่านั้น)
- Self-check ของ implementer จับ major เองก่อนส่งรีวิว: **password โดน trim ก่อนส่ง** (ความลับถูกเปลี่ยนเงียบ ๆ) + catalog fetch ล้มเงียบ

## Nit ค้างให้เจ้าของ (ไม่ block)

1. `formatDetail` join ด้วย `\n` ซึ่ง HTML ยุบเป็น space — error หลาย field อ่านติดกันเป็นบรรทัดเดียว
2. `README.md` ประกาศ "M1–M3 complete" ล่วงหน้า ก่อนครึ่ง owner-verified จะถูกรัน
3. ปุ่ม Delete ใช้คำ "readings" ที่ glossary ใช้ "Interval Reading" (drift อ่อน)
4. `theme.ts:5` มี comment ภาษาไทย (ของเดิม M1 นอก scope)

## ⚠️ ครึ่ง owner-verified ยังค้าง — ใบนี้ปิดเฉพาะส่วนอัตโนมัติ

สคริปต์เดินเทส 3 ชุดอยู่ในรายงาน implementer (walkthrough มิเตอร์จริง `203.170.151.152:4059` **อ่านอย่างเดียว** · 4 เคส error ต้องอ่านต่างกัน · role `user` ไม่เห็นปุ่ม admin) — **ยังไม่มีใครรัน** ต้องรอเจ้าของเปิดเบราว์เซอร์

## ตรวจสอบซ้ำ (self-audit)

```
cd app && ruff format --check . && ruff check . && pytest    # 578 passed
cd web && pnpm lint && pnpm build
git show --stat f644f59
grep -o '"skill":"[a-z:_-]*"' <output_file ของ agent ทั้งสอง> | sort | uniq -c
```
