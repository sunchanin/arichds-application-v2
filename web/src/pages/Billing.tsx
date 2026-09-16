import {
  App,
  Badge,
  Button,
  Card,
  DatePicker,
  Empty,
  Flex,
  Form,
  Input,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TabsProps } from "antd/es/tabs";
import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiRequestError,
  api,
  downloadBillingImage,
  isLicenseLapsed,
  type AllMetersRow,
  type AllMetersStatus,
  type AllMetersView,
  type BillingPage as BillingPageData,
  type BillingRow,
  type BillingSettings,
  type BillingStatus,
  type Device,
} from "../api";
import { latestBillRowId } from "../billingHighlight";
import { captureRequest } from "../capture";
import { type DisplayUnitScale, type UnitKind, scaleValue, unitLabel, useDisplayUnitScale } from "../units";

const { RangePicker } = DatePicker;

/** Shown wherever the meter never captured a quantity. A genuine 0 must still
 * render as `0` — see `num()` below. */
const NOTHING = "—";
/** The History row carrying the newest closed period (ui-audit ticket 09) —
 * the class `index.css` tints in v1's exact lavender, so the capture PNG (a
 * screenshot of this page, ADR 0017) matches the customer's v1 screenshot. */
const LATEST_BILL_ROW_CLASS = "latest-bill-row";
const { Text } = Typography;

const PAGE_SIZE_OPTIONS = [50, 100, 200, 500];
const DEFAULT_PAGE_SIZE = 100;

/** The sentinel the device filter's "All" option carries. Devices have
 * numeric ids, so it cannot collide. */
const ALL = "all";

/**
 * Render a measurement, or an em dash when the meter never captured it.
 *
 * Same rule as `LoadProfile.tsx`'s `num()`: `value == null` catches `null`
 * and `undefined` and nothing else, so a genuine reading of 0 kW never
 * degrades to a dash.
 */
const num =
  (digits: number) =>
  (value: number | null): string =>
    value == null ? NOTHING : value.toFixed(digits);

const num3 = num(3);

/** Format a Demand Time cell — a timestamp, not a number (D20, M4c issue #24). */
const time = (value: string | null): string => (value == null ? NOTHING : dayjs(value).format("YYYY-MM-DD HH:mm:ss"));

/** The four tariffs plus the total — every measurement group has exactly
 * these five children (D20), mirroring `capture/_render_shared.py`'s
 * `_measurement_section`. */
const RATE_SUFFIXES = ["total", "rate_a", "rate_b", "rate_c", "rate_d"] as const;
const RATE_LABELS: Record<(typeof RATE_SUFFIXES)[number], string> = {
  total: "Total",
  rate_a: "Rate A",
  rate_b: "Rate B",
  rate_c: "Rate C",
  rate_d: "Rate D",
};

const MEASUREMENT_COLUMN_WIDTH = 110;
const TIME_COLUMN_WIDTH = 170;

/** One grouped-header column: a title spanning five children (Total,
 * Rate A..D) reading `${prefix}_${suffix}` off the row (D20).
 *
 * `unit`/`scale` decide the group's title suffix (e.g. `(kWh)` vs `(Wh)`)
 * and scale every child's value together — the display-unit setting's one
 * hard requirement is that a value and its label never move independently. */
function measurementGroup(
  title: string,
  prefix: string,
  unit: UnitKind,
  scale: DisplayUnitScale,
): ColumnsType<BillingRow>[number] {
  return {
    title: `${title} (${unitLabel(unit, scale)})`,
    children: RATE_SUFFIXES.map((suffix) => ({
      title: RATE_LABELS[suffix],
      dataIndex: `${prefix}_${suffix}`,
      key: `${prefix}_${suffix}`,
      width: MEASUREMENT_COLUMN_WIDTH,
      render: (value: number | null) => num3(scaleValue(value, scale) ?? null),
    })),
  };
}

/** Same shape as `measurementGroup`, but for a Demand Time group — its five
 * children are timestamps, never `toFixed(3)` and never scaled (D20/D11):
 * a Demand Time cell carries no unit token, kilo or base. */
function demandTimeGroup(title: string, prefix: string): ColumnsType<BillingRow>[number] {
  return {
    title,
    children: RATE_SUFFIXES.map((suffix) => ({
      title: RATE_LABELS[suffix],
      dataIndex: `${prefix}_${suffix}`,
      key: `${prefix}_${suffix}`,
      width: TIME_COLUMN_WIDTH,
      render: time,
    })),
  };
}

/** The identity/Demand-Time columns plus every scale-aware measurement
 * group, built fresh per `scale`, in the page's original column order.
 *
 * `showIdentityColumns` drops `Device` and `Meter Serial` when a specific
 * device is already selected — both would print the same value on every row
 * at that point. The serial does not become unreachable: the device filter's
 * own dropdown option already reads `name (serial)` (see `deviceOptions`),
 * so it stays visible there regardless of this flag. */
function buildColumns(scale: DisplayUnitScale, showIdentityColumns: boolean): ColumnsType<BillingRow> {
  const group = (title: string, prefix: string, unit: UnitKind) => measurementGroup(title, prefix, unit, scale);
  return [
    {
      title: "Bill Date",
      dataIndex: "bill_date",
      key: "bill_date",
      width: 170,
      fixed: "left",
      render: (billDate: string) => dayjs(billDate).format("YYYY-MM-DD HH:mm"),
    },
    ...(showIdentityColumns
      ? ([
          { title: "Device", dataIndex: "device_name", key: "device_name", width: 180 },
          {
            title: "Meter Serial",
            dataIndex: "meter_serial",
            key: "meter_serial",
            width: 150,
            render: (serial: string | null) => serial ?? NOTHING,
          },
        ] as ColumnsType<BillingRow>)
      : []),
    group("Import Active", "import_active_kwh", "energy"),
    group("Export Active", "export_active_kwh", "energy"),
    group("Import Reactive", "import_reactive_kvarh", "reactiveEnergy"),
    group("Export Reactive", "export_reactive_kvarh", "reactiveEnergy"),
    group("Max Demand Import Active", "max_demand_import_active_kw", "power"),
    group("Max Demand Export Active", "max_demand_export_active_kw", "power"),
    group("Max Demand Import Reactive", "max_demand_import_reactive_kvar", "reactivePower"),
    group("Max Demand Export Reactive", "max_demand_export_reactive_kvar", "reactivePower"),
    demandTimeGroup("Demand Time Import Active", "max_demand_import_active_time"),
    demandTimeGroup("Demand Time Import Reactive", "max_demand_import_reactive_time"),
    group("Cumulative Demand Import Active", "cumul_demand_import_active_kw", "power"),
    group("Cumulative Demand Import Reactive", "cumul_demand_import_reactive_kvar", "reactivePower"),
  ];
}

/** Sum every **leaf** column's width — a grouped header column has no width
 * of its own, only its `children` do (D20's `scroll={{ x: tableWidth }}`
 * still needs the true total so the page body never scrolls sideways). */
function totalLeafWidth<Row>(columns: ColumnsType<Row>): number {
  return columns.reduce((sum, column) => {
    if ("children" in column && column.children) return sum + totalLeafWidth(column.children as ColumnsType<Row>);
    return sum + (Number(column.width) || 0);
  }, 0);
}

/** Which tab is showing. The first two are `GET /api/billing`'s own `status`
 * values; `all` is the All-Meters View, which is a different endpoint with no
 * parameters at all (issue 01). */
type BillingTab = BillingStatus | typeof ALL_METERS;

const ALL_METERS = "all";

/** How each All-Meters status renders (issue 01; colours and meanings from
 * ui-audit ticket 07, §7.3's order `paused > not answering > never billed /
 * behind > ok`).
 *
 * `OK` is green so it is never the same grey as a problem; `Paused` stays
 * uncoloured because it is a state an operator chose, not a fault, and it is
 * excluded from the attention counter for the same reason. `meaning` is the
 * chip's tooltip — the one sentence that says what the state is. */
const STATUS_PRESENTATION: Record<AllMetersStatus, { color?: string; label: string; meaning: string }> = {
  paused: {
    label: "Paused",
    meaning: "Polling is paused for this meter on the Devices page; nothing is read until it is resumed.",
  },
  not_answering: {
    color: "error",
    label: "Not answering",
    meaning: "The most recent reads of this meter failed one after another — the number is how many in a row.",
  },
  never_billed: {
    color: "warning",
    label: "Never billed",
    meaning: "No closed billing period has ever been read from this meter.",
  },
  behind: {
    color: "warning",
    label: "Behind",
    meaning: "The newest closed period is older than the 35-day threshold — the number is how many days old it is.",
  },
  ok: { color: "success", label: "OK", meaning: "A closed billing period was read within the last 35 days." },
};

/** The chip for one row — the label plus the number the status carries, if
 * it carries one (consecutive failures, or whole days behind), with the
 * state's meaning as its tooltip. */
function statusChip(row: AllMetersRow) {
  const { color, label, meaning } = STATUS_PRESENTATION[row.status];
  const suffix =
    row.status === "not_answering"
      ? ` · ${row.status_value} failed read${row.status_value === 1 ? "" : "s"}`
      : row.status === "behind"
        ? ` · ${row.status_value} days`
        : "";
  return (
    <Tooltip title={meaning}>
      <Tag color={color}>{`${label}${suffix}`}</Tag>
    </Tooltip>
  );
}

/** Format an instant, or an em dash where there is none. */
const stamp = (value: string | null): string => (value == null ? NOTHING : dayjs(value).format("YYYY-MM-DD HH:mm"));

/** The All-Meters View's seven columns (issue 01).
 *
 * `scale` reaches the two measurement columns for the same reason it reaches
 * every other rendered number (ADR 0013): a value and its unit label must
 * never move independently. */
function allMetersColumns(scale: DisplayUnitScale): ColumnsType<AllMetersRow> {
  return [
    { title: "Device", dataIndex: "device_name", key: "device_name", width: 200 },
    {
      title: "Meter Serial",
      dataIndex: "meter_serial",
      key: "meter_serial",
      width: 150,
      render: (value: string | null) => value ?? NOTHING,
    },
    {
      title: "Bill Date",
      dataIndex: "bill_date",
      key: "bill_date",
      width: 170,
      render: stamp,
    },
    {
      title: `Import Active (${unitLabel("energy", scale)})`,
      dataIndex: "import_active_kwh_total",
      key: "import_active_kwh_total",
      width: 150,
      render: (value: number | null) => num3(scaleValue(value, scale) ?? null),
    },
    {
      title: `Export Active (${unitLabel("energy", scale)})`,
      dataIndex: "export_active_kwh_total",
      key: "export_active_kwh_total",
      width: 150,
      render: (value: number | null) => num3(scaleValue(value, scale) ?? null),
    },
    {
      title: "Captured",
      dataIndex: "captured_at",
      key: "captured_at",
      width: 170,
      render: stamp,
    },
    {
      title: "Status",
      key: "status",
      width: 190,
      render: (_: unknown, row: AllMetersRow) => statusChip(row),
    },
  ];
}

/**
 * Admin-only `capture_dir` form (M6b, issue #22).
 *
 * Changing the value while captures already exist confirms first — the
 * backend never blocks (ADR 0010: "warns, never blocks"), so this confirm
 * dialog is the only place that fact is enforced at all.
 */
function CaptureSettingsCard({ surface }: { surface: (err: unknown, fallback: string) => void }) {
  const { message, modal } = App.useApp();
  const [form] = Form.useForm<{ capture_dir: string }>();
  const [settings, setSettings] = useState<BillingSettings | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .billingSettings()
      .then((data) => {
        setSettings(data);
        form.setFieldsValue({ capture_dir: data.capture_dir });
      })
      .catch((err: unknown) => surface(err, "Could not load the capture folder setting."));
    // Loaded once on mount — the form owns edits from then on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = useCallback(
    (captureDir: string) => {
      setSaving(true);
      api
        .updateBillingSettings(captureDir)
        .then((data) => {
          setSettings(data);
          form.setFieldsValue({ capture_dir: data.capture_dir });
          message.success("Capture folder saved.");
        })
        .catch((err: unknown) => surface(err, "Could not save the capture folder."))
        .finally(() => setSaving(false));
    },
    [form, message, surface],
  );

  const onFinish = (values: { capture_dir: string }) => {
    const next = values.capture_dir.trim();
    if (settings && next !== settings.capture_dir && settings.capture_count > 0) {
      // `capture_count` is the number of CLOSED BILLING ROWS — the rows a
      // capture could exist for — not the number of files actually written
      // (the backend is honest about this; see `BillingSettingsOut`). On the
      // very first configuration of a site that already has billing history,
      // capture_count > 0 even though nothing has ever been captured, so the
      // text below must not claim captures already exist — only that some
      // *might*, under whatever folder is currently set.
      modal.confirm({
        title: "Change the capture folder?",
        content: `${settings.capture_count} closed billing period(s) exist. Any captures already written under the current folder stay exactly where they are and will no longer be reachable from this page.`,
        okText: "Change folder",
        onOk: () => save(next),
      });
      return;
    }
    save(next);
  };

  return (
    <Card size="small" title="Capture folder">
      <Form form={form} layout="vertical" onFinish={onFinish}>
        <Form.Item
          name="capture_dir"
          label="Folder path"
          extra="Where billing PDF/xlsx captures are written. Leave empty to disable capture."
        >
          <Input placeholder="e.g. C:\Captures" allowClear />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={saving}>
          Save
        </Button>
      </Form>
    </Card>
  );
}

/**
 * Billing (M6a, issue #21) — read a device's stored Billing Readings, either tab.
 *
 * Every row shown here was frozen by the meter itself and stored by Read now
 * (either the Devices page's three-job version or this page's own button
 * below), the Scheduler's daily `billing` job, or the Billing Change Check
 * riding the Load Profile cycle (#43, ADR 0018).
 *
 * **This page's own Read now button (issue #44) reverses this docstring's
 * former claim that it has none.** The original reasoning — "that capability
 * lives on the Devices page" — was reconsidered: an operator waiting on one
 * device's billing should not have to leave this page for the Devices page's
 * unrelated three-job version just to press a button. This page's button
 * reads only this device's whole billing buffer (ADR 0009), never the load
 * profile, and is hidden in capture mode (D13, below).
 *

 * **Two tabs, one endpoint, a different `status`.** History is every closed
 * period (`record_status IS NULL`); Current is the device's Open Period
 * (`record_status = 'open'`) — at most one row per device, and it is the one
 * place this page shows a number that is not yet a bill (CONTEXT.md — Open
 * Period).
 *
 * **The device filter and the date range are both optional** — unlike Load
 * Profile, which forces a range because one meter can hold 8,640 rows over 90
 * days. Billing is roughly a dozen rows per device per year, so forcing
 * either filter would only hide data.
 *
 * **The `capture_dir` form (M6b, issue #22) is admin-only**, shown above the
 * tabs — SPEC §3.6 puts it on this page, next to the data it captures.
 */
export function Billing({ role }: { role: "admin" | "user" }) {
  const { message } = App.useApp();
  const scale = useDisplayUnitScale();

  const [devices, setDevices] = useState<Device[]>([]);
  const [tab, setTab] = useState<BillingTab>("closed");
  // Seeded from the capture request (ADR 0017, issue #38, decision 4) when
  // present — the page is driven by seeded state, not by clicking, because
  // exactly ten periods is unreachable through the UI and the `bill_date`
  // bound needs instant precision the RangePicker cannot give it. `deviceId`
  // and `pageSize` are read once via lazy initializers, matching how
  // `captureRequest` itself is read once at module load.
  const [deviceId, setDeviceId] = useState<number | undefined>(() => captureRequest?.deviceId);
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => captureRequest?.pageSize ?? DEFAULT_PAGE_SIZE);

  // The loaded page is keyed by the scope it answers, so a page belonging to
  // the previous tab/device/range is never rendered under the new one — same
  // pattern as LoadProfile.tsx.
  const [loaded, setLoaded] = useState<{ scope: string; page: BillingPageData } | null>(null);
  const [loading, setLoading] = useState(false);

  const surface = useCallback(
    (err: unknown, fallback: string) => {
      if (isLicenseLapsed(err)) {
        window.location.reload();
        return;
      }
      message.error(err instanceof ApiRequestError ? err.message : fallback);
    },
    [message],
  );

  useEffect(() => {
    api.listDevices().then(setDevices).catch((err: unknown) => surface(err, "Could not load the device list."));
  }, [surface]);

  // The All-Meters View (issue 01). Loaded whichever tab is showing, because
  // its `needs_attention` count lives on the *tab header* — it is what tells
  // an operator whether to open the tab at all, so fetching it only once the
  // tab is open would make the count useless.
  //
  // Not loaded in capture mode: the headless renderer photographs one
  // device's History (ADR 0017), and a fleet-wide request has nothing to do
  // with the document it is producing.
  const [allMeters, setAllMeters] = useState<AllMetersView | null>(null);
  const [allMetersLoading, setAllMetersLoading] = useState(false);

  const deviceOptions = useMemo(
    () => [
      { value: ALL, label: "All devices" },
      ...[...devices]
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((device) => ({
          value: device.id,
          label: device.meter_serial ? `${device.name} (${device.meter_serial})` : device.name,
        })),
    ],
    [devices],
  );

  const columns: ColumnsType<BillingRow> = useMemo(
    () => buildColumns(scale, deviceId === undefined),
    [scale, deviceId],
  );

  const tableWidth = totalLeafWidth(columns);

  const [imageDownloading, setImageDownloading] = useState(false);
  // One shared refresh trigger for the fetch effects below — bumped by Read
  // now (issue #44) and by Capture image (ui-audit ticket 03).
  const [refreshTick, setRefreshTick] = useState(0);

  // Capture image (M7 slice 4, issue #35, D12) — device-keyed, so it needs a
  // specific device selected; "All devices" has no anchor to render from.
  const onDownloadImage = useCallback(() => {
    if (deviceId === undefined) return;
    setImageDownloading(true);
    downloadBillingImage(deviceId)
      .then((capturedAt) => {
        // The toast names the instant the server stamped on the anchor period
        // (ui-audit ticket 03); the refresh makes the All-Meters row show it.
        // A file that predates the stamp (ui-audit ticket 03) carries no
        // instant; say the download happened rather than nothing at all.
        message.success(capturedAt === null ? "Capture image downloaded." : `Captured ${stamp(capturedAt)}`);
        setRefreshTick((tick) => tick + 1);
      })
      .catch((err: unknown) => surface(err, "Could not download the capture image."))
      .finally(() => setImageDownloading(false));
  }, [deviceId, message, surface]);

  // "Save billing file now" (M13, issue 01) — the same shape "Save CSV now"
  // has on the Load Profile page, and for the same reason it is worth having:
  // it is how an installer proves the output folder is right without waiting
  // a whole cycle to find out. An unconfigured folder comes back as a 422 with
  // an actionable sentence, which `surface` renders.
  const [exporting, setExporting] = useState(false);

  const onSaveFile = useCallback(() => {
    if (deviceId === undefined) return;
    setExporting(true);
    api
      .exportBillingNow(deviceId)
      .then((result) => {
        if (result.rows_written === 0) {
          message.info("No new billing periods to export.");
          return;
        }
        message.success(
          `Exported ${result.rows_written} period(s) to ${result.path ?? "the billing file"}.`,
        );
      })
      .catch((err: unknown) => surface(err, "Could not save the billing file now."))
      .finally(() => setExporting(false));
  }, [deviceId, message, surface]);

  // Read now (issue #44, D11) — one whole-buffer round trip (ADR 0009), one
  // toast, one refresh. `refreshTick` is the minimal trigger the fetch
  // effect below needed added to it — neither this page nor LoadProfile.tsx
  // had one before this issue.
  const [reading, setReading] = useState(false);

  const onReadNow = useCallback(() => {
    if (deviceId === undefined) return;
    setReading(true);
    api
      .readBillingNow(deviceId)
      .then((result) => {
        // A meter failure is a verdict on `result.error`, never a thrown
        // error (mirrors Test Connection / EnergySummary.tsx's own
        // `onReadNow`) — surfaced via `message`, not `surface()`, which is
        // reserved for request-layer failures.
        if (result.error) {
          message.error(result.error);
          return;
        }
        const parts: string[] = [];
        if (result.stored > 0) {
          parts.push(`${result.stored} closed billing period${result.stored === 1 ? "" : "s"}`);
        }
        if (result.open_updated) parts.push("the Open Period");
        // The capture count comes from the read path (issue 02), never from
        // `stored` and never inferred here from the capture-folder setting —
        // that setting is not loaded for non-admin roles at all. Saying
        // "and 0 captures" out loud is the point: with no capture folder set,
        // periods store and no documents are written, and the old message
        // read as though they had been.
        const captures = `${result.captured} capture${result.captured === 1 ? "" : "s"} written`;
        message.success(
          parts.length > 0 ? `Stored ${parts.join(" and ")} — ${captures}.` : "No new billing periods to store.",
        );
        setRefreshTick((tick) => tick + 1);
      })
      .catch((err: unknown) => surface(err, "Could not read the billing buffer."))
      .finally(() => setReading(false));
  }, [deviceId, message, surface]);

  const onTabChange = (key: string) => {
    setTab(key as BillingTab);
    setPage(1);
  };

  /** Clicking a row opens that meter's History — what keeps this table
   * narrow enough to scan (issue 01). */
  const onAllMetersRowClick = useCallback((row: AllMetersRow) => {
    setDeviceId(row.device_id);
    setTab("closed");
    setPage(1);
  }, []);

  const onDeviceChange = (value: number | typeof ALL) => {
    setDeviceId(value === ALL ? undefined : value);
    setPage(1);
  };

  const onRangeChange = (dates: (Dayjs | null)[] | null) => {
    const [from, to] = dates ?? [];
    // A cleared picker hands back `null` — that is a real, valid state here
    // (the range is optional), unlike LoadProfile.tsx's `allowClear={false}`.
    setRange(from && to ? [from, to] : null);
    setPage(1);
  };

  // Local days in, UTC instants out — the upper bound is the start of the day
  // after the one picked, the exclusive bound the API wants. In capture mode
  // the RangePicker stays untouched (`range` is always `null` there — the
  // page never renders it as visited) and `endIso` comes from the seeded
  // request instead: it is chosen server-side to be exclusive of everything
  // *after* the anchor row while including the anchor's own `bill_date`
  // exactly (`_png_source_rows()` is `<=`, this endpoint's `end` is `<`).
  const startIso = captureRequest ? undefined : range ? range[0].startOf("day").toISOString() : undefined;
  const endIso = captureRequest
    ? captureRequest.endIso
    : range
      ? range[1].add(1, "day").startOf("day").toISOString()
      : undefined;
  const meterSerial = captureRequest?.meterSerial ?? undefined;

  const scope = `${tab}|${deviceId ?? ALL}|${startIso ?? ""}|${endIso ?? ""}|${meterSerial ?? ""}`;
  const shown = loaded?.scope === scope ? loaded.page : null;

  // The row holding the newest closed period in the current result, by bill
  // date — never by row index (ui-audit ticket 09): a page sorted oldest-first,
  // or a range that hides the newest, still tints the newest period *shown*,
  // and an empty table tints nothing. History only — an Open Period's bill
  // date moves on every read (CONTEXT.md), so the Current tab has no "latest".
  // With "All devices" it is the single newest closed period across devices
  // (v1 #49), one row, not one per device — meters that close on the same
  // instant tie, and the helper breaks the tie. In capture mode the same rule
  // runs on the ten seeded periods, so the anchor row is tinted in the PNG.
  const latestClosedRowId = useMemo(
    () => (tab !== "closed" || !shown ? null : latestBillRowId(shown.items)),
    [tab, shown],
  );

  useEffect(() => {
    // The All-Meters tab is a different endpoint with no parameters — its own
    // effect below owns it, and this paged list has nothing to fetch for it.
    if (tab === ALL_METERS) return;
    let current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    void api
      .billing(tab, deviceId, startIso, endIso, pageSize, (page - 1) * pageSize, meterSerial)
      .then((result) => {
        if (current) setLoaded({ scope, page: result });
      })
      .catch((err: unknown) => {
        if (current) {
          setLoaded(null);
          surface(err, "Could not load the Billing Readings.");
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
    // `scope` is derived from the same dependencies already listed; adding it
    // too would be redundant, not incorrect. `refreshTick` (issue #44) is the
    // one addition: it forces this effect to re-run after a successful Read
    // now without changing `scope`, so the same page reloads rather than the
    // view resetting.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, deviceId, startIso, endIso, meterSerial, page, pageSize, surface, refreshTick]);

  useEffect(() => {
    if (captureRequest) return;
    let current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAllMetersLoading(true);
    void api
      .billingAllMeters()
      .then((result) => {
        if (current) setAllMeters(result);
      })
      .catch((err: unknown) => {
        if (current) {
          setAllMeters(null);
          surface(err, "Could not load the All-Meters View.");
        }
      })
      .finally(() => {
        if (current) setAllMetersLoading(false);
      });
    return () => {
      current = false;
    };
  }, [surface, refreshTick]);

  const allMetersCols = useMemo(() => allMetersColumns(scale), [scale]);

  // The toolbar strip (ui-audit ticket 10): the counters the customer pointed
  // at in the v1 screenshot, with real definitions — served beside the
  // All-Meters rows so the strip and the tab can never disagree. `Auto` is an
  // indicator, never a Stop button: the scheduler holds no state to stop (ADR
  // 0008), and pausing is a per-device action on the Devices page.
  const autoText =
    allMeters === null
      ? NOTHING
      : allMeters.auto_last_cycle_at === null
        ? "Not yet run since start"
        : `Every ${Math.round(allMeters.auto_interval_sec / 60)} min · last cycle ${dayjs(allMeters.auto_last_cycle_at).format("HH:mm")}`;
  const selectedDevice = deviceId === undefined ? undefined : devices.find((device) => device.id === deviceId);

  // The All-Meters tab is hidden in capture mode for the same reason the
  // capture-folder form and Read now are (issues #38/#44): the headless
  // renderer photographs one device's History, and a fleet-wide tab has no
  // place in a document a human carries to one customer.
  const tabItems: TabsProps["items"] = [
    { key: "closed", label: "History" },
    { key: "open", label: "Current" },
    ...(captureRequest
      ? []
      : [
          {
            key: ALL_METERS,
            label: (
              <Space size="small">
                All Meters
                <Badge count={allMeters?.needs_attention ?? 0} />
              </Space>
            ),
          },
        ]),
  ];

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      {/* Hidden in capture mode (decision 8, issue #38): the folder path is
          for a human admin, not for what the headless renderer photographs. */}
      {role === "admin" && !captureRequest ? <CaptureSettingsCard surface={surface} /> : null}
      {/* Hidden in capture mode like the other operator controls (D13): the
          PNG stays the table the customer's screenshot shows. */}
      {captureRequest ? null : (
        <Card size="small">
          <Flex gap="large" wrap align="center">
            <Statistic title="Total Devices" value={allMeters?.total_devices ?? NOTHING} />
            <Statistic title="Devices with Issues" value={allMeters?.devices_with_issues ?? NOTHING} />
            <Statistic title="Complete" value={allMeters?.complete ?? NOTHING} />
            <Space direction="vertical" size={0}>
              <Text type="secondary">Auto</Text>
              <Text>{autoText}</Text>
            </Space>
            {selectedDevice ? (
              <>
                <Space direction="vertical" size={0}>
                  <Text type="secondary">Site Name</Text>
                  <Text>{selectedDevice.site_name || NOTHING}</Text>
                </Space>
                <Space direction="vertical" size={0}>
                  <Text type="secondary">Site Code</Text>
                  <Text>{selectedDevice.site_code || NOTHING}</Text>
                </Space>
              </>
            ) : null}
          </Flex>
        </Card>
      )}
      <Tabs activeKey={tab} onChange={onTabChange} items={tabItems} />
      {/* Open Periods are not closed bills (CONTEXT.md — Open Period); the
          caption says so once, above the table (ui-audit ticket 07). */}
      {tab === "open" ? (
        <Text type="secondary">
          These are Open Periods — each meter&rsquo;s running period. Its bill date moves on every read; it is
          not a closed bill and is never captured or exported.
        </Text>
      ) : null}
      {/* The whole filter card is **hidden** on the All-Meters tab (issue
          01): the device picker, the date range and the per-meter capture
          control all contradict a tab that is every device, the latest
          period, and no range. Hidden rather than disabled — a greyed
          control invites the question, an absent one does not. */}
      {tab === ALL_METERS ? null : (
        <Card size="small">
          <Flex gap="small" wrap align="center">
            <Select
              value={deviceId ?? ALL}
              onChange={onDeviceChange}
              options={deviceOptions}
              style={{ minWidth: 260 }}
              aria-label="Device"
            />
            <RangePicker
              value={range}
              onChange={onRangeChange}
              allowClear
              placeholder={["Bill date from", "Bill date to"]}
              disabledDate={(current) => current.isAfter(dayjs().endOf("day"))}
              aria-label="Bill date range"
            />
            {/* Each Tooltip wraps a <span>, not the Button: AntD attaches its
                hover handlers to the child, and a disabled button fires none,
                so the tooltip never rendered (ui-audit ticket 07). */}
            <Tooltip
              title={
                deviceId === undefined
                  ? "Choose one device first."
                  : "Saves the ten most recent closed periods to the capture folder and downloads a copy."
              }
            >
              <span>
                <Button onClick={onDownloadImage} disabled={deviceId === undefined} loading={imageDownloading}>
                  Capture image
                </Button>
              </span>
            </Tooltip>
            {/* Hidden in capture mode (D13, issue #44) — a button offering to
                talk to a meter has no place in a headless screenshot a human
                carries to a customer (ADR 0015/0017). */}
            {captureRequest ? null : (
              <Tooltip
                title={
                  deviceId === undefined
                    ? "Choose one device first."
                    : "Rewrites this meter's billing file in the export folder with every closed period now."
                }
              >
                <span>
                  <Button onClick={onSaveFile} loading={exporting} disabled={deviceId === undefined}>
                    Save billing file now
                  </Button>
                </span>
              </Tooltip>
            )}
            {captureRequest ? null : (
              <Tooltip
                title={
                  deviceId === undefined
                    ? "Choose one device first."
                    : "Reads this meter's whole billing buffer now and refreshes the table."
                }
              >
                <span>
                  <Button type="primary" onClick={onReadNow} loading={reading} disabled={deviceId === undefined}>
                    Read now
                  </Button>
                </span>
              </Tooltip>
            )}
        </Flex>
      </Card>
      )}
      <Card size="small">
        {tab === ALL_METERS ? (
          <Table<AllMetersRow>
            size="small"
            rowKey={(row) => row.device_id}
            loading={allMetersLoading}
            dataSource={allMeters?.items ?? []}
            columns={allMetersCols}
            scroll={{ x: totalLeafWidth(allMetersCols) }}
            onRow={(row) => ({
              onClick: () => onAllMetersRowClick(row),
              style: { cursor: "pointer" },
            })}
            locale={{ emptyText: <Empty description="No meters configured" /> }}
            pagination={false}
          />
        ) : (
          <Table<BillingRow>
            size="small"
            rowKey={(row) => row.id}
            rowClassName={(row) => (row.id === latestClosedRowId ? LATEST_BILL_ROW_CLASS : "")}
            loading={loading}
            dataSource={shown?.items ?? []}
            columns={columns}
            scroll={{ x: tableWidth }}
            locale={{
              emptyText: (
                <Empty
                  description={tab === "closed" ? "No closed billing periods" : "No device has an Open Period"}
                />
              ),
            }}
            pagination={{
              current: page,
              pageSize,
              total: shown?.total ?? 0,
              showSizeChanger: true,
              pageSizeOptions: PAGE_SIZE_OPTIONS,
              showTotal: (total) => `${total} rows`,
              onChange: (nextPage, nextSize) => {
                setPage(nextPage);
                setPageSize(nextSize);
              },
            }}
          />
        )}
      </Card>
    </Space>
  );
}
