# Issue #37 — สองหน้า Data-out Destination (Database + File Upload) แบบไม่มี backend

**สถานะ: DONE** · commit `e7b0edc` · branch `feature/light-modules` · **รีวิวรอบเดียวผ่าน**

## สิ่งที่ทำ

สองหน้าสำหรับ admin เท่านั้น ที่มาก่อนโมดูล Data-out (SPEC §3.8) — **ไม่มี transport อยู่ข้างหลัง
เลย** และงานจริงคือ*ทำให้ไม่มีใครเข้าใจผิดว่ามันทำงาน* ไม่ใช่การสร้างฟอร์ม

## สกิลที่เรียกจริง — ตรวจจาก transcript

| agent | สกิล |
|---|---|
| reviewer `a4e461c613e17b717` | `draft-delegation-prompt` ×1 (Job A) · `scrutinize` ×1 (Job B) |
| implementer `a96192a8efac7fddc` | `antd-ui` ×1 |

ครบตาม mandate · ไม่มีรอบรีวิวซ้ำซ้อน · `/tdd` ไม่ถูกเรียกตามที่ prompt ห้าม (`web/` ไม่มี runner)

## การตัดสินใจที่คมที่สุดของ Job A

**ปุ่มเดียวคือ `Clear`** — เกณฑ์บอกว่าปุ่มต้องกดได้และให้ผลตอบกลับ **โดยไม่อ้างว่าเชื่อมต่อสำเร็จ
หรือบันทึกแล้ว** · คำกริยาอื่นทุกคำ (Save, Test connection, Connect, Apply, Verify) เป็นคำสัญญา
ที่หน้านี้ทำไม่ได้ และป้ายที่สัญญาคู่กับ toast ที่ถอนคำ คือความล้มเหลวแบบ "ดูเหมือนใช้งานได้"
ที่ issue นี้มีอยู่เพื่อป้องกันพอดี · `Clear` เป็นสิ่งเดียวที่หน้านี้ทำได้จริง — และยังเป็นวิธีที่
operator ใช้ล้างรหัสผ่านออกจาก state ด้วย

**เมนูเป็นกลุ่มชื่อ "Data-out Destination"** ไม่ใช่รายการ "Database" ลอย ๆ · เพราะ "Database"
ที่วางอยู่ใต้ "Devices" (ซึ่งใช้ไอคอน `DatabaseOutlined` อยู่แล้ว) จะอ่านว่า *ฐานข้อมูลของแอป*
ซึ่งคือความเข้าใจผิดที่ ADR 0016 มีอยู่เพื่อป้องกัน

**ห้ามใช้ `<Space>` ครอบป้ายเตือน** — `Space` ห่อลูกทุกตัวด้วย `div` ⇒ `position: sticky` จะผูกกับ
wrapper สูงเท่าเนื้อหา แล้ว**เงียบ ๆ ไม่ทำงาน** และรีวิวโค้ดมองไม่เห็น · Job A ยืนยันด้วยการ
server-render อ่าน markup จริง ไม่ใช่เดา

## หลักฐาน — C1–C14 ผ่านครบทั้งสองครึ่งทุกแถว

harness ตรวจสอบตัวเองก่อน: รันกับ `Settings.tsx` ได้ **1686 ตัวอักษร ตรงกับที่ Job A วัดไว้เอง**
⇒ พิสูจน์ว่าเครื่องมือถูก ไม่ใช่แค่หน้าเว็บถูก

| check | สิ่งที่พิสูจน์ |
|---|---|
| **C10** | bundle โดยไม่ external `../api` ⇒ ไม่มี `fetch(`/`localStorage`/`console.` เลย · ลอง import จริง → `["fetch(", "localStorage"]` โผล่ทันที ⇒ **คำรับประกันเรื่องรหัสผ่านเป็นกลไก ไม่ใช่คำพูด** |
| **C4** | `sticky=88 < alert=172 < card=1330` ไม่มี `ant-space` คั่น · ใส่ `Space` แล้ว offset เลื่อนเป็น 275/359/1529 ⇒ กับดักที่ Job A ทำนายไว้เกิดขึ้นจริง |
| C11 | ไม่มี deprecation warning เลยทั้งสองหน้า (ใช้ `title`/`orientation` ไม่ใช่ `message`/`direction`) |
| C12a/C12b | คู่ตรวจด้านเดียว — ถ้ามีข้างเดียวจะถูกทำให้ผ่านได้ด้วยการลบสิ่งที่มันควรเฝ้า |

mutation ทุกตัว `cp` สำรอง → แก้ → รัน → กู้ → **ยืนยันด้วย `sha256sum`** เทียบ hash ก่อนแก้

## reviewer ไปปิดช่องที่ทั้งไปป์ไลน์มองข้าม

**`<Form>` เรนเดอร์ `<form>` จริง ⇒ กด Enter ในช่องรหัสผ่านอาจยิง GET เอา `password=` ไปโผล่ใน
URL และประวัติเบราว์เซอร์** — ช่องรั่วที่ `grep` มองไม่เห็นเพราะไม่มีโค้ดผิดสักบรรทัด

เปิดซอร์สที่ติดตั้งจริงมายืนยันว่าปิดอยู่: `@rc-component/form/lib/Form.js:136-138` เรียก
`preventDefault()` **และ** `stopPropagation()` · `antd/lib/button/button.js:70` ตั้ง
`htmlType = 'button'` เป็นค่าเริ่มต้น ⇒ ปุ่ม `Clear` ก็ submit ไม่ได้

⇒ **D12f เป็นจริงบนเส้นทางการโต้ตอบจริง ไม่ใช่แค่เพราะไม่มีโค้ดที่ผิด**

และมันรัน C13 เองแทนที่จะรับคำอธิบาย: `grep` exit 1 → เติมคำว่า "Transport Endpoint" ลงคอมเมนต์
→ exit 0 → กู้ → `sha256sum -c` OK → exit 1 · บวกตรวจว่าแนวคิดไม่เล็ดลอดผ่านคำอื่น
("connection"/"target"/"server") — เจอ 2 จุดแต่อยู่ในคอมเมนต์ที่*กำลังอธิบายความเข้าใจผิดที่
กำลังหลีกเลี่ยง* ซึ่งเป็นการใช้ที่ถูก

## นิต 2 ข้อ — orchestrator แก้เอง ไม่ส่งกลับอีกรอบ

1. **`<p>` ในคำอธิบาย Alert พก `margin-block: 1em` ของเบราว์เซอร์มาด้วย** — reviewer ตรวจแล้วว่า
   `web/src/index.css` reset แค่ `html, body, #root` · ไม่มีการ import `antd/dist/reset.css` ·
   และ `antd/lib/alert/style/index.js` ไม่มีกฎที่เล็ง `p` เลย ⇒ ได้ที่ว่างเปล่า ~1em บนธีมที่
   ทั้งชุดเลือก compact มา → เปลี่ยนเป็น `<div style={{display:"grid", gap:8}}>` + `margin: 0`
2. **`<Space>` ครอบลูกตัวเดียว** — ตกทอดมาจาก `ExportFormat.tsx` ที่มันคั่นสองอย่างจริง แต่ที่นี่
   ลูกตัวที่สองหายไปแล้วยัง wrapper ค้าง → ตัดทิ้ง เอา `Form` ใส่ `Card` ตรง ๆ

*(reviewer ระบุว่านิต 2 เป็นความผิดของ prompt ตัวเองบางส่วน — D5 เขียนว่า "ใช้ `Space` ข้างใน
`Card` ได้" ซึ่งเป็นการอนุญาตที่ implementer รับไปอย่างสมเหตุสมผล)*

หลังแก้: `pnpm lint` สะอาด · `pnpm build` ผ่าน · ข้อความ D6/D7 ไม่ถูกแตะ

## Gate

```
pnpm lint                →  clean
pnpm build               →  ✓ 3096 modules
python -m pytest -n auto →  1478 passed, 16 skipped   (เท่า baseline เป๊ะ)
ruff format --check .    →  195 files already formatted
ruff check .             →  All checks passed!
grep -rn "console\." web/src/  →  0 hits (เท่าเดิม)
```

## ข้อจำกัดของหลักฐาน — บันทึกไว้ตรง ๆ ไม่ใช่ข้อบกพร่อง

- **ป้ายเตือนติดหนึบตอนเลื่อนจอจริงไหม — พิสูจน์ไม่ได้ด้วยเครื่องมือที่มี** · ไม่มี jsdom ไม่มี
  เบราว์เซอร์ และ `renderToStaticMarkup` ไม่คำนวณ layout ⇒ สิ่งที่รันได้คือลำดับ DOM และการไม่มี
  กับดัก · ส่วนที่เหลือยืนอยู่บนกลไก CSS ล้วน ๆ · **ควรชำเลืองดูในเบราว์เซอร์หนึ่งครั้งตอน merge**
- `form.resetFields()` ในปุ่ม `Clear` **ไม่มี check ไหนยึดไว้** และยึดไม่ได้ — การคลิกต้องมี DOM
- `PROTOCOL_OPTIONS` ยึดด้วย C7 ซึ่งเป็น source check เท่านั้น เพราะ `Select` ไม่ render options
  ตอน SSR · สัญญาณ "FTPS/SFTP อยู่ใน markup" ที่เห็นมาจาก **placeholder ของช่อง port** ไม่ใช่จาก
  options ⇒ C7 เป็นด่านเดียวจริง ๆ และเขียนถูกแล้วว่าเป็น source check

## วิธีตรวจหลักฐานเอง

```bash
d=~/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents
grep -o '"skill":"[a-z0-9:_-]*"' $d/agent-a4e461c613e17b717.jsonl | sort | uniq -c
grep -o '"skill":"[a-z0-9:_-]*"' $d/agent-a96192a8efac7fddc.jsonl | sort | uniq -c
```
