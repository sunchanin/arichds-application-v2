import { App as AntdApp, ConfigProvider } from "antd";
import enUS from "antd/locale/en_US";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { arichdsTheme } from "./theme";
import "./index.css";

/**
 * The theme is applied once, here, and every module inherits it (SPEC §3.1).
 * `AntdApp` is what makes `App.useApp()` work for message/modal/notification —
 * the static `message.*` API does not pick up the ConfigProvider theme.
 *
 * Locale is English only, on purpose: SPEC §2 rules out i18n.
 */
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConfigProvider theme={arichdsTheme} locale={enUS}>
      <AntdApp>
        <App />
      </AntdApp>
    </ConfigProvider>
  </StrictMode>,
);
