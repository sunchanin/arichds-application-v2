import { App, Card, DatePicker, Empty, Flex, Select, Space, Table, Tabs } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { TabsProps } from "antd/es/tabs";
import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiRequestError,
  api,
  isLicenseLapsed,
  type BillingPage as BillingPageData,
  type BillingRow,
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

const COLUMNS: ColumnsType<BillingRow> = [
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

/** The total of every column width, so the horizontal scroll has something to scroll to. */
const TABLE_WIDTH = COLUMNS.reduce((sum, column) => sum + (Number(column.width) || 0), 0);

const TAB_ITEMS: TabsProps["items"] = [
  { key: "closed", label: "History" },
  { key: "open", label: "Current" },
];

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
 */
export function Billing() {
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
          rowKey={(row) => `${row.device_id}-${row.bill_date}`}
          loading={loading}
          dataSource={shown?.items ?? []}
          columns={COLUMNS}
          scroll={{ x: TABLE_WIDTH }}
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
