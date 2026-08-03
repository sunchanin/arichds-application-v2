import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Toaster, toast } from "sonner";
import {
  Search,
  Plus,
  Pencil,
  Copy,
  Settings,
  Pause,
  Play,
  Trash2,
  Eraser,
  RefreshCw,
  ShieldCheck,
  ChevronDown,
  ChevronRight,
  Folder,
  ArrowLeft,
} from "lucide-react";

import "./shadcn.css";
import { Button } from "./components/button";
import { Badge } from "./components/badge";
import { Input } from "./components/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./components/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "./components/dialog";
import { RadioGroup, RadioGroupItem } from "./components/radio-group";
import { DatePicker } from "./components/date-picker";
import {
  DEVICES,
  QUOTA,
  BRANDS,
  TYPE_FILTER_OPTIONS,
  ALLOWED_BAUD_RATES,
  ALLOWED_DATA_BITS,
  ALLOWED_PARITY,
  ALLOWED_STOP_BITS,
  ALLOWED_FLOW_CONTROL,
  DEFAULT_DATA_BITS,
  DEFAULT_PARITY,
  DEFAULT_STOP_BITS,
  DEFAULT_FLOW_CONTROL,
  modelsForBrand,
  catalogFor,
  defaultBaudFor,
  groupBySite,
  resolveNextBillingCutDate,
  formatDateShort,
  formatDateTime,
  type Device,
  type Brand,
  type ModelKey,
  type Source,
  type ConnectionType,
} from "../../mockData";

// ─── Status presentation ────────────────────────────────────────────────────

const STATUS_DOT: Record<Device["status"], string> = {
  Online: "bg-emerald-500",
  Offline: "bg-red-500",
  Connecting: "bg-sky-400 animate-pulse",
  Error: "bg-amber-500",
};

// ─── Form state (mirrors v1's FormFieldValues, string-backed for inputs) ───

interface FormState {
  deviceName: string;
  siteCode: string;
  siteName: string;
  customerName: string;
  meterNumber: string;
  meterKey: string;
  brand: Brand | "";
  model: ModelKey | "";
  source: Source;
  slaveAddr: string;
  connectionType: ConnectionType;
  ip: string;
  port: string;
  serialPort: string;
  baudRate: string;
  dataBits: string;
  parity: string;
  stopBits: string;
  flowControl: string;
  password: string;
  billStartDate: Date | undefined;
  billDayFeb28: string;
  billDayFeb29: string;
  billDay30: string;
  billDay31: string;
}

const blankForm = (): FormState => ({
  deviceName: "",
  siteCode: "",
  siteName: "",
  customerName: "",
  meterNumber: "",
  meterKey: "",
  brand: "",
  model: "",
  source: "dlms",
  slaveAddr: "",
  connectionType: "net",
  ip: "",
  port: "",
  serialPort: "",
  baudRate: "",
  dataBits: String(DEFAULT_DATA_BITS),
  parity: DEFAULT_PARITY,
  stopBits: DEFAULT_STOP_BITS,
  flowControl: DEFAULT_FLOW_CONTROL,
  password: "",
  billStartDate: undefined,
  billDayFeb28: "",
  billDayFeb29: "",
  billDay30: "",
  billDay31: "",
});

const deviceToForm = (d: Device): FormState => ({
  deviceName: d.name,
  siteCode: d.siteCode ?? "",
  siteName: d.siteName,
  customerName: d.customer ?? "",
  meterNumber: d.meterNumber ?? "",
  meterKey: "",
  brand: d.brand,
  model: d.model,
  source: d.source,
  slaveAddr: d.slaveAddr != null ? String(d.slaveAddr) : "",
  connectionType: d.connectionType ?? "net",
  ip: d.ip ?? "",
  port: d.port != null ? String(d.port) : "",
  serialPort: d.serialPort ?? "",
  baudRate: d.baudRate != null ? String(d.baudRate) : "",
  dataBits: d.dataBits != null ? String(d.dataBits) : String(DEFAULT_DATA_BITS),
  parity: d.parity ?? DEFAULT_PARITY,
  stopBits: d.stopBits ?? DEFAULT_STOP_BITS,
  flowControl: d.flowControl ?? DEFAULT_FLOW_CONTROL,
  password: "", // re-derived by the model-change effect, mirroring v1
  billStartDate: d.firstBillDate ? new Date(d.firstBillDate) : undefined,
  billDayFeb28: d.billDayFeb28 != null ? String(d.billDayFeb28) : "",
  billDayFeb29: d.billDayFeb29 != null ? String(d.billDayFeb29) : "",
  billDay30: d.billDay30 != null ? String(d.billDay30) : "",
  billDay31: d.billDay31 != null ? String(d.billDay31) : "",
});

const validate = (f: FormState): Record<string, string> => {
  const errors: Record<string, string> = {};
  if (!f.deviceName.trim()) errors.deviceName = "Device name is required";
  if (!f.siteName.trim()) errors.siteName = "Site name is required";
  if (!f.brand) errors.brand = "Brand is required";
  if (!f.model) errors.model = "Meter model is required";
  if (f.source === "modbus") {
    const n = Number(f.slaveAddr);
    if (!f.slaveAddr || !Number.isInteger(n) || n < 1 || n > 247) {
      errors.slaveAddr = "Slave address must be 1–247";
    }
  } else if (f.connectionType === "net") {
    if (!f.ip.trim()) errors.ip = "IP address is required";
    const p = Number(f.port);
    if (!f.port || !Number.isInteger(p) || p < 1 || p > 65535) errors.port = "Port must be 1–65535";
  } else {
    if (!/^(COM\d+|\/dev\/tty[A-Za-z0-9._/-]+)$/.test(f.serialPort)) {
      errors.serialPort = "Serial port must be COM<n> or /dev/tty…";
    }
    if (!f.baudRate) errors.baudRate = "Baud rate is required";
  }
  return errors;
};

const buildDevicePatch = (
  f: FormState,
): Omit<Device, "id" | "status" | "pollingPaused" | "latencyMs" | "lastSeenAt" | "meterSerial"> => {
  const base = {
    name: f.deviceName,
    siteName: f.siteName,
    siteCode: f.siteCode || undefined,
    customer: f.customerName || undefined,
    meterNumber: f.meterNumber || undefined,
    brand: f.brand as Brand,
    model: f.model as ModelKey,
    firstBillDate: f.billStartDate ? formatDateShort(f.billStartDate) : null,
    billDayFeb28: f.billDayFeb28 ? Number(f.billDayFeb28) : null,
    billDayFeb29: f.billDayFeb29 ? Number(f.billDayFeb29) : null,
    billDay30: f.billDay30 ? Number(f.billDay30) : null,
    billDay31: f.billDay31 ? Number(f.billDay31) : null,
  };
  if (f.source === "modbus") {
    return { ...base, source: "modbus", slaveAddr: Number(f.slaveAddr) };
  }
  return {
    ...base,
    source: "dlms",
    password: f.password || undefined,
    connectionType: f.connectionType,
    ...(f.connectionType === "net"
      ? { ip: f.ip, port: Number(f.port) }
      : {
          serialPort: f.serialPort,
          baudRate: Number(f.baudRate),
          dataBits: f.dataBits ? Number(f.dataBits) : DEFAULT_DATA_BITS,
          parity: f.parity || DEFAULT_PARITY,
          stopBits: f.stopBits || DEFAULT_STOP_BITS,
          flowControl: f.flowControl || DEFAULT_FLOW_CONTROL,
        }),
  };
};

// ─── Small layout helpers ───────────────────────────────────────────────────

function Field({
  label,
  required,
  error,
  children,
  className,
}: {
  label: string;
  required?: boolean;
  error?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cn2("flex flex-col gap-1 text-sm", className)}>
      <span className="text-xs font-medium text-[var(--muted-foreground)]">
        {required && <span className="text-[var(--destructive)]">*</span>}
        {label}
      </span>
      {children}
      {error && <span className="text-xs text-[var(--destructive)]">{error}</span>}
    </label>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mb-3 rounded-lg border border-[var(--border)] bg-[var(--secondary)]/60 p-3">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">{title}</p>
      <div className="flex flex-col gap-3">{children}</div>
    </div>
  );
}

function cn2(...parts: (string | undefined | false)[]) {
  return parts.filter(Boolean).join(" ");
}

// ─── Page ────────────────────────────────────────────────────────────────────

function ShadcnDevicesContent() {
  const [devices, setDevices] = useState<Device[]>(DEVICES);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [expandedSites, setExpandedSites] = useState<Set<string>>(
    () => new Set(groupBySite(DEVICES).map((g) => g.siteName)),
  );
  const [form, setForm] = useState<FormState>(blankForm());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Device | null>(null);
  const keepTemplateRef = useRef(false);

  const selectedDevice = useMemo(() => devices.find((d) => d.id === selectedId) ?? null, [devices, selectedId]);

  const filteredDevices = useMemo(
    () =>
      devices.filter((d) => {
        const matchesSearch = d.name.toLowerCase().includes(search.toLowerCase());
        const matchesType = typeFilter === "all" || d.model === typeFilter;
        return matchesSearch && matchesType;
      }),
    [devices, search, typeFilter],
  );
  const siteGroups = useMemo(() => groupBySite(filteredDevices), [filteredDevices]);

  // Populate / reset the form whenever the selection changes (mirrors v1's
  // detail-load effect, including the "New Device (copy)" template carry-over).
  useEffect(() => {
    if (selectedId === null) {
      if (keepTemplateRef.current) {
        keepTemplateRef.current = false;
        return;
      }
      setForm(blankForm());
      setErrors({});
      return;
    }
    const device = devices.find((d) => d.id === selectedId);
    if (device) {
      setForm(deviceToForm(device));
      setErrors({});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  // Password prefill: fires on every model change, in both add and edit modes
  // (deliberate v1 behavior — convenience over secrecy, see mockData.ts).
  useEffect(() => {
    if (!form.model) return;
    const spec = catalogFor(form.model);
    setForm((f) => ({ ...f, password: spec.fixedPassword ?? "" }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.model]);

  const selectedModelSpec = form.model ? catalogFor(form.model) : null;
  const isKeylessModel = selectedModelSpec?.fixedPassword === null;
  const modelSupportsSerial = selectedModelSpec?.supportsSerial ?? false;

  const nextCutDate = useMemo(
    () => (selectedDevice ? resolveNextBillingCutDate(selectedDevice) : null),
    [selectedDevice],
  );

  const toggleSite = (site: string) => {
    setExpandedSites((prev) => {
      const next = new Set(prev);
      if (next.has(site)) next.delete(site);
      else next.add(site);
      return next;
    });
  };

  const setField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => (e[key as string] ? { ...e, [key as string]: "" } : e));
  };

  const onBrandChange = (brand: Brand) => {
    const models = modelsForBrand(brand);
    setForm((f) => ({ ...f, brand, model: models.length === 1 ? models[0].model : "" }));
  };

  const onConnectionTypeChange = (connectionType: ConnectionType) => {
    setForm((f) => {
      if (connectionType !== "serial") return { ...f, connectionType };
      return {
        ...f,
        connectionType,
        baudRate: f.baudRate || String(defaultBaudFor(f.model || undefined)),
        dataBits: f.dataBits || String(DEFAULT_DATA_BITS),
        parity: f.parity || DEFAULT_PARITY,
        stopBits: f.stopBits || DEFAULT_STOP_BITS,
        flowControl: f.flowControl || DEFAULT_FLOW_CONTROL,
      };
    });
  };

  const onCreate = () => {
    const errs = validate(form);
    if (Object.keys(errs).length) {
      setErrors(errs);
      toast.error("Please fix the highlighted fields.");
      return;
    }
    setSubmitting(true);
    setTimeout(() => {
      const newId = devices.reduce((max, d) => Math.max(max, d.id), 0) + 1;
      const patch = buildDevicePatch(form);
      const newDevice: Device = {
        id: newId,
        status: "Connecting",
        pollingPaused: false,
        latencyMs: null,
        lastSeenAt: new Date().toISOString(),
        ...patch,
      };
      setDevices((prev) => [...prev, newDevice]);
      setSelectedId(newId);
      setSubmitting(false);
      toast.success(`Device "${newDevice.name}" created successfully.`);
      setTimeout(() => {
        setDevices((prev) =>
          prev.map((d) => (d.id === newId ? { ...d, status: "Online", latencyMs: 40 + Math.round(Math.random() * 120) } : d)),
        );
      }, 900);
    }, 500);
  };

  const onUpdate = () => {
    if (!selectedDevice) return;
    const errs = validate(form);
    if (Object.keys(errs).length) {
      setErrors(errs);
      toast.error("Please fix the highlighted fields.");
      return;
    }
    setSubmitting(true);
    setTimeout(() => {
      const patch = buildDevicePatch(form);
      setDevices((prev) => prev.map((d) => (d.id === selectedDevice.id ? { ...d, ...patch } : d)));
      setSubmitting(false);
      toast.success(`Device "${form.deviceName}" updated successfully.`);
    }, 400);
  };

  const onCopyAsTemplate = () => {
    keepTemplateRef.current = true;
    setForm((f) => ({ ...f, meterKey: "" }));
    setSelectedId(null);
  };

  const onDisconnect = () => {
    if (!selectedDevice) return;
    setDevices((prev) => prev.map((d) => (d.id === selectedDevice.id ? { ...d, pollingPaused: true } : d)));
    toast.success("Device background polling paused.");
  };

  const onReconnect = () => {
    if (!selectedDevice) return;
    const id = selectedDevice.id;
    setDevices((prev) => prev.map((d) => (d.id === id ? { ...d, pollingPaused: false, status: "Connecting" } : d)));
    toast.success("Reconnect job has been queued.");
    setTimeout(() => {
      setDevices((prev) =>
        prev.map((d) => (d.id === id ? { ...d, status: "Online", latencyMs: 40 + Math.round(Math.random() * 120) } : d)),
      );
    }, 900);
  };

  const onRemoveConfirmed = () => {
    if (!deleteTarget) return;
    setDevices((prev) => prev.filter((d) => d.id !== deleteTarget.id));
    if (selectedId === deleteTarget.id) setSelectedId(null);
    toast.success(`Device "${deleteTarget.name}" has been removed.`);
    setDeleteTarget(null);
  };

  const onRefreshLicense = () => {
    toast.warning("No updated license was issued — the portal may be unreachable, or nothing has changed.");
  };
  const onReconnectAll = () => {
    toast.success("Reconnect all job queued.");
  };

  const addingWhileSubmitting = submitting && QUOTA.mode === "lease" && !selectedDevice;

  return (
    <div className="shadcn-scope flex h-screen flex-col">
      <Toaster position="top-right" richColors />
      <div className="border-b border-[var(--border)] px-4 py-2">
        <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
          <ArrowLeft className="h-3.5 w-3.5" /> All variants
        </Link>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* Left: device tree */}
        <aside className="flex w-72 shrink-0 flex-col border-r border-[var(--border)] bg-white">
          <div className="space-y-1.5 border-b border-[var(--border)] p-2">
            <div className="flex items-center justify-between">
              <div className="flex min-w-0 items-baseline gap-2">
                <span className="text-xs font-semibold text-[var(--foreground)]">Devices ({filteredDevices.length})</span>
                <span
                  className="whitespace-nowrap text-xs text-[var(--muted-foreground)]"
                  title={
                    QUOTA.maxMeters === null
                      ? "This license does not limit the number of meters."
                      : `${QUOTA.used} of ${QUOTA.maxMeters} licensed meter slots in use.`
                  }
                >
                  {QUOTA.maxMeters === null ? `${QUOTA.used} meters · unlimited` : `${QUOTA.used} / ${QUOTA.maxMeters} meters`}
                </span>
              </div>
              <div className="flex shrink-0 items-center">
                <Button variant="ghost" size="icon" title="Refresh license from the licensing portal now" onClick={onRefreshLicense}>
                  <ShieldCheck className="h-3.5 w-3.5" />
                </Button>
                <Button variant="ghost" size="icon" title="Reconnect All Active Devices" onClick={onReconnectAll}>
                  <RefreshCw className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-[var(--muted-foreground)]" />
              <Input placeholder="Search devices..." value={search} onChange={(e) => setSearch(e.target.value)} className="h-8 pl-8 text-xs" />
            </div>
            <Select value={typeFilter} onValueChange={setTypeFilter}>
              <SelectTrigger className="h-8 w-full text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TYPE_FILTER_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex-1 overflow-y-auto py-1">
            {siteGroups.map((group) => (
              <div key={group.siteName}>
                <button
                  onClick={() => toggleSite(group.siteName)}
                  className="flex w-full items-center gap-1 border-0 bg-transparent px-2 py-1 text-left text-xs font-semibold text-[var(--foreground)] hover:bg-[var(--accent)]"
                >
                  {expandedSites.has(group.siteName) ? (
                    <ChevronDown className="h-3 w-3 text-[var(--muted-foreground)]" />
                  ) : (
                    <ChevronRight className="h-3 w-3 text-[var(--muted-foreground)]" />
                  )}
                  <Folder className="h-3 w-3 text-[var(--muted-foreground)]" />
                  {group.siteName} ({group.devices.length})
                </button>
                {expandedSites.has(group.siteName) &&
                  group.devices.map((d) => {
                    const isSelected = selectedId === d.id;
                    const suffix =
                      (d.meterSerial ? ` (${d.meterSerial})` : "") +
                      (d.connectionType === "net" && d.ip ? ` - ${d.ip}:${d.port}` : "");
                    return (
                      <button
                        key={d.id}
                        onClick={() => setSelectedId(d.id)}
                        className={cn2(
                          "flex w-full items-center gap-2 border-0 py-0.5 pl-6 pr-2 text-left font-mono text-xs transition-colors",
                          isSelected
                            ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                            : "bg-transparent text-[var(--foreground)] hover:bg-[var(--accent)]",
                        )}
                      >
                        <span className={cn2("h-2 w-2 shrink-0 rounded-full", STATUS_DOT[d.status])} />
                        <span className="truncate">
                          {d.name}
                          {suffix}
                        </span>
                      </button>
                    );
                  })}
              </div>
            ))}
            {siteGroups.length === 0 && <p className="py-4 text-center text-xs text-[var(--muted-foreground)]">No devices found.</p>}
          </div>
        </aside>

        {/* Right: device control form */}
        <main className="flex-1 overflow-y-auto p-4">
          <div className="mb-3 flex items-center justify-between">
            <h1 className="text-base font-semibold text-[var(--foreground)]">{!selectedDevice ? "Add New Device" : "Device Control"}</h1>
            {selectedDevice && (
              <div className="flex items-center gap-2">
                {selectedDevice.pollingPaused && <Badge variant="neutral">Disconnected</Badge>}
                {selectedDevice.status === "Online" && <Badge variant="success">Online</Badge>}
                {selectedDevice.status === "Offline" && <Badge variant="destructive">Offline</Badge>}
                {selectedDevice.status === "Connecting" && <Badge variant="info">Connecting</Badge>}
                {selectedDevice.status === "Error" && (
                  <span title={selectedDevice.detail}>
                    <Badge variant="warning">Error</Badge>
                  </span>
                )}
                {selectedDevice.latencyMs != null && (
                  <span className="font-mono text-xs text-[var(--muted-foreground)]">{selectedDevice.latencyMs} ms</span>
                )}
                {selectedDevice.lastSeenAt && (
                  <span className="ml-1 text-xs text-[var(--muted-foreground)]">Last Seen: {formatDateTime(selectedDevice.lastSeenAt)}</span>
                )}
              </div>
            )}
          </div>

          {/* Identity */}
          <Section title="Identity">
            <Field label="Device Name" required error={errors.deviceName}>
              <Input value={form.deviceName} onChange={(e) => setField("deviceName", e.target.value)} />
            </Field>
            <Field label="Meter Serial">
              <Input value="" readOnly disabled placeholder="Assigned automatically by the system" />
            </Field>
            <Field label="Site Code">
              <Input value={form.siteCode} onChange={(e) => setField("siteCode", e.target.value)} />
            </Field>
            <Field label="Site Name" required error={errors.siteName}>
              <Input value={form.siteName} onChange={(e) => setField("siteName", e.target.value)} />
            </Field>
            <Field label="Customer Name">
              <Input value={form.customerName} onChange={(e) => setField("customerName", e.target.value)} />
            </Field>
            <Field label="Meter Number">
              <Input value={form.meterNumber} onChange={(e) => setField("meterNumber", e.target.value)} />
            </Field>
            {QUOTA.mode === "lease" && !selectedDevice && (
              <Field label="Meter Key">
                <Input placeholder="e.g. MK-XXXX-XXXX" value={form.meterKey} onChange={(e) => setField("meterKey", e.target.value)} />
                <span className="text-xs text-[var(--muted-foreground)]">One key grants one meter slot. Ask your vendor for one.</span>
              </Field>
            )}
          </Section>

          {/* Meter (brand → model cascade) */}
          <Section title="Meter">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Brand" required error={errors.brand}>
                <Select value={form.brand || undefined} onValueChange={(v) => onBrandChange(v as Brand)}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select brand" />
                  </SelectTrigger>
                  <SelectContent>
                    {BRANDS.map((b) => (
                      <SelectItem key={b} value={b}>
                        {b}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Model" required error={errors.model}>
                <Select value={form.model || undefined} onValueChange={(v) => setField("model", v as ModelKey)}>
                  <SelectTrigger disabled={!form.brand}>
                    <SelectValue placeholder={form.brand ? "Select model" : "Select a brand first"} />
                  </SelectTrigger>
                  <SelectContent>
                    {(form.brand ? modelsForBrand(form.brand) : []).map((m) => (
                      <SelectItem key={m.model} value={m.model} disabled={m.driverStatus !== "ready"}>
                        {m.driverStatus === "ready" ? m.uiLabel : `${m.uiLabel} (coming soon)`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            </div>
          </Section>

          {/* Source */}
          <Section title="Source">
            <Field label="Source" required>
              <RadioGroup value={form.source} onValueChange={(v) => setField("source", v as Source)}>
                <label className="flex items-center gap-2 text-sm">
                  <RadioGroupItem value="dlms" /> DLMS
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <RadioGroupItem value="modbus" /> Modbus
                </label>
              </RadioGroup>
            </Field>
            {form.source === "modbus" && (
              <Field label="Slave Address" required error={errors.slaveAddr}>
                <Input
                  type="number"
                  min={1}
                  max={247}
                  placeholder="1–247"
                  value={form.slaveAddr}
                  onChange={(e) => setField("slaveAddr", e.target.value)}
                  className="font-mono"
                />
              </Field>
            )}
          </Section>

          {/* Connection (DLMS only) */}
          {form.source !== "modbus" && (
            <Section title="Connection">
              <Field label="Type" required>
                <RadioGroup value={form.connectionType} onValueChange={(v) => onConnectionTypeChange(v as ConnectionType)}>
                  <label className="flex items-center gap-2 text-sm">
                    <RadioGroupItem value="net" /> Network (TCP)
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <RadioGroupItem value="serial" /> Serial (RS-232/485)
                  </label>
                </RadioGroup>
              </Field>
              {modelSupportsSerial && form.connectionType !== "serial" && (
                <p className="text-xs text-[var(--muted-foreground)]">This model supports a serial connection.</p>
              )}
              {form.connectionType !== "serial" ? (
                <div className="grid grid-cols-2 gap-3">
                  <Field label="IP Address" required error={errors.ip}>
                    <Input className="font-mono" value={form.ip} onChange={(e) => setField("ip", e.target.value)} />
                  </Field>
                  <Field label="Port" required error={errors.port}>
                    <Input type="number" min={1} max={65535} className="font-mono" value={form.port} onChange={(e) => setField("port", e.target.value)} />
                  </Field>
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Serial Port" required error={errors.serialPort}>
                      <Input className="font-mono" placeholder="COM3" value={form.serialPort} onChange={(e) => setField("serialPort", e.target.value)} />
                    </Field>
                    <Field label="Baud Rate" required error={errors.baudRate}>
                      <Select value={form.baudRate || undefined} onValueChange={(v) => setField("baudRate", v)}>
                        <SelectTrigger>
                          <SelectValue placeholder="Select baud rate" />
                        </SelectTrigger>
                        <SelectContent>
                          {ALLOWED_BAUD_RATES.map((v) => (
                            <SelectItem key={v} value={String(v)}>
                              {v}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </Field>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Data Bits">
                      <Select value={form.dataBits || undefined} onValueChange={(v) => setField("dataBits", v)}>
                        <SelectTrigger>
                          <SelectValue placeholder="Select data bits" />
                        </SelectTrigger>
                        <SelectContent>
                          {ALLOWED_DATA_BITS.map((v) => (
                            <SelectItem key={v} value={String(v)}>
                              {v}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </Field>
                    <Field label="Parity">
                      <Select value={form.parity || undefined} onValueChange={(v) => setField("parity", v)}>
                        <SelectTrigger>
                          <SelectValue placeholder="Select parity" />
                        </SelectTrigger>
                        <SelectContent>
                          {ALLOWED_PARITY.map((v) => (
                            <SelectItem key={v} value={v}>
                              {v}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </Field>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Stop Bits">
                      <Select value={form.stopBits || undefined} onValueChange={(v) => setField("stopBits", v)}>
                        <SelectTrigger>
                          <SelectValue placeholder="Select stop bits" />
                        </SelectTrigger>
                        <SelectContent>
                          {ALLOWED_STOP_BITS.map((v) => (
                            <SelectItem key={v} value={v}>
                              {v}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </Field>
                    <Field label="Flow Control">
                      <Select value={form.flowControl || undefined} onValueChange={(v) => setField("flowControl", v)}>
                        <SelectTrigger>
                          <SelectValue placeholder="Select flow control" />
                        </SelectTrigger>
                        <SelectContent>
                          {ALLOWED_FLOW_CONTROL.map((v) => (
                            <SelectItem key={v} value={v}>
                              {v}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </Field>
                  </div>
                </>
              )}
              {!isKeylessModel && (
                <Field label="Password">
                  <Input type="password" value={form.password} onChange={(e) => setField("password", e.target.value)} />
                  <span className="text-xs text-[var(--muted-foreground)]">
                    Sent to the meter. Prefilled with the brand default — clear it to keep the stored password on update.
                  </span>
                </Field>
              )}
            </Section>
          )}

          {/* Billing */}
          <Section title="Billing">
            {selectedDevice && (
              <div className="flex text-xs">
                <span className="w-1/3 text-[var(--muted-foreground)]">Next Cut Date</span>
                <span className="font-mono" title={nextCutDate ? undefined : "No billing day configured for this device"}>
                  {nextCutDate ? formatDateShort(nextCutDate) : "—"}
                </span>
              </div>
            )}
            <Field label="Bill Start Date">
              <DatePicker date={form.billStartDate} onDateChange={(d) => setField("billStartDate", d)} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Bill Day - Feb (28 days)">
                <Select value={form.billDayFeb28 || undefined} onValueChange={(v) => setField("billDayFeb28", v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="Day of month" />
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from({ length: 28 }, (_, i) => i + 1).map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        {n}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Bill Day - Feb (29 days)">
                <Select value={form.billDayFeb29 || undefined} onValueChange={(v) => setField("billDayFeb29", v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="Day of month" />
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from({ length: 29 }, (_, i) => i + 1).map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        {n}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Bill Day - 30-day months">
                <Select value={form.billDay30 || undefined} onValueChange={(v) => setField("billDay30", v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="Day of month" />
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from({ length: 30 }, (_, i) => i + 1).map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        {n}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Bill Day - 31-day months">
                <Select value={form.billDay31 || undefined} onValueChange={(v) => setField("billDay31", v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="Day of month" />
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from({ length: 31 }, (_, i) => i + 1).map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        {n}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            </div>
          </Section>

          {/* Actions */}
          <div className="mb-2 flex flex-wrap gap-2">
            <Button onClick={onCreate} disabled={submitting}>
              <Plus className="h-4 w-4" /> {addingWhileSubmitting ? "Checking meter…" : "Create Device"}
            </Button>
            {selectedDevice && (
              <Button variant="outline" onClick={onUpdate} disabled={submitting}>
                <Pencil className="h-4 w-4" /> Update Device
              </Button>
            )}
            {selectedDevice && (
              <Button variant="outline" title="Start a new device using the current form values as a template" onClick={onCopyAsTemplate}>
                <Copy className="h-4 w-4" /> New Device (copy)
              </Button>
            )}
            {selectedDevice && (
              <Button variant="outline" disabled title="Configure meter parameters">
                <Settings className="h-4 w-4" /> Meter Setting
              </Button>
            )}
          </div>
          {selectedDevice && (
            <div className="flex flex-wrap gap-2">
              {selectedDevice.source === "dlms" && (
                <Button variant="outline" disabled={selectedDevice.pollingPaused} onClick={onDisconnect}>
                  <Pause className="h-4 w-4" /> Disconnect
                </Button>
              )}
              <Button variant="outline" onClick={onReconnect}>
                <Play className="h-4 w-4" /> Reconnect
              </Button>
              <Button variant="destructive" onClick={() => setDeleteTarget(selectedDevice)}>
                <Trash2 className="h-4 w-4" /> Remove Device
              </Button>
              <Button variant="destructive" disabled>
                <Eraser className="h-4 w-4" /> Remove All Data
              </Button>
            </div>
          )}
        </main>
      </div>

      {/* Remove-device confirm */}
      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove Device</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-[var(--muted-foreground)]">
            Are you sure you want to remove "{deleteTarget?.name}"? This action cannot be undone.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={onRemoveConfirmed}>
              Remove
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function ShadcnDevicesPage() {
  return <ShadcnDevicesContent />;
}
