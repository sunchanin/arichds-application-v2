# Audit log — Issue 011: เปลี่ยน license ที่ยังใช้งานได้ จาก UI ไม่ได้

รัน: 2026-08-26 · branch: `feature/light-modules` · ผลลัพธ์: **APPROVED** · รอบรีวิว: **2**
เกิดจากของหลุด: **ใช่** — เจอตอนเจ้าของถามว่า "หน้า activation อยู่ตรงไหน" ระหว่างทดสอบการจำกัดฟีเจอร์
ไม่ใช่จากการอ่านโค้ด · ความสามารถมีอยู่ที่ backend มาตลอด **ขาดแค่ที่ให้วางโค้ด**

## ทำอะไรไปบ้าง (ทีละขั้น)

### 1. reviewer (Job A) — สร้าง prompt (`/draft-delegation-prompt`)
- **Track: full** — พฤติกรรมที่กั้นด้วย role, เส้นทาง error ที่มีความหมายต่อ reason, คำถามออกแบบที่ต้องตัดสิน, และการแก้เอกสารข้ามไฟล์
- **TDD required: no — แทนที่โดยตั้งใจ ไม่ใช่ยกเว้น** · backend ไม่ได้เพิ่มพฤติกรรมใหม่เลย (endpoint ทำได้อยู่แล้ว) เทสใหม่ทุกตัวจะเขียวตั้งแต่รันครั้งแรก การบังคับ red-first จึงเป็นพิธีกรรม · และ `web/` **ไม่มี test runner** ในรีโปนี้ (`package.json` มีแค่ `dev`/`lint`/`build`/`preview`) · ใช้ **mutation table แทน** ซึ่งแข็งกว่าในกรณีนี้
- **Workflow discipline: `antd-ui`** — ระบุด้วยว่า `fastapi` ไม่จำเป็นเพราะไม่มีโค้ด FastAPI ให้เขียน (Python ที่งานนี้เขียนมีแต่เทส) และ `gurux-dlms` ไม่เกี่ยว

**กับดักสองตัวที่ reviewer เจอตอนอ่านโค้ด และเป็นเหตุผลที่ใบนี้เป็น full track:**

1. **`isLicenseLapsed` จะกลืนทุกการปฏิเสธถ้าปล่อยไว้** — โค้ดที่ถูกปฏิเสธคืน `error.code == ERROR_LICENSE_INVALID`
   ซึ่งเป็นสตริง `"LICENSE_INVALID"` เดียวกับที่ `isLicenseLapsed` จับ (`web/src/api.ts:832-834`) และ
   `surface()` ใน `Settings.tsx` สั่ง `window.location.reload()` เมื่อเจอ ⇒ **พิมพ์โค้ดผิดทีเดียว
   แอปรีโหลดเงียบๆ** เด้งกลับหน้า Devices โดยไม่บอกอะไร — ซึ่งคือความสับสนที่ issue นี้ตั้งใจกำจัดพอดี
2. **`data.state` ในซองที่ปฏิเสธคือ `"limited"` และไม่ใช่สถานะของเครื่องนี้** — มันบรรยาย*โค้ดที่ถูกปฏิเสธ*
   ไม่ใช่เครื่อง · `request()` ทิ้ง `data` ทิ้งอยู่แล้วเมื่อ `success:false` — **ให้คงไว้แบบนั้น**

### 2. implementer — ลงมือ + ตรวจตัวเอง (`antd-ui`)
- ไฟล์: `LicenseCard.tsx` (ใหม่) · `Settings.tsx` · `App.tsx` · `Activation.tsx` · `AppShell.tsx` ·
  เทสสองไฟล์ · เอกสารสี่ไฟล์ (`SPEC.md` เขียนไทยตามภาษาของไฟล์, `CONTEXT.md`, `README.md`, `installer/README.md`)
- **ไม่แตะ `app/src/` เลย** — `git status --short app/src/` ว่าง · Python ที่เขียนมีแต่เทส
- **เขียนเทสตัวหนึ่งแล้วลบทิ้งเอง แล้วรายงานว่าลบ:** `test_replacing_a_license_does_not_stop_the_poller`
  **ผ่าน** แต่พออ่าน `re_evaluate` ต่อพบว่า listener ยิงเฉพาะตอน state *เปลี่ยน* — active→active
  ไม่เปลี่ยนทั้ง state และ reason ⇒ **ไม่มี listener ยิง เทสจึงเขียวไม่ว่าจะ mutate อะไร** · ลบทิ้ง
  แทนที่จะชิปเทสที่ไม่ได้คุมอะไร
- **mutation 8 ตัว แดงหมด** พร้อม probe ของตัวเอง 3 ตัว · restore ยืนยันด้วย SHA-256 ไม่ใช่ `git status`
- ผลรันเทสต์: **1790 → 1799 passed, 57 skipped** (+9 ตรงกับจำนวนเทสที่เพิ่ม)
- **รายงานราคาของคำสั่ง D8 แทนที่จะขยายขอบเขตเงียบๆ:** `export const REASON_TEXT` ทำให้เกิด eslint
  warning ตัวแรกของรีโป · มันทำตามคำสั่งตรงๆ แล้วบอกว่าทางแก้ที่สะอาดคืออะไร และรอให้ reviewer ตัดสิน

### 3. reviewer (Job B) — รีวิว (`/scrutinize`)
- verdict: **CHANGES_REQUESTED** — 1 minor + 3 nit
- **minor เป็นความผิดของ reviewer เอง และมันประกาศเช่นนั้น** — D8 สั่งให้ `export` และ Out-of-scope
  ห้ามแตะ `Activation.tsx` เกินนั้น **จึงไม่มีทางทำให้ถูกได้เลยตามกฎที่ตัวเองเขียน** · reviewer
  **ยกข้อห้ามของตัวเอง** ให้แยก `REASON_TEXT` ออกเป็นโมดูล
- มันเจอเหตุผลข้อสองที่ implementer ไม่ได้พูดถึง: `LicenseCard.tsx` เป็น **import จาก `components/`
  ไป `pages/` ตัวเดียวในทั้ง SPA** — ทิศทางพึ่งพากลับด้าน
- **รัน mutation ของตัวเอง 3 ตัวที่ไม่ทับของ implementer เลย แดงหมด** · ที่สำคัญที่สุดคือ **M2**:
  เปลี่ยน `devices.py:861` จากอ่าน `current_state().max_meters` สดๆ เป็นค่าตายตัว — นั่นคือครึ่ง
  "มีผลทันทีไม่ต้อง restart" ของเกณฑ์ข้อ 1 (ADR 0001) **ซึ่งไม่มีเทสตัวไหนคุมอยู่**
- **harness ของ reviewer เองเกือบทิ้งขยะไว้:** `write_text` แอบเปลี่ยน line ending ของ `service.py`
  จาก LF เป็น CRLF ทั้ง 264 บรรทัด · **hash จับได้ `git status` จับไม่ได้** — ตรงกับ memory
  `mutation-probe-can-leave-the-mutation-on-disk`

**ควรถูกจับที่ด่านไหน (ต่อ problem):**
- minor (eslint warning + import กลับด้าน) — **โจทย์ Job A** · reviewer รับเองว่าเป็นข้อจำกัดที่ตัวเองสร้าง
- nit ทั้งสาม — **ไม่มี** · Job B เท่านั้นที่จับได้ และทั้งสามไม่ต้องแก้

### 4. รอบแก้ (1 รอบ)
- แยก `web/src/licenseReasons.ts` ถือเฉพาะ `REASON_TEXT` · `reasonText()` **อยู่ที่เดิม ไม่ export**
  พร้อม fallback แบบ Limited Mode ครบ
- **diff เนื้อ map ทั้ง 7 รายการก่อนแตะอะไรเลย** ได้ `MAP ENTRIES IDENTICAL` — การย้ายโค้ดคือจุดที่
  ค่าเปลี่ยนโดยไม่มีใครเห็นได้ง่ายที่สุด
- `pnpm lint` **เงียบสนิท ไม่มี output เลย** ไม่ใช่แค่ exit 0 · import จาก `components/` ไป `pages/`
  หายไปทั้ง SPA
- **พิสูจน์ว่าไม่ต้องรัน mutation ซ้ำ แทนที่จะอ้าง** — `git diff --stat -- app/` แสดงแต่ไฟล์เทสสองไฟล์
  ที่จำนวนบรรทัดเท่ารอบแรกเป๊ะ และ `app/src/` ว่าง ⇒ ไม่มีบรรทัด Python ที่รันได้ขยับเลย

### 5. reviewer (Job B รอบ 2) — **APPROVED**
- diff เนื้อ map จาก `git show HEAD:` เทียบกับโมดูลใหม่เอง (normalize เฉพาะคำว่า `export`): **diff ว่าง**
- ยืนยันว่า `reasonText` ไม่มี export และ grep ทั้งรีโปเจอที่เดียวคือ*คอมเมนต์*ที่อธิบายว่าทำไมจงใจไม่ใช้
- ตอบคำถามที่ orchestrator ถามว่าโมดูลใหม่จะล่อให้คนถัดไปย้าย `reasonText()` ตามเข้าไปไหม:
  **docstring ห้ามไว้แล้ว** — *"The map is shared; the fallbacks are not … Keep it that way."*
  และย้ำอีกสองที่ที่จุดเรียกใช้ · **invariant เดียว ประกาศสามที่** ปลอดภัยกว่าตอนที่ map อยู่บนหน้าเพจ

## ต้นทุน (เวลา + tool calls + tokens)

| สเตจ | เวลา | tool calls | tokens (ดูหมายเหตุ) |
|---|---|---|---|
| reviewer Job A | 9.4 นาที | 45 | 132,089 |
| implementer (build) | 14.0 นาที | 62 | 135,508 |
| reviewer Job B | 6.4 นาที | 17 | 186,332 |
| รอบแก้ 1 — implementer | 3.9 นาที | 10 | 152,086 |
| รอบแก้ 1 — reviewer Job B | 1.5 นาที | 5 | 197,696 |

**หมายเหตุ tokens:** `subagent_tokens` บวกกันตรงๆ ไม่ได้ — double-count ข้าม SendMessage resume
(memory `subagent-token-counts-are-not-additive`)

## ✅ skill ที่เรียกจริง — ยืนยันจาก transcript (tamper-proof)

```
=== IMPLEMENTER (784K) ===
      1 "skill":"antd-ui"
Skill calls: 1

=== REVIEWER (836K) ===
      1 "skill":"draft-delegation-prompt"
      1 "skill":"scrutinize"
Skill calls: 2
```

**สะอาด** — implementer เรียก `antd-ui` ตัวเดียวที่โจทย์บังคับ และไม่ได้เรียกสกิลรีวิวมาตรวจงานตัวเอง ·
reviewer เรียก `draft-delegation-prompt` + `scrutinize` อย่างละครั้ง · ไม่มีใคร spawn `docs-researcher`

## Commit

`2f5cced` — **feat: replace a working licence from Settings (issue 011)**

⚠️ **ข้อสังเกตเรื่องความสะอาดของ commit:** `git add -A` ตามที่ pipeline กำหนด กวาด
`.claude/run-logs/issue-010.md` (audit log ของใบก่อน) เข้ามาใน commit นี้ด้วย · ไฟล์ควรอยู่บน branch นี้
อยู่แล้วจึงไม่เสียหาย แต่ commit message ไม่ได้พูดถึงมัน · ไม่ rewrite history เพื่อเรื่องนี้

## ของที่ยังค้าง (nit — ไม่บล็อก เจ้าของตัดสินตอน merge)

1. **401 ระหว่างกดเปลี่ยน license** อ่านเหมือนโค้ดถูกปฏิเสธ · reviewer ชี้ว่าเล็กกว่าที่ implementer
   รายงาน — `request()` เรียก `clearSession()` ทันทีเมื่อเจอ 401 ที่มี token จึงเด้งไป Login เลย
   การ์ดถูก unmount ก่อนที่ข้อความจะถูกอ่าน
2. **assert ตัวที่สองของ R6 เข้าไม่ถึงภายใต้ mutation ของตัวเอง** (assert 403 ยิงก่อน) แต่เก็บไว้
   เพราะมันแยกแยะได้ในรูปแบบอนาคตที่ย้ายการตรวจ role ไปหลังการ activate
3. **`onActivated()` เป็น fire-and-forget** การ์ดจึงแสดง license เก่าอยู่หนึ่ง round-trip ข้างๆ toast
   ที่บอกว่าสำเร็จ · รูปเดียวกับ `Activation.tsx:78` เดิม

**สิ่งที่ reviewer ยืนยันแล้วว่าไม่ต้องทำอะไร** — "การเปลี่ยน license ไม่ยิง listener เลย" ปลอดภัยจริง
เพราะทุกอย่างที่อิง license อ่านสดผ่าน `current_state()` และ **หลักฐานถาวรมีอยู่แล้วคือ ADR 0001**
("ห้าม cache สถานะที่มาจาก license ตอน import/startup") การเขียนเพิ่มจะเป็นการพูดซ้ำ ADR

## วิธีตรวจซ้ำด้วยตัวเอง (audit)

    d="C:/Users/HP/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents"
    grep -o '"skill":"[a-z0-9:_-]*"' "$d/agent-a67dc97bb279ae35d.jsonl" | sort | uniq -c   # implementer
    grep -o '"skill":"[a-z0-9:_-]*"' "$d/agent-a6cdb50827f46442b.jsonl" | sort | uniq -c   # reviewer
    grep -c '"name":"Skill"' "$d/agent-a67dc97bb279ae35d.jsonl"
