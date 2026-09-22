# 01: An admin chooses the Capture Style, and Classic has something to draw from

**What to build:** On the Billing page, beside the Capture folder, an admin sees **Capture image
style: Standard / Classic** — Standard selected on any install that never chose — and saves it
with one click; a `user` sees it and cannot change it. Nothing on disk changes when it is
switched. Alongside, one new endpoint hands the Classic page (ticket 02) everything it will draw,
already formatted: the capture folder with `/` separators, the device's real group (blank when it
has none), `<BRAND>` and Meter Serial, a Statistics Summary counted from what the Poller knows
right now over the devices sharing that group (Paused not counted; *Devices with Issues* =
Offline only; Unknown counted but not an issue; Complete = Total − Issues), and the ten most
recent closed periods oldest first then by Billing Sequence, each cell a string the old program
would have printed (`100.302`, `319840.2819`, `1/21/2026 00:00` local, empty for a missing
value), always kWh/kW. Every value is true or is inert. No image is produced by this ticket; the
setting round-trips and the numbers are right. Decision record: ADR 0028 (and ADR 0029 for the
row key/order); spec: `.scratch/capture-style/spec.md`; glossary: CONTEXT.md → *Capture Style*,
*Billing Sequence*.

**Blocked by:** `.scratch/billing-sequence/issues/01` (ARICHDS holds every closed period the
meter holds, oldest first) — the rows and their order

**Status:** done — 2026-09-22 (commit in the log). One deviation from the spec, recorded in
CLAUDE.md's ADR 0028 digest: the endpoint is keyed by `reading_id` (the anchor) rather than
`end`+`limit`, because `_png_source_rows` has been anchor-sequence-aware since the billing-sequence
review round and only the id can name a same-second pair's older member. Evidence: 15 tests in
`test_api_billing_capture_classic.py` + 5 in `test_api_billing_settings.py`; seven mutation probes
(paused counted, unknown as issue, `NULL` group, rows not reversed, epoch rendered, leading zeros,
style not persisted) all red; `pnpm lint && pnpm build` green; full gate in the commit message.

- [x] Setting `capture_style` ∈ {`standard`, `classic`}, default `standard`, stored through the
      existing settings table; no migration; no licence feature key
- [x] `GET`/`PUT` billing settings carry `capture_style` beside `capture_dir`: a fresh database
      answers `standard`; a `user` may read and is refused on write; an admin round-trips
      `classic`; `banana` is 422; saving a style leaves `capture_dir` untouched and saving
      `capture_dir` leaves the style untouched (`test_api_billing_settings.py`)
- [x] Billing page: the Capture folder card gains the control, disabled for a `user`, saved
      through the same PUT, confirmed by the page's existing success message; no confirmation
      dialog; English-only strings
- [x] New endpoint for the Classic view model, under the billing router's own feature gates and
      the image endpoint's `billing_image_export` gate (a licence without it gets the same refusal
      the image endpoint gives): `save_path` (forward slashes), `group_name` (nullable), `brand`
      (upper-cased catalog brand), `meter_serial`, `statistics {total, issues, complete}`, `rows[]`
- [x] Rows are exactly the ones the PNG window selects (same device, same serial, closed only,
      `bill_date <=` the given end, at most ten) reversed to `bill_date ASC, sequence DESC` —
      seeded with thirteen closed rows plus an Open Period so the selection, the order and the
      Open Period's absence each discriminate; a same-second pair is two rows with one Time
- [x] Each row carries `id` and the nine cells as strings: Name `<BRAND> (<serial>)`; Time and
      Time of kW Demand A as local `M/D/YYYY HH:MM` (no leading zeros on month/day, 24-hour);
      Total kWh Total/A/B/C, Prev kW Demand Rate A/B as four decimals with trailing zeros dropped
      (`100.302`, `319840.2819`, `0` → `0`); `None` → `""`; never scaled by the Display unit
      setting (a test flips it to `base` and the strings do not move)
- [x] The column mapping (Total kWh ← `import_active_kwh_*`, Prev kW Demand ←
      `max_demand_import_active_kw_rate_*`, Time of kW Demand A ←
      `max_demand_import_active_time_rate_a`) is declared in one place with a docstring saying it
      was confirmed on 2026-09-22 from ARICHDS Meter's own `billing.csv` against its own image
      (spec, *Implementation Decisions*); a demand time equal to the meter's epoch
      (`2000-01-01 00:00` local, what TC's rows hold) renders as an empty cell
- [x] Statistics, each as a mutation the test would catch (two devices per status): a Paused
      device is in neither `total` nor `issues`; an Offline device is in both; an Unknown device is
      in `total` only; an Online device is in `total` only; a group-less device counts with the
      other group-less devices and never with a named group, and vice versa; `complete = total −
      issues`; the counts reflect the Poller's stored status at request time, never billing rows
- [x] `save_path` for `C:\CEWE DATA\Billing` reads `C:/CEWE DATA/Billing`; an unconfigured
      capture folder makes the endpoint 404 the way the image endpoint does
- [x] Docs in the same change: CLAUDE.md's ADR 0028 digest records the setting and the endpoint
      as landed (still "Classic page pending" until ticket 02); SPEC.md §3.6 names the style
- [x] Gate: `ruff format --check`, `ruff check`, `pytest -n auto` (app); `pnpm lint`, `pnpm build`
      (web)
