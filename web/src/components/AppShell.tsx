import {
  AreaChartOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Layout, Menu, Tag, theme, Typography } from "antd";
import type { ReactNode } from "react";

import { HEADER_HEIGHT } from "../theme";

const { Header, Sider, Content } = Layout;

/**
 * The app shell: slim header plus the sidebar the finished product will have.
 *
 * The later modules' menu entries are present but disabled on purpose (SPEC
 * §3.1 — "so the skeleton looks like the product"). Seeing the real shape from
 * M1 is what makes this a walking skeleton rather than a demo page, and each
 * milestone lights up its own entry rather than redesigning navigation.
 */
export function AppShell({ children, licensedTo }: { children: ReactNode; licensedTo?: string | null }) {
  // The shell wraps every page M2–M7 will add, so its colours must come from
  // the theme rather than literals — otherwise a later re-theme silently
  // strands the header text at whatever white looked right in M1.
  const { token } = theme.useToken();

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          height: HEADER_HEIGHT,
          lineHeight: `${HEADER_HEIGHT}px`,
          paddingInline: 16,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Typography.Text
          strong
          style={{ color: token.colorTextLightSolid, fontSize: 16, letterSpacing: 0.5 }}
        >
          ARICHDS
        </Typography.Text>
        {licensedTo ? (
          <Tag color="green" style={{ marginInlineEnd: 0 }}>
            Licensed to {licensedTo}
          </Tag>
        ) : null}
      </Header>
      <Layout>
        <Sider width={200} theme="light" breakpoint="lg" collapsedWidth={0}>
          <Menu
            mode="inline"
            selectedKeys={["monitor"]}
            style={{ height: "100%", borderInlineEnd: 0 }}
            items={[
              { key: "monitor", icon: <DashboardOutlined />, label: "Monitor" },
              // Owned by later milestones — visible so the shape is honest,
              // disabled so nothing pretends to work yet.
              { key: "devices", icon: <DatabaseOutlined />, label: "Devices", disabled: true },
              { key: "load-profile", icon: <AreaChartOutlined />, label: "Load Profile", disabled: true },
              { key: "billing", icon: <FileTextOutlined />, label: "Billing", disabled: true },
              { key: "energy", icon: <ThunderboltOutlined />, label: "Energy", disabled: true },
              { key: "settings", icon: <SettingOutlined />, label: "Settings", disabled: true },
            ]}
          />
        </Sider>
        <Content style={{ padding: 20, overflow: "auto" }}>{children}</Content>
      </Layout>
    </Layout>
  );
}
