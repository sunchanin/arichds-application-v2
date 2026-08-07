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
};
