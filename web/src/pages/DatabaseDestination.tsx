import { App, Alert, Button, Card, Form, Input } from "antd";

interface FormValues {
  host: string;
  port: string;
  database: string;
  user: string;
  password: string;
}

/**
 * Database Destination (issue #37) — a presentation-only page for a
 * customer's own database as a Data-out Destination (CONTEXT.md, ADR 0016).
 *
 * There is no transport behind this page: the Data-out module (SPEC §3.8)
 * has not shipped, so nothing typed here is saved, sent, or read back. The
 * notice below is what keeps this from being mistaken for a working
 * connection form — ADR 0016's Consequences block requires the wording state
 * that ARICHDS pushes to this database rather than running on it, because a
 * form shaped like a connection form reads like v1's MySQL settings unless
 * it says otherwise.
 */
export function DatabaseDestination() {
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();

  return (
    <div>
      <div style={{ position: "sticky", top: 0, zIndex: 1, marginBlockEnd: 16 }}>
        <Alert
          type="warning"
          showIcon
          title="Not connected yet"
          description={
            <div style={{ display: "grid", gap: 8 }}>
              <p style={{ margin: 0 }}>
                ARICHDS pushes finished data <strong>to</strong> this database. It does not run on it — ARICHDS
                always keeps its own local store and keeps reading meters whether or not this destination is
                reachable.
              </p>
              <p style={{ margin: 0 }}>
                Nothing typed on this page is saved, sent, or stored. The transport that will use these settings
                ships with the Data-out module.
              </p>
            </div>
          }
        />
      </div>
      <Card size="small" title="Database Destination">
        <Form form={form} layout="vertical">
          <Form.Item name="host" label="Host">
            <Input />
          </Form.Item>
          <Form.Item name="port" label="Port">
            <Input inputMode="numeric" placeholder="3306" />
          </Form.Item>
          <Form.Item name="database" label="Database">
            <Input />
          </Form.Item>
          <Form.Item name="user" label="User">
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="password" label="Password">
            <Input.Password autoComplete="off" />
          </Form.Item>
          <Button
            onClick={() => {
              form.resetFields();
              message.success("Form cleared.");
            }}
          >
            Clear
          </Button>
        </Form>
      </Card>
    </div>
  );
}
