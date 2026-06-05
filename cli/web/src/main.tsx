import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { markStartup } from "./lib/startup-performance";
import "./index.css";
import App from "./App";
import { SystemActionsProvider } from "./contexts/SystemActions";
import { I18nProvider } from "./i18n";
import { exposePluginSDK } from "./plugins";
import { ThemeProvider } from "./themes";

// Expose the plugin SDK before rendering so plugins loaded via <script>
// can access React, components, etc. immediately.
markStartup("web:main-module-loaded");
// Flag the desktop (Electron) build so CSS can inset the chat header away from
// the macOS traffic lights only where they actually exist.
if (typeof window !== "undefined" && (window as { elevateDesktop?: unknown }).elevateDesktop) {
  document.documentElement.classList.add("is-desktop");
}
exposePluginSDK();
markStartup("web:plugin-sdk-exposed");

markStartup("web:react-render-start");
createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <I18nProvider>
      <ThemeProvider>
        <SystemActionsProvider>
          <App />
        </SystemActionsProvider>
      </ThemeProvider>
    </I18nProvider>
  </BrowserRouter>,
);
