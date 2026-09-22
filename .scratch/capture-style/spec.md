# Spec — Capture Style: Classic reproduces the customer's previous program

**Status:** ready-for-agent · grilled 2026-09-21 (13 questions, 2 rounds) · owner decisions
recorded inline · ADR 0028 accompanies this spec · glossary: CONTEXT.md → *Capture Style*,
*Capture*, *Billing Sequence*. Tracker: local (`.scratch/capture-style/issues/` once
`/to-tickets` runs); no GitHub issue. **Blocked by the Billing Sequence work (ADR 0029,
`.scratch/billing-sequence/`)**: the rows every image draws are keyed and ordered by it.

## Problem Statement

The customer hands the Billing capture image on to people who have received the image their
**previous program** wrote for years — their own desktop program, not v1. Our `.png` is a
screenshot of our Billing page (ADR 0017): a different window, different columns, a different
order. The people downstream have to learn a new picture, and the customer asked, in so many
words, for the old one — "เป๊ะ 100%".

## Solution

An admin opens the Billing page, and beside the Capture folder chooses the **Capture Style**:
**Standard** (today's image) or **Classic**. In Classic, every `.png` written from then on —
the automatic capture of a new closed period, a hand-pressed Capture image, and the
render-on-miss download — is a 1280×709 picture of the previous program's window: its toolbar,
Save Path, Data Billing group with Statistics Summary and the Billing/Current tabs, the Auto
Read Schedule group, the Data Table with the ten most recent closed periods oldest first, and
the status line. Every value in it is true or is inert: the folder, the group, the device and
the rows are real; the statistics are counted from what the Poller knows at the moment of
writing; the schedule panel is fixed text. The `.pdf`, the `.xlsx`, the filename and the
ten-period span are untouched, nothing already on disk is rewritten, and nothing about it is
sold separately. Acceptance is an overlay against a PNG the previous program itself wrote.

## User Stories

1. As an admin, I want a **Capture image style** choice beside the Capture folder on the
   Billing page, so that the setting lives where the capture is configured.
2. As an admin, I want the choice to offer exactly **Standard** and **Classic**, with Standard
   selected on an install that never chose, so that upgrading changes nobody's image.
3. As a user (non-admin), I want to see which style is active but not be able to change it, so
   that the setting follows the same read/change split as the Capture folder.
4. As an admin, I want the style saved with one click and confirmed with a message, so that I
   know it took.
5. As an admin, I want switching style to leave every existing `.png` exactly as it is, so that
   documents already handed over never change under someone's feet.
6. As an admin, I want the new style to govern the very next write on all three paths — the
   automatic capture of a new closed period, the Capture image button, and the download of a
   missing image — so that "next write" means every next write.
7. As an operator, I want to re-issue an old period in the new style by pressing Capture image
   on that period, so that a switch is not a one-way door for history. **Amended 2026-09-22
   (owner, ข):** the button stays render-on-miss — a period whose `.png` already exists is served
   as it is, whatever style wrote it; to re-issue it, delete the file first. ADR 0028's "switching
   style rewrites nothing on disk" wins over this story.
8. As the customer, I want the Classic image to be 1280×709 pixels, always, regardless of how
   many rows it holds, so that it drops into the place the old image occupied.
9. As the customer, I want the toolbar's ten icons to be the previous program's own icons, so
   that the image is recognised at a glance.
10. As the customer, I want *Save Path* to show the real capture folder, with `/` separators as
    the old program showed them, so that the path in the picture is the path on the machine.
11. As the customer, I want *Group* to show the device's real group name, and to be blank when
    the device has none, so that the picture never invents a group.
12. As the customer, I want *Device* to read `<BRAND> - <Meter Serial>` and the table's *Name*
    column to read `<BRAND> (<Meter Serial>)`, so that the two match the old program's wording.
13. As the customer, I want the Data Table to hold the ten most recent closed periods **oldest
    first, then by Billing Sequence** (a same-second pair is two rows, ADR 0029), never the
    Open Period, so that it reads as the old program's table did.
14. As the customer, I want the columns, left to right, to be Name · Time · Total kWh Total ·
    Total kWh Rate A · Total kWh Rate B · Total kWh Rate C · Prev kW Demand Rate A · Time of kW
    Demand A · Prev kW Demand Rate B (cut by the window edge), and nothing past the edge, so
    that the image is cut where the old window was cut.
15. As the customer, I want *Time* and *Time of kW Demand A* in local time as `M/D/YYYY HH:MM`
    (no leading zeros on month or day, 24-hour clock), so that the dates read as they always
    have.
16. As the customer, I want every number in kWh or kW with four decimals and trailing zeros
    dropped (`100.302`, `319840.2819`), so that the figures look as the old program printed
    them.
17. As the customer, I want the Classic image to ignore the machine-wide Display unit setting
    (kW/W), so that a column headed "kWh" is never filled with Wh.
18. As the customer, I want a missing value shown as an empty cell, never `0`, so that the
    picture never claims a reading the meter did not give.
19. As the customer, I want *Statistics Summary* to count the devices sharing the captured
    device's group — or sharing no group, when it has none — so that the numbers are about the
    meters I would expect.
20. As the customer, I want *Total Devices* to exclude Paused devices, so that a meter I took
    out for repair is not counted against me.
21. As the customer, I want *Devices with Issues* to be the devices the Poller currently holds
    Offline, and only those, so that an Unknown (never yet read, or just Resumed) device is not
    accused of anything.
22. As the customer, I want *Complete Devices* to equal Total minus Issues, so that the three
    numbers always agree.
23. As the customer, I want the statistics to be about connectivity at the moment of writing,
    never about whose bill has arrived yet, so that the first meter of a group captured after
    a cut does not picture the other six as broken.
24. As the customer, I want the *Auto Read Schedule* group to show `00` : `00`, `Status:
    Running` and a `Stop` button as fixed text, so that the panel looks as it always did while
    claiming nothing about a bill.
25. As the customer, I want the *Billing* tab selected and *Current* unselected, the *Read
    Billing* and *Reload Table* buttons drawn, and the status line to read
    `Capture bill data <Meter Serial>...`, so that the frame is complete.
26. As the customer, I want the table's own vertical and horizontal scrollbars drawn where the
    old window drew them, so that the picture is the window and not a cropped table.
27. As an operator, I want the Classic page to be unreachable from the menu and from any URL a
    person would type, so that nobody mistakes a picture of a window for a page they can use.
28. As an operator, I want a Classic capture that fails (Edge missing, timeout) to be logged and
    to leave the PDF write untouched, exactly as a Standard one does, so that a picture never
    costs me a document.
29. As an operator, I want the Standard image to stay a screenshot of the Billing page exactly
    as this feature found it (ADR 0029's oldest-first order included), so that customers who
    never asked for Classic notice nothing from *this* change.
30. As a developer, I want the previous program's icons and every measured distance, colour and
    column width in one place, so that the day the customer's original PNGs arrive the
    correction touches one file.
31. As the owner, I want acceptance to be an overlay of our image over a PNG the previous
    program itself wrote — positions, sizes, colours and text agreeing, glyph edges allowed to
    differ — so that "เป๊ะ" is judged against the real thing and not a chat-app JPEG.
32. As the owner, I want that acceptance ticket typed HITL and held until the customer sends
    three or more original PNGs and the machine's display scaling, so that nobody reports
    "identical" from the JPEG.
33. As the owner, I want the column mapping confirmed against a meter both programs read, so
    that a heading-to-column guess never ships as fact.
34. As the owner, I want no new licence feature key, so that the customer does not need a new
    Activation Code to change how a picture looks.
35. As the owner, I want the Central Push, the Database Destination and the File Upload
    Destination unaffected — the FTP upload carries whatever `.png` is on disk, as it does
    today — so that this change stays inside the capture.

## Implementation Decisions

**The setting.**
- One new machine-wide setting key, `capture_style`, values `standard` | `classic`, default
  `standard` (a missing key means today's behaviour). Stored through the existing settings
  table and helpers, no migration.
- Exposed on the existing Billing settings endpoint (`GET`/`PUT /api/billing/settings`) as a
  field beside `capture_dir`. `GET` is any authenticated caller; `PUT` stays admin-only; a value
  outside the two literals is 422 by the body model. The `PUT` replaces both fields together,
  the shape the endpoint already has — the page sends what it holds for both.
- The Billing page's Capture folder card gains a radio/segmented control **Capture image
  style: Standard / Classic**, disabled for a `user`, saved through the same PUT, confirmed by
  the page's existing message. No confirmation dialog on switching: nothing on disk changes.
- No licence feature key. The style is read at write time on every path (ADR 0001 applies the
  same way to settings as to licences — never cached).

**The renderer.**
- `render_billing_png` stays the one entry the three write paths call. It reads
  `capture_style` itself (it already opens a session to mint the capture token) and drives one
  of two on-page targets. `write_png_capture` and `capture_reading` are unchanged in signature.
- The seeded capture request (`capture/dom.py` ↔ `web/src/capture.ts`) gains one field,
  `style: "standard" | "classic"`. A request without it, or with anything else, is treated as
  Standard by the page — a malformed global must never break the page for a human, the
  contract's own rule. `dom.py` remains the one place the contract's strings live.
- In Classic the driver sets the viewport to **1280×709**, clips the screenshot to exactly that
  box and does **not** capture beyond the viewport or grow the height to the content. Standard
  keeps 1920 wide, height grown to fit.
- The row-id gate is unchanged: the driver waits until the rendered body rows are exactly the
  expected ids, in the expected order — for Classic that order is **ascending** `bill_date`
  (the same ten rows `png_source_rows` selects, reversed by the view-model endpoint; the
  expected-id list the driver waits for is built in the same order).
- The Classic page renders no AntD table; its rows carry the same `data-row-key` attribute on
  `<tr>` so the existing selector still finds them. If the page needs its own selector, it is
  declared in `dom.py` beside the existing one, not hardcoded in the driver.

**The Classic view model — the one new seam.**
- `GET /api/billing/capture-classic/{device_id}?end=<iso>&limit=<n>` (any authenticated
  caller — the capture token's user is what the page holds; gated by the router's `billing`
  feature and `billing_image_export`, the same gates the image endpoint has) returns everything
  the page draws: `save_path` (the capture folder with `/` separators), `group_name`
  (nullable), `brand` (upper-cased catalog brand), `meter_serial`, `statistics {total, issues,
  complete}`, and `rows[]` oldest first, each with `id`, `name`, `time`, and the seven
  numeric/time cells **already formatted as strings** (four decimals, trailing zeros dropped,
  local `M/D/YYYY HH:MM`, empty for `None`). The page is a layout, not a formatter — the
  formatting is testable in Python, and one formatting rule cannot drift between the endpoint
  and a page.
- Row selection is `png_source_rows`' own query (same device, same serial, closed periods
  only, `bill_date <= end`, newest first, at most ten) then reversed — never a second copy of
  the rule.
- Statistics: devices whose `group_name` equals the captured device's (`NULL` matches `NULL`),
  excluding disabled (Paused) devices; `issues` = those whose stored status is `offline`;
  `complete = total − issues`. Read from the same rows the Devices page derives its status
  from (ADR 0004) at request time; nothing new is persisted (ADR 0008).
- Column mapping — **confirmed 2026-09-22 from ARICHDS Meter's own `billing.csv`** read against
  its own image of WP081200 (say so in the endpoint's docstring): Total kWh Total/A/B/C ←
  `import_active_kwh_total/_rate_a/_rate_b/_rate_c` (A+B+C = Total on every row of that file);
  Prev kW Demand Rate A/B ← `max_demand_import_active_kw_rate_a/_rate_b`; Time of kW Demand A
  ← `max_demand_import_active_time_rate_a`. Units are the stored kWh/kW, never scaled. A
  demand time the meter left unset (TC's rows hold the meter's epoch, `2000-01-01 00:00`
  local) renders as an empty cell, never as the epoch.
- The `billing.csv` layout, for the record (no header; 1-based): 1 id · 2 period `YYYYMMDD` ·
  3 brand · 4 serial · 5 group · 6 site · 7 Time · 8 Total kWh Total · 9 Rate A · 10 Rate B ·
  11 Rate C · 12 Prev kW Demand Rate A · 13 its time · 14 Rate B · 15 its time · 16 Rate C ·
  17 its time · 18/19/20 cumulative demand A/B/C · 21 reactive import kvarh total · 22 reactive
  max demand (kvar) · 23 its time · 24 its cumulative ×1000 · 25 `..........` · 26 written-at.
- The endpoint is not on the API page's published contract; it is the capture's own, like the
  image endpoint.

**The Classic page.**
- A route in `web/` reached only through the seeded capture request (`App.tsx` already chooses
  the Billing page when a request is present; with `style: "classic"` it chooses the Classic
  page instead). No nav entry, no URL path, not exported from the menu.
- Plain HTML/CSS at a fixed 1280×709 box; no AntD components in the frame (AntD's theme would
  fight every measured colour). One stylesheet holds every measured distance, colour, font
  size and column width; ten icon bitmaps live beside it, cut from the customer's original PNG
  once it arrives — from the JPEG until then, and replaced without a code change.
- English-only strings, exactly the previous program's: `Save Path`, `Browse`, `Data Billing`,
  `Group:`, `Statistics Summary`, `Total Devices:`, `Devices with Issues:`, `Complete Devices:`,
  `Billing`, `Current`, `Device:`, `Read Billing`, `Auto Read Schedule (Default for All
  Devices)`, `Time:`, `Status: Running`, `Stop`, `Data Table`, `Reload Table`, the nine column
  headings, `Capture bill data <serial>...`.
- Colours as measured on the reference: statistics numbers Total and Complete in blue, Issues
  in red; `Status: Running` in green; the rest system greys. Recorded in the stylesheet with
  the measurement's source (JPEG now, PNG later).

**Documents.**
- ADR 0028 (written), CONTEXT.md *Capture Style* (written), CLAUDE.md digest (written, marked
  "decided, not implemented" — flip when it lands). SPEC.md §3.6 gains one sentence naming the
  style. `installer/arichds.iss` `AppVersion` bumps for the build that ships it (a new number,
  never a reused one).

## Testing Decisions

A good test here asserts what a person or the customer would notice — the JSON the page draws
from, the bytes the driver asks Edge for, the setting's round trip — and never how the page
happens to be laid out or which helper formatted a cell.

- **Billing settings** (`test_api_billing_settings.py`, existing shape): default is `standard`
  on a fresh database; a `user` sees it and cannot change it; an admin's `PUT` round-trips;
  `banana` is 422; saving a style does not touch `capture_dir`.
- **The view-model endpoint** (new file beside `test_api_billing_captures.py`, TestClient):
  rows are oldest first and exactly the ten `png_source_rows` selects (seed thirteen, as the
  integration test does — with one row every ordering is identical); the Open Period is absent;
  formatting — `100.302`, `319840.2819`, `0` → `0`, `None` → `""`, `1/21/2026 00:00` in local
  time; the group rule — a Paused device is not in `total`, an Offline one is in `issues`, an
  Unknown one is in `total` but not `issues`, a device with no group counts with the other
  group-less devices and not with any named group; `complete = total − issues`; `save_path`
  uses `/`; the same feature gates as the image endpoint. Each rule is written as a mutation the
  test would catch (the memory *write required tests as mutations, not scenarios*): two devices
  per status so that swapping the status filter or the `NULL` rule changes the count.
- **The driver** (`test_capture_screenshot*.py`, fake CDP transport): with `classic` the seeded
  request carries `style: "classic"`, `Emulation.setDeviceMetricsOverride` is 1280×709, the
  screenshot clip is 1280×709 with no `captureBeyondViewport` and no `Page.getLayoutMetrics`
  growth; with `standard` every request the transport sees is byte-identical to today's
  (assert the recorded request list against the existing expectation, not a new one).
  `test_capture_dom_contract.py` pins the new field the way it pins the others.
- **Real Edge** (`test_capture_screenshot_integration.py`, opt-in `ARICHDS_TEST_EDGE=1`): a
  Classic capture of thirteen seeded rows returns a PNG whose header says 1280×709 and whose
  bytes are non-trivial; the Standard case is unchanged. Run by hand before the build; its
  output line goes in the ticket's evidence.
- **Web**: `pnpm lint && pnpm build`. The Classic page is data in, DOM out; the memory *React
  renders outside the browser for evidence* is the way to prove the page has no network surface
  beyond the one endpoint if a reviewer asks.
- **Acceptance** (HITL ticket): our Classic PNG laid over a customer-original PNG at the same
  scaling — positions, sizes, colours and text agree; and the numbers for one period of one
  meter both programs read agree cell for cell. Recorded with the image pair's paths and the
  date in the ticket; the stylesheet's "measured from" note is updated from JPEG to PNG in the
  same change.
- The gate: `ruff format --check` + `ruff check` + `pytest -n auto` (app), `pnpm lint` +
  `pnpm build` (web), plus the opt-in Edge test run by hand.

## Out of Scope

- Pixel identity with the previous program's glyph rendering (native toolkit vs Chromium).
- A Classic `.pdf` or `.xlsx`; the previous program's own filename or folder convention
  (ours stands: `<capture_dir>/<serial>/<bill_date>.png`).
- Re-rendering existing `.png` files on a style switch.
- An "All" or invented group for group-less devices; a per-device style.
- A real schedule behind the Auto Read Schedule panel.
- The columns past the window's right edge (Prev kW Demand Rate B and beyond are cut, and
  nothing beyond them is fetched or drawn).
- Any change to the Central Push, the Database Destination or the File Upload Destination.
- A licence key for the style.

## Further Notes

- The previous program is **ARICHDS Meter** (owner, 2026-09-22). References, all in the owner's
  Downloads folder and **kept out of the repository** except the icons (real serials, groups and
  readings): `capture_WP081200.png` — a 1280×709 PNG the program itself wrote, the overlay
  target; `Screenshot 2026-09-22 191637.png` — its ten toolbar icons, 514×54, owner-supplied and
  shippable; `billing.csv` — its export, the source of the confirmed column mapping;
  `S__12976353.jpg` — an earlier chat-app JPEG of another window (WP079092), also 1280×709,
  now a secondary reference. Because the program writes a fixed 1280×709 image, display scaling
  is irrelevant.
- Two things the PNG shows that the JPEG did not: the *Auto Read Schedule* time reads `00 : 10`
  there and `00 : 00` in the JPEG — it is a per-install setting of ARICHDS Meter, and Classic
  shows `00 : 00` unless the owner says otherwise; and a *Statistics Summary* of `212 / 36 /
  176` — real numbers from a 212-meter group, which is what our count must be able to produce.
- As of 2026-09-22 nobody consumes the Central Push or the FTP upload; only the Database
  Destination to `localhost` is in use — so contract version 2 has no server to coordinate with
  yet.
- Ask the customer for: three or more PNGs the previous program itself wrote (different meters,
  different row counts, a long name), that machine's Windows display scaling, and at least one
  image of a meter v2 also reads.
- The reference image shows 8 rows with one month absent and is cut mid-column on the right —
  neither is something to reproduce; ten rows and the cut are what the fixed frame gives.
- Owner decisions from the grill, for the record: reader is a person (Q1); statistics from
  connectivity, not billing completeness (Q7); Paused uncounted, Issues = Offline only (Q13);
  setting not a fourth file nor a replacement for everyone (Q5); no licence key (Q10); "Classic",
  not "legacy" (Q9); start from the JPEG, accept only against PNGs (Q12).
