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
}

/** One page of Interval Readings. `total` is the unpaged count the pager needs. */
export interface LoadProfilePage {
  items: LoadProfileRow[];
  total: number;
  limit: number;
  offset: number;
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

/** One page of Battery Readings. `total` is the unpaged count the pager needs. */
export interface BatteryPage {
  items: BatteryRow[];
  total: number;
  limit: number;
  offset: number;
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
 * **The CSV these govern is always kWh/kvarh** — it never follows
 * `display_unit_scale` (ADR 0013). `export_date_format` and
 * `export_csv_filename_tmpl` are owned by the ExportFormat page;
 * `export_auto_save_enabled` and `export_output_dir` are owned by the
 * matching controls on the Load Profile page (D-16) — one `PUT` replaces
 * all four, so either page's save must carry the other pair's current
 * values through unchanged.
 */
export interface ExportFormatSettings {
  /** An Excel-style token string, e.g. `"yyyy-mm-dd HH:MM:SS"` — `yyyy`/`mm`/`dd`/`HH`/`MM`/`SS`. */
  export_date_format: string;
  /** `[meter]`/`[serial]`/`[date]` filename tokens, e.g. `"[meter].csv"`. */
  export_csv_filename_tmpl: string;
  /** The scheduler job's own switch — "Save CSV now" ignores it. */
  export_auto_save_enabled: boolean;
  /** `""` means "not configured" — same convention as `capture_dir`. */
  export_output_dir: string;
}

/** What `POST /api/load-profile/export` ("Save CSV now") did. */
export interface LoadProfileExportResult {
  rows_written: number;
  /** The resolved target CSV file path, or `null` when nothing was written. */
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
  brand: string;
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
async function downloadBinary(url: string, fallbackFilename: string): Promise<void> {
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
  return downloadBinary(`/api/billing/captures/${readingId}?format=${format}`, `capture.${format}`);
}

/**
 * Download the Billing History image for one device — the ten most recent
 * closed periods, a headless screenshot of this page itself (M7 slice 4,
 * issue #35; issue #38, ADR 0017/0015). Device-keyed, not reading-keyed:
 * there is no per-row id to pass, only the device the operator has selected.
 */
export async function downloadBillingImage(deviceId: number): Promise<void> {
  return downloadBinary(`/api/billing/captures/image?device_id=${deviceId}`, "capture.png");
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

  /** The current `capture_dir` and how many closed periods exist (M6b, issue #22). */
  billingSettings: () => request<BillingSettings>("/api/billing/settings"),

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
   * "Save CSV now" — export one device's pending Interval Readings at once,
   * ignoring `export_auto_save_enabled`. Any authenticated role. `422` when
   * `export_output_dir` is not configured.
   */
  exportLoadProfileNow: (deviceId: number) =>
    request<LoadProfileExportResult>(`/api/load-profile/export?device_id=${deviceId}`, { method: "POST" }),

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
    request<Holiday>("/api/holidays", { method: "POST", body: JSON.stringify(input) }),

  /** Replace one Holiday's fields in place — admin-only. */
  updateHoliday: (id: number, input: HolidayInput) =>
    request<Holiday>(`/api/holidays/${id}`, { method: "PATCH", body: JSON.stringify(input) }),

  /** Remove one Holiday — admin-only. */
  deleteHoliday: (id: number) => request<boolean>(`/api/holidays/${id}`, { method: "DELETE" }),

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
