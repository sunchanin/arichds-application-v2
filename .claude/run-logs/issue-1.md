# Audit log — Issue #1: M2-1 Auth end-to-end (Setup, Login, JWT guard ทุก endpoint)

รัน: 2026-08-05 · branch: `feature/authentication` · ผลลัพธ์: **APPROVED** · รอบรีวิว: **2** · commit: `026bd8e`

## ทำอะไรไปบ้าง (ทีละขั้น)

1. **reviewer (Job A) — สร้าง delegation prompt**
   - TDD required: **yes** — security logic ที่มี branch เยอะ (credential path, token validity/revoke/expiry, role gate) ทุก acceptance criterion เขียนเป็น failing test ได้
   - prompt ตัดสินให้ล่วงหน้า 19 ข้อ (D1–D19) เพื่อไม่ให้ implementer ต้องเดา — และ scrutinize step-1 ก่อนเขียนสเปคจับได้ 3 กับดักตั้งแต่ยังไม่มีโค้ด:
     `HTTPBearer(auto_error=True)` คืน **403** ไม่ใช่ 401 · SQLite คืน `expires_at` เป็น **naive datetime** · Pydantic `max_length` นับ **character** แต่ bcrypt นับ **byte**
   - จับได้ด้วยว่า ADR 0002 ถูกใช้ไปแล้ว (scaler) → ADR ใหม่ต้องเป็น 0003 และ M1 ไม่มี device-update endpoint ทั้งที่ issue เขียนถึง

2. **implementer — ลงมือ (`/tdd`)**
   - ไฟล์ใหม่: `auth/{roles,security,service}.py` (HTTP-free), `api/auth.py`, migration `0002_m2_auth_tables.py`, เทส 7 ไฟล์
   - แก้: `api/deps.py` (guard + `HTTPBearer(auto_error=False)`), `api/devices.py` + `api/license.py` (router-level dependency + `AdminDep`), `licensing/middleware.py` (`/api/auth` เข้า allow-list), `db/models.py`, `config.py`, `main.py`, `conftest.py`
   - FE: `auth.ts`, `pages/Setup.tsx`, `pages/Login.tsx` + แก้ `api.ts`/`App.tsx`/`Activation.tsx`/`AppShell.tsx`
   - **เทส 165 → 270 (+105)**
   - **TDD จับบั๊กจริง 2 ตัวก่อนเขียนโค้ดทับ**:
     (ก) login 2 ครั้งในวินาทีเดียวกัน → JWT เหมือนกัน byte ต่อ byte → `token_hash` ชน UNIQUE → **500** แก้ด้วย `jti` claim
     (ข) กับดัก timezone หนักกว่าที่ prompt เตือน — mutation test พิสูจน์ว่ามันรันบน**ทุก authenticated request** ไม่ใช่แค่ตอน expiry
   - **overrule prompt 1 จุดพร้อมหลักฐาน**: FastAPI 0.141.1 เก็บ router ที่ include เป็น `_IncludedRouter` node — เดิน `app.routes` ตรง ๆ ตามที่ prompt สั่งจะได้ **0 route** และ sweep test ผ่านแบบว่างเปล่า จึง recurse ผ่าน `original_router` + ใส่ tripwire 2 ตัว

3. **reviewer (Job B รอบ 1) — CHANGES_REQUESTED** (2 minor, ไม่มี blocker)
   - ตรวจแบบไม่เชื่อรายงาน: เดิน flow บน temp data dir จริง · **อ่าน byte ดิบใน SQLite + WAL** ยืนยันว่าไม่มี JWT ดิบถูกเก็บ (ทั้งตัวเต็มและทีละ segment) เจอแต่ SHA-256 · รัน 164 เทสแบบขยายขอบเขตเอง
   - รับรอง 3 ข้อที่ implementer ขอ bless: `jti` (reproduce บั๊กเองแล้ว — และชี้ว่าการผ่อน UNIQUE จะทำให้ logout ล้มเหลวเงียบ) · แก้ `installer/README.md` (definition of done บังคับ) · overrule sweep (**ยืนยันเองว่า `app.routes` ให้ 0 APIRoute จริง**)
   - minor 1: `web/src/App.tsx` หยุด retry ตอนยังไม่ login ทั้งที่จอบอก "will keep trying" — regression จาก M1 บนเส้นทาง first-run ที่ issue นี้สร้างเอง
   - minor 2: `role` เก็บลง DB เป็น `ADMIN`/`USER` (SQLAlchemy `Enum` เก็บชื่อ member) ขัดกับ CONTEXT.md ที่การแก้เดียวกันเพิ่งเขียนว่า lowercase — เทสเดิมผ่านเพราะวิ่งผ่าน ORM ทั้งขาไปกลับ

4. **รอบแก้ (cycle 2)** — implementer แก้ทั้งสอง เขียนเทสก่อนแก้และ reproduce finding ได้เป๊ะ (`('a-user','USER') != ('a-user','user')`) · เทสใหม่อ่าน raw column ผ่าน `text()` พร้อม docstring อธิบายว่าทำไมต้องเลี่ยง ORM · **เทส 271** · reviewer ตรวจซ้ำทั้ง 4 state transition ของ timer และ query DB จริงอีกครั้ง → **APPROVED**

## ✅ skill ที่เรียกจริง — ยืนยันจาก transcript

⚠️ **ตรวจไม่ได้ในรอบนี้ — กลไก audit เองมีข้อจำกัด**: ไฟล์ transcript ของ subagent ทั้งสองตัว
(`afc3c87270d72d553.output`, `a79f83f93addd1887.output`) มีขนาด **0 byte** หลังงานจบ ขณะที่ agent
ตัวอื่นใน session เดียวกัน (`a67db48d39e037b58.output` = 344 KB) และ agent ของ M1 (2.6 MB) เขียน
transcript ได้ปกติ — จึง grep ได้ 0 skill call ทั้งที่ไม่ได้แปลว่าไม่มีการเรียก

**ไม่บันทึกเป็น process miss** เพราะหลักฐานว่างเปล่าไม่ใช่หลักฐานว่าไม่ได้ทำ หลักฐานทางอ้อมชี้ว่า
ทั้งคู่ทำงานตามวินัยจริง: prompt มีผลผลิตของ scrutinize step-1 ที่ต้องอ่านโค้ดถึงจะรู้ (3 กับดักข้างบน)
และ implementer รายงาน red→green ต่อ behaviour พร้อม mutation test

→ **ข้อเสนอแก้ pipeline**: transcript-grep ใช้เป็น "หลักฐานเสริมเมื่อมี" ไม่ใช่ gate เดี่ยว ควรให้ subagent
รายงาน skill ที่เรียกในผลลัพธ์ด้วย แล้ว cross-check เมื่อ transcript มีจริง

## Commit

`026bd8e` — `feat: auth end-to-end — Setup, Login, JWT guard on every endpoint (#1)` (41 ไฟล์)

## Nit คงค้าง (ไม่ block — ตัดสินตอน merge)

1. `auth/service.py` — failed login ที่ไม่มี client address log ว่า `from None` (unreachable ใน prod, เห็นแค่ใน TestClient)
2. `auth/security.py` — `jwt_secret.key` ใช้ permission default สืบทอด ACL ของ `%ProgramData%` ไม่ได้ล็อกเอง
3. `web/src/App.tsx` — ยิง `GET /api/auth/me` ซ้ำทันทีหลัง login (code path เดียวกับที่ validate token จาก storage)
4. `api/auth.py` — `Credentials` บังคับ 8–72 ที่ **login** ด้วย → รหัสสั้นที่หน้า login คืน 422 ไม่ใช่ 401 (ไม่ใช่ enumeration oracle เพราะขึ้นกับ string ที่ส่งมาเท่านั้น)

**สิ่งเดียวที่ไม่มีเทสคลุม**: browser walk จริง (Chrome extension ไม่ต่อ) — ชดเชยด้วยการยิง HTTP ชุดเดียวกับที่ SPA ยิงบน server จริง + activation code จริงจาก vendor CLI + restart พิสูจน์ว่า token เดิมรอด (คุณสมบัติ ADR 0003) · reviewer แนะนำให้มนุษย์คลิกผ่าน Setup → Login → Sign out หนึ่งรอบก่อน merge

## วิธีตรวจซ้ำด้วยตัวเอง (audit)

    T="%LOCALAPPDATA%/Temp/claude/C--Users-HP-Documents-Work-arichds-application-v2/e6d49371-8cab-471a-be73-524d52bc5b24/tasks"
    grep -o '"skill":"[a-z-]*"' "$T/afc3c87270d72d553.output" | sort | uniq -c   # reviewer (0 byte — ดูหมายเหตุข้างบน)
    grep -o '"skill":"[a-z-]*"' "$T/a79f83f93addd1887.output" | sort | uniq -c   # implementer (0 byte)
    git show 026bd8e --stat
