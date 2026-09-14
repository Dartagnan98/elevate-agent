const path = require("path");

function createUpdaterController({
  app,
  autoUpdater,
  fs,
  ipcMain,
  log,
  mainWindow,
  resourcesPath = () => process.resourcesPath,
  setImmediateImpl = setImmediate,
  setIntervalImpl = setInterval,
  DateImpl = Date,
}) {
  let updateState = { status: "idle", info: null, progress: null, error: null };
  let updateCheckInFlight = false;
  const updateBusyStatuses = new Set(["checking", "available", "downloading", "ready"]);

  function currentWindow() {
    return typeof mainWindow === "function" ? mainWindow() : mainWindow;
  }

  function updateConfigPath() {
    return path.join(resourcesPath(), "app-update.yml");
  }

  function broadcastUpdaterEvent(payload) {
    updateState = { ...updateState, ...payload };
    // The floating "update available" toast window was removed — the in-app
    // update card (App.tsx, fed by these same events) is the single update UI.
    const win = currentWindow();
    if (win && !win.isDestroyed()) {
      win.webContents.send("updater:event", updateState);
    }
  }

  async function runUpdaterCheck(reason) {
    if (app.isPackaged && !fs.existsSync(updateConfigPath())) {
      const message = "update metadata is not bundled";
      log.warn(`[updater] skip check (${reason}) — ${message}`);
      broadcastUpdaterEvent({ status: "error", info: null, progress: null, error: message });
      return { ok: false, message };
    }

    if (updateCheckInFlight || updateBusyStatuses.has(updateState.status)) {
      const message = updateCheckInFlight
        ? "a check is already in flight"
        : `update already ${updateState.status}`;
      log.info(`[updater] skip check (${reason}) — ${message}`);
      return { ok: true, skipped: true, message };
    }

    updateCheckInFlight = true;
    try {
      log.info(`[updater] checking for updates (${reason})`);
      const result = await autoUpdater.checkForUpdates();
      return {
        ok: true,
        version: result && result.updateInfo ? result.updateInfo.version : null,
      };
    } catch (err) {
      const message = err && err.message ? err.message : String(err);
      log.warn(`[updater] check failed (${reason}): ${message}`);
      broadcastUpdaterEvent({ status: "error", error: message });
      return { ok: false, message };
    } finally {
      updateCheckInFlight = false;
    }
  }

  function registerAutoUpdaterEvents() {
    autoUpdater.on("checking-for-update", () => {
      broadcastUpdaterEvent({ status: "checking", error: null });
    });
    autoUpdater.on("update-available", (info) => {
      broadcastUpdaterEvent({ status: "available", info, error: null });
    });
    autoUpdater.on("update-not-available", (info) => {
      broadcastUpdaterEvent({ status: "current", info, error: null });
    });
    autoUpdater.on("download-progress", (progress) => {
      broadcastUpdaterEvent({ status: "downloading", progress, error: null });
    });
    autoUpdater.on("update-downloaded", (info) => {
      broadcastUpdaterEvent({ status: "ready", info, progress: null, error: null });
    });
    autoUpdater.on("error", (err) => {
      broadcastUpdaterEvent({
        status: "error",
        error: err && err.message ? err.message : String(err),
      });
    });
  }

  function kickoffUpdates() {
    if (!app.isPackaged) {
      log.info("[updater] skipped in development build");
      return;
    }

    runUpdaterCheck("startup");
    // Poll frequently so a freshly-shipped build reaches the device within
    // minutes. autoDownload pulls it silently; the user still applies it via the
    // one-click "Restart to update" card — no auto-relaunch, no forced install.
    const timer = setIntervalImpl(() => runUpdaterCheck("poll"), 3 * 60 * 1000);
    if (typeof timer.unref === "function") timer.unref();
    // Also check the instant the app regains focus, so an update that shipped
    // while you were away shows up right when you come back. Debounced so rapid
    // focus changes don't hammer the feed.
    let lastFocusCheck = 0;
    app.on("browser-window-focus", () => {
      const now = DateImpl.now();
      if (now - lastFocusCheck < 60 * 1000) return;
      lastFocusCheck = now;
      runUpdaterCheck("focus");
    });
  }

  function registerIpcHandlers() {
    // Renderer can ask "what's the latest status?" on mount so it doesn't miss
    // events that fired before the listener was attached.
    ipcMain.handle("updater:status", () => updateState);

    // Renderer fires this when the user clicks "Restart to update".
    ipcMain.handle("updater:install", () => {
      if (updateState.status !== "ready") {
        return { ok: false, message: "Update is not ready yet." };
      }
      // setImmediate so the IPC reply is sent before quit kicks in.
      setImmediateImpl(() => {
        try {
          autoUpdater.quitAndInstall(false, true);
        } catch (err) {
          const message = err && err.message ? err.message : String(err);
          log.warn(`[updater] install failed: ${message}`);
          broadcastUpdaterEvent({ status: "error", error: message });
        }
      });
      return { ok: true };
    });

    // Manual "check now" button (useful from a Help menu).
    ipcMain.handle("updater:check", async () => {
      if (!app.isPackaged) {
        return { ok: false, message: "Updates only run in packaged builds." };
      }
      return runUpdaterCheck("manual");
    });
  }

  return {
    broadcastUpdaterEvent,
    kickoffUpdates,
    registerAutoUpdaterEvents,
    registerIpcHandlers,
    runUpdaterCheck,
  };
}

module.exports = { createUpdaterController };
