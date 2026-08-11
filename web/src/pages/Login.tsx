import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { Alert, App, Button, Card, Form, Input, Space, theme, Typography } from "antd";
import { useState } from "react";

import { ApiRequestError, api, type Credentials } from "../api";
import { setSession } from "../auth";

const { Text } = Typography;

/**
 * Entry animation for the login card, injected once as a <style> tag (there is
 * no CSS-in-JS setup in this project). Guarded for prefers-reduced-motion.
 * Ported from v1's Login page verbatim.
 */
const loginCardAnimCss = `
  @keyframes loginFadeUp {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .login-card-anim {
    animation: loginFadeUp 0.42s cubic-bezier(0.22, 1, 0.36, 1) both;
  }
  @media (prefers-reduced-motion: reduce) {
    .login-card-anim { animation: none; }
  }
`;

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
 * Layout (full-bleed background shifted down, card pinned bottom-right, glass
 * effect, entry animation, brand header) is ported from v1's Login page
 * verbatim (v1: cewe-fe/src/pages/Login/index.tsx lines 51-62, 106-190). The
 * one place v1 is NOT ported is theme: v1 wraps the page in a dark+gold
 * ConfigProvider, but v2 keeps its own deep-teal light identity — every color
 * below comes from v2's theme tokens, none from v1's hardcoded palette.
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
    <>
      <style>{loginCardAnimCss}</style>

      <div
        style={{
          position: "fixed",
          inset: 0,
          backgroundImage: "url(/images/arichds.jpg)",
          backgroundSize: "cover",
          // Shifts the photo down so the logo in it sits clear of the card, ported from v1.
          backgroundPosition: "center calc(50% + 120px)",
          // A viewport genuinely shorter than the card's content-box height
          // scrolls instead of silently clipping it.
          overflowY: "auto",
        }}
      >
        {/*
         * Veil so the card reads over the photo. v1 hardcodes a dark navy
         * (rgba(4, 10, 26, 0.40)) because its card is itself a dark glass
         * panel. v2's card is a LIGHT glass panel (see below), so it needs
         * the opposite: a dark veil behind it for contrast, same as v1's
         * effect but sourced from the theme (token.colorBgMask) rather than
         * a hardcoded value — it works whether the theme's mask token shifts
         * and never fights the locked light identity.
         */}
        <div style={{ position: "absolute", inset: 0, background: token.colorBgMask }} />

        {/* Login card pinned to the bottom-right corner. */}
        <div
          style={{
            position: "relative",
            zIndex: 1,
            display: "flex",
            alignItems: "flex-end",
            justifyContent: "flex-end",
            // Without this, `minHeight: 100vh` is the *content* height (the
            // browser default is content-box, and this project imports no
            // AntD reset), so the padding below adds on top of a full
            // viewport and the fixed, non-scrolling parent clips it. With
            // border-box, `minHeight: 100vh` already includes this padding.
            boxSizing: "border-box",
            minHeight: "100vh",
            padding: "2rem",
          }}
        >
          <Card
            className="login-card-anim"
            styles={{ body: { padding: "2rem 2rem 1.75rem" } }}
            style={{
              width: "100%",
              maxWidth: 360,
              // Semi-transparent surface derived from the theme's own container
              // token (not a new color) — required for backdropFilter below to
              // have any visible effect; an opaque card would hide the blur.
              background: `${token.colorBgContainer}f0`,
              backdropFilter: "blur(18px)",
              WebkitBackdropFilter: "blur(18px)",
              boxShadow: token.boxShadowSecondary,
            }}
          >
            {/* Brand header, ported from v1's layout with v2's own colors. */}
            <div style={{ textAlign: "center", marginBottom: "1.75rem" }}>
              <Text
                style={{
                  display: "block",
                  color: token.colorPrimary,
                  fontSize: 11,
                  letterSpacing: "0.22em",
                  fontWeight: 600,
                  textTransform: "uppercase",
                  marginBottom: 6,
                }}
              >
                ARICHEST CO., LTD.
              </Text>
              <div style={{ fontSize: 24, fontWeight: 700, letterSpacing: "0.06em", lineHeight: 1.2 }}>
                ARICHDS
              </div>
              {/* Gradient divider, ported from v1's layout. */}
              <div
                style={{
                  height: 1,
                  margin: "1.25rem 0 0",
                  background: `linear-gradient(90deg, transparent, ${token.colorPrimary}, transparent)`,
                }}
              />
            </div>

            <Space direction="vertical" size="large" style={{ width: "100%" }}>
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
        </div>
      </div>
    </>
  );
}
