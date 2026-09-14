# Batch evaluation — M14 (central-push 01–08) บน pipeline slim

แผ่นนี้ **ล็อกก่อนเริ่ม batch** และก่อนมีโค้ดของตั๋วใดๆ อยู่จริง จุดประสงค์คือตอบว่า pipeline ใหม่
(`~/.claude` commit `1da4544`) ได้งานถูกเท่าเวอร์ชันเดิม (`1da4544^`) หรือไม่ และใช้ต้นทุนเท่าไร

- **Commit ก่อนเริ่ม:** `28f334e` (ตั๋ว) + commit ของไฟล์นี้
- **Suite ก่อนเริ่ม:** ดูหัวข้อ Baseline ด้านล่าง

## กติกา (ห้ามแก้หลังเริ่ม batch)

1. **คนตรวจไม่ใช่ orchestrator ของ batch** ใช้ agent ใหม่ หรือ session หลักหลัง batch จบ
2. **รายการ mutation ด้านล่างถูกล็อก** เพราะนิยามเป็น *พฤติกรรม* ไม่ใช่บรรทัดของโค้ด จึงเขียนได้ก่อนโค้ดมีจริง
   - ถ้าโครงสร้างโค้ดทำให้ mutation เขียนตรงตัวไม่ได้ ให้ทำลายพฤติกรรมเดียวกันด้วยวิธีที่ใกล้ที่สุด แล้วจดว่าทำอย่างไร
   - ห้ามตัดทิ้ง
   - ถ้าตรวจแล้วอยากเพิ่ม mutation ใหม่ ให้จดแยกในหัวข้อ "เพิ่มเติม" และห้ามนับรวมในคะแนน Q1
3. **ขั้นตอนต่อหนึ่ง mutation**
   1. เก็บ hash ของไฟล์ไว้ก่อน
   2. แก้โค้ดตามที่ระบุ
   3. รันเฉพาะไฟล์เทสต์ที่เกี่ยวข้อง ด้วย `pytest` แบบธรรมดา (ไม่ใช้ `-n auto`) และตั้ง timeout
   4. คืนไฟล์ แล้วตรวจว่า hash ตรงกับตอนก่อนแก้
   5. ตรวจ `git status` ด้วย (บทเรียน: mutation-probe-can-leave-the-mutation-on-disk)
4. **วิธีจดผล**
   - **แดง**: มีเทสต์ล้มอย่างน้อยหนึ่งตัว ให้จดจำนวนตัวที่ล้มด้วย (ล้มตัวเดียวแปลว่าแม่นยำ)
   - **เขียว**: ไม่มีเทสต์ไหนจับได้ ถือเป็นเกณฑ์ที่ไม่มีเทสต์คุ้มจริง
   - **N/A**: ทำ mutation ไม่ได้เลย ต้องเขียนเหตุผลกำกับ
5. **Invariance ต้องทำลายด้านเดียว** mutation ที่ทำให้ทั้งสองฝั่งผิดพร้อมกันพิสูจน์อะไรไม่ได้
   (บทเรียน: write-required-tests-as-mutations-not-scenarios)

## ตัววัด

| | ตัววัด | นิยาม |
|---|---|---|
| Q1 | เกณฑ์ที่มีเทสต์คุ้มจริง | จำนวนแดง ÷ (ทั้งหมด − N/A) ต่อตั๋ว และรวมทั้ง batch |
| Q2 | ของหลุด | defect ที่พบหลังตั๋ว commit แล้ว นับให้ตั๋วต้นเหตุ (ดูหัวข้อ Q2) |
| Q3 | เกณฑ์ครบ | ติ๊กเกณฑ์ในตั๋วทีละข้อเทียบกับ diff และรายการ Check ด้านล่าง |
| C1 | เวลา | นาทีต่อตั๋ว, median ของ batch, และนาทีต่อ 100 บรรทัดที่เปลี่ยน (`git show --stat`) |
| C2 | tokens | ค่าสุดท้ายของแต่ละ agent เท่านั้น เพราะเป็นค่าสะสม ห้ามบวกข้ามรอบ |
| C3 | การแทรกแซง | ครั้งที่มนุษย์ต้องเข้ามา · agent ตาย · SKIPPED / NOT_APPROVED / ERROR |
| C4 | รอบที่เสียกับ minor/nit | นาทีของรอบแก้และรอบรีวิวซ้ำ ที่ไม่มี blocker หรือ major |

**เกณฑ์ตัดสิน**
- **ดีกว่าจริง**: C1 และ C4 ลดลง, Q1 ≥ 90%, และ Q2 ไม่มากกว่าเวอร์ชันเดิม
- **แค่ย้ายต้นทุน**: เวลาลดลง แต่ Q1 < 90% หรือ Q2 เพิ่มขึ้น

## Baseline

**Pipeline เวอร์ชันเดิม** (จาก `.claude/run-logs/`)
- เวลา: median **76 นาทีต่อ issue** จาก 14 issue (ตัวเลขใน `run-batch.md`) · #38 ~115 นาที, #40 ~89, #41 ~101
- รอบรีวิว: 12 ledger ที่ตรวจ (010–013, 015, 35–38, 40, 41, 46) ใช้ 2 รอบ **ทุกใบ**
  - รอบแรกของ 010–015 เจอแค่ minor/nit
  - #46 เจอ major 1 ข้อ
- C4 ตัวอย่าง #015: รอบแก้ 7.6 นาที + รีวิวซ้ำ 5.1 นาที
- Q1 หลังแก้: #015 19/19 · #46 40/40 (mutation table ของ implementer)
- tokens #015: reviewer 240k · implementer 356k (ค่าสะสม)
- Q2 ที่เคยเกิด: #38 → #40 ต้องตามแก้ · GitHub #32 ถูกปิดโดยไม่มีการแก้

**ข้อจำกัดของ baseline**
- ตั๋วคนละชุด ขนาดงานไม่เท่ากัน
- batch M13 (export-files) ไม่มี ledger
- "รอบรีวิว" ของสองเวอร์ชันนิยามต่างกัน จึงไม่ใช้เป็นตัววัด

**Suite ก่อนเริ่ม:** รันเมื่อ 2026-09-14 (วันจันทร์) ที่ `28f334e` ได้ `1 failed, 2108 passed, 57 skipped in 105.61s`
- เทสต์ที่ล้มคือ `test_energy_csv_export.py::TestTheOnDemandSave::test_it_corrects_a_day_the_daily_file_already_wrote_under_the_old_rules`
- สาเหตุ: เทสต์ใช้ `yesterday` เป็นวันทดสอบ ถ้า yesterday ตรงกับเสาร์หรืออาทิตย์ energy ของวันนั้นเข้า Holiday bucket อยู่แล้วตั้งแต่ก่อนเพิ่มวันหยุด assertion `!=` จึงล้ม
- ผลคือล้มทุกวันอาทิตย์และวันจันทร์ **ไม่ใช่ความผิดของ batch นี้**
- **แก้ก่อนเริ่ม batch:** ให้เทสต์ใช้วันธรรมดาล่าสุดแทน
  - ลองให้โค้ดไม่นับ public Holiday แล้วเทสต์แดง จึงยังจับบั๊กได้
  - gate หลังแก้: `2109 passed, 57 skipped in 137.43s` · ruff สะอาด
  - **นี่คือค่าตั้งต้นที่ใช้นับเทสต์ที่เพิ่มขึ้น**

## Mutation ที่ล็อกไว้ (Q1)

### 01 — Energy Summary stored + recomputed
| # | เกณฑ์ | Mutation | ผล |
|---|---|---|---|
| 01-1 | Stored, not live | `GET /api/energy/summary` คำนวณสดจาก load profile แทนอ่านตาราง | |
| 01-2 | Retroactive / Late readings | recompute คำนวณแค่วันนี้ ไม่ย้อน 90 วัน | |
| 01-3 | Retroactive | recompute ไม่นับ Holiday (นับแค่เสาร์-อาทิตย์) | |
| 01-4 | Output Parity | recompute ไม่กรอง all-invalid interval (ทางคำนวณสดยังกรองอยู่) | |
| 01-5 | Quiet recompute | upsert ตั้ง `updated_at = now` ทุกครั้งแม้ค่าไม่เปลี่ยน | |
| 01-6 | Quiet recompute (เฉพาะวันที่เปลี่ยน) | มีวันเปลี่ยนหนึ่งวัน → ขยับ `updated_at` ทุกวันของ device นั้น | |
| 01-7 | ไม่มี reading ไม่มีแถว | เขียนแถวค่าศูนย์ให้วันที่ไม่มี reading | |
| 01-8 | Retention | retention ไม่ลบ `energy_summary_days` | |
| 01-9 | ลำดับ job | ลงทะเบียน recompute **ก่อน** load-profile | |

### 02 — atomic rewrite, one head
| # | เกณฑ์ | Mutation | ผล |
|---|---|---|---|
| 02-1 | Atomicity | เขียนทับไฟล์เป้าหมายตรงๆ ไม่ผ่านไฟล์ temp | |
| 02-2 | ไม่มี temp ค้าง | ตัดการลบ temp ในทาง failure | |
| 02-3 | Head mismatch → ไฟล์เดียว | คืนทาง rename เป็นไฟล์ติดวันที่ | |
| 02-4 | Head mismatch rewrite | head ไม่ตรงแล้ว append ต่อใต้ head เดิม | |
| 02-5 | LP render ทั้งไฟล์ | ไม่ตั้ง watermark เป็นแถวใหม่สุดที่เขียน | |
| 02-6 | Billing render | รวม Open Period ด้วย | |
| 02-7 | Auto-save | ทาง rewrite ไม่ดูสวิตช์ auto-save | |

**Check (ไม่ใช่ mutation):** `git diff 28f334e --` บนไฟล์เทสต์ export ที่มีอยู่เดิม ต้องไม่มี assertion ถูกแก้ · grep ต้องไม่เหลืออะไรอ้างถึงทาง rename หรือ Closed Edition ใน `app/src`

### 03 — Push Token
| # | เกณฑ์ | Mutation | ผล |
|---|---|---|---|
| 03-1 | claim `product` | `sign-push` ใส่ `product` = `arichds` | |
| 03-2 | ไม่มี `exp` | `sign-push` ใส่ `exp` | |
| 03-3 | verifier เช็ค product | verifier ไม่เช็ค `product` | |
| 03-4 | Domain separation (อีกทาง) | ตัวตรวจ Activation Code รับ Push Token ได้ | |
| 03-5 | `v` | verifier ไม่เช็ค `v` | |
| 03-6 | Machine ID ผิดรูป | ตัดการตรวจรูปแบบ Machine ID ใน `sign-push` | |
| 03-7 | เหตุผลแยกกัน | ทุกความล้มเหลวคืนเหตุผลเดียวกัน | |

**Check:** ไม่มี dependency ใหม่ใน `pyproject.toml` · ทาง `sign-push` ไม่เรียก keygen

### 04 — Energy / Billing rewritten every cycle
| # | เกณฑ์ | Mutation | ผล |
|---|---|---|---|
| 04-1 | Matches the page | เขียน Energy file เฉพาะวันที่ยังไม่เคย export (เก็บพฤติกรรม watermark เดิมไว้) | |
| 04-2 | All closed periods | Billing file จำกัดแค่ 90 วัน | |
| 04-3 | Window | Energy file ไม่ตัดหน้าต่าง 90 วัน | |
| 04-4 | Open Period excluded | Billing file รวม Open Period | |
| 04-5 | Save to file | Save to file ไม่สนวันสิ้นสุดของช่วงที่เลือก | |
| 04-6 | Auto-save | สวิตช์ปิดแล้วยังเขียนไฟล์ | |

**Check:** grep `energy_exported_through|billing_exported_through` ใน `app/src` ต้องเหลือเฉพาะใน migration

### 05 — LP CSV keeps 90 days
| # | เกณฑ์ | Mutation | ผล |
|---|---|---|---|
| 05-1 | Window | job รายวัน rewrite ด้วยทุกแถว ไม่ตัดหน้าต่าง | |
| 05-2 | Cadence | cycle 15 นาทีเรียก rewrite | |
| 05-3 | Faithful | ทาง rewrite ไม่ใช้ skew cap หรือไม่รวม Logger 2 (ทาง append ยังใช้ครบ) | |
| 05-4 | Watermark ซ้ำ | หลัง rewrite ตั้ง watermark เป็นแถวเก่าสุด | |
| 05-5 | Watermark ช่องโหว่ | หลัง rewrite ตั้ง watermark เป็นเวลาปัจจุบัน | |
| 05-6 | Auto-save | สวิตช์ปิดแล้ว job รายวันยังเขียน | |

### 06 — Holiday Change record
| # | เกณฑ์ | Mutation | ผล |
|---|---|---|---|
| 06-1 | ทั้งห้าทาง | CSV import ไม่บันทึก | |
| 06-2 | ทั้งห้าทาง | delete ไม่บันทึก | |
| 06-3 | หนึ่งแถวต่อ import | Import from meter บันทึกหนึ่งแถวต่อ Holiday | |
| 06-4 | refused → ไม่บันทึก | บันทึกก่อน validation (Holiday ที่ชนก็ถูกบันทึก) | |
| 06-5 | non-admin อ่านได้ | endpoint อ่านบังคับ admin | |
| 06-6 | newest first | เรียงเก่าก่อน | |
| 06-7 | App Log | ไม่เขียน App Log | |
| 06-8 | Retention | retention ไม่ลบ `holiday_changes` | |

**Check:** grep `affected_date|energy_files_written_past` ใน `app/src` และ `web/src` ต้องเป็นศูนย์ · ไม่มีสตริงภาษาไทยใน `web/`

### 07 — API page configuration
| # | เกณฑ์ | Mutation | ผล |
|---|---|---|---|
| 07-1 | Token write-only | response ของ configuration คืน token ด้วย | |
| 07-2 | Redaction | filter ไม่ครอบ key ของ token | |
| 07-3 | Machine ID ต้องตรง | ตัดการเทียบ Machine ID | |
| 07-4 | ปฏิเสธ Activation Code | ใช้ตัวตรวจ Activation Code แทนตัวตรวจ Push Token | |
| 07-5 | Admin-only | ตัด admin guard จาก GET configuration | |
| 07-6 | Rendered from models | สร้าง contract จากรายการฟิลด์ที่เขียนตายตัว แทนการอ่านจาก model | |
| 07-7 | URL ว่าง = ปิด | URL ว่างรายงานว่าเปิด | |

**Check:** `test_nav_feature_contract.py` เขียว · router ไม่มี `require_feature`

### 08 — push cycle
| # | เกณฑ์ | Mutation | ผล |
|---|---|---|---|
| 08-1 | Opt-out | URL ว่างแล้วยังเรียก holdings | |
| 08-2 | Second cycle roster only | ไม่ถาม holdings แล้วส่งทุกอย่างทุก cycle | |
| 08-3 | Changed Open Period | billing เทียบด้วย `bill_date` แทน `updated_at` | |
| 08-4 | LP ต่อ logger | LP เทียบกับ `read_at` ใหม่สุดข้ามทุก logger | |
| 08-5 | Licensed kinds | ส่ง Energy Summary โดยไม่ดู `energy_summary` | |
| 08-6 | ไม่มี Meter Serial | ส่งแถวที่ serial เป็น null | |
| 08-7 | Stall abandoned | ตัด read timeout และ budget | |
| 08-8 | Offset บน instant | serialize instant เป็นแบบ naive | |
| 08-9 | kWh เสมอ | ใช้ค่าตั้งหน่วยแสดงผลกับ payload | |
| 08-10 | ลำดับ job | ลงทะเบียนก่อน `dbdest_sync` | |
| 08-11 | Status on failure | ไม่บันทึก status เมื่อ cycle ถูก skip | |

## บันทึกต่อตั๋ว (กรอกหลัง batch)

| ตั๋ว | Status | นาที | บรรทัด +/− | นาที/100 บรรทัด | รอบ | C4 นาที | tokens impl / rev | Q1 แดง/ทั้งหมด | Q3 ครบ | เทสต์เพิ่ม |
|---|---|---|---|---|---|---|---|---|---|---|
| 01 | | | | | | | | | | |
| 02 | | | | | | | | | | |
| 03 | | | | | | | | | | |
| 04 | | | | | | | | | | |
| 05 | | | | | | | | | | |
| 06 | | | | | | | | | | |
| 07 | | | | | | | | | | |
| 08 | | | | | | | | | | |

## Q2 — ของหลุด (เปิดบันทึกจนถึงการ smoke test M14 บนเครื่องจริง)

| วันที่ | พบโดย | ตั๋วต้นเหตุ | อาการ | ความรุนแรง |
|---|---|---|---|---|

## เพิ่มเติม (ไม่นับคะแนน)

## ขอบเขตการเทียบกับ pipeline เดิม (เจ้าของตัดสิน 2026-09-14)

- **เทียบ:** ต้นทุน C1–C4 กับ ledger เดิม, C1 ต่อ 100 บรรทัดจาก `git show --stat` ของ commit เดิม, และ Q2 ของเวอร์ชันเดิมนับจาก `fix:` commit ใน git log ที่ตามแก้ issue ก่อนหน้า
- **ไม่ทำ:** ตรวจ Q1 ย้อนหลังกับ issue เก่า และ A/B ตั๋ว 03 บนเวอร์ชันเดิม
- **ผลที่ตามมา:** Q1 ของ M14 ยังรายงานได้ แต่ไม่มีตัวเทียบที่วัดด้วยวิธีเดียวกัน จึงห้ามเขียนว่าคุณภาพ "เท่าเดิม" หรือ "ดีกว่า"
- batch นี้รันใน session เดียวกับที่เขียนแผ่นนี้ ดังนั้นตาม **กติกาข้อ 1** คนตรวจต้องเป็น agent ใหม่
