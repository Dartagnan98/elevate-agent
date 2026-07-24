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
  protocolScheme = "elevate",
  setShuttingDown = () => {},
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

    // Hand off duplicate launches and protocol argv links to the primary app.
    app.on("second-instance", (_event, argv) => {
      const win = mainWindow();
      if (win && !win.isDestroyed()) {
        if (win.isMinimized()) win.restore();
        win.show();
        win.focus();
      }
      app.focus({ steal: true });
      const deepLink = argv.find(
        (arg) => typeof arg === "string" && arg.startsWith(`${protocolScheme}://`),
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
      // Start the update poll FIRST so an "alive but broken" build can still
      // pull its own fix. A startDesktop() throw or hang must never strand the
      // updater — a shipped build that crashes during backend/window init would
      // otherwise brick the whole fleet with no self-update path.
      kickoffUpdates();
      try {
        await startDesktop();
        startSmsOutboxWatcher();
        deepLinks.replayPending();
      } catch (err) {
        log.error(
          `[startup] startDesktop failed; updater already polling for a fix: ${
            err && err.message ? err.message : err
          }`,
        );
      }
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
      // Mark the shutdown BEFORE killing so the supervisor's exit handler sees
      // this as an intentional quit and does not respawn the backend.
      setShuttingDown();
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
