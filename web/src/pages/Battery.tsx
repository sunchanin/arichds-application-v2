import { App, Card, DatePicker, Empty, Flex, Select, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiRequestError,
  api,
  isLicenseLapsed,
  type BatteryPage as BatteryPageData,
  type BatteryRow,
  type CatalogEntry,
  type Device,
} from "../api";

const { RangePicker } = DatePicker;

const PAGE_SIZE_OPTIONS = [50, 100, 200, 500];
const DEFAULT_PAGE_SIZE = 100;

/** The sentinel the device filter's "All" option carries — devices have
 * numeric ids, so it cannot collide (mirrors `Billing.tsx`'s `ALL`). */
const ALL = "all";

/**
 * Battery (M7-2, issue #29) — read a device's stored Battery Readings.
 *
 * **Read-only, background-only.** Every row shown here was written by the
 * hourly Scheduler job; there is no Read-now button on this page (D5) —
 * battery is a trend, not a minute (SPEC §3.7).
 *
 * **The device selector offers only battery-capable models** — the three
 * CEWE models — filtered off the catalog's `supports_battery` flag exactly
 * as `SpecialDays.tsx` filters on `supports_special_days`.
 *
 * **`status` renders as a plain, uncoloured `Tag`** (D8, CONTEXT.md — Battery
 * Reading): the raw value the meter reported, never thresholded, never
 * coloured — v1 refused both deliberately.
 */
export function Battery() {
  const { message } = App.useApp();

  const [devices, setDevices] = useState<Device[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [deviceId, setDeviceId] = useState<number | undefined>(undefined);
  const [range, setRange] = useState<[Dayjs, Dayjs] | null>(null);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  // The loaded page is keyed by the scope it answers, so a page belonging to
  // a previous device/range is never rendered under the new one — same
  // pattern as Billing.tsx/LoadProfile.tsx.
  const [loaded, setLoaded] = useState<{ scope: string; page: BatteryPageData } | null>(null);
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
    api.catalog().then(setCatalog).catch(() => setCatalog([]));
  }, [surface]);

  const supportedModels = useMemo(
    () => new Set(catalog.filter((entry) => entry.supports_battery).map((entry) => `${entry.brand}/${entry.model}`)),
    [catalog],
  );

  const deviceOptions = useMemo(
    () => [
      { value: ALL, label: "All devices" },
      ...[...devices]
        .filter((device) => supportedModels.has(`${device.brand}/${device.model}`))
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((device) => ({
          value: device.id,
          label: device.meter_serial ? `${device.name} (${device.meter_serial})` : device.name,
        })),
    ],
    [devices, supportedModels],
  );

  const onDeviceChange = (value: number | typeof ALL) => {
    setDeviceId(value === ALL ? undefined : value);
    setPage(1);
  };

  const onRangeChange = (dates: (Dayjs | null)[] | null) => {
    const [from, to] = dates ?? [];
    setRange(from && to ? [from, to] : null);
    setPage(1);
  };

  // Local days in, UTC instants out — the upper bound is the start of the
  // day after the one picked, the exclusive bound the API wants (mirrors
  // Billing.tsx).
  const startIso = range ? range[0].startOf("day").toISOString() : undefined;
  const endIso = range ? range[1].add(1, "day").startOf("day").toISOString() : undefined;

  const scope = `${deviceId ?? ALL}|${startIso ?? ""}|${endIso ?? ""}`;
  const shown = loaded?.scope === scope ? loaded.page : null;

  useEffect(() => {
    let current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    void api
      .battery(deviceId, startIso, endIso, pageSize, (page - 1) * pageSize)
      .then((result) => {
        if (current) setLoaded({ scope, page: result });
      })
      .catch((err: unknown) => {
        if (current) {
          setLoaded(null);
          surface(err, "Could not load the Battery Readings.");
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
    // `scope` is derived from the same dependencies already listed; adding it
    // too would be redundant, not incorrect (mirrors Billing.tsx).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceId, startIso, endIso, page, pageSize, surface]);

  const columns: ColumnsType<BatteryRow> = [
    { title: "Device", dataIndex: "device_name", key: "device_name", width: 180 },
    {
      title: "Meter Serial",
      dataIndex: "meter_serial",
      key: "meter_serial",
      width: 150,
      render: (serial: string | null) => serial ?? "—",
    },
    {
      title: "Read at",
      dataIndex: "read_at",
      key: "read_at",
      width: 170,
      render: (readAt: string) => dayjs(readAt).format("YYYY-MM-DD HH:mm:ss"),
    },
    {
      title: "Status",
      dataIndex: "status",
      key: "status",
      render: (status: string | null) => (status == null ? "—" : <Tag>{status}</Tag>),
    },
  ];

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
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
            placeholder={["Read at from", "Read at to"]}
            disabledDate={(current) => current.isAfter(dayjs().endOf("day"))}
            aria-label="Read at range"
          />
        </Flex>
      </Card>
      <Card size="small">
        <Table<BatteryRow>
          size="small"
          rowKey={(row) => row.id}
          loading={loading}
          dataSource={shown?.items ?? []}
          columns={columns}
          locale={{ emptyText: <Empty description="No battery readings stored yet" /> }}
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
