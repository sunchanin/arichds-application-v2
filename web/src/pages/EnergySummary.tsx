import { App, Button, Card, DatePicker, Descriptions, Empty, Flex, Select, Space, Table, Tabs } from "antd";
import type { DescriptionsItemType } from "antd/es/descriptions";
import type { ColumnsType } from "antd/es/table";
import type { TabsProps } from "antd/es/tabs";
import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiRequestError,
  api,
  isLicenseLapsed,
  type CatalogEntry,
  type Device,
  type EnergyRegisterRow,
  type EnergySummaryDay,
} from "../api";
import { type UnitKind, scaleValue, unitLabel, useDisplayUnitScale } from "../units";

const { RangePicker } = DatePicker;

/** Shown wherever a value is absent. */
const NOTHING = "—";

/** The most local days one Summary Report request may span (matches the
 * server's own bound — `api/energy.py`'s `MAX_DAYS`). */
const MAX_DAYS = 31;

const num =
  (digits: number) =>
  (value: number | null): string =>
    value == null ? NOTHING : value.toFixed(digits);

const num2 = num(2);

const TAB_ITEMS: TabsProps["items"] = [
  { key: "summary", label: "Summary Report" },
  { key: "registers", label: "Meter Registers" },
];

function SummaryReportTab({
  devices,
  surface,
}: {
  devices: Device[];
  surface: (err: unknown, fallback: string) => void;
}) {
  const { message } = App.useApp();
  const scale = useDisplayUnitScale();
  const [deviceId, setDeviceId] = useState<number | undefined>(undefined);
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(6, "day"), dayjs()]);
  const [days, setDays] = useState<EnergySummaryDay[]>([]);
  const [loading, setLoading] = useState(false);

  const deviceOptions = useMemo(
    () =>
      [...devices]
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((device) => ({
          value: device.id,
          label: device.meter_serial ? `${device.name} (${device.meter_serial})` : device.name,
        })),
    [devices],
  );

  useEffect(() => {
    // No device selected — nothing to fetch. `days` is left as-is; the
    // render below shows an empty table whenever `deviceId` is undefined,
    // so there is no need to clear it here (and doing so would call
    // setState synchronously in the effect body for no rendering benefit).
    if (deviceId === undefined) return;
    let current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    void api
      .energySummary(deviceId, range[0].format("YYYY-MM-DD"), range[1].format("YYYY-MM-DD"))
      .then((result) => {
        if (current) setDays(result.days);
      })
      .catch((err: unknown) => {
        if (current) {
          setDays([]);
          surface(err, "Could not load the Energy Summary.");
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [deviceId, range, surface]);

  const shownDays = deviceId === undefined ? [] : days;

  const columns: ColumnsType<EnergySummaryDay> = useMemo(() => {
    const kwh = (title: string, dataIndex: keyof EnergySummaryDay) => ({
      title: `${title} (${unitLabel("energy", scale)})`,
      dataIndex,
      key: dataIndex,
      width: 130,
      render: (value: number) => num2(scaleValue(value, scale) ?? null),
    });
    return [
      { title: "Date", dataIndex: "date", key: "date", width: 110, fixed: "left" as const },
      kwh("Peak Import", "peak_import_kwh"),
      kwh("Off-Peak Import", "offpeak_import_kwh"),
      kwh("Holiday Import", "holiday_import_kwh"),
      kwh("Total Import", "total_import_kwh"),
      kwh("Peak Export", "peak_export_kwh"),
      kwh("Off-Peak Export", "offpeak_export_kwh"),
      kwh("Holiday Export", "holiday_export_kwh"),
      kwh("Total Export", "total_export_kwh"),
    ];
  }, [scale]);

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card size="small">
        <Flex gap="small" wrap align="center">
          <Select
            value={deviceId}
            onChange={setDeviceId}
            options={deviceOptions}
            placeholder="Select a device"
            style={{ minWidth: 260 }}
            aria-label="Device"
          />
          <RangePicker
            value={range}
            allowClear={false}
            disabledDate={(current) => current.isAfter(dayjs().endOf("day"))}
            onChange={(dates) => {
              const [from, to] = dates ?? [];
              if (!from || !to) return;
              // The server refuses a span over MAX_DAYS with 422 — clamped
              // here too so the picker never sends a request the API will
              // only reject. Named explicitly rather than silently snapping
              // back to the previous range, which left no clue why the
              // picker "didn't take" the selection.
              if (to.diff(from, "day") + 1 > MAX_DAYS) {
                message.info(`A Summary Report request may span at most ${MAX_DAYS} days.`);
                return;
              }
              setRange([from, to]);
            }}
            aria-label="Date range"
          />
        </Flex>
      </Card>
      <Card size="small">
        <Table<EnergySummaryDay>
          size="small"
          rowKey={(row) => row.date}
          loading={loading}
          dataSource={shownDays}
          columns={columns}
          scroll={{ x: 110 + 130 * 8 }}
          pagination={false}
          locale={{
            emptyText: (
              <Empty
                description={deviceId === undefined ? "Select a device to see its Energy Summary" : "No data in range"}
              />
            ),
          }}
        />
      </Card>
    </Space>
  );
}

function MeterRegistersTab({
  devices,
  catalog,
  surface,
}: {
  devices: Device[];
  catalog: CatalogEntry[];
  surface: (err: unknown, fallback: string) => void;
}) {
  const { message } = App.useApp();
  const scale = useDisplayUnitScale();
  const [deviceId, setDeviceId] = useState<number | undefined>(undefined);
  const [latest, setLatest] = useState<EnergyRegisterRow | null>(null);
  const [loading, setLoading] = useState(false);
  const [reading, setReading] = useState(false);

  // Only meters this build can actually read Energy Registers from (ADR
  // 0011: the driver is the authority; the catalog flag mirrors it).
  const supportedModels = useMemo(
    () => new Set(catalog.filter((entry) => entry.supports_energy_summary).map((entry) => `${entry.brand}/${entry.model}`)),
    [catalog],
  );
  const deviceOptions = useMemo(
    () =>
      [...devices]
        .filter((device) => supportedModels.has(`${device.brand}/${device.model}`))
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((device) => ({
          value: device.id,
          label: device.meter_serial ? `${device.name} (${device.meter_serial})` : device.name,
        })),
    [devices, supportedModels],
  );

  const loadLatest = useCallback(
    (id: number) => {
      api
        .energyRegisters(id)
        .then((rows) => setLatest(rows[0] ?? null))
        .catch((err: unknown) => surface(err, "Could not load the stored Energy Registers."))
        .finally(() => setLoading(false));
    },
    [surface],
  );

  useEffect(() => {
    // No device selected — nothing to fetch; `shownLatest` below hides
    // `latest` in that case, so there is nothing to clear here.
    if (deviceId === undefined) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    loadLatest(deviceId);
  }, [deviceId, loadLatest]);

  const shownLatest = deviceId === undefined ? null : latest;

  const onReadNow = () => {
    if (deviceId === undefined) return;
    setReading(true);
    api
      .readEnergyRegisters(deviceId)
      .then((result) => {
        // A live-read failure is a verdict on `result.error`, never a
        // thrown error (mirrors Test Connection) — surfaced as a toast
        // rather than `surface()`, which is reserved for request-layer
        // failures (network, 4xx/5xx, license lapse).
        if (result.error) {
          message.error(result.error);
          return;
        }
        setLatest(result.row);
        message.success("Energy Registers read.");
      })
      .catch((err: unknown) => surface(err, "Could not read the Energy Registers."))
      .finally(() => setReading(false));
  };

  const group = (title: string, prefix: string, unit: UnitKind): DescriptionsItemType | null => {
    if (!shownLatest) return null;
    const value = (suffix: string) =>
      num2(scaleValue(shownLatest[`${prefix}_${suffix}` as keyof EnergyRegisterRow] as number | null, scale) ?? null);
    return {
      key: prefix,
      label: `${title} (${unitLabel(unit, scale)})`,
      children: (
        <>
          Total {value("total")} · A {value("rate_a")} · B {value("rate_b")} · C {value("rate_c")} · D {value("rate_d")}
        </>
      ),
    };
  };

  // `Descriptions`' `items` prop, not JSX `<Descriptions.Item>` children —
  // the latter is `@deprecated` in the installed AntD v6 (`items` instead).
  const items: DescriptionsItemType[] = shownLatest
    ? [
        { key: "read_at", label: "Read at", children: dayjs(shownLatest.read_at).format("YYYY-MM-DD HH:mm:ss") },
        { key: "meter_serial", label: "Meter Serial", children: shownLatest.meter_serial ?? NOTHING },
        group("Import Active", "import_active_kwh", "energy"),
        group("Export Active", "export_active_kwh", "energy"),
        group("Import Reactive", "import_reactive_kvarh", "reactiveEnergy"),
        group("Export Reactive", "export_reactive_kvarh", "reactiveEnergy"),
      ].filter((item): item is DescriptionsItemType => item !== null)
    : [];

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card size="small">
        <Flex gap="small" wrap align="center">
          <Select
            value={deviceId}
            onChange={setDeviceId}
            options={deviceOptions}
            placeholder="Select a device"
            style={{ minWidth: 260 }}
            aria-label="Device"
          />
          <Button type="primary" onClick={onReadNow} loading={reading} disabled={deviceId === undefined}>
            Read now
          </Button>
        </Flex>
      </Card>
      <Card size="small" loading={loading} title="Latest reading">
        {shownLatest ? (
          <Descriptions column={1} size="small" items={items} />
        ) : (
          <Empty description={deviceId === undefined ? "Select a device" : "No reading stored yet — press Read now"} />
        )}
      </Card>
    </Space>
  );
}

/**
 * Energy Summary (M7-1, issue #28) — the Time-of-Use report and the Energy
 * Registers page, sharing one license key (`energy_summary`) and nothing
 * else (CONTEXT.md — Energy Summary / Energy Registers are two different
 * things: one is arithmetic over Interval Readings already stored, the
 * other is a fresh dated snapshot of the meter's own cumulative counters).
 *
 * **Summary Report is derived, never stored** (ADR 0012) — every load
 * re-aggregates `load_profile_readings` live, the same way Records counts
 * its cells. **Meter Registers is button-triggered only** — there is no
 * scheduler job (decision — a cumulative snapshot is not a cadence).
 */
export function EnergySummary() {
  const { message } = App.useApp();
  const [tab, setTab] = useState("summary");
  const [devices, setDevices] = useState<Device[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);

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

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Tabs activeKey={tab} onChange={setTab} items={TAB_ITEMS} />
      {tab === "summary" ? (
        <SummaryReportTab devices={devices} surface={surface} />
      ) : (
        <MeterRegistersTab devices={devices} catalog={catalog} surface={surface} />
      )}
    </Space>
  );
}
