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
  runtimeMetadata = {},
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
    // Exact Beta cleanup is an awaited startup precondition in ensureBackend.
    // Only Stable keeps the delayed install/repair self-heal path.
    if (runtimeMetadata.releaseChannel === "beta" || !launcher) return;
    setTimeout(async () => {
      try {
        await ensureGatewayInstalled(launcher, baseEnv);
      } catch (e) {
        appendBackendLog(`[gateway] self-heal threw: ${e}\n`);
      }
    }, 8000);
  }

  async function ensureBackend() {
    markStartup("backend:ensure-start");
    const launcher = resolveElevateLauncher();
    if (runtimeMetadata.releaseChannel === "beta") {
      markStartup("backend:beta-gateway-cleanup-start");
      await ensureGatewayInstalled(launcher, {
        ELEVATE_RELEASE_CHANNEL: "beta",
      });
      markStartup("backend:beta-gateway-cleanup-complete");
    }

    await chooseBackendPort();
    markStartup("backend:port-selected", String(getBackendPort()));

    const baseEnv = {
      ELEVATE_DESKTOP_APP: "1",
      // Foreground desktop drains the SMS spool; headless backend cannot drive Messages.
      ELEVATE_SMS_VIA_APP: "1",
      ELEVATE_DASHBOARD_PORT: String(getBackendPort()),
      ...(runtimeMetadata.appVersion ? { ELEVATE_APP_VERSION: String(runtimeMetadata.appVersion) } : {}),
      ...(runtimeMetadata.architecture ? { ELEVATE_APP_ARCHITECTURE: String(runtimeMetadata.architecture) } : {}),
      ...(runtimeMetadata.appBundleName ? { ELEVATE_APP_BUNDLE_NAME: String(runtimeMetadata.appBundleName) } : {}),
      ...(runtimeMetadata.releaseChannel ? { ELEVATE_RELEASE_CHANNEL: String(runtimeMetadata.releaseChannel) } : {}),
      ...(runtimeMetadata.sourceReceiptId ? { ELEVATE_SOURCE_RECEIPT_ID: String(runtimeMetadata.sourceReceiptId) } : {}),
      ...(embeddedChat ? { ELEVATE_DASHBOARD_TUI: "1" } : {}),
    };

    if (await backendMatchesDesktopMode()) {
      markStartup("backend:already-compatible");
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

    const compatible = await waitForBackend();
    if (!compatible) {
      markStartup("backend:timeout-detail", await backendProbeSummary());
    }
    markStartup(compatible ? "backend:compatible" : "backend:timeout");

    scheduleGatewaySelfHeal(launcher, baseEnv);

    return compatible;
  }

  return {
    appendBackendLog,
    ensureBackend,
    scheduleGatewaySelfHeal,
  };
}

module.exports = { createBackendRunner };
