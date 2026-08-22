import { App, Button, Card, DatePicker, Empty, Flex, Form, Input, Select, Space, Table, Tabs, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TabsProps } from "antd/es/tabs";
import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiRequestError,
  api,
  downloadBillingImage,
  isLicenseLapsed,
  type BillingPage as BillingPageData,
  type BillingRow,
  type BillingSettings,
  type BillingStatus,
  type Device,
} from "../api";
import { type DisplayUnitScale, type UnitKind, scaleValue, unitLabel, useDisplayUnitScale } from "../units";

const { RangePicker } = DatePicker;

/** Shown wherever the meter never captured a quantity. A genuine 0 must still
 * render as `0` — see `num()` below. */
const NOTHING = "—";

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
function totalLeafWidth(columns: ColumnsType<BillingRow>): number {
  return columns.reduce((sum, column) => {
    if ("children" in column && column.children) return sum + totalLeafWidth(column.children as ColumnsType<BillingRow>);
    return sum + (Number(column.width) || 0);
  }, 0);
}

const TAB_ITEMS: TabsProps["items"] = [
  { key: "closed", label: "History" },
  { key: "open", label: "Current" },
];

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
 * **Read-only, and it never talks to a meter.** Every row shown here was
 * frozen by the meter itself and stored by Read now or the Scheduler's daily
 * `billing` job. Exactly like Load Profile's own slice (#17), this page has
 * no Read now button of its own — that capability lives on the Devices page.
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
  const [tab, setTab] = useState<BillingStatus>("closed");
  const [deviceId, setDeviceId] = useState<number | undefined>(undefined);
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

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

  // Capture image (M7 slice 4, issue #35, D12) — device-keyed, so it needs a
  // specific device selected; "All devices" has no anchor to render from.
  const onDownloadImage = useCallback(() => {
    if (deviceId === undefined) return;
    setImageDownloading(true);
    downloadBillingImage(deviceId)
      .catch((err: unknown) => surface(err, "Could not download the capture image."))
      .finally(() => setImageDownloading(false));
  }, [deviceId, surface]);

  const onTabChange = (key: string) => {
    setTab(key as BillingStatus);
    setPage(1);
  };

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
  // after the one picked, the exclusive bound the API wants.
  const startIso = range ? range[0].startOf("day").toISOString() : undefined;
  const endIso = range ? range[1].add(1, "day").startOf("day").toISOString() : undefined;

  const scope = `${tab}|${deviceId ?? ALL}|${startIso ?? ""}|${endIso ?? ""}`;
  const shown = loaded?.scope === scope ? loaded.page : null;

  useEffect(() => {
    let current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    void api
      .billing(tab, deviceId, startIso, endIso, pageSize, (page - 1) * pageSize)
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
    // too would be redundant, not incorrect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, deviceId, startIso, endIso, page, pageSize, surface]);

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      {role === "admin" ? <CaptureSettingsCard surface={surface} /> : null}
      <Tabs activeKey={tab} onChange={onTabChange} items={TAB_ITEMS} />
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
          <Tooltip title="Saves the ten most recent closed periods to the capture folder and downloads a copy.">
            <Button onClick={onDownloadImage} disabled={deviceId === undefined} loading={imageDownloading}>
              Capture image
            </Button>
          </Tooltip>
        </Flex>
      </Card>
      <Card size="small">
        <Table<BillingRow>
          size="small"
          rowKey={(row) => row.id}
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
      </Card>
    </Space>
  );
}
