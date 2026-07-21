"use strict";

function createBackendPortController({
  backendBundleMatches,
  backendCanServeApp,
  dashboardChatEnabled,
  embeddedChat,
  execFileSync,
  getBackendPort,
  log,
  preferredPort,
  setBackendPort,
  setTimeout,
}) {
  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function killProcessOnPort(port) {
    try {
      const out = execFileSync(
        "/usr/sbin/lsof",
        ["-ti", `tcp:${port}`, "-sTCP:LISTEN"],
        { encoding: "utf8", timeout: 4000 },
      );
      const pids = out.split(/\s+/).map((s) => s.trim()).filter(Boolean);
      for (const pid of pids) {
        try {
          execFileSync("/bin/kill", ["-TERM", pid], { timeout: 2000 });
          log.info(`[elevate-backend] killed stale dashboard pid ${pid} on port ${port}`);
        } catch (e) {
          log.warn(`[elevate-backend] failed to kill pid ${pid}: ${e}`);
        }
      }
      return pids.length > 0;
    } catch {
      return false;
    }
  }

  async function backendMatchesDesktopMode(port = getBackendPort()) {
    if (!(await backendCanServeApp(port))) return false;
    if (!(await backendBundleMatches(port))) return false;
    if (!embeddedChat) return true;
    return dashboardChatEnabled(port);
  }

  async function waitForBackend(timeoutMs = 180000) {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      if (await backendMatchesDesktopMode()) return true;
      await sleep(500);
    }
    return false;
  }

  async function backendProbeSummary(port = getBackendPort()) {
    const [statusReady, bundleMatch, chatEnabled] = await Promise.allSettled([
      backendCanServeApp(port),
      backendBundleMatches(port),
      dashboardChatEnabled(port),
    ]);
    const value = (result) => result.status === "fulfilled" ? String(result.value) : `error:${result.reason}`;
    return `port=${port} status=${value(statusReady)} bundle=${value(bundleMatch)} chat=${value(chatEnabled)}`;
  }

  async function chooseBackendPort() {
    if (await backendMatchesDesktopMode(preferredPort)) {
      setBackendPort(preferredPort);
      return;
    }

    if (
      (await backendCanServeApp(preferredPort)) &&
      !(await backendBundleMatches(preferredPort))
    ) {
      log.info("[elevate-backend] stale-bundle dashboard on preferred port — evicting");
      killProcessOnPort(preferredPort);
      for (let i = 0; i < 20; i += 1) {
        if (!(await backendCanServeApp(preferredPort))) break;
        await sleep(250);
      }
      setBackendPort(preferredPort);
      return;
    }

    // A free preferred port must be claimed here. Both checks above require an
    // *existing* backend to answer, so an idle preferred port failed both and
    // fell through to the scan below, which starts at preferredPort + 1. The
    // desktop then waited on a port nothing would ever bind while the spawned
    // backend took the preferred one, burning the full 180s waitForBackend
    // timeout and showing "backend unavailable" on every clean launch.
    if (!(await backendCanServeApp(preferredPort))) {
      setBackendPort(preferredPort);
      return;
    }

    for (let port = preferredPort + 1; port <= preferredPort + 10; port += 1) {
      if (await backendMatchesDesktopMode(port)) {
        setBackendPort(port);
        return;
      }
      if (!(await backendCanServeApp(port))) {
        setBackendPort(port);
        return;
      }
    }

    setBackendPort(preferredPort);
  }

  return {
    backendMatchesDesktopMode,
    backendProbeSummary,
    chooseBackendPort,
    killProcessOnPort,
    waitForBackend,
  };
}

module.exports = { createBackendPortController };
