> **ยกมาจาก v1 โดยไม่แก้เนื้อหา** (`cewe/docs/requirements/tcc-obis-scan-partial.md`) เมื่อ 2026-08-05
> เป็นผลสแกนจากมิเตอร์จริง ไม่ใช่เอกสารของผู้ผลิต — v2 ใช้เป็นแหล่งอ้างอิง OBIS ตอนพอร์ต driver ที่ M4
> ทุกบรรทัดข้างล่างคือของเดิม รวมทั้งข้อจำกัดที่มันประกาศไว้เอง · ก่อนเชื่อค่าใด ให้ดูหัวข้อ "สถานะ/ข้อจำกัด" ของมันก่อน
> เมื่อจะแตะโค้ด Gurux ให้ใช้ skill `gurux-dlms` คู่กับเอกสารนี้ — เอกสารนี้บอก *อะไร* ส่วน skill บอก *อย่างไร*
>
> **แก้ชื่อไฟล์ + หัวข้อสถานะแล้ว (2026-08-09, issue #25, D13)** — ชื่อไฟล์นี้เคยมีคำว่า "-partial"
> ต่อท้าย และหัวข้อ "สถานะ/ข้อจำกัด" ด้านล่างเคยเขียนว่า "บางส่วน ไม่ใช่ทั้งใบ" ทั้งสองผิด: สแกนรอบ 4 (18 ก.ค. 2026,
> ดูหัวข้อ "ผลอ่าน captureObjects จากมิเตอร์จริง — สแกนรอบ 4" ด้านล่าง) อ่าน captureObjects ได้ครบทั้ง
> Load Profile (`1.0.99.1.0.255`, 35 คอลัมน์) และ Billing (`0.0.98.1.0.255`, 148 คอลัมน์) จบด้วย
> `## Result: SCAN COMPLETE` — ชื่อไฟล์และหัวข้อสถานะจึงถูกแก้ให้ตรงกับเนื้อหาจริงที่มีอยู่แล้ว ไม่ใช่ผลจากการสแกนใหม่
> เนื้อหาสแกนเดิมทั้งหมดด้านล่าง **ไม่ถูกแก้ไข** — เป็นหลักฐานภาคสนาม
>
> **ขอบเขตความครอบคลุม — สแกนรุ่นเดียวจากห้ารุ่น (D14)** ไฟล์นี้ทั้งไฟล์มาจากการ probe รุ่น **test 3CL** ตัวเดียว
> (`203.170.148.103:4059`) — `st3c`, `st33tl`, `st3tl`, `st3dh` ไม่เคยถูกสแกน ไดรเวอร์ v2
> (`SmartTccDriver`, `app/src/arichds/acquisition/drivers/smart_tcc.py`) ถือว่าทั้งห้ารุ่นเหมือนกันเพราะ
> v1 ใช้ driver เดียวคุมทั้งห้า (`cewe-worker/src/drivers/smart_tcc.py:3-5`) ไม่ใช่เพราะมีใครวัดจริง —
> ยังเป็นสมมติฐานที่ไม่ยืนยันกับฮาร์ดแวร์จนกว่าจะได้ลิงก์ไปสแกนอีกสี่รุ่น (F13, `SPEC.md` M4c c2)

# SMART TCC (test 3CL) — OBIS ที่สกัดจาก association view จริงของมิเตอร์

ที่มา: probe `cewe-worker/scripts/probe_tcc_association.py` ต่อ `203.170.148.103:4059` (18 ก.ค. 2026) —
ลิงก์ GPRS หลุดก่อนอ่าน object list ครบ จึงแกะจาก PDU trace ของบล็อกที่รับมาแล้ว (~105 บล็อก)

## สถานะ/ข้อจำกัด

- **สแกนรอบ 4 (18 ก.ค. 2026) เสร็จสมบูรณ์** — อ่าน captureObjects ได้ครบทั้ง Load Profile ทั้งสองโปรไฟล์
  และ Billing Scheme 1 (ดูหัวข้อ "ผลอ่าน captureObjects จากมิเตอร์จริง — สแกนรอบ 4" และ "4. ProfileGeneric
  column layouts" ท้ายไฟล์) จบด้วย `## Result: SCAN COMPLETE`
- **สามโปรไฟล์ FAILed ระหว่างสแกน — ยังไม่ได้อ่าน** (ดูหัวข้อ "4. ProfileGeneric column layouts" ท้ายไฟล์):
  `1.0.98.1.0.255` (Wrong CRC), `0.0.98.2.0.255` และ `1.0.98.2.0.255` (ทั้งคู่ timeout รอ reply) ·
  Battery (`0.0.96.6.x`), SpecialDays (`0.0.11.0.0.255`), ActivityCalendar ก็ยังไม่เห็นในสแกนนี้เช่นกัน
- ค้นพบสำคัญ: **Frequency มีจริงที่ `1.0.14.7.0.255` (Register)** ซึ่งตารางลูกค้าไม่มี · Phase angle `1.0.81.7.40/51/62.255` ตรงกับเอกสาร · แรงดัน/กระแส instantaneous (`x.7.0`) และ average (`x.27.0`, `x.24.x`) มีครบ L1-L3 · Max demand `1.0.x.6.rate` เป็น ExtendedRegister (มี captureTime → ยืนยัน inference เรื่องเวลา demand) · Cumulative demand `1.0.x.2.rate` เป็น Register — **ยืนยันว่า `1.0.1.2.x` คือ demand ไม่ใช่ energy → Energy Summary ในเอกสารลูกค้าพิมพ์ผิดจริง (ต้องเป็น `1.0.x.8.x`)**
- แถวที่ OBIS ไม่ลงท้าย `.255` (เช่น `...196.2`) น่าจะเป็นขยะจากรอยต่อ frame — ติดป้าย ⚠ อย่าใช้

| OBIS | Class | Ver | หมายเหตุ |
|------|-------|-----|----------|
| `0.0.0.1.0.255` | Data (1) | 0 | |
| `0.0.0.1.1.255` | Data (1) | 0 | |
| `0.0.0.1.2.255` | Data (1) | 0 | |
| `0.0.1.0.0.255` | Clock (8) | 0 | |
| `0.0.14.0.1.255` | RegisterActivation (6) | 0 | |
| `0.0.14.0.2.255` | RegisterActivation (6) | 0 | |
| `0.0.16.0.1.255` | RegisterMonitor (21) | 0 | |
| `0.0.16.0.2.255` | RegisterMonitor (21) | 0 | |
| `0.0.16.0.3.255` | RegisterMonitor (21) | 0 | |
| `0.0.16.1.0.255` | RegisterMonitor (21) | 0 | |
| `0.0.16.1.1.255` | RegisterMonitor (21) | 0 | |
| `0.0.16.2.0.255` | ?65 (65) | 0 | |
| `0.0.25.0.0.255` | TcpUdpSetup (41) | 0 | |
| `0.0.25.1.0.255` | Ipv4Setup (42) | 0 | |
| `0.0.25.3.0.255` | PppSetup (44) | 0 | |
| `0.0.25.4.0.255` | GprsSetup (45) | 0 | |
| `0.0.25.4.128.255` | Data (1) | 0 | |
| `0.0.25.7.0.255` | ?48 (48) | 0 | |
| `0.0.40.0.0.255` | AssociationLN (15) | 3 | |
| `0.0.40.0.1.255` | AssociationLN (15) | 3 | |
| `0.0.40.0.2.255` | AssociationLN (15) | 3 | |
| `0.0.40.0.3.255` | AssociationLN (15) | 3 | |
| `0.0.40.0.4.255` | AssociationLN (15) | 3 | |
| `0.0.40.0.5.255` | AssociationLN (15) | 3 | |
| `0.0.41.0.0.255` | SapAssignment (17) | 0 | |
| `0.0.42.0.0.255` | Data (1) | 0 | |
| `0.0.96.1.0.255` | Data (1) | 0 | |
| `0.0.96.1.1.255` | Data (1) | 0 | |
| `0.0.96.1.2.255` | Data (1) | 0 | |
| `0.0.96.1.3.255` | Data (1) | 0 | |
| `0.0.96.1.4.255` | Data (1) | 0 | |
| `0.0.96.1.5.255` | Data (1) | 0 | |
| `0.0.96.1.6.255` | Data (1) | 0 | |
| `0.0.96.1.8.255` | Data (1) | 0 | |
| `0.0.96.1.9.255` | Data (1) | 0 | |
| `0.0.96.1.10.255` | Data (1) | 0 | |
| `0.0.96.1.12.255` | Data (1) | 0 | |
| `0.0.96.1.13.255` | Data (1) | 0 | |
| `0.0.96.1.14.255` | Data (1) | 0 | |
| `0.0.96.1.21.255` | Data (1) | 0 | |
| `0.0.96.5.0.255` | Data (1) | 0 | |
| `0.0.96.10.14.255` | Data (1) | 0 | |
| `0.0.96.12.5.255` | Data (1) | 0 | |
| `0.0.96.12.128.255` | Data (1) | 0 | |
| `0.0.96.12.129.255` | Data (1) | 0 | |
| `0.0.96.12.130.255` | Data (1) | 0 | |
| `0.0.96.13.0.255` | Data (1) | 0 | |
| `0.0.96.13.1.255` | Data (1) | 0 | |
| `0.0.96.14.0.255` | Data (1) | 0 | |
| `0.0.96.14.1.255` | Data (1) | 0 | |
| `0.0.96.60.0.255` | Register (3) | 0 | |
| `0.0.96.60.1.255` | Register (3) | 0 | |
| `0.0.96.60.2.255` | Data (1) | 0 | |
| `0.0.96.60.3.255` | Data (1) | 0 | |
| `0.0.96.60.4.255` | Data (1) | 0 | |
| `0.0.96.60.5.196` | Data (1) | 0 | ⚠ อาจเป็น parse artifact |
| `0.0.96.60.5.255` | Data (1) | 0 | |
| `0.0.96.60.7.255` | Data (1) | 0 | |
| `0.0.96.60.8.255` | Data (1) | 0 | |
| `0.0.96.60.9.255` | Data (1) | 0 | |
| `0.0.96.60.10.255` | Data (1) | 0 | |
| `0.0.96.60.11.255` | Data (1) | 0 | |
| `0.0.96.60.12.255` | Register (3) | 0 | |
| `0.0.96.60.14.255` | Data (1) | 0 | |
| `0.0.96.60.16.255` | Data (1) | 0 | |
| `0.0.96.60.17.255` | Data (1) | 0 | |
| `0.0.96.60.42.255` | Register (3) | 0 | |
| `0.0.96.60.196.2` | Register (3) | 0 | ⚠ อาจเป็น parse artifact |
| `0.1.96.12.5.255` | Data (1) | 0 | |
| `0.2.20.0.0.255` | IecLocalPortSetup (19) | 1 | |
| `0.2.22.0.0.255` | IecHdlcSetup (23) | 1 | |
| `0.2.96.12.5.255` | Data (1) | 0 | |
| `0.3.96.12.5.255` | Data (1) | 0 | |
| `0.196.2.193.0.0` | Data (1) | 0 | ⚠ อาจเป็น parse artifact |
| `1.0.0.1.0.255` | Data (1) | 0 | |
| `1.0.0.1.2.255` | Data (1) | 0 | |
| `1.0.0.2.0.255` | Data (1) | 0 | |
| `1.0.0.2.1.255` | Data (1) | 0 | |
| `1.0.0.3.3.255` | Register (3) | 0 | |
| `1.0.0.4.2.255` | Data (1) | 0 | |
| `1.0.0.4.5.255` | Data (1) | 0 | |
| `1.0.0.8.0.255` | Register (3) | 0 | |
| `1.0.0.8.1.255` | Register (3) | 0 | |
| `1.0.0.8.2.255` | Register (3) | 0 | |
| `1.0.0.8.4.255` | Register (3) | 0 | |
| `1.0.0.9.1.255` | Data (1) | 0 | |
| `1.0.0.9.2.255` | Data (1) | 0 | |
| `1.0.0.9.5.255` | Data (1) | 0 | |
| `1.0.0.9.6.255` | Data (1) | 0 | |
| `1.0.0.9.7.255` | Data (1) | 0 | |
| `1.0.0.9.11.255` | Register (3) | 0 | |
| `1.0.1.2.0.255` | Register (3) | 0 | |
| `1.0.1.2.1.255` | Register (3) | 0 | |
| `1.0.1.2.2.255` | Register (3) | 0 | |
| `1.0.1.2.3.255` | Register (3) | 0 | |
| `1.0.1.2.4.255` | Register (3) | 0 | |
| `1.0.1.2.5.255` | Register (3) | 0 | |
| `1.0.1.2.6.255` | Register (3) | 0 | |
| `1.0.1.2.7.255` | Register (3) | 0 | |
| `1.0.1.2.8.255` | Register (3) | 0 | |
| `1.0.1.4.0.255` | DemandRegister (5) | 0 | |
| `1.0.1.5.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.1.6.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.1.6.1.255` | ExtendedRegister (4) | 0 | |
| `1.0.1.6.2.255` | ExtendedRegister (4) | 0 | |
| `1.0.1.6.3.255` | ExtendedRegister (4) | 0 | |
| `1.0.1.6.4.255` | ExtendedRegister (4) | 0 | |
| `1.0.1.6.5.255` | ExtendedRegister (4) | 0 | |
| `1.0.1.6.6.255` | ExtendedRegister (4) | 0 | |
| `1.0.1.6.7.255` | ExtendedRegister (4) | 0 | |
| `1.0.1.6.8.255` | ExtendedRegister (4) | 0 | |
| `1.0.1.7.0.255` | Register (3) | 0 | |
| `1.0.1.8.0.255` | Register (3) | 0 | |
| `1.0.1.8.1.255` | Register (3) | 0 | |
| `1.0.1.8.2.255` | Register (3) | 0 | |
| `1.0.1.8.3.255` | Register (3) | 0 | |
| `1.0.1.8.4.255` | Register (3) | 0 | |
| `1.0.1.8.5.255` | Register (3) | 0 | |
| `1.0.1.8.6.255` | Register (3) | 0 | |
| `1.0.1.8.7.255` | Register (3) | 0 | |
| `1.0.1.8.8.255` | Register (3) | 0 | |
| `1.0.1.24.0.255` | DemandRegister (5) | 0 | |
| `1.0.1.29.0.255` | Register (3) | 0 | |
| `1.0.2.2.0.255` | Register (3) | 0 | |
| `1.0.2.2.1.255` | Register (3) | 0 | |
| `1.0.2.2.2.255` | Register (3) | 0 | |
| `1.0.2.2.3.255` | Register (3) | 0 | |
| `1.0.2.2.4.255` | Register (3) | 0 | |
| `1.0.2.2.5.255` | Register (3) | 0 | |
| `1.0.2.2.6.255` | Register (3) | 0 | |
| `1.0.2.2.7.255` | Register (3) | 0 | |
| `1.0.2.2.8.255` | Register (3) | 0 | |
| `1.0.2.4.0.255` | DemandRegister (5) | 0 | |
| `1.0.2.5.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.2.6.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.2.6.1.255` | ExtendedRegister (4) | 0 | |
| `1.0.2.6.2.255` | ExtendedRegister (4) | 0 | |
| `1.0.2.6.3.255` | ExtendedRegister (4) | 0 | |
| `1.0.2.6.4.255` | ExtendedRegister (4) | 0 | |
| `1.0.2.6.5.255` | ExtendedRegister (4) | 0 | |
| `1.0.2.6.6.255` | ExtendedRegister (4) | 0 | |
| `1.0.2.6.7.255` | ExtendedRegister (4) | 0 | |
| `1.0.2.6.8.255` | ExtendedRegister (4) | 0 | |
| `1.0.2.7.0.255` | Register (3) | 0 | |
| `1.0.2.8.0.255` | Register (3) | 0 | |
| `1.0.2.8.1.255` | Register (3) | 0 | |
| `1.0.2.8.2.255` | Register (3) | 0 | |
| `1.0.2.8.3.255` | Register (3) | 0 | |
| `1.0.2.8.4.255` | Register (3) | 0 | |
| `1.0.2.8.5.255` | Register (3) | 0 | |
| `1.0.2.8.6.255` | Register (3) | 0 | |
| `1.0.2.8.7.255` | Register (3) | 0 | |
| `1.0.2.8.8.255` | Register (3) | 0 | |
| `1.0.2.8.196.2` | Register (3) | 0 | ⚠ อาจเป็น parse artifact |
| `1.0.2.24.0.255` | DemandRegister (5) | 0 | |
| `1.0.2.29.0.255` | Register (3) | 0 | |
| `1.0.3.2.0.255` | Register (3) | 0 | |
| `1.0.3.2.1.255` | Register (3) | 0 | |
| `1.0.3.2.2.255` | Register (3) | 0 | |
| `1.0.3.2.3.255` | Register (3) | 0 | |
| `1.0.3.2.4.255` | Register (3) | 0 | |
| `1.0.3.2.5.255` | Register (3) | 0 | |
| `1.0.3.2.6.255` | Register (3) | 0 | |
| `1.0.3.2.7.255` | Register (3) | 0 | |
| `1.0.3.2.8.255` | Register (3) | 0 | |
| `1.0.3.4.0.255` | DemandRegister (5) | 0 | |
| `1.0.3.5.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.3.6.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.3.6.1.255` | ExtendedRegister (4) | 0 | |
| `1.0.3.6.2.255` | ExtendedRegister (4) | 0 | |
| `1.0.3.6.3.255` | ExtendedRegister (4) | 0 | |
| `1.0.3.6.4.255` | ExtendedRegister (4) | 0 | |
| `1.0.3.6.5.255` | ExtendedRegister (4) | 0 | |
| `1.0.3.6.6.255` | ExtendedRegister (4) | 0 | |
| `1.0.3.6.7.255` | ExtendedRegister (4) | 0 | |
| `1.0.3.6.8.255` | ExtendedRegister (4) | 0 | |
| `1.0.3.6.196.2` | ExtendedRegister (4) | 0 | ⚠ อาจเป็น parse artifact |
| `1.0.3.7.0.255` | Register (3) | 0 | |
| `1.0.3.8.0.255` | Register (3) | 0 | |
| `1.0.3.8.1.255` | Register (3) | 0 | |
| `1.0.3.8.2.255` | Register (3) | 0 | |
| `1.0.3.8.3.255` | Register (3) | 0 | |
| `1.0.3.8.4.255` | Register (3) | 0 | |
| `1.0.3.8.5.255` | Register (3) | 0 | |
| `1.0.3.8.6.255` | Register (3) | 0 | |
| `1.0.3.8.7.255` | Register (3) | 0 | |
| `1.0.3.8.8.255` | Register (3) | 0 | |
| `1.0.3.29.0.255` | Register (3) | 0 | |
| `1.0.4.2.0.255` | Register (3) | 0 | |
| `1.0.4.2.1.255` | Register (3) | 0 | |
| `1.0.4.2.2.255` | Register (3) | 0 | |
| `1.0.4.2.3.255` | Register (3) | 0 | |
| `1.0.4.2.4.255` | Register (3) | 0 | |
| `1.0.4.2.5.255` | Register (3) | 0 | |
| `1.0.4.2.6.255` | Register (3) | 0 | |
| `1.0.4.2.7.255` | Register (3) | 0 | |
| `1.0.4.2.8.255` | Register (3) | 0 | |
| `1.0.4.4.0.255` | DemandRegister (5) | 0 | |
| `1.0.4.5.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.4.6.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.4.6.1.255` | ExtendedRegister (4) | 0 | |
| `1.0.4.6.2.255` | ExtendedRegister (4) | 0 | |
| `1.0.4.6.3.255` | ExtendedRegister (4) | 0 | |
| `1.0.4.6.4.255` | ExtendedRegister (4) | 0 | |
| `1.0.4.6.5.255` | ExtendedRegister (4) | 0 | |
| `1.0.4.6.6.255` | ExtendedRegister (4) | 0 | |
| `1.0.4.6.7.255` | ExtendedRegister (4) | 0 | |
| `1.0.4.6.8.255` | ExtendedRegister (4) | 0 | |
| `1.0.4.7.0.255` | Register (3) | 0 | |
| `1.0.4.8.0.255` | Register (3) | 0 | |
| `1.0.4.8.1.255` | Register (3) | 0 | |
| `1.0.4.8.2.255` | Register (3) | 0 | |
| `1.0.4.8.3.255` | Register (3) | 0 | |
| `1.0.4.8.4.255` | Register (3) | 0 | |
| `1.0.4.8.5.255` | Register (3) | 0 | |
| `1.0.4.8.6.255` | Register (3) | 0 | |
| `1.0.4.8.7.255` | Register (3) | 0 | |
| `1.0.4.8.8.255` | Register (3) | 0 | |
| `1.0.4.29.0.255` | Register (3) | 0 | |
| `1.0.5.8.0.255` | Register (3) | 0 | |
| `1.0.5.8.1.255` | Register (3) | 0 | |
| `1.0.5.8.2.255` | Register (3) | 0 | |
| `1.0.5.8.3.255` | Register (3) | 0 | |
| `1.0.5.8.4.255` | Register (3) | 0 | |
| `1.0.5.8.5.255` | Register (3) | 0 | |
| `1.0.5.8.6.255` | Register (3) | 0 | |
| `1.0.5.8.7.255` | Register (3) | 0 | |
| `1.0.5.8.8.255` | Register (3) | 0 | |
| `1.0.5.29.0.255` | Register (3) | 0 | |
| `1.0.6.8.0.255` | Register (3) | 0 | |
| `1.0.6.8.1.255` | Register (3) | 0 | |
| `1.0.6.8.2.255` | Register (3) | 0 | |
| `1.0.6.8.3.255` | Register (3) | 0 | |
| `1.0.6.8.4.255` | Register (3) | 0 | |
| `1.0.6.8.5.255` | Register (3) | 0 | |
| `1.0.6.8.6.255` | Register (3) | 0 | |
| `1.0.6.8.7.255` | Register (3) | 0 | |
| `1.0.6.8.8.255` | Register (3) | 0 | |
| `1.0.6.29.0.255` | Register (3) | 0 | |
| `1.0.7.8.0.255` | Register (3) | 0 | |
| `1.0.7.8.1.255` | Register (3) | 0 | |
| `1.0.7.8.2.255` | Register (3) | 0 | |
| `1.0.7.8.3.255` | Register (3) | 0 | |
| `1.0.7.8.4.255` | Register (3) | 0 | |
| `1.0.7.8.5.255` | Register (3) | 0 | |
| `1.0.7.8.6.255` | Register (3) | 0 | |
| `1.0.7.8.7.255` | Register (3) | 0 | |
| `1.0.7.8.8.255` | Register (3) | 0 | |
| `1.0.7.29.0.255` | Register (3) | 0 | |
| `1.0.8.8.0.255` | Register (3) | 0 | |
| `1.0.8.8.1.255` | Register (3) | 0 | |
| `1.0.8.8.2.255` | Register (3) | 0 | |
| `1.0.8.8.3.255` | Register (3) | 0 | |
| `1.0.8.8.4.255` | Register (3) | 0 | |
| `1.0.8.8.5.255` | Register (3) | 0 | |
| `1.0.8.8.6.255` | Register (3) | 0 | |
| `1.0.8.8.7.255` | Register (3) | 0 | |
| `1.0.8.8.8.255` | Register (3) | 0 | |
| `1.0.8.29.0.255` | Register (3) | 0 | |
| `1.0.9.4.0.255` | DemandRegister (5) | 0 | |
| `1.0.9.5.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.9.6.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.9.6.1.255` | ExtendedRegister (4) | 0 | |
| `1.0.9.6.2.255` | ExtendedRegister (4) | 0 | |
| `1.0.9.6.3.255` | ExtendedRegister (4) | 0 | |
| `1.0.9.6.4.255` | ExtendedRegister (4) | 0 | |
| `1.0.9.6.5.255` | ExtendedRegister (4) | 0 | |
| `1.0.9.6.6.255` | ExtendedRegister (4) | 0 | |
| `1.0.9.6.7.255` | ExtendedRegister (4) | 0 | |
| `1.0.9.6.8.255` | ExtendedRegister (4) | 0 | |
| `1.0.9.7.0.255` | Register (3) | 0 | |
| `1.0.9.8.0.255` | Register (3) | 0 | |
| `1.0.9.8.1.255` | Register (3) | 0 | |
| `1.0.9.8.2.255` | Register (3) | 0 | |
| `1.0.9.8.3.255` | Register (3) | 0 | |
| `1.0.9.8.4.255` | Register (3) | 0 | |
| `1.0.9.8.5.255` | Register (3) | 0 | |
| `1.0.9.8.6.255` | Register (3) | 0 | |
| `1.0.9.8.7.255` | Register (3) | 0 | |
| `1.0.9.8.8.255` | Register (3) | 0 | |
| `1.0.9.29.0.255` | Register (3) | 0 | |
| `1.0.10.4.0.255` | DemandRegister (5) | 0 | |
| `1.0.10.5.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.10.6.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.10.6.1.255` | ExtendedRegister (4) | 0 | |
| `1.0.10.6.2.255` | ExtendedRegister (4) | 0 | |
| `1.0.10.6.3.255` | ExtendedRegister (4) | 0 | |
| `1.0.10.6.4.255` | ExtendedRegister (4) | 0 | |
| `1.0.10.6.5.255` | ExtendedRegister (4) | 0 | |
| `1.0.10.6.6.255` | ExtendedRegister (4) | 0 | |
| `1.0.10.6.7.255` | ExtendedRegister (4) | 0 | |
| `1.0.10.6.8.255` | ExtendedRegister (4) | 0 | |
| `1.0.10.7.0.255` | Register (3) | 0 | |
| `1.0.10.8.0.255` | Register (3) | 0 | |
| `1.0.10.8.1.255` | Register (3) | 0 | |
| `1.0.10.8.2.255` | Register (3) | 0 | |
| `1.0.10.8.3.255` | Register (3) | 0 | |
| `1.0.10.8.4.255` | Register (3) | 0 | |
| `1.0.10.8.5.255` | Register (3) | 0 | |
| `1.0.10.8.6.255` | Register (3) | 0 | |
| `1.0.10.8.7.255` | Register (3) | 0 | |
| `1.0.10.8.8.255` | Register (3) | 0 | |
| `1.0.10.8.196.2` | Register (3) | 0 | ⚠ อาจเป็น parse artifact |
| `1.0.10.29.0.255` | Register (3) | 0 | |
| `1.0.11.7.128.255` | Data (1) | 0 | |
| `1.0.13.3.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.13.5.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.13.7.0.255` | Register (3) | 0 | |
| `1.0.13.27.0.255` | Register (3) | 0 | |
| `1.0.13.27.196.2` | Register (3) | 0 | ⚠ อาจเป็น parse artifact |
| `1.0.14.7.0.255` | Register (3) | 0 | |
| `1.0.15.4.0.255` | DemandRegister (5) | 0 | |
| `1.0.15.6.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.15.6.1.255` | ExtendedRegister (4) | 0 | |
| `1.0.15.6.2.255` | ExtendedRegister (4) | 0 | |
| `1.0.15.6.3.255` | ExtendedRegister (4) | 0 | |
| `1.0.15.6.4.255` | ExtendedRegister (4) | 0 | |
| `1.0.15.6.5.255` | ExtendedRegister (4) | 0 | |
| `1.0.15.6.6.255` | ExtendedRegister (4) | 0 | |
| `1.0.15.6.7.255` | ExtendedRegister (4) | 0 | |
| `1.0.15.6.8.255` | ExtendedRegister (4) | 0 | |
| `1.0.15.7.0.255` | Register (3) | 0 | |
| `1.0.15.8.0.255` | Register (3) | 0 | |
| `1.0.15.8.1.255` | Register (3) | 0 | |
| `1.0.15.8.2.255` | Register (3) | 0 | |
| `1.0.15.8.3.255` | Register (3) | 0 | |
| `1.0.15.8.4.255` | Register (3) | 0 | |
| `1.0.15.8.5.255` | Register (3) | 0 | |
| `1.0.15.8.6.255` | Register (3) | 0 | |
| `1.0.15.8.7.255` | Register (3) | 0 | |
| `1.0.15.8.8.255` | Register (3) | 0 | |
| `1.0.15.24.0.255` | DemandRegister (5) | 0 | |
| `1.0.15.29.0.255` | Register (3) | 0 | |
| `1.0.15.55.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.16.7.0.255` | Register (3) | 0 | |
| `1.0.16.8.0.255` | Register (3) | 0 | |
| `1.0.16.8.1.255` | Register (3) | 0 | |
| `1.0.16.8.2.255` | Register (3) | 0 | |
| `1.0.16.8.3.255` | Register (3) | 0 | |
| `1.0.16.8.4.255` | Register (3) | 0 | |
| `1.0.16.8.5.255` | Register (3) | 0 | |
| `1.0.16.8.6.255` | Register (3) | 0 | |
| `1.0.16.8.7.255` | Register (3) | 0 | |
| `1.0.16.8.8.255` | Register (3) | 0 | |
| `1.0.16.24.0.255` | DemandRegister (5) | 0 | |
| `1.0.21.7.0.255` | Register (3) | 0 | |
| `1.0.21.8.0.255` | Register (3) | 0 | |
| `1.0.21.29.0.255` | Register (3) | 0 | |
| `1.0.22.7.0.255` | Register (3) | 0 | |
| `1.0.22.8.0.255` | Register (3) | 0 | |
| `1.0.22.29.0.255` | Register (3) | 0 | |
| `1.0.23.7.0.255` | Register (3) | 0 | |
| `1.0.23.8.0.255` | Register (3) | 0 | |
| `1.0.23.29.0.255` | Register (3) | 0 | |
| `1.0.24.7.0.255` | Register (3) | 0 | |
| `1.0.24.8.0.255` | Register (3) | 0 | |
| `1.0.24.29.0.255` | Register (3) | 0 | |
| `1.0.25.8.0.255` | Register (3) | 0 | |
| `1.0.25.29.0.255` | Register (3) | 0 | |
| `1.0.26.8.0.255` | Register (3) | 0 | |
| `1.0.26.29.0.255` | Register (3) | 0 | |
| `1.0.27.8.0.255` | Register (3) | 0 | |
| `1.0.27.29.0.255` | Register (3) | 0 | |
| `1.0.28.8.0.255` | Register (3) | 0 | |
| `1.0.28.29.0.255` | Register (3) | 0 | |
| `1.0.29.7.0.255` | Register (3) | 0 | |
| `1.0.29.8.0.255` | Register (3) | 0 | |
| `1.0.30.7.0.255` | Register (3) | 0 | |
| `1.0.30.8.0.255` | Register (3) | 0 | |
| `1.0.31.4.0.255` | DemandRegister (5) | 0 | |
| `1.0.31.7.0.255` | Register (3) | 0 | |
| `1.0.31.7.128.255` | Register (3) | 0 | |
| `1.0.31.24.0.255` | Register (3) | 0 | |
| `1.0.31.24.124.255` | Register (3) | 0 | |
| `1.0.31.27.0.255` | Register (3) | 0 | |
| `1.0.32.7.0.255` | Register (3) | 0 | |
| `1.0.32.24.0.255` | Register (3) | 0 | |
| `1.0.32.24.124.255` | Register (3) | 0 | |
| `1.0.32.27.0.255` | Register (3) | 0 | |
| `1.0.33.3.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.33.5.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.33.7.0.255` | Register (3) | 0 | |
| `1.0.33.27.0.255` | Register (3) | 0 | |
| `1.0.35.7.0.255` | Register (3) | 0 | |
| `1.0.35.8.0.255` | Register (3) | 0 | |
| `1.0.36.7.0.255` | Register (3) | 0 | |
| `1.0.36.8.0.255` | Register (3) | 0 | |
| `1.0.41.7.0.255` | Register (3) | 0 | |
| `1.0.41.8.0.255` | Register (3) | 0 | |
| `1.0.41.29.0.255` | Register (3) | 0 | |
| `1.0.42.7.0.255` | Register (3) | 0 | |
| `1.0.42.8.0.255` | Register (3) | 0 | |
| `1.0.42.29.0.255` | Register (3) | 0 | |
| `1.0.43.7.0.255` | Register (3) | 0 | |
| `1.0.43.8.0.255` | Register (3) | 0 | |
| `1.0.43.29.0.255` | Register (3) | 0 | |
| `1.0.44.7.0.255` | Register (3) | 0 | |
| `1.0.44.8.0.255` | Register (3) | 0 | |
| `1.0.44.29.0.255` | Register (3) | 0 | |
| `1.0.45.8.0.255` | Register (3) | 0 | |
| `1.0.45.29.0.255` | Register (3) | 0 | |
| `1.0.46.8.0.255` | Register (3) | 0 | |
| `1.0.46.29.0.255` | Register (3) | 0 | |
| `1.0.47.8.0.255` | Register (3) | 0 | |
| `1.0.47.29.0.255` | Register (3) | 0 | |
| `1.0.48.8.0.255` | Register (3) | 0 | |
| `1.0.48.29.0.255` | Register (3) | 0 | |
| `1.0.49.7.0.255` | Register (3) | 0 | |
| `1.0.49.8.0.255` | Register (3) | 0 | |
| `1.0.50.7.0.255` | Register (3) | 0 | |
| `1.0.50.8.0.255` | Register (3) | 0 | |
| `1.0.51.4.0.255` | DemandRegister (5) | 0 | |
| `1.0.51.7.0.255` | Register (3) | 0 | |
| `1.0.51.7.128.255` | Register (3) | 0 | |
| `1.0.51.24.0.255` | Register (3) | 0 | |
| `1.0.51.24.124.255` | Register (3) | 0 | |
| `1.0.51.27.0.255` | Register (3) | 0 | |
| `1.0.52.7.0.255` | Register (3) | 0 | |
| `1.0.52.24.0.255` | Register (3) | 0 | |
| `1.0.52.24.124.255` | Register (3) | 0 | |
| `1.0.52.27.0.255` | Register (3) | 0 | |
| `1.0.53.3.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.53.5.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.53.7.0.255` | Register (3) | 0 | |
| `1.0.53.27.0.255` | Register (3) | 0 | |
| `1.0.55.7.0.255` | Register (3) | 0 | |
| `1.0.55.8.0.255` | Register (3) | 0 | |
| `1.0.56.7.0.255` | Register (3) | 0 | |
| `1.0.56.8.0.255` | Register (3) | 0 | |
| `1.0.61.7.0.255` | Register (3) | 0 | |
| `1.0.61.8.0.255` | Register (3) | 0 | |
| `1.0.61.29.0.255` | Register (3) | 0 | |
| `1.0.62.7.0.255` | Register (3) | 0 | |
| `1.0.62.8.0.255` | Register (3) | 0 | |
| `1.0.62.29.0.255` | Register (3) | 0 | |
| `1.0.63.7.0.255` | Register (3) | 0 | |
| `1.0.63.8.0.255` | Register (3) | 0 | |
| `1.0.63.29.0.255` | Register (3) | 0 | |
| `1.0.64.7.0.255` | Register (3) | 0 | |
| `1.0.64.8.0.255` | Register (3) | 0 | |
| `1.0.64.29.0.255` | Register (3) | 0 | |
| `1.0.65.8.0.255` | Register (3) | 0 | |
| `1.0.65.29.0.255` | Register (3) | 0 | |
| `1.0.66.8.0.255` | Register (3) | 0 | |
| `1.0.66.29.0.255` | Register (3) | 0 | |
| `1.0.67.8.0.255` | Register (3) | 0 | |
| `1.0.67.29.0.255` | Register (3) | 0 | |
| `1.0.68.8.0.255` | Register (3) | 0 | |
| `1.0.68.29.0.255` | Register (3) | 0 | |
| `1.0.69.7.0.255` | Register (3) | 0 | |
| `1.0.69.8.0.255` | Register (3) | 0 | |
| `1.0.70.7.0.255` | Register (3) | 0 | |
| `1.0.70.8.0.255` | Register (3) | 0 | |
| `1.0.71.4.0.255` | DemandRegister (5) | 0 | |
| `1.0.71.7.0.255` | Register (3) | 0 | |
| `1.0.71.7.128.255` | Register (3) | 0 | |
| `1.0.71.24.0.255` | Register (3) | 0 | |
| `1.0.71.24.124.255` | Register (3) | 0 | |
| `1.0.71.27.0.255` | Register (3) | 0 | |
| `1.0.72.7.0.255` | Register (3) | 0 | |
| `1.0.72.24.0.255` | Register (3) | 0 | |
| `1.0.72.24.124.255` | Register (3) | 0 | |
| `1.0.72.27.0.255` | Register (3) | 0 | |
| `1.0.73.3.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.73.5.0.255` | ExtendedRegister (4) | 0 | |
| `1.0.73.7.0.255` | Register (3) | 0 | |
| `1.0.73.27.0.255` | Register (3) | 0 | |
| `1.0.75.7.0.255` | Register (3) | 0 | |
| `1.0.75.8.0.255` | Register (3) | 0 | |
| `1.0.76.7.0.255` | Register (3) | 0 | |
| `1.0.76.8.0.255` | Register (3) | 0 | |
| `1.0.81.7.10.255` | Register (3) | 0 | |
| `1.0.81.7.20.255` | Register (3) | 0 | |
| `1.0.81.7.21.255` | Register (3) | 0 | |
| `1.0.81.7.40.255` | Register (3) | 0 | |
| `1.0.81.7.51.255` | Register (3) | 0 | |
| `1.0.81.7.62.255` | Register (3) | 0 | |
| `1.0.81.7.70.255` | Register (3) | 0 | |
| `1.0.81.7.71.255` | Register (3) | 0 | |
| `1.0.81.7.72.255` | Register (3) | 0 | |
| `1.0.90.7.0.255` | Register (3) | 0 | |
| `1.0.91.7.0.255` | Register (3) | 0 | |
| `1.0.96.71.18.255` | Data (1) | 0 | |
| `1.0.96.72.1.255` | Data (1) | 0 | |
| `1.0.96.72.2.255` | Data (1) | 0 | |
| `1.0.128.7.0.255` | Register (3) | 0 | |
| `1.0.128.8.0.255` | Register (3) | 0 | |
| `1.0.128.8.1.255` | Register (3) | 0 | |
| `1.0.128.8.2.255` | Register (3) | 0 | |
| `1.0.128.8.3.255` | Register (3) | 0 | |
| `1.0.128.8.4.255` | Register (3) | 0 | |
| `1.0.128.8.5.255` | Register (3) | 0 | |
| `1.0.128.8.6.255` | Register (3) | 0 | |
| `1.0.128.8.7.255` | Register (3) | 0 | |
| `1.0.128.8.8.255` | Register (3) | 0 | |
| `1.0.129.7.0.255` | Register (3) | 0 | |
| `1.0.129.8.0.255` | Register (3) | 0 | |
| `1.0.129.8.1.255` | Register (3) | 0 | |
| `1.0.129.8.2.255` | Register (3) | 0 | |
| `1.0.129.8.3.255` | Register (3) | 0 | |
| `1.0.129.8.4.255` | Register (3) | 0 | |
| `1.0.129.8.5.255` | Register (3) | 0 | |
| `1.0.129.8.6.255` | Register (3) | 0 | |
| `1.0.129.8.7.255` | Register (3) | 0 | |
| `1.0.129.8.8.255` | Register (3) | 0 | |
| `1.0.130.7.0.255` | Register (3) | 0 | |
| `1.0.131.7.0.255` | Register (3) | 0 | |
| `1.0.132.7.0.255` | Register (3) | 0 | |
| `1.0.133.7.0.255` | Register (3) | 0 | |
| `1.0.134.7.0.255` | Register (3) | 0 | |
| `1.0.135.7.0.255` | Register (3) | 0 | |
| `1.0.148.7.0.255` | Register (3) | 0 | |
| `1.0.148.8.0.255` | Register (3) | 0 | |
| `1.0.149.7.0.255` | Register (3) | 0 | |
| `1.0.149.8.0.255` | Register (3) | 0 | |
| `1.0.168.7.0.255` | Register (3) | 0 | |
| `1.0.168.8.0.255` | Register (3) | 0 | |
| `1.0.169.7.0.255` | Register (3) | 0 | |
| `1.0.169.8.0.255` | Register (3) | 0 | |
| `1.0.188.7.0.255` | Register (3) | 0 | |
| `1.0.188.8.0.255` | Register (3) | 0 | |
| `1.0.189.7.0.255` | Register (3) | 0 | |
| `1.0.189.8.0.255` | Register (3) | 0 | |
| `1.0.196.2.193.0` | Register (3) | 0 | ⚠ อาจเป็น parse artifact |
| `1.1.0.2.0.255` | Data (1) | 0 | |
| `196.2.193.0.0.0` | ExtendedRegister (4) | 0 | ⚠ อาจเป็น parse artifact |

## ProfileGeneric inventory — จาก screenshot GXDLMSDirector ของ vendor (`profile-tcc.jpg` ในโฟลเดอร์นี้, 18 ก.ค. 2026)

ปิดช่องว่างกลุ่ม ProfileGeneric ที่สแกนไม่ถึง:

| OBIS | ความหมาย (ตาม Director) | บทบาท |
|------|--------------------------|-------|
| `1.0.99.1.0.255` | Load profile with recording period 1 | **LP หลัก (#107 ใช้ตัวนี้)** |
| `1.0.99.2.0.255` | Load profile with recording period 2 | LP ชุดสอง (ยังไม่รู้ period — ต้องอ่าน attr 4) |
| `0.0.98.1.0.255` | Data of billing period Scheme 1 | **Billing หลัก (vendor เปิดโชว์ข้อมูลจริงจากตัวนี้)** |
| `0.0.98.2.0.255` | Data of billing period Scheme 2 | สำรอง |
| `0.0.98.3.0.255` / `1.0.98.3.0.255` | Invalid / Load profile during test | ไม่ใช้ |
| `1.0.98.1.0.255` / `1.0.98.2.0.255` | Data of billing period Scheme 1/2 (ช่อง 1-0) | มีคู่ขนานกับ 0.0.98.x |
| `1.0.99.97.0.255`, `1.0.99.97.1.255` | Power failure event log #1/#2 | event |
| `0.0.99.98.0-4.255`, `0.0.99.98.10/11.255` | Event log #1–#5, #11, #12 | event |
| `0.0.99.16.0.255` | Parameter monitor log | event |
| `1.0.99.14.0/1/2.255` | Power quality profile #1–#3 | PQ |
| `0.0.21.0.1.255`, `0.0.21.0.2.255` | General/Alternate display readout | readout |
| `1.0.96.129.0.255`, `1.0.96.66.6.255`, `1.0.96.66.3.255` | Manufacturer specific | - |

## คอลัมน์ billing profile `0.0.98.1.0.255` (เท่าที่เห็นในตาราง Data ของ screenshot)

Entries in use = 4 · sort FiFo · sort object = Clock `0.0.1.0.0.255` · ลำดับ capture objects:

1. `0.0.1.0.0.255` — Time (Clock)
2. `1.0.98.1.0.255` — Data of billing period marker
3. `1.0.0.1.0.255` — Billing period counter
4. `1.0.0.1.2.255` — Time stamp of the most recent billing period closed
5. `1.0.1.8.0.255` — Active energy import Rate 0 (total)
6. `1.0.1.8.1.255` — Active energy import Rate 1
7. … (คอลัมน์ถัดไปถูกตัดขอบจอ — รายการเต็มรอไฟล์ .gxc หรืออ่าน attr 3 สำเร็จ)

### Field probe billing profile (3CL จริง, 24 ก.ค. 2026 — issue #123)

- อ่าน `0.0.98.1.0.255` ได้ **148 capture columns** ครบทั้งใบ ถือ **1 cut จริง**: **14/07/2026 16:00**,
  billing-period counter `1.0.0.1.0.255` = **1**.
- **bill date ราย row = Clock capture column `0.0.1.0.0.255` attr 2** (อ่านได้ `14/07/2026 16:00`
  ทั้งใน current row และทุก history row) → driver map `bill_date` ไปที่ column นี้.
- `0.0.0.1.2.255` (bill-date default ของ CEWE) = **"undefined object"** บนมิเตอร์นี้ (ไม่ใช่ capture column,
  อ่าน standalone error) — ใช้ไม่ได้.
- `1.0.0.1.2.255`: standalone อ่านได้ `14/07 16:00` แต่ **buffer column อ่านได้ UNSET (ปี 2000)** และให้ค่าเดียว
  — ใช้เป็น per-row date ไม่ได้ (การตัดสิน bill_date = Clock column, **ไม่ใช่** `1.0.0.1.2.255`, เป็นข้อสรุป FINAL).
- **ไม่มี reset_reason register** (`0.0.0.1.12.255` ไม่ใช่ capture column) → classifier reset-reason คืน None
  สำหรับ TCC; open/closed จำแนกจาก bill_date ที่ set แทน (ดู ADR 0018 note 2026-07-24).
- Scheme 2 (`0.0.98.2.0.255`) = daily auto-snapshot 8 ใบ (period counter ค้างที่ 1) — **ไม่ใช่** billing history, exclude.

### Field probe billing — เพิ่มเติม (3CL + Premier 550 จริง, 24 ก.ค. 2026 — issue #125)

ต่อยอด note #123 ด้านบน (ไม่ทวนสิ่งที่ #123/#124 บันทึกแล้ว — 148 คอลัมน์, bill_date→Clock,
reset_reason ไม่มี, scaler mechanics ×10/÷10000 ของ ADR 0010):

- **บทบาทของ 4 billing ProfileGeneric (ยืนยัน field).** ปิดภาพที่ inventory table ด้านบนแจกไว้:
  - Scheme 1 `0.0.98.1.0.255` = billing history จริง (1 cut — ดู note #123, ไม่ทวนจำนวน).
  - Scheme 2 `0.0.98.2.0.255` = periodic capture ที่ยิงราย **00:00** (#123 บันทึก 8 ใบ + counter ค้าง 1
    ไว้แล้ว). **เพิ่มเติม**: ทั้ง 8 แถว **byte-identical กันเอง และเท่ากับ standalone register สด** ทุกตัว
    → เป็น snapshot ตามเวลา **ไม่ใช่** รอบตัดบิล.
  - คู่ `1.0.98.1.0.255` / `1.0.98.2.0.255` (ช่อง 1-0) = mirror ของทั้งสอง scheme — field probe เห็นตรงกับ
    ที่ inventory แจก.
  - สรุป: "history" ของลูกค้า = cut ของ Scheme 1 เท่านั้น; driver ตั้ง `billing_profile_obis = 0.0.98.1.0.255`
    ตรงเป้าอยู่แล้ว.
- **Entry order = entry 1 ใหม่สุด (ยืนยัน).** อ่าน Scheme 2 (24 ก.ค.) เห็น **24/07 ที่ entry 1 และ 16/07
  ที่ entry 8** → entry index 1 = ใหม่สุด. **caveat ตรงไปตรงมา**: billing profile ของ TCC (Scheme 1) มี
  `entries_in_use = 1` จึง **พิสูจน์ entry-order ของ billing profile เองบนมิเตอร์นี้ไม่ได้** — หลักฐานมาจาก
  8 แถวของ Scheme 2 (และ Premier 550 ด้านล่าง). ดู ADR 0004 note 2026-07-24.
- **Operational note (GPRS/HighGMAC).** association ล้มเป็นช่วง ๆ ที่ frame-counter pre-read
  (`ValueError: Invalid connection.`, ~2 ใน 4 ครั้ง) แล้วสำเร็จเมื่อ retry; หนึ่ง connection อ่านได้
  ProfileGeneric **เดียว** ก่อน link หลุด → **ต้อง reconnect ราย profile**.
- **Scaler ground truth.** ทุก energy/demand register ที่เช็ค report **exponent 0**, unit
  Wh(30)/W(27)/varh(32). ดู ADR 0010 (ไม่ทวน phantom-×10 mechanics — เป็น ADR ของ #124).
- **Premier 550 (`49.229.159.42:50001`, 24 ก.ค. 2026).** scaler exponent 0 / unit Wh·varh·W ทุก register;
  ratio billing-row-vs-standalone ≈ **1.0** ⇒ entry 1 = รอบเปิด/กำลังเดิน — เป็น cross-family confirmation
  ของ entry-order assumption (ADR 0004) ที่ TCC (`entries_in_use = 1`) ให้ไม่ได้.

## ผลอ่าน captureObjects จากมิเตอร์จริง — สแกนรอบ 4 (18 ก.ค. 2026, สำเร็จ)

ข้อค้นพบหลัก:
- **LP หลัก `1.0.99.1.0.255`: capturePeriod = 900 วินาที (15 นาที)** · 297 entries · 35 คอลัมน์ — โครงตรง requirement ของลูกค้า (พลังงานช่วงบันทึกรวม+รายเฟส `x.29`, V/I เฉลี่ย `x.27` และ `x.24.124`, PF `13.27`, phase angle `81.7.x`, record status `0.0.96.10.1.255`)
- **`1.0.99.2.0.255`: capturePeriod = 60 วินาที (1 นาที)** · 4320 entries (~3 วัน) — เก็บค่า instantaneous (`x.7.0`) ทั้ง V/I/P/Q/PF รายเฟส
- **Billing `0.0.98.1.0.255`: ได้คอลัมน์ครบทั้งใบ (~130 คอลัมน์)** — counter, timestamp งวด, kWh import/export rate 0–8, max demand (ค่า attr 2 + **เวลา attr 5**) import/export rate 0–8, cumulative demand, kvarh, kvar demand — capturePeriod 0 (บันทึกตามรอบตัดบิล ไม่ใช่ตามเวลา)
- **"Access Error" รอบก่อนเป็นอาการชั่วคราว** (มิเตอร์ค้างจาก association เก่า) — รอบนี้อ่าน `0.0.98.1.0.255` ได้ปกติ → ไม่ต้องเปลี่ยน client address (คำถามข้อ 11.8 ปิด)
- **Frequency ไม่อยู่ใน capture list ของ LP** — มีเฉพาะค่า instantaneous `1.0.14.7.0.255` → คอลัมน์ Frequency ในไฟล์ export ต้องเป็น snapshot ตอนอ่านหรือเว้นว่าง (ต้องเคาะกับลูกค้า)

## 4. ProfileGeneric column layouts (captureObjects)
(6 profiles)

### `1.0.99.1.0.255`
- capturePeriod: 900 s · entriesInUse: 297
  - `0.0.1.0.0.255` attr 2 (CLOCK)
  - `1.0.99.1.0.255` attr -1 (PROFILE_GENERIC)
  - `0.0.96.10.1.255` attr 2 (DATA)
  - `1.0.1.29.0.255` attr 2 (REGISTER)
  - `1.0.21.29.0.255` attr 2 (REGISTER)
  - `1.0.41.29.0.255` attr 2 (REGISTER)
  - `1.0.61.29.0.255` attr 2 (REGISTER)
  - `1.0.2.29.0.255` attr 2 (REGISTER)
  - `1.0.22.29.0.255` attr 2 (REGISTER)
  - `1.0.42.29.0.255` attr 2 (REGISTER)
  - `1.0.62.29.0.255` attr 2 (REGISTER)
  - `1.0.3.29.0.255` attr 2 (REGISTER)
  - `1.0.23.29.0.255` attr 2 (REGISTER)
  - `1.0.43.29.0.255` attr 2 (REGISTER)
  - `1.0.63.29.0.255` attr 2 (REGISTER)
  - `1.0.4.29.0.255` attr 2 (REGISTER)
  - `1.0.24.29.0.255` attr 2 (REGISTER)
  - `1.0.44.29.0.255` attr 2 (REGISTER)
  - `1.0.64.29.0.255` attr 2 (REGISTER)
  - `1.0.32.27.0.255` attr 2 (REGISTER)
  - `1.0.52.27.0.255` attr 2 (REGISTER)
  - `1.0.72.27.0.255` attr 2 (REGISTER)
  - `1.0.31.27.0.255` attr 2 (REGISTER)
  - `1.0.51.27.0.255` attr 2 (REGISTER)
  - `1.0.71.27.0.255` attr 2 (REGISTER)
  - `1.0.32.24.124.255` attr 2 (REGISTER)
  - `1.0.52.24.124.255` attr 2 (REGISTER)
  - `1.0.72.24.124.255` attr 2 (REGISTER)
  - `1.0.31.24.124.255` attr 2 (REGISTER)
  - `1.0.51.24.124.255` attr 2 (REGISTER)
  - `1.0.71.24.124.255` attr 2 (REGISTER)
  - `1.0.13.27.0.255` attr 2 (REGISTER)
  - `1.0.81.7.40.255` attr 2 (REGISTER)
  - `1.0.81.7.51.255` attr 2 (REGISTER)
  - `1.0.81.7.62.255` attr 2 (REGISTER)
### `1.0.99.2.0.255`
- capturePeriod: 60 s · entriesInUse: 4320
  - `0.0.1.0.0.255` attr 2 (CLOCK)
  - `1.0.99.2.0.255` attr -1 (PROFILE_GENERIC)
  - `0.0.96.10.2.255` attr 2 (DATA)
  - `1.0.32.7.0.255` attr 2 (REGISTER)
  - `1.0.52.7.0.255` attr 2 (REGISTER)
  - `1.0.72.7.0.255` attr 2 (REGISTER)
  - `1.0.31.7.0.255` attr 2 (REGISTER)
  - `1.0.51.7.0.255` attr 2 (REGISTER)
  - `1.0.71.7.0.255` attr 2 (REGISTER)
  - `1.0.1.7.0.255` attr 2 (REGISTER)
  - `1.0.21.7.0.255` attr 2 (REGISTER)
  - `1.0.41.7.0.255` attr 2 (REGISTER)
  - `1.0.61.7.0.255` attr 2 (REGISTER)
  - `1.0.2.7.0.255` attr 2 (REGISTER)
  - `1.0.22.7.0.255` attr 2 (REGISTER)
  - `1.0.42.7.0.255` attr 2 (REGISTER)
  - `1.0.62.7.0.255` attr 2 (REGISTER)
  - `1.0.3.7.0.255` attr 2 (REGISTER)
  - `1.0.23.7.0.255` attr 2 (REGISTER)
  - `1.0.43.7.0.255` attr 2 (REGISTER)
  - `1.0.63.7.0.255` attr 2 (REGISTER)
  - `1.0.4.7.0.255` attr 2 (REGISTER)
  - `1.0.24.7.0.255` attr 2 (REGISTER)
  - `1.0.44.7.0.255` attr 2 (REGISTER)
  - `1.0.64.7.0.255` attr 2 (REGISTER)
  - `1.0.13.7.0.255` attr 2 (REGISTER)
  - `1.0.33.7.0.255` attr 2 (REGISTER)
  - `1.0.53.7.0.255` attr 2 (REGISTER)
  - `1.0.73.7.0.255` attr 2 (REGISTER)
  - `1.0.81.7.40.255` attr 2 (REGISTER)
  - `1.0.81.7.51.255` attr 2 (REGISTER)
  - `1.0.81.7.62.255` attr 2 (REGISTER)
### `0.0.98.1.0.255`
- capturePeriod: 0 s · entriesInUse: 1
  - `0.0.1.0.0.255` attr 2 (CLOCK)
  - `1.0.98.1.0.255` attr -1 (PROFILE_GENERIC)
  - `1.0.0.1.0.255` attr 2 (DATA)
  - `1.0.0.1.2.255` attr 2 (DATA)
  - `1.0.1.8.0.255` attr 2 (REGISTER)
  - `1.0.1.8.1.255` attr 2 (REGISTER)
  - `1.0.1.8.2.255` attr 2 (REGISTER)
  - `1.0.1.8.3.255` attr 2 (REGISTER)
  - `1.0.1.8.4.255` attr 2 (REGISTER)
  - `1.0.1.8.5.255` attr 2 (REGISTER)
  - `1.0.1.8.6.255` attr 2 (REGISTER)
  - `1.0.1.8.7.255` attr 2 (REGISTER)
  - `1.0.1.8.8.255` attr 2 (REGISTER)
  - `1.0.2.8.0.255` attr 2 (REGISTER)
  - `1.0.2.8.1.255` attr 2 (REGISTER)
  - `1.0.2.8.2.255` attr 2 (REGISTER)
  - `1.0.2.8.3.255` attr 2 (REGISTER)
  - `1.0.2.8.4.255` attr 2 (REGISTER)
  - `1.0.2.8.5.255` attr 2 (REGISTER)
  - `1.0.2.8.6.255` attr 2 (REGISTER)
  - `1.0.2.8.7.255` attr 2 (REGISTER)
  - `1.0.2.8.8.255` attr 2 (REGISTER)
  - `1.0.1.6.0.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.1.6.1.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.1.6.2.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.1.6.3.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.1.6.4.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.1.6.5.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.1.6.6.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.1.6.7.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.1.6.8.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.2.6.0.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.2.6.1.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.2.6.2.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.2.6.3.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.2.6.4.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.2.6.5.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.2.6.6.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.2.6.7.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.2.6.8.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.1.6.0.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.1.6.1.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.1.6.2.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.1.6.3.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.1.6.4.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.1.6.5.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.1.6.6.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.1.6.7.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.1.6.8.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.2.6.0.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.2.6.1.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.2.6.2.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.2.6.3.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.2.6.4.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.2.6.5.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.2.6.6.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.2.6.7.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.2.6.8.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.1.2.0.255` attr 2 (REGISTER)
  - `1.0.1.2.1.255` attr 2 (REGISTER)
  - `1.0.1.2.2.255` attr 2 (REGISTER)
  - `1.0.1.2.3.255` attr 2 (REGISTER)
  - `1.0.1.2.4.255` attr 2 (REGISTER)
  - `1.0.1.2.5.255` attr 2 (REGISTER)
  - `1.0.1.2.6.255` attr 2 (REGISTER)
  - `1.0.1.2.7.255` attr 2 (REGISTER)
  - `1.0.1.2.8.255` attr 2 (REGISTER)
  - `1.0.2.2.0.255` attr 2 (REGISTER)
  - `1.0.2.2.1.255` attr 2 (REGISTER)
  - `1.0.2.2.2.255` attr 2 (REGISTER)
  - `1.0.2.2.3.255` attr 2 (REGISTER)
  - `1.0.2.2.4.255` attr 2 (REGISTER)
  - `1.0.2.2.5.255` attr 2 (REGISTER)
  - `1.0.2.2.6.255` attr 2 (REGISTER)
  - `1.0.2.2.7.255` attr 2 (REGISTER)
  - `1.0.2.2.8.255` attr 2 (REGISTER)
  - `1.0.3.8.0.255` attr 2 (REGISTER)
  - `1.0.3.8.1.255` attr 2 (REGISTER)
  - `1.0.3.8.2.255` attr 2 (REGISTER)
  - `1.0.3.8.3.255` attr 2 (REGISTER)
  - `1.0.3.8.4.255` attr 2 (REGISTER)
  - `1.0.3.8.5.255` attr 2 (REGISTER)
  - `1.0.3.8.6.255` attr 2 (REGISTER)
  - `1.0.3.8.7.255` attr 2 (REGISTER)
  - `1.0.3.8.8.255` attr 2 (REGISTER)
  - `1.0.4.8.0.255` attr 2 (REGISTER)
  - `1.0.4.8.1.255` attr 2 (REGISTER)
  - `1.0.4.8.2.255` attr 2 (REGISTER)
  - `1.0.4.8.3.255` attr 2 (REGISTER)
  - `1.0.4.8.4.255` attr 2 (REGISTER)
  - `1.0.4.8.5.255` attr 2 (REGISTER)
  - `1.0.4.8.6.255` attr 2 (REGISTER)
  - `1.0.4.8.7.255` attr 2 (REGISTER)
  - `1.0.4.8.8.255` attr 2 (REGISTER)
  - `1.0.3.6.0.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.3.6.1.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.3.6.2.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.3.6.3.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.3.6.4.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.3.6.5.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.3.6.6.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.3.6.7.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.3.6.8.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.4.6.0.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.4.6.1.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.4.6.2.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.4.6.3.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.4.6.4.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.4.6.5.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.4.6.6.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.4.6.7.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.4.6.8.255` attr 2 (EXTENDED_REGISTER)
  - `1.0.3.6.0.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.3.6.1.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.3.6.2.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.3.6.3.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.3.6.4.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.3.6.5.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.3.6.6.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.3.6.7.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.3.6.8.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.4.6.0.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.4.6.1.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.4.6.2.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.4.6.3.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.4.6.4.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.4.6.5.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.4.6.6.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.4.6.7.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.4.6.8.255` attr 5 (EXTENDED_REGISTER)
  - `1.0.3.2.0.255` attr 2 (REGISTER)
  - `1.0.3.2.1.255` attr 2 (REGISTER)
  - `1.0.3.2.2.255` attr 2 (REGISTER)
  - `1.0.3.2.3.255` attr 2 (REGISTER)
  - `1.0.3.2.4.255` attr 2 (REGISTER)
  - `1.0.3.2.5.255` attr 2 (REGISTER)
  - `1.0.3.2.6.255` attr 2 (REGISTER)
  - `1.0.3.2.7.255` attr 2 (REGISTER)
  - `1.0.3.2.8.255` attr 2 (REGISTER)
  - `1.0.4.2.0.255` attr 2 (REGISTER)
  - `1.0.4.2.1.255` attr 2 (REGISTER)
  - `1.0.4.2.2.255` attr 2 (REGISTER)
  - `1.0.4.2.3.255` attr 2 (REGISTER)
  - `1.0.4.2.4.255` attr 2 (REGISTER)
  - `1.0.4.2.5.255` attr 2 (REGISTER)
  - `1.0.4.2.6.255` attr 2 (REGISTER)
  - `1.0.4.2.7.255` attr 2 (REGISTER)
  - `1.0.4.2.8.255` attr 2 (REGISTER)
### `1.0.98.1.0.255`
- FAIL: Wrong CRC.
### `0.0.98.2.0.255`
- FAIL: Failed to receive reply from the device in given time.
### `1.0.98.2.0.255`
- FAIL: Failed to receive reply from the device in given time.

## Result: SCAN COMPLETE
