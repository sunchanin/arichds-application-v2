import { App, Alert, Button, Card, Form, Input, Select } from "antd";

interface FormValues {
  protocol: "FTPS" | "SFTP";
  host: string;
  port: string;
  user: string;
  password: string;
  remote_path: string;
}

// Module-private: react-refresh/only-export-components' allowConstantExport
// only exempts literal/unary/template/binary exports, not an array of
// objects (see Devices.tsx:71-74's note on the same constraint).
const PROTOCOL_OPTIONS = [
  { value: "FTPS", label: "FTPS" },
  { value: "SFTP", label: "SFTP" },
];

/**
 * File Upload Destination (issue #37) — a presentation-only page for an
 * encrypted-transfer Data-out Destination (CONTEXT.md). Plain FTP is
 * excluded by design (ADR 0016's Consequences block): only FTPS and SFTP are
 * offered, because a site's stated reason for choosing a file destination
 * over cloud upload is confidentiality, and plain FTP puts credentials and
 * data on the wire in clear text.
 *
 * There is no transport behind this page: the Data-out module (SPEC §3.8)
 * has not shipped, so nothing typed here is saved, sent, or read back.
 */
export function FileUploadDestination() {
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
                Only encrypted transfers are offered. Plain FTP is not an option: it puts the credentials and the
                data on the wire in clear text, and confidentiality is the stated reason a site chooses a file
                destination over cloud upload in the first place.
              </p>
              <p style={{ margin: 0 }}>
                Nothing typed on this page is saved, sent, or stored. The transport that will use these settings
                ships with the Data-out module.
              </p>
            </div>
          }
        />
      </div>
      <Card size="small" title="File Upload Destination">
        <Form form={form} layout="vertical">
          <Form.Item name="protocol" label="Protocol">
            <Select placeholder="Select a protocol" options={PROTOCOL_OPTIONS} />
          </Form.Item>
          <Form.Item name="host" label="Host">
            <Input />
          </Form.Item>
          <Form.Item name="port" label="Port">
            <Input inputMode="numeric" placeholder="990 (FTPS) or 22 (SFTP)" />
          </Form.Item>
          <Form.Item name="user" label="User">
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="password" label="Password">
            <Input.Password autoComplete="off" />
          </Form.Item>
          <Form.Item name="remote_path" label="Remote path">
            <Input />
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
