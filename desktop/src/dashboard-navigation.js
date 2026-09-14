"use strict";

function createDashboardNavigation({
  appRoot,
  backendMatchesDesktopMode,
  backendUrl,
  delayMs,
  limit,
  log,
  mainWindow,
  markStartup,
  path,
  setTimeout,
  startPath,
  trimLogMessage,
}) {
  let dashboardLoadRetryCount = 0;
  let dashboardLoadRetryTimer = null;
  let lastDashboardPath = startPath;

  function currentWindow() {
    return mainWindow();
  }

  function loadLocalPage(fileName) {
    const win = currentWindow();
    if (!win) return;
    markStartup("window:load-local", fileName);
    win.loadFile(path.join(appRoot, fileName));
  }

  function clearDashboardLoadRetryTimer() {
    if (!dashboardLoadRetryTimer) return;
    clearTimeout(dashboardLoadRetryTimer);
    dashboardLoadRetryTimer = null;
  }

  function resetDashboardLoadRetry() {
    dashboardLoadRetryCount = 0;
    clearDashboardLoadRetryTimer();
  }

  function scheduleDashboardLoadRetry(reason) {
    const win = currentWindow();
    if (!win || win.isDestroyed() || dashboardLoadRetryTimer) return;
    if (dashboardLoadRetryCount >= limit) {
      markStartup("window:dashboard-retry-exhausted", reason);
      loadLocalPage("install.html");
      return;
    }

    dashboardLoadRetryCount += 1;
    const attempt = dashboardLoadRetryCount;
    const pathname = lastDashboardPath || startPath;
    markStartup("window:dashboard-retry", `${attempt}:${reason}`);
    loadLocalPage("loading.html");

    dashboardLoadRetryTimer = setTimeout(async () => {
      dashboardLoadRetryTimer = null;
      const current = currentWindow();
      if (!current || current.isDestroyed()) return;
      if (!(await backendMatchesDesktopMode())) {
        scheduleDashboardLoadRetry("backend-not-ready");
        return;
      }
      loadAppPath(pathname, { retry: true });
    }, delayMs);
    if (typeof dashboardLoadRetryTimer.unref === "function") {
      dashboardLoadRetryTimer.unref();
    }
  }

  function openLoginWindow() {
    const win = currentWindow();
    if (!win || win.isDestroyed()) return;
    win.focus();
    const currentUrl = win.webContents.getURL();
    if (!currentUrl.startsWith(backendUrl())) {
      loadAppPath(startPath);
      return;
    }
    win.webContents
      .executeJavaScript(
        "window.dispatchEvent(new Event('elevate:auth-changed'));",
        true,
      )
      .catch(() => {});
  }

  function loadAppPath(pathname = startPath, options = {}) {
    const win = currentWindow();
    if (!win) return;
    const targetPath = pathname || startPath;
    lastDashboardPath = targetPath;
    if (!options.retry) resetDashboardLoadRetry();
    markStartup("window:load-dashboard", targetPath);
    win.loadURL(`${backendUrl()}${targetPath}`).catch((err) => {
      if (String(err && err.message ? err.message : err).includes("ERR_ABORTED")) return;
      log.warn(`[renderer:loadURL] ${trimLogMessage(err && err.message ? err.message : err, 500)}`);
      scheduleDashboardLoadRetry("loadURL-rejected");
    });
  }

  return {
    clearDashboardLoadRetryTimer,
    loadAppPath,
    loadLocalPage,
    openLoginWindow,
    resetDashboardLoadRetry,
    scheduleDashboardLoadRetry,
  };
}

module.exports = { createDashboardNavigation };
