import { UserAddOutlined } from "@ant-design/icons";
import { Alert, App, Button, Card, Flex, Form, Input, Space, theme, Typography } from "antd";
import { useState } from "react";

import { ApiRequestError, api } from "../api";

const { Text, Title } = Typography;

/** Minimum password length, mirroring the API's own rule (SPEC §3.2). */
const MIN_PASSWORD_LENGTH = 8;

interface SetupForm {
  username: string;
  password: string;
  confirm: string;
}

/**
 * First-run Setup: create the one bootstrap admin.
 *
 * Shown only while zero accounts exist — `GET /api/auth/check-setup` is what
 * decides that, and once an account exists this page is never reachable again.
 *
 * A successful Setup deliberately does **not** sign the new admin in. Typing
 * the password once more against the real Login form is the cheapest possible
 * proof that it was recorded as intended — and at this moment it matters most,
 * because this is the only account on the machine and an admin may not reset
 * its own password (M2-2). Until a second admin exists there is nobody who
 * could rescue a mistyped one.
 */
export function Setup({ onComplete }: { onComplete: (username: string) => void }) {
  const { message } = App.useApp();
  const { token } = theme.useToken();
  const [form] = Form.useForm<SetupForm>();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (values: SetupForm) => {
    setSubmitting(true);
    setError(null);
    try {
      const user = await api.setup({ username: values.username, password: values.password });
      message.success("Administrator account created. Please sign in.");
      onComplete(user.username);
    } catch (err) {
      setError(
        err instanceof ApiRequestError ? err.message : "Could not reach the server. Is it running?",
      );
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
      <Card style={{ width: "100%", maxWidth: 480 }}>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <div>
            <Title level={3} style={{ marginBottom: 4 }}>
              <UserAddOutlined /> Set up ARICHDS
            </Title>
            <Text type="secondary">
              Create the administrator account for this machine. This is done once — afterwards
              accounts are managed from inside the app.
            </Text>
          </div>

          {error ? <Alert type="error" showIcon message={error} /> : null}

          <Form form={form} layout="vertical" onFinish={(values) => void submit(values)} disabled={submitting}>
            <Form.Item
              name="username"
              label="Username"
              rules={[
                { required: true, message: "Choose a username." },
                { min: 3, message: "Use at least 3 characters." },
                { max: 64, message: "Use at most 64 characters." },
              ]}
            >
              <Input autoFocus autoComplete="username" />
            </Form.Item>

            <Form.Item
              name="password"
              label="Password"
              rules={[
                { required: true, message: "Choose a password." },
                { min: MIN_PASSWORD_LENGTH, message: `Use at least ${MIN_PASSWORD_LENGTH} characters.` },
              ]}
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>

            <Form.Item
              name="confirm"
              label="Confirm password"
              dependencies={["password"]}
              rules={[
                { required: true, message: "Type the password again." },
                ({ getFieldValue }) => ({
                  validator: (_, value: string) =>
                    !value || getFieldValue("password") === value
                      ? Promise.resolve()
                      : Promise.reject(new Error("The two passwords do not match.")),
                }),
              ]}
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>

            <Form.Item style={{ marginBottom: 0 }}>
              <Button type="primary" size="large" block htmlType="submit" loading={submitting}>
                Create administrator
              </Button>
            </Form.Item>
          </Form>
        </Space>
      </Card>
    </Flex>
  );
}
