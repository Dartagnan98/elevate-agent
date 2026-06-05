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
