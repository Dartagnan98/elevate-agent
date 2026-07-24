"use strict";

// Supervisor tuning.
// - STABILITY_WINDOW_MS: a backend that stays up this long is treated as a
//   healthy run, so the consecutive-fast-failure counter resets and an eventual
//   death restarts from a cheap 1s backoff instead of an escalated one.
// - MAX_RESTART_ATTEMPTS: after this many consecutive fast failures we stop
//   thrashing and surface the outage instead of respawning forever.
// - LOG_ROTATE_BYTES: rotate backend.log → backend.log.1 past ~5 MB.
const STABILITY_WINDOW_MS = 30000;
const MAX_RESTART_ATTEMPTS = 5;
const MAX_RESTART_DELAY_MS = 30000;
const LOG_ROTATE_BYTES = 5 * 1024 * 1024;

function createBackendRunner({
  backendMatchesDesktopMode,
  backendProbeSummary,
  chooseBackendPort,
  embeddedChat,
  ensureGatewayInstalled,
  envWithPath,
  fs,
  getBackendLogPath,
  getBackendPort,
  isShuttingDown = () => false,
  markStartup,
  now = () => Date.now(),
  onBackendGaveUp = () => {},
  path,
  resolveElevateLauncher,
  runtimeMetadata = {},
  setBackendProcess,
  setBackendReady = () => {},
  setOwnsBackend,
  setTimeout,
  spawn,
  waitForBackend,
}) {
  // Append-only capture of raw backend stdout/stderr to a file next to
  // electron-log's own log. In a packaged .app console.log is discarded, so
  // without this a backend that died leaves no record. Size-rotated so it can
  // never grow unbounded.
  let backendLogStream = null;
  let backendLogBytes = 0;

  function openBackendLogStream() {
    if (!fs || typeof getBackendLogPath !== "function") return null;
    try {
      const logPath = getBackendLogPath();
      if (!logPath) return null;
      fs.mkdirSync(path.dirname(logPath), { recursive: true });
      try {
        backendLogBytes = fs.statSync(logPath).size;
      } catch {
        backendLogBytes = 0;
      }
      return fs.createWriteStream(logPath, { flags: "a" });
    } catch {
      return null;
    }
  }

  function rotateBackendLog() {
    try {
      if (backendLogStream) backendLogStream.end();
    } catch {
      /* ignore close failures */
    }
    backendLogStream = null;
    try {
      const logPath = getBackendLogPath();
      fs.renameSync(logPath, `${logPath}.1`);
    } catch {
      /* nothing to rotate */
    }
    backendLogBytes = 0;
  }

  function writeBackendLog(text) {
    if (!fs || typeof getBackendLogPath !== "function") return;
    try {
      if (backendLogStream && backendLogBytes >= LOG_ROTATE_BYTES) {
        rotateBackendLog();
      }
      if (!backendLogStream) {
        backendLogStream = openBackendLogStream();
        if (!backendLogStream) return;
      }
      backendLogStream.write(text);
      backendLogBytes += Buffer.byteLength(text);
    } catch {
      /* logging must never take the app down */
    }
  }

  function appendBackendLog(data) {
    const text = data.toString();
    // Raw chunk to disk (survives a packaged build); trimmed line to console.
    writeBackendLog(text);
    if (text.trim()) {
      console.log(`[elevate-backend] ${text.trimEnd()}`);
    }
  }

  // --- Supervisor state -------------------------------------------------
  // lastSpec is the exact spawn recipe (command/args/cwd/env) captured on the
  // first launch so a respawn re-binds the SAME port the UI already points at
  // (env carries ELEVATE_DASHBOARD_PORT from the already-selected
  // getBackendPort()). restartCount tracks consecutive fast failures.
  let lastSpec = null;
  let restartCount = 0;
  let spawnStartedAt = 0;

  function spawnBackend() {
    if (!lastSpec) return null;
    markStartup("backend:spawn", path.basename(lastSpec.command));
    spawnStartedAt = now();
    const backendProcess = spawn(lastSpec.command, lastSpec.args, {
      cwd: lastSpec.cwd,
      env: lastSpec.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    setBackendProcess(backendProcess);
    setOwnsBackend(true);

    backendProcess.stdout.on("data", appendBackendLog);
    backendProcess.stderr.on("data", appendBackendLog);
    backendProcess.on("exit", handleBackendExit);
    return backendProcess;
  }

  function handleBackendExit(code, signal) {
    console.log(`[elevate-backend] exited code=${code} signal=${signal}`);
    appendBackendLog(
      `[supervisor] backend exited code=${code} signal=${signal}\n`,
    );
    setBackendProcess(null);
    setOwnsBackend(false);
    // Health is no longer latched at startup: a dead backend flips readiness
    // false and notifies the renderer so it stops presenting a live UI. The 60s
    // license loop keeps logging "refresh succeeded" regardless, so it can no
    // longer stand in for backend health.
    setBackendReady(false);

    if (isShuttingDown()) {
      // Deliberate before-quit kill (app-lifecycle) — do not resurrect.
      return;
    }

    // A run that survived the stability window was healthy; reset the backoff
    // so an eventual death restarts cheaply instead of at an escalated delay.
    if (now() - spawnStartedAt >= STABILITY_WINDOW_MS) {
      restartCount = 0;
    }
    restartCount += 1;
    if (restartCount >= MAX_RESTART_ATTEMPTS) {
      markStartup("backend:supervisor-giveup", String(restartCount));
      appendBackendLog(
        `[supervisor] giving up after ${restartCount} consecutive fast failures\n`,
      );
      onBackendGaveUp();
      return;
    }
    const delay = Math.min(
      1000 * 2 ** (restartCount - 1),
      MAX_RESTART_DELAY_MS,
    );
    markStartup("backend:supervisor-respawn", String(delay));
    setTimeout(() => {
      if (isShuttingDown()) return;
      spawnBackend();
    }, delay);
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

    // Capture the spawn recipe once; the supervisor reuses it verbatim on every
    // respawn so restarts re-bind the same port and env the UI points at.
    lastSpec = {
      command: launcher.command,
      args: launcher.args,
      cwd: launcher.cwd,
      env: envWithPath({ ...baseEnv, ...(launcher.extraEnv || {}) }),
    };
    restartCount = 0;
    spawnBackend();

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
