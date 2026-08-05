import { DeleteOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  App,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import {
  ApiRequestError,
  api,
  type CatalogEntry,
  type Device,
  type NewDevice,
  type Reading,
} from "../api";
import { MONITOR_REFRESH_MS } from "../theme";

const { Text, Title } = Typography;

type ReadingsByDevice = Record<number, Reading | null>;

/** Format a number for display, or an em dash when the meter gave nothing. */
function show(value: number | null | undefined, digits = 1, unit = ""): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(digits)}${unit}`;
}

/**
 * The monitor page: add a meter, watch its values arrive.
 *
 * It proves the full chain end to end (meter → driver → Poller → SQLite → API →
 * browser). It refreshes on a timer rather than a socket because 10 seconds is
 * plenty for a 60-second poll cadence, and a polling page has no reconnect
 * logic to get wrong.
 *
 * Adding a meter **connects to it** before the row exists (ADR 0005), so the
 * button takes seconds and can fail for reasons that have nothing to do with
 * the form. The hint below the form says so, and a refusal shows the API's own
 * sentence — which distinguishes a wrong password from no route to host,
 * because the operator's next action differs completely.
 */
export function Monitor() {
  const { message } = App.useApp();
  const [devices, setDevices] = useState<Device[]>([]);
  const [readings, setReadings] = useState<ReadingsByDevice>({});
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [form] = Form.useForm<NewDevice>();

  const refresh = useCallback(async () => {
    try {
      const list = await api.listDevices();
      setDevices(list);
      const entries = await Promise.all(
        list.map(async (device) => {
          try {
            return [device.id, await api.latestReading(device.id)] as const;
          } catch {
            return [device.id, null] as const;
          }
        }),
      );
      setReadings(Object.fromEntries(entries));
    } catch (err) {
      if (err instanceof ApiRequestError && err.code === "LICENSE_INVALID") {
        // The license lapsed while the page was open — reload so the app falls
        // back to the Activation page rather than showing a dead grid.
        window.location.reload();
        return;
      }
      message.error("Could not load devices");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    // Both calls are async: state is set from promise callbacks once the API
    // answers, never synchronously in the effect body. Polling a backend on a
    // timer is exactly the external-system subscription the rule permits.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    api
      .catalog()
      .then(setCatalog)
      .catch(() => setCatalog([]));
    const timer = window.setInterval(() => void refresh(), MONITOR_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  /** Prefill the fields the catalog knows the answer to. */
  const onModelChange = (model: string) => {
    const entry = catalog.find((candidate) => candidate.model === model);
    if (!entry) return;
    form.setFieldsValue({
      brand: entry.brand,
      ...(entry.default_port !== null ? { port: entry.default_port } : {}),
      ...(entry.fixed_password !== null ? { password: entry.fixed_password } : {}),
    });
  };

  const addDevice = async (values: NewDevice) => {
    setAdding(true);
    try {
      await api.createDevice({ ...values, password: values.password ?? "" });
      message.success(`Added ${values.name}`);
      form.resetFields();
      await refresh();
    } catch (err) {
      // The API's message names the endpoint and the cause (wrong password,
      // timeout, no route). Showing it verbatim is the point — a generic
      // "could not add" would send the operator looking in the wrong place.
      message.error(err instanceof ApiRequestError ? err.message : "Could not add the device");
    } finally {
      setAdding(false);
    }
  };

  const removeDevice = async (device: Device) => {
    try {
      await api.deleteDevice(device.id);
      message.success(`Removed ${device.name}`);
      await refresh();
    } catch {
      message.error("Could not remove the device");
    }
  };

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Row justify="space-between" align="middle">
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            Monitor
          </Title>
          <Text type="secondary">Latest reading per meter. Refreshes every {MONITOR_REFRESH_MS / 1000}s.</Text>
        </Col>
        <Col>
          <Button icon={<ReloadOutlined />} onClick={() => void refresh()}>
            Refresh
          </Button>
        </Col>
      </Row>

      <Card size="small" title="Add a meter">
        <Form form={form} layout="vertical" onFinish={addDevice} initialValues={{ port: 4059 }}>
          <Row gutter={12}>
            <Col xs={24} sm={12} md={5}>
              <Form.Item name="name" label="Name" rules={[{ required: true }]}>
                <Input placeholder="Main incomer" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={5}>
              <Form.Item name="site_name" label="Site name" rules={[{ required: true }]}>
                <Input placeholder="Plant A" />
              </Form.Item>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Form.Item name="model" label="Model" rules={[{ required: true }]}>
                <Select
                  placeholder="Select"
                  onChange={onModelChange}
                  options={catalog.map((entry) => ({ value: entry.model, label: entry.ui_label }))}
                />
              </Form.Item>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Form.Item name="brand" label="Brand" rules={[{ required: true }]}>
                <Input placeholder="cewe" />
              </Form.Item>
            </Col>
            <Col xs={14} sm={8} md={4}>
              <Form.Item name="host" label="Host" rules={[{ required: true }]}>
                <Input placeholder="192.168.1.100" />
              </Form.Item>
            </Col>
            <Col xs={10} sm={6} md={2}>
              <Form.Item name="port" label="Port" rules={[{ required: true }]}>
                <InputNumber min={1} max={65535} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={10} md={4}>
              <Form.Item name="password" label="Password">
                <Input.Password placeholder="Meter password" />
              </Form.Item>
            </Col>
          </Row>
          <Space size="middle" align="center" wrap>
            <Button type="primary" htmlType="submit" icon={<PlusOutlined />} loading={adding}>
              Add meter
            </Button>
            <Text type="secondary">
              Adding connects to the meter to read its serial number — this can take a few seconds.
            </Text>
          </Space>
        </Form>
      </Card>

      {devices.length === 0 && !loading ? (
        <Card>
          <Empty description="No meters yet. Add one above — the meter must be reachable, because its serial number is read from it." />
        </Card>
      ) : null}

      <Row gutter={[16, 16]}>
        {devices.map((device) => {
          const reading = readings[device.id] ?? null;
          return (
            <Col key={device.id} xs={24} xl={12}>
              <Card
                loading={loading && !reading}
                title={
                  <Space>
                    <span>{device.name}</span>
                    <Tag>{device.model}</Tag>
                    <Text type="secondary" style={{ fontWeight: 400, fontSize: 12 }}>
                      {device.endpoint}
                      {/* Null only for a row created before M3, which the next
                          Update identifies (ADR 0005). */}
                      {device.meter_serial ? ` · serial ${device.meter_serial}` : ""}
                    </Text>
                  </Space>
                }
                extra={
                  <Popconfirm title={`Remove ${device.name}?`} onConfirm={() => void removeDevice(device)}>
                    <Button size="small" danger type="text" icon={<DeleteOutlined />} />
                  </Popconfirm>
                }
              >
                {reading ? (
                  <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                    <Row gutter={16}>
                      <Col span={8}>
                        <Statistic title="Frequency" value={show(reading.freq, 2)} suffix="Hz" />
                      </Col>
                      <Col span={16}>
                        <Statistic
                          title="Import energy"
                          value={show(reading.import_active_kwh, 3)}
                          suffix="kWh"
                        />
                      </Col>
                    </Row>
                    <Table<{ key: string; phase: string; volts: string; amps: string }>
                      size="small"
                      pagination={false}
                      dataSource={[
                        {
                          key: "l1",
                          phase: "L1",
                          volts: show(reading.volt_l1, 1, " V"),
                          amps: show(reading.current_l1, 2, " A"),
                        },
                        {
                          key: "l2",
                          phase: "L2",
                          volts: show(reading.volt_l2, 1, " V"),
                          amps: show(reading.current_l2, 2, " A"),
                        },
                        {
                          key: "l3",
                          phase: "L3",
                          volts: show(reading.volt_l3, 1, " V"),
                          amps: show(reading.current_l3, 2, " A"),
                        },
                      ]}
                      columns={[
                        { title: "Phase", dataIndex: "phase", key: "phase" },
                        { title: "Voltage", dataIndex: "volts", key: "volts" },
                        { title: "Current", dataIndex: "amps", key: "amps" },
                      ]}
                    />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      Read at {dayjs(reading.read_at).format("YYYY-MM-DD HH:mm:ss")} (local) · source{" "}
                      {reading.source} · interval {reading.interval}
                    </Text>
                  </Space>
                ) : (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="Waiting for the first reading (up to 60s)…"
                  />
                )}
              </Card>
            </Col>
          );
        })}
      </Row>
    </Space>
  );
}
