import {
  AreaChartOutlined,
  CalendarOutlined,
  CloudServerOutlined,
  CloudUploadOutlined,
  DatabaseOutlined,
  ExportOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  KeyOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PoweroffOutlined,
  SettingOutlined,
  TableOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Button, Layout, Menu, Space, Tag, theme, Typography } from "antd";
import type { ItemType, MenuItemType } from "antd/es/menu/interface";
import { type ReactNode, useState } from "react";

import { type Page, isPageAdvertised } from "../features";
import { HEADER_HEIGHT } from "../theme";
import { ChangePasswordModal } from "./ChangePasswordModal";

const { Header, Sider, Content } = Layout;

/** One menu entry, keyed by the page it opens so the mapping can be applied to it. */
type NavEntry = { key: Page; icon: ReactNode; label: string };

/** A labelled group of entries — the only nesting this menu has. */
type NavGroup = { type: "group"; label: string; children: NavEntry[] };

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
 * way User Management does. Energy stays disabled until M7 owns it.
 *
 * M5b-2 lights up **Records** — whether those stored Readings are *complete*,
 * counted per meter and logger against the meter's own capture period — for
 * every role too, and for the same reason: it only reads rows that are already
 * on disk.
 *
 * M6a lights up **Billing** — the read-only view of the Billing Readings the
 * meter itself froze when it closed a period, for every role, same reason as
 * Load Profile and Records.
 *
 * M7-1 lights up **Energy Summary**, **Holidays** and **Special Days** — the
 * TOU report + Energy Registers page, the calendar that feeds its Holiday
 * bucket, and the read-through view of a meter's own Special Days Table —
 * for every role, same reason as the rest of this group: every one of them
 * reads what is already on disk or reads a meter through the same Manual
 * Read path Devices already uses; none is admin-only to *view* (only
 * Holiday mutations and both imports are, decision 19).
 *
 * M7-2 lights up **Battery** — the read-only view of the stored Battery
 * Readings an hourly background job writes, for every role, same reason as
 * the rest of this group (SPEC §3.7). It carries no Read-now control: the
 * job is background-only (D5).
 *
 * M7 slice 3 (issue #30) lights up **Export Format** — the page that owns
 * the Load Profile CSV's date/time and filename settings, for every role
 * too: reading the current format is not admin-only, only saving it is
 * (the same split Settings.tsx's display-unit control already uses). The
 * auto-save switch and output folder live on the Load Profile page itself,
 * not here (D-16).
 *
 * M7 slice 4 (issue #31) lights up **App Log**, the last slice of M7 — a
 * read-only tail viewer for the rotating application log. **Admin-only**,
 * like User Management: the log's content is machine-internal (usernames,
 * Transport Endpoints, file paths, tracebacks), unlike the meter data every
 * other page in this group shows.
 *
 * **Issue 012 reverses this shell's own rule about what it may know.** It used
 * to say: the API answers `FEATURE_DISABLED` and the page shows that inline
 * rather than hiding the menu entry, since whether a feature is on is not this
 * shell's business to know in advance. It now is — `GET /api/license/status`
 * carries `enabled_features`, the resolved `.env FEATURES ∩ licence` set, and
 * this shell advertises only what that set allows. The owner's reason: a
 * customer who sees six pages that refuse them reads the product as broken or
 * as nagging them to buy; a customer who sees only what they bought reads it
 * as theirs. The mapping is `features.ts`'s `PAGE_ENTITLEMENT`, exhaustive
 * over `Page` so a new page with no entry fails the build. Three consequences
 * worth stating, because each was decided rather than fallen into:
 *
 * - **App Log takes the same rule as everything else** (D6) — no ops-only
 *   exception to remember. An empty/unset `.env FEATURES` expands to every
 *   key, so its entry is present on every default install and disappears only
 *   where an operator deliberately excluded it, on a machine where the page
 *   403s anyway. `AppLog.tsx`'s inline `Result` stays as the backstop.
 * - **File Upload is never advertised** (D7) until M8 gives it a transport
 *   (SPEC §3.8): it is a presentation-only shell with no transport and no
 *   feature key, so there is nothing a customer can do with it. The page
 *   component is untouched and still renders normally if reached.
 * - **Hiding is total** (D9): no "show what else ARICHDS can do" affordance,
 *   which would re-introduce exactly the nagging this removes. Settings is
 *   never hidden, so support can always say "open Settings → License" — the
 *   card there lists what this machine has.
 *
 * Enforcement did **not** move. `require_feature` on the server is unchanged
 * and is still what refuses an unlicensed page; this filter is cosmetic.
 *
 * A later CR (display-unit setting, kW/kWh vs W/Wh) lights up **Settings**
 * for every role too — its controls are disabled for a `user` rather than
 * the entry being absent, because reading the current settings is not
 * admin-only, only changing them is (mirrors the Billing page's own
 * `capture_dir` form). Issue 011 adds a second card there, **License**,
 * under the same split: every role reads what the machine is licensed to,
 * only an admin can paste a replacement Activation Code.
 *
 * Issue #37 adds the **Data-out Destination** group — Database and File
 * Upload — after Settings. **Admin-only, for the same reason App Log is**:
 * the fields are machine-internal credentials, not meter data, so the group
 * and both entries are *absent* for a `user`, not disabled. **The two now
 * differ**: Database carries a real transport since issue #46 (SPEC §3.10 —
 * the `dbdest_sync` job writes into the customer's own MariaDB every fifteen
 * minutes), while File Upload is still presentation-only, waiting on the
 * Data-out module (SPEC §3.8) that is a later milestone — and since issue 012
 * that is why File Upload is not advertised to anyone, admin included, which
 * in turn is what lets the group header disappear entirely when the licence
 * omits `database_destination`.
 *
 * The header carries who is signed in, the way to change your own password
 * (every role — the modal is owned here, so no page has to pass a prop for it),
 * and the way out.
 */
export function AppShell({
  children,
  licensedTo,
  enabledFeatures,
  username,
  role,
  activeKey,
  onNavigate,
  onSignOut,
}: {
  children: ReactNode;
  licensedTo?: string | null;
  /**
   * `LicenseStatus.enabled_features` — a prop, never state, so replacing the
   * licence re-renders the menu with no reload (ADR 0001: never cache
   * licence-derived state). Nothing here may snapshot it.
   */
  enabledFeatures: readonly string[];
  username: string;
  role: "admin" | "user";
  activeKey: string;
  onNavigate: (key: string) => void;
  onSignOut: () => void;
}) {
  const [changingPassword, setChangingPassword] = useState(false);
  // Shared by the responsive `lg` breakpoint and the manual header toggle
  // below, so they act on one state instead of fighting each other — the
  // `Sider`'s own `onCollapse` fires for both, and the button just flips it.
  const [collapsed, setCollapsed] = useState(false);
  // The shell wraps every page M2–M7 will add, so its colours must come from
  // the theme rather than literals — otherwise a later re-theme silently
  // strands the header text at whatever white looked right in M1.
  const { token } = theme.useToken();

  // Role first, licence second — two independent questions, kept apart. The
  // role conditionals below decide what this *account* may see; the filter
  // underneath decides what this *machine* is licensed to (issue 012).
  const entries: (NavEntry | NavGroup)[] = [
    { key: "devices", icon: <DatabaseOutlined />, label: "Devices" },
    { key: "load-profile", icon: <AreaChartOutlined />, label: "Load Profile" },
    { key: "records", icon: <TableOutlined />, label: "Records" },
    { key: "billing", icon: <FileTextOutlined />, label: "Billing" },
    // M7-1 (issue #28) — the calendar sits beside the thing it feeds.
    { key: "energy-summary", icon: <ThunderboltOutlined />, label: "Energy Summary" },
    { key: "holidays", icon: <CalendarOutlined />, label: "Holidays" },
    { key: "special-days", icon: <CalendarOutlined />, label: "Special Days" },
    // M7-2 (issue #29) — after Special Days, SPEC §3.7's page order.
    { key: "battery", icon: <PoweroffOutlined />, label: "Battery" },
    // M7 slice 3 (issue #30) — after Battery, SPEC §3.7's page order.
    { key: "export-format", icon: <ExportOutlined />, label: "Export Format" },
    // M7 slice 4 (issue #31) — after Export Format, SPEC §3.7's page order.
    // Admin-only, like User Management: the log's content is machine-internal
    // (usernames, Transport Endpoints, file paths, tracebacks), unlike the
    // meter data every other page in this group shows.
    ...(role === "admin"
      ? ([{ key: "app-log", icon: <FileSearchOutlined />, label: "App Log" }] satisfies NavEntry[])
      : []),
    ...(role === "admin"
      ? ([{ key: "users", icon: <TeamOutlined />, label: "User Management" }] satisfies NavEntry[])
      : []),
    { key: "settings", icon: <SettingOutlined />, label: "Settings" },
    // Issue #37 — admin-only, like App Log/User Management above: these two
    // pages carry no transport yet (SPEC §3.8 is a later milestone), and
    // their fields are machine-internal credentials, not meter data.
    ...(role === "admin"
      ? ([
          {
            type: "group",
            label: "Data-out Destination",
            children: [
              { key: "database-destination", icon: <CloudServerOutlined />, label: "Database" },
              { key: "file-upload-destination", icon: <CloudUploadOutlined />, label: "File Upload" },
            ],
          },
        ] satisfies NavGroup[])
      : []),
  ];

  // One pass over the whole tree rather than a special case for the Data-out
  // group: a group is kept only when something is left under it, so any future
  // group inherits the rule instead of re-deciding it. A label with nothing
  // beneath it is worse than either showing or hiding the pages (issue 012).
  const items: ItemType<MenuItemType>[] = entries
    .map((entry) =>
      "children" in entry
        ? {
            ...entry,
            children: entry.children.filter((child) => isPageAdvertised(child.key, enabledFeatures)),
          }
        : entry,
    )
    .filter((entry) =>
      "children" in entry ? entry.children.length > 0 : isPageAdvertised(entry.key, enabledFeatures),
    );

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
        <Space size="small" align="center">
          <Button
            type="text"
            size="small"
            // Stays visible while collapsed — otherwise the sidebar, once
            // hidden, would have no way back (collapsedWidth={0} hides it
            // completely, so there is no icon rail to click through).
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed((current) => !current)}
            style={{ color: token.colorTextLightSolid }}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          />
          <Typography.Text
            strong
            style={{ color: token.colorTextLightSolid, fontSize: 16, letterSpacing: 0.5 }}
          >
            ARICHDS
          </Typography.Text>
        </Space>
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
        <Sider
          width={200}
          theme="light"
          breakpoint="xl"
          collapsedWidth={0}
          collapsible
          collapsed={collapsed}
          // AntD shows its own floating trigger once `collapsedWidth` is 0;
          // suppressed because the header button above is the one control
          // (it must stay visible collapsed, which the header button does).
          trigger={null}
          onCollapse={setCollapsed}
        >
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
