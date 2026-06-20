"use strict";

function createBackendPortController({
  backendBundleMatches,
  backendIsReady,
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
    if (!(await backendIsReady(port))) return false;
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
      backendIsReady(port),
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
      (await backendIsReady(preferredPort)) &&
      !(await backendBundleMatches(preferredPort))
    ) {
      log.info("[elevate-backend] stale-bundle dashboard on preferred port — evicting");
      killProcessOnPort(preferredPort);
      for (let i = 0; i < 20; i += 1) {
        if (!(await backendIsReady(preferredPort))) break;
        await sleep(250);
      }
      setBackendPort(preferredPort);
      return;
    }

    for (let port = preferredPort + 1; port <= preferredPort + 10; port += 1) {
      if (await backendMatchesDesktopMode(port)) {
        setBackendPort(port);
        return;
      }
      if (!(await backendIsReady(port))) {
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
