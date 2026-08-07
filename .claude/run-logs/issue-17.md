# Issue #17 — M5b-1: Load Profile page

**สถานะ: DONE** · commit `c3d4189` · branch `feature/load-profile` · รอบรีวิว **2**

---

## ขั้นตอนที่เดินจริง

| ขั้น | agent | เวลา |
|---|---|---|
| Job A — ร่าง delegation prompt | reviewer | 10.8 นาที |
| Implement รอบ 1 | implementer | 18.4 นาที |
| Job B รอบ 1 — **CHANGES_REQUESTED** (เอกสารล้วน) | reviewer | 6.9 นาที |
| Fix รอบ 1 | implementer (ตัวเดิม) | 2.2 นาที |
| Job B รอบ 2 — **APPROVED** | reviewer (ตัวเดิม) | 2.3 นาที |
| **รวม** | | **40.6 นาที** |

**Track: full** · ใบแรกใน M5 ที่แตะ `web/` จึงมีสอง gate
**เทส 737 → 754** (+17) · `pnpm lint` + `pnpm build` เขียว

**token (วัดจาก transcript):** reviewer 108,491 output / 177 turn · implementer 103,023 output / 263 turn · cache read รวม 47.6 M

---

## สกิลที่ถูกเรียกจริง — ยืนยันจาก transcript

| agent | สกิล |
|---|---|
| reviewer | `draft-delegation-prompt` |
| implementer | `tdd` · `fastapi` · `antd-ui` |

ครบตามที่ delegation prompt บังคับทั้งสามตัว · ไม่มี review pass ซ้ำซ้อน

---

## สิ่งที่ Job A จับได้ก่อนเริ่มเขียนโค้ด

**ใบ issue นับคอลัมน์ผิด — บอกสี่ ของจริงห้า**

ใบ #17 เขียนว่า "Four of those are empty for the only model in service today" · Job A ไปดู `smw110.py:79-89` แล้วพบว่า driver map แค่เจ็ดคอลัมน์ (`import_active_kwh`, `volt_l1/l2/l3`, `current_l1/l2/l3`) เหลือ **ห้า** ที่เป็น `None` เสมอ — สี่ตัวที่ #15 เพิ่ม **บวก `freq`** ซึ่ง `smw110.py:432` hard-set เป็น `None`

**ที่มาของความผิด:** ใบไปลอกรายการ "คอลัมน์ที่เพิ่มใหม่" จาก SPEC §3.5 มาแทนที่จะดูว่า driver map อะไรจริง ๆ · และความผิดนี้**แพร่ไปแล้วสองต่อ** — จาก `models.py:194-200` → SPEC §3.5 → ใบ #17 · reviewer สั่งแก้ที่ต้นทาง (`models.py` docstring) ในรอบแก้

---

## กับดักที่ delegation prompt ปิดไว้ตรง ๆ

เกณฑ์ "คอลัมน์ที่ไม่มีแหล่งข้อมูลต้องแสดงเป็นช่องว่าง ไม่ใช่ `0`" พังได้ง่ายมากใน JSX และทั้งสองวิธีที่คนเขียนโดยสัญชาตญาณผิดคนละทาง:

| เขียนแบบ | ผลที่ผิด |
|---|---|
| `value \|\| NOTHING` | `0` จริงกลายเป็นขีด — 0 แอมป์อ่านเป็น "ไม่มีข้อมูล" |
| `value ?? NOTHING` | พิมพ์ `0` ตรงที่ควรเป็นขีด (เพราะ raw number ไม่ใช่ null) |
| **`value == null`** | จับ `null` และ `undefined` เท่านั้น — ถูก |

prompt สั่งให้ทุกคอลัมน์ผ่าน helper ตัวเดียว ห้าม inline · reviewer ตรวจแล้วพบ `render: num(...)` **12 ตัวพอดีสำหรับ 12 คอลัมน์วัด** ไม่มี inline ที่ไหน

---

## ปัญหาที่ไม่มีเครื่องมืออัตโนมัติจับได้ — และการตัดสิน

**`web/` ไม่มี test runner** ดังนั้นเกณฑ์ null-rendering ข้างบน**ไม่มีเทสใดเฝ้าเลย** ถ้าวันหน้ามีคนแก้เป็น `||` ทั้ง `pnpm lint` และ `pnpm build` จะยังเขียว

**คำตัดสินของ reviewer: รับได้ตามที่ส่งมา ไม่ต้องแก้** — เพราะ implementer เขียนคอมเมนต์ไว้ที่ตัว helper (`LoadProfile.tsx:32-43`) อธิบายว่า `value == null` เป็นบรรทัดที่แบกน้ำหนัก และระบุว่า `||` กับ `??` จะพังคนละแบบยังไง · คนที่จะแก้เป็น `||` ต้องแก้ใต้คอมเมนต์ที่บอกว่าการทำแบบนั้นเปลี่ยน 0 แอมป์เป็นขีด · การตั้ง test runner อยู่นอกขอบเขตใบนี้ และ reviewer บันทึกว่าจะไม่รับ guard-rail ที่อ่อนกว่านี้

---

## Mutation probe

**implementer รันเอง 10 ตัวโดยไม่ถูกสั่ง** (พฤติกรรมที่ mandate เพิ่งเริ่มปลูกเมื่อสองใบก่อน) — ไม่มีตัวรอด:
กลับลำดับเป็นเก่าไปใหม่ · ถอด cap ขนาดหน้า · ไม่ใช้ `limit` · ไม่ใช้ `offset` · ถอด device filter จาก row query · เอา filter logger-1-only ของ v1 กลับมา · ไม่ผูก UTC กลับให้ค่าที่ SQLite คืนมา · แบน null เป็น `0.0` · ตัด null ออกจาก payload · ถอด auth dependency

**ตัวที่มีค่าที่สุดคือ "ถอด device filter จาก row query"** — จับได้เฉพาะที่ assertion ของ items เพราะ **count query เก็บสำเนา clause ของตัวเอง** แปลว่าสอง clause หลุดจากกันได้จนกลายเป็นหน้าที่แถวกับ `total` ไม่ตรงกัน → refactor ให้เขียนครั้งเดียวใช้ร่วมกัน

**reviewer รันเพิ่มอีก 7 ตัวที่ implementer ไม่ได้แตะ** — โดนหมด:
ถอด tiebreak `logger_id` ทั้งอัน · กลับ tiebreak เป็น `desc()` · เปลี่ยนขอบบนจาก `<` เป็น `<=` · ให้ device ที่ไม่มีอยู่คืนหน้าว่างแทน 404 · คำนวณ `total` จาก query ที่แบ่งหน้าแล้ว · ทำลายการใช้ clause ร่วมกัน (ยืนยันคำกล่าวอ้างหลักของ implementer) · ถอด auth ที่ระดับ router

---

## Findings ที่ยืนยันแล้ว ไม่ใช่รับมาเฉย ๆ

- **`freq` ไม่ถูก map จริง** — ไม่อยู่ใน `_MAPPED_CAPTURE_COLUMNS` และ `smw110.py:432` hard-set `None`
- **`test_auth_guard.py` กวาดถึง route ใหม่จริง** — พิสูจน์ด้วย mutation: ถอด dependency แล้วได้ `assert [('GET', '/api/load-profile', 422)] == []` · แปลว่า guard คือสิ่งที่ทำให้ 401 ชนะการ validate พารามิเตอร์
- **`end == start` → 422 ไม่ over-reach** — ช่วงครึ่งเปิด `[X, X)` เลือกอะไรไม่ได้เลย และหน้าเว็บส่งค่าแบบนั้นไม่ได้เพราะ `to.add(1,"day").startOf("day")` มากกว่า `from.startOf("day")` เสมอ
- **ADR 0007 ไม่ถูกละเมิด** — ADR ห้ามค่า live/instantaneous ส่วนทุกแถวที่หน้านี้แสดงคือ interval ที่มิเตอร์บันทึกเอง

---

## สิ่งที่ v1 ทำแล้วจงใจไม่พอร์ตมา

1. **merge Logger 2 เข้า Logger 1 ด้วย `LEFT JOIN` + `COALESCE`** (`repository.py:207-236`) — SPEC §3.5 บันทึกว่าผิด: บน Premier 550 สอง logger map register คนละตัวลงคอลัมน์เดียวกัน การ merge จึงทับค่ากันเงียบ ๆ
2. **filter เหลือ logger 1 อย่างเดียว** (`index.tsx:49`) — ซ่อนแถวที่มีอยู่จริง
3. **ปล่อยช่วงวันว่างแล้วแปลว่า "ทั้งหมด"** — ที่ retention 90 วันคือ ~8,640 แถวต่อมิเตอร์ และ ~259,000 แถวทั้งไซต์ ส่งเข้า browser ในการตอบครั้งเดียว
4. **clamp ปฏิทินย้อนหลังไว้ 90 วัน** (`index.tsx:52-56`) — v2 ยังไม่มี retention job จนถึง #19 การ clamp ตอนนี้จะซ่อนแถวที่อยู่ในตารางจริง

---

## ข้อบกพร่องที่รอบรีวิวจับได้ (ทั้งคู่เป็นเอกสาร)

**1. docstring ของ `App` ถูกทำให้กำพร้า** — การแทรก `type Page`, `PAGES`, `toPage` เข้าไประหว่าง docstring 19 บรรทัดเรื่องลำดับ routing กับ `export default function App()` ทำให้ docstring ไปเกาะ union สามค่า และ component ไม่เหลือคำอธิบาย · **ไม่มีเครื่องมือไหนจับได้** — `pnpm lint` และ `pnpm build` ผ่านทั้งคู่ เพราะมันถูกต้องทางไวยากรณ์ทุกประการ

**2. `devices.py:8-11` พูดสิ่งที่เป็นเท็จ** — *"from M3-4 until M5 that table is empty, because nothing writes to it at all"* · #15 ทำให้ผิดไปแล้วทั้งสองครึ่ง (`devices.py:71` import `read_and_store_load_profile` และ `read_now` เขียนแถวลงตารางนั้น) · implementer จับได้แต่**ไม่แก้** เพราะ out-of-scope list ห้ามแตะไฟล์นั้น → reviewer ยกเลิกข้อห้ามของตัวเองเฉพาะประโยคนั้น

นี่คือรูปแบบเดียวกับ #16: **รายการห้ามที่ reviewer เขียนเอง กลายเป็นสิ่งที่ขวางทางแก้ที่ถูกต้อง** — ต่างกันที่ #16 ขวางการแก้บั๊กจริง ส่วนใบนี้ขวางแค่การแก้เอกสาร

---

## สิ่งที่ **ไม่ได้** ทำ

- **ไม่ได้แตะมิเตอร์จริง** — fake driver ใน `conftest.py` เป็น autouse ไม่มีอะไรที่เขียนใหม่ทะลุไปได้
- ไม่ได้เพิ่ม dependency ทั้งสองฝั่ง · ไม่ได้เพิ่ม test runner ให้ `web/`
- ไม่ได้ทำ CSV, `resolution` parameter, ปุ่ม Read now บนหน้านี้ หรือ placeholder ที่กดไม่ได้

---

## วิธีตรวจสอบเอง

```bash
git show c3d4189 --stat
cd app && pytest -n auto                     # ต้องได้ 754 passed
cd web && pnpm lint && pnpm build
grep -c "render: num(" src/pages/LoadProfile.tsx      # ต้องได้ 12
grep -n "|| NOTHING\|?? NOTHING" src/pages/LoadProfile.tsx   # ต้องเจอเฉพาะในคอมเมนต์
```
