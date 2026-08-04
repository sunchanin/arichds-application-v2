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

import { ApiRequestError, api, type Device, type NewDevice, type Reading } from "../api";
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
 * This is the whole point of M1 — it proves the full chain end to end
 * (meter → driver → Poller → SQLite → API → browser). It refreshes on a timer
 * rather than a socket because 10 seconds is plenty for a 60-second poll
 * cadence, and a polling page has no reconnect logic to get wrong.
 */
export function Monitor() {
  const { message } = App.useApp();
  const [devices, setDevices] = useState<Device[]>([]);
  const [readings, setReadings] = useState<ReadingsByDevice>({});
  const [models, setModels] = useState<string[]>([]);
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
      .supportedModels()
      .then(setModels)
      .catch(() => setModels([]));
    const timer = window.setInterval(() => void refresh(), MONITOR_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const addDevice = async (values: NewDevice) => {
    setAdding(true);
    try {
      await api.createDevice({ ...values, password: values.password ?? "" });
      message.success(`Added ${values.name}`);
      form.resetFields();
      await refresh();
    } catch (err) {
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
        <Form form={form} layout="vertical" onFinish={addDevice} initialValues={{ port: 4059, brand: "CEWE" }}>
          <Row gutter={12}>
            <Col xs={24} sm={12} md={5}>
              <Form.Item name="name" label="Name" rules={[{ required: true }]}>
                <Input placeholder="Main incomer" />
              </Form.Item>
            </Col>
            <Col xs={12} sm={6} md={4}>
              <Form.Item name="brand" label="Brand" rules={[{ required: true }]}>
                <Input placeholder="CEWE" />
              </Form.Item>
            </Col>
            <Col xs={12} sm={6} md={4}>
              <Form.Item name="model" label="Model" rules={[{ required: true }]}>
                <Select
                  placeholder="Select"
                  options={models.map((model) => ({ value: model, label: model }))}
                />
              </Form.Item>
            </Col>
            <Col xs={14} sm={8} md={5}>
              <Form.Item name="host" label="Host" rules={[{ required: true }]}>
                <Input placeholder="192.168.1.100" />
              </Form.Item>
            </Col>
            <Col xs={10} sm={4} md={2}>
              <Form.Item name="port" label="Port" rules={[{ required: true }]}>
                <InputNumber min={1} max={65535} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={8} md={4}>
              <Form.Item name="password" label="Password">
                <Input.Password placeholder="Meter password" />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary" htmlType="submit" icon={<PlusOutlined />} loading={adding}>
            Add meter
          </Button>
        </Form>
      </Card>

      {devices.length === 0 && !loading ? (
        <Card>
          <Empty description="No meters yet. Add one above — pick model SIM to see the chain work without hardware." />
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
