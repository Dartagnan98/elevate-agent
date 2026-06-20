"use strict";

function createBackendRunner({
  backendMatchesDesktopMode,
  backendProbeSummary,
  chooseBackendPort,
  embeddedChat,
  ensureGatewayInstalled,
  envWithPath,
  getBackendPort,
  markStartup,
  path,
  resolveElevateLauncher,
  setBackendProcess,
  setOwnsBackend,
  setTimeout,
  spawn,
  waitForBackend,
}) {
  function appendBackendLog(data) {
    const text = data.toString();
    if (text.trim()) {
      console.log(`[elevate-backend] ${text.trimEnd()}`);
    }
  }

  function scheduleGatewaySelfHeal(launcher, baseEnv) {
    if (!launcher) return;
    setTimeout(() => {
      try {
        ensureGatewayInstalled(launcher, baseEnv);
      } catch (e) {
        appendBackendLog(`[gateway] self-heal threw: ${e}\n`);
      }
    }, 8000);
  }

  async function ensureBackend() {
    markStartup("backend:ensure-start");
    await chooseBackendPort();
    markStartup("backend:port-selected", String(getBackendPort()));

    const launcher = resolveElevateLauncher();
    const baseEnv = {
      ELEVATE_DESKTOP_APP: "1",
      // Foreground desktop drains the SMS spool; headless backend cannot drive Messages.
      ELEVATE_SMS_VIA_APP: "1",
      ...(embeddedChat ? { ELEVATE_DASHBOARD_TUI: "1" } : {}),
    };

    if (await backendMatchesDesktopMode()) {
      markStartup("backend:already-ready");
      scheduleGatewaySelfHeal(launcher, baseEnv);
      return true;
    }

    if (!launcher) {
      markStartup("backend:launcher-missing");
      return false;
    }

    markStartup("backend:spawn", path.basename(launcher.command));
    const backendProcess = spawn(launcher.command, launcher.args, {
      cwd: launcher.cwd,
      env: envWithPath({ ...baseEnv, ...(launcher.extraEnv || {}) }),
      stdio: ["ignore", "pipe", "pipe"],
    });
    setBackendProcess(backendProcess);
    setOwnsBackend(true);

    backendProcess.stdout.on("data", appendBackendLog);
    backendProcess.stderr.on("data", appendBackendLog);
    backendProcess.on("exit", (code, signal) => {
      console.log(`[elevate-backend] exited code=${code} signal=${signal}`);
      setBackendProcess(null);
      setOwnsBackend(false);
    });

    const ready = await waitForBackend();
    if (!ready) {
      markStartup("backend:timeout-detail", await backendProbeSummary());
    }
    markStartup(ready ? "backend:ready" : "backend:timeout");

    scheduleGatewaySelfHeal(launcher, baseEnv);

    return ready;
  }

  return {
    appendBackendLog,
    ensureBackend,
    scheduleGatewaySelfHeal,
  };
}

module.exports = { createBackendRunner };
