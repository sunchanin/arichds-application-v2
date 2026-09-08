# Requirements brief: แก้ไข capture และฟอร์ม billing+เมนู  sum energy.xlsx

**Source:** `source/แก้ไข capture และฟอร์ม billing+เมนู  sum energy.xlsx` · ingested 2026-09-08 · sha256 `fab6b4563f65`
**Original path:** C:\Users\HP\Downloads\แก้ไข capture และฟอร์ม billing+เมนู  sum energy.xlsx

## Summary

A 5-sheet workbook whose own filename states its subject: "fix capture and the billing form + the sum energy menu". Sheets 1–2 are feedback on the **Billing page and its Capture behaviour**, each carrying screenshots of *three different products* side by side — v1 (`ARICHDS v1.0`, the Electron-style app with a File/Setting/Help menu bar), v2 (`localhost:8000`, the teal SPA, badge "Licensed to logger-4"), and an older Windows-Forms application with an icon toolbar — plus one screenshot of a **Provincial Electricity Authority (PEA) energy-management summary document** that has an ARICHDS billing screenshot pasted into it as evidence. Sheets 3–4 are two sample billing output files for the same meter (`WP080672`, customer `TFTECH`), one labelled "loaded by Auto" and one "loaded manually", differing by exactly four Export-energy columns marked in red. Sheet 5 is one screenshot of v2's Energy Summary page with two lines of note. The notes are Thai, terse, in column AF (sheet 1), F60 (sheet 2), C17 (sheets 3–4) and Z20:Z21 (sheet 5); several name people ("ซัน", "โจ", "sino").

Sheet 1 is titled "Billing อันเก่า" (*the old billing*) and sheet 2 "Bill ใหม่" (*the new bill*), but **both sheets contain screenshots of both the old and the new product**, so the sheet names cannot be taken as labelling their contents — see the open questions.

## Terminology

Glossary read: `CONTEXT.md` at the repo root. `CONTEXT-MAP.md` and `docs/agents/domain.md` do not exist.

| Customer's term | Where | Glossary term | Status | Note |
|---|---|---|---|---|
| capture / cap | AF14, AF15, AF20, AF24, AF26, F60 | **Capture** | match | glossary: a document written for a *closed* Billing Reading into `capture_dir`; three formats share one stem and the `.png` spans ten periods (ADR 0015) |
| ตัดบิล / รอบการตัดบิล ("bill cut", "billing cycle") | AF17, AF18, AT53 | **Bill Date** / **Open Period** | conflict | glossary splits the concept in two — the meter-stamped `bill_date` of a *closed* period versus the provisional Open Period. The note's "รอบตัดบิลปัจจุบัน" (current billing cycle) maps to neither cleanly |
| Bill total | AF18 | — | missing | customer defines it inline as "all meters that have had a bill cut, ignoring the billing cycle"; no glossary entry, no screen shows it |
| ดึง / ดึงซ้ำ ("pull", "re-pull") | AF10, AF11, AF12, B17/G16 of the other file | **Manual Read** / **Poller** | conflict | the customer's "ดึงซ้ำทุกๆ15 นาที" is a *retry* policy; the glossary has no retry concept — a background tick that cannot take the Transport Endpoint lock is **skipped, never queued** (ADR 0006) |
| หลังบ้าน ("back end") | AF15 | — | missing | customer contrasts it with "keeping this page open"; v2 already captures server-side (ADR 0017), v1 did not |
| ไฮไลน์ / ไฮไลต์ ("highlight") | AF20, AF26 | — | missing | no glossary entry; v1's Billing screen shows a lavender-highlighted first row (`01-billing-อันเก่า-5.png`) |
| campare (compare) | AF24, AF26, AT53 | **Output Parity** | conflict | Output Parity is v1-vs-v2 *our* numbers; the customer means *bill document* vs *captured image* — a different comparison entirely |
| เว็บ ("the web") | AF24, AF27 | — | missing | a separate web product the customer intends to extend to; not this repo's SPA |
| ฟอร์มของไฟฟ้า / ผู้ขายไฟหลัก | AF27 | — | missing | "the electricity authority's form and the main power seller's" — the PEA document in `01-billing-อันเก่า-4.jpg` |
| Record No | C7/A7 of sheets 3–4 | — | missing | a 1-based row counter in the export file; v2's Billing page has no such column |
| Record Status | T7/X7 of sheets 3–4 | **Records** | conflict | glossary's **Records** is a per-day completeness grid; this is a per-row status string, rendered `..........` in every sample row |
| Setting : | A4 of sheets 3–4 | — | missing | a file header field whose value is the number `1`; meaning unknown |
| Customer : / Site Name : | A1/A2 of sheets 3–4 | — | missing | file header fields; v2 has no Customer or Site concept, v1's Billing screen shows "Site Name" and "Site Code" |
| Group | v1 screenshots (`01-…-1.png`, `01-…-5.png`) | — | missing | v1 groups devices ("All", "CE", "solar-d 1"); v2's Devices page has no group |
| sum energy | filename | **Energy Summary** | match | v2's page is called "Energy Summary" |
| ปุ่มบันทึก ("save button") | Z20 | **Export Format** | conflict | the Export Format settings govern the **Load Profile CSV only** (ADR 0013); Billing has no equivalent auto-export setting, and the note asks for Energy to be stored "like load profile and billing" |

## Sections

### 01. Billing อันเก่า *("the old billing")*

**Screenshots:** five images, three of them distinct products.

- [`01-billing-อันเก่า-1.png`](source/images/01-billing-อันเก่า-1.png), anchored at A1 — **v1** (`ARICHDS v1.0`, 20/04/2026 11:21:49, user Admin).
- [`01-billing-อันเก่า-2.png`](source/images/01-billing-อันเก่า-2.png), anchored at G1 — a **red-and-black siren/alarm-beacon clip-art icon**, 384×384, no product content. Placed just above the AF10–AF12 note about failed pulls.
- [`01-billing-อันเก่า-3.png`](source/images/01-billing-อันเก่า-3.png), anchored at H2 — **v1's Battery Status page** (20/04/2026 11:22:17).
- [`01-billing-อันเก่า-4.jpg`](source/images/01-billing-อันเก่า-4.jpg), anchored at AF29 — a **PEA document**, page 2/2.
- [`01-billing-อันเก่า-5.png`](source/images/01-billing-อันเก่า-5.png), anchored at AS29 — **v1's Billing page again**, zoomed, 24/04/2026 09:49:45, mid-capture.

**Current state — image 1 (v1 Billing):**
Top menu bar: `File` `Setting` `Help`; right-hand badge `ARICHDS v1.0`. Icon navigation: `Devices` · `Load Profile` · `Records` · `Energy` · `Billing` (selected) · `Battery` · `DB Settings` · `API Config` · `Users` · `App Log`. Clock `20/04/2026, 11:21:49`, avatar `Admin`.
Page title `Billing`. Controls, in order: `Save Path:` with the value `C:/Users/ASUS/Desktop/cewe data data` and a `Browse` button · `Group:` `All` · a `Search...` box · the counters `Total Devices: 6`, `Devices with Issues: 2`, `Complete: 4` · `Auto Schedule: ● Running` with a red `Stop` button · `Device:` `All Devices` · `Site Name: -` `Site Code: -` · buttons `Read Billing` (highlighted), `Read Current`, `Capture` · `Export:` `Show`.
Tabs: `Billing` (selected) and `Billing Current`.
Table columns: `Name`, `Time`, `Total kWh Total`, `Total kWh Rate A`, `Total kWh Rate B`, `Total kWh Rate C`, `Export kWh Total`, `Export kWh Rate A`, `Export kWh Rate B`, `Export kWh Rate C`, `Prev kW Demand Rate A`, `Time of …` (cut off).
16 rows, device names like `twell (WP081125)`, `1 (WP077595)`, `AG-17 (WP079385)`, `Sub AD-23 (WP079298)`, `solar (WP063532)`, `test (WP063531)`. **The first row is highlighted lavender** and is the only one whose Time differs (`02-12-2025 10:00:00`); every other row reads `01-12-2025 00:00:00`. Status bar: `Data collection complete`.

**Current state — image 3 (v1 Battery Status):**
Same chrome, `Battery` selected. Filters `Start:`/`End:` (`Select date`), `Group: All`, `Device: All Devices`, a `Search...` box, buttons `Search Data` and `Reading`. A `Status Legend:` row — `Healthy (≥ 3:00:00 / 180 min)`, `Low (2:00–2:59 / 120–179 min)`, `Critical (< 2:00:00 / < 120 min)`, `Full battery = 5:59:00 (359 min)`. Columns `Site`, `Device Name`, `Meter`, `Date`, `Time`, `Status`, `Remaining Minutes`; 8 rows, sites `CE`, `CE-2`, `Zone C`, `gallery`, `office`; rows tinted by status. Pager showing page `1`.

**Current state — image 4 (the PEA document):**
Thai government form, PEA logo top-left, `สำหรับผู้รับบริการ` ("for the service recipient") top-right, `หน้า 2/2` bottom-right. Title `สรุปค่าจัดการพลังงาน` ("energy-management charge summary").
Header table: `ชื่อโครงการ` = a Solar Rooftop energy-management project for a Department of Corrections site at Klong Prem prison · `เลขที่สัญญา` = `PEA(EMD)-09/2022` · `อายุสัญญา` = `25 ปี` · `วันที่เริ่มให้บริการ` = `27 ตุลาคม พ.ศ. 2568` · `ค่าจัดการพลังงานเดือน` = `กุมภาพันธ์ พ.ศ. 2569` · `งวดการจ่ายเงินที่` = `4/300` · `ประเภทอัตรา` = `4.2.2` · `วันที่อ่านหน่วย` = `24 กุมภาพันธ์ 2569` · `รหัสเครื่องวัด` = `252706621`.
Second table `รายละเอียดการจัดการพลังงานไฟฟ้าภาพรวม`: `หมายเลขเครื่องวัด 252706621`, `ช่วงเวลาที่อ่านหน่วย 27 มกราคม 2569 - 23 กุมภาพันธ์ 2569`; columns `TOU Period` · `RATE ค่าไฟฟ้า` · `เลขที่อ่านหน่วยครั้งล่าสุด` · `เลขที่อ่านหน่วยครั้งก่อน` · `ปริมาณการใช้ไฟฟ้าเดือนปัจจุบัน (หน่วย)`. Rows: `kWh ON PEAK`/`RATE A`/`1,185.6741`/`1,185.6741`/`0.0000`; `kWh OFF PEAK`/`RATE B`/`122.7142`/`122.7137`/`0.0005`; `kWh HOLIDAY`/`RATE C`/`1,138.6002`/`1,138.6002`/`0.0000`; total `2,446.9885`/`2,446.9879`/`0.0005`.
Third table `รายการคำนวณค่าจัดการพลังงานจากการผลิตพลังงานไฟฟ้า`: per-TOU-rate quantity, `อัตราค่าไฟฟ้าฐาน` at normal rate and after a 10 % discount (`4.1839`/`3.7655`, `2.6037`/`2.3433`, `2.6037`/`2.3433`), money column `*ไม่รวมภาษีมูลค่าเพิ่ม`, all `0.00`.
Footer line `การไฟฟ้าส่วนภูมิภาคได้ตรวจสอบและยืนยันว่าข้อมูลข้างต้นถูกต้อง`.
**Below the footer, inside a black border, a screenshot of the older Windows-Forms ARICHDS billing screen is pasted in** — `Save Path C:/cewe/Billing`, `Auto Read Schedule (Default for All Devices)`, `Status Running`, `Total Devices 15`, `Complete Devices 15`, a `Billing`/`Current` tab pair, and a data table of `cewe wolflink active (WP063527)` rows. Status bar: `Capture bill data WP063527…`.

**Current state — image 5 (v1 Billing, zoomed, mid-capture):**
Same as image 1 but `Group: CE`, `Device: twell - WP081125`, `Site Name: CE`, `Site Code: CE-01`, clock `24/04/2026, 09:49:45`. The third button now reads **`Capturing…`** instead of `Capture`. The table holds **one** row, `twell (WP081125)` / `02-12-2025 10:00:00`, **highlighted lavender**.

**Customer notes (verbatim), 13 cells:**

- AF10: "สามารถกดดูได้ด้วยว่า ที่ไหนไม่ดึงในตามรอบของการดึงบิลล่าสุด" → "Should also be able to click and see which ones did not get pulled in the latest bill-pull cycle."
- AF11: "และตั้งการดึงซ้ำได้ให้ดึงซ้ำทุกๆ15 นาทีจนกว่าจะได้  เพราะบางทีสื่อสารอาจจะ" → "And be able to set a re-pull, re-pulling every 15 minutes until it succeeds, because sometimes the communication may"
- AF12: "ไม่สเถียรเอง  แต่อยากให้ดึงซ่ำตลอด" → "be unstable on its own. But I want it to keep re-pulling all the time." (*sic*: `สเถียร` for `เสถียร`, `ซ่ำ` for `ซ้ำ`)
- AF14: "เวลา capture จะเดขึ้นเวลาดึงแบบ manual และ auto" → "The capture time will come up when pulling both manually and automatically." (*sic*: `เดขึ้น`, most likely `เด้งขึ้น` = "pops up")
- AF15: "***ถ้าสามารถทำให้ หน้า billing แบบไม่ต้องเปิดหน้านี้ใว้ตลอดและ cap จากหลังบ้านก็ได้นะ โดยหน้า cap เป็นแบบที่ตกลงกันล่าสุด หรือให้เห็นประมาณรูปนี้กก็ได้" → "*** If you can make the billing page such that this page does not have to be kept open all the time, and cap from the back end, that's fine. With the cap page being the version we agreed on most recently, or roughly like this picture, that's fine too." (*sic*: `ใว้` for `ไว้`, `กก็` for `ก็`)
- AF17: "เพิ่มให้แสดงที่ตัดบิลทั้งหมดเพิ่ม" → "Also add showing all the bill cuts."
- AF18: "Bill total คือมิเตอร์ทั้งหมดที่มีการตัดบิลแบบไม่สนใจรอบการตัดบิล แต่ที่ทำมาแล้วสนใจในรอบตัดบิลปัจจุบัน" → "Bill total means all the meters that have had a bill cut, ignoring the billing cycle. But what has been built already cares about the current billing cycle."
- AF20: "ถ้า capture ของรายตัวให้มี ไฮไลน์ แบบนี้ในบิลล่าสุดด้วย" → "If it is a per-meter capture, have a highlight like this on the latest bill too."
- AF24: "**** อยากได้รูปและสามารถ campare ค่าแสดงในบิลและรูปที่ cap ได้ โดยจะทำต่อยอดไปที่เว็บ" → "**** I want the image, and to be able to compare the values shown in the bill with the capped image. This will be built onward into the web."
- AF25: "ที่พวก sino กับทางซันและโจ" → "the one with sino and with Sun and Jo."
- AF26: "โดยเวลาเช็คค่าคือสีที่ไฮไลต์ให้ตรงกัน กับรูปที่ cap  แต่ทำเมนูแยกในการตรวจสอบได้" → "When checking the values, the highlighted colour should match the capped image. But it can be a separate menu for the checking."
- AF27: "*** จะทำในส่วนของเว็บที่ฟอร์มของเว็บที่เกี่ยวกับงานไฟฟาเท่านั้น  โดยฟอร์มจะเป็นของไฟฟ้า และผู้ขายไฟหลัก" → "*** It will be done in the web part, on the web form relating to electricity work only. The form will be the electricity authority's and the main power seller's." (*sic*: `ไฟฟา` for `ไฟฟ้า`)
- AT53: "ส่วนมากจะเทียบค่าก่อนและค่าล่าสุดที่ตัดบิล" → "Mostly it compares the previous value and the latest value at the bill cut."

**Open questions:**

- [customer] AF10 — "which ones did not get pulled" refers to *meters*, or to *billing periods within one meter*? The v1 screen has a `Devices with Issues: 2` counter; is that counter the thing being asked for, or is a per-meter drill-down being asked for on top of it?
- [customer] AF11/AF12 — "every 15 minutes until it succeeds": until what, exactly? Until the meter answers at all, until a *new* Bill Date appears, or until every meter in the list has been read this cycle? And with what stop condition — forever, or bounded?
- [internal] The 15-minute retry cadence is numerically identical to the **Billing Change Check** interval already shipped (ADR 0018, issue #43). Is the customer describing a feature they already have and cannot see, or a genuinely different retry?
- [internal] ADR 0006 says a background tick that cannot take the Transport Endpoint lock is skipped and **never queued**. A retry loop is not the same as a queue, but the two need to be reconciled explicitly before anything is built.
- [customer] AF14 — is "capture time" a *column to display*, or a *notification that pops up*? The word `เด้งขึ้น` suggests a popup; the sheet gives no screenshot of one.
- [customer] AF15 — "the version we agreed on most recently" names a decision this brief has no record of. Which capture layout is it, and is `01-billing-อันเก่า-5.png` (one highlighted row) that layout, or the fallback ("or roughly like this picture")?
- [internal] AF15 also asks for capture "from the back end, without keeping the page open". v2 already does exactly this (ADR 0017 — headless Edge under a scheduled task, nobody signed in). Is the customer looking at v1 and asking for something v2 has, or is there a v2 case where a browser must be open?
- [customer] AF17/AF18 — "Bill total": is this a **new tab/page** listing every closed bill cut across all meters regardless of period, a **counter** beside `Total Devices`, or a change to what the existing Billing tab lists?
- [customer] AF20 — "highlight like this on the latest bill": the highlight in the screenshots marks the row whose Time differs from all the others. Is the rule "highlight the newest Bill Date", "highlight the row that differs from the rest", or "highlight the row this capture is about"?
- [customer] AF24/AF26/AT53 — the compare feature: which two things are compared, exactly? "the values shown in the bill" = the PEA document's numbers, or ARICHDS's own Billing table? And who enters the PEA numbers — is a human typing them in, or is a PEA file being read?
- [customer] AF27 — "It will be done in the web part" — **is this in scope for this product at all?** The note explicitly places the compare feature on a different web system ("จะทำต่อยอดไปที่เว็บ", "sino / Sun / Jo"). This is the single largest scope question in the document.
- [internal] Image 2 is a siren icon with no product content. It sits directly above the "which ones did not get pulled" note — is it decoration, or is the customer asking for an alert/alarm indicator?
- [internal] Image 3 (Battery Status) carries no note at all and no other note in this sheet mentions battery. Why is it here?
- [internal] All five images are of **v1** and older products, none of v2. Is this sheet feedback on v1 that has already been superseded, or a statement that v2 must reproduce v1's behaviour?

### 02. Bill ใหม่ *("the new bill")*

**Screenshots:** five images, of which **three are duplicates** (verified by sha256):

- [`02-bill-ใหม่-1.png`](source/images/02-bill-ใหม่-1.png), anchored at A1 — **v2's Billing page**. Identical to `02-bill-ใหม่-3.png` (anchored D63).
- [`02-bill-ใหม่-2.png`](source/images/02-bill-ใหม่-2.png), anchored at D18 — **identical to `01-billing-อันเก่า-1.png`**, v1's Billing page. Identical to `02-bill-ใหม่-4.png` (anchored F66).
- [`02-bill-ใหม่-5.png`](source/images/02-bill-ใหม่-5.png), anchored at F70 — the **older Windows-Forms application**.

Three images (D63, F66, F70) are anchored **below the sheet's own used range** (`A1:F60`).

**Current state — image 1 (v2 Billing):**
Dark teal header `ARICHDS`, badge `Licensed to logger-4`, `admin`, `Change password`, `Sign out`. Sidebar: `Devices` · `Load Profile` · `Records` · `Billing` (selected) · `Energy Summary` · `Holidays` · `Special Days` · `Battery` · `Export Format` · `App Log` · `User Management` · `Settings` · a section label `Data-out Destination` · `Database`.
Tabs `History` (selected) and `Current`. Filter row: a device select showing `3CL (002607000049)`, a range picker `Bill date from → Bill date to`, and a **`Capture image`** button.
Table with grouped headers `Import Active (kWh)` (Total, Rate A, Rate B, Rate C, Rate D), `Export Active (kWh)` (Total, Rate A, Rate B, Rate C, Rate D) and `Import Reactive (kvarh)` (Total, Rate A, Rate B, Rate C…) over a `Bill Date` column. **One row**: `2026-09-01 00:00`, `4463.222`, `3374.071`, `409.740`, `679.410`, `0.000`, `0.271`, `0.163`, `0.000`, `0.108`, `0.000`, `89.608`, `21.069`, `38.863`, `29.676`. Footer `1 rows`, pager `1`, `1 / page`. **No row is highlighted.**

**Current state — image 5 (the Windows-Forms application):**
An icon-only toolbar (9 icons). `Save Path` = `C:/Solar D/Back up` with `Browse`. A `Data Billing` group: `Group: solar-d 1`; a `Statistics Summary` sub-group with `Total Devices: 7`, `Devices with Issues: 0`, `Complete Devices: 7`; tabs `Billing` / `Current`; `Device: cewe solar-d - WP0635`, button `Read Billing`. An `Auto Read Schedule (Default for All Devices)` group: `Time: 00 : 35`, `Status: Running`, `Stop`. A `Data Table` group with a `Reload Table` button and columns `Name`, `Time`, `Total kWh Total`, `Total kWh Rate A`, `Total kWh Rate B`, `Total kWh Rate C`, `Prev kW Demand Rate A`, `Time of kW Demand A`, `Prev kW Demand Rate B`, `Time of kW Demand B`, `Prev kW Demand Rate C`, `Time of kW Demand C`, `Cumul kW Demand Rate`, `Cumul k…`. 16 rows for `cewe solar-d (WP063532)`, monthly from `2025-06-01 00:00:00` to `2026-09-01 00:00:00`. Status bar: `Capture bill data WP063532…`. **No Export kWh columns.**

**Customer notes (verbatim), 1 cell:**

- F60: "*** อยากได้แบบเก่านะ แต่แสดงเวลา cap มันจะ cap รายตัวไปเรื่อยๆจนครบที่ add เข้าระบบ" → "*** I want the old style. But show the time when capping — it will cap one by one until all the ones added into the system are done."

**Open questions:**

- [customer] F60 — "the old style" (`แบบเก่า`): which of the three products in this sheet? All three are visible here, and the sheet's title says "new bill".
- [customer] F60 — what specifically is "old style"? The v1/WinForms Billing table shows **one row per meter** (many meters, latest cut each); v2's shows **one meter's periods over time**. Is the ask a per-meter-across-all-meters table, or something about the visual style?
- [customer] F60 — "cap one by one until all the ones added into the system are done": is this describing the **desired** behaviour (capture every device in turn, automatically), or **observed** behaviour the customer is confirming is correct?
- [internal] v2 captures **eagerly and per closed period** (glossary: "Created eagerly, synchronously, the moment a closed period is inserted"). A sweep over "all devices added into the system" is a different trigger. Which one is being asked for?
- [internal] Three of the five images are exact duplicates of images already on this sheet or on sheet 1. Was the workbook assembled by pasting, and do the anchors below the used range (D63, F66, F70) carry meaning, or are they leftovers?

### 03. รูปแบบไฟล์ billing-auto *("billing file format — auto")*

**Screenshot:** none.
**Example data:** [`billing-auto.csv`](source/fixtures/billing-auto.csv), from `A7:T12` — **20 columns**, header row plus 5 data rows.

**File header block (A1:B5), quoted:**

- A1 `Customer :` / B1 `TFTECH`
- A2 `Site Name :` / B2 `TFTECH`
- A3 `Serial Meter :` / B3 `WP080672`
- A4 `Setting :` / B4 `1` (a number)
- A5 `Billing :` (no value beside it)

**Column headers (A7:T7), quoted in order:**
A7 `Record No` · B7 `Time` · C7 `111 Billing total kWh Total` · D7 `010 Billing total kWh Rate A` · E7 `020 Billing total kWh Rate B` · F7 `030 Billing total kWh Rate C` · G7 `050 Previous kW demand Rate A` · H7 `050T Previous Time of kW deman` · I7 `060 Previous kW demand Rate B` · J7 `060T Previous Time of kW deman` · K7 `070 Previous kW demand Rate C` · L7 `070T Previous Time of kW deman` · M7 `015 Cumul kW demand Rate A` · N7 `016 Cumul kW demand Rate B` · O7 `017 Cumul kW demand Rate C` · P7 `222 Billing total Varh Total` · Q7 `280 Previous Var demand Total` · R7 `280T Previous Time of Var dem` · S7 `118 Cumul Var demand Total` · T7 `Record Status`.

Note the headers are **truncated at 30 characters** (`…of kW deman`, `…of Var dem`) — consistent across both format sheets and both files, so the truncation is in the producing program, not a typing slip.

**Data cells that are strings rather than numbers:**

- H8, J8, L8, R8: `-` (four cells — the demand-time columns of row 1, where no demand time exists)
- T8, T9, T10, T11, T12: `..........` (five cells — the `Record Status` value on every row)

**Note (verbatim), 1 cell:**

- C17: "**** ตัวอย่างปกติ ที่โหลด Auto" → "**** A normal example, the one loaded by Auto."

**Observations recorded, not interpreted:**
Row 1 (`Record No` 1) has `Time` = `2026-05-07 14:25:50` — a wall-clock time, not a period boundary — with every energy and demand column `0` **except** `222 Billing total Varh Total` = `999570.1281`. Rows 2–5 are `2026-06-01`, `2026-07-01`, `2026-08-01`, `2026-09-01`, all at `00:00:00`. `Time` cells are **datetime** cells; the demand-time columns are datetimes in rows 2–5 and the string `-` in row 1.

**Open questions:**

- [customer] Row 1 — is this the Open Period, a commissioning/reset row, or a defect? Its Varh total is populated while everything else is zero.
- [internal] The sample has **no Export energy columns at all**, and the sheet name says "auto". Sheet 04, the manual one, has four. Is the difference *auto vs manual*, or *this meter vs that meter*, or *a setting*?
- [internal] `Record Status` is `..........` on every row of every sample in both workbooks. What is it, and has any sample ever shown a different value?
- [customer] `Setting : 1` — what is this field?

### 04. รูปแบบไฟล์ billing-ไม่ auto  *("billing file format — not auto")*

**Screenshot:** none.
**Example data:** [`billing-manual-with-export.csv`](source/fixtures/billing-manual-with-export.csv), from `A7:X12` — **24 columns**, header row plus 5 data rows.

Same meter, same customer, same five rows, same values as sheet 03. The header block is identical (A1 `Customer :`/B1 `TFTECH`, A2 `Site Name :`/B2 `TFTECH`, A3 `Serial Meter :`/B3 `WP080672`, A4 `Setting :`/B4 `1`, A5 `Billing :`).

**The only difference is four inserted columns, and they are the four the customer marked red:**

- G7 ` Billing total Export kWh Total` (leading space, *sic*)
- H7 `Billing total  Export  kWh Rate A` (double spaces, *sic*)
- I7 ` Billing total   Export kWh Rate B` (*sic*)
- J7 ` Billing total  Export  kWh Rate C` (*sic*)

**These four columns are empty in all five data rows.** Every other column shifts right by four (`050 Previous kW demand Rate A` moves G→K, `Record Status` moves T→X).

Remaining headers, unchanged in content: A7 `Record No` · B7 `Time` · C7 `111 Billing total kWh Total` · D7 `010 Billing total kWh Rate A` · E7 `020 Billing total kWh Rate B` · F7 `030 Billing total kWh Rate C` · K7 `050 Previous kW demand Rate A` · L7 `050T Previous Time of kW deman` · M7 `060 Previous kW demand Rate B` · N7 `060T Previous Time of kW deman` · O7 `070 Previous kW demand Rate C` · P7 `070T Previous Time of kW deman` · Q7 `015 Cumul kW demand Rate A` · R7 `016 Cumul kW demand Rate B` · S7 `017 Cumul kW demand Rate C` · T7 `222 Billing total Varh Total` · U7 `280 Previous Var demand Total` · V7 `280T Previous Time of Var dem` · W7 `118 Cumul Var demand Total` · X7 `Record Status`.

**Data cells that are strings:** L8, N8, P8, V8 = `-` (four cells); X8, X9, X10, X11, X12 = `..........` (five cells).

**Note (verbatim), 1 cell:**

- C17: "**** ตัวอย่างปกติ ที่โหลด เอง โดยเลือกที่มี export ด้วย" → "**** A normal example, loaded by oneself, choosing the one that has export as well."

**Open questions:**

- [customer] "choosing the one that has export as well" — is `export` a **checkbox the operator ticks before pulling**, or a property of the meter that the program detects? The wording (`โดยเลือก` = "by choosing") reads as an operator action.
- [customer] Why are the four Export columns present but **empty** in the sample? Does this meter genuinely export nothing, or was the sample produced before the values were read?
- [internal] There are three different spellings of the same four headers across the two workbooks (this sheet's leading/double spaces, and `ตัวอย่างไฟล์.xlsx`'s `Billing total Export kWh Total`). If the header row is a contract, exactly one spelling has to be the right one — and the whitespace is in the customer's own file.
- [internal] v2's Billing page **already shows** Export Active kWh Total/A/B/C/D (`02-bill-ใหม่-1.png`). The gap, if any, is in the **exported file**, not in the screen.
- [internal] The customer's columns carry **three tariffs** (Rate A/B/C); v2 stores **four** (`rate_a`…`rate_d`, glossary: Billing Reading) and the v2 screenshot shows a Rate D column. Which wins in the file?

### 05. Energy

**Screenshot:** [`05-energy-1.png`](source/images/05-energy-1.png), anchored at A1 — **v2's Energy Summary page**, photographed through an AnyDesk session to a machine named `LOGGER WC` (AnyDesk ID `1062896882`), Windows taskbar clock `2:45 PM 9/5/2026`.

**Current state:**
Edge, tab title `ARICHDS`, address `localhost:8000`. Same v2 chrome and sidebar as sheet 02, badge `Licensed to logger-4`, `Energy Summary` selected.
Tabs `Summary Report` (selected) and `Meter Registers`. Filter row: device select `3CL (002607000049)`, a `Single day` / `Range` toggle with `Range` active, and a date range `2026-08-30 → 2026-09-05`.
Table columns: `Date`, `Peak Import (kWh)`, `Off-Peak Import (kWh)`, `Holiday Import (kWh)`, `Total Import (kWh)`, `Peak Export (kWh)` (the table scrolls horizontally — a scrollbar is visible, so there are more columns off-screen).
Seven daily rows `2026-08-30` … `2026-09-05`, then a bold `Total` row: `1820.36`, `160.68`, `164.58`, `2145.63`, `0.08`. Both `2026-08-30` and `2026-09-05` show all import in the **Holiday** bucket (69.99 and 94.59) with Peak and Off-Peak at `0.00`.
**There is no save/export control anywhere on the page.**

**Customer notes (verbatim), 2 cells:**

- Z20: "ให้มีปุ่มบันทึกด้วย เก็บเหมือน load profile ละ billing " → "Have a save button too; store it like load profile and billing." (*sic*: `ละ` for `และ`; trailing space)
- Z21: "และรูปแบบฟอร์มเอาตามโปรแกรมได้เลย" → "And for the form's format, just take it from the program as it is."

**Open questions:**

- [customer] Z20 "save button" — save **to a file the operator downloads**, or save **into an auto-export folder** the way the Load Profile CSV does? The two are different features in v2.
- [customer] Z20 "store it like load profile and billing" — the word `เก็บ` ("store/keep") can mean *persist in the database* or *write a file*. The Energy Summary is deliberately **derived and never stored** (ADR 0012); if the ask is database persistence, that ADR is in play.
- [customer] Z21 "take the form's format from the program" — which program, and which form? v1's `Energy` page is visible in `01-billing-อันเก่า-1.png`'s nav bar but no screenshot of it exists in either workbook.
- [internal] Does "like load profile and billing" mean the **file layout** should match those exports (a `Customer :`/`Site Name :`/`Serial Meter :` header block over a table), or only that a save capability should exist?
- [internal] `2026-08-30` is a Sunday and `2026-09-05` a Saturday, which is why their energy lands in the Holiday bucket (glossary: Holiday swallows weekends). No note questions this, but it is the kind of thing that reads as a bug to a customer.

## Open questions (consolidated)

**Scope — answer first, it gates everything else**

1. [customer] AF27 — is the bill-vs-capture **compare feature in scope for ARICHDS at all**, or is it being built on the other web system ("sino / Sun / Jo")?
2. [internal] Sheets 01–02 are almost entirely screenshots of **v1 and an older Windows-Forms product**. Which notes are feedback on v2, and which are v1 history already answered by v2?

**Billing page and pulls**

3. [customer] AF10 — "which ones did not get pulled": meters, or periods within a meter? Is `Devices with Issues` the answer already?
4. [customer] AF11/AF12 — retry every 15 minutes "until it succeeds": success criterion and stop condition?
5. [internal] Is the requested retry different from the shipped **Billing Change Check** (ADR 0018), which already runs on the 15-minute Load Profile cycle?
6. [internal] How does a retry loop reconcile with ADR 0006 (a background tick that cannot take the Transport Endpoint lock is skipped, never queued)?
7. [customer] AF17/AF18 — "Bill total": a new page, a counter, or a change to the existing Billing tab?
8. [customer] F60 — which product is "the old style", and what specifically about it?
9. [customer] F60 — is per-device sequential capture the desired behaviour or an observation?
10. [internal] v2 captures per closed period, eagerly. Does the ask change the **trigger** to a sweep over all devices?

**Capture**

11. [customer] AF14 — "capture time": a displayed column, or a popup?
12. [customer] AF15 — which capture layout is "the version we agreed on most recently"?
13. [internal] AF15 asks for back-end capture without an open page; v2 already does this (ADR 0017). Is there a v2 case where a browser must be open?
14. [customer] AF20 — what is the rule that decides which row is highlighted?
15. [customer] AF24/AF26/AT53 — the compare: which two artefacts, and who supplies the bill's numbers?
16. [internal] Image 2 is a siren icon above the failed-pull note. Decoration, or an alert requirement?
17. [internal] Image 3 (Battery Status) has no note. Why is it in this sheet?

**Export file format**

18. [internal] Is the auto/manual difference in the file (20 vs 24 columns) about **auto vs manual**, about the **meter**, or about a **setting**?
19. [customer] "choosing the one that has export as well" — is `export` an operator checkbox?
20. [customer] Why are the four Export columns empty in the sample?
21. [internal] Three whitespace spellings of the same four headers exist across the two files. Which is the contract?
22. [internal] Three tariffs (customer) vs four (`rate_a`…`rate_d`, v2). Which wins in the file?
23. [customer] What is the `Setting :` header field, whose value is `1`?
24. [internal] What is `Record Status`, given it is `..........` in every sample row of every file?
25. [customer] Sheet 03 row 1 — Open Period, commissioning row, or defect?
26. [internal] Headers are truncated at 30 characters by the producing program. Is that truncation part of the contract or an artefact to fix?
27. [customer] There is no `Customer` or `Site Name` concept in v2, yet every sample file has both in its header block. Where do these values come from?

**Energy Summary**

28. [customer] Z20 — save to a downloaded file, or to an auto-export folder?
29. [customer] Z20 — "store" means persist in the database (which ADR 0012 forbids) or write a file?
30. [customer] Z21 — which program's form format?
31. [internal] Should the Energy save reuse the sample files' header-block layout?

## Not covered

- **Sheet 03 and sheet 04 carry no screenshot at all** — they are file samples only, so nothing shows *where* in the product these files come from or which control produces them.
- **No screenshot of v1's `Energy` page exists**, although Z21 asks for the form format to follow "the program".
- **`01-billing-อันเก่า-3.png` (v1's Battery Status page) carries no note** and battery is mentioned nowhere in this workbook.
- **`01-billing-อันเก่า-2.png` (the siren icon) carries no note.**
- **v2's `Current` tab is never shown** — every v2 screenshot in this workbook has `History` selected.
- **No screenshot shows the Export Format page or Settings**, although the Export-column question and the Energy save-button question both land near them.

---

## Answers — 2026-09-08 (owner)

Answers given by the owner in session, plus a code check the owner approved.

### Answered

- **B2 / AF11–AF12 — the retry, explained.** The scenario is: the meter cuts its
  bill at 00:00, we read at 00:00, the connection is poor at that moment, the
  read fails — and **the previous version then waited until the next day** to try
  again automatically. The customer wants the frequency raised to 15 minutes.
  The owner's reading: this is already built.
  **Code check confirms it is.** See below.
- **C4 / AF24–AF27 — out of scope as a feature.** The reference product is
  **v1 at `C:\Users\HP\Documents\Work\cewe`**. The PEA
  *สรุปค่าจัดการพลังงาน* document in `01-billing-อันเก่า-4.jpg` is the customer
  showing **what they use the output for**, not a form we build or read.
  *(The owner corrected an earlier answer that named "sino" as the reference.)*
- **B4 / F60 — "the old style" is v1**, `C:\Users\HP\Documents\Work\cewe`.
- **D1 / Z20 — a FILE.** "เก็บเหมือน load profile ละ billing" means the Energy
  Summary must be **savable to a file the way Billing and Load Profile are**.
  **ADR 0012 is not reversed** — nothing is persisted. The remaining question is
  which of the two shapes it copies (see "Still open").
- **A2 — the line-to-line voltages are read from the meter**, not computed.
  Recorded in the sibling brief; repeated here because it changes the size of
  this workbook's export work too.

### Code check (approved by the owner, run 2026-09-08)

**B2 — already shipped, exactly as described.**

| | |
|---|---|
| `acquisition/billing.py:293` | `billing_change_check(driver, device_id)` |
| `acquisition/load_profile.py:391` | called each Load Profile tick, background path only |
| `constants.py:78` | `LOAD_PROFILE_INTERVAL_SEC = 900` — **15 minutes** |
| `constants.py:96` | `BILLING_INTERVAL_SEC = 86400` — the daily backstop ADR 0018 keeps deliberately |

This is ADR 0018 / issue #43, and the failure it was built for is the one the
customer described. **What is not yet known is whether the customer's machine is
running a build that contains it** — that is a deployment question, not a
development one, and it is the next thing to check.

**A3 — there is no billing export file, and there never was.**

`export/` contains `csv_export.py` and `format.py`, both Load Profile only;
nothing under `export/` mentions billing. v1 has no billing export file either:
its billing output is the **per-row PDF/xlsx capture**
(`cewe-worker/src/billing/xlsx.py`, `_render_shared.py`), the same shape v2
ships. Grepping v1 for `Record No` and `111 Billing total kWh Total` finds them
**only in OBIS reference CSVs**, never in exporter code.

So the customer's two billing samples — one header block, many periods, a
`Record No` counter — are produced by the **third program in these screenshots**
(the Windows-Forms application in `02-bill-ใหม่-5.png`), not by v1 and not by us.

**This changes A3 from "add four columns" to "build a billing export file that
has never existed in either product."** The four Export columns are then a
detail inside a much larger piece of work, and the auto-vs-manual difference
between the two samples is a property of *that* program, which is why neither
sample matches anything we ship.

### Still open

- **D1 shape**: does the Energy Summary file copy the **Load Profile CSV**
  (appended on a schedule to a folder, ADR 0013's contract) or the **Billing
  capture** (one file per event into `capture_dir`, ADR 0010)? The note says
  "like load profile and billing" — but those two are different mechanisms, so
  the sentence cannot mean both.
- **B1** — whether v2 surfaces which meters failed to pull. Not yet checked.
- Everything in this brief's consolidated list that is not named above.

---

## Answers — round 2, 2026-09-08 (owner)

### Answered

- **A3 / the billing file** — an **appended CSV**, one file per meter that grows,
  the way the Load Profile CSV does. The owner's words were "แทนไฟล์ csv เดิมที่
  billing". **There is no CSV in v2's billing output to replace** — see the
  capture-folder evidence below — so this is read as *the file the customer's own
  billing folder receives today from their other program*. Stated as an
  assumption; correct it if wrong.
- **D1 / Energy Summary** — same shape: an appended file, not one file per event.
- **B3 / "Bill total"** — a **new tab on the Billing page, beside History and
  Current**.
- **B4 / "the old style"** — yes, **one table showing every meter, one row per
  meter**, as v1 does.
- **B5 / capture time** — a **popup that appears when the capture finishes**, not
  a column. See the conflict below.
- **E5 / the seven silent sheets** — nothing to do for now.

### Evidence: a real v2 capture folder

The owner supplied `C:\Users\HP\Documents\test-cewe\Billing`, produced by v2.

```
SS18197374/   5 pdf ·  5 xlsx · 1 png · 0 csv
SS21996979/  12 pdf · 12 xlsx · 0 png · 0 csv
WP079074/     1 pdf ·  0 xlsx · 1 png · 0 csv
```

Filenames are `<bill_date>.<ext>` under `<serial>/`, exactly as ADR 0010/0015
describe. **No CSV anywhere**, confirming the code check: v2's billing output is
per-period documents, not an appended file. An appended CSV in this same tree is
a **new filename shape** next to the existing one — worth naming in the issue so
nobody "fixes" it back to `<bill_date>.csv`.

Two things in that listing are worth one look, recorded as observations rather
than diagnoses:

- **`WP079074` has a `.pdf` and a `.png` but no `.xlsx`**, and `SS21996979` has
  twelve `.xlsx` but no `.png`. Both are plausibly licence-driven —
  `billing_excel_export` and `billing_image_export` are separate keys in
  `SELLABLE_FEATURE_KEYS` — but `SS21996979` and `WP079074` share a folder, so
  they share a machine and a licence, and on `2026-07-31` one got a png and the
  other did not. That asymmetry is not explained by the licence.
- **Two captures carry non-boundary timestamps** — `2026-04-27_133047` and
  `2026-03-06_064918` — sitting between clean month-end cuts. A manual MD reset
  would produce exactly that, and so would the class of defect issue 016 fixed on
  SMART TCC. Worth confirming which.

### Conflict: B5's popup has nowhere to appear

The owner chose "ข้อความเด้งเตือนตอนที่ cap เสร็จ". **ADR 0017 is the obstacle**:
v2's capture runs headless, under a scheduled task, with nobody signed in — which
is what the customer asked for in AF15 and what C1 records as already shipped.
There is no open page to raise a toast on, and a capture fired at 17:00:00 will
usually complete with no operator present.

Two shapes fit without reversing ADR 0017:

1. **A toast when a page happens to be open**, plus a **persistent list of recent
   captures** the operator can look at afterwards. The list is the real feature;
   the toast is a convenience on top.
2. **A capture column on the Billing table** (what B5's other reading asked for)
   — the cheapest, and it survives nobody being at the screen.

Recorded, not decided. **A popup alone would be a feature that fires into an
empty room most nights**, and that is worth saying before it is built.

### Still open

- Which of the two popup shapes above.
- **B1** — whether v2 surfaces which meters failed to pull. Still not checked.
- **C2 / C3** — the per-device capture sweep and the highlight rule. With B4
  answered as "one row per meter", C3's "highlight the latest bill" may now mean
  something different from what the v1 screenshots show.

---

## Answers — round 3, 2026-09-08 (owner)

### B5 — the capture notification, recommendation

The owner asked for a recommendation rather than choosing. **Recommendation:
split it by path, because the two paths have opposite economics.**

| path | who is watching | recommendation |
|---|---|---|
| **Manual read / manual capture** | the operator, right there, waiting | **a toast** — and it is nearly free, because the browser already made the request and is waiting on the response. No new signalling of any kind. This is also what "เด้งขึ้น" actually describes. |
| **Auto capture at the bill cut** | usually nobody — 17:00, unattended | **a capture-time column**, plus a recent-captures list. A toast here fires into an empty room and needs a whole push channel (SSE/WebSocket/polling) to deliver it. |

Build order, cheapest first:

1. **Capture time as a column** on the Billing table — covers both paths, zero
   risk, and it is the other reading of AF14 that was always plausible.
2. **Toast on the manual path** — small once (1) exists; the response already
   comes back to an open page.
3. **A recent-captures list** — the honest answer for the auto path. It is the
   real feature; the toast is a convenience on top.
4. ~~Real-time push for auto captures~~ — **do not build.** It is the expensive
   one and it benefits the one path where nobody is present.

This does not reverse ADR 0017 anywhere: the auto capture still runs headless
under the scheduled task with nobody signed in.

### E4 — the third destination is a push

The owner answered **push**: "API" means ARICHDS sends data outward, not that
anything external reads our tables. **The invariant is untouched** — data still
leaves the box only through a Data-out Destination we drive outbound.

This is SPEC §3.8's central-server push (JSON + JWT + an ACK-driven watermark),
still M8 and unbuilt, on its own queue. **E4 closes as a scoping answer**, and
the work itself is the already-planned M8, not something new.

---

## B1 — checked, 2026-09-08

**v2 already tracks the data. It just never shows it.**

| | |
|---|---|
| `db/models.py:154` | `devices.consecutive_failures`, default 0 |
| `acquisition/status.py:190` | incremented on every failed read |
| `acquisition/status.py:192` | writes `status_detail` from the streak |
| `acquisition/status.py:194` | at `OFFLINE_AFTER_CONSECUTIVE_FAILURES` the device goes offline (ADR 0004) |
| `api/devices.py:383-384` | the API returns `status` and `status_detail` |
| `web/src/pages/Devices.tsx:956` | `status_detail` is shown — but **only in the detail drawer of one selected device** |
| `grep consecutive_failures web/src/` | **no match** — the count itself never reaches the UI |

So AF10 (*"see which ones did not get pulled in the latest bill-pull cycle"*) is a
**display gap, not a data gap**. v1's `Devices with Issues: 2` counter has no
equivalent on any v2 screen; the underlying number has existed since ADR 0004.

That makes it much smaller than it looked — a count and a filtered list over data
already on the row, not new tracking. It belongs in the same Billing grill as
B3/B4, since that is the screen the customer was looking at when they wrote the
note.

### Other answers, round 4

- **B5** — build the recommendation as written: a capture-time column, a toast on
  the manual path only, a recent-captures list for the automatic one, and **no
  real-time push**.
- **E3** — unblocked. The import path (meter Special Days → Holiday rows) is
  cleared to be specified.
- **E2** — the catalog unlock is approved **and needs its own ADR** recording that
  four model keys were added deliberately, with capability flags still coming
  from real meters rather than datasheets (ADR 0011).
