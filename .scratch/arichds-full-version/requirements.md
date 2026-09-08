# Requirements brief: โปรแกรมดึงข้อมูล  ARICHDS Version full..xlsx

**Source:** `source/โปรแกรมดึงข้อมูล  ARICHDS Version full..xlsx` · ingested 2026-09-08 · sha256 `0b2790448908`
**Original path:** C:\Users\HP\Downloads\โปรแกรมดึงข้อมูล  ARICHDS Version full..xlsx

## Summary

A 13-sheet workbook, one sheet per screen of the ARICHDS web UI, titled (literally) "Data-pull program ARICHDS Version full." Each sheet carries a screenshot of the running product — mostly ARICHDS v2 at `localhost:8000`, viewed over AnyDesk, under two different licences ("Licensed to Ryosan" and "Licensed to logger-4"/a smaller badge) whose sidebars show different sets of pages; one sheet also carries a screenshot of a different application labelled "ARICHDS v1.0" at `demo-cewe.chaninkre.com`. Beside a few screenshots are short Thai notes in column P (or L), and two sheets (Load Profile, Billing) hold a key-value block and a sample output table with a "Serial Meter : WP076996" header. The notes address the reader by name ("ซัน") and read as feedback from a customer/partner on the existing product plus a list of meter models to support; seven of the thirteen sheets carry a screenshot and no note at all.

## Terminology

Glossary read: `CONTEXT.md` at the repo root. `CONTEXT-MAP.md` and `docs/agents/domain.md` do not exist.

| Customer's term | Where | Glossary term | Status | Note |
|---|---|---|---|---|
| Log in | sheet 1 name | — | missing | glossary mentions "Login" only inside the Setup entry; screenshot button says "SIGN IN" |
| license / "log license" | sheet 1 P8, sheet 12 P12 | Activation Code, Lease, Limited Mode | match | glossary's word is "license" (Activation Code activates it); "log" vs "lock" is an open question |
| CEWE | sheet 1 P10, sheet 2 P18, sheet 7 L11 | CEWE (brand, in Battery Reading / Billing Reading entries) | match | |
| prometer 100. / Pro100 | sheet 1 P11, sheet 2 P19, F45 | Prometer 100 / `prometer100` (Licensed Model) | match | customer also writes "Pro100"; v1 screenshot shows devices named "Pro100" |
| saral 350 / Saral 350 | sheet 1 P12, sheet 2 P20, F49 | — | missing | no glossary entry; v1 screenshot shows a device named "saral (SS21996979)" without a model number |
| Samart TTC / samart TCC | sheet 1 P13, sheet 2 P21, sheet 7 L11 | SMART TCC | conflict | three spellings in the file (TTC on P13/P21, TCC on L11); glossary writes "SMART TCC" |
| ST- 3CL | sheet 1 P14, sheet 2 P22 | ST-3CL / `st3cl` | match | space after the hyphen in the customer's text |
| ST-3DH, ST-1DH, ST-3TL, ST-33TL | sheet 1 P15–P18, sheet 2 P23–P26 | — | missing | no glossary entry for any of the four |
| Devices | sheet 2 name | — | missing | glossary has Meter Serial, Device Event, Pause but no "Device" entry; both screenshots title the page "Devices" / "Device Management" |
| Load Profile | sheet 3 name, A31 | Load Profile (page), Interval Reading (row) | match | glossary: "load profile row" is *avoided*; the row is an Interval Reading |
| Serial Meter | sheet 3 A29, sheet 5 A29 | Meter Serial | match | word order reversed; screenshots say "Meter Serial" |
| Customer / Site Name / Setting | sheet 3 A27–A30, sheet 5 A27–A30 | — | missing | v2 screenshot has "Customer Name", "Site Name" fields; no glossary entry; "Setting : 1" has no counterpart on screen |
| Name (column) | sheet 3 A33 | — | missing | screenshot form has "Device Name"; sample rows leave the column empty |
| Date/Time | sheet 3 B33 | `read_at` (Interval Reading) | match | |
| Import kWh Active / Reactive, Export kWh Active / Reactive | sheet 3 C33–F33 | Interval Reading ("always kWh"), Export Format ("always kWh/kvarh") | match | customer labels reactive as "kWh"; glossary/screen say kvarh |
| Voltage L1–L3, Current L1–L3, Avg Phase Angle Ph-A/B/C, Frequency, (Average Power Factor Avg | sheet 3 G33–Q33 | — | missing | glossary defines Interval Reading columns only as "COSEM shape"; no named entries |
| Record Status | sheet 3 R33, sheet 5 T33 | — | missing | sample value in Billing is ".........." |
| RECORD | sheet 4 name | Records | match | sheet name is singular upper-case; screenshot page is "Records" |
| Billing | sheet 5 name, A31 | Billing Reading, Bill Date, Open Period | match | |
| Record No | sheet 5 A33 | — | missing | |
| Time (billing) | sheet 5 B33 | Bill Date | match | glossary avoids "read time"; customer's samples are 1st-of-month 00:00 |
| Rate A / Rate B / Rate C | sheet 5 D33–F33 etc. | `rate_a`…`rate_d` (four tariffs) | conflict | customer's table has three rates; glossary and v2 screenshot carry four (Rate D shows "—" on screen) |
| Previous kW demand | sheet 5 G33, I33, K33 | Maximum Demand of one period (`D=6`, in Cumulative Demand entry) | missing | no glossary entry named "Previous demand" |
| Previous Time of kW deman / Var dem | sheet 5 H33, J33, L33, R33 | Demand Time | match | glossary avoids "MD time", "peak time" |
| Cumul kW demand / Cumul Var demand | sheet 5 M33–O33, S33 | Cumulative Demand | match | |
| Billing total kWh / Varh | sheet 5 C33–F33, P33 | Billing Reading (energy columns) | match | |
| Energy Summary | sheet 6 name | Energy Summary | match | |
| Special Day | sheet 7 name | Special Day | conflict | glossary: Special Day is the meter's, "read and displayed, never written"; note L11 says "เพิ่มเอาได้" (can add) — adding is what the glossary's *Holiday* allows |
| Battery | sheet 8 name | Battery Reading | match | |
| Export format | sheet 9 name | Export Format | match | |
| Event log | sheet 10 name | App Log · Device Event | conflict | glossary keeps these two apart ("easy to conflate and must not be"); the screenshot on this sheet is the App Log page |
| User | sheet 11 name | Role (users table) | missing | screenshot page is "User Management" |
| Setting | sheet 12 name | — | missing | screenshot page is "Settings"; glossary mentions "the License card on Settings" but has no entry |
| Data base / DATA Base | sheet 13 name, P15 | Database Destination | match | screenshot page is "Database" under "Data-out Destination" |
| FTP | sheet 13 P16 | Data-out Destination ("an upload target") | match | no specific FTP entry |
| API | sheet 13 P17 | — | missing | glossary's central-server push is a Data-out Destination; nothing is called "API" |
| version ดึงข้อมูลเต็ม / Version full | file name, sheet 1 P22 | — | missing | |

## Sections

### 01. Log in

**Screenshot:** [`01-log-in-1.png`](source/images/01-log-in-1.png), anchored at A1.
**Current state:** Browser tab "ARICHDS", URL `localhost:8000`, inside two nested AnyDesk sessions (`desktop-m97470a@ad` → `ryosan` / 597424769). Full-bleed background image of a circuit board reading "ARICHEST CO.,LTD". Sign-in card: small caps "ARICHEST CO., LTD.", title "ARICHDS", fields "* Username" (filled: `admin`) and "* Password" (masked, show/hide eye icon), button "SIGN IN". No navigation visible (pre-login). Taskbar clock 9:53 PM 9/5/2026.
**Customer notes (verbatim):**
- P8: "1.ไม่ log license" → "1. Don't log license."
- P9: "2.เพิ่มได้ไม่จำกัด มีรุ่นที่ใช้ดึงตามนี้" → "2. Can add without limit; the models used for pulling are as follows."
- P10: "1.CEWE " → "1. CEWE"
- P11: "1.1 prometer 100." → "1.1 prometer 100."
- P12: "1.2 saral 350 " → "1.2 saral 350"
- P13: "2.Samart TTC " → "2. Samart TTC"
- P14: "2.1.ST- 3CL ดึงได้แล้ว" → "2.1. ST- 3CL can already be pulled."
- P15: "2.2 ST-3DH " → "2.2 ST-3DH"
- P16: "2.3 ST-1DH" → "2.3 ST-1DH"
- P17: "2.4 ST-3TL" → "2.4 ST-3TL"
- P18: "2.5 ST-33TL" → "2.5 ST-33TL"
- P22: "*** เป็น version ดึงข้อมูลเต็ม" → "*** It is the full data-pull version."
**Open questions:**
- [customer] P8 "ไม่ log license": is "log" the English word *log* (do not record/log the license) or *lock* (do not lock on license — i.e. no licence gate)? The screenshot is the sign-in page, which has no licence element.
- [customer] P9 "เพิ่มได้ไม่จำกัด": add *what* without limit — meters (the v2 Devices screen shows "12 meters · unlimited"), users, or something else?
- [customer] P9–P18: is this the complete list of models the "full version" must pull, or examples? Are the four models P15–P18 (ST-3DH, ST-1DH, ST-3TL, ST-33TL) new to the product?
- [customer] P14 "ดึงได้แล้ว" is written only against ST- 3CL. Does it mean the other listed models are *not* yet pullable, or is it an aside?
- [customer] P22: what distinguishes the "full data-pull version" from the version in the screenshots? Is this the same as the licence whose sidebar shows Records / Energy Summary / Holidays / Special Days / Battery / File Upload (sheets 4, 6, 7, 8, 13) versus the one that does not (sheets 2, 3, 5, 9–12)?
- [internal] The same two lines (P8, P9) reappear on sheet 12 Setting (P12, P13) and P9–P18 reappear on sheet 2 Devices (P17–P26). Do they mean the same thing on each sheet, or is the placement pointing at a different screen element each time?

### 02. Devices

**Screenshot 1:** [`02-devices-1.png`](source/images/02-devices-1.png), anchored at A7.
**Current state (screenshot 1):** ARICHDS v2 at `localhost:8000`, header badge "Licensed to Ryosan", "admin", "Change password", "Sign out". Sidebar: **Devices** (selected), Load Profile, Billing, Export Format, App Log, User Management, Settings; group "Data-out Destination": Database. Page title "Devices"; subtitle "Every meter on this machine. Status comes from the 60-second poll — nothing here asks a meter anything until you press a button."; top-right "12 meters · unlimited". Left list "12 meters": search box "Search name or Meter Serial", dropdowns "All statuses", "All models", collapsible group "advance grid (12)" listing (green status dots) Phase 2 -2 / SS18197381, Phase 2-1 / SS18197374, Phase 2-10 / SS18197373, Phase 2-11 / SS18197384, Phase 2-12 / SS18197385, Phase 2-3 / SS18197372, Phase 2-4 / SS18197375, Phase 2-5 / SS18197376, Phase 2-6 / SS18197377 (list continues below the fold). Right panel "New device" → section "Identity": "* Device Name" (placeholder "Main incomer"); "Meter Serial" shown as "—" with help "Assigned automatically by the system — it is read from the meter when you press Create Device."; "* Meter Activation Code" textarea (placeholder "Paste the code the vendor issued", help "Test connection to read the Meter Serial, ask the vendor for a code, then paste it here before Create Device."); "Site Code" (Optional); "* Site Name" (placeholder "Plant A"); "Customer Name" (Optional); "Meter Number" (Optional); "Group" (Optional). Section "Meter": dropdowns "* Brand", "* Model". Taskbar 9:54 PM 9/5/2026.

**Screenshot 2:** [`02-devices-2.png`](source/images/02-devices-2.png), anchored at A31.
**Current state (screenshot 2):** A different application. Chrome tabs "Dashboard | DOC-PEA", **"cewe-fe"** (active), "Meter"; URL `demo-cewe.chaninkre.com/#/app`. Menu bar "File · Setting · Help", right edge "ARICHDS v1.0". Top icon navigation: **Devices** (selected), Load Profile, Records, Energy, Billing, Battery, DB Settings, API Config, Users, App Log; right side "06/09/2026, 20:45:21" and "Admin". Page title "Device Management". Left panel "Devices (24)" with refresh icon, search "Search devices...", dropdown "All Types"; tree of devices "phase 2 (SS18197381) - 49.229.159..." etc. (about 14 "phase 2"/"Phase 2" rows, mixed green/blue/red dots), then groups: "test_premier (1)" → "Premier550 (SS17444640) - 49.229..."; "test_pro100 (3)" → "OTC1 (WP080653) - 147.50.94.190:4...", "OTC2 (WP080652) - 147.50.94.190:4...", "Pro100 (WP063531) - 49.229.156.14..."; "test_saral (1)" → "saral (SS21996979) - 203.170.151..."; "test_saran (1)" → "saran (SS21996908) - 110.49.150.6..." (highlighted/selected); "test_site_name (2)" → "Prometer100_4059 (WP079074) - 203...", "Prometer100_4060 (WP079073) - 203..."; "ttc (1)" → "cl3 - 203.170.148.103:4059" (red dot); "Welltek (1)" → "Pro100 - 10.76.173.146:4059". Footer "Ready — 16 devices configured". Edit form for the selected device: "Meter Serial:" (placeholder "Assigned automatically by the system"), "Site Code:" `test`, "* Site Name:" `test_saran`, "Customer Name:" `test`, "Meter Number:" `test`. Section "CONNECTION INFORMATION": "* IP Address:" `110.49.150.64`, "* Port:" `4059`, "Password:" (masked) with help "Pre-filled with the shared meter password; clear to keep the current password unchanged." Section "BILLING INFORMATION": "Bill Start Date:" (Select date), "Bill Day - Feb (28 days):" (Day of month), "Bill Day - Feb (29 days):" (Day of month), "Bill Day - 30-day months:" (Day of month). Taskbar 8:57 PM 9/6/2026.

**Customer notes (verbatim):**
- P17: "2.เพิ่มได้ไม่จำกัด มีรุ่นที่ใช้ดึงตามนี้" → "2. Can add without limit; the models used for pulling are as follows."
- P18: "1.CEWE " → "1. CEWE"
- P19: "1.1 prometer 100." → "1.1 prometer 100."
- P20: "1.2 saral 350 " → "1.2 saral 350"
- P21: "2.Samart TTC " → "2. Samart TTC"
- P22: "2.1.ST- 3CL ดึงได้แล้ว" → "2.1. ST- 3CL can already be pulled."
- P23: "2.2 ST-3DH " → "2.2 ST-3DH"
- P24: "2.3 ST-1DH" → "2.3 ST-1DH"
- P25: "2.4 ST-3TL" → "2.4 ST-3TL"
- P26: "2.5 ST-33TL" → "2.5 ST-33TL"
- F45: "Pro100" → "Pro100"
- F49: "Saral 350" → "Saral 350"

P17–P26 sit beside screenshot 1 (rows 7–30). F45 and F49 sit in rows 45 and 49, beside screenshot 2 (anchored at A31), whose device tree contains rows named "Pro100 (WP063531)" and "saral (SS21996979)".

**Open questions:**
- [customer] Why is a v1 screenshot ("ARICHDS v1.0", `demo-cewe.chaninkre.com`) on this sheet next to the v2 one? Is the v1 device form (IP Address / Port / Password, Bill Start Date, the three Bill Day fields) being requested for v2, or is it context?
- [customer] F45 "Pro100" and F49 "Saral 350": are these labels for something in screenshot 2 (which rows?), a list of models present at the site, or a continuation of the model list above?
- [customer] The customer writes "saral 350" / "Saral 350". Is that the exact model name to support? No glossary or screenshot text carries a model number for saral.
- [customer] Is there a "Samart TTC" as distinct from "samart TCC" (sheet 7), or is one a typo?
- [internal] Screenshot 1's list shows 12 meters all "Phase 2-x" under "advance grid"; screenshot 2 shows 24 devices across several groups. Are these the same site?

### 03. Load Profile

**Screenshot:** [`03-load-profile-1.png`](source/images/03-load-profile-1.png), anchored at A1.
**Current state:** ARICHDS v2, "Licensed to Ryosan". Sidebar: Devices, **Load Profile** (selected), Billing, Export Format, App Log, User Management, Settings; Data-out Destination: Database. Card "CSV export": "Auto-save" toggle (off); "Output folder" input (placeholder "e.g. C:\LoadProfileExports", help "Where the per-meter CSV files are written. Required while Auto-save is on — turn Auto-save off first if you want to clear it."); button "Save"; button "Save CSV now" (disabled). Filter row: dropdowns "All site groups", "All brands", "All models", "Select a device"; date range "2026-09-05 → 2026-09-05"; button "Read now" (disabled). Empty-state illustration with text "Select a device to view its Interval Readings". The word "ADMIN" appears in the AnyDesk toolbar area (remote-desktop chrome, not the product). Taskbar 9:56 PM 9/5/2026.
**Customer notes (verbatim):**
- P11: "ดึงแบบนี้ได้เลย" → "Pull it like this, that works."
- I25: "ตัวอย่าง" → "Example."
- A27: "Customer :" / B27: "LPH" → "Customer : LPH"
- A28: "Site Name :" / B28: "LPH Days1" → "Site Name : LPH Days1"
- A29: "Serial Meter :" / B29: "WP076996" → "Serial Meter : WP076996"
- A30: "Setting :" (B30 holds the number `1`) → "Setting : 1"
- A31: "Load Profile :" (no value beside it) → "Load Profile :"
**Example data:** [`load-profile-sample.csv`](source/fixtures/load-profile-sample.csv), from A33:R36 — 18 columns, header row plus 3 rows. Only the Date/Time column is filled (2025-04-01 00:00, 00:15, 00:30 — 15-minute steps); every other cell in the three rows, including "Name", is empty. The Date/Time cells are Excel **datetime** cells (exported as ISO 8601), not typed strings, so the file does not show how the customer wants the timestamp printed. Header cells, verbatim:
- A33: "Name"
- B33: "Date/Time"
- C33: "Import kWh Active"
- D33: "Import kWh Reactive"
- E33: "Export kWh Active"
- F33: "Export kWh Reactive"
- G33: "(Average Power Factor Avg" (unbalanced opening parenthesis as typed)
- H33: "Voltage L1 (V)"
- I33: "Voltage L2 (V)"
- J33: "Voltage L3 (V)"
- K33: "Current L1 (A)"
- L33: "Current L2(B)" (no space; "(B)" where the neighbours say "(A)" and "(C)")
- M33: "Current L3 (C)"
- N33: "Avg Phase Angle Ph-A"
- O33: "Avg Phase Angle Ph-B"
- P33: "Avg Phase Angle Ph-C"
- Q33: "Frequency (Hz)"
- R33: "Record Status"
**Open questions:**
- [customer] "Like this" (P11) — like the example table at A33:R36, like the current screen, or both? The screen shows no data (no device selected).
- [customer] Is the A27:A31 header block (Customer / Site Name / Serial Meter / Setting / Load Profile) meant to be part of the exported file, above the table?
- [customer] What is "Setting : 1"?
- [customer] "Name" column — device name, site name, or something else? The sample leaves it empty.
- [customer] Are "Import kWh Reactive" / "Export kWh Reactive" intended to be kvarh (the screen's Export Format page says the CSV is kWh/kvarh), or is "kWh" the required header text?
- [customer] What is "Record Status" and what values does it take?
- [customer] What timestamp format is required in the file? The cells are datetimes, so the workbook only shows Excel's rendering.
- [customer] Serial WP076996 with Customer "LPH" — is this a specific meter/site the export must be validated against?
- [internal] Does the current Load Profile CSV produce these 18 columns in this order? (Voltage, Current, Phase Angle, Frequency, Power Factor columns are not on the v2 screen.)

### 04. RECORD

**Screenshot:** [`04-record-1.png`](source/images/04-record-1.png), anchored at A1.
**Current state:** ARICHDS v2 under a different AnyDesk session ("ArichDS logger 1…", 388888656); the licence badge is too small to read. A second browser tab reads "localhost:9000 / localhost / arichd…". Sidebar: Devices, Load Profile, **Records** (selected), Billing, Energy Summary, Holidays, Special Days, Battery, Export Format, App Log, User Management, Settings; Data-out Destination: Database, File Upload. Filter row: "All site groups", date range "2026-08-31 → 2026-09-06". Table columns: Meter, Logger, 08-31, 09-01, 09-02, 09-03, 09-04, 09-05, 09-06. Rows: "serail" | 1 | 96 | 96 | 96 | 96 | 96 | 96 | "83 (-13)" (orange); "test_ip" | 1 | 96 | 96 | 96 | 96 | 96 | 96 | "83 (-13)" (orange). Taskbar 8:53 PM 9/6/2026.
**Customer notes (verbatim):** none.
**Open questions:**
- [customer] The sheet is named "RECORD" and shows the Records page with no note. What is being asked of it?

### 05. Billing

**Screenshot:** [`05-billing-1.png`](source/images/05-billing-1.png), anchored at A1.
**Current state:** ARICHDS v2, "Licensed to Ryosan". Sidebar: Devices, Load Profile, **Billing** (selected), Export Format, App Log, User Management, Settings; Data-out Destination: Database. Card "Capture folder": "Folder path" input (placeholder "e.g. C:\Captures", help "Where billing PDF/xlsx captures are written. Leave empty to disable capture."), button "Save". Tabs "History" (selected), "Current". Filter row: "All devices", "Bill date from → Bill date to", buttons "Capture image", "Read now" (disabled). Table with group header "Import Active (kWh)"; columns: Bill Date, Device, Meter Serial, Total, Rate A, Rate B, Rate C, Rate D, "Tota…" (cut off at the right edge). Rows (all Bill Date 2026-08-26 00:00): Phase 2-1 / SS18197374 / 40902.032 / 25695.448 / 2746.661 / 12459.923 / — / 7.20…; Phase 2 -2 / SS18197381 / 43138.064 / 24924.534 / 3277.554 / 14935.976 / — / 4.26…; Phase 2-3 / SS18197372 / 107849.615 / 63719.764 / 8285.896 / 35843.955 / — / 22.2…; Phase 2-4 / SS18197375 / 37042.431 / 22834.097 / 1828.440 / 12379.895 / — / 479…; Phase 2-5 / SS18197376 / 44701.968 / 26373.696 / 3640.056 / 14688.215 / — / 18.9…; Phase 2-7 / SS18197379 / 25447.751 / 14822.359 / 2126.611 / 8498.781 / — / 23.2…; Phase 2-6 / SS18197377 / 44911.887 / 27236.187 / 3972.612 / 137…. Rate D is "—" on every row. Taskbar 9:57 PM 9/5/2026.
**Customer notes (verbatim):**
- P13: "ใช้แบบนี้ได้เลย" → "Use it like this, that works."
- P14: "แต่ไฟล์ออกมาให้เหมือนที่ส่งออกแบบใหม่นะ  แต่ไม่มี export" → "But have the file come out the same as the one exported the new way. But there is no export."
- I26: "ตัวอย่าง" → "Example."
- A27: "Customer :" / B27: "LPH" → "Customer : LPH"
- A28: "Site Name :" / B28: "LPH Days1" → "Site Name : LPH Days1"
- A29: "Serial Meter :" / B29: "WP076996" → "Serial Meter : WP076996"
- A30: "Setting :" (B30 holds the number `1`) → "Setting : 1"
- A31: "Billing :" (no value beside it) → "Billing :"
**Example data:** [`billing-sample.csv`](source/fixtures/billing-sample.csv), from A33:T37 — 20 columns, header row plus 4 data rows (Record No 1–4). Every timestamp in this table is a **typed string**, not a datetime cell: the "Time" column reads `5/1/2025 00:00`, `6/1/2025 00:00`, `7/1/2025 00:00`, `8/1/2025 00:00` and the four "Previous Time of…" columns use the same `M/D/YYYY HH:MM` shape. That string may itself be the required output format. Numeric cells have four decimals. "Record Status" is `..........` on every row. Header cells, verbatim:
- A33: "Record No"
- B33: "Time"
- C33: "111 Billing total kWh Total"
- D33: "010 Billing total kWh Rate A"
- E33: "020 Billing total kWh Rate B"
- F33: "030 Billing total kWh Rate C"
- G33: "050 Previous kW demand Rate A"
- H33: "050T Previous Time of kW deman" (truncated as typed)
- I33: "060 Previous kW demand Rate B"
- J33: "060T Previous Time of kW deman"
- K33: "070 Previous kW demand Rate C"
- L33: "070T Previous Time of kW deman"
- M33: "015 Cumul kW demand Rate A"
- N33: "016 Cumul kW demand Rate B"
- O33: "017 Cumul kW demand Rate C"
- P33: "222 Billing total Varh Total"
- Q33: "280 Previous Var demand Total"
- R33: "280T Previous Time of Var dem" (truncated as typed)
- S33: "118 Cumul Var demand Total"
- T33: "Record Status"
Text cells in the data rows (the numeric cells are in the fixture):
- B34: "5/1/2025 00:00" · H34: "4/13/2025 12:45" · J34: "4/2/2025 19:00" · L34: "4/2/2025 19:00" · R34: "4/4/2025 06:30" · T34: ".........."
- B35: "6/1/2025 00:00" · H35: "5/18/2025 11:45" · J35: "5/9/2025 19:15" · L35: "5/9/2025 19:15" · R35: "5/20/2025 06:15" · T35: ".........."
- B36: "7/1/2025 00:00" · H36: "6/3/2025 12:15" · J36: "6/28/2025 19:30" · L36: "6/19/2025 19:30" · R36: "6/27/2025 06:15" · T36: ".........."
- B37: "8/1/2025 00:00" · H37: "7/12/2025 13:00" · J37: "7/27/2025 19:15" · L37: "7/22/2025 19:15" · R37: "7/1/2025 06:30" · T37: ".........."
**Open questions:**
- [customer] P13 "Use it like this": the current Billing screen, the example table, or both?
- [customer] P14 "the one exported the new way" — which export is "the new way"? The Load Profile CSV export, the Billing capture (PDF/xlsx/png), or something else?
- [customer] P14 "แต่ไม่มี export" — "but there is no export": is this reporting that the Billing page currently has no export button (the screen shows "Capture image" and "Read now" only), or asking that the file be produced *without* an export step (e.g. auto-saved)?
- [customer] The example has three rates (Rate A/B/C); the v2 screen shows Rate D as well (all "—"). Is a three-rate file required, or are four acceptable?
- [customer] The numeric prefixes (111, 010, 020, 030, 050, 050T, 060, 070, 015, 016, 017, 222, 280, 280T, 118) — are they required in the header text as typed?
- [customer] Is `M/D/YYYY HH:MM` (e.g. `5/1/2025 00:00`) the required timestamp format for Time and the demand-time columns?
- [customer] What is "Record Status" and what should replace `..........`?
- [customer] "Time" values are all the 1st of the month at 00:00 — is the file expected to contain one row per closed billing period?
- [customer] Same A27:A31 header block as Load Profile: part of the file?
- [internal] Do the "Previous kW demand" / "Previous Time of kW demand" / "Cumul kW demand" columns map to what v2 already stores (Demand Time, Cumulative Demand)?

### 06. Energy Summary

**Screenshot:** [`06-energy-summary-1.png`](source/images/06-energy-summary-1.png), anchored at A1.
**Current state:** ARICHDS v2 under a third AnyDesk session ("LOGGER WC", 1062896882), badge "Licensed to logger-4". A second browser tab "Device". Sidebar: Devices, Load Profile, Records, Billing, **Energy Summary** (selected), Holidays, Special Days, Battery, Export Format, App Log, User Management, Settings; Data-out Destination: Database. Tabs "Summary Report" (selected), "Meter Registers". Device dropdown "3CL (002607000049)"; segmented "Single day" / "Range" (Range selected); date range "2026-08-30 → 2026-09-05". Table columns: Date, Peak Import (kWh), Off-Peak Import (kWh), Holiday Import (kWh), Total Import (kWh), Peak Export (kWh) — a horizontal scrollbar indicates more columns to the right. Rows: 2026-08-30 / 0.00 / 0.00 / 69.99 / 69.99 / 0.00; 2026-08-31 / 253.09 / 22.08 / 0.00 / 275.18 / 0.02; 2026-09-01 / 295.92 / 14.35 / 0.00 / 310.27 / 0.02; 2026-09-02 / 391.26 / 27.17 / 0.00 / 418.43 / 0.01; 2026-09-03 / 426.96 / 43.72 / 0.00 / 470.68 / 0.01; 2026-09-04 / 453.13 / 53.37 / 0.00 / 506.49 / 0.02; 2026-09-05 / 0.00 / 0.00 / 115.71 / 115.71 / 0.00; **Total** / 1820.36 / 160.68 / 185.70 / 2166.75 / 0.08. Taskbar 10:02 PM 9/5/2026.
**Customer notes (verbatim):** none.
**Open questions:**
- [customer] The sheet shows the Energy Summary for an ST-3CL with no note. What is being asked of it?

### 07. Special Day

**Screenshot:** [`07-special-day-1.png`](source/images/07-special-day-1.png), anchored at A1.
**Current state:** ARICHDS v2, "ArichDS logger 1…" session (388888656); badge too small to read. Sidebar: Devices, Load Profile, Records, Billing, Energy Summary, Holidays, **Special Days** (selected), Battery, Export Format, App Log, User Management, Settings; Data-out Destination: Database, File Upload. Dropdown "Select a device" (empty). Info banner: "This is what the meter itself holds right now — it is not stored anywhere." Table columns: Index, Day, Day ID. Empty state "Select a device". Taskbar 8:54 PM 9/6/2026.
**Customer notes (verbatim):**
- L11: "ถ้าของ samart TCC ดึงมาได้ก็ดึงมาด้วยนะซัน ส่วนของยี่ห้อ CEWE อิงตามได้ แต่ถ้าไม่มีเพิ่มเอาได้" → "If Samart TCC's can be pulled, pull it too, Sun. As for the CEWE brand, it can be based on [that], but if there isn't any, adding is fine."
**Open questions:**
- [customer] "ดึงมาด้วย" (pull it too): pull Samart TCC's Special Days table in addition to which brand's — is CEWE's already being pulled in the customer's view, or the other way round?
- [customer] "อิงตามได้" (can be based on it) — based on what: the meter's own table, the Samart TCC table, or the Holidays page?
- [customer] "ถ้าไม่มีเพิ่มเอาได้" (if there isn't any, adding is fine): add entries *to the meter*, or add them on our side (the Holidays page)? The screen says Special Days are read from the meter and not stored.
- [customer] Who is "ซัน" (Sun) — the developer the note is addressed to?
- [internal] The glossary says Special Days are read-only and never written to a meter; the note's "adding" would need to be routed somewhere.

### 08. Battery

**Screenshot:** [`08-battery-1.png`](source/images/08-battery-1.png), anchored at A2.
**Current state:** ARICHDS v2, "ArichDS logger 1…" session (388888656). Sidebar as sheet 07 with **Battery** selected. Filter row: "All devices", "Read at from → Read at to". Table columns: Device, Meter Serial, Read at, Status. Empty state "No battery readings stored yet". A stray "Search" tooltip from the taskbar sits over the page's bottom-left (OS chrome). Taskbar 8:56 PM 9/6/2026.
**Customer notes (verbatim):** none.
**Open questions:**
- [customer] The Battery page is shown empty with no note. What is being asked of it?

### 09. Export format

**Screenshot:** [`09-export-format-1.png`](source/images/09-export-format-1.png), anchored at A1.
**Current state:** ARICHDS v2, "Licensed to Ryosan". Sidebar: Devices, Load Profile, Billing, **Export Format** (selected), App Log, User Management, Settings; Data-out Destination: Database. Card "Export Format" with text: "The Load Profile CSV is always exported in kWh/kvarh — it does not follow the Display unit setting on the Settings page. The header is written once when a meter's file is created, and rows append to it for months, so its unit can never change." Field "* Date/time format" = `yyyy-mm-dd HH:MM:SS`, help "Tokens: yyyy, mm (month), dd, HH (hour), MM (minute), SS." Field "* CSV filename template" = `{meter}.csv`, help "Tokens: {meter} / {serial} (the meter's serial number), {date} (today's date)." Button "Save". A browser tab-hover tooltip ("ARICHDS · localhost:8000") overlaps the top-left. Taskbar 10:03 PM 9/5/2026.
**Customer notes (verbatim):** none.
**Open questions:**
- [customer] Shown with no note. Is the current Date/time format / filename template acceptable, or is this the screen the Load Profile and Billing example tables are meant to change?

### 10. Event log

**Screenshot:** [`10-event-log-1.png`](source/images/10-event-log-1.png), anchored at A1.
**Current state:** ARICHDS v2, "Licensed to Ryosan". Sidebar: Devices, Load Profile, Billing, Export Format, **App Log** (selected), User Management, Settings; Data-out Destination: Database. Filter row: "All levels", "500 lines", button "Refresh". Table columns: Time, Level, Logger, Message. Visible rows (2026-09-05T21:33:00+0700 … 21:33:58+0700): INFO `arichds.acquisition.poller` "Tick OK for Phase 2 -2 (49.229.159.42:50001)"; WARNING `arichds.acquisition.drivers_dlms` "premier550 association to 49.229.159.44:50001 aborted (ConnectionAbortedError) — retrying (attempt 1/3)"; WARNING `arichds.acquisition.drivers_gurux_net_patch` "GXNet listener socket error, stopping listener thread: [WinError 10053] An established connection was aborted by the software in your host machine"; INFO `arichds.acquisition.drivers_dlms` "Connected to premier550 110.49.210.46:50001" and "Connected to premier550 49.229.152.6:50001"; INFO poller "Tick OK for Phase 2-4 (110.49.210.46:50001)", "Tick OK for Phase 2-11 (49.229.152.6:50001)"; INFO "Connected to premier550 203.170.149.224:50001"; INFO poller "Skipping tick for Phase 2-5 — a Manual Read holds 110.49.210.109:50001"; INFO "Tick OK for Phase 2-10 (203.170.149.224:50001)"; further WARNING/INFO rows of the same kinds. Taskbar 10:03 PM 9/5/2026.
**Customer notes (verbatim):** none.
**Open questions:**
- [customer] The sheet is named "Event log" but shows the App Log page (process log lines). Is "Event log" the customer's name for App Log, or is a separate event log (device status changes, operator actions) being asked for?

### 11. User

**Screenshot:** [`11-user-1.png`](source/images/11-user-1.png), anchored at A7.
**Current state:** ARICHDS v2, "Licensed to Ryosan". Sidebar: Devices, Load Profile, Billing, Export Format, App Log, **User Management** (selected), Settings; Data-out Destination: Database. Page title "User Management"; subtitle "Accounts on this machine. Resetting a password signs that user out everywhere." Card "Add a user": fields "* Username", "* Password" (eye icon), "* Role" (Select); button "Add user". Table columns: Username, Role, Created, Actions. One row: `admin` (tag "you") | Role dropdown `admin` (disabled) + badge "admin" | 2026-08-27 11:24 | "Reset password" (disabled), delete icon. Taskbar 10:04 PM 9/5/2026.
**Customer notes (verbatim):** none.
**Open questions:**
- [customer] Shown with no note. What is being asked of it?

### 12. Setting

**Screenshot:** [`12-setting-1.png`](source/images/12-setting-1.png), anchored at A1.
**Current state:** ARICHDS v2, "Licensed to Ryosan". Sidebar: Devices, Load Profile, Billing, Export Format, App Log, User Management, **Settings** (selected); Data-out Destination: Database. Card "Display unit": "Applies machine-wide, to the Billing and Load Profile pages and the capture PDF/xlsx files."; segmented "Kilo (kW, kWh)" (selected) / "Base (W, Wh)". Card "License": "Licensed to: Ryosan", "Mode: Offline", "Expiry: No expiry", "Max meters: Unlimited", "Licensed models: premier550", "Enabled features: App Log · Billing · Database Destination · Load Profile". "Machine ID" = `f46b67634473a36386d918d05aebc3f872e3b19c73ab2c2c5e0def71fa9b57e0` with "Copy" button; help "This identifies this computer. Every license is bound to it — send it to your vendor to get a new code." "New Activation Code" textarea (placeholder "Paste the single-line Activation Code here"); button "Replace license". Taskbar 10:04 PM 9/5/2026.
**Customer notes (verbatim):**
- P12: "1.ไม่ log license" → "1. Don't log license."
- P13: "2.เพิ่มได้ไม่จำกัด มีรุ่นที่ใช้ดึงตามนี้" → "2. Can add without limit; the models used for pulling are as follows."
**Open questions:**
- [customer] P12 beside the License card: does "ไม่ log license" mean the License card / Activation Code gate should not exist in the full version, that licence activity should not be logged, or something else?
- [customer] P13 beside "Max meters: Unlimited" and "Licensed models: premier550": is "add without limit" about Max meters (already "Unlimited" here) or about Licensed models (currently one model, premier550, versus the eight-model list on sheet 1)?
- [customer] P13 ends "the models used for pulling are as follows" but no list follows on this sheet. Is the sheet-1 list (P10–P18) the referent?

### 13. Data base

**Screenshot:** [`13-data-base-1.png`](source/images/13-data-base-1.png), anchored at A10.
**Current state:** ARICHDS v2, "ArichDS logger 1…" session (388888656); badge too small to read. Sidebar: Devices, Load Profile, Records, Billing, Energy Summary, Holidays, Special Days, Battery, Export Format, App Log, User Management, Settings; Data-out Destination: **Database** (selected, cursor over it), File Upload. Info banner: "ARICHDS writes to this database" / "ARICHDS pushes finished data to this database. It does not run on it — ARICHDS always keeps its own local store and keeps reading meters whether or not this destination is reachable." Card "Database Destination": "ARICHDS creates and owns two tables here — Load Profile and Billing — and is their only writer. Ask for a database dedicated to ARICHDS rather than one holding the customer's own tables; the account needs SELECT, INSERT, DELETE, CREATE and ALTER on it." Fields: "* Host" = `localhost`, "* Port" = `3307`, "* Database" = `arichds_data`, "User" = `root`, "Password" (placeholder "Unchanged", eye icon) with help "A password is saved. Leave this box alone to keep it, or clear it and save to store an empty password." Buttons "Save", "Test saved connection". Card "Last sync" with "Refresh": "Ran at" = `9/6/2026, 8:42:07 PM`, "Load Profile rows sent" = `10` (rest cut off). Taskbar 8:56 PM 9/6/2026.
**Customer notes (verbatim):**
- P15: "DATA Base" → "DATA Base"
- P16: "FTP" → "FTP"
- P17: "API" → "API"
**Open questions:**
- [customer] Are "DATA Base / FTP / API" three data-out destinations the full version must offer? The screen shows "Database" and "File Upload" in the sidebar; nothing is called FTP or API.
- [customer] "API" — an API that ARICHDS *pushes to*, or an API that ARICHDS *exposes* for others to pull from?
- [customer] "FTP" — is the existing "File Upload" item what is meant, or a separate FTP transfer?
- [customer] The v1 screenshot on sheet 2 has "DB Settings" and "API Config" navigation items. Is the v1 behaviour behind those the reference?

## Open questions (consolidated)

Sheet 01 — Log in
- [customer] P8 "ไม่ log license": *log* (do not record the license) or *lock* (no licence gate)?
- [customer] P9 "เพิ่มได้ไม่จำกัด": add what without limit — meters, users, or something else?
- [customer] P9–P18: complete list of models for the full version, or examples? Are ST-3DH, ST-1DH, ST-3TL, ST-33TL new?
- [customer] P14 "ดึงได้แล้ว" only on ST- 3CL: are the others not yet pullable?
- [customer] P22: what is the "full data-pull version" versus the screenshots' version? Is it the licence with the longer sidebar (Records, Energy Summary, Holidays, Special Days, Battery, File Upload)?
- [internal] P8/P9 recur on sheet 12 (P12/P13) and P9–P18 on sheet 2 (P17–P26): same meaning each time, or pointing at a different element?

Sheet 02 — Devices
- [customer] Why a v1 screenshot ("ARICHDS v1.0") beside the v2 one — is the v1 device form (IP Address / Port / Password, Bill Start Date, three Bill Day fields) requested for v2?
- [customer] F45 "Pro100" and F49 "Saral 350": labels for rows in screenshot 2, site inventory, or continuation of the model list?
- [customer] Is "Saral 350" the exact model name?
- [customer] "Samart TTC" vs "samart TCC": typo or two names?
- [internal] Are screenshot 1's 12 "Phase 2-x" meters and screenshot 2's 24 devices the same site?

Sheet 03 — Load Profile
- [customer] "Like this" (P11) — the example table, the current screen, or both?
- [customer] Is the A27:A31 block (Customer / Site Name / Serial Meter / Setting / Load Profile) part of the exported file?
- [customer] What is "Setting : 1"?
- [customer] "Name" column — device name, site name, other?
- [customer] "Import/Export kWh Reactive" — kvarh intended, or "kWh" required as header text?
- [customer] What is "Record Status" and its values?
- [customer] Required timestamp format (cells are datetimes, so the workbook shows only Excel's rendering)?
- [customer] Is WP076996 / "LPH" a specific meter the export must be validated against?
- [internal] Does the current Load Profile CSV produce these 18 columns in this order?

Sheet 04 — RECORD
- [customer] Screenshot only, no note. What is asked?

Sheet 05 — Billing
- [customer] P13 "Use it like this": screen, example table, or both?
- [customer] P14 "exported the new way" — which export is the new way?
- [customer] P14 "แต่ไม่มี export" — reporting that Billing has no export button, or asking for a file without an export step?
- [customer] Three rates in the example vs four on screen (Rate D "—"): three required?
- [customer] Numeric header prefixes (111, 010, 050T, …) required as typed?
- [customer] Is `M/D/YYYY HH:MM` the required timestamp format for Time and demand-time columns?
- [customer] What is "Record Status" and what replaces `..........`?
- [customer] One row per closed billing period (all samples are 1st-of-month 00:00)?
- [customer] Same A27:A31 header block — part of the file?
- [internal] Do "Previous kW demand" / "Previous Time of…" / "Cumul kW demand" map onto Demand Time and Cumulative Demand as stored?

Sheet 06 — Energy Summary
- [customer] Screenshot only, no note. What is asked?

Sheet 07 — Special Day
- [customer] "ดึงมาด้วย": pull Samart TCC's Special Days in addition to which brand's?
- [customer] "อิงตามได้" — based on what?
- [customer] "ถ้าไม่มีเพิ่มเอาได้" — add to the meter, or add on our side (Holidays)?
- [customer] Who is "ซัน"?
- [internal] Glossary says Special Days are never written to a meter; where would "adding" go?

Sheet 08 — Battery
- [customer] Screenshot only, no note. What is asked?

Sheet 09 — Export format
- [customer] Screenshot only, no note. Is the current format acceptable, or is this the screen the example tables change?

Sheet 10 — Event log
- [customer] Is "Event log" the customer's name for App Log, or a separate event log being requested?

Sheet 11 — User
- [customer] Screenshot only, no note. What is asked?

Sheet 12 — Setting
- [customer] P12 beside the License card: no licence gate, no licence logging, or something else?
- [customer] P13 beside "Max meters: Unlimited" / "Licensed models: premier550": which limit?
- [customer] P13's "as follows" — is the sheet-1 list the referent?

Sheet 13 — Data base
- [customer] Are "DATA Base / FTP / API" three required destinations?
- [customer] "API" — push to, or expose?
- [customer] "FTP" — the existing "File Upload", or separate?
- [customer] Is v1's "DB Settings" / "API Config" the reference?

## Not covered

Sheets that carry a screenshot but no note:
- 04. RECORD — Records page (two meters, 96/day, "83 (-13)" on 09-06)
- 06. Energy Summary — Summary Report for "3CL (002607000049)", 2026-08-30 → 09-05
- 08. Battery — empty ("No battery readings stored yet")
- 09. Export format — Date/time format `yyyy-mm-dd HH:MM:SS`, filename `{meter}.csv`
- 10. Event log — App Log page, 500 lines, poller/dlms messages
- 11. User — User Management, one `admin` account

No sheet is empty; every sheet has at least one image.
