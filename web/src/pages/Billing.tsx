import { App, Button, Card, DatePicker, Dropdown, Empty, Flex, Form, Input, Select, Space, Table, Tabs } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TabsProps } from "antd/es/tabs";
import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiRequestError,
  api,
  downloadBillingCapture,
  isLicenseLapsed,
  type BillingPage as BillingPageData,
  type BillingRow,
  type BillingSettings,
  type BillingStatus,
  type Device,
} from "../api";

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

const BASE_COLUMNS: ColumnsType<BillingRow> = [
  {
    title: "Bill Date",
    dataIndex: "bill_date",
    key: "bill_date",
    width: 170,
    fixed: "left",
    render: (billDate: string) => dayjs(billDate).format("YYYY-MM-DD HH:mm"),
  },
  { title: "Device", dataIndex: "device_name", key: "device_name", width: 180 },
  {
    title: "Meter Serial",
    dataIndex: "meter_serial",
    key: "meter_serial",
    width: 150,
    render: (serial: string | null) => serial ?? NOTHING,
  },
  {
    title: "Import kWh Active",
    dataIndex: "import_active_kwh_total",
    key: "import_active_kwh_total",
    width: 160,
    render: num3,
  },
  {
    title: "Export kWh Active",
    dataIndex: "export_active_kwh_total",
    key: "export_active_kwh_total",
    width: 160,
    render: num3,
  },
  {
    title: "Import kvarh Reactive",
    dataIndex: "import_reactive_kvarh_total",
    key: "import_reactive_kvarh_total",
    width: 180,
    render: num3,
  },
  {
    title: "Export kvarh Reactive",
    dataIndex: "export_reactive_kvarh_total",
    key: "export_reactive_kvarh_total",
    width: 180,
    render: num3,
  },
  {
    title: "Max Demand Import (kW)",
    dataIndex: "max_demand_import_active_kw_total",
    key: "max_demand_import_active_kw_total",
    width: 190,
    render: num3,
  },
  {
    title: "Max Demand Export (kW)",
    dataIndex: "max_demand_export_active_kw_total",
    key: "max_demand_export_active_kw_total",
    width: 190,
    render: num3,
  },
  {
    title: "Max Demand Import (kvar)",
    dataIndex: "max_demand_import_reactive_kvar_total",
    key: "max_demand_import_reactive_kvar_total",
    width: 200,
    render: num3,
  },
  {
    title: "Max Demand Export (kvar)",
    dataIndex: "max_demand_export_reactive_kvar_total",
    key: "max_demand_export_reactive_kvar_total",
    width: 200,
    render: num3,
  },
];

/** Width of the History-only "Capture" column appended in `Billing`'s `columns`. */
const CAPTURE_COLUMN_WIDTH = 130;

const TAB_ITEMS: TabsProps["items"] = [
  { key: "closed", label: "History" },
  { key: "open", label: "Current" },
];

/**
 * Per-row PDF/xlsx download control (M6b, issue #22) — History tab only, the
 * Open Period has no capture (SPEC §3.6). Errors surface through the page's
 * `surface()` handler rather than a local toast, matching every other action
 * on this page.
 */
function CaptureDownload({
  readingId,
  surface,
}: {
  readingId: number;
  surface: (err: unknown, fallback: string) => void;
}) {
  const download = (format: "pdf" | "xlsx") => {
    downloadBillingCapture(readingId, format).catch((err: unknown) => surface(err, "Could not download the capture."));
  };

  return (
    <Dropdown
      menu={{
        items: [
          { key: "pdf", label: "Download PDF", onClick: () => download("pdf") },
          { key: "xlsx", label: "Download Excel", onClick: () => download("xlsx") },
        ],
      }}
    >
      <Button size="small">Capture</Button>
    </Dropdown>
  );
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

  // The Capture column is History-only — the Open Period has no capture
  // (SPEC §3.6), so appending it unconditionally would offer a download that
  // always fails on the Current tab.
  const columns: ColumnsType<BillingRow> = useMemo(() => {
    if (tab !== "closed") return BASE_COLUMNS;
    return [
      ...BASE_COLUMNS,
      {
        title: "Capture",
        key: "capture",
        width: CAPTURE_COLUMN_WIDTH,
        fixed: "right",
        render: (_: unknown, row: BillingRow) => <CaptureDownload readingId={row.id} surface={surface} />,
      },
    ];
  }, [tab, surface]);

  const tableWidth = columns.reduce((sum, column) => sum + (Number(column.width) || 0), 0);

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
