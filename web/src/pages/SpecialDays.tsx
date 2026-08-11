import { App, Alert, Card, Empty, Flex, Select, Space, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiRequestError, api, isLicenseLapsed, type CatalogEntry, type Device, type SpecialDay } from "../api";

function specialDayDate(row: SpecialDay): string {
  const month = String(row.month).padStart(2, "0");
  const day = String(row.day).padStart(2, "0");
  return row.kind === "public" && row.year != null ? `${row.year}-${month}-${day}` : `${month}-${day} (every year)`;
}

/**
 * Special Days (M7-1, issue #28) — a read-through view of a selected
 * meter's own COSEM class-11 Special Days Table (CONTEXT.md — Holiday).
 *
 * **Stores nothing.** Every load re-reads the meter through the Manual
 * Read lock. Turning one of these entries into a stored Holiday is a
 * separate, explicit action on the Holidays page ("Import from meter").
 */
export function SpecialDays() {
  const { message } = App.useApp();
  const [devices, setDevices] = useState<Device[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [deviceId, setDeviceId] = useState<number | undefined>(undefined);
  const [entries, setEntries] = useState<SpecialDay[]>([]);
  const [readError, setReadError] = useState<string | null>(null);
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
    () => new Set(catalog.filter((entry) => entry.supports_special_days).map((entry) => `${entry.brand}/${entry.model}`)),
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

  useEffect(() => {
    // No device selected — nothing to fetch; `shownEntries` below hides
    // `entries` in that case, so there is nothing to clear here.
    if (deviceId === undefined) return;
    let current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    void api
      .specialDays(deviceId)
      .then((result) => {
        // A live-read failure is a verdict on `result.error`, never a
        // thrown error (mirrors Test Connection) — `result.entries` is
        // already `[]` on that path, so there is nothing else to clear.
        if (current) {
          setEntries(result.entries);
          setReadError(result.error);
        }
      })
      .catch((err: unknown) => {
        if (current) {
          setEntries([]);
          setReadError(null);
          surface(err, "Could not read the Special Days Table.");
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [deviceId, surface]);

  const shownEntries = deviceId === undefined ? [] : entries;

  const columns: ColumnsType<SpecialDay> = [
    { title: "Index", dataIndex: "index", key: "index", width: 80 },
    { title: "Day", key: "day", render: (_: unknown, row: SpecialDay) => specialDayDate(row) },
    { title: "Day ID", dataIndex: "day_id", key: "day_id", width: 100 },
  ];

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
        </Flex>
      </Card>
      {readError ? (
        <Alert type="error" showIcon message={readError} />
      ) : (
        <Alert
          type="info"
          showIcon
          message="This is what the meter itself holds right now — it is not stored anywhere."
        />
      )}
      <Card size="small">
        <Table<SpecialDay>
          size="small"
          rowKey={(row) => row.index}
          loading={loading}
          dataSource={shownEntries}
          columns={columns}
          pagination={false}
          locale={{
            emptyText: (
              <Empty description={deviceId === undefined ? "Select a device" : "The meter reports no special days"} />
            ),
          }}
        />
      </Card>
    </Space>
  );
}
