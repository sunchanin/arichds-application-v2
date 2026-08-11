import { Flex, Result, Spin } from "antd";
import { useCallback, useEffect, useState } from "react";

import { api, type LicenseStatus } from "./api";
import { type Session, clearSession, getSession, onSessionChange, setSession } from "./auth";
import { AppShell } from "./components/AppShell";
import { Activation } from "./pages/Activation";
import { Battery } from "./pages/Battery";
import { Billing } from "./pages/Billing";
import { Devices } from "./pages/Devices";
import { EnergySummary } from "./pages/EnergySummary";
import { ExportFormat } from "./pages/ExportFormat";
import { Holidays } from "./pages/Holidays";
import { LoadProfile } from "./pages/LoadProfile";
import { Login } from "./pages/Login";
import { Records } from "./pages/Records";
import { Settings } from "./pages/Settings";
import { Setup } from "./pages/Setup";
import { SpecialDays } from "./pages/SpecialDays";
import { Users } from "./pages/Users";
import { LICENSE_POLL_MS } from "./theme";

/** The in-shell pages. Every other menu key belongs to a milestone that has not shipped. */
type Page =
  | "devices"
  | "load-profile"
  | "records"
  | "billing"
  | "energy-summary"
  | "holidays"
  | "special-days"
  | "battery"
  | "export-format"
  | "users"
  | "settings";

const PAGES: readonly Page[] = [
  "devices",
  "load-profile",
  "records",
  "billing",
  "energy-summary",
  "holidays",
  "special-days",
  "battery",
  "export-format",
  "users",
  "settings",
];

/** Read a menu key as a page, falling back to Devices for anything unrecognised. */
function toPage(key: string): Page {
  return PAGES.includes(key as Page) ? (key as Page) : "devices";
}

/**
 * Routes on state, not on a URL — and from M2-1 the first question is auth.
 *
 * The order is forced by what each answer costs. `check-setup` is the only
 * question a fresh machine can answer at all. Once an account exists, the
 * license status is no longer public (it carries the Machine ID), so the app
 * cannot even ask about Limited Mode until someone has signed in:
 *
 *   Setup → Login → Activation → Devices
 *
 * A stored token is *validated* with `GET /api/auth/me` rather than trusted:
 * an 8-hour token sitting in localStorage may well have expired or been revoked
 * since the tab was last open. That same answer also *refreshes* the stored
 * role and id, so an account another admin demoted loses the User Management
 * menu entry on the next reload rather than keeping a stale one.
 *
 * In-shell navigation is state, not a URL — `react-router` is not a dependency
 * and the top-level gate above stays state-driven either way.
 */
export default function App() {
  const [session, setSessionState] = useState<Session | null>(() => getSession());
  const [setupRequired, setSetupRequired] = useState<boolean | null>(null);
  const [tokenChecked, setTokenChecked] = useState(false);
  const [status, setStatus] = useState<LicenseStatus | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [page, setPage] = useState<Page>("devices");

  // A 401 anywhere in the app clears the session; this is what turns that into
  // a re-render back to Login, without any page knowing about any other page.
  useEffect(() => onSessionChange(setSessionState), []);

  const refreshSetup = useCallback(async () => {
    try {
      const result = await api.checkSetup();
      setSetupRequired(result.setup_required);
      setUnreachable(false);
    } catch {
      setUnreachable(true);
    }
  }, []);

  useEffect(() => {
    // The setState lands in a promise callback once the API answers, never
    // synchronously in the effect body, so it cannot cascade renders. This is
    // the "subscribe to an external system" case the rule's own documentation
    // permits.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshSetup();
  }, [refreshSetup]);

  // Keep asking until the service answers. This runs *before* anyone has signed
  // in, which is exactly when it is needed: the installer opens the browser the
  // moment the service starts, so the very first `check-setup` often loses that
  // race — and the "Cannot reach the ARICHDS service" screen promises the page
  // will keep trying. Without this timer that promise is a lie on the whole
  // pre-auth half of the app (Setup and Login), and the user is parked forever.
  useEffect(() => {
    if (setupRequired !== null && !unreachable) return;
    const timer = window.setInterval(() => void refreshSetup(), LICENSE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [setupRequired, unreachable, refreshSetup]);

  // Validate a token restored from storage before acting on it. `me()` returning
  // 401 clears the session through the api layer, which re-renders us at Login.
  useEffect(() => {
    if (!session || tokenChecked) return;
    void api
      .me()
      .then((user) => {
        // The server is the authority on both. Guarded by the inequality so
        // setSession cannot notify its way into a render loop.
        if (user.role !== session.role || user.id !== session.id) {
          setSession({ ...session, id: user.id, role: user.role });
        }
        setTokenChecked(true);
      })
      .catch(() => setTokenChecked(true));
  }, [session, tokenChecked]);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await api.licenseStatus());
      setUnreachable(false);
    } catch {
      // A 401 here has already cleared the session; anything else means the
      // service is not answering.
      if (getSession()) setUnreachable(true);
    }
  }, []);

  useEffect(() => {
    if (!session || !tokenChecked) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshStatus();
  }, [session, tokenChecked, refreshStatus]);

  // While the machine is limited, keep checking: a license can also arrive by
  // being dropped into the data directory, not only through the page.
  useEffect(() => {
    if (!session || status?.state === "active") return;
    const timer = window.setInterval(() => void refreshStatus(), LICENSE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [session, status?.state, refreshStatus]);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // The token may already be expired or revoked server-side. Either way the
      // local session goes — a logout button that can fail to log you out would
      // be worse than one that always does.
    }
    clearSession();
    setStatus(null);
    setTokenChecked(false);
    setNotice(null);
    setPage("devices");
  }, []);

  if (unreachable) {
    return (
      <Result
        status="warning"
        title="Cannot reach the ARICHDS service"
        subTitle="The service may still be starting. This page will keep trying."
      />
    );
  }

  if (setupRequired === null) return <Loading />;

  if (setupRequired) {
    return (
      <Setup
        onComplete={(username) => {
          setNotice(`Account "${username}" created. Sign in to continue.`);
          void refreshSetup();
        }}
      />
    );
  }

  if (!session) return <Login notice={notice} />;

  if (!tokenChecked || !status) return <Loading />;

  if (status.state !== "active") {
    return <Activation status={status} role={session.role} onActivated={() => void refreshStatus()} />;
  }

  // A `user` never reaches the Users page: the menu entry is absent for them,
  // and this second check is what keeps a stale `page` from surviving a
  // demotion that landed while the page was open. Load Profile and Records need
  // no such gate — reading stored readings is open to both roles.
  const active: Page = page === "users" && session.role !== "admin" ? "devices" : page;

  return (
    <AppShell
      licensedTo={status.customer}
      username={session.username}
      role={session.role}
      activeKey={active}
      onNavigate={(key) => setPage(toPage(key))}
      onSignOut={() => void signOut()}
    >
      {active === "users" ? (
        <Users currentUserId={session.id} />
      ) : active === "load-profile" ? (
        <LoadProfile role={session.role} />
      ) : active === "records" ? (
        <Records />
      ) : active === "billing" ? (
        <Billing role={session.role} />
      ) : active === "energy-summary" ? (
        <EnergySummary />
      ) : active === "holidays" ? (
        <Holidays role={session.role} />
      ) : active === "special-days" ? (
        <SpecialDays />
      ) : active === "battery" ? (
        <Battery />
      ) : active === "export-format" ? (
        <ExportFormat role={session.role} />
      ) : active === "settings" ? (
        <Settings role={session.role} />
      ) : (
        <Devices role={session.role} />
      )}
    </AppShell>
  );
}

function Loading() {
  return (
    <Flex justify="center" align="center" style={{ minHeight: "100vh" }}>
      <Spin size="large" />
    </Flex>
  );
}
