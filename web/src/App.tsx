import { Flex, Result, Spin } from "antd";
import { useCallback, useEffect, useState } from "react";

import { api, type LicenseStatus } from "./api";
import { AppShell } from "./components/AppShell";
import { Activation } from "./pages/Activation";
import { Monitor } from "./pages/Monitor";
import { LICENSE_POLL_MS } from "./theme";

/**
 * Routes on license state, not on a URL.
 *
 * There is exactly one decision to make at this level: is this machine in
 * Limited Mode (show Activation) or not (show the app)? Because activation
 * applies live (ADR 0001), moving between the two is just a refetch — no
 * reload, no restart, no "please wait".
 */
export default function App() {
  const [status, setStatus] = useState<LicenseStatus | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await api.licenseStatus());
      setUnreachable(false);
    } catch {
      setUnreachable(true);
    }
  }, []);

  useEffect(() => {
    // refreshStatus is async: the setState lands in a promise callback once the
    // API answers, never synchronously in the effect body, so it cannot cascade
    // renders. This is the "subscribe to an external system" case the rule's own
    // documentation permits.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshStatus();
  }, [refreshStatus]);

  // While the machine is limited, keep checking: a license can also arrive by
  // being dropped into the data directory, not only through this page.
  useEffect(() => {
    if (status?.state === "active") return;
    const timer = window.setInterval(() => void refreshStatus(), LICENSE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [status?.state, refreshStatus]);

  if (unreachable) {
    return (
      <Result
        status="warning"
        title="Cannot reach the ARICHDS service"
        subTitle="The service may still be starting. This page will keep trying."
      />
    );
  }

  if (!status) {
    return (
      <Flex justify="center" align="center" style={{ minHeight: "100vh" }}>
        <Spin size="large" />
      </Flex>
    );
  }

  if (status.state !== "active") {
    return <Activation status={status} onActivated={() => void refreshStatus()} />;
  }

  return (
    <AppShell licensedTo={status.customer}>
      <Monitor />
    </AppShell>
  );
}
