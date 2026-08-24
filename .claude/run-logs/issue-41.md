# Audit log — Issue #41: Issue Meter Activation Codes — the vendor-side signer and CLI (ADR 0019)
รัน: 2026-08-24 · branch: `feature/light-modules` · ผลลัพธ์: **APPROVED** · รอบรีวิว: **2**
เกิดจากของหลุด: **ไม่ใช่ งานใหม่** — ครึ่งฝั่งผู้ขายของ ADR 0019 · ครึ่งฝั่งผลิตภัณฑ์คือ #42 ซึ่งถูกบล็อกโดยใบนี้

## ทำอะไรไปบ้าง (ทีละขั้น)

### 1. reviewer (Job A) — สร้าง prompt (`/draft-delegation-prompt`)
- **Track: `full`** · **TDD required: `yes`**
- **Workflow discipline: ตรวจทั้งสามสกิลแล้วระบุว่าไม่มีตัวไหนเข้าข่าย** — `fastapi` (ไม่มี route), `antd-ui` (ไม่แตะ `web/`), `gurux-dlms` (ไม่ต่อมิเตอร์)

**แก้ข้อผิดพลาดของ orchestrator สองข้อ:**

1. **path ที่ orchestrator ยืนยันไม่มีอยู่จริง** — kickoff เขียนว่า `.claude/skills/activate/` · ของจริงคือ
   `.claude/commands/activate.md` · orchestrator ยืนยัน path โดยไม่เปิดดู ⇒ ถ้า agent เชื่อจะสร้างไฟล์ผิดที่
2. **เจอเอกสารเก่าเพิ่มอีก 2 จุดที่ issue ไม่ได้ระบุ** — `SPEC.md:131` และ docstring ที่
   `test_api_users.py:143` ทั้งคู่เขียนว่า *"`arichds_vendor.py` มีแค่ keygen/sign/fingerprint"*
   · ตัวหลังเป็น **docstring** ⇒ ไม่มีเทสพัง ⇒ **ซึ่งคือเหตุผลว่าทำไมมันจะเน่าอยู่อย่างนั้น**

**การตัดสินที่สำคัญ:**
- **D3 ใส่ `type: "meter"` ลง payload** ทั้งที่สองรูปแบบมีชุด field ต่างกันอยู่แล้ว —
  *"relying on an incidental difference between two things signed by the same key is not a
  boundary, it is luck"* (กุญแจเดียวเซ็นทั้งสองแบบ)
- **ไม่มี field วันหมดอายุเลย ไม่ใช่แม้แต่ `expires_at: null`** — ADR 0019 ตรวจครั้งเดียวตอนเพิ่มมิเตอร์
  ⇒ key ที่เป็น null คือคำเชิญให้คนถัดไปเขียนการตรวจที่ ADR ปฏิเสธ
- **เตือนเรื่อง private key จริงบนเครื่อง** — `tools/.arichds_private_key.pem` **มีอยู่จริง** ⇒
  เทส "ไม่มี key แล้วต้อง fail" ที่พึ่ง path ปริยายจะผ่านบน CI แต่ fail บนเครื่องนี้ ⇒
  บังคับให้ทุกเทสส่ง `--private-key` ชี้ `tmp_path` และ **ห้ามรัน `keygen`**

### 2. implementer — ลงมือ + ตรวจตัวเอง (`/tdd` + self-check สองด่าน)
- **ไฟล์ที่เปลี่ยน (8):** ใหม่ 3 — `licensing/meter_activation_code.py`,
  `tests/test_meter_activation_code.py`, `.claude/commands/activate-meter.md` ·
  แก้ 5 — `licensing/__init__.py`, `tools/arichds_vendor.py`, `CLAUDE.md`, `SPEC.md`,
  `tests/test_api_users.py`
- **red ที่ดี:** cycle 1 เขียน payload **ผิดโดยตั้งใจ** (ใส่ `expires_at` แทน `type`/`issued_at`)
  ⇒ ได้ `AssertionError` จากค่าที่ผิดจริง ไม่ใช่ `ImportError` เพราะ symbol หาย — ตรงกับที่ prompt สั่ง
- **ผลรันรอบแรก:** `1591 passed, 17 skipped` · scoped 37 เทส · ruff ผ่าน
- **ยืนยันว่าไม่แตะ key จริง** ด้วยการเช็ค mtime (ยังเป็น 4 ส.ค.)
- **ไม่เก็บ baseline** — ยอมรับตรงๆ ว่า *"not captured"*

### 3. reviewer (Job B) — รีวิว (`/scrutinize`, full track)
- **verdict: CHANGES_REQUESTED** — 2 blocking (ทั้งคู่ `minor`, **แก้เฉพาะเทส ไม่แตะโค้ด production**) + 4 nit

#### 🔴 ข้อ 1 — เทสชื่อ "tampered" ไม่ได้ทดสอบการ tamper เลย

ทั้งสองตัวสร้าง payload **ขึ้นใหม่** ด้วย `build_meter_payload()` หลังเซ็นไปแล้ว ⇒ `issued_at`
เป็นเวลาใหม่ ⇒ canonical bytes ต่างอยู่แล้ว**โดยไม่ต้อง tamper อะไรเลย**

reviewer พิสูจน์ด้วยการ **ลบบรรทัดที่ tamper ทิ้ง**

```
ลบ payload["meter_serial"] = "TAMPERED"     -> GREEN, 1 passed
ลบ payload["machine_id"]  = OTHER_MACHINE   -> GREEN, 1 passed
```

⇒ **verifier ที่ไม่สนใจเนื้อ payload เลยก็ผ่านทั้งสองตัว** · และนี่คือเกณฑ์ที่ issue เขียนไว้ชัดว่า
ต้องมีเทสแยกต่อกรณี · *"it is the accidental discriminator that is masking the real one"*

#### 🔴 ข้อ 2 — ตัวแยกรูปแบบ (`product`/`type`/`v`) ไม่มีเทสคุมเลย

แทนเงื่อนไขทั้งก้อนด้วย `False` → **37 passed** ⇒ `WRONG_PRODUCT` เข้าไม่ถึงทั้งชุดเทส
⇒ ขอบเขตความปลอดภัยของรูปแบบนี้พิงอยู่บน **ความต่างของชุด field** ซึ่งคือสิ่งที่ D3 เพิ่ม `type` เข้ามาแทนพอดี

#### ⚖️ ตัดสินสองข้อที่ orchestrator สั่งให้ดู

**baseline กระทบยอดได้** — reviewer ตรวจเองด้วย `--collect-only` (1571 → 1608, ต่าง 37 พอดี)
แต่เตือนว่า *"only because the entire delta was one new untracked file I could subtract cleanly.
That is a property of this issue, not a general substitute for capturing a baseline."*

**เหตุผลของ Mutation 3 กลับหัวจริง** — implementer อ้างว่า *"เทส cross-format ยังเขียวใต้ mutation
⇒ ยืนยันว่าตัวแยกทำงาน"* · reviewer ตอบว่า **เทสที่ยังเขียวใต้ mutation คือหลักฐานว่าเทสนั้นไม่ได้คุมโค้ดตรงนั้น**
แล้ว trace ให้ดู: พอ `type` ไม่บังคับ payload ของเครื่องก็ยังไม่มี `meter_serial` ⇒ ตายที่บรรทัด 150
ไม่เคยไปถึงการเช็ค `type` ที่บรรทัด 180 ⇒ สีเขียวมาจาก `meter_serial` ล้วนๆ

- **ควรถูกจับที่ด่านไหน:**
  - **ข้อ 1** → **self-check ของ implementer** · เป็นรูปแบบเดียวกับ memory
    `a-fake-that-overrides-a-method-hides-it-from-every-test` — ถามว่า *"เทสนี้แดงเพราะอะไรกันแน่"*
    ไม่ใช่แค่ *"assertion นี้ discriminate ไหม"*
  - **ข้อ 2** → **ไม่มี — Job B เท่านั้นที่จับได้** ต้องรัน mutation ถึงจะเห็นว่าโค้ดเข้าไม่ถึง
  - **nit 6** → reviewer ยอมรับเป็นความผิดตัวเอง: *"my Job A prompt put `activation_code.py` out of
    scope, so extracting a shared helper was not available to you"*

### 4. รอบแก้ (รอบ 1) — แก้เฉพาะเทส
- tamper ที่ **payload ที่ถูกเซ็นจริง** แทนที่จะสร้างใหม่ (split → `_b64url_decode` → mutate →
  re-encode ด้วยลายเซ็นเดิม)
- เพิ่มเทสที่ **เซ็นหลัง mutate** เพื่อให้ลายเซ็นถูกต้องและไปถึงการเช็คตัวแยกได้จริง
- **รัน mutation ของ reviewer เองซ้ำ** เพื่อพิสูจน์ว่าตอนนี้แดง ไม่ใช่แค่บอกว่าแก้แล้ว
- **รับ nit ทั้งสองตัว** — `.lower()` บน Machine ID (ถ้าหลุด code ที่เซ็นออกไปจะ verify ไม่ผ่านตลอดกาล)
  และ `--out`

### 5. reviewer (Job B รอบ 2) — **APPROVED**

#### ⚖️ reviewer ยอมรับว่าคำทำนายของตัวเองผิด — และผลลัพธ์แข็งแรงกว่าที่มันคิด

orchestrator ทักว่าค่าที่ได้ (`WRONG_METER`/`WRONG_MACHINE`) ต่างจากที่ reviewer ทำนายไว้ (`reason=None`)

reviewer ตรวจแล้วตอบว่า **คำทำนายของตัวเองต่างหากที่ผิด** — มันทำนายบนสมมติฐานว่าผู้เรียกอ้าง serial
**เดิม** แต่เทสอ้าง serial ที่ **ถูก tamper** ⇒ เป็นคนละรูปการเรียก

และชี้ว่ารูปของเทส **แข็งแรงกว่า** รูปที่ตัวเองเสนอ: เพราะผู้เรียกอ้างค่าที่ตรงกับ payload ที่ถูก tamper
⇒ การเช็ค type/product/version ผ่าน · machine binding ผ่าน · serial binding ผ่าน ⇒
**`INVALID_SIGNATURE` เข้าถึงได้ทางเดียวเท่านั้น คือ authentication ล้มบนเนื้อที่ไม่ตรงลายเซ็น**

แล้วพิสูจน์ด้วย mutation ที่ถูกต้องกว่า — **ลบการตรวจลายเซ็นทั้งบล็อกทิ้ง**

```
Q1 delete the signature verification entirely -> RED :: 3 failed, 38 passed
```

พร้อมยอมรับข้อจำกัดของตัวเองตรงๆ: *"'delete the tamper line' is now a weak mutation — it goes red
for a binding reason, so it no longer isolates authentication. Q1 is the mutation that does."*

#### ตรวจ probe รอบแรกซ้ำทุกตัว

| probe รอบ 1 | ก่อน | หลัง |
|---|---|---|
| ทำลายตัวแยก `product`/`type`/`v` | GREEN 37/37 | **RED 2 failed** |
| ลบบรรทัด tamper | GREEN | **RED** (+ Q1 แดงที่ authentication) |
| ถอด `.lower()` บน Machine ID | GREEN | **RED 1 failed** |
| ถอดการเขียนไฟล์ `--out` | GREEN | **RED 1 failed** |

- **nit ที่เหลือให้มนุษย์ (ไม่บล็อก):** 3 เงื่อนไข defence-in-depth ยังไม่มีเทสคุม — และ reviewer
  อธิบายว่าทำไมถึงไม่บล็อก: **ทุกตัวเข้าถึงได้เฉพาะคนที่ถือ private key ของเราอยู่แล้ว คือพวกเราเอง** ·
  ที่น่าสนใจคือ **`product` ไม่ได้ทำงานแยกแยะอะไรเลย** เพราะทั้งสองรูปแบบมี `product == "arichds"`
  เหมือนกัน ⇒ `type` คือตัวแยกจริงและตอนนี้มีเทสคุมแล้ว

## ต้นทุน (เวลา + tokens ต่อสเตจ)

| สเตจ | เวลา | tokens (สะสม) |
|---|---|---|
| reviewer Job A | 8.1 นาที | 102,777 |
| implementer (build) | 13.0 นาที | 187,718 |
| reviewer Job B (รอบ 1) | 32.8 นาที | 169,791 |
| รอบแก้ 1 — implementer | 5.0 นาที | 219,946 |
| รอบแก้ 1 — reviewer Job B | 42.1 นาที | 188,532 |
| **รวม** | **~101 นาที** | — |

> ⚠️ token บวกกันไม่ได้ — `subagent_tokens` หลัง `SendMessage` resume เป็นค่า**สะสม**
>
> **รอบแก้ = 47.1 นาที = 47% ของ wall-clock** — สูงกว่า #38 (35%) และ #40 (26%)
> เพราะเวลาส่วนใหญ่ไปอยู่ที่ **reviewer รัน mutation probe** (15 ตัวสองรอบ) ไม่ใช่ที่การแก้โค้ด
> (implementer ใช้ 5.0 นาที) · นี่คือรูปที่ต่างจากสองใบก่อน และเป็นการใช้เวลาที่คุ้ม —
> mutation ทั้งสองข้อที่บล็อกมาจาก probe ไม่ใช่จากการอ่านโค้ด

## ✅ skill ที่เรียกจริง — ยืนยันจาก transcript (tamper-proof)

```
=== reviewer aeb9776af452d2898 (754,654 bytes) ===
      1 "skill":"draft-delegation-prompt"
      1 "skill":"scrutinize"
Skill calls: 2

=== implementer a1fee6ce210f0f4ac (1,212,411 bytes) ===
      1 "skill":"tdd"
Skill calls: 1
```

- **ครบทุก mandate** · **ไม่มีรีวิวซ้ำซ้อน** · **ไม่มี `docs-researcher` ถูก spawn** —
  Job A ระบุไว้ตรงๆ ว่า *"Findings from research: None required, and this is a decision rather than
  an omission"* พร้อมเหตุผล (รูปแบบ wire เป็นของภายในรีโป, `cryptography` pin อยู่แล้ว) ⇒
  ประหยัดรอบค้นที่ไม่จำเป็นไปหนึ่งรอบ

## Commit
`12ec84e` — `feat: issue Meter Activation Codes from the vendor CLI (#41)`
9 ไฟล์ · +1,060 / −5

**ยังไม่มีอะไรให้เจ้าของยืนยันด้วยมือในใบนี้** — code ที่ออกได้ยังไม่มีที่ให้วาง เพราะฟอร์ม
Add Device คือ #42 · `/activate-meter` เขียนความจริงข้อนี้ไว้ใน Step 4 แล้ว ไม่ได้เขียนวิธีวาง
ลงหน้าจอที่ยังไม่มี

## วิธีตรวจซ้ำด้วยตัวเอง (audit)

```bash
d="C:/Users/HP/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents"
grep -o '"skill":"[a-zA-Z0-9:_-]*"' "$d/agent-aeb9776af452d2898.jsonl" | sort | uniq -c   # reviewer
grep -o '"skill":"[a-zA-Z0-9:_-]*"' "$d/agent-a1fee6ce210f0f4ac.jsonl" | sort | uniq -c   # implementer
```

**อย่าใช้ `output_file` ที่ tool คืนมา** — เป็น 0 ไบต์เสมอ
