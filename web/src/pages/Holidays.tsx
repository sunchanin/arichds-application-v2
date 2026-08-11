import {
  App,
  Button,
  Card,
  DatePicker,
  Empty,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Table,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiRequestError,
  api,
  isLicenseLapsed,
  type CatalogEntry,
  type Device,
  type Holiday,
  type HolidayInput,
  type HolidayKind,
} from "../api";

/** Shown wherever a value is absent. */
const NOTHING = "—";

/** How one holiday's day is shown, regardless of kind. */
function holidayDay(row: Holiday): string {
  return row.kind === "public" ? (row.date ?? NOTHING) : `${row.month}/${row.day} (every year)`;
}

interface HolidayFormValues {
  kind: HolidayKind;
  name: string;
  date?: import("dayjs").Dayjs;
  month?: number;
  day?: number;
}

function HolidayFormModal({
  open,
  editing,
  onClose,
  onSaved,
  surface,
}: {
  open: boolean;
  editing: Holiday | null;
  onClose: () => void;
  onSaved: () => void;
  surface: (err: unknown, fallback: string) => void;
}) {
  const [form] = Form.useForm<HolidayFormValues>();
  const [saving, setSaving] = useState(false);
  const kind = Form.useWatch("kind", form) ?? "annual";

  useEffect(() => {
    if (!open) return;
    form.resetFields();
    if (editing) {
      form.setFieldsValue({
        kind: editing.kind,
        name: editing.name,
        date: editing.date ? dayjs(editing.date) : undefined,
        month: editing.month ?? undefined,
        day: editing.day ?? undefined,
      });
    } else {
      form.setFieldsValue({ kind: "annual" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing]);

  const onFinish = (values: HolidayFormValues) => {
    const input: HolidayInput =
      values.kind === "annual"
        ? { kind: "annual", name: values.name, month: values.month, day: values.day }
        : { kind: "public", name: values.name, date: values.date?.format("YYYY-MM-DD") };

    setSaving(true);
    const save = editing ? api.updateHoliday(editing.id, input) : api.createHoliday(input);
    save
      .then(() => {
        onSaved();
        onClose();
      })
      .catch((err: unknown) => surface(err, "Could not save the holiday."))
      .finally(() => setSaving(false));
  };

  return (
    <Modal
      open={open}
      title={editing ? "Edit holiday" : "Add holiday"}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={saving}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={onFinish}>
        <Form.Item name="kind" label="Kind" rules={[{ required: true }]}>
          <Radio.Group
            options={[
              { value: "annual", label: "Annual (recurs every year)" },
              { value: "public", label: "Public (one exact date)" },
            ]}
          />
        </Form.Item>
        <Form.Item name="name" label="Name" rules={[{ required: true, message: "Name is required" }]}>
          <Input placeholder="e.g. New Year's Day" />
        </Form.Item>
        {kind === "annual" ? (
          <Flex gap="small">
            <Form.Item name="month" label="Month" rules={[{ required: true }]} style={{ flex: 1 }}>
              <InputNumber min={1} max={12} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="day" label="Day" rules={[{ required: true }]} style={{ flex: 1 }}>
              <InputNumber min={1} max={31} style={{ width: "100%" }} />
            </Form.Item>
          </Flex>
        ) : (
          <Form.Item name="date" label="Date" rules={[{ required: true }]}>
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

/**
 * Holidays (M7-1, issue #28) — the machine-wide calendar the Energy
 * Summary's Holiday bucket is judged against (CONTEXT.md — Holiday).
 *
 * **No device column** — holidays are machine-wide. **Import replaces the
 * whole set**, from either JSON or a meter, and both imports confirm first,
 * naming how many current rows will be lost (decision 13) — the backend
 * never blocks on it.
 */
export function Holidays({ role }: { role: "admin" | "user" }) {
  const { message, modal } = App.useApp();
  const [holidays, setHolidays] = useState<Holiday[]>([]);
  const [loading, setLoading] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Holiday | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [meterDeviceId, setMeterDeviceId] = useState<number | undefined>(undefined);
  const [importingFromMeter, setImportingFromMeter] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

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

  const load = useCallback(() => {
    setLoading(true);
    api
      .listHolidays()
      .then(setHolidays)
      .catch((err: unknown) => surface(err, "Could not load the Holidays."))
      .finally(() => setLoading(false));
  }, [surface]);

  useEffect(() => {
    // `load` itself calls setState synchronously (setLoading(true)) — this
    // is the mount fetch, the one case that pattern is meant for (matches
    // Billing.tsx/Records.tsx's own inline version of this exact shape).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  useEffect(() => {
    if (role !== "admin") return;
    api.listDevices().then(setDevices).catch(() => setDevices([]));
    api.catalog().then(setCatalog).catch(() => setCatalog([]));
  }, [role]);

  const supportedModels = useMemo(
    () => new Set(catalog.filter((entry) => entry.supports_special_days).map((entry) => `${entry.brand}/${entry.model}`)),
    [catalog],
  );
  const meterDeviceOptions = useMemo(
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

  const onDelete = (row: Holiday) => {
    api
      .deleteHoliday(row.id)
      .then(() => {
        message.success("Holiday deleted.");
        load();
      })
      .catch((err: unknown) => surface(err, "Could not delete the holiday."));
  };

  const onExport = () => {
    api
      .exportHolidays()
      .then((document) => {
        const blob = new Blob([JSON.stringify(document, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const link = window.document.createElement("a");
        link.href = url;
        link.download = "holidays.json";
        window.document.body.appendChild(link);
        link.click();
        window.document.body.removeChild(link);
        URL.revokeObjectURL(url);
      })
      .catch((err: unknown) => surface(err, "Could not export the Holidays."));
  };

  const doImportJson = (document: { version: number; holidays: HolidayInput[] }) => {
    api
      .importHolidays(document)
      .then((imported) => {
        message.success(`Imported ${imported.length} holiday(s).`);
        load();
      })
      .catch((err: unknown) => surface(err, "Could not import the file."));
  };

  const onImportJsonPicked = (file: File) => {
    file
      .text()
      .then((text) => {
        const parsed: unknown = JSON.parse(text);
        const document = parsed as { version: number; holidays: HolidayInput[] };
        modal.confirm({
          title: "Replace the whole calendar?",
          content: `This will remove all ${holidays.length} currently stored holiday(s) and replace them with ${document.holidays.length} from the file.`,
          okText: "Replace",
          onOk: () => doImportJson(document),
        });
      })
      .catch(() => message.error("That file is not valid JSON."));
  };

  const onImportFromMeter = () => {
    if (meterDeviceId === undefined) return;
    modal.confirm({
      title: "Replace the whole calendar from this meter?",
      content: `This will remove all ${holidays.length} currently stored holiday(s) and replace them with whatever this meter's Special Days Table holds.`,
      okText: "Replace",
      onOk: () => {
        setImportingFromMeter(true);
        api
          .importHolidaysFromMeter(meterDeviceId)
          .then((result) => {
            message.success(
              result.skipped > 0
                ? `Imported ${result.imported.length} holiday(s), skipped ${result.skipped} duplicate(s) from the meter.`
                : `Imported ${result.imported.length} holiday(s).`,
            );
            load();
          })
          .catch((err: unknown) => surface(err, "Could not import from the meter."))
          .finally(() => setImportingFromMeter(false));
      },
    });
  };

  const columns: ColumnsType<Holiday> = useMemo(() => {
    const base: ColumnsType<Holiday> = [
      { title: "Kind", dataIndex: "kind", key: "kind", width: 100, render: (kind: HolidayKind) => (kind === "annual" ? "Annual" : "Public") },
      { title: "Name", dataIndex: "name", key: "name" },
      { title: "Day", key: "day", render: (_: unknown, row: Holiday) => holidayDay(row) },
    ];
    if (role !== "admin") return base;
    return [
      ...base,
      {
        title: "Actions",
        key: "actions",
        width: 160,
        render: (_: unknown, row: Holiday) => (
          <Space size="small">
            <Button
              size="small"
              onClick={() => {
                setEditing(row);
                setFormOpen(true);
              }}
            >
              Edit
            </Button>
            <Popconfirm title="Delete this holiday?" onConfirm={() => onDelete(row)}>
              <Button size="small" danger>
                Delete
              </Button>
            </Popconfirm>
          </Space>
        ),
      },
    ];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card size="small">
        <Flex gap="small" wrap align="center">
          {role === "admin" ? (
            <Button
              type="primary"
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              Add holiday
            </Button>
          ) : null}
          <Button onClick={onExport}>Export JSON</Button>
          {role === "admin" ? (
            <>
              <Button onClick={() => fileInputRef.current?.click()}>Import JSON</Button>
              <input
                ref={fileInputRef}
                type="file"
                accept="application/json"
                style={{ display: "none" }}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) onImportJsonPicked(file);
                  event.target.value = "";
                }}
              />
              <Select
                value={meterDeviceId}
                onChange={setMeterDeviceId}
                options={meterDeviceOptions}
                placeholder="Select a meter"
                style={{ minWidth: 240 }}
                aria-label="Meter to import from"
              />
              <Button onClick={onImportFromMeter} loading={importingFromMeter} disabled={meterDeviceId === undefined}>
                Import from meter
              </Button>
            </>
          ) : null}
        </Flex>
      </Card>
      <Card size="small">
        <Table<Holiday>
          size="small"
          rowKey={(row) => row.id}
          loading={loading}
          dataSource={holidays}
          columns={columns}
          pagination={false}
          locale={{ emptyText: <Empty description="No holidays configured" /> }}
        />
      </Card>
      {role === "admin" ? (
        <HolidayFormModal
          open={formOpen}
          editing={editing}
          onClose={() => setFormOpen(false)}
          onSaved={load}
          surface={surface}
        />
      ) : null}
    </Space>
  );
}
