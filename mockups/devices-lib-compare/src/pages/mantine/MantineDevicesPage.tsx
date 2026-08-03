import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import "@mantine/core/styles.css";
import "@mantine/dates/styles.css";
import "@mantine/notifications/styles.css";
import {
  MantineProvider,
  createTheme,
  Group,
  Stack,
  Text,
  Title,
  Badge,
  TextInput,
  PasswordInput,
  Select,
  Button,
  ActionIcon,
  Tooltip,
  Radio,
  NumberInput,
  Paper,
  Anchor,
  ScrollArea,
} from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { ModalsProvider, modals } from "@mantine/modals";
import { Notifications, notifications } from "@mantine/notifications";
import {
  IconSearch,
  IconPlus,
  IconEdit,
  IconCopy,
  IconSettings,
  IconPlayerPause,
  IconPlayerPlay,
  IconTrash,
  IconEraser,
  IconRefresh,
  IconShieldCheck,
  IconChevronDown,
  IconChevronRight,
  IconFolder,
  IconArrowLeft,
} from "@tabler/icons-react";

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

// A distinct teal-family palette (same family as the shadcn variant, for a
// fair primary-color comparison) with a slightly larger radius than the
// shadcn variant's — Mantine's own idiom leans softer/rounder by default.
const theme = createTheme({
  primaryColor: "teal",
  defaultRadius: "md",
  fontFamily: "system-ui, 'Segoe UI', Roboto, sans-serif",
});

const STATUS_DOT: Record<Device["status"], string> = {
  Online: "#12b886",
  Offline: "#fa5252",
  Connecting: "#4dabf7",
  Error: "#fd7e14",
};

// ─── Form state (mirrors v1's FormFieldValues) ─────────────────────────────

interface FormState {
  deviceName: string;
  siteCode: string;
  siteName: string;
  customerName: string;
  meterNumber: string;
  meterKey: string;
  brand: Brand | null;
  model: ModelKey | null;
  source: Source;
  slaveAddr: number | "";
  connectionType: ConnectionType;
  ip: string;
  port: number | "";
  serialPort: string;
  baudRate: string | null;
  dataBits: string | null;
  parity: string | null;
  stopBits: string | null;
  flowControl: string | null;
  password: string;
  billStartDate: string | null; // YYYY-MM-DD, matches DatePickerInput's onChange output
  billDayFeb28: string | null;
  billDayFeb29: string | null;
  billDay30: string | null;
  billDay31: string | null;
}

const blankForm = (): FormState => ({
  deviceName: "",
  siteCode: "",
  siteName: "",
  customerName: "",
  meterNumber: "",
  meterKey: "",
  brand: null,
  model: null,
  source: "dlms",
  slaveAddr: "",
  connectionType: "net",
  ip: "",
  port: "",
  serialPort: "",
  baudRate: null,
  dataBits: String(DEFAULT_DATA_BITS),
  parity: DEFAULT_PARITY,
  stopBits: DEFAULT_STOP_BITS,
  flowControl: DEFAULT_FLOW_CONTROL,
  password: "",
  billStartDate: null,
  billDayFeb28: null,
  billDayFeb29: null,
  billDay30: null,
  billDay31: null,
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
  slaveAddr: d.slaveAddr ?? "",
  connectionType: d.connectionType ?? "net",
  ip: d.ip ?? "",
  port: d.port ?? "",
  serialPort: d.serialPort ?? "",
  baudRate: d.baudRate != null ? String(d.baudRate) : null,
  dataBits: d.dataBits != null ? String(d.dataBits) : String(DEFAULT_DATA_BITS),
  parity: d.parity ?? DEFAULT_PARITY,
  stopBits: d.stopBits ?? DEFAULT_STOP_BITS,
  flowControl: d.flowControl ?? DEFAULT_FLOW_CONTROL,
  password: "", // re-derived by the model-change effect, mirroring v1
  billStartDate: d.firstBillDate ?? null,
  billDayFeb28: d.billDayFeb28 != null ? String(d.billDayFeb28) : null,
  billDayFeb29: d.billDayFeb29 != null ? String(d.billDayFeb29) : null,
  billDay30: d.billDay30 != null ? String(d.billDay30) : null,
  billDay31: d.billDay31 != null ? String(d.billDay31) : null,
});

const validate = (f: FormState): Record<string, string> => {
  const errors: Record<string, string> = {};
  if (!f.deviceName.trim()) errors.deviceName = "Device name is required";
  if (!f.siteName.trim()) errors.siteName = "Site name is required";
  if (!f.brand) errors.brand = "Brand is required";
  if (!f.model) errors.model = "Meter model is required";
  if (f.source === "modbus") {
    const n = Number(f.slaveAddr);
    if (f.slaveAddr === "" || !Number.isInteger(n) || n < 1 || n > 247) {
      errors.slaveAddr = "Slave address must be 1–247";
    }
  } else if (f.connectionType === "net") {
    if (!f.ip.trim()) errors.ip = "IP address is required";
    const p = Number(f.port);
    if (f.port === "" || !Number.isInteger(p) || p < 1 || p > 65535) errors.port = "Port must be 1–65535";
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
    firstBillDate: f.billStartDate || null,
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

// ─── Layout helper: a bordered/tinted section, mirrors v1's
// `bg-gray-50 border border-gray-200 rounded p-3` grouping ─────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Paper withBorder radius="md" p="sm" mb="sm" bg="gray.0">
      <Text size="xs" fw={600} c="dimmed" tt="uppercase" mb="xs" style={{ letterSpacing: 0.4 }}>
        {title}
      </Text>
      <Stack gap="sm">{children}</Stack>
    </Paper>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

function DevicesContent() {
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

  const onBrandChange = (value: string | null) => {
    const brand = value as Brand | null;
    const models = brand ? modelsForBrand(brand) : [];
    setForm((f) => ({ ...f, brand, model: models.length === 1 ? models[0].model : null }));
  };

  const onConnectionTypeChange = (value: string) => {
    const connectionType = value as ConnectionType;
    setForm((f) => {
      if (connectionType !== "serial") return { ...f, connectionType };
      return {
        ...f,
        connectionType,
        baudRate: f.baudRate || String(defaultBaudFor(f.model ?? undefined)),
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
      notifications.show({ color: "red", title: "Fix the highlighted fields", message: "Some required fields are missing or invalid." });
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
      notifications.show({ color: "teal", title: "Device created", message: `"${newDevice.name}" created successfully.` });
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
      notifications.show({ color: "red", title: "Fix the highlighted fields", message: "Some required fields are missing or invalid." });
      return;
    }
    setSubmitting(true);
    setTimeout(() => {
      const patch = buildDevicePatch(form);
      setDevices((prev) => prev.map((d) => (d.id === selectedDevice.id ? { ...d, ...patch } : d)));
      setSubmitting(false);
      notifications.show({ color: "teal", title: "Device updated", message: `"${form.deviceName}" updated successfully.` });
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
    notifications.show({ message: "Device background polling paused." });
  };

  const onReconnect = () => {
    if (!selectedDevice) return;
    const id = selectedDevice.id;
    setDevices((prev) => prev.map((d) => (d.id === id ? { ...d, pollingPaused: false, status: "Connecting" } : d)));
    notifications.show({ message: "Reconnect job has been queued." });
    setTimeout(() => {
      setDevices((prev) =>
        prev.map((d) => (d.id === id ? { ...d, status: "Online", latencyMs: 40 + Math.round(Math.random() * 120) } : d)),
      );
    }, 900);
  };

  const onRemove = () => {
    if (!selectedDevice) return;
    const device = selectedDevice;
    modals.openConfirmModal({
      title: "Remove Device",
      children: (
        <Text size="sm">
          Are you sure you want to remove "{device.name}"? This action cannot be undone.
        </Text>
      ),
      labels: { confirm: "Remove", cancel: "Cancel" },
      confirmProps: { color: "red" },
      onConfirm: () => {
        setDevices((prev) => prev.filter((d) => d.id !== device.id));
        setSelectedId(null);
        notifications.show({ color: "red", message: `Device "${device.name}" has been removed.` });
      },
    });
  };

  const onRefreshLicense = () => {
    notifications.show({
      color: "yellow",
      message: "No updated license was issued — the portal may be unreachable, or nothing has changed.",
    });
  };
  const onReconnectAll = () => {
    notifications.show({ color: "teal", message: "Reconnect all job queued." });
  };

  const addingWhileSubmitting = submitting && QUOTA.mode === "lease" && !selectedDevice;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <div style={{ borderBottom: "1px solid #e9ecef", padding: "8px 16px" }}>
        <Anchor component={Link} to="/" size="sm" c="dimmed" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <IconArrowLeft size={14} /> All variants
        </Anchor>
      </div>

      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* Left: device tree */}
        <div style={{ width: 288, flexShrink: 0, borderRight: "1px solid #e9ecef", background: "#fff", display: "flex", flexDirection: "column" }}>
          <div style={{ borderBottom: "1px solid #e9ecef", padding: 8, display: "flex", flexDirection: "column", gap: 6 }}>
            <Group justify="space-between" wrap="nowrap">
              <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
                <Text size="xs" fw={600}>
                  Devices ({filteredDevices.length})
                </Text>
                <Tooltip
                  label={
                    QUOTA.maxMeters === null
                      ? "This license does not limit the number of meters."
                      : `${QUOTA.used} of ${QUOTA.maxMeters} licensed meter slots in use.`
                  }
                >
                  <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>
                    {QUOTA.maxMeters === null ? `${QUOTA.used} meters · unlimited` : `${QUOTA.used} / ${QUOTA.maxMeters} meters`}
                  </Text>
                </Tooltip>
              </Group>
              <Group gap={2} wrap="nowrap">
                <Tooltip label="Refresh license from the licensing portal now">
                  <ActionIcon variant="subtle" color="gray" onClick={onRefreshLicense}>
                    <IconShieldCheck size={15} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label="Reconnect All Active Devices">
                  <ActionIcon variant="subtle" color="gray" onClick={onReconnectAll}>
                    <IconRefresh size={15} />
                  </ActionIcon>
                </Tooltip>
              </Group>
            </Group>
            <TextInput
              size="xs"
              placeholder="Search devices..."
              leftSection={<IconSearch size={13} />}
              value={search}
              onChange={(e) => setSearch(e.currentTarget.value)}
            />
            <Select
              size="xs"
              data={TYPE_FILTER_OPTIONS}
              value={typeFilter}
              onChange={(v) => setTypeFilter(v ?? "all")}
              allowDeselect={false}
            />
          </div>

          <ScrollArea style={{ flex: 1 }} type="auto">
            <div style={{ padding: "4px 0" }}>
              {siteGroups.map((group) => (
                <div key={group.siteName}>
                  <button
                    onClick={() => toggleSite(group.siteName)}
                    style={{
                      width: "100%",
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
                      padding: "4px 8px",
                      background: "transparent",
                      border: 0,
                      textAlign: "left",
                      cursor: "pointer",
                      fontSize: 12,
                      fontWeight: 600,
                    }}
                  >
                    {expandedSites.has(group.siteName) ? <IconChevronDown size={13} color="#868e96" /> : <IconChevronRight size={13} color="#868e96" />}
                    <IconFolder size={13} color="#868e96" />
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
                          style={{
                            width: "100%",
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            border: 0,
                            padding: "2px 8px 2px 24px",
                            textAlign: "left",
                            cursor: "pointer",
                            fontFamily: "ui-monospace, Consolas, monospace",
                            fontSize: 12,
                            background: isSelected ? "#e6fcf5" : "transparent",
                            color: isSelected ? "#0c8599" : "#212529",
                          }}
                        >
                          <span style={{ width: 8, height: 8, borderRadius: 999, flexShrink: 0, background: STATUS_DOT[d.status] }} />
                          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {d.name}
                            {suffix}
                          </span>
                        </button>
                      );
                    })}
                </div>
              ))}
              {siteGroups.length === 0 && (
                <Text size="xs" c="dimmed" ta="center" py="md">
                  No devices found.
                </Text>
              )}
            </div>
          </ScrollArea>
        </div>

        {/* Right: device control form */}
        <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
          <Group justify="space-between" mb="sm">
            <Title order={4}>{!selectedDevice ? "Add New Device" : "Device Control"}</Title>
            {selectedDevice && (
              <Group gap="xs">
                {selectedDevice.pollingPaused && <Badge color="gray" variant="light">Disconnected</Badge>}
                {selectedDevice.status === "Online" && <Badge color="teal" variant="light">Online</Badge>}
                {selectedDevice.status === "Offline" && <Badge color="red" variant="light">Offline</Badge>}
                {selectedDevice.status === "Connecting" && <Badge color="blue" variant="light">Connecting</Badge>}
                {selectedDevice.status === "Error" && (
                  <Tooltip label={selectedDevice.detail}>
                    <Badge color="orange" variant="light">Error</Badge>
                  </Tooltip>
                )}
                {selectedDevice.latencyMs != null && (
                  <Text size="xs" c="dimmed" ff="monospace">
                    {selectedDevice.latencyMs} ms
                  </Text>
                )}
                {selectedDevice.lastSeenAt && (
                  <Text size="xs" c="dimmed">
                    Last Seen: {formatDateTime(selectedDevice.lastSeenAt)}
                  </Text>
                )}
              </Group>
            )}
          </Group>

          {/* Identity */}
          <Section title="Identity">
            <TextInput
              label="Device Name"
              required
              size="xs"
              value={form.deviceName}
              onChange={(e) => setField("deviceName", e.currentTarget.value)}
              error={errors.deviceName}
            />
            <TextInput label="Meter Serial" size="xs" value="" readOnly placeholder="Assigned automatically by the system" />
            <TextInput label="Site Code" size="xs" value={form.siteCode} onChange={(e) => setField("siteCode", e.currentTarget.value)} />
            <TextInput
              label="Site Name"
              required
              size="xs"
              value={form.siteName}
              onChange={(e) => setField("siteName", e.currentTarget.value)}
              error={errors.siteName}
            />
            <TextInput label="Customer Name" size="xs" value={form.customerName} onChange={(e) => setField("customerName", e.currentTarget.value)} />
            <TextInput label="Meter Number" size="xs" value={form.meterNumber} onChange={(e) => setField("meterNumber", e.currentTarget.value)} />
            {QUOTA.mode === "lease" && !selectedDevice && (
              <TextInput
                label="Meter Key"
                size="xs"
                placeholder="e.g. MK-XXXX-XXXX"
                value={form.meterKey}
                onChange={(e) => setField("meterKey", e.currentTarget.value)}
                description="One key grants one meter slot. Ask your vendor for one."
              />
            )}
          </Section>

          {/* Meter (brand → model cascade) */}
          <Section title="Meter">
            <Group grow>
              <Select
                label="Brand"
                required
                size="xs"
                placeholder="Select brand"
                data={BRANDS}
                value={form.brand}
                onChange={onBrandChange}
                error={errors.brand}
              />
              <Select
                label="Model"
                required
                size="xs"
                placeholder={form.brand ? "Select model" : "Select a brand first"}
                disabled={!form.brand}
                data={(form.brand ? modelsForBrand(form.brand) : []).map((m) => ({
                  value: m.model,
                  label: m.driverStatus === "ready" ? m.uiLabel : `${m.uiLabel} (coming soon)`,
                  disabled: m.driverStatus !== "ready",
                }))}
                value={form.model}
                onChange={(v) => setField("model", v as ModelKey | null)}
                error={errors.model}
              />
            </Group>
          </Section>

          {/* Source */}
          <Section title="Source">
            <Radio.Group label="Source" required value={form.source} onChange={(v) => setField("source", v as Source)}>
              <Group mt={4}>
                <Radio value="dlms" label="DLMS" />
                <Radio value="modbus" label="Modbus" />
              </Group>
            </Radio.Group>
            {form.source === "modbus" && (
              <NumberInput
                label="Slave Address"
                required
                size="xs"
                min={1}
                max={247}
                placeholder="1–247"
                value={form.slaveAddr}
                onChange={(v) => setField("slaveAddr", v as number | "")}
                error={errors.slaveAddr}
              />
            )}
          </Section>

          {/* Connection (DLMS only) */}
          {form.source !== "modbus" && (
            <Section title="Connection">
              <Radio.Group label="Type" required value={form.connectionType} onChange={onConnectionTypeChange}>
                <Group mt={4}>
                  <Radio value="net" label="Network (TCP)" />
                  <Radio value="serial" label="Serial (RS-232/485)" />
                </Group>
              </Radio.Group>
              {modelSupportsSerial && form.connectionType !== "serial" && (
                <Text size="xs" c="dimmed">
                  This model supports a serial connection.
                </Text>
              )}
              {form.connectionType !== "serial" ? (
                <Group grow>
                  <TextInput
                    label="IP Address"
                    required
                    size="xs"
                    ff="monospace"
                    value={form.ip}
                    onChange={(e) => setField("ip", e.currentTarget.value)}
                    error={errors.ip}
                  />
                  <NumberInput
                    label="Port"
                    required
                    size="xs"
                    min={1}
                    max={65535}
                    value={form.port}
                    onChange={(v) => setField("port", v as number | "")}
                    error={errors.port}
                  />
                </Group>
              ) : (
                <>
                  <Group grow>
                    <TextInput
                      label="Serial Port"
                      required
                      size="xs"
                      placeholder="COM3"
                      value={form.serialPort}
                      onChange={(e) => setField("serialPort", e.currentTarget.value)}
                      error={errors.serialPort}
                    />
                    <Select
                      label="Baud Rate"
                      required
                      size="xs"
                      placeholder="Select baud rate"
                      data={ALLOWED_BAUD_RATES.map((v) => String(v))}
                      value={form.baudRate}
                      onChange={(v) => setField("baudRate", v)}
                      error={errors.baudRate}
                    />
                  </Group>
                  <Group grow>
                    <Select
                      label="Data Bits"
                      size="xs"
                      data={ALLOWED_DATA_BITS.map((v) => String(v))}
                      value={form.dataBits}
                      onChange={(v) => setField("dataBits", v)}
                    />
                    <Select label="Parity" size="xs" data={[...ALLOWED_PARITY]} value={form.parity} onChange={(v) => setField("parity", v)} />
                  </Group>
                  <Group grow>
                    <Select
                      label="Stop Bits"
                      size="xs"
                      data={[...ALLOWED_STOP_BITS]}
                      value={form.stopBits}
                      onChange={(v) => setField("stopBits", v)}
                    />
                    <Select
                      label="Flow Control"
                      size="xs"
                      data={[...ALLOWED_FLOW_CONTROL]}
                      value={form.flowControl}
                      onChange={(v) => setField("flowControl", v)}
                    />
                  </Group>
                </>
              )}
              {!isKeylessModel && (
                <PasswordInput
                  label="Password"
                  size="xs"
                  value={form.password}
                  onChange={(e) => setField("password", e.currentTarget.value)}
                  description="Sent to the meter. Prefilled with the brand default — clear it to keep the stored password on update."
                />
              )}
            </Section>
          )}

          {/* Billing */}
          <Section title="Billing">
            {selectedDevice && (
              <Group gap={0}>
                <Text size="xs" c="dimmed" style={{ width: "33%" }}>
                  Next Cut Date
                </Text>
                <Tooltip label="No billing day configured for this device" disabled={!!nextCutDate}>
                  <Text size="xs" ff="monospace">
                    {nextCutDate ? formatDateShort(nextCutDate) : "—"}
                  </Text>
                </Tooltip>
              </Group>
            )}
            <DatePickerInput
              label="Bill Start Date"
              size="xs"
              clearable
              valueFormat="YYYY-MM-DD"
              value={form.billStartDate}
              onChange={(v) => setField("billStartDate", v as string | null)}
            />
            <Group grow>
              <Select
                label="Bill Day - Feb (28 days)"
                size="xs"
                placeholder="Day of month"
                clearable
                data={Array.from({ length: 28 }, (_, i) => String(i + 1))}
                value={form.billDayFeb28}
                onChange={(v) => setField("billDayFeb28", v)}
              />
              <Select
                label="Bill Day - Feb (29 days)"
                size="xs"
                placeholder="Day of month"
                clearable
                data={Array.from({ length: 29 }, (_, i) => String(i + 1))}
                value={form.billDayFeb29}
                onChange={(v) => setField("billDayFeb29", v)}
              />
            </Group>
            <Group grow>
              <Select
                label="Bill Day - 30-day months"
                size="xs"
                placeholder="Day of month"
                clearable
                data={Array.from({ length: 30 }, (_, i) => String(i + 1))}
                value={form.billDay30}
                onChange={(v) => setField("billDay30", v)}
              />
              <Select
                label="Bill Day - 31-day months"
                size="xs"
                placeholder="Day of month"
                clearable
                data={Array.from({ length: 31 }, (_, i) => String(i + 1))}
                value={form.billDay31}
                onChange={(v) => setField("billDay31", v)}
              />
            </Group>
          </Section>

          {/* Actions */}
          <Group gap="xs" mb="xs">
            <Button size="xs" leftSection={<IconPlus size={14} />} loading={submitting} onClick={onCreate}>
              {addingWhileSubmitting ? "Checking meter…" : "Create Device"}
            </Button>
            {selectedDevice && (
              <Button size="xs" variant="filled" leftSection={<IconEdit size={14} />} loading={submitting} onClick={onUpdate}>
                Update Device
              </Button>
            )}
            {selectedDevice && (
              <Tooltip label="Start a new device using the current form values as a template">
                <Button size="xs" variant="default" leftSection={<IconCopy size={14} />} onClick={onCopyAsTemplate}>
                  New Device (copy)
                </Button>
              </Tooltip>
            )}
            {selectedDevice && (
              <Tooltip label="Configure meter parameters">
                <Button size="xs" variant="default" leftSection={<IconSettings size={14} />} disabled>
                  Meter Setting
                </Button>
              </Tooltip>
            )}
          </Group>
          {selectedDevice && (
            <Group gap="xs">
              {selectedDevice.source === "dlms" && (
                <Button size="xs" variant="default" leftSection={<IconPlayerPause size={14} />} disabled={selectedDevice.pollingPaused} onClick={onDisconnect}>
                  Disconnect
                </Button>
              )}
              <Button size="xs" variant="default" leftSection={<IconPlayerPlay size={14} />} onClick={onReconnect}>
                Reconnect
              </Button>
              <Button size="xs" color="red" leftSection={<IconTrash size={14} />} onClick={onRemove}>
                Remove Device
              </Button>
              <Button size="xs" color="red" variant="outline" leftSection={<IconEraser size={14} />} disabled>
                Remove All Data
              </Button>
            </Group>
          )}
        </div>
      </div>
    </div>
  );
}

export default function MantineDevicesPage() {
  return (
    <MantineProvider theme={theme}>
      <ModalsProvider>
        <Notifications position="top-right" />
        <DevicesContent />
      </ModalsProvider>
    </MantineProvider>
  );
}
