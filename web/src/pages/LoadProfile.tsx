import { App, Card, DatePicker, Empty, Flex, Select, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiRequestError,
  api,
  isLicenseLapsed,
  type CatalogEntry,
  type Device,
  type LoadProfilePage,
  type LoadProfileRow,
} from "../api";

const { RangePicker } = DatePicker;
const { Text } = Typography;

/** Shown wherever a column this meter model does not capture would go. */
const NOTHING = "—";

/** The page sizes the customer already knows, from v1's own Load Profile page. */
const PAGE_SIZE_OPTIONS = [50, 100, 200, 500];

/** v1's default, kept: 100 rows is a little over one day of 15-minute intervals. */
const DEFAULT_PAGE_SIZE = 100;

/** The sentinel every "All …" filter option carries. Devices have numeric ids, so it cannot collide. */
const ALL = "all";

/**
 * Render a measurement, or an em dash when the meter never captured it.
 *
 * `value == null` is the whole point and is not interchangeable with the
 * shorter spellings. `value || NOTHING` turns a genuine reading of **0 A** into
 * a dash, and `value ?? NOTHING` prints `0` where a truly absent column should
 * dash — this catches `null` and `undefined`, and nothing else.
 *
 * Five of the twelve columns are `null` on every row the only model in service
 * produces (`import_reactive_kvarh`, `export_active_kwh`,
 * `export_reactive_kvarh`, `avg_geo_pf` and `freq`), so this is the normal case,
 * not an edge one.
 */
const num =
  (digits: number) =>
  (value: number | null): string =>
    value == null ? NOTHING : value.toFixed(digits);

/** Energy columns carry v1's nine decimals; everything else carries three. */
const ENERGY_DIGITS = 9;
const MEASUREMENT_DIGITS = 3;

const COLUMNS: ColumnsType<LoadProfileRow> = [
  {
    // Named for the clock it is in. The rows are stored UTC and rendered in the
    // browser's own zone — on the customer's machine that is ICT, which is what
    // v1 showed — and a bare "Timestamp" next to a meter reading is ambiguous.
    title: "Timestamp (local time)",
    dataIndex: "read_at",
    key: "read_at",
    width: 180,
    fixed: "left",
    render: (readAt: string) => dayjs(readAt).format("YYYY-MM-DD HH:mm:ss"),
  },
  {
    title: "Import kWh Active",
    dataIndex: "import_active_kwh",
    key: "import_active_kwh",
    width: 180,
    render: num(ENERGY_DIGITS),
  },
  {
    title: "Import kvarh Reactive",
    dataIndex: "import_reactive_kvarh",
    key: "import_reactive_kvarh",
    width: 190,
    render: num(ENERGY_DIGITS),
  },
  {
    title: "Export kWh Active",
    dataIndex: "export_active_kwh",
    key: "export_active_kwh",
    width: 180,
    render: num(ENERGY_DIGITS),
  },
  {
    title: "Export kvarh Reactive",
    dataIndex: "export_reactive_kvarh",
    key: "export_reactive_kvarh",
    width: 190,
    render: num(ENERGY_DIGITS),
  },
  {
    title: "Avg Geo PF",
    dataIndex: "avg_geo_pf",
    key: "avg_geo_pf",
    width: 120,
    render: num(MEASUREMENT_DIGITS),
  },
  { title: "Voltage L1 (V)", dataIndex: "volt_l1", key: "volt_l1", width: 130, render: num(MEASUREMENT_DIGITS) },
  { title: "Voltage L2 (V)", dataIndex: "volt_l2", key: "volt_l2", width: 130, render: num(MEASUREMENT_DIGITS) },
  { title: "Voltage L3 (V)", dataIndex: "volt_l3", key: "volt_l3", width: 130, render: num(MEASUREMENT_DIGITS) },
  { title: "Current L1 (A)", dataIndex: "current_l1", key: "current_l1", width: 130, render: num(MEASUREMENT_DIGITS) },
  { title: "Current L2 (A)", dataIndex: "current_l2", key: "current_l2", width: 130, render: num(MEASUREMENT_DIGITS) },
  { title: "Current L3 (A)", dataIndex: "current_l3", key: "current_l3", width: 130, render: num(MEASUREMENT_DIGITS) },
  { title: "Frequency (Hz)", dataIndex: "freq", key: "freq", width: 130, render: num(MEASUREMENT_DIGITS) },
];

/** The total of every column width, so the horizontal scroll has something to scroll to. */
const TABLE_WIDTH = COLUMNS.reduce((sum, column) => sum + (Number(column.width) || 0), 0);

/**
 * Load Profile (M5b-1) — read a device's stored Interval Readings over a date
 * range.
 *
 * **Read-only, and it never talks to a meter.** Every row shown here was
 * recorded by the meter itself and stored by Read now (#15) or the Scheduler's
 * load-profile job (#16). The page has no Read now button of its own in this
 * slice — that capability already lives on the Devices page, and duplicating it
 * here was not part of what this slice was asked to ship (SPEC §3.5).
 *
 * **One list call paints the four filters.** Site group, brand, model and device
 * all narrow the array from a single `GET /api/devices` — the pattern the
 * Devices page states outright, because a request per device to fill a dropdown
 * of 10-30 meters is the N+1 that issue #5 already ruled out. The readings
 * endpoint takes only a `device_id`.
 *
 * **The table pages server-side, always.** A year of 15-minute intervals is
 * ~35,000 rows per meter; the endpoint caps a page at 500 so no caller can ask
 * for the table.
 *
 * **The range is converted from local days to UTC instants here**, so what was
 * filtered and what is displayed agree: the picker speaks in the operator's own
 * days, the API speaks in UTC, and the exclusive upper bound is "the start of
 * the day after the one you picked".
 */
export function LoadProfile() {
  const { message } = App.useApp();

  const [devices, setDevices] = useState<Device[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);

  const [site, setSite] = useState<string>(ALL);
  const [brand, setBrand] = useState<string>(ALL);
  const [model, setModel] = useState<string>(ALL);
  const [deviceId, setDeviceId] = useState<number | undefined>(undefined);
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs(), dayjs()]);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  // The loaded page is stored with the device+range it answers, so a page
  // belonging to the *previous* selection is never rendered under the new one.
  // Keying on the scope rather than the exact request is deliberate: changing
  // page must keep the current rows visible under the spinner (ordinary table
  // behaviour), while changing device or range must not.
  const [loaded, setLoaded] = useState<{ scope: string; page: LoadProfilePage } | null>(null);
  const [loading, setLoading] = useState(false);

  const surface = useCallback(
    (err: unknown, fallback: string) => {
      // Checked first, everywhere: a license that lapsed under a signed-in
      // operator must take them back to Activation, not show a toast.
      if (isLicenseLapsed(err)) {
        window.location.reload();
        return;
      }
      message.error(err instanceof ApiRequestError ? err.message : fallback);
    },
    [message],
  );

  useEffect(() => {
    // Issued separately, not as one `Promise.all`, because they are not equally
    // important (the pattern Devices.tsx follows for the same pair). The device
    // list is what every filter is built from; the catalog only supplies a
    // prettier model label, and `labelModel` already falls back without it.
    // Under `Promise.all` a catalog failure would discard the device list too
    // and strand the page on its Empty state with no meter selectable.
    api.listDevices().then(setDevices).catch((err: unknown) => surface(err, "Could not load the device list."));
    // Settled on its own and deliberately quiet: an unlabelled model reads as
    // "cewe · prometer100" instead of its catalog name, which costs nothing a
    // toast would recover.
    api.catalog().then(setCatalog).catch(() => setCatalog([]));
  }, [surface]);

  // ─── The cascade ────────────────────────────────────────────────────────────
  // Each level's options come from the devices still matching every filter
  // *above* it, so a combination that would select nothing is never offered.

  const bySite = useMemo(() => devices.filter((device) => site === ALL || device.site_name === site), [devices, site]);
  const byBrand = useMemo(() => bySite.filter((device) => brand === ALL || device.brand === brand), [bySite, brand]);
  const byModel = useMemo(() => byBrand.filter((device) => model === ALL || device.model === model), [byBrand, model]);

  /** Label a model the way the catalog does, falling back to the raw pair for a model this build has no driver for. */
  const labelModel = useCallback(
    (device: Device) =>
      catalog.find((entry) => entry.brand === device.brand && entry.model === device.model)?.ui_label ??
      `${device.brand} · ${device.model}`,
    [catalog],
  );

  const siteOptions = useMemo(
    () => [
      { value: ALL, label: "All site groups" },
      ...unique(devices.map((device) => device.site_name)).map((value) => ({ value, label: value })),
    ],
    [devices],
  );

  const brandOptions = useMemo(
    () => [
      { value: ALL, label: "All brands" },
      ...unique(bySite.map((device) => device.brand)).map((value) => ({ value, label: value })),
    ],
    [bySite],
  );

  const modelOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const device of byBrand) {
      if (!seen.has(device.model)) seen.set(device.model, labelModel(device));
    }
    return [
      { value: ALL, label: "All models" },
      ...[...seen].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label)),
    ];
  }, [byBrand, labelModel]);

  // No "All devices": a device must be chosen before the table has anything to
  // show, and offering "All" would promise a merged view this page does not do.
  const deviceOptions = useMemo(
    () =>
      [...byModel]
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((device) => ({
          value: device.id,
          label: device.meter_serial ? `${device.name} (${device.meter_serial})` : device.name,
        })),
    [byModel],
  );

  // Changing a broader filter drops the narrower ones — including the selected
  // device, which is how a device that falls out of the narrowed set is cleared.
  const onSiteChange = (value: string) => {
    setSite(value);
    setBrand(ALL);
    setModel(ALL);
    setDeviceId(undefined);
    setPage(1);
  };

  const onBrandChange = (value: string) => {
    setBrand(value);
    setModel(ALL);
    setDeviceId(undefined);
    setPage(1);
  };

  const onModelChange = (value: string) => {
    setModel(value);
    setDeviceId(undefined);
    setPage(1);
  };

  const onDeviceChange = (value: number) => {
    setDeviceId(value);
    setPage(1);
  };

  const onRangeChange = (dates: (Dayjs | null)[] | null) => {
    // `allowClear={false}` means the picker cannot hand back an empty range, but
    // its type permits one — so the range is only replaced when both ends are
    // real, and the previous one stands otherwise.
    const [from, to] = dates ?? [];
    if (!from || !to) return;
    setRange([from, to]);
    setPage(1);
  };

  // ─── The readings ───────────────────────────────────────────────────────────

  const [from, to] = range;
  // Local days in, UTC instants out. The upper bound is the *start of the day
  // after* the one picked, which is exactly the exclusive bound the API wants:
  // picking "the 3rd" on both ends asks for [3rd 00:00, 4th 00:00).
  const startIso = from.startOf("day").toISOString();
  const endIso = to.add(1, "day").startOf("day").toISOString();

  /** Which selection the rows on screen must belong to. Empty while no device is chosen. */
  const scope = deviceId === undefined ? "" : `${deviceId}|${startIso}|${endIso}`;
  const shown = loaded?.scope === scope ? loaded.page : null;

  useEffect(() => {
    if (deviceId === undefined) return;
    let current = true;
    // The setState lands in a promise callback once the API answers; only the
    // spinner is set synchronously, which is the "subscribe to an external
    // system" case the rule's own documentation permits — the same exemption
    // Devices.tsx and App.tsx already take for their fetches.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    void api
      .loadProfile(deviceId, startIso, endIso, pageSize, (page - 1) * pageSize)
      .then((result) => {
        // A slower earlier request must not overwrite a newer answer, and must
        // not un-set the spinner a newer request turned on.
        if (current) setLoaded({ scope: `${deviceId}|${startIso}|${endIso}`, page: result });
      })
      .catch((err: unknown) => {
        if (current) {
          setLoaded(null);
          surface(err, "Could not load the Interval Readings.");
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [deviceId, startIso, endIso, page, pageSize, surface]);

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card size="small">
        <Flex gap="small" wrap align="center">
          <Select
            value={site}
            onChange={onSiteChange}
            options={siteOptions}
            style={{ minWidth: 200 }}
            aria-label="Site group"
          />
          <Select
            value={brand}
            onChange={onBrandChange}
            options={brandOptions}
            style={{ minWidth: 160 }}
            aria-label="Brand"
          />
          <Select
            value={model}
            onChange={onModelChange}
            options={modelOptions}
            style={{ minWidth: 220 }}
            aria-label="Model"
          />
          <Select
            value={deviceId}
            onChange={onDeviceChange}
            options={deviceOptions}
            placeholder="Select a device"
            style={{ minWidth: 260 }}
            aria-label="Device"
          />
          <RangePicker
            value={range}
            onChange={onRangeChange}
            allowClear={false}
            // Only the future is out of reach. v1 also clamped the past to its
            // 90-day retention window. v2 has one from M5c, and still does not
            // clamp: retention runs once a day, so rows older than the cutoff
            // legitimately exist in the table between two runs, and clamping
            // would hide them. This page is M5b's and ships no new UI here.
            disabledDate={(current) => current.isAfter(dayjs().endOf("day"))}
          />
        </Flex>
      </Card>

      {deviceId === undefined ? (
        <Card>
          <Empty description="Select a device to view its Interval Readings" />
        </Card>
      ) : (
        <Card
          size="small"
          title={
            <Text type="secondary">
              {from.format("YYYY-MM-DD")} to {to.format("YYYY-MM-DD")}
            </Text>
          }
        >
          <Table<LoadProfileRow>
            size="small"
            // Unique per device: this is the Logger 1 spine of the read-side
            // merge, and `(device_id, logger_id, read_at)` is unique (ADR 0008).
            rowKey="read_at"
            loading={loading}
            dataSource={shown?.items ?? []}
            columns={COLUMNS}
            scroll={{ x: TABLE_WIDTH }}
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
      )}
    </Space>
  );
}

/** The distinct values of a list, sorted — one helper for three of the four filters. */
function unique(values: string[]): string[] {
  return [...new Set(values)].sort((a, b) => a.localeCompare(b));
}
