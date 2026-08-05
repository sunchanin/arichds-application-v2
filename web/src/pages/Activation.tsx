import { CopyOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { Alert, App, Button, Card, Flex, Input, Space, theme, Typography } from "antd";
import { useState } from "react";

import { ApiRequestError, api, type LicenseStatus } from "../api";

const { Paragraph, Text, Title } = Typography;

/** Why the machine is limited, in words a site engineer can act on. */
const REASON_TEXT: Record<string, string> = {
  NO_LICENSE: "This machine has not been activated yet.",
  MALFORMED: "That code could not be read. Copy the whole line and try again.",
  INVALID_SIGNATURE: "That code failed its signature check. It may have been altered in transit.",
  WRONG_MACHINE: "That code was issued for a different machine. Check the Machine ID you sent the vendor.",
  EXPIRED: "That license has expired. Ask the vendor for a renewal.",
  WRONG_PRODUCT: "That code is not an ARICHDS Activation Code.",
  MACHINE_ID_UNAVAILABLE: "This machine's ID could not be read, so no license can be verified.",
};

function reasonText(reason: string | null): string {
  if (!reason) return "This machine is in Limited Mode.";
  return REASON_TEXT[reason] ?? `This machine is in Limited Mode (${reason}).`;
}

/**
 * First-run Activation page.
 *
 * Shows the Machine ID with a copy button and takes a pasted Activation Code.
 * On success the app moves straight to Monitor — activation applies live, with
 * no service restart (ADR 0001), so there is nothing to wait for.
 *
 * From M2-1 activating is admin-only (SPEC §3.2). A `user` still sees the
 * Machine ID — reading it is allowed, and being able to send it to the vendor
 * is exactly what someone on site needs to do — but the form is disabled rather
 * than left live to fail with a 403 on submit.
 *
 * The same page is reused later for renewing or replacing a license, and is
 * where online activation lands in M9.
 */
export function Activation({
  status,
  role,
  onActivated,
}: {
  status: LicenseStatus;
  role: "admin" | "user";
  onActivated: () => void;
}) {
  const { message } = App.useApp();
  // This page is permanent — reused for renewal and the home of M9's online
  // activation — so its backdrop tracks the theme, not a literal. `colorBgLayout`
  // is the same token AntD's own Layout uses for its body background.
  const { token } = theme.useToken();
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canActivate = role === "admin";

  const copyMachineId = async () => {
    try {
      await navigator.clipboard.writeText(status.machine_id);
      message.success("Machine ID copied");
    } catch {
      message.warning("Could not copy automatically — select the ID and copy it manually.");
    }
  };

  const activate = async () => {
    if (!code.trim()) {
      setError("Paste the Activation Code first.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.activate(code.trim());
      message.success("Activated. Starting the poller…");
      onActivated();
    } catch (err) {
      const detail =
        err instanceof ApiRequestError ? reasonText(err.reason) : "Could not reach the server. Is it running?";
      setError(detail);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Flex
      justify="center"
      align="center"
      style={{ minHeight: "100vh", padding: 24, background: token.colorBgLayout }}
    >
      <Card style={{ width: "100%", maxWidth: 680 }}>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <div>
            <Title level={3} style={{ marginBottom: 4 }}>
              <SafetyCertificateOutlined /> Activate ARICHDS
            </Title>
            <Text type="secondary">
              Send the Machine ID below to your vendor, then paste the Activation Code they return.
            </Text>
          </div>

          <Alert type="warning" showIcon message="Limited Mode" description={reasonText(status.reason)} />

          {canActivate ? null : (
            <Alert
              type="info"
              showIcon
              message="An administrator must activate this machine"
              description="Send the Machine ID below to your vendor, then ask an administrator to sign in and enter the code."
            />
          )}

          <div>
            <Text strong>Machine ID</Text>
            <Space.Compact style={{ width: "100%", marginTop: 8 }}>
              <Input readOnly value={status.machine_id} style={{ fontFamily: "monospace" }} />
              <Button icon={<CopyOutlined />} onClick={copyMachineId}>
                Copy
              </Button>
            </Space.Compact>
            <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
              This identifies this computer. Every license is bound to it.
            </Paragraph>
          </div>

          <div>
            <Text strong>Activation Code</Text>
            <Input.TextArea
              rows={4}
              value={code}
              disabled={!canActivate}
              onChange={(event) => setCode(event.target.value)}
              placeholder="Paste the single-line Activation Code here"
              style={{ marginTop: 8, fontFamily: "monospace", fontSize: 12 }}
            />
          </div>

          {error ? <Alert type="error" showIcon message={error} /> : null}

          <Button
            type="primary"
            size="large"
            block
            disabled={!canActivate}
            loading={submitting}
            onClick={activate}
          >
            Activate
          </Button>
        </Space>
      </Card>
    </Flex>
  );
}
