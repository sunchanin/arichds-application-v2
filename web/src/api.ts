/**
 * Thin client for the ARICHDS API.
 *
 * Every call is a same-origin relative URL: in production FastAPI serves both
 * the SPA and the API, and in development Vite proxies `/api` to the backend.
 * There is no base-URL configuration to get wrong.
 */

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

export interface Device {
  id: number;
  name: string;
  brand: string;
  model: string;
  host: string;
  port: number;
  endpoint: string;
  enabled: boolean;
  created_at: string;
}

export interface Reading {
  device_id: number;
  read_at: string;
  source: string;
  interval: string;
  volt_l1: number | null;
  volt_l2: number | null;
  volt_l3: number | null;
  current_l1: number | null;
  current_l2: number | null;
  current_l3: number | null;
  freq: number | null;
  import_active_kwh: number | null;
}

export interface NewDevice {
  name: string;
  brand: string;
  model: string;
  host: string;
  port: number;
  password: string;
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

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
      body && typeof body === "object" && "detail" in body ? String(body.detail) : response.statusText;
    throw new ApiRequestError(detail || `HTTP ${response.status}`);
  }

  throw new ApiRequestError("Unexpected response shape from the API");
}

export const api = {
  licenseStatus: () => request<LicenseStatus>("/api/license/status"),

  activate: (code: string) =>
    request<LicenseStatus>("/api/license/activate", {
      method: "POST",
      body: JSON.stringify({ code }),
    }),

  listDevices: () => request<Device[]>("/api/devices"),

  supportedModels: () => request<string[]>("/api/devices/models"),

  createDevice: (device: NewDevice) =>
    request<Device>("/api/devices", {
      method: "POST",
      body: JSON.stringify(device),
    }),

  deleteDevice: (id: number) => request<boolean>(`/api/devices/${id}`, { method: "DELETE" }),

  latestReading: (id: number) => request<Reading | null>(`/api/devices/${id}/readings/latest`),
};
