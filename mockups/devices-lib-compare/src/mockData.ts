// Shared mock data + domain helpers for the Devices page, used identically by
// both library variants (mantine / shadcn) so the comparison is apples-to-apples.
//
// This module mirrors v1's actual data shapes (read-only reference:
// cewe-fe/src/types/device.ts, src/types/meterCatalog.ts,
// src/utils/nextBillingCutDate.ts, src/pages/Devices/index.tsx) closely enough
// that the two variants can replicate v1's real page layout field-for-field.
// There is no backend here, so quota/catalog/status are static mock data
// rather than fetched — see README "Assumptions" for what was simplified.

// ─── Catalog (mirrors MeterCatalogModel / MeterCatalogBrand) ───────────────

export type Brand = "CEWE" | "Mitsubishi" | "SMART TCC";
export const BRANDS: Brand[] = ["CEWE", "Mitsubishi", "SMART TCC"];

export type ModelKey =
  | "prometer100"
  | "saral305"
  | "premier550"
  | "smw110"
  | "st3c"
  | "st3cl"
  | "st33tl"
  | "st3tl"
  | "st3dh";

export type DriverStatus = "ready" | "pending_spec";
export type Protocol = "dlms" | "modbus";

export interface CatalogModel {
  model: ModelKey;
  brand: Brand;
  uiLabel: string;
  defaultPort: number | null;
  protocol: Protocol;
  supportsSerial: boolean;
  driverStatus: DriverStatus;
  // Vendor-documented brand default password, prefilled on model select.
  // null = key-based model (SMART TCC) — the Password field is hidden entirely.
  fixedPassword: string | null;
}

export const CATALOG_MODELS: CatalogModel[] = [
  { model: "prometer100", brand: "CEWE", uiLabel: "ProMeter 100", defaultPort: 4059, protocol: "dlms", supportsSerial: false, driverStatus: "ready", fixedPassword: "ABCD0001" },
  { model: "saral305", brand: "CEWE", uiLabel: "Saral 305", defaultPort: 4059, protocol: "dlms", supportsSerial: true, driverStatus: "ready", fixedPassword: "ABCD0001" },
  { model: "premier550", brand: "CEWE", uiLabel: "Premier 550", defaultPort: 4059, protocol: "dlms", supportsSerial: false, driverStatus: "ready", fixedPassword: "ABCD0001" },
  { model: "smw110", brand: "Mitsubishi", uiLabel: "SMW-110", defaultPort: 4059, protocol: "dlms", supportsSerial: true, driverStatus: "ready", fixedPassword: "00000000" },
  { model: "st3c", brand: "SMART TCC", uiLabel: "ST3C", defaultPort: 502, protocol: "modbus", supportsSerial: false, driverStatus: "ready", fixedPassword: null },
  { model: "st3cl", brand: "SMART TCC", uiLabel: "ST3CL", defaultPort: 502, protocol: "modbus", supportsSerial: false, driverStatus: "ready", fixedPassword: null },
  { model: "st33tl", brand: "SMART TCC", uiLabel: "ST33TL", defaultPort: 502, protocol: "modbus", supportsSerial: false, driverStatus: "ready", fixedPassword: null },
  { model: "st3tl", brand: "SMART TCC", uiLabel: "ST3TL", defaultPort: 502, protocol: "modbus", supportsSerial: false, driverStatus: "ready", fixedPassword: null },
  // Marked pending_spec deliberately (assumption, see README): demonstrates
  // v1's disabled + "(coming soon)" model-select option, even though one
  // existing seed device already uses it (a driver can go from ready back to
  // "under re-certification" without existing installs being torn out).
  { model: "st3dh", brand: "SMART TCC", uiLabel: "ST3DH", defaultPort: 502, protocol: "modbus", supportsSerial: false, driverStatus: "pending_spec", fixedPassword: null },
];

export const modelsForBrand = (brand: Brand): CatalogModel[] =>
  CATALOG_MODELS.filter((m) => m.brand === brand);

export const catalogFor = (model: ModelKey): CatalogModel =>
  CATALOG_MODELS.find((m) => m.model === model)!;

// Flat "type filter" options (v1: typeFilterOptions) — every model across every
// brand, labelled by ui_label, independent of the brand→model cascade used in
// the Add/Edit form's Meter section.
export const TYPE_FILTER_OPTIONS = [
  { value: "all", label: "All Types" },
  ...CATALOG_MODELS.map((m) => ({ value: m.model, label: m.uiLabel })),
];

// ─── Serial line-format option sets (mirrors ALLOWED_* in v1 types/device.ts) ───

export const ALLOWED_BAUD_RATES = [300, 600, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200] as const;
export const ALLOWED_DATA_BITS = [7, 8] as const;
export const ALLOWED_PARITY = ["None", "Odd", "Even", "Mark", "Space"] as const;
export const ALLOWED_STOP_BITS = ["One", "OnePointFive", "Two"] as const;
export const ALLOWED_FLOW_CONTROL = ["None", "XOnXOff", "RequestToSend", "RequestToSendXOnXOff"] as const;

export const DEFAULT_DATA_BITS = 8;
export const DEFAULT_PARITY = "None";
export const DEFAULT_STOP_BITS = "One";
export const DEFAULT_FLOW_CONTROL = "None";

// Per-model serial baud default (v1: MODEL_DEFAULT_BAUD) — only smw110 runs
// serial in the field today, at 19200; everything else falls back to 9600.
const MODEL_DEFAULT_BAUD: Partial<Record<ModelKey, number>> = { smw110: 19200 };
export const defaultBaudFor = (model?: ModelKey): number =>
  (model ? MODEL_DEFAULT_BAUD[model] : undefined) ?? 9600;

// ─── Device (mirrors DevicePublic + DeviceTreeItem) ────────────────────────

export type ConnectionStatus = "Online" | "Offline" | "Connecting" | "Error";
export type Source = "dlms" | "modbus";
export type ConnectionType = "net" | "serial";

export interface Device {
  id: number;
  name: string;
  siteName: string;
  siteCode?: string;
  customer?: string;
  meterNumber?: string;
  meterSerial?: string; // auto-assigned, read-only, absent until first read
  brand: Brand;
  model: ModelKey;

  source: Source;
  slaveAddr?: number | null; // modbus only
  connectionType?: ConnectionType; // dlms only
  ip?: string; // dlms + net only
  port?: number; // dlms + net only
  serialPort?: string; // dlms + serial only
  baudRate?: number; // dlms + serial only
  dataBits?: number; // dlms + serial only
  parity?: string; // dlms + serial only
  stopBits?: string; // dlms + serial only
  flowControl?: string; // dlms + serial only
  password?: string; // dlms only, absent for keyless models

  firstBillDate?: string | null; // ISO date (YYYY-MM-DD)
  billDayFeb28?: number | null;
  billDayFeb29?: number | null;
  billDay30?: number | null;
  billDay31?: number | null;

  status: ConnectionStatus;
  detail?: string; // populated when status === "Error"
  pollingPaused: boolean; // persistent operator Disconnect, dlms-only in the UI
  latencyMs?: number | null;
  lastSeenAt: string; // ISO datetime
}

const iso = (daysAgo: number, hours = 0, minutes = 0): string => {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  d.setHours(d.getHours() - hours, d.getMinutes() - minutes, 0, 0);
  return d.toISOString();
};

export const DEVICES: Device[] = [
  // Substation A — 2 devices, both CEWE/dlms/net
  {
    id: 1,
    name: "Feeder 1",
    siteName: "Substation A",
    siteCode: "STA-A",
    customer: "Bangkok Grid Co.",
    meterNumber: "MTR-10021",
    meterSerial: "SN-84213",
    brand: "CEWE",
    model: "prometer100",
    source: "dlms",
    connectionType: "net",
    ip: "192.168.1.10",
    port: 4059,
    password: "ABCD0001",
    firstBillDate: "2024-06-01",
    billDayFeb28: 5,
    billDayFeb29: 5,
    billDay30: 5,
    billDay31: 5,
    status: "Online",
    pollingPaused: false,
    latencyMs: 62,
    lastSeenAt: iso(0, 0, 2),
  },
  {
    id: 2,
    name: "Feeder 2",
    siteName: "Substation A",
    siteCode: "STA-A",
    customer: "Bangkok Grid Co.",
    brand: "CEWE",
    model: "saral305",
    source: "dlms",
    connectionType: "net",
    ip: "192.168.1.11",
    port: 4059,
    password: "ABCD0001",
    status: "Connecting",
    pollingPaused: false,
    latencyMs: null,
    lastSeenAt: iso(0, 0, 5),
  },
  // Rooftop PV — 1 device, Mitsubishi/dlms/serial
  {
    id: 3,
    name: "PV Meter",
    siteName: "Rooftop PV",
    meterSerial: "SN-11940",
    brand: "Mitsubishi",
    model: "smw110",
    source: "dlms",
    connectionType: "serial",
    serialPort: "COM3",
    baudRate: 19200,
    dataBits: 8,
    parity: "None",
    stopBits: "One",
    flowControl: "None",
    password: "00000000",
    status: "Online",
    pollingPaused: false,
    latencyMs: 140,
    lastSeenAt: iso(0, 0, 12),
  },
  // Warehouse — 1 modbus (inert) + 1 dlms/serial (paused)
  {
    id: 4,
    name: "Main Incomer",
    siteName: "Warehouse",
    siteCode: "WH-1",
    brand: "SMART TCC",
    model: "st3c",
    source: "modbus",
    slaveAddr: 5,
    status: "Offline",
    pollingPaused: false,
    latencyMs: null,
    lastSeenAt: iso(2, 3, 0),
  },
  {
    id: 5,
    name: "Loading Dock Feeder",
    siteName: "Warehouse",
    siteCode: "WH-1",
    brand: "CEWE",
    model: "saral305",
    source: "dlms",
    connectionType: "serial",
    serialPort: "COM4",
    baudRate: 9600,
    dataBits: 8,
    parity: "None",
    stopBits: "One",
    flowControl: "None",
    password: "ABCD0001",
    status: "Offline",
    pollingPaused: true, // shows the "Disconnected" tag + disabled Disconnect button
    latencyMs: null,
    lastSeenAt: iso(4, 0, 0),
  },
  // Cold Storage Facility — 2 modbus (inert)
  {
    id: 6,
    name: "Unit 1",
    siteName: "Cold Storage Facility",
    brand: "SMART TCC",
    model: "st3cl",
    source: "modbus",
    slaveAddr: 2,
    status: "Online",
    pollingPaused: false,
    latencyMs: 45,
    lastSeenAt: iso(0, 1, 30),
  },
  {
    id: 7,
    name: "Unit 2",
    siteName: "Cold Storage Facility",
    brand: "SMART TCC",
    model: "st33tl",
    source: "modbus",
    slaveAddr: 3,
    status: "Error",
    detail: "Timeout waiting for meter response (3 retries).",
    pollingPaused: false,
    latencyMs: null,
    lastSeenAt: iso(0, 2, 0),
  },
  // Production Plant — 2 CEWE/dlms/net
  {
    id: 8,
    name: "Line 1",
    siteName: "Production Plant",
    customer: "Siam Textile PLC",
    meterNumber: "MTR-20044",
    meterSerial: "SN-77002",
    brand: "CEWE",
    model: "premier550",
    source: "dlms",
    connectionType: "net",
    ip: "192.168.1.30",
    port: 4059,
    password: "ABCD0001",
    status: "Online",
    pollingPaused: false,
    latencyMs: 58,
    lastSeenAt: iso(0, 0, 45),
  },
  {
    id: 9,
    name: "Line 2",
    siteName: "Production Plant",
    customer: "Siam Textile PLC",
    meterNumber: "MTR-20045",
    brand: "CEWE",
    model: "premier550",
    source: "dlms",
    connectionType: "net",
    ip: "192.168.1.31",
    port: 4059,
    password: "ABCD0001",
    status: "Offline",
    pollingPaused: false,
    latencyMs: null,
    lastSeenAt: iso(1, 6, 0),
  },
  // Office Building — 2 modbus (inert), one on the pending_spec model
  {
    id: 10,
    name: "Main Panel",
    siteName: "Office Building",
    brand: "SMART TCC",
    model: "st3tl",
    source: "modbus",
    slaveAddr: 1,
    status: "Online",
    pollingPaused: false,
    latencyMs: 33,
    lastSeenAt: iso(0, 0, 3),
  },
  {
    id: 11,
    name: "HVAC Sub-meter",
    siteName: "Office Building",
    brand: "SMART TCC",
    model: "st3dh", // pending_spec — still shown fine since it predates that flag
    source: "modbus",
    slaveAddr: 7,
    status: "Offline",
    pollingPaused: false,
    latencyMs: null,
    lastSeenAt: iso(3, 0, 0),
  },
  // Generator Room — 1 Mitsubishi/dlms/serial
  {
    id: 12,
    name: "Backup Generator Meter",
    siteName: "Generator Room",
    meterSerial: "SN-33170",
    brand: "Mitsubishi",
    model: "smw110",
    source: "dlms",
    connectionType: "serial",
    serialPort: "COM7",
    baudRate: 19200,
    dataBits: 8,
    parity: "None",
    stopBits: "One",
    flowControl: "None",
    password: "00000000",
    status: "Offline",
    pollingPaused: false,
    latencyMs: null,
    lastSeenAt: iso(10, 0, 0),
  },
];

// ─── Licensed meter-slot usage (mirrors MeterQuota) ────────────────────────

export interface Quota {
  used: number;
  maxMeters: number | null; // null = unlimited
  mode: "lease" | "offline";
}

// Static demo value — this mockup has no license backend. `mode: "lease"`
// is chosen deliberately so the Meter Key field (Identity section, add-only)
// has a reason to render; see README "Assumptions".
export const QUOTA: Quota = { used: DEVICES.length, maxMeters: null, mode: "lease" };

// ─── Tree grouping (mirrors DeviceTreeResponse / DeviceTreeGroup) ──────────

export interface SiteGroup {
  siteName: string;
  devices: Device[];
}

export const groupBySite = (devices: Device[]): SiteGroup[] => {
  const order: string[] = [];
  const map = new Map<string, Device[]>();
  for (const d of devices) {
    if (!map.has(d.siteName)) {
      map.set(d.siteName, []);
      order.push(d.siteName);
    }
    map.get(d.siteName)!.push(d);
  }
  return order.map((siteName) => ({ siteName, devices: map.get(siteName)! }));
};

// Tree row connection suffix — v1's DeviceTreeItem only ever carries ip/port
// (never serial info), so only net/TCP devices get a "- host:port" suffix;
// serial and modbus devices show their name alone.
export const treeConnectionSuffix = (d: Device): string =>
  d.connectionType === "net" && d.ip != null ? ` - ${d.ip}:${d.port}` : "";

// ─── Billing: next cut date (mirrors utils/nextBillingCutDate.ts) ──────────

export const resolveNextBillingCutDate = (
  device: Pick<Device, "billDayFeb28" | "billDayFeb29" | "billDay30" | "billDay31">,
  now: Date = new Date(),
): Date | null => {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  for (let i = 0; i <= 11; i++) {
    const monthStart = new Date(today.getFullYear(), today.getMonth() + i, 1);
    const daysInMonth = new Date(monthStart.getFullYear(), monthStart.getMonth() + 1, 0).getDate();

    let fieldValue: number | null | undefined;
    if (daysInMonth === 28) fieldValue = device.billDayFeb28;
    else if (daysInMonth === 29) fieldValue = device.billDayFeb29;
    else if (daysInMonth === 30) fieldValue = device.billDay30;
    else fieldValue = device.billDay31;

    if (fieldValue == null) continue;

    const day = Math.min(fieldValue, daysInMonth);
    const candidate = new Date(monthStart.getFullYear(), monthStart.getMonth(), day);
    if (candidate.getTime() > today.getTime()) return candidate;
  }
  return null;
};

// ─── Formatting helpers ─────────────────────────────────────────────────────

export const formatDateShort = (d: Date): string => {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
};

export const formatDateTime = (isoStr: string): string => new Date(isoStr).toLocaleString();

// Short relative-time formatter for "Last Seen" — no date library dependency
// so both variants stay on equal footing for this bit of text.
export const formatRelative = (isoStr: string): string => {
  const then = new Date(isoStr).getTime();
  const now = Date.now();
  const diffMs = now - then;
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
};
