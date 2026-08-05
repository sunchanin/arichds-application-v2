# Audit log — Issue #2: M2-2 User Management (admin CRUD, password reset, เปลี่ยนรหัสตัวเอง)

รัน: 2026-08-05 · branch: `feature/authentication` · ผลลัพธ์: **APPROVED** · รอบรีวิว: **2** · commit: `7b75a3a`

## ทำอะไรไปบ้าง (ทีละขั้น)

1. **reviewer (Job A) — สร้าง delegation prompt** · TDD required: **yes** (กฎป้องกันมี branch เยอะและเกี่ยวกับความปลอดภัย)

   งานที่มีค่าที่สุดของใบนี้คือ **การไปขุด v1 จริงแทนการเดา** — issue เขียนว่า "reproduce กฎกันล็อกตัวเองของ v1"
   reviewer อ่าน `router_users.py` / `user_service.py` / `auth_service.py` / `repository.py` / `schemas.py`
   และ sequence diagram แล้วพบว่า **v1 แทบไม่มีกฎที่คนคิดว่ามี**:

   | กฎที่มักถูกสันนิษฐาน | ความจริงใน v1 |
   |---|---|
   | กันลบ admin คนสุดท้าย | **ไม่มี** — ไม่เคยนับ admin |
   | กันลดสิทธิ์ตัวเอง | **ไม่มี** — `update_user` รับ `role_id` ของตัวเองได้ |
   | ป้องกัน admin คนแรก (id 1) | **ไม่มี** — แถวธรรมดา |
   | admin reset รหัส → revoke session เป้าหมาย | **ไม่มี** — ปล่อย session ค้างทั้งหมด (v1 พลาด ไม่ใช่ดีไซน์) |

   ที่ v1 **มี**จริง: self-deactivation 400 (INV-AUTHZ-02) · cascade revoke ตอน deactivate (INV-DATA-02) ·
   change-password ต้องใส่รหัสเดิม + revoke token อื่น (INV-DATA-04) · username ซ้ำ 409 · ไม่เจอ 404

   → ถ้าปล่อยให้ implementer อ่านเอง มีโอกาสสูงที่จะ **พอร์ตช่องโหว่มาด้วย** (admin reset ไม่ revoke)
   หรือเดาว่ามีกฎที่ไม่มีจริง

2. **การตัดสินใจสำคัญที่ reviewer ทำแทน (D1–D12)**
   - **เพิ่มกฎกันล็อกตัวเอง 3 ข้อที่ v1 ไม่มี** พร้อมเหตุผลจากบริบทที่ต่างกันจริง: v1 เป็น demo ที่มี MySQL
     console อยู่ข้างหลัง แต่ v2 ลงเครื่องลูกค้าโดย**ไม่มีทางกู้คืนเลย** (`tools/arichds_vendor.py` มีแค่
     keygen/sign/fingerprint — "ทางหนีไฟผ่าน vendor CLI" ที่ SPEC §3.2 อ้างถึง **ยังไม่มีอยู่จริง**)
   - **ไม่ต้องนับ admin** — ทุก endpoint ต้องมี admin เป็นผู้สั่ง และผู้สั่งลบ/ลดสิทธิ์ตัวเองไม่ได้
     ⇒ "เหลือ admin ≥ 1" เป็นทฤษฎีบท ไม่ใช่เงื่อนไขที่ต้องเช็ค · count query = dead code
     → ล็อกด้วยเทสที่เดินทุกเส้นทางแทน (`test_the_admin_count_can_never_reach_zero`)
   - **wrong current password = 400 ไม่ใช่ 401 ของ v1** เพราะ `api.ts` ล้าง session ทุกครั้งที่เจอ 401
     ที่มี token → ใช้ 401 = ผู้ใช้พิมพ์ผิดครั้งเดียวถูกเตะออก
   - **admin reset revoke ทุก token ของเป้าหมาย** (แย้ง v1) เพราะ path นี้มีไว้สำหรับลืมรหัส/สงสัยถูกเจาะ
   - **role change ไม่ revoke อะไร** เพราะ `require_admin` อ่าน role จาก DB ไม่ใช่ JWT claim → ลดสิทธิ์มีผลทันที

3. **implementer — ลงมือ (`/tdd`)** · เทส **271 → 313 (+42)**
   - ไฟล์ใหม่: `api/users.py`, `tests/test_api_users.py`, `web/src/pages/Users.tsx`, `components/ChangePasswordModal.tsx`
   - **รายงานความไม่สมบูรณ์ของตัวเองโดยไม่มีใครถาม**: เทส 403 sweep / 409 / 404 / 422 เขียน*หลัง*โค้ด
     (เกิดจาก router guard + type ที่ reuse มา) จึงเขียวตั้งแต่แรก — flag ว่าเป็น characterization ไม่ใช่ TDD
     และมีเทส 1 ตัว "weakly green" (เขียวเพราะ endpoint ยัง 404)
   - เจอเองระหว่าง self-check: หน้า Users กลืน 403 `LICENSE_INVALID` เป็น toast → แก้ให้ reload
     กลับหน้า Activation เหมือน `Monitor.tsx` (เพราะ `/api/users` จงใจไม่อยู่ใน Limited Mode allow-list)
   - annotate SPEC §3.2 ว่าทางหนีไฟ vendor CLI **ยังไม่ได้ทำ** แทนที่จะลบประโยคทิ้ง

4. **reviewer (Job B รอบ 1) — CHANGES_REQUESTED** (1 minor)
   - ไม่เชื่อหลักฐานง่าย ๆ: ตอนตรวจ "ลบ user แล้ว session ตาย" มันชี้ว่า **401 ไม่ใช่หลักฐาน** เพราะ
     ต่อให้ FK ปิดอยู่ `resolve_token` ก็จะตกที่ `session.get(User) is None` อยู่ดี → ไป query
     `PRAGMA foreign_keys` บน engine จริงของ API ได้ **1** และเห็น `user_tokens` 2 → **0**
   - minor: `set_password` **commit 2 ครั้ง** (เขียนรหัส → commit → revoke → commit) ⇒ ถ้า crash คั่นกลาง
     รหัสเปลี่ยนแล้วแต่ session เก่ารอดได้ถึง 8 ชม. — บนเส้นทางที่มีไว้ปิดช่องนั้นพอดี
     พิสูจน์โดย **instrument event `commit` ของ session factory จริง** นับได้ 2 ครั้ง (v1 ทำ atomic)
   - ตัดสิน 3 ข้อที่ implementer รายงานตัวเอง: **ผ่านทั้งหมด** — โดยเฉพาะเรื่อง TDD เขียนว่า
     *"การรายงาน characterization test ว่าเป็น characterization คือพฤติกรรมที่ควรส่งเสริม"*

5. **รอบแก้ (cycle 2)** — ลบ commit กลางออก 1 บรรทัด · implementer instrument เองซ้ำ ยืนยัน 2 → 1 commit
   ทั้งสองเส้นทาง · เพิ่ม docstring 2 จุดกันคนแยก transaction กลับ (รวมถึงประกาศว่า `revoke_user_tokens`
   commit ของที่ caller staged ไว้ด้วย — coupling ที่ไม่ชัดในตัวเอง)
   - reviewer ตรวจสิ่งที่ commit count พิสูจน์ไม่ได้: **rollback กลางคัน** แล้วยืนยันว่า**ทั้งสองการเขียนถูกยกเลิก**
     (รหัสไม่เปลี่ยน + token ยังมีชีวิต) = atomic จริง ไม่ใช่แค่ commit น้อยลง → **APPROVED**

## ✅ skill ที่เรียกจริง — ยืนยันจาก transcript

⚠️ **ตรวจไม่ได้** — เหมือน issue #1: transcript ของ subagent ทั้งสองตัวเป็นไฟล์ **0 byte**
(`a0fb6014537b31bc9.output`, `ae2bd8715be74f4f3.output`) ขณะที่ agent ประเภทอื่นใน session เดียวกัน
เขียน transcript ได้ปกติ → grep ได้ 0 ทั้งที่ไม่ได้แปลว่าไม่มีการเรียก **ไม่บันทึกเป็น process miss**

หลักฐานทางอ้อมที่หนักแน่น: implementer อ้างถึงเนื้อหาของ `antd-ui` skill โดยตรง (ตรวจ `destroyOnHidden`
กับ `node_modules/antd/es/modal/interface.d.ts` เองเพราะ skill สั่งห้ามใช้ context7) และรายงาน red→green
ราย behaviour พร้อมแยกแยะว่าอันไหนเป็น characterization

## Commit

`7b75a3a` — `feat: user management — admin CRUD, password reset, change own password (#2)`

## Nit คงค้าง (ไม่ block — ตัดสินตอน merge)

1. `web/src/pages/Users.tsx:161-170` — ช่อง Role มี `Select` ที่แสดง "admin" อยู่แล้ว บวก `<Tag>admin</Tag>` ซ้ำข้าง ๆ
2. `web/src/theme.ts:5` — คอมเมนต์ภาษาไทย (อ้าง SPEC) มีมาตั้งแต่ M1 · เป็นคอมเมนต์ ไม่ใช่ UI string
   · reviewer สแกนทั้ง `web/src` ยืนยันว่าเป็นภาษาไทยจุดเดียวที่เหลือ
3. `pnpm build` เตือน chunk > 500 kB — มีมาก่อนหน้านี้ ไม่เกี่ยวกับ slice นี้

## วิธีตรวจซ้ำด้วยตัวเอง (audit)

    T="%LOCALAPPDATA%/Temp/claude/C--Users-HP-Documents-Work-arichds-application-v2/e6d49371-8cab-471a-be73-524d52bc5b24/tasks"
    grep -o '"skill":"[a-z-]*"' "$T/a0fb6014537b31bc9.output" | sort | uniq -c   # reviewer (0 byte)
    grep -o '"skill":"[a-z-]*"' "$T/ae2bd8715be74f4f3.output" | sort | uniq -c   # implementer (0 byte)
    git show 7b75a3a --stat
