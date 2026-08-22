# Issue #36 — Energy Summary: โหมดวันเดียว + แถวรวม

**สถานะ: DONE** · commit `3a09357` · branch `feature/light-modules` · **รีวิวรอบเดียวผ่าน**

## สิ่งที่ทำ

ปุ่ม `Segmented` สลับ **Single day / Range** บนแท็บ Summary Report และ **แถวรวม**ท้ายตาราง ·
งานฝั่งหน้าเว็บล้วน — endpoint รับช่วงวันเดียวได้อยู่แล้ว (`energy.py:240-250`) จึงไม่แตะ `app/`
แม้แต่ไฟล์เดียว

ตรรกะการบวกแยกออกเป็นโมดูลใหม่ `web/src/energyTotals.ts` ที่ import **แค่ type เท่านั้น**

## ปัญหาที่ต้องแก้ก่อน: `web/` ไม่มี test runner และห้ามเพิ่ม

การเพิ่ม vitest เป็นการตัดสินใจคนละเรื่องที่ issue ด้าน UI ไม่ควรลากมาตัดสิน ⇒ reviewer หาทาง
พิสูจน์แบบอื่น: **แยกเลขคณิตออกเป็นโมดูลบริสุทธิ์แล้วรันด้วย `node` เปล่า ๆ**

มันไม่ได้เดาว่าทำได้ — ทดลองก่อน: เขียน `.mjs` ที่ import `.ts` ซึ่ง `import type` จากไฟล์ที่
throw ตอนโหลด แล้วยืนยันว่าไฟล์นั้นไม่เคยถูกรัน ⇒ Node 24 ลบ type ทิ้งจริง

## สกิลที่เรียกจริง — ตรวจจาก transcript

| agent | ขนาด | สกิล |
|---|---|---|
| reviewer `a00964ac30f05d1be` | 1 MB | `draft-delegation-prompt` ×1 |
| implementer `a6d0dcaa8c308ce62` | 1 MB | `antd-ui` ×1 |

**ครบตาม mandate** · prompt **ห้ามเรียก `/tdd`** (มันสมมติว่ามี suite ที่ commit แล้ว ซึ่ง `web/`
ไม่มี) และ transcript ยืนยันว่าไม่ได้เรียกจริง ไม่ใช่แค่บอกว่าไม่ได้เรียก · ไม่มีรอบรีวิวซ้ำซ้อน

## TDD

**แบบจำกัดขอบเขต** — red→green ด้วยมือบน harness ที่รันด้วย `node`

Red แรกคือ `Cannot find module … energyTotals.ts` ซึ่ง prompt ระบุไว้เองว่า *"รับได้ในฐานะ red
แรก แต่ไม่ใช่หลักฐานว่า assertion แยกแยะได้ — mutation sweep ต่างหากที่เป็นหลักฐาน"*

## รีวิว — APPROVED รอบเดียว และ reviewer ทำเกินที่สั่งสามเรื่อง

**1. มันรัน React จริงได้ ทั้งที่ทุกคนคิดว่าทำไม่ได้**

implementer รายงานตรงไปตรงมาว่า JSX ไม่ได้ถูกตรวจอะไรเลยนอกจาก type check · reviewer ไป
**server-render ตาราง antd ตัวจริง** ด้วย `createRequire` + `renderToStaticMarkup` (ต้องใช้ CJS
entry เพราะ `es/` ของ antd ใช้ import แบบไม่มีนามสกุล ซึ่ง Node ESM ดิบโหลดไม่ได้)

ผลที่ได้กลายเป็นหลักฐานที่รันจริง ไม่ใช่แค่ผ่าน type:
- 2 วัน → มี `<tfoot>` · **9 `<td>` ตรงกับ 9 คอลัมน์** · ข้อความ `Total 2.25 2.50 0.01 4.76 12.00 22.50 33.50 68.00` ถูกทุกค่าและอยู่ใต้หัวที่ถูก · มี `<strong>` 9 ตัว · ไม่มี React warning
- ข้อมูลว่าง → **ไม่มี `<tfoot>` เลย** เหลือแต่ placeholder ⇒ เกณฑ์ "ต้องไม่ใช่แถวว่างที่ดูเหมือนวัน" ผ่านแบบเห็นจริง

> reviewer เขียนเองว่านี่คือ **ข้อบกพร่องของ prompt ตัวเอง** — มันควรยื่นเทคนิคนี้ให้ implementer
> ตั้งแต่แรกแทนที่จะยอมรับว่าตรวจไม่ได้ · เป็นสิ่งที่ควรพกไปใช้กับงาน `web/` ทุกใบต่อจากนี้

**2. ยืนยันว่ากับดัก invariance ถูกปิดจริง**

ผมตั้งข้อสงสัยว่า C2 กับ C4 รายงานว่า "โดน C1 จับก่อน" ⇒ assertion ของตัวเองไม่เคยยิง

reviewer หา mutation ที่แยกได้จริง — **ให้โมดูลเมิน parameter `render` แล้ว hardcode `.toFixed(2)`**
⇒ ฝั่ง kilo **เขียว** (ตัวเลขถูกหมด C1 จับไม่ได้) แต่ฝั่ง base **แดงเดี่ยว** ⇒ กลไกของเกณฑ์ข้อ 6
ถูกยึดไว้จริง

**บทเรียน**: เกณฑ์แบบ invariance ต้องใช้ mutation ที่รบกวน**ข้างเดียว** ไม่งั้น assertion
สัมบูรณ์ที่จับคู่ไว้จะไม่มีวันได้พูด

**3. รัน mutation sweep ของตัวเอง 8 ตัว** แดงครบ กู้คืนยืนยันด้วย hash · มีสองเป้าที่ implementer
ไม่ได้ probe: `days[0][key]` แทนการ fold และ `days.slice(0, -1)` — จับได้ทั้งคู่

## Nit ที่แก้ก่อน commit

docstring ของ `energyTotals.ts` ชี้ไปที่ *"the issue's delegation prompt, Findings"* ซึ่ง
**ไม่มีอยู่ในรีโป** ⇒ ตัวชี้ที่ห้อยอยู่ · ตัดทิ้ง ประโยคก่อนหน้าอธิบายเหตุผลครบอยู่แล้ว ·
รัน `pnpm lint` ซ้ำหลังแก้

## Gate

```
pnpm lint               →  clean
pnpm build              →  ✓ 3094 modules, 53.40s
ruff format --check .   →  195 files already formatted
ruff check .            →  All checks passed!
python -m pytest -n auto →  1478 passed, 16 skipped
```

ตัวเลข **เท่ากับ #35 เป๊ะ** ตามที่ควรเป็น เพราะไม่ได้แตะ Python เลย — reviewer เทียบกับ
`.claude/run-logs/issue-35.md:91` เอง ไม่ได้เชื่อคำอ้าง

## 🔴 ของที่งอกออกมาและใหญ่กว่า issue นี้

reviewer พบว่า **`pytest -n auto` ที่ `CLAUDE.md` เขียนไว้เป็น gate นั้นเก็บเทสขาดไป 99 ตัว**

```
pytest.exe --collect-only -q  →  1395 collected, 5 errors
python -m pytest --collect-only -q  →  1494 collected, clean
```

สาเหตุแน่ชัด: `app/pyproject.toml:67` ตั้ง `pythonpath = ["src"]` แต่ไม่มี `"."` · ไม่มี
`app/tests/__init__.py` · และ 5 ไฟล์ทำ `from tests.conftest import …` ·
`python -m pytest` เติม CWD เข้า `sys.path` ให้ ส่วน console script ไม่เติม

**มันล้มแบบส่งเสียง ไม่ได้เงียบ** ⇒ ไม่เคยมีอะไร ship ผ่าน gate ที่แอบสั้น · แต่คำสั่งที่เอกสาร
เขียนไว้ผิด และกระทบทุก issue ต่อจากนี้

⇒ เปิดเป็น **`docs/issues/004-pytest-n-auto-is-broken-as-the-documented-gate.md`** แล้ว
เพราะบันทึกไว้ใน audit log เฉย ๆ จะไม่มีใครมาเก็บ

## วิธีตรวจหลักฐานเอง

```bash
d=~/.claude/projects/C--Users-HP-Documents-Work-arichds-application-v2/c36a49e7-7c61-4e55-be90-6cd16b5a941a/subagents
grep -o '"skill":"[a-z0-9:_-]*"' $d/agent-a00964ac30f05d1be.jsonl | sort | uniq -c
grep -o '"skill":"[a-z0-9:_-]*"' $d/agent-a6d0dcaa8c308ce62.jsonl | sort | uniq -c
```
