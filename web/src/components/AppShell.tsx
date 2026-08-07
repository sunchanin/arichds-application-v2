import {
  AreaChartOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  KeyOutlined,
  LogoutOutlined,
  SettingOutlined,
  TableOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Button, Layout, Menu, Space, Tag, theme, Typography } from "antd";
import type { ItemType, MenuItemType } from "antd/es/menu/interface";
import { type ReactNode, useState } from "react";

import { HEADER_HEIGHT } from "../theme";
import { ChangePasswordModal } from "./ChangePasswordModal";

const { Header, Sider, Content } = Layout;

/**
 * The app shell: slim header plus the sidebar the finished product will have.
 *
 * The later modules' menu entries are present but disabled on purpose (SPEC
 * §3.1 — "so the skeleton looks like the product"). Seeing the real shape from
 * M1 is what makes this a walking skeleton rather than a demo page, and each
 * milestone lights up its own entry rather than redesigning navigation.
 *
 * M2-2 lights up **User Management**, and does so only for an `admin`: the
 * entry is *absent* for a `user`, not disabled. A disabled entry here means
 * "a later milestone owns this", which would be a lie — the page exists, that
 * account simply may not use it.
 *
 * M3-3 lights up **Devices** and removes **Monitor**, which was M1 scaffolding
 * rather than a product page (ADR 0007). Devices is where a meter is added,
 * edited, paused, read and deleted, and it is what the app opens on.
 *
 * M5b-1 lights up **Load Profile** — the read-only view of the Interval
 * Readings the meter recorded — for **every** role, so it carries no gate the
 * way User Management does. Billing, Energy and Settings stay disabled until
 * M6-M7 own them.
 *
 * M5b-2 lights up **Records** — whether those stored Readings are *complete*,
 * counted per meter and logger against the meter's own capture period — for
 * every role too, and for the same reason: it only reads rows that are already
 * on disk.
 *
 * The header carries who is signed in, the way to change your own password
 * (every role — the modal is owned here, so no page has to pass a prop for it),
 * and the way out.
 */
export function AppShell({
  children,
  licensedTo,
  username,
  role,
  activeKey,
  onNavigate,
  onSignOut,
}: {
  children: ReactNode;
  licensedTo?: string | null;
  username: string;
  role: "admin" | "user";
  activeKey: string;
  onNavigate: (key: string) => void;
  onSignOut: () => void;
}) {
  const [changingPassword, setChangingPassword] = useState(false);
  // The shell wraps every page M2–M7 will add, so its colours must come from
  // the theme rather than literals — otherwise a later re-theme silently
  // strands the header text at whatever white looked right in M1.
  const { token } = theme.useToken();

  const items: ItemType<MenuItemType>[] = [
    { key: "devices", icon: <DatabaseOutlined />, label: "Devices" },
    { key: "load-profile", icon: <AreaChartOutlined />, label: "Load Profile" },
    { key: "records", icon: <TableOutlined />, label: "Records" },
    // Owned by later milestones — visible so the shape is honest, disabled so
    // nothing pretends to work yet.
    { key: "billing", icon: <FileTextOutlined />, label: "Billing", disabled: true },
    { key: "energy", icon: <ThunderboltOutlined />, label: "Energy", disabled: true },
    ...(role === "admin"
      ? [{ key: "users", icon: <TeamOutlined />, label: "User Management" }]
      : []),
    { key: "settings", icon: <SettingOutlined />, label: "Settings", disabled: true },
  ];

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
        <Space size="middle" align="center">
          {licensedTo ? (
            <Tag color="green" style={{ marginInlineEnd: 0 }}>
              Licensed to {licensedTo}
            </Tag>
          ) : null}
          <Typography.Text style={{ color: token.colorTextLightSolid }}>
            <UserOutlined /> {username}
          </Typography.Text>
          <Button
            type="text"
            size="small"
            icon={<KeyOutlined />}
            onClick={() => setChangingPassword(true)}
            style={{ color: token.colorTextLightSolid }}
          >
            Change password
          </Button>
          <Button
            type="text"
            size="small"
            icon={<LogoutOutlined />}
            onClick={onSignOut}
            style={{ color: token.colorTextLightSolid }}
          >
            Sign out
          </Button>
        </Space>
      </Header>
      <ChangePasswordModal open={changingPassword} onClose={() => setChangingPassword(false)} />
      <Layout>
        <Sider width={200} theme="light" breakpoint="lg" collapsedWidth={0}>
          <Menu
            mode="inline"
            selectedKeys={[activeKey]}
            style={{ height: "100%", borderInlineEnd: 0 }}
            items={items}
            onClick={({ key }) => onNavigate(key)}
          />
        </Sider>
        <Content style={{ padding: 20, overflow: "auto" }}>{children}</Content>
      </Layout>
    </Layout>
  );
}
