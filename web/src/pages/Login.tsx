import { LockOutlined, LoginOutlined, UserOutlined } from "@ant-design/icons";
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
 *
 * Layout (full-bleed background, centred card, gradient divider) is ported
 * from v1's Login page; the theme, feedback wiring and session handling stay
 * v2's own (no dark/gold ConfigProvider, no zod, no react-router-dom).
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
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundImage: "url(/images/arichds.jpg)",
        backgroundSize: "cover",
        backgroundPosition: "center",
      }}
    >
      {/* Veil so the card reads over the photo, from a theme token rather than a hardcoded color. */}
      <div style={{ position: "absolute", inset: 0, background: token.colorBgMask }} />

      <Flex
        justify="center"
        align="center"
        style={{ position: "relative", minHeight: "100vh", padding: 24 }}
      >
        <Card style={{ width: "100%", maxWidth: 400, boxShadow: token.boxShadowSecondary }}>
          <Space direction="vertical" size="large" style={{ width: "100%" }}>
            <div style={{ textAlign: "center" }}>
              <Title level={3} style={{ marginBottom: 4 }}>
                <LoginOutlined /> Sign in to ARICHDS
              </Title>
              <Text type="secondary">Use the account created when this machine was set up.</Text>
              {/* Thin gradient divider, ported from v1's layout. */}
              <div
                style={{
                  height: 1,
                  margin: "16px 0 0",
                  background: `linear-gradient(90deg, transparent, ${token.colorPrimary}, transparent)`,
                }}
              />
            </div>

            {notice ? <Alert type="success" showIcon message={notice} /> : null}
            {error ? <Alert type="error" showIcon message={error} /> : null}

            <Form form={form} layout="vertical" onFinish={(values) => void submit(values)} disabled={submitting}>
              <Form.Item
                name="username"
                label="Username"
                rules={[{ required: true, message: "Enter your username." }]}
              >
                <Input
                  prefix={<UserOutlined />}
                  placeholder="Enter your username"
                  size="large"
                  autoFocus
                  autoComplete="username"
                />
              </Form.Item>

              <Form.Item
                name="password"
                label="Password"
                rules={[{ required: true, message: "Enter your password." }]}
              >
                <Input.Password
                  prefix={<LockOutlined />}
                  placeholder="Enter your password"
                  size="large"
                  autoComplete="current-password"
                />
              </Form.Item>

              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  type="primary"
                  size="large"
                  block
                  htmlType="submit"
                  loading={submitting}
                  style={{ fontWeight: 600, letterSpacing: "0.05em" }}
                >
                  SIGN IN
                </Button>
              </Form.Item>
            </Form>
          </Space>
        </Card>
      </Flex>
    </div>
  );
}
