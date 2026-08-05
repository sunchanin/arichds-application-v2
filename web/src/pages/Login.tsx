import { LoginOutlined } from "@ant-design/icons";
import { Alert, App, Button, Card, Flex, Form, Input, Space, theme, Typography } from "antd";
import { useState } from "react";

import { ApiRequestError, api, type Credentials } from "../api";
import { setSession } from "../auth";

const { Text, Title } = Typography;

/**
 * The Login page.
 *
 * Reachable even while the machine is in Limited Mode — the auth endpoints sit
 * outside the license gate on purpose, because activation needs an admin and a
 * machine whose lease lapsed would otherwise have no way back.
 *
 * Every credential failure comes back as the same message from the server; the
 * page does not try to guess whether it was the username or the password.
 */
export function Login({ notice }: { notice?: string | null }) {
  const { message } = App.useApp();
  const { token } = theme.useToken();
  const [form] = Form.useForm<Credentials>();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (values: Credentials) => {
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.login(values);
      // Setting the session is what re-routes the app: App subscribes to it.
      setSession({
        id: result.user.id,
        token: result.access_token,
        username: result.user.username,
        role: result.user.role,
      });
      message.success(`Signed in as ${result.user.username}`);
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
      <Card style={{ width: "100%", maxWidth: 420 }}>
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <div>
            <Title level={3} style={{ marginBottom: 4 }}>
              <LoginOutlined /> Sign in to ARICHDS
            </Title>
            <Text type="secondary">Use the account created when this machine was set up.</Text>
          </div>

          {notice ? <Alert type="success" showIcon message={notice} /> : null}
          {error ? <Alert type="error" showIcon message={error} /> : null}

          <Form form={form} layout="vertical" onFinish={(values) => void submit(values)} disabled={submitting}>
            <Form.Item
              name="username"
              label="Username"
              rules={[{ required: true, message: "Enter your username." }]}
            >
              <Input autoFocus autoComplete="username" />
            </Form.Item>

            <Form.Item
              name="password"
              label="Password"
              rules={[{ required: true, message: "Enter your password." }]}
            >
              <Input.Password autoComplete="current-password" />
            </Form.Item>

            <Form.Item style={{ marginBottom: 0 }}>
              <Button type="primary" size="large" block htmlType="submit" loading={submitting}>
                Sign in
              </Button>
            </Form.Item>
          </Form>
        </Space>
      </Card>
    </Flex>
  );
}
