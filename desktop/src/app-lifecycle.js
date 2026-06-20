"use strict";

function createAppLifecycle({
  app,
  backendProcess,
  backendReady,
  computerUseOverlay,
  createMenu,
  createWindow,
  deepLinks,
  kickoffUpdates,
  loadAppPath,
  log,
  mainWindow,
  markStartup,
  ownsBackend,
  process,
  startDesktop,
  startPath,
  startSmsOutboxWatcher,
}) {
  function registerSingleInstance() {
    const isPrimaryInstance = app.requestSingleInstanceLock();
    if (!isPrimaryInstance) {
      app.quit();
      return false;
    }

    // Hand off duplicate launches and elevate:// argv links to the primary app.
    app.on("second-instance", (_event, argv) => {
      const win = mainWindow();
      if (win && !win.isDestroyed()) {
        if (win.isMinimized()) win.restore();
        win.show();
        win.focus();
      }
      app.focus({ steal: true });
      const deepLink = argv.find(
        (arg) => typeof arg === "string" && arg.startsWith("elevate://"),
      );
      if (deepLink) deepLinks.handleDeepLink(deepLink);
    });
    return true;
  }

  function registerAppEvents(isPrimaryInstance) {
    app.whenReady().then(async () => {
      if (!isPrimaryInstance) return;
      markStartup("electron:ready");
      if (process.platform === "darwin" && app.dock) {
        // Fire-and-forget: awaiting dock.show() can hold window creation for seconds.
        Promise.resolve(app.dock.show())
          .then(() => app.focus({ steal: false }))
          .catch((err) =>
            log.warn(`[startup] dock registration failed: ${err && err.message ? err.message : err}`),
          );
      }
      await startDesktop();
      startSmsOutboxWatcher();
      kickoffUpdates();
      deepLinks.replayPending();
    });

    app.on("activate", () => {
      const win = mainWindow();
      if (win && !win.isDestroyed()) {
        if (win.isMinimized()) win.restore();
        win.show();
        win.focus();
        return;
      }
      if (backendReady()) {
        createWindow();
        createMenu();
        loadAppPath(startPath);
        return;
      }
      startDesktop();
    });

    app.on("before-quit", () => {
      computerUseOverlay.dispose();
      const proc = backendProcess();
      if (ownsBackend() && proc) proc.kill();
    });

    app.on("window-all-closed", () => {
      if (process.platform !== "darwin") app.quit();
    });
  }

  return {
    registerAppEvents,
    registerSingleInstance,
  };
}

module.exports = { createAppLifecycle };
