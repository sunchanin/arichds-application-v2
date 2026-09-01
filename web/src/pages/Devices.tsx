import {
  CopyOutlined,
  DeleteOutlined,
  HistoryOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  SaveOutlined,
  SearchOutlined,
  ThunderboltOutlined,
  WifiOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Divider,
  Drawer,
  Empty,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Tree,
  Typography,
} from "antd";
import type { InputRef } from "antd/es/input";
import type { ColumnsType } from "antd/es/table";
import type { DataNode } from "antd/es/tree";
import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiRequestError,
  api,
  isLicenseLapsed,
  type CatalogEntry,
  type Device,
  type DeviceEvent,
  type DeviceEventKind,
  type DeviceEventPage,
  type DeviceInput,
  type DeviceStatus,
  type Quota,
  type Transport,
} from "../api";
import { DEVICES_REFRESH_MS } from "../theme";

const { Text, Title } = Typography;

/**
 * The four device statuses, as one table (ADR 0004).
 *
 * Every place this page shows a status — the tree dot, the status filter, the
 * selected-device header — reads it from here, so a dot and its filter option
 * can never disagree. The `badge` values are Ant Design's own presets, which
 * are already token-driven: no hex belongs on this page.
 *
 * Module-private rather than exported: nothing outside this file consumes it,
 * and `react-refresh/only-export-components` only exempts *literal* exports
 * (`allowConstantExport` accepts Literal/Unary/Template/Binary and nothing
 * else), so exporting an object here would land a lint warning to no purpose.
 */
const STATUS_PRESENTATION: Record<
  DeviceStatus,
  { badge: "success" | "error" | "default" | "warning"; label: string }
> = {
  online: { badge: "success", label: "Online" },
  offline: { badge: "error", label: "Offline" },
  paused: { badge: "default", label: "Paused" },
  unknown: { badge: "warning", label: "Unknown" },
};

/** What each Device Event kind is called for a person (CONTEXT.md — Device Event). */
const EVENT_LABEL: Record<DeviceEventKind, string> = {
  online: "Went online",
  offline: "Went offline",
  created: "Created",
  updated: "Updated",
  paused: "Paused",
  resumed: "Resumed",
  data_cleared: "Data cleared",
};

/** The Tag colour per event kind. Absent means "no colour" — most kinds carry no alarm. */
const EVENT_COLOR: Partial<Record<DeviceEventKind, string>> = {
  online: "success",
  offline: "error",
  data_cleared: "warning",
};

/**
 * The heading to put above a probe failure, per `ProbeFailure` reason.
 *
 * The API's own sentence is always shown underneath it verbatim; this line only
 * makes the operator's *next action* unambiguous, because fixing a password and
 * fixing an address are different jobs (ADR 0006).
 */
const PROBE_HEADING: Record<string, string> = {
  AUTH_FAILED: "The meter rejected the password.",
  TIMEOUT: "The meter did not answer in time.",
  UNREACHABLE: "No route to the meter at that address.",
  NO_SERIAL: "The meter answered but would not report its serial number.",
};

/** How many history rows one Drawer page holds. The API pages server-side. */
const HISTORY_PAGE_SIZE = 50;

/** Shown wherever a value the meter or the operator never supplied would go. */
const NOTHING = "—";

/**
 * The five parity names the backend's ``-S`` argv parser resolves (issue #9).
 * Sent case-insensitively; the API normalizes to this exact casing.
 */
/**
 * What the Brand and Model pickers say when the licence names an empty model
 * list (issue 015) — distinct from AntD's default "No data", which would read
 * as a failed catalog load rather than a licence that permits nothing.
 */
const NO_LICENSED_MODELS = "This machine's licence permits no meter models. Ask the vendor for a new Activation Code.";

const PARITY_OPTIONS = [
  { value: "None", label: "None" },
  { value: "Odd", label: "Odd" },
  { value: "Even", label: "Even" },
  { value: "Mark", label: "Mark" },
  { value: "Space", label: "Space" },
];

const TRANSPORT_KIND_OPTIONS = [
  { value: "net", label: "TCP" },
  { value: "serial", label: "Serial" },
];

/**
 * The form's own shape: `first_bill_date` is a Dayjs while it is being
 * edited, and the transport fields are flat (issue #9) — `transportKind`
 * decides which group the Connection card renders and which group
 * {@link transportFromForm} reads. The inactive group's fields are simply
 * unused, not cleared, so switching back and forth does not lose what was
 * typed.
 */
interface DeviceFormValues {
  name: string;
  brand: string;
  model: string;
  meter_activation_code: string;
  site_name: string;
  site_code: string;
  customer: string;
  meter_number: string;
  group_name: string;
  transportKind: "net" | "serial";
  host: string;
  port: number;
  serialPort: string;
  baudRate: number;
  dataBits: number;
  parity: string;
  stopBits: number;
  password: string;
  first_bill_date: Dayjs | null;
  bill_day_feb28: number | null;
  bill_day_feb29: number | null;
  bill_day_30: number | null;
  bill_day_31: number | null;
}

const EMPTY_FORM: DeviceFormValues = {
  name: "",
  brand: "",
  model: "",
  meter_activation_code: "",
  site_name: "",
  site_code: "",
  customer: "",
  meter_number: "",
  group_name: "",
  transportKind: "net",
  host: "",
  port: 4059,
  serialPort: "",
  baudRate: 19200,
  dataBits: 8,
  parity: "None",
  stopBits: 1,
  password: "",
  first_bill_date: null,
  bill_day_feb28: null,
  bill_day_feb29: null,
  bill_day_30: null,
  bill_day_31: null,
};

/** Build the {@link Transport} the form currently describes. */
function transportFromForm(values: DeviceFormValues): Transport {
  if (values.transportKind === "serial") {
    return {
      kind: "serial",
      serial_port: values.serialPort.trim(),
      baud_rate: values.baudRate,
      data_bits: values.dataBits,
      parity: values.parity,
      stop_bits: values.stopBits,
    };
  }
  return {
    kind: "net",
    host: values.host.trim(),
    port: values.port,
  };
}

/** A record-only text field: blank is stored as nothing, not as an empty string. */
function blankToNull(value: string | undefined): string | null {
  const trimmed = (value ?? "").trim();
  return trimmed === "" ? null : trimmed;
}

/** Render a UTC timestamp in the operator's own clock, or say it never happened. */
function checkedAt(value: string | null): string {
  return value === null ? "Never checked" : `Checked ${dayjs(value).format("YYYY-MM-DD HH:mm:ss")}`;
}

/**
 * Project a device row onto the form's shape. Password is prefilled from the
 * stored value (owner ruling, 2026-08-11 — meter passwords are not a
 * security boundary, so convenience wins over secrecy).
 */
function toFormValues(device: Device): DeviceFormValues {
  const transport = device.transport;
  return {
    name: device.name,
    brand: device.brand,
    model: device.model,
    // The API never returns a stored code (`DeviceOut` deliberately omits
    // it), and edit never sends one (`toInput`'s `mode === "create"` guard).
    meter_activation_code: "",
    site_name: device.site_name,
    site_code: device.site_code ?? "",
    customer: device.customer ?? "",
    meter_number: device.meter_number ?? "",
    group_name: device.group_name ?? "",
    transportKind: transport.kind,
    host: transport.kind === "net" ? transport.host : "",
    port: transport.kind === "net" ? transport.port : EMPTY_FORM.port,
    serialPort: transport.kind === "serial" ? transport.serial_port : "",
    baudRate: transport.kind === "serial" ? transport.baud_rate : EMPTY_FORM.baudRate,
    dataBits: transport.kind === "serial" ? transport.data_bits : EMPTY_FORM.dataBits,
    parity: transport.kind === "serial" ? transport.parity : EMPTY_FORM.parity,
    stopBits: transport.kind === "serial" ? transport.stop_bits : EMPTY_FORM.stopBits,
    // The API now returns the stored password in the clear (owner ruling,
    // 2026-08-11), so it is visible on open and Test Connection works
    // without retyping. Blank still means "keep it" (D10) — see the Password
    // field's own hint.
    password: device.password,
    first_bill_date: device.first_bill_date ? dayjs(device.first_bill_date) : null,
    bill_day_feb28: device.bill_day_feb28,
    bill_day_feb29: device.bill_day_feb29,
    bill_day_30: device.bill_day_30,
    bill_day_31: device.bill_day_31,
  };
}

/**
 * Build the request body. `meter_serial` is absent by construction (ADR 0005),
 * and so are the two cipher keys: their inputs land with M4, and the API treats
 * an absent secret as "keep the stored one", so omitting them cannot wipe them.
 */
function toInput(values: DeviceFormValues, mode: "create" | "edit"): DeviceInput {
  // Trimmed only to decide whether the field was *left blank* — the value sent
  // is verbatim, because trimming a secret would change it.
  const password = values.password ?? "";
  return {
    name: values.name.trim(),
    brand: values.brand,
    model: values.model,
    site_name: values.site_name.trim(),
    transport: transportFromForm(values),
    // Create only — ADR 0019 checks it once, at Create; Update never
    // re-validates it, so sending it there would be misleading at best.
    ...(mode === "create" ? { meter_activation_code: values.meter_activation_code } : {}),
    site_code: blankToNull(values.site_code),
    customer: blankToNull(values.customer),
    meter_number: blankToNull(values.meter_number),
    group_name: blankToNull(values.group_name),
    first_bill_date: values.first_bill_date ? values.first_bill_date.format("YYYY-MM-DD") : null,
    bill_day_feb28: values.bill_day_feb28 ?? null,
    bill_day_feb29: values.bill_day_feb29 ?? null,
    bill_day_30: values.bill_day_30 ?? null,
    bill_day_31: values.bill_day_31 ?? null,
    // On create the field is prefilled and always sent. On edit a blank field is
    // omitted entirely, which is how the API is told to keep what it has (D10).
    ...(mode === "create" || password.trim() !== "" ? { password } : {}),
  };
}

/**
 * Device Manager (M3-3) — the site tree on the left, one device's form on the
 * right, and every meter action underneath it.
 *
 * **One list call paints everything.** The tree, the status dots, the quota chip
 * and the form's prefill all come from `GET /api/devices` plus `GET
 * /api/devices/quota`, re-read every {@link DEVICES_REFRESH_MS}. Search and the
 * two filters run over that already-fetched array — a request per device to
 * paint a tree of 10-30 meters is the N+1 that issue #5 put `status` on the list
 * response to prevent.
 *
 * **The timer never touches the form.** Fields are written only by an explicit
 * action — selecting a node, New Device (copy), or a successful save. A
 * background refresh that reset the fields under a typing operator is the one
 * bug a polling form page is prone to, and keeping `selectedId` (not a device
 * object) in state is what rules it out.
 *
 * **No electrical value appears anywhere here** (ADR 0007). Read now reports
 * whether the meter answered, never what it measured.
 *
 * A `user` sees every field and every value, can press Read now and History, and
 * is never shown a control it may not use — discovering a permission by
 * collecting a 403 is not a design (SPEC §3.2).
 */
export function Devices({
  role,
  licensedModels,
}: {
  role: "admin" | "user";
  /**
   * The model keys this machine's licence permits **adding** (issue 015), or
   * `null` for no restriction — which is what every licence issued before the
   * model lock carries. `[]` means none may be added.
   */
  licensedModels: string[] | null;
}) {
  const { message, modal } = App.useApp();
  const isAdmin = role === "admin";

  const [devices, setDevices] = useState<Device[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [quota, setQuota] = useState<Quota | null>(null);
  const [loading, setLoading] = useState(true);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [expandedKeys, setExpandedKeys] = useState<string[] | null>(null);

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<DeviceStatus | "all">("all");
  const [modelFilter, setModelFilter] = useState("all");

  const [saving, setSaving] = useState(false);
  const [acting, setActing] = useState<string | null>(null);

  const [historyId, setHistoryId] = useState<number | null>(null);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyData, setHistoryData] = useState<DeviceEventPage | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  const [clearOpen, setClearOpen] = useState(false);
  const [clearTyped, setClearTyped] = useState("");
  const [clearing, setClearing] = useState(false);

  const [form] = Form.useForm<DeviceFormValues>();
  const passwordRef = useRef<InputRef>(null);
  const watchedBrand = Form.useWatch("brand", form);
  const watchedTransportKind = Form.useWatch("transportKind", form);
  const watchedHost = Form.useWatch("host", form);
  const watchedPort = Form.useWatch("port", form);
  const watchedSerialPort = Form.useWatch("serialPort", form);
  const watchedModel = Form.useWatch("model", form);

  const selected = devices.find((device) => device.id === selectedId) ?? null;
  const mode: "create" | "edit" = selected ? "edit" : "create";

  // ─── Loading ────────────────────────────────────────────────────────────────

  const refresh = useCallback(async () => {
    try {
      const [list, currentQuota] = await Promise.all([api.listDevices(), api.quota()]);
      setDevices(list);
      setQuota(currentQuota);
    } catch (err) {
      if (isLicenseLapsed(err)) {
        // The lease lapsed while the page was open. Reload so the app falls back
        // to Activation — the only screen that can fix the machine.
        window.location.reload();
        return;
      }
      message.error(err instanceof ApiRequestError ? err.message : "Could not load devices");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    // Every setState below lands in a promise callback once the API answers,
    // never synchronously in the effect body. Polling a backend on a timer is
    // the external-system subscription the rule permits.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    api
      .catalog()
      .then(setCatalog)
      .catch((err: unknown) => {
        setCatalog([]);
        // Not swallowed: with no catalog the Brand and Model lists are empty and
        // no meter can be added, which needs saying. A lapsed license is the one
        // exception — `refresh` above is already reloading the app for it.
        if (!isLicenseLapsed(err)) {
          message.error("Could not load the meter catalog — the Brand and Model lists will be empty.");
        }
      });
    const timer = window.setInterval(() => void refresh(), DEVICES_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [refresh, message]);

  // ─── Errors ─────────────────────────────────────────────────────────────────

  /**
   * Show what actually went wrong.
   *
   * A lapsed license is not an error message, it is a different screen. A probe
   * failure gets a modal with a heading naming the next action and the API's own
   * sentence under it — it can run to a paragraph, and it is the difference
   * between fixing a password and fixing a cable.
   */
  /** Present a meter-side refusal: heading by reason, then the API's sentence. */
  const showProbeFailure = useCallback(
    (reason: string | null, detail: string) => {
      modal.error({
        title: (reason && PROBE_HEADING[reason]) || "The meter refused the read.",
        content: detail,
        okText: "Close",
        // The password is the field to fix, so put the cursor in it on the way out.
        afterClose: reason === "AUTH_FAILED" ? () => passwordRef.current?.focus() : undefined,
      });
    },
    [modal],
  );

  const surface = useCallback(
    (err: unknown, fallback: string) => {
      if (isLicenseLapsed(err)) {
        window.location.reload();
        return;
      }
      if (err instanceof ApiRequestError && err.code === "PROBE_FAILED") {
        showProbeFailure(err.reason, err.message);
        return;
      }
      message.error(err instanceof ApiRequestError ? err.message : fallback);
    },
    [message, showProbeFailure],
  );

  // ─── Catalog ────────────────────────────────────────────────────────────────

  /**
   * The catalog narrowed to what the licence permits adding (issue 015).
   *
   * **Only the Brand and Model pickers read this** — `applyModelDefaults` and
   * `modelFilterOptions` keep reading the full `catalog`, because a device that
   * predates a narrowed licence is still polled and still listed (issue 015 D6),
   * and it must keep its label and its password default. Narrowing those too
   * would blank a grandfathered row's own name in its own tree.
   *
   * `null` means no restriction — every licence issued before the model lock
   * carries no `models` key at all — so the pickers behave exactly as before.
   *
   * This is a **convenience, never the gate**: `POST`/`PUT /api/devices` refuse
   * an unlicensed model with 422 whatever the dropdown offered.
   */
  const licensedCatalog = useMemo(() => {
    if (licensedModels === null) return catalog;
    const allowed = new Set(licensedModels);
    return catalog.filter((entry) => allowed.has(entry.model));
  }, [catalog, licensedModels]);

  /** A licence that names an empty model list forbids adding anything at all. */
  const noLicensedModels = licensedModels !== null && licensedModels.length === 0;

  const brandOptions = useMemo(() => {
    const brands = new Set(licensedCatalog.map((entry) => entry.brand));
    // A row created before this build's catalog (SPEC §3.3) — or before the
    // licence narrowed — keeps its own brand selectable, or opening it would
    // silently blank the field.
    if (watchedBrand) brands.add(watchedBrand);
    return [...brands].sort().map((brand) => ({ value: brand, label: brand }));
  }, [licensedCatalog, watchedBrand]);

  const modelOptions = useMemo(() => {
    const forBrand = licensedCatalog.filter((entry) => entry.brand === watchedBrand);
    const options = forBrand.map((entry) => ({ value: entry.model, label: entry.ui_label }));
    if (watchedModel && !forBrand.some((entry) => entry.model === watchedModel)) {
      // Two different reasons a stored model is missing from the list, and the
      // operator needs to be told which: the build has no driver for it, or it
      // has one and the licence does not cover it. Either way the value stays
      // selectable so editing an existing row cannot blank its own model.
      const known = catalog.some((entry) => entry.model === watchedModel);
      options.push({
        value: watchedModel,
        label: known ? `${watchedModel} (not licensed on this machine)` : `${watchedModel} (no driver in this build)`,
      });
    }
    return options;
  }, [catalog, licensedCatalog, watchedBrand, watchedModel]);

  /**
   * Apply what the catalog knows about a model: on create, its password.
   *
   * The catalog carries no transport information (issue #9) — every model is
   * offered both transports, so there is no per-model port to prefill; the
   * Port field's own default (4059, in {@link EMPTY_FORM}) covers it.
   */
  const applyModelDefaults = useCallback(
    (model: string, target: "create" | "edit") => {
      const entry = catalog.find((candidate) => candidate.model === model);
      if (!entry) return;
      if (target === "create" && entry.fixed_password !== null) {
        form.setFieldsValue({ password: entry.fixed_password });
      }
    },
    [catalog, form],
  );

  /** Choosing a brand narrows the models — and picks the only one when there is only one. */
  const onBrandChange = (brand: string) => {
    const forBrand = licensedCatalog.filter((entry) => entry.brand === brand);
    if (forBrand.length === 1) {
      form.setFieldsValue({ model: forBrand[0].model });
      applyModelDefaults(forBrand[0].model, mode);
    } else {
      form.setFieldsValue({ model: "" });
    }
  };

  // ─── Filtering and the tree ─────────────────────────────────────────────────

  /** Every brand+model pair the loaded devices actually use, labelled from the catalog. */
  const modelFilterOptions = useMemo(() => {
    const pairs = new Map<string, string>();
    for (const device of devices) {
      const key = `${device.brand}|${device.model}`;
      if (pairs.has(key)) continue;
      const entry = catalog.find((candidate) => candidate.model === device.model && candidate.brand === device.brand);
      pairs.set(key, entry ? entry.ui_label : `${device.brand} · ${device.model}`);
    }
    return [
      { value: "all", label: "All models" },
      ...[...pairs].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label)),
    ];
  }, [devices, catalog]);

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return devices.filter((device) => {
      if (statusFilter !== "all" && device.status !== statusFilter) return false;
      if (modelFilter !== "all" && `${device.brand}|${device.model}` !== modelFilter) return false;
      if (needle === "") return true;
      return (
        device.name.toLowerCase().includes(needle) ||
        (device.meter_serial ?? "").toLowerCase().includes(needle)
      );
    });
  }, [devices, search, statusFilter, modelFilter]);

  const treeData = useMemo<DataNode[]>(() => {
    const bySite = new Map<string, Device[]>();
    for (const device of visible) {
      const group = bySite.get(device.site_name);
      if (group) group.push(device);
      else bySite.set(device.site_name, [device]);
    }
    return [...bySite.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([site, members]) => ({
        key: siteKey(site),
        // A site is a heading, not a thing you can edit — clicking it must not
        // load a form.
        selectable: false,
        title: (
          <Text strong>
            {site} ({members.length})
          </Text>
        ),
        children: members
          .slice()
          .sort((a, b) => a.name.localeCompare(b.name))
          .map((device) => ({
            key: String(device.id),
            isLeaf: true,
            title: <DeviceLeaf device={device} />,
          })),
      }));
  }, [visible]);

  const allSiteKeys = useMemo(() => treeData.map((node) => String(node.key)), [treeData]);

  // ─── Form population — only ever from an explicit action ────────────────────

  /** Replace every field at once, so nothing from the previous device survives. */
  const fill = useCallback(
    (values: DeviceFormValues) => {
      form.resetFields();
      form.setFieldsValue(values);
    },
    [form],
  );

  const selectDevice = (device: Device) => {
    setSelectedId(device.id);
    fill(toFormValues(device));
  };

  const startCreate = () => {
    setSelectedId(null);
    fill(EMPTY_FORM);
  };

  /**
   * Keep the current values as a template for a second meter on the same site.
   *
   * The name is cleared because it must be unique — a copied name is a
   * guaranteed 409 — and the password goes back to the brand default, since the
   * field was blank while editing and blank on a *create* would send nothing.
   * The Meter Activation Code is cleared for the same reason as the name: a
   * copied code belongs to the other meter, and pasting it here is a
   * guaranteed refusal (ADR 0019 — a code is bound to one Meter Serial).
   */
  const copyDevice = () => {
    const values = form.getFieldsValue();
    const entry = catalog.find((candidate) => candidate.model === values.model);
    setSelectedId(null);
    fill({ ...values, name: "", password: entry?.fixed_password ?? "", meter_activation_code: "" });
  };

  // ─── Actions ────────────────────────────────────────────────────────────────

  const save = async (values: DeviceFormValues) => {
    setSaving(true);
    try {
      const saved =
        mode === "edit" && selected
          ? await api.updateDevice(selected.id, toInput(values, "edit"))
          : await api.createDevice(toInput(values, "create"));
      message.success(mode === "edit" ? `Updated ${saved.name}` : `Created ${saved.name}`);
      // Refresh first: selecting an id the list does not carry yet would flip
      // the panel back to "New device" for a render.
      await refresh();
      setSelectedId(saved.id);
      fill(toFormValues(saved));
    } catch (err) {
      surface(err, mode === "edit" ? "Could not update the device" : "Could not create the device");
    } finally {
      setSaving(false);
    }
  };

  const run = async (label: string, action: () => Promise<void>) => {
    setActing(label);
    try {
      await action();
    } finally {
      setActing(null);
    }
  };

  const togglePause = (device: Device) =>
    run(device.enabled ? "pause" : "resume", async () => {
      try {
        const updated = device.enabled ? await api.pauseDevice(device.id) : await api.resumeDevice(device.id);
        message.success(updated.enabled ? `Resumed ${updated.name}` : `Paused ${updated.name}`);
        await refresh();
      } catch (err) {
        surface(err, "Could not change the pause state");
      }
    });

  const readNow = (device: Device) =>
    run("read", async () => {
      try {
        const result = await api.readNow(device.id);
        modal.info({
          title: `Read now — ${device.name}`,
          width: 520,
          okText: "Close",
          content: (
            <Space direction="vertical" size="small" style={{ width: "100%", marginBlockStart: 8 }}>
              {result.results.map((job) => (
                <Space key={job.job} align="start">
                  <Text code>{job.job}</Text>
                  <Tag color={job.ok ? "success" : "error"}>{job.ok ? "Succeeded" : "Failed"}</Tag>
                  <Text>{job.detail}</Text>
                </Space>
              ))}
            </Space>
          ),
        });
        // Show what this click just proved, without waiting for the next timer.
        setDevices((current) =>
          current.map((candidate) =>
            candidate.id === device.id
              ? { ...candidate, status: result.status, status_checked_at: result.checked_at }
              : candidate,
          ),
        );
        await refresh();
      } catch (err) {
        surface(err, "Could not read the meter");
      }
    });

  const testConnection = () =>
    run("test", async () => {
      // The form's own rules first. Test connection is the one action with no
      // `htmlType="submit"` behind it, so without this a blank Model or a blank
      // transport field goes to the server and comes back as a 422 saying what
      // the field already knew — and the operator gets a server error where a
      // field error belongs. Which fields depends on the Transport switch.
      // Password is deliberately not validated: it has no rule, and a meter may
      // legitimately have none.
      const kind = form.getFieldValue("transportKind") as "net" | "serial";
      const transportFields =
        kind === "serial"
          ? ["serialPort", "baudRate", "dataBits", "parity", "stopBits"]
          : ["host", "port"];
      try {
        await form.validateFields(["model", ...transportFields]);
      } catch {
        // `validateFields` has already marked the offending fields on screen;
        // there is nothing left to say and nothing to send.
        return;
      }

      try {
        const values = form.getFieldsValue();
        const result = await api.testConnection({
          model: values.model,
          transport: transportFromForm(values),
          // Verbatim: a password is not a label, and trimming one changes it.
          password: values.password ?? "",
        });
        if (result.reachable) {
          message.success(result.message);
        } else {
          showProbeFailure(result.reason, result.message);
        }
      } catch (err) {
        surface(err, "Could not test the connection");
      }
    });

  const confirmDelete = (device: Device) => {
    modal.confirm({
      title: `Delete ${device.name}?`,
      content: `Its stored readings are deleted with it. The meter itself is untouched.`,
      okText: "Delete device",
      okType: "danger",
      onOk: async () => {
        try {
          await api.deleteDevice(device.id);
          message.success(`Deleted ${device.name}`);
          startCreate();
          await refresh();
        } catch (err) {
          surface(err, "Could not delete the device");
        }
      },
    });
  };

  const clearReadings = async () => {
    if (!selected) return;
    setClearing(true);
    try {
      const deleted = await api.clearReadings(selected.id, clearTyped);
      message.success(`Deleted ${deleted} readings.`);
      closeClear();
      await refresh();
    } catch (err) {
      surface(err, "Could not delete the readings");
    } finally {
      setClearing(false);
    }
  };

  const closeClear = () => {
    setClearOpen(false);
    setClearTyped("");
  };

  // ─── History ────────────────────────────────────────────────────────────────

  const openHistory = (device: Device) => {
    setHistoryData(null);
    setHistoryPage(1);
    setHistoryId(device.id);
  };

  useEffect(() => {
    if (historyId === null) return;
    let live = true;
    // The drawer's own spinner. Every other setState here lands in a promise
    // callback once the API answers.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHistoryLoading(true);
    api
      .deviceEvents(historyId, HISTORY_PAGE_SIZE, (historyPage - 1) * HISTORY_PAGE_SIZE)
      .then((page) => {
        if (live) setHistoryData(page);
      })
      .catch((err: unknown) => {
        if (live) surface(err, "Could not load the history");
      })
      .finally(() => {
        if (live) setHistoryLoading(false);
      });
    return () => {
      live = false;
    };
  }, [historyId, historyPage, surface]);

  const historyDevice = devices.find((device) => device.id === historyId) ?? null;

  // ─── Render ─────────────────────────────────────────────────────────────────

  const busy = saving || acting !== null;
  const meterSerial = selected?.meter_serial ?? null;

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Flex justify="space-between" align="flex-start" gap="middle" wrap>
        <div>
          <Title level={4} style={{ margin: 0 }}>
            Devices
          </Title>
          <Text type="secondary">
            Every meter on this machine. Status comes from the 60-second poll — nothing here asks a meter
            anything until you press a button.
          </Text>
        </div>
        <QuotaChip quota={quota} />
      </Flex>

      {quota?.over_quota ? (
        <Alert
          type="warning"
          showIcon
          message="More meters than this license allows"
          description="Every meter listed keeps being read. No new one can be added until the license is raised or a device is deleted."
        />
      ) : null}

      <Row gutter={16} align="top">
        <Col xs={24} lg={8} xl={7} style={{ maxWidth: 360 }}>
          <Card
            size="small"
            loading={loading}
            title={
              visible.length === devices.length
                ? `${devices.length} meters`
                : `${visible.length} of ${devices.length} shown`
            }
          >
            <Space direction="vertical" size="small" style={{ width: "100%" }}>
              <Input
                allowClear
                prefix={<SearchOutlined />}
                placeholder="Search name or Meter Serial"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              <Space.Compact block>
                <Select
                  style={{ width: "50%" }}
                  value={statusFilter}
                  onChange={setStatusFilter}
                  options={[
                    { value: "all", label: "All statuses" },
                    ...(Object.keys(STATUS_PRESENTATION) as DeviceStatus[]).map((status) => ({
                      value: status,
                      label: STATUS_PRESENTATION[status].label,
                    })),
                  ]}
                />
                <Select
                  style={{ width: "50%" }}
                  value={modelFilter}
                  onChange={setModelFilter}
                  options={modelFilterOptions}
                />
              </Space.Compact>

              {devices.length === 0 ? (
                <Empty description="No meters yet. Fill in the form and press Create Device — the meter must be reachable, because its serial number is read from it." />
              ) : treeData.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="No meters match these filters."
                />
              ) : (
                <Tree
                  blockNode
                  treeData={treeData}
                  selectedKeys={selectedId === null ? [] : [String(selectedId)]}
                  expandedKeys={expandedKeys ?? allSiteKeys}
                  onExpand={(keys) => setExpandedKeys(keys.map(String))}
                  onSelect={(keys) => {
                    const key = keys[0];
                    // Clicking the selected meter again deselects it, which is
                    // the way back to an empty create form.
                    if (key === undefined) {
                      startCreate();
                      return;
                    }
                    const device = devices.find((candidate) => String(candidate.id) === String(key));
                    if (device) selectDevice(device);
                  }}
                />
              )}
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={16} xl={17}>
          <Card
            size="small"
            title={
              selected ? (
                <Space size="small" wrap>
                  <Badge
                    status={STATUS_PRESENTATION[selected.status].badge}
                    text={STATUS_PRESENTATION[selected.status].label}
                  />
                  <Text strong>{selected.name}</Text>
                  <Text type="secondary" style={{ fontWeight: 400 }}>
                    {selected.endpoint} · {checkedAt(selected.status_checked_at)}
                  </Text>
                </Space>
              ) : (
                "New device"
              )
            }
          >
            {selected?.status_detail ? (
              <Alert type="info" showIcon message={selected.status_detail} style={{ marginBlockEnd: 12 }} />
            ) : null}

            <Form
              form={form}
              layout="vertical"
              initialValues={EMPTY_FORM}
              disabled={!isAdmin || saving}
              onFinish={(values) => void save(values)}
            >
              <Space direction="vertical" size="small" style={{ width: "100%" }}>
                <Card size="small" title="Identity" type="inner">
                  <Row gutter={12}>
                    <Col xs={24} md={8}>
                      <Form.Item
                        name="name"
                        label="Device Name"
                        rules={[{ required: true, message: "Name this device." }]}
                      >
                        <Input placeholder="Main Incomer" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      {/* Deliberately nameless: the Meter Serial is read off the
                          meter (ADR 0005), so it must not be able to reach the
                          submitted values at all. */}
                      <Form.Item label="Meter Serial" extra={serialHint(mode, meterSerial)}>
                        <Typography.Text>{meterSerial ?? NOTHING}</Typography.Text>
                      </Form.Item>
                    </Col>
                    {mode === "create" ? (
                      <Col xs={24} md={8}>
                        <Form.Item
                          name="meter_activation_code"
                          label="Meter Activation Code"
                          rules={[{ required: true, message: "Paste the code the vendor issued for this meter." }]}
                          extra="Test connection to read the Meter Serial, ask the vendor for a code, then paste it here before Create Device."
                        >
                          <Input.TextArea
                            rows={2}
                            placeholder="Paste the code the vendor issued"
                            style={{ fontFamily: "monospace", fontSize: 12 }}
                          />
                        </Form.Item>
                      </Col>
                    ) : null}
                    <Col xs={24} md={8}>
                      <Form.Item name="site_code" label="Site Code">
                        <Input placeholder="Optional" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item
                        name="site_name"
                        label="Site Name"
                        rules={[{ required: true, message: "Every meter belongs to a site." }]}
                      >
                        <Input placeholder="Plant A" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item name="customer" label="Customer Name">
                        <Input placeholder="Optional" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item name="meter_number" label="Meter Number">
                        <Input placeholder="Optional" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item name="group_name" label="Group">
                        <Input placeholder="Optional" />
                      </Form.Item>
                    </Col>
                  </Row>
                </Card>

                <Card size="small" title="Meter" type="inner">
                  <Row gutter={12}>
                    <Col xs={24} md={8}>
                      <Form.Item name="brand" label="Brand" rules={[{ required: true, message: "Pick a brand." }]}>
                        <Select
                          placeholder="Select"
                          options={brandOptions}
                          onChange={onBrandChange}
                          notFoundContent={noLicensedModels ? NO_LICENSED_MODELS : undefined}
                        />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={8}>
                      <Form.Item name="model" label="Model" rules={[{ required: true, message: "Pick a model." }]}>
                        <Select
                          placeholder="Select"
                          options={modelOptions}
                          onChange={(model: string) => applyModelDefaults(model, mode)}
                          notFoundContent={noLicensedModels ? NO_LICENSED_MODELS : undefined}
                        />
                      </Form.Item>
                    </Col>
                  </Row>
                </Card>

                <Card size="small" title="Connection" type="inner">
                  <Row gutter={12}>
                    <Col xs={24} md={8}>
                      <Form.Item name="transportKind" label="Transport">
                        <Segmented options={TRANSPORT_KIND_OPTIONS} />
                      </Form.Item>
                    </Col>
                  </Row>
                  {watchedTransportKind === "serial" ? (
                    <Row gutter={12}>
                      <Col xs={24} md={8}>
                        <Form.Item
                          name="serialPort"
                          label="COM Port"
                          rules={[{ required: true, message: "Which COM port?" }]}
                        >
                          <Input placeholder="COM4" />
                        </Form.Item>
                      </Col>
                      <Col xs={12} md={4}>
                        <Form.Item
                          name="baudRate"
                          label="Baud Rate"
                          rules={[{ required: true, message: "Baud rate?" }]}
                        >
                          <InputNumber min={110} max={1_000_000} style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                      <Col xs={12} md={4}>
                        <Form.Item
                          name="dataBits"
                          label="Data Bits"
                          rules={[{ required: true, message: "Data bits?" }]}
                        >
                          <InputNumber min={5} max={8} style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                      <Col xs={12} md={4}>
                        <Form.Item name="parity" label="Parity" rules={[{ required: true, message: "Parity?" }]}>
                          <Select options={PARITY_OPTIONS} />
                        </Form.Item>
                      </Col>
                      <Col xs={12} md={4}>
                        <Form.Item
                          name="stopBits"
                          label="Stop Bits"
                          rules={[{ required: true, message: "Stop bits?" }]}
                        >
                          <InputNumber min={1} max={2} style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                    </Row>
                  ) : (
                    <Row gutter={12}>
                      <Col xs={24} md={8}>
                        <Form.Item
                          name="host"
                          label="IP Address"
                          rules={[{ required: true, message: "Where is the meter?" }]}
                        >
                          <Input placeholder="192.168.1.100" />
                        </Form.Item>
                      </Col>
                      <Col xs={12} md={4}>
                        <Form.Item name="port" label="Port" rules={[{ required: true, message: "Port?" }]}>
                          <InputNumber min={1} max={65535} style={{ width: "100%" }} />
                        </Form.Item>
                      </Col>
                    </Row>
                  )}
                  <Row gutter={12}>
                    <Col xs={24} md={8}>
                      <Form.Item
                        name="password"
                        label="Password"
                        extra={mode === "edit" ? "Leave blank to keep the current password." : undefined}
                      >
                        <Input.Password
                          ref={passwordRef}
                          autoComplete="new-password"
                          placeholder={
                            mode === "edit" ? "Leave blank to keep the current password" : "Meter password"
                          }
                        />
                      </Form.Item>
                    </Col>
                  </Row>
                </Card>

                <Card size="small" title="Billing" type="inner">
                  <Row gutter={12}>
                    <Col xs={24} md={8}>
                      <Form.Item name="first_bill_date" label="Bill Start Date">
                        <DatePicker style={{ width: "100%" }} format="YYYY-MM-DD" />
                      </Form.Item>
                    </Col>
                    <Col xs={12} md={4}>
                      <Form.Item name="bill_day_feb28" label="Bill Day — February (28 days)">
                        <InputNumber min={1} max={28} style={{ width: "100%" }} />
                      </Form.Item>
                    </Col>
                    <Col xs={12} md={4}>
                      <Form.Item name="bill_day_feb29" label="Bill Day — February (29 days)">
                        <InputNumber min={1} max={29} style={{ width: "100%" }} />
                      </Form.Item>
                    </Col>
                    <Col xs={12} md={4}>
                      <Form.Item name="bill_day_30" label="Bill Day — 30-day months">
                        <InputNumber min={1} max={30} style={{ width: "100%" }} />
                      </Form.Item>
                    </Col>
                    <Col xs={12} md={4}>
                      <Form.Item name="bill_day_31" label="Bill Day — 31-day months">
                        <InputNumber min={1} max={31} style={{ width: "100%" }} />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Text type="secondary">These are stored only — the period logic arrives with Billing (M6).</Text>
                </Card>
              </Space>
            </Form>

            <Divider style={{ marginBlock: 12 }} />

            {/* Outside the Form on purpose: a disabled Form disables every Button
                inside it, and Read now and History belong to every role. */}
            <Space size="small" wrap>
              {isAdmin ? (
                <Button
                  type="primary"
                  icon={mode === "edit" ? <SaveOutlined /> : <PlusOutlined />}
                  loading={saving}
                  disabled={busy}
                  onClick={() => form.submit()}
                >
                  {mode === "edit" ? "Update Device" : "Create Device"}
                </Button>
              ) : null}
              {isAdmin ? (
                <Button icon={<CopyOutlined />} disabled={!selected || busy} onClick={copyDevice}>
                  New Device (copy)
                </Button>
              ) : null}
              {isAdmin ? (
                <Button
                  icon={selected?.enabled === false ? <PlayCircleOutlined /> : <PauseCircleOutlined />}
                  loading={acting === "pause" || acting === "resume"}
                  disabled={!selected || busy}
                  onClick={() => selected && void togglePause(selected)}
                >
                  {selected?.enabled === false ? "Resume" : "Pause"}
                </Button>
              ) : null}

              {/* The separators group by consequence — edit · read · destroy.
                  A `user` sees none of the first group, so its divider goes too
                  rather than opening the row with a rule against nothing. */}
              {isAdmin ? <Divider type="vertical" style={{ height: 24 }} /> : null}

              <Tooltip title="Read this meter now instead of waiting for the next 60-second cycle.">
                <Button
                  icon={<ThunderboltOutlined />}
                  loading={acting === "read"}
                  disabled={!selected || busy}
                  onClick={() => selected && void readNow(selected)}
                >
                  Read now
                </Button>
              </Tooltip>
              {isAdmin ? (
                <Button
                  icon={<WifiOutlined />}
                  loading={acting === "test"}
                  disabled={busy}
                  onClick={() => void testConnection()}
                >
                  Test connection
                </Button>
              ) : null}
              <Button
                icon={<HistoryOutlined />}
                disabled={!selected}
                onClick={() => selected && openHistory(selected)}
              >
                History
              </Button>

              {isAdmin ? <Divider type="vertical" style={{ height: 24 }} /> : null}

              {isAdmin ? (
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  disabled={!selected || busy}
                  onClick={() => selected && confirmDelete(selected)}
                >
                  Delete
                </Button>
              ) : null}
              {isAdmin ? (
                <Button danger disabled={!selected || busy} onClick={() => setClearOpen(true)}>
                  Delete all data
                </Button>
              ) : null}
            </Space>

            {saving ? (
              <div style={{ marginBlockStart: 8 }}>
                <Text type="secondary">
                  Connecting to the meter at{" "}
                  {watchedTransportKind === "serial"
                    ? (watchedSerialPort ?? "").trim() || NOTHING
                    : `${(watchedHost ?? "").trim() || NOTHING}:${watchedPort ?? NOTHING}`}{" "}
                  to read its serial number…
                </Text>
              </div>
            ) : null}
          </Card>
        </Col>
      </Row>

      <Drawer
        open={historyId !== null}
        onClose={() => setHistoryId(null)}
        width={720}
        title={historyDevice ? `History — ${historyDevice.name}` : "History"}
      >
        <Table<DeviceEvent>
          rowKey="id"
          size="small"
          loading={historyLoading}
          dataSource={historyData?.items ?? []}
          columns={HISTORY_COLUMNS}
          pagination={{
            current: historyPage,
            pageSize: HISTORY_PAGE_SIZE,
            total: historyData?.total ?? 0,
            showSizeChanger: false,
            onChange: setHistoryPage,
          }}
        />
      </Drawer>

      <Modal
        open={clearOpen}
        title={selected ? `Delete all data for ${selected.name}` : "Delete all data"}
        okText="Delete all data"
        okButtonProps={{ danger: true, disabled: selected === null || clearTyped !== selected.name }}
        confirmLoading={clearing}
        onOk={() => void clearReadings()}
        onCancel={closeClear}
        destroyOnHidden
      >
        <Space direction="vertical" size="small" style={{ width: "100%" }}>
          <Text>
            This permanently deletes every stored Interval Reading and billing period for{" "}
            {selected?.name ?? NOTHING}. The device itself and its history are kept. This cannot be undone.
          </Text>
          <Text type="secondary">
            Billing periods still held by the meter come back on the next read — this repairs a value that was
            wrong on our side, but it is a no-op for a value the meter itself reports.
          </Text>
          <Text type="secondary">Type the device name to confirm.</Text>
          <Input
            autoFocus
            value={clearTyped}
            placeholder={selected?.name ?? ""}
            onChange={(event) => setClearTyped(event.target.value)}
          />
        </Space>
      </Modal>
    </Space>
  );
}

/** The key of a site heading — prefixed so it can never collide with a device id. */
function siteKey(site: string): string {
  return `site:${site}`;
}

/** What to say under the Meter Serial, given where the operator is. */
function serialHint(mode: "create" | "edit", serial: string | null): string {
  if (mode === "create") {
    return "Assigned automatically by the system — it is read from the meter when you press Create Device.";
  }
  return serial === null
    ? "Assigned automatically by the system — press Update to identify this meter."
    : "Assigned automatically by the system.";
}

/**
 * One meter in the tree: a fixed-width dot gutter, the name, the serial beneath.
 *
 * The gutter is what makes 30 meters scannable in one vertical sweep — every dot
 * lands on the same x, so "which of these is dark" is one look, not a read.
 */
function DeviceLeaf({ device }: { device: Device }) {
  const presentation = STATUS_PRESENTATION[device.status];
  return (
    <Space size="small" align="start">
      <span
        role="img"
        // The dot is otherwise colour-only, which is no signal at all to a
        // screen reader or to an operator who cannot tell red from green.
        aria-label={presentation.label}
        title={presentation.label}
        style={{ display: "inline-flex", width: 12, justifyContent: "center" }}
      >
        <Badge status={presentation.badge} />
      </span>
      <span>
        <div>{device.name}</div>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {device.meter_serial ?? NOTHING}
        </Text>
      </span>
    </Space>
  );
}

/** How many meters this machine has, against how many it may have. */
function QuotaChip({ quota }: { quota: Quota | null }) {
  if (quota === null) return null;
  if (quota.over_quota) {
    return <Tag color="warning">{`${quota.used} / ${quota.max_meters} — over quota`}</Tag>;
  }
  return (
    <Tag>{quota.max_meters === null ? `${quota.used} meters · unlimited` : `${quota.used} / ${quota.max_meters} meters`}</Tag>
  );
}

const HISTORY_COLUMNS: ColumnsType<DeviceEvent> = [
  {
    title: "When",
    dataIndex: "created_at",
    key: "created_at",
    width: 170,
    render: (createdAt: string) => dayjs(createdAt).format("YYYY-MM-DD HH:mm:ss"),
  },
  {
    title: "Event",
    dataIndex: "kind",
    key: "kind",
    width: 130,
    // Falls back to the raw kind: a kind this build has no label for must still
    // read as something, not as an empty tag.
    render: (kind: DeviceEventKind) => <Tag color={EVENT_COLOR[kind]}>{EVENT_LABEL[kind] ?? kind}</Tag>,
  },
  {
    title: "By",
    dataIndex: "actor",
    key: "actor",
    width: 120,
    // Null is not "system": a meter that went offline was nobody's action (D11).
    render: (actor: string | null) => actor ?? NOTHING,
  },
  { title: "Detail", dataIndex: "detail", key: "detail", render: (detail: string | null) => detail ?? NOTHING },
];
