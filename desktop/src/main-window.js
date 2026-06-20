"use strict";

function createMainWindowController({
  BrowserWindow,
  Menu,
  appRoot,
  backendUrl,
  currentMainWindowUrl,
  finishStartup,
  isTrustedNavigationUrl,
  log,
  markStartup,
  path,
  process,
  resetDashboardLoadRetry,
  scheduleDashboardLoadRetry,
  setMainWindow,
  shell,
  trimLogMessage,
}) {
  function createWindow() {
    markStartup("window:create");
    const mainWindow = new BrowserWindow({
      width: 1360,
      height: 900,
      minWidth: 380,
      minHeight: 480,
      title: "Elevate",
      backgroundColor: "#0F0F0F",
      show: false,
      titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
      trafficLightPosition:
        process.platform === "darwin" ? { x: 14, y: 18 } : undefined,
      webPreferences: {
        preload: path.join(appRoot, "preload.js"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    });
    setMainWindow(mainWindow);

    mainWindow.once("ready-to-show", () => {
      markStartup("window:ready-to-show");
      mainWindow.show();
    });

    mainWindow.webContents.on("dom-ready", () => {
      const url = mainWindow && !mainWindow.isDestroyed() ? mainWindow.webContents.getURL() : "";
      const origin = backendUrl();
      markStartup("renderer:dom-ready", url.startsWith(origin) ? "dashboard" : path.basename(url));
    });

    mainWindow.webContents.on("did-finish-load", () => {
      const url = mainWindow && !mainWindow.isDestroyed() ? mainWindow.webContents.getURL() : "";
      const origin = backendUrl();
      const isDashboard = url.startsWith(origin);
      markStartup("renderer:did-finish-load", isDashboard ? "dashboard" : path.basename(url));
      if (isDashboard) {
        resetDashboardLoadRetry();
        finishStartup("dashboard-loaded");
      }
    });

    mainWindow.webContents.on("did-fail-load", (_event, code, description, validatedUrl) => {
      const failedUrl = validatedUrl || currentMainWindowUrl();
      log.warn(
        `[renderer:did-fail-load] code=${code} desc=${trimLogMessage(description, 300)} url=${trimLogMessage(failedUrl, 500)}`,
      );
      if (code !== -3 && failedUrl.startsWith(backendUrl())) {
        scheduleDashboardLoadRetry(`did-fail-load:${code}`);
      }
    });

    mainWindow.webContents.on("console-message", (_event, ...args) => {
      const details =
        args.length === 1 && args[0] && typeof args[0] === "object"
          ? args[0]
          : {
              level: args[0],
              message: args[1],
              line: args[2],
              sourceId: args[3],
            };
      const level = Number(details.level ?? 0);
      if (level < 2) return;
      const label = level >= 3 ? "error" : "warn";
      log[label](
        `[renderer:console:${level}] ${trimLogMessage(details.message)} (${trimLogMessage(details.sourceId || currentMainWindowUrl(), 500)}:${details.line ?? 0})`,
      );
    });

    mainWindow.webContents.on("render-process-gone", (_event, details) => {
      log.error(
        `[renderer:gone] reason=${details.reason} exitCode=${details.exitCode} url=${trimLogMessage(currentMainWindowUrl(), 500)}`,
      );
    });

    mainWindow.on("unresponsive", () => {
      log.error(`[renderer:unresponsive] url=${trimLogMessage(currentMainWindowUrl(), 500)}`);
    });

    mainWindow.on("responsive", () => {
      log.info(`[renderer:responsive] url=${trimLogMessage(currentMainWindowUrl(), 500)}`);
    });

    mainWindow.on("closed", () => {
      setMainWindow(null);
    });

    mainWindow.on("page-title-updated", (event) => {
      event.preventDefault();
    });

    mainWindow.webContents.on("before-input-event", (event, input) => {
      if (input.type !== "keyDown") return;
      const key = (input.key || "").toLowerCase();
      const isReloadCombo =
        (key === "r" && (input.meta || input.control)) || key === "f5";
      if (isReloadCombo) event.preventDefault();
    });

    mainWindow.webContents.on("context-menu", (_event, params) => {
      const editFlags = params.editFlags || {};
      const hasSelection = (params.selectionText || "").trim().length > 0;
      const items = [];
      if (params.isEditable) {
        items.push(
          { role: "cut", enabled: !!editFlags.canCut },
          { role: "copy", enabled: !!editFlags.canCopy },
          { role: "paste", enabled: !!editFlags.canPaste },
          { type: "separator" },
          { role: "selectAll" },
        );
      } else {
        if (hasSelection) items.push({ role: "copy" }, { type: "separator" });
        items.push({ role: "selectAll" });
      }
      if (items.length) {
        Menu.buildFromTemplate(items).popup({ window: mainWindow });
      }
    });

    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
      if (url.startsWith(backendUrl())) return { action: "allow" };
      try {
        const scheme = new URL(url).protocol;
        if (scheme === "https:" || scheme === "http:" || scheme === "mailto:") {
          shell.openExternal(url);
        }
      } catch {
        /* malformed URL: ignore */
      }
      return { action: "deny" };
    });

    mainWindow.webContents.on("will-navigate", (event, url) => {
      if (!isTrustedNavigationUrl(url, { backendUrl: backendUrl(), appRoot })) {
        event.preventDefault();
      }
    });
  }

  return { createWindow };
}

module.exports = { createMainWindowController };
