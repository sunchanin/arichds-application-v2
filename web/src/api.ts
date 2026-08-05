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
      body && typeof body === "object" && "detail" in body ? String(body.detail) : response.statusText;
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

  supportedModels: () => request<string[]>("/api/devices/models"),

  createDevice: (device: NewDevice) =>
    request<Device>("/api/devices", {
      method: "POST",
      body: JSON.stringify(device),
    }),

  deleteDevice: (id: number) => request<boolean>(`/api/devices/${id}`, { method: "DELETE" }),

  latestReading: (id: number) => request<Reading | null>(`/api/devices/${id}/readings/latest`),

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
