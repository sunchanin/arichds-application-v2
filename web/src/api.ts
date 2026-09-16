/**
 * Thin client for the ARICHDS API.
 *
 * Every call is a same-origin relative URL: in production FastAPI serves both
 * the SPA and the API, and in development Vite proxies `/api` to the backend.
 * There is no base-URL configuration to get wrong.
 *
 * One place attaches the Access Token and one place reacts to a 401, so no page
 * has to remember to do either.
 */

import { clearSession, getSession } from "./auth";

/** The `{success, data, error}` envelope every endpoint returns. */
export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: ApiError | null;
}

export interface ApiError {
  code: string;
  message: string;
  reason: string | null;
}

export interface LicenseStatus {
  machine_id: string;
  state: "active" | "limited";
  reason: string | null;
  customer: string | null;
  mode: string | null;
  expires_at: string | null;
  max_meters: number | null;
  /**
   * The **effective** feature set — `.env FEATURES ∩ licence` — resolved by the
   * server, sorted, and never null (issue 012). `[]` means nothing is enabled,
   * which is also what a non-active machine reports; the sellable keys are
   * deliberately not duplicated in TypeScript, so adding one is a backend-only
   * edit. Read it through `features.ts`, never by comparing strings inline.
   */
  enabled_features: string[];
  /**
   * The licensed meter model keys (issue 015) — **raw**, never resolved: a
   * model has no `.env` equivalent to intersect against, unlike
   * `enabled_features`, so there is nothing to resolve. Three states, all
   * meaningful: `null` means every catalogued model may be added (including
   * on a non-active machine, whose value is always `null` but meaningless —
   * Limited Mode blocks every device handler first); `[]` means none may be
   * added; a list names exactly which. Rendered as raw model keys — no
   * label map in TypeScript (issue 015, decision D), matching what the
   * vendor CLI's `--models` and the Create/Update 422 both name.
   */
  licensed_models: string[] | null;
  /**
   * Whether this machine demands a **Meter Activation Code** for each meter
   * added (issue 01) — **resolved by the server**, unlike `licensed_models`.
   *
   * The licence's own value is a tri-state where "unstated" means "not
   * required"; that rule lives in the backend only, so this is a plain
   * boolean and TypeScript never carries a second copy of it. `false` on a
   * non-active machine, which is meaningless there — Limited Mode blocks
   * every device handler before anything can be added.
   */
  meter_activation_required: boolean;
}

/**
 * What a device's last read proved (ADR 0004). `paused` is computed from
 * `enabled` rather than stored, so this can never say `online` for a device
 * nobody is reading.
 */
export type DeviceStatus = "online" | "offline" | "paused" | "unknown";

/** The seven things a Device Event records (CONTEXT.md — Device Event). */
export type DeviceEventKind =
  | "online"
  | "offline"
  | "created"
  | "updated"
  | "paused"
  | "resumed"
  | "data_cleared";

/** A TCP/IP Transport Endpoint. */
export interface NetTransport {
  kind: "net";
  host: string;
  port: number;
}

/**
 * A serial Transport Endpoint (issue #9) — five fields, no flow control: the
 * `-S` argv seam the backend's `GXSettings` parses carries no flow-control
 * slot at all, and both field-confirmed SMW110W4 units run at the default of
 * "no flow control".
 */
export interface SerialTransport {
  kind: "serial";
  serial_port: string;
  baud_rate: number;
  data_bits: number;
  parity: string;
  stop_bits: number;
}

/** A device's Transport Endpoint — TCP or serial, discriminated on `kind`. */
export type Transport = NetTransport | SerialTransport;

/**
 * A device as `GET /api/devices` returns it — every field the Devices page
 * needs, status included, so the tree paints from **one** call rather than an
 * N+1 per meter.
 */
export interface Device {
  id: number;
  name: string;
  brand: string;
  model: string;
  /** Read off the meter (ADR 0005). Null only for rows created before M3. */
  meter_serial: string | null;
  site_name: string;
  site_code: string | null;
  customer: string | null;
  meter_number: string | null;
  group_name: string | null;
  transport: Transport;
  /**
   * The stored DLMS password, in the clear. Owner ruling (2026-08-11): meter
   * passwords are not a security boundary, so convenience wins over secrecy —
   * this is what lets the edit form prefill it and Test Connection run
   * without retyping.
   */
  password: string;
  endpoint: string;
  enabled: boolean;
  status: DeviceStatus;
  /** A sentence explaining a non-online status, or null. */
  status_detail: string | null;
  /** When a read last reported on this device (UTC), or null when none has. */
  status_checked_at: string | null;
  first_bill_date: string | null;
  bill_day_feb28: number | null;
  bill_day_feb29: number | null;
  bill_day_30: number | null;
  bill_day_31: number | null;
  created_at: string;
}

/** One row of a device's history, from `GET /api/devices/{id}/events`. */
export interface DeviceEvent {
  id: number;
  kind: DeviceEventKind;
  detail: string | null;
  /** Who did it, or **null for an automatic transition** — nobody took a meter offline. */
  actor: string | null;
  created_at: string;
}

/** One page of history. `total` is the unpaged count the pager needs. */
export interface DeviceEventPage {
  items: DeviceEvent[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * One Interval Reading, from `GET /api/load-profile`.
 *
 * Every measurement is `number | null`, and the null is load-bearing: the only
 * meter model in service captures seven of the twelve columns, so the other five
 * arrive as `null` on every row. They must render as an em dash, never as `0` —
 * which is why nothing here may be read with `??` or `||` (see `LoadProfile.tsx`).
 */
export interface LoadProfileRow {
  /**
   * UTC, ISO-8601. Rendered in the browser's local clock. Always a Logger 1
   * timestamp — Logger 1 is the spine of the read-side merge (owner ruling,
   * 2026-08-11; see `app/src/arichds/api/load_profile.py`'s module docstring).
   */
  read_at: string;
  import_active_kwh: number | null;
  import_reactive_kvarh: number | null;
  export_active_kwh: number | null;
  export_reactive_kvarh: number | null;
  avg_geo_pf: number | null;
  volt_l1: number | null;
  volt_l2: number | null;
  volt_l3: number | null;
  current_l1: number | null;
  current_l2: number | null;
  current_l3: number | null;
  freq: number | null;
  phase_angle_a: number | null;
  phase_angle_b: number | null;
  phase_angle_c: number | null;
  /**
   * The meter's own Interval Status word, raw. `interval_status` below is the
   * same value decoded to words; the decoding happens on the server, in
   * `arichds/interval_status.py`, so the CSV and this page can never word one
   * bitmap differently. This is deliberately unlike `units.ts`, which is a
   * hand-kept TypeScript twin — a status vocabulary has no reason to exist
   * twice.
   */
  interval_status_flag: number | null;
  /** The decoded wording, or `""` on a model that records no status word. */
  interval_status: string;
  import_active_kw: number | null;
  import_reactive_kvar: number | null;
  export_active_kw: number | null;
  export_reactive_kvar: number | null;
  volt_l1_l2: number | null;
  volt_l2_l3: number | null;
  volt_l3_l1: number | null;
}

/** One page of Interval Readings. `total` is the unpaged count the pager needs. */
export interface LoadProfilePage {
  items: LoadProfileRow[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * What `POST /api/load-profile/read` did (issue #44). A live-read failure is
 * a verdict on `error`, never a thrown error — mirrors
 * `EnergyRegisterReadResult` ("always arrives on a 200 — the verdict is in
 * here").
 */
export interface LoadProfileReadNowResult {
  stored: number;
  /** UTC, ISO-8601 — the highest `read_at` now stored, or null if the
   * device still has no rows. */
  through: string | null;
  /** Whether another press would make progress (D9) — the Load Profile
   * page's button loops on this field, never on `detail`/message text. */
  history_remains: boolean;
  error: string | null;
}

/** Which Billing page tab a row belongs to — closed periods (History) or the
 * one Open Period slot (Current), from `GET /api/billing`'s `status` query. */
export type BillingStatus = "closed" | "open";

/**
 * One Billing Reading as `GET /api/billing` returns it — **all sixty**
 * measurement columns (D19, M4c issue #24; grew from the original eight
 * `*_total`-only shape so the grouped-header Billing page, D20, can show
 * every tariff). `null` here means the meter never captured that quantity,
 * never `0`, so it must render as an em dash (see `Billing.tsx`).
 *
 * Ten of the sixty (the Demand Time columns) are ISO-8601 UTC timestamp
 * strings, not numbers — when a maximum demand actually occurred
 * (CONTEXT.md — Demand Time), never scaled.
 */
export interface BillingRow {
  /** The row's own id — used by the History tab's download-capture link (M6b, issue #22). */
  id: number;
  device_id: number;
  device_name: string;
  /** The meter's own Clock cell — UTC, ISO-8601 (CONTEXT.md — Bill Date). */
  bill_date: string;
  /** When *we* read it — UTC, ISO-8601. */
  read_at: string;
  meter_serial: string | null;

  import_active_kwh_total: number | null;
  import_active_kwh_rate_a: number | null;
  import_active_kwh_rate_b: number | null;
  import_active_kwh_rate_c: number | null;
  import_active_kwh_rate_d: number | null;

  export_active_kwh_total: number | null;
  export_active_kwh_rate_a: number | null;
  export_active_kwh_rate_b: number | null;
  export_active_kwh_rate_c: number | null;
  export_active_kwh_rate_d: number | null;

  import_reactive_kvarh_total: number | null;
  import_reactive_kvarh_rate_a: number | null;
  import_reactive_kvarh_rate_b: number | null;
  import_reactive_kvarh_rate_c: number | null;
  import_reactive_kvarh_rate_d: number | null;

  export_reactive_kvarh_total: number | null;
  export_reactive_kvarh_rate_a: number | null;
  export_reactive_kvarh_rate_b: number | null;
  export_reactive_kvarh_rate_c: number | null;
  export_reactive_kvarh_rate_d: number | null;

  max_demand_import_active_kw_total: number | null;
  max_demand_import_active_kw_rate_a: number | null;
  max_demand_import_active_kw_rate_b: number | null;
  max_demand_import_active_kw_rate_c: number | null;
  max_demand_import_active_kw_rate_d: number | null;

  max_demand_export_active_kw_total: number | null;
  max_demand_export_active_kw_rate_a: number | null;
  max_demand_export_active_kw_rate_b: number | null;
  max_demand_export_active_kw_rate_c: number | null;
  max_demand_export_active_kw_rate_d: number | null;

  max_demand_import_reactive_kvar_total: number | null;
  max_demand_import_reactive_kvar_rate_a: number | null;
  max_demand_import_reactive_kvar_rate_b: number | null;
  max_demand_import_reactive_kvar_rate_c: number | null;
  max_demand_import_reactive_kvar_rate_d: number | null;

  max_demand_export_reactive_kvar_total: number | null;
  max_demand_export_reactive_kvar_rate_a: number | null;
  max_demand_export_reactive_kvar_rate_b: number | null;
  max_demand_export_reactive_kvar_rate_c: number | null;
  max_demand_export_reactive_kvar_rate_d: number | null;

  /** ISO-8601 UTC, or null — when the corresponding max demand occurred
   * (CONTEXT.md — Demand Time). M4c, issue #24. */
  max_demand_import_active_time_total: string | null;
  max_demand_import_active_time_rate_a: string | null;
  max_demand_import_active_time_rate_b: string | null;
  max_demand_import_active_time_rate_c: string | null;
  max_demand_import_active_time_rate_d: string | null;

  max_demand_import_reactive_time_total: string | null;
  max_demand_import_reactive_time_rate_a: string | null;
  max_demand_import_reactive_time_rate_b: string | null;
  max_demand_import_reactive_time_rate_c: string | null;
  max_demand_import_reactive_time_rate_d: string | null;

  cumul_demand_import_active_kw_total: number | null;
  cumul_demand_import_active_kw_rate_a: number | null;
  cumul_demand_import_active_kw_rate_b: number | null;
  cumul_demand_import_active_kw_rate_c: number | null;
  cumul_demand_import_active_kw_rate_d: number | null;

  cumul_demand_import_reactive_kvar_total: number | null;
  cumul_demand_import_reactive_kvar_rate_a: number | null;
  cumul_demand_import_reactive_kvar_rate_b: number | null;
  cumul_demand_import_reactive_kvar_rate_c: number | null;
  cumul_demand_import_reactive_kvar_rate_d: number | null;
}

/** One page of Billing Readings. `total` is the unpaged count the pager needs. */
export interface BillingPage {
  items: BillingRow[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * The Billing settings, from `GET`/`PUT /api/billing/settings` (M6b, issue #22).
 *
 * `capture_dir` of `""` means "not configured" — capture is then skipped
 * rather than defaulting to some fixed path (ADR 0010). `capture_count` is
 * how many **closed** billing rows exist right now — the rows a capture
 * could exist for — and is what the Save form's "this orphans existing
 * captures" warning is based on; the backend never blocks on it.
 */
export interface BillingSettings {
  capture_dir: string;
  capture_count: number;
}

/**
 * What `POST /api/billing/read` did (issue #44). A live-read failure is a
 * verdict on `error`, never a thrown error — mirrors
 * `LoadProfileReadNowResult`.
 */
export interface BillingReadNowResult {
  /** How many closed periods this call newly inserted. */
  stored: number;
  /**
   * How many **captures** this call wrote (issue 02).
   *
   * Deliberately not derivable from `stored`: with no capture folder set (or
   * no `auto_capture` entitlement) periods are stored and no documents are
   * written at all. It comes from the read path rather than being inferred
   * here from the capture-folder setting, which non-admin roles never load.
   */
  captured: number;
  open_updated: boolean;
  error: string | null;
}

/**
 * What the All-Meters View says about one meter (issue 01), resolved
 * server-side — the threshold constant lives in the backend and the planned
 * billing export needs the same rule, so computing it here would put one rule
 * in two languages.
 */
export type AllMetersStatus = "paused" | "not_answering" | "never_billed" | "behind" | "ok";

/**
 * One meter's latest **closed** period, from `GET /api/billing/all-meters`.
 *
 * Deliberately narrow against `BillingRow`'s sixty measurements: History is
 * shaped for one meter across time, and that shape is unreadable across every
 * meter at once. Clicking a row opens History for that meter instead.
 *
 * `bill_date` is null for a meter that has never produced a closed period —
 * the row still exists, because the row set comes from devices, not readings.
 * `captured_at` is null when there is no reading **and** whenever captures are
 * switched off, since the read time would otherwise name a document nobody
 * wrote. `status_value` is the number the chip carries: consecutive failures
 * for `not_answering`, whole days behind for `behind`, null otherwise.
 */
export interface AllMetersRow {
  device_id: number;
  device_name: string;
  meter_serial: string | null;
  bill_date: string | null;
  captured_at: string | null;
  import_active_kwh_total: number | null;
  export_active_kwh_total: number | null;
  status: AllMetersStatus;
  status_value: number | null;
}

/**
 * The whole All-Meters View. Not paged, unlike `BillingPage` — it is bounded
 * by device count, not by reading volume.
 *
 * `needs_attention` counts every row that is neither `ok` nor `paused`, and is
 * what the tab header shows so an operator knows whether to open the tab.
 */
export interface AllMetersView {
  items: AllMetersRow[];
  needs_attention: number;
  /** The Billing toolbar strip (ui-audit ticket 10) — computed from `items`
   * on the server so the strip and the tab share one definition of "issue".
   * `devices_with_issues + complete === total_devices` always; `paused`
   * counts as an issue here even though it needs no attention. */
  total_devices: number;
  devices_with_issues: number;
  complete: number;
  /** The Billing Change Check rides the Load Profile cycle (ADR 0018). */
  auto_interval_sec: number;
  /** UTC ISO-8601, or null until the first cycle since the service started
   * — the scheduler keeps no persisted state (ADR 0008). */
  auto_last_cycle_at: string | null;
}

/**
 * One meter-logger's completeness on one local day, from `GET /api/records`.
 *
 * `expected` and `interval_sec` are null **only** when `status` is `missing`:
 * with no rows stored that day there is no capture period to compute an
 * expectation from, which is exactly what makes "nothing at all" a different
 * answer from "short by everything". Every other status carries both.
 *
 * `expected` is always `86400 / interval_sec` — never 96. A Prometer 100's
 * Logger 2 runs at 300 s, so a complete day for it is 288.
 */
export interface RecordsCell {
  /** The local calendar day, `YYYY-MM-DD`. */
  date: string;
  count: number;
  expected: number | null;
  /** The capture period the count is judged against; the day's **modal** one when it changed. */
  interval_sec: number | null;
  status: "complete" | "short" | "missing" | "period_changed";
}

/**
 * One line of the Records grid — a `(meter, logger)` pair, never a meter alone.
 *
 * `logger_id` is null only for a meter that recorded nothing at all in the
 * range: there is no logger to name, and the row still appears because a
 * completeness page that drops the silent meter is broken exactly where it
 * matters.
 */
export interface RecordsRow {
  device_id: number;
  device_name: string;
  site_name: string;
  logger_id: number | null;
  /** One per entry in `RecordsGrid.dates`, same order and length. */
  cells: RecordsCell[];
}

/** The completeness grid: the date axis, and a row per meter-logger. */
export interface RecordsGrid {
  /** Every date in the requested range, ascending, `YYYY-MM-DD`. */
  dates: string[];
  rows: RecordsRow[];
}

/**
 * One local calendar day's Time-of-Use buckets, from `GET /api/energy/summary`
 * (M7-1, issue #28; CONTEXT.md — Energy Summary). Only active energy —
 * import and export, never reactive (decision 8). **Derived, never stored**
 * (ADR 0012): a day absent from the response simply has no stored Interval
 * Reading in range, mirroring `api/records.py`'s own live-count rule.
 */
export interface EnergySummaryDay {
  /** The local calendar day, `YYYY-MM-DD`. */
  date: string;
  peak_import_kwh: number;
  offpeak_import_kwh: number;
  holiday_import_kwh: number;
  total_import_kwh: number;
  peak_export_kwh: number;
  offpeak_export_kwh: number;
  holiday_export_kwh: number;
  total_export_kwh: number;
}

export interface EnergySummaryReport {
  days: EnergySummaryDay[];
}

/**
 * One stored `energy_register_readings` row, from `GET`/`POST /api/energy/registers*`
 * (M7-1, issue #28; CONTEXT.md — Energy Registers). Twenty measurement
 * columns, all `number | null` — `null` means the meter's address refused,
 * never `0` (mirrors `BillingRow`'s own rule).
 */
export interface EnergyRegisterRow {
  id: number;
  device_id: number;
  /** UTC, ISO-8601 — **our** clock, truncated to whole seconds, not the meter's. */
  read_at: string;
  meter_serial: string | null;

  import_active_kwh_total: number | null;
  import_active_kwh_rate_a: number | null;
  import_active_kwh_rate_b: number | null;
  import_active_kwh_rate_c: number | null;
  import_active_kwh_rate_d: number | null;

  export_active_kwh_total: number | null;
  export_active_kwh_rate_a: number | null;
  export_active_kwh_rate_b: number | null;
  export_active_kwh_rate_c: number | null;
  export_active_kwh_rate_d: number | null;

  import_reactive_kvarh_total: number | null;
  import_reactive_kvarh_rate_a: number | null;
  import_reactive_kvarh_rate_b: number | null;
  import_reactive_kvarh_rate_c: number | null;
  import_reactive_kvarh_rate_d: number | null;

  export_reactive_kvarh_total: number | null;
  export_reactive_kvarh_rate_a: number | null;
  export_reactive_kvarh_rate_b: number | null;
  export_reactive_kvarh_rate_c: number | null;
  export_reactive_kvarh_rate_d: number | null;
}

/**
 * What `POST /api/energy/registers/read` did. A live-read failure (a
 * connection error, a busy endpoint) is a verdict on `error`, never an
 * HTTP error status — mirrors `TestConnectionResult` ("always arrives on a
 * 200 — the verdict is in here").
 */
export interface EnergyRegisterReadResult {
  row: EnergyRegisterRow | null;
  error: string | null;
}

/** Which of the two Holiday kinds a row is (CONTEXT.md — Holiday). */
export type HolidayKind = "annual" | "public";

/** One stored Holiday row, from `GET /api/holidays`. Machine-wide — no `device_id`. */
export interface Holiday {
  id: number;
  kind: HolidayKind;
  name: string;
  /** `YYYY-MM-DD`, `public` only — `null` for `annual`. */
  date: string | null;
  /** 1-12, `annual` only — `null` for `public`. */
  month: number | null;
  /** 1-31, `annual` only — `null` for `public`. */
  day: number | null;
}

/** The body `POST`/`PATCH /api/holidays` and each entry of a JSON import
 * document take. Exactly one of `date` or `month`+`day` is set, matching
 * `kind` — the API 422s on any other shape, including 29 February as `annual`. */
export interface HolidayInput {
  kind: HolidayKind;
  name: string;
  date?: string | null;
  month?: number | null;
  day?: number | null;
}

/** The JSON export/import document shape (decision 14) — the whole calendar,
 * as one file that travels between machines. */
export interface HolidayDocument {
  version: number;
  holidays: HolidayInput[];
}

/** What `POST /api/holidays/import-from-meter` did. */
export interface HolidayImportFromMeterResult {
  imported: Holiday[];
  /** How many of the meter's own entries collided with another of the
   * meter's entries and were dropped, keeping the first (decision 15). */
  skipped: number;
}

/** Which of the five ways a Holiday moves one recorded change names
 * (ADR 0022, M14 ticket 06; CONTEXT.md — Holiday Change). */
export type HolidayChangeAction = "add" | "edit" | "delete" | "import_csv" | "import_meter";

/**
 * One recorded Holiday Change, from `GET /api/holidays/changes` — who made a
 * Holiday mutation, when, and which day it names (or how many Holidays an
 * import brought in). `holiday_*` fields are set for `add`/`edit`/`delete`
 * and `null` for the two imports; `count` is the reverse.
 */
export interface HolidayChange {
  id: number;
  created_at: string;
  username: string;
  action: HolidayChangeAction;
  holiday_kind: HolidayKind | null;
  holiday_name: string | null;
  holiday_date: string | null;
  holiday_month: number | null;
  holiday_day: number | null;
  count: number | null;
}

/** One page of the Holiday Change record. `total` is the unpaged count the
 * pager needs — mirrors {@link DeviceEventPage}. */
export interface HolidayChangePage {
  items: HolidayChange[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * One entry off a meter's own Special Days Table, from `GET /api/special-days`
 * (M7-1, issue #28) — read-through, never stored. The annual/public split
 * is already resolved by the driver (CONTEXT.md — Holiday): `year` is
 * `null` for an `annual` entry, never the wire's `2000` placeholder.
 */
export interface SpecialDay {
  index: number;
  day_id: number;
  kind: HolidayKind;
  year: number | null;
  month: number;
  day: number;
}

/**
 * What `GET /api/special-days` returned. A live-read failure is a verdict
 * on `error`, never an HTTP error status — `entries` is `[]` both when the
 * meter genuinely holds nothing and when `error` is set.
 */
export interface SpecialDaysReadResult {
  entries: SpecialDay[];
  error: string | null;
}

/**
 * One stored `battery_readings` row, from `GET /api/battery` (M7-2, issue
 * #29; CONTEXT.md — Battery Reading). `status` is the raw charge/status
 * value the meter reported at `0.0.96.6.1.255` — **stored verbatim, never
 * interpreted**: no scaling, no threshold, no colour classification. `null`
 * means the meter answered with nothing on that read, not that the read
 * failed (a failed read stores no row at all). Written only by the hourly
 * background job — there is no Read-now endpoint for battery.
 */
export interface BatteryRow {
  id: number;
  device_id: number;
  device_name: string;
  meter_serial: string | null;
  /** UTC, ISO-8601 — **our** clock, not the meter's. */
  read_at: string;
  status: string | null;
}

/** One page of Battery Readings. `total` is the unpaged count the pager needs.
 * `failure` is present only for a single-device request whose last hourly
 * read failed — kept in memory on the server since it started, never stored. */
export interface BatteryPage {
  items: BatteryRow[];
  total: number;
  limit: number;
  offset: number;
  failure: { at: string; reason: string } | null;
}

/**
 * One parsed entry from the rotating application log, from `GET /api/logs`
 * (M7-4, issue #31). `timestamp` is the raw string the log line carried —
 * local-time-with-offset, unlike every UTC value elsewhere in this API — and
 * is rendered verbatim, never parsed with `dayjs`. `level`/`logger` are
 * `null` for a leading continuation line with no preceding header; `message`
 * carries any continuation lines (e.g. a traceback) joined onto it.
 */
export interface LogEntry {
  timestamp: string | null;
  level: string | null;
  logger: string | null;
  message: string;
}

/** The tail of the application log. Not a page — the client already knows
 * what it asked for. */
export interface LogTail {
  items: LogEntry[];
}

/**
 * The machine-wide display-unit setting — `"kilo"` (kW/kWh/kvar/kvarh,
 * today's behaviour) or `"base"` (W/Wh/var/varh), from
 * `GET`/`PUT /api/settings/display`. One value for the whole machine, not
 * per user (owner ruling). Applied at render time only — every readings
 * endpoint keeps returning kWh/kvarh/kW/kvar regardless of this setting; see
 * `units.ts`, which is where the conversion actually happens.
 */
export type DisplayUnitScale = "kilo" | "base";

export interface DisplaySettings {
  display_unit_scale: DisplayUnitScale;
}

/**
 * The Export Format settings, from `GET`/`PUT /api/settings/export-format`
 * (M7 slice 3, issue #30). Machine-wide, not per-meter (SPEC §3.7, grill
 * 2026-08-11) — one customer's site runs meters set up identically, so a
 * per-device column would solve a problem nobody has hit.
 *
 * **The CSVs these govern are always kWh/kvarh** — they never follow
 * `display_unit_scale` (ADR 0013). `export_date_format`,
 * `export_csv_filename_tmpl` and `export_billing_filename_tmpl` are owned by
 * the ExportFormat page; `export_auto_save_enabled` and `export_output_dir`
 * are owned by the matching controls on the Load Profile page (D-16) — one
 * `PUT` replaces all five, so either page's save must carry the other side's
 * current values through unchanged.
 */
export interface ExportFormatSettings {
  /** An Excel-style token string, e.g. `"yyyy-mm-dd HH:MM:SS"` — `yyyy`/`mm`/`dd`/`HH`/`MM`/`SS`. */
  export_date_format: string;
  /** `[meter]`/`[serial]`/`[date]` filename tokens for the Load Profile CSV, e.g. `"[meter].csv"`. */
  export_csv_filename_tmpl: string;
  /**
   * The same token shape for the billing export file (M13, issue 01). Its own
   * key rather than a suffix on the one above: both files land in
   * `export_output_dir`, so one template would have them overwrite each other.
   */
  export_billing_filename_tmpl: string;
  /** The same for the Energy Summary file (M13, issue 02) — names the daily file. */
  export_energy_filename_tmpl: string;
  /** The scheduler job's own switch — "Save CSV now" ignores it. */
  export_auto_save_enabled: boolean;
  /** `""` means "not configured" — same convention as `capture_dir`. */
  export_output_dir: string;
}

/**
 * What the last Database Destination sync cycle did (issue #46).
 *
 * In memory on the service only (ADR 0008 forbids persisted job state), so it
 * is `null` until a cycle has run since the last restart — which is not an
 * error state and must not be shown as one.
 */
export interface DatabaseDestinationSyncStatus {
  /** When the cycle finished, UTC. */
  ran_at: string;
  /** Interval Readings sent — "sent", never "gained": a row re-sent inside the watermark rewind counts here. */
  load_profile_rows: number;
  /** Billing Readings written by the whole-table replace. */
  billing_rows: number;
  /** Rows removed from the destination past the Mirror Window (ADR 0020). */
  purged_rows: number;
  /** Rows with no Meter Serial to attribute them to. */
  skipped_rows: number;
  duration_sec: number;
  error: string | null;
  /** The cycle stopped on its wall-clock budget and resumes next tick — **not** an error. */
  budget_exhausted: boolean;
}

/**
 * The Database Destination connection settings (issue #46, SPEC §3.10).
 *
 * **There is no `password` field, by design** — the API never returns it
 * (write-only, the `block_cipher_key` precedent). `password_set` is what lets
 * the form show "unchanged" rather than an empty box that reads as a cleared
 * value.
 */
export interface DatabaseDestinationSettings {
  /** `""` means "not configured" — the sync then does nothing, with no error. */
  host: string;
  port: number;
  /** `""` means "not configured", same as `host`. */
  database: string;
  user: string;
  password_set: boolean;
  last_sync: DatabaseDestinationSyncStatus | null;
}

/**
 * The body `PUT /api/settings/database-destination` takes.
 *
 * **Omit `password` to keep the stored one; send `""` to store an empty
 * password.** The empty string is deliberate: XAMPP's `root` genuinely has no
 * password, so treating `""` as "keep" would make the customer's own reference
 * setup impossible to enter. Send the field only when it was actually edited.
 */
export interface DatabaseDestinationUpdate {
  host: string;
  port: number;
  database: string;
  user: string;
  password?: string;
}

/** The six outcomes `POST …/test` distinguishes. "Connection failed" alone is what it exists to replace. */
export type DatabaseDestinationTestResult =
  | "ok"
  /** Nothing saved to test yet. A blank host is **not** a connection failure — the driver defaults it to localhost. */
  | "not_configured"
  | "unreachable"
  | "auth_failed"
  | "database_missing"
  | "missing_privilege";

/** What `POST /api/settings/database-destination/test` returns — always on a 200, failures included. */
export interface DatabaseDestinationTest {
  result: DatabaseDestinationTestResult;
  /** One operator-actionable English sentence. */
  message: string;
  /** `SELECT VERSION()` on success, `null` otherwise. */
  server_version: string | null;
}

/**
 * What the last Central Push cycle did (ADR 0024, ticket 07).
 *
 * In memory on the service only (ADR 0008), the same shape
 * `DatabaseDestinationSyncStatus` has. Always `null` before ticket 08 lands
 * the job that populates it, and on every restart after.
 */
export interface CentralPushCycleStatus {
  ran_at: string;
  outcome: string;
  meters_rows: number;
  billing_rows: number;
  energy_summary_rows: number;
  load_profile_rows: number;
  skipped_rows: number;
  duration_sec: number;
  error: string | null;
}

/**
 * The Central Push configuration (ADR 0024, ticket 07).
 *
 * **There is no `token` field, by design** — write-only, never returned.
 * `token_set` is what lets the form show "token set" rather than an empty
 * box that reads as cleared.
 */
export interface CentralPushSettings {
  /** `""` disables the push. */
  url: string;
  token_set: boolean;
  last_cycle: CentralPushCycleStatus | null;
}

/**
 * The body `PUT /api/settings/central-push` takes.
 *
 * **Omit `token` to keep the stored one; send `""` to clear it; send a
 * pasted token to have it verified and, if accepted, stored.**
 */
export interface CentralPushUpdate {
  url: string;
  token?: string;
}

/** One field the published contract documents for one item kind. */
export interface CentralPushContractField {
  name: string;
  type: string;
  description: string;
}

/** One item kind (`meters` / `billing` / `energy_summary` / `load_profile`) in the published contract. */
export interface CentralPushContractKind {
  kind: string;
  natural_key: string[];
  replace_whole_roster: boolean;
  fields: CentralPushContractField[];
}

/** One of the three lists inside the holdings response (`load_profile` / `billing` / `energy_summary`). */
export interface CentralPushContractHoldingsEntry {
  kind: string;
  fields: CentralPushContractField[];
}

/**
 * What `GET /api/settings/central-push/contract` returns — generated from
 * the same models the push serializes: the four item kinds, plus the
 * holdings response (`GET .../v1/holdings`) and its three entry lists, plus
 * the push envelope (`POST .../v1/push`) — every payload model, not just
 * the item kinds.
 */
export interface CentralPushContract {
  contract_version: number;
  holdings_endpoint: string;
  push_endpoint: string;
  /** The top-level fields of the holdings response (`contract_version`, `load_profile`, `billing`, `energy_summary`). */
  holdings: CentralPushContractField[];
  /** The fields inside each of the holdings response's three lists. */
  holdings_entries: CentralPushContractHoldingsEntry[];
  /** The fields of one push request's envelope (`contract_version`, `machine_id`, `sent_at`, `kind`, `items`). */
  envelope: CentralPushContractField[];
  kinds: CentralPushContractKind[];
  notes: string[];
}

/**
 * What the last File Upload Destination cycle did (ADR 0025, tickets 01-02).
 *
 * In memory on the service only (ADR 0008), `null` until a cycle has run
 * since the last restart. The three real transports (SFTP/FTPS/HTTPS) land
 * in tickets 03-05, so today the one `outcome` reachable is
 * `"not_configured"` (an unset protocol, or one with no host/URL) — a
 * *configured* page still publishes nothing, because the backend has no
 * transport to build yet.
 */
export interface FileUploadStatus {
  ran_at: string;
  protocol: string;
  outcome: string;
  files_sent: number;
  bytes_sent: number;
  files_skipped_unchanged: number;
  files_skipped_budget: number;
  files_skipped_no_serial: number;
  duration_sec: number;
  error: string | null;
}

/**
 * What `POST /api/settings/file-upload/upload-now` returns (ADR 0025,
 * ticket 02).
 *
 * `finished` is `false` when the endpoint's own bounded wait ran out before
 * the triggered cycle actually completed — the one-shot lane runs behind
 * every job already due on the scheduler's one thread, so a slow meter read
 * ahead of it can outlast the wait. When `false`, `status` is whatever was
 * already published before this request (possibly `null`, possibly an
 * unrelated earlier cycle) and must not be read as this cycle's own result.
 */
export interface FileUploadUploadNowResult {
  finished: boolean;
  status: FileUploadStatus | null;
}

/**
 * The SFTP tab as the API reports it (ADR 0025).
 *
 * **There is no `password` or `key_passphrase` field, by design** — both are
 * write-only, the `db_dest_password` precedent. `password_set` /
 * `key_passphrase_set` are what let the form show "set" rather than an
 * empty box that reads as cleared.
 */
export interface FileUploadSftpSettings {
  host: string;
  port: number;
  username: string;
  password_set: boolean;
  /** Not a secret — a file path, always echoed back in full. */
  key_path: string;
  key_passphrase_set: boolean;
  remote_root: string;
  /** `""` until a first successful connection pins one (ticket 04). */
  host_key_fingerprint: string;
}

/** The FTPS tab as the API reports it — no `password` field, same rule. */
export interface FileUploadFtpsSettings {
  host: string;
  port: number;
  username: string;
  password_set: boolean;
  remote_root: string;
}

/** The HTTPS tab as the API reports it — no `token` field, same rule. */
export interface FileUploadHttpsSettings {
  url: string;
  token_set: boolean;
  remote_root: string;
}

/**
 * `GET /api/settings/file-upload` (ADR 0025, ticket 01).
 *
 * `active_protocol` is `""` (nothing saved yet), `"sftp"`, `"ftps"` or
 * `"https"` — the tab saved last. The other two tabs' settings are still
 * returned, unchanged, so their forms can render even while inactive.
 */
export interface FileUploadSettings {
  active_protocol: "" | "sftp" | "ftps" | "https";
  sftp: FileUploadSftpSettings;
  ftps: FileUploadFtpsSettings;
  https: FileUploadHttpsSettings;
  status: FileUploadStatus | null;
}

/**
 * The body `PUT /api/settings/file-upload/sftp` takes.
 *
 * **Omit `password`/`key_passphrase` to keep the stored one; send `""` to
 * clear it.** `key_path` is not write-only — always send the full value.
 */
export interface FileUploadSftpUpdate {
  host: string;
  port: number;
  username: string;
  password?: string;
  key_path: string;
  key_passphrase?: string;
  remote_root: string;
}

/** The body `PUT /api/settings/file-upload/ftps` takes — same `password` rule as SFTP. */
export interface FileUploadFtpsUpdate {
  host: string;
  port: number;
  username: string;
  password?: string;
  remote_root: string;
}

/** The body `PUT /api/settings/file-upload/https` takes — same rule for `token`. */
export interface FileUploadHttpsUpdate {
  url: string;
  token?: string;
  remote_root: string;
}

/** What `POST /api/load-profile/export` ("Save CSV now") did. */
export interface LoadProfileExportResult {
  rows_written: number;
  /** The resolved target CSV file path, or `null` when nothing was written. */
  path: string | null;
}

/**
 * What "Save billing file now" did (M13, issue 01) — the same shape
 * `LoadProfileExportResult` has, because two export files an operator drives
 * the same way should not report what they did in two different shapes.
 */
export interface EnergyExportResult {
  /** Local days written. Zero means the range holds no stored readings — normal, not an error. */
  rows_written: number;
  /** The resolved target file path, or `null` when nothing was written. */
  path: string | null;
}

export interface BillingExportResult {
  /**
   * Closed periods the file now holds — every call rewrites the whole file
   * from every closed period (ADR 0023). Zero means nothing to write, a
   * hold, or a failure.
   */
  rows_written: number;
  /** The resolved target file path, or `null` when nothing was written. */
  path: string | null;
}

/** How many meters this machine has and may have, from `GET /api/devices/quota`. */
export interface Quota {
  used: number;
  /** Null means unlimited. */
  max_meters: number | null;
  /** True when an existing set exceeds a newly reduced limit. */
  over_quota: boolean;
}

/** What Test connection learned. Always arrives on a 200 — the verdict is in here. */
export interface TestConnectionResult {
  reachable: boolean;
  meter_serial: string | null;
  reason: string | null;
  message: string;
}

/** What one job of a Read now did. `detail` is a sentence, never a measured value. */
export interface ReadNowJobResult {
  job: string;
  ok: boolean;
  detail: string;
}

/**
 * What a Read now produced — a **list**, because M5 adds `load_profile` and M6
 * adds `billing`, and a multi-job read can be partially successful.
 */
export interface ReadNowResult {
  results: ReadNowJobResult[];
  status: DeviceStatus;
  checked_at: string | null;
}

/**
 * One selectable meter model, from `GET /api/devices/catalog`.
 *
 * Only models that resolve to a real driver are listed, so the dropdown can
 * never offer something that will fail to connect. `fixed_password` is a
 * documented brand-wide default the form prefills, not a per-site secret.
 *
 * **Carries no transport information** (issue #9) — every catalogued model
 * is offered both transports; the operator picks per device on the form's
 * own Transport switch.
 */
export interface CatalogEntry {
  model: string;
  /** The catalog key — the stored value and the one to compare with. */
  brand: string;
  /** What to show for the brand; never compare with it. */
  brand_label: string;
  ui_label: string;
  fixed_password: string | null;
  supports_battery: boolean;
  supports_energy_summary: boolean;
  supports_special_days: boolean;
}

/**
 * The body `POST /api/devices` and `PUT /api/devices/{id}` take.
 *
 * `meter_serial` is deliberately absent: it is read off the meter, never
 * submitted (ADR 0005). Omitting `password` on an update **keeps the stored
 * one** — the API never returns a secret, so a blank field cannot mean "clear
 * it". The two cipher keys are omitted entirely at M3: their inputs land with
 * M4's key-authenticated models, and an absent secret is a kept secret.
 */
export interface DeviceInput {
  name: string;
  brand: string;
  model: string;
  /** Required — the Devices tree groups by it (SPEC §3.3). */
  site_name: string;
  /** `net` or `serial` (issue #9) — the operator's Transport switch. */
  transport: Transport;
  password?: string;
  /**
   * Signed by the vendor for this Meter Serial and this Machine ID (ADR
   * 0019, issue #42). Required on create; omitted on an edit — Update never
   * re-checks it (`_reject_changed_serial` already refuses any probed-serial
   * change, unconditionally).
   */
  meter_activation_code?: string;
  site_code?: string | null;
  customer?: string | null;
  meter_number?: string | null;
  group_name?: string | null;
  /** `YYYY-MM-DD`. Stored only — the period logic is M6. */
  first_bill_date?: string | null;
  bill_day_feb28?: number | null;
  bill_day_feb29?: number | null;
  bill_day_30?: number | null;
  bill_day_31?: number | null;
}

/** The transport values `POST /api/devices/test-connection` tries. */
export interface TestConnectionInput {
  model: string;
  transport: Transport;
  password: string;
}

export interface SetupStatus {
  setup_required: boolean;
}

export interface User {
  id: number;
  username: string;
  role: "admin" | "user";
  created_at: string;
}

export interface LoginResult {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Credentials {
  username: string;
  password: string;
}

/** Request body for `POST /api/users`. The role is required — there is no default. */
export interface NewUser {
  username: string;
  password: string;
  role: "admin" | "user";
}

/** Raised when a request fails; carries the API's own error code when present. */
export class ApiRequestError extends Error {
  constructor(
    message: string,
    readonly code: string | null = null,
    readonly reason: string | null = null,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

/**
 * True when a call failed because this machine's license lapsed.
 *
 * Every page checks this **first** in its catch and reloads: `/api/devices` and
 * `/api/users` are not on the Limited Mode allow-list, so a lease that ran out
 * while the page was open kills every call on it. Reloading drops the app back
 * to the Activation page, which is the only screen that can fix the machine —
 * swallowing it into a toast would leave the operator staring at a dead page.
 */
export function isLicenseLapsed(err: unknown): boolean {
  return err instanceof ApiRequestError && err.code === "LICENSE_INVALID";
}

/**
 * Turn a FastAPI error body's `detail` into something a person can act on.
 *
 * A 422 carries `detail` as an **array** of validation errors, one object per
 * offending field. `String(...)` on that array yields
 * `[object Object],[object Object]` — which tells the operator nothing at all,
 * and is exactly what a rule the form does not mirror (a name over 128
 * characters, say) would have shown them. Each entry becomes `<loc>: <msg>`,
 * one per line. A plain string `detail` — what every deliberate
 * `HTTPException` in this backend raises — passes straight through.
 */
function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return String(detail);

  return detail
    .map((entry: unknown) => {
      if (entry === null || typeof entry !== "object") return String(entry);
      const { loc, msg } = entry as { loc?: unknown; msg?: unknown };
      const where = Array.isArray(loc) ? loc.map(String).join(" > ") : "";
      const what = typeof msg === "string" ? msg : JSON.stringify(entry);
      return where ? `${where}: ${what}` : what;
    })
    .join("\n");
}

/**
 * Fetch a binary capture and trigger a browser save (M6b issue #22; shared
 * by every capture download since M7 slice 4, issue #35).
 *
 * A separate helper from `request<T>()` because that one always parses the
 * response as JSON — a capture download is a binary body. Errors still come
 * back as the `{success, data, error}` envelope, so this parses that shape
 * on a non-OK response the same way `request()` does, just without the
 * "always JSON" assumption on the success path.
 */
async function downloadBinary(url: string, fallbackFilename: string): Promise<Headers> {
  const session = getSession();
  const response = await fetch(url, {
    headers: session ? { Authorization: `Bearer ${session.token}` } : {},
  });

  if (response.status === 401 && session) {
    clearSession();
  }

  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    let code: string | null = null;
    let reason: string | null = null;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "error" in body) {
        const error = (body as ApiResponse<unknown>).error;
        if (error) {
          message = error.message;
          code = error.code;
          reason = error.reason;
        }
      }
    } catch {
      // A non-JSON error body — fall through to the status-based message.
    }
    throw new ApiRequestError(message, code, reason);
  }

  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  const filename = match ? match[1] : fallbackFilename;

  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(objectUrl);
  return response.headers;
}

/**
 * Download the per-period PDF/xlsx capture (M6b, issue #22).
 *
 * Kept as its own exported function — even though the Billing page dropped
 * its per-row Capture column in favour of the one Billing History image
 * button (M7 slice 4, issue #35, D12) and nothing in `web/` calls this any
 * more — because the backend endpoint it wraps
 * (`GET /api/billing/captures/{reading_id}`) is unchanged and still a
 * documented part of the API surface.
 */
export async function downloadBillingCapture(readingId: number, format: "pdf" | "xlsx"): Promise<void> {
  await downloadBinary(`/api/billing/captures/${readingId}?format=${format}`, `capture.${format}`);
}

/**
 * Download the Billing History image for one device — the ten most recent
 * closed periods, a headless screenshot of this page itself (M7 slice 4,
 * issue #35; issue #38, ADR 0017/0015). Device-keyed, not reading-keyed:
 * there is no per-row id to pass, only the device the operator has selected.
 */
/**
 * Resolves to the instant the served capture was written (`X-Captured-At`,
 * ISO 8601 with offset) so the toast can name the same time the All-Meters
 * row shows (ui-audit ticket 03) — or null for a file the server holds no
 * stamp for.
 */
export async function downloadBillingImage(deviceId: number): Promise<string | null> {
  const headers = await downloadBinary(`/api/billing/captures/image?device_id=${deviceId}`, "capture.png");
  return headers.get("x-captured-at");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const session = getSession();
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(session ? { Authorization: `Bearer ${session.token}` } : {}),
      ...init?.headers,
    },
  });

  // A 401 on a request that *carried* a token means that token is no longer
  // good — expired, revoked, or issued under a since-rotated signing secret —
  // so drop the session and let the app fall back to Login. A 401 on a request
  // that carried no token is just the Login form being told the password was
  // wrong; clearing there would turn a typo into a "session expired" loop.
  if (response.status === 401 && session) {
    clearSession();
  }

  let body: ApiResponse<T> | { detail?: unknown } | null = null;
  try {
    body = await response.json();
  } catch {
    // A non-JSON body (a proxy error page, say) — fall through to the status.
  }

  if (body && "success" in body) {
    if (body.success) {
      return body.data as T;
    }
    throw new ApiRequestError(
      body.error?.message ?? "Request failed",
      body.error?.code ?? null,
      body.error?.reason ?? null,
    );
  }

  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body ? formatDetail(body.detail) : response.statusText;
    throw new ApiRequestError(detail || `HTTP ${response.status}`);
  }

  throw new ApiRequestError("Unexpected response shape from the API");
}

/**
 * What a Holiday change did (ADR 0022, M14 ticket 04).
 *
 * Used to carry `affected_date`/`energy_files_written_past` (M13, issue 03),
 * so the page could warn which daily energy files had fallen behind a
 * Holiday entered after the fact. Since ADR 0022/0023 the Energy Summary is
 * stored and recomputed every cycle and the Energy file is rewritten from it
 * every cycle too, so neither can be stale by more than one cycle — there is
 * nothing left to compute or warn about.
 */
export interface HolidayMutation {
  /** The row as it now stands, or `null` for a delete. */
  holiday: Holiday | null;
}

export const api = {
  checkSetup: () => request<SetupStatus>("/api/auth/check-setup"),

  setup: (credentials: Credentials) =>
    request<User>("/api/auth/setup", {
      method: "POST",
      body: JSON.stringify(credentials),
    }),

  login: (credentials: Credentials) =>
    request<LoginResult>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(credentials),
    }),

  logout: () => request<boolean>("/api/auth/logout", { method: "POST" }),

  me: () => request<User>("/api/auth/me"),

  // Changing your own password lives on /api/auth, not /api/users: it is the
  // one non-admin endpoint of User Management, and /api/auth stays reachable in
  // Limited Mode. A wrong current password comes back 400, so the request
  // helper above leaves the session alone.
  changeOwnPassword: (currentPassword: string, newPassword: string) =>
    request<boolean>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),

  licenseStatus: () => request<LicenseStatus>("/api/license/status"),

  activate: (code: string) =>
    request<LicenseStatus>("/api/license/activate", {
      method: "POST",
      body: JSON.stringify({ code }),
    }),

  listDevices: () => request<Device[]>("/api/devices"),

  catalog: () => request<CatalogEntry[]>("/api/devices/catalog"),

  quota: () => request<Quota>("/api/devices/quota"),

  createDevice: (device: DeviceInput) =>
    request<Device>("/api/devices", {
      method: "POST",
      body: JSON.stringify(device),
    }),

  updateDevice: (id: number, device: DeviceInput) =>
    request<Device>(`/api/devices/${id}`, {
      method: "PUT",
      body: JSON.stringify(device),
    }),

  deleteDevice: (id: number) => request<boolean>(`/api/devices/${id}`, { method: "DELETE" }),

  testConnection: (input: TestConnectionInput) =>
    request<TestConnectionResult>("/api/devices/test-connection", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  pauseDevice: (id: number) => request<Device>(`/api/devices/${id}/pause`, { method: "POST" }),

  resumeDevice: (id: number) => request<Device>(`/api/devices/${id}/resume`, { method: "POST" }),

  readNow: (id: number) => request<ReadNowResult>(`/api/devices/${id}/read-now`, { method: "POST" }),

  deviceEvents: (id: number, limit: number, offset: number) =>
    request<DeviceEventPage>(`/api/devices/${id}/events?limit=${limit}&offset=${offset}`),

  /**
   * One page of a device's stored Interval Readings.
   *
   * The range is **half-open**: `startIso` is included, `endIso` is *excluded*,
   * so a whole day is `[day 00:00, next day 00:00)` with nothing to round. Both
   * are required, and `end <= start` is refused with 422.
   */
  loadProfile: (deviceId: number, startIso: string, endIso: string, limit: number, offset: number) =>
    request<LoadProfilePage>(
      `/api/load-profile?device_id=${deviceId}&start=${encodeURIComponent(startIso)}&end=${encodeURIComponent(endIso)}&limit=${limit}&offset=${offset}`,
    ),

  /**
   * One page of Billing Readings, either tab.
   *
   * Unlike `loadProfile` above, `deviceId` and the range are **optional** —
   * billing's row volume never justifies forcing either (SPEC §3.6). The
   * range, when given, is half-open on `bill_date`: `startIso` included,
   * `endIso` excluded.
   *
   * `meterSerial` (ADR 0017, issue #38, decision 7) restricts to one
   * `meter_serial` — used only by the headless-screenshot renderer's seeded
   * capture request; a human never sets this.
   */
  billing: (
    billingStatus: BillingStatus,
    deviceId: number | undefined,
    startIso: string | undefined,
    endIso: string | undefined,
    limit: number,
    offset: number,
    meterSerial?: string,
  ) => {
    const params = new URLSearchParams({ status: billingStatus, limit: String(limit), offset: String(offset) });
    if (deviceId !== undefined) params.set("device_id", String(deviceId));
    if (startIso !== undefined) params.set("start", startIso);
    if (endIso !== undefined) params.set("end", endIso);
    if (meterSerial !== undefined) params.set("meter_serial", meterSerial);
    return request<BillingPage>(`/api/billing?${params.toString()}`);
  },

  /**
   * The All-Meters View — every meter's latest closed period, one row each
   * (issue 01). Any authenticated role, gated by the billing entitlement.
   *
   * No parameters at all: no device, no range, no paging. The tab is every
   * device and the latest period, and it is bounded by device count.
   */
  billingAllMeters: () => request<AllMetersView>("/api/billing/all-meters"),

  /** The current `capture_dir` and how many closed periods exist (M6b, issue #22). */
  billingSettings: () => request<BillingSettings>("/api/billing/settings"),

  /**
   * Read one device's whole billing buffer now, through the Manual Read
   * lock (issue #44, ADR 0009 — one round trip). Any authenticated role. A
   * meter failure comes back as `{error: "…"}` on a 200, same as Test
   * Connection.
   */
  readBillingNow: (deviceId: number) =>
    request<BillingReadNowResult>(`/api/billing/read?device_id=${deviceId}`, { method: "POST" }),

  /**
   * "Save billing file now" — rewrite one device's whole billing file from
   * every closed period it has (ADR 0023), ignoring `export_auto_save_enabled`
   * the way "Save CSV now" does. Any authenticated role. `422` when
   * `export_output_dir` is not configured, which is what makes this the check
   * an installer uses to prove the folder is right without waiting a cycle.
   */
  exportBillingNow: (deviceId: number) =>
    request<BillingExportResult>(`/api/billing/export?device_id=${deviceId}`, { method: "POST" }),

  /**
   * Save the Energy Summary for one device and range to a file (M13, issue 02).
   * This is the corrective for a stale daily file — the archive records what
   * was true the night it was written, and a Holiday entered later changes
   * what those days should say. Any authenticated role. `422` when
   * `export_output_dir` is not configured or the range is too wide.
   */
  exportEnergySummary: (deviceId: number, startDate: string, endDate: string) =>
    request<EnergyExportResult>(
      `/api/energy/export?device_id=${deviceId}&start_date=${startDate}&end_date=${endDate}`,
      { method: "POST" },
    ),

  /**
   * Save `capture_dir` — admin-only. An empty string disables capture; a
   * non-empty value is validated server-side (ADR 0010) and a rejection
   * comes back as a 422 the caller renders via `ApiRequestError.message`.
   */
  updateBillingSettings: (captureDir: string) =>
    request<BillingSettings>("/api/billing/settings", {
      method: "PUT",
      body: JSON.stringify({ capture_dir: captureDir }),
    }),

  /**
   * The completeness grid over a range of local calendar dates.
   *
   * The dates are plain `YYYY-MM-DD` and **both ends are inclusive** — unlike
   * `loadProfile` above, whose range is half-open. A date axis is discrete, so
   * there is nothing to round, and a missing last column would be a surprise.
   * The server refuses a range longer than 31 days with 422.
   *
   * `utcOffsetMinutes` is the minutes to **add to UTC** to reach the caller's
   * local time (ICT is 420), which is what decides which column a reading falls
   * in.
   */
  records: (startDate: string, endDate: string, utcOffsetMinutes: number) =>
    request<RecordsGrid>(
      `/api/records?start_date=${startDate}&end_date=${endDate}&utc_offset_minutes=${utcOffsetMinutes}`,
    ),

  clearReadings: (id: number, confirmName: string) =>
    request<number>(`/api/devices/${id}/readings/clear`, {
      method: "POST",
      body: JSON.stringify({ confirm_name: confirmName }),
    }),

  listUsers: () => request<User[]>("/api/users"),

  createUser: (user: NewUser) =>
    request<User>("/api/users", {
      method: "POST",
      body: JSON.stringify(user),
    }),

  setUserRole: (id: number, role: "admin" | "user") =>
    request<User>(`/api/users/${id}/role`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    }),

  resetUserPassword: (id: number, newPassword: string) =>
    request<boolean>(`/api/users/${id}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ new_password: newPassword }),
    }),

  deleteUser: (id: number) => request<boolean>(`/api/users/${id}`, { method: "DELETE" }),

  /** The current `display_unit_scale` — any authenticated caller. */
  displaySettings: () => request<DisplaySettings>("/api/settings/display"),

  /** Save `display_unit_scale` — admin-only. */
  updateDisplaySettings: (scale: DisplayUnitScale) =>
    request<DisplaySettings>("/api/settings/display", {
      method: "PUT",
      body: JSON.stringify({ display_unit_scale: scale }),
    }),

  /** The current Export Format settings — any authenticated caller. */
  exportFormatSettings: () => request<ExportFormatSettings>("/api/settings/export-format"),

  /**
   * Save all four Export Format settings — admin-only, a full replace. The
   * caller must pass every field, not just the one it owns (D-16) — build
   * the body from the last-fetched `ExportFormatSettings`, overriding only
   * what changed.
   */
  updateExportFormatSettings: (settings: ExportFormatSettings) =>
    request<ExportFormatSettings>("/api/settings/export-format", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),

  /**
   * The Database Destination settings plus the last cycle's status — any
   * authenticated caller. Never carries the password.
   */
  databaseDestinationSettings: () =>
    request<DatabaseDestinationSettings>("/api/settings/database-destination"),

  /**
   * Save the Database Destination settings — admin-only. **Include
   * `password` only when the field was actually edited**: omitting it keeps
   * the stored one, while sending `""` deliberately stores an empty password.
   */
  updateDatabaseDestinationSettings: (settings: DatabaseDestinationUpdate) =>
    request<DatabaseDestinationSettings>("/api/settings/database-destination", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),

  /**
   * Test the connection with the **stored** settings — admin-only, no body.
   * Every outcome comes back on a 200 with a `result`; a failure here is not
   * an HTTP error, so it never reaches the page's generic error surface.
   */
  testDatabaseDestination: () =>
    request<DatabaseDestinationTest>("/api/settings/database-destination/test", { method: "POST" }),

  /**
   * The Central Push configuration and the last cycle's status — admin-only
   * (ADR 0024, ticket 07): unlike the settings above, even reading this is
   * gated, because the URL and whether a token is set are machine-internal.
   */
  centralPushSettings: () => request<CentralPushSettings>("/api/settings/central-push"),

  /**
   * Save the Central Push configuration — admin-only. A non-empty `token` is
   * verified on the spot; a rejected token changes nothing and the promise
   * rejects with an `ApiRequestError` whose `reason` names the failed check.
   */
  updateCentralPushSettings: (settings: CentralPushUpdate) =>
    request<CentralPushSettings>("/api/settings/central-push", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),

  /** The last Central Push cycle's status alone — admin-only. */
  centralPushStatus: () => request<CentralPushCycleStatus | null>("/api/settings/central-push/status"),

  /** The published Central Push contract — admin-only. */
  centralPushContract: () => request<CentralPushContract>("/api/settings/central-push/contract"),

  /**
   * The File Upload Destination's three tabs and the last cycle's status —
   * admin-only (ADR 0025, ticket 01), the same reasoning Central Push's own
   * `GET` uses: the settings are machine-internal configuration.
   */
  fileUploadSettings: () => request<FileUploadSettings>("/api/settings/file-upload"),

  /** Save the SFTP tab and make it the active protocol — admin-only. */
  updateFileUploadSftp: (settings: FileUploadSftpUpdate) =>
    request<FileUploadSettings>("/api/settings/file-upload/sftp", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),

  /** Save the FTPS tab and make it the active protocol — admin-only. */
  updateFileUploadFtps: (settings: FileUploadFtpsUpdate) =>
    request<FileUploadSettings>("/api/settings/file-upload/ftps", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),

  /** Save the HTTPS tab and make it the active protocol — admin-only. */
  updateFileUploadHttps: (settings: FileUploadHttpsUpdate) =>
    request<FileUploadSettings>("/api/settings/file-upload/https", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),

  /**
   * "Upload now" (ADR 0025, ticket 02) — run one File Upload Destination
   * cycle immediately. Admin-only. Waits for the cycle to finish (bounded
   * by the cycle's own time budget), so this can take a while — the caller
   * should show a loading state. `result.finished` tells the caller
   * whether the wait actually caught the cycle finishing, or timed out.
   */
  uploadFileUploadNow: () =>
    request<FileUploadUploadNowResult>("/api/settings/file-upload/upload-now", { method: "POST" }),


  /**
   * "Save CSV now" — export one device's pending Interval Readings at once,
   * ignoring `export_auto_save_enabled`. Any authenticated role. `422` when
   * `export_output_dir` is not configured.
   */
  exportLoadProfileNow: (deviceId: number) =>
    request<LoadProfileExportResult>(`/api/load-profile/export?device_id=${deviceId}`, { method: "POST" }),

  /**
   * Read one device's load profile now, through the Manual Read lock (issue
   * #44). Any authenticated role. `422`/`404` never happen for a normal
   * press — a `404` means the device or its driver's load profile is gone;
   * a meter failure comes back as `{error: "…"}` on a 200, same as Test
   * Connection.
   */
  readLoadProfileNow: (deviceId: number) =>
    request<LoadProfileReadNowResult>(`/api/load-profile/read?device_id=${deviceId}`, { method: "POST" }),

  /**
   * The Time-of-Use daily totals for one device (M7-1, issue #28). Both
   * dates are local, inclusive, `YYYY-MM-DD` — the server refuses a range
   * over 31 days with 422, the same bound `records()` uses.
   */
  energySummary: (deviceId: number, startDate: string, endDate: string) =>
    request<EnergySummaryReport>(
      `/api/energy/summary?device_id=${deviceId}&start_date=${startDate}&end_date=${endDate}`,
    ),

  /** Every stored Energy Registers snapshot for one device, newest first. */
  energyRegisters: (deviceId: number) => request<EnergyRegisterRow[]>(`/api/energy/registers?device_id=${deviceId}`),

  /**
   * Read the meter's Energy Registers now, through the Manual Read lock.
   * A live-read failure comes back as `{row: null, error: "…"}`, not a
   * thrown error — the caller renders `result.error` the way Test
   * Connection's `message` is rendered.
   */
  readEnergyRegisters: (deviceId: number) =>
    request<EnergyRegisterReadResult>(`/api/energy/registers/read?device_id=${deviceId}`, { method: "POST" }),

  /** Every stored Holiday, machine-wide. Any authenticated role. */
  listHolidays: () => request<Holiday[]>("/api/holidays"),

  /** Add one Holiday — admin-only. */
  createHoliday: (input: HolidayInput) =>
    request<HolidayMutation>("/api/holidays", { method: "POST", body: JSON.stringify(input) }),

  /** Replace one Holiday's fields in place — admin-only. */
  updateHoliday: (id: number, input: HolidayInput) =>
    request<HolidayMutation>(`/api/holidays/${id}`, { method: "PATCH", body: JSON.stringify(input) }),

  /** Remove one Holiday — admin-only. Removing one changes an already-written day as much as adding one. */
  deleteHoliday: (id: number) => request<HolidayMutation>(`/api/holidays/${id}`, { method: "DELETE" }),

  /** The whole calendar as the JSON document (decision 14) — the caller
   * saves this as a Blob download. */
  exportHolidays: () => request<HolidayDocument>("/api/holidays/export"),

  /** Replace the whole calendar with *document* — admin-only. Refuses (422)
   * a document with a duplicate key or a 29-February annual entry. */
  importHolidays: (document: HolidayDocument) =>
    request<Holiday[]>("/api/holidays/import", { method: "POST", body: JSON.stringify(document) }),

  /** Replace the whole calendar with one device's Special Days Table —
   * admin-only. */
  importHolidaysFromMeter: (deviceId: number) =>
    request<HolidayImportFromMeterResult>(`/api/holidays/import-from-meter?device_id=${deviceId}`, {
      method: "POST",
    }),

  /** Read one device's Special Days Table now, read-through — nothing is stored. */
  specialDays: (deviceId: number) => request<SpecialDaysReadResult>(`/api/special-days?device_id=${deviceId}`),

  /** One page of the Holiday Change record, newest first (ADR 0022, M14
   * ticket 06) — server-paginated like {@link api.deviceEvents}. Any
   * authenticated role. */
  listHolidayChanges: (limit: number, offset: number) =>
    request<HolidayChangePage>(`/api/holidays/changes?limit=${limit}&offset=${offset}`),

  /**
   * One page of stored Battery Readings (M7-2, issue #29), newest
   * `read_at` first. `deviceId` and the range are optional — mirrors
   * `billing()`'s own optional filters, half-open on `read_at`: `startIso`
   * included, `endIso` excluded. There is no Read-now variant — battery is
   * background-only (D5).
   */
  battery: (
    deviceId: number | undefined,
    startIso: string | undefined,
    endIso: string | undefined,
    limit: number,
    offset: number,
  ) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (deviceId !== undefined) params.set("device_id", String(deviceId));
    if (startIso !== undefined) params.set("start", startIso);
    if (endIso !== undefined) params.set("end", endIso);
    return request<BatteryPage>(`/api/battery?${params.toString()}`);
  },

  /**
   * The tail of the application log (M7-4, issue #31), newest last.
   * `minLevel` omitted entirely when unset — the endpoint's own default is
   * "no filtering".
   */
  logs: (lines: number, minLevel?: string) => {
    const params = new URLSearchParams({ lines: String(lines) });
    if (minLevel !== undefined) params.set("min_level", minLevel);
    return request<LogTail>(`/api/logs?${params.toString()}`);
  },
};
