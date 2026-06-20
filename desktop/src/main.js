const {
  app,
  BrowserWindow,
  Menu,
  dialog,
  ipcMain,
  session,
  shell,
  screen,
} = require("electron");
const { execFileSync, spawn, spawnSync } = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { autoUpdater } = require("electron-updater");
const log = require("electron-log");
const { isTrustedNavigationUrl } = require("./navigation-guard");
const backendHttp = require("./backend-http");
const { createComputerUseOverlay } = require("./computer-use-overlay");
const dashboardBundle = require("./dashboard-bundle");
const { createDesktopAuth } = require("./desktop-auth");
const { createGatewaySelfHeal } = require("./gateway-self-heal");
const { installDesktopPermissions } = require("./permissions");
const desktopMenu = require("./menu");
const { createSmsOutbox } = require("./sms-outbox");
const startupLog = require("./startup-log");
const { createUpdaterController } = require("./updater");
const { createInstallerController } = require("./installer");

// Send autoUpdater logs to a file so we can debug what the user saw.
// Tail with: tail -f ~/Library/Logs/Elevate/main.log
log.transports.file.level = "info";
autoUpdater.logger = log;
autoUpdater.autoDownload = true; // download in background as soon as available
// Install-on-quit safety net — NOT on macOS. On mac this hands the staged
// update to Squirrel's ShipIt when the user quits, and ShipIt ALWAYS
// relaunches the app after swapping the bundle: the user quits Elevate and a
// "different app" pops right back open (it's the updated bundle), sometimes
// without a Dock tile because the ShipIt respawn skips normal LaunchServices
// activation. With daily releases nearly every quit had an update staged, so
// quitting looked broken (Justin live repro, 2026-06-12). On mac, quit means
// quit — the in-app "Restart to update" card is the install path, and the
// next launch re-offers a downloaded update from cache within seconds.
autoUpdater.autoInstallOnAppQuit = process.platform !== "darwin";
// Always pull the full, notarized zip — never a differential reconstruction.
// Differential updates rebuild the new .app from the *currently installed* app's
// blocks. Older builds (before PYTHONPYCACHEPREFIX/PYTHONDONTWRITEBYTECODE) let
// the bundled Python write .pyc into Contents/Resources at runtime, so the
// reconstructed bundle carries stray .pyc + an altered web_dist/index.html that
// aren't in the signature's sealed manifest. macOS then rejects it:
//   "a sealed resource is missing or invalid" → ShipIt aborts → stuck on old ver.
// The full zip is pristine (your DMG installs work for exactly this reason), so
// forcing it sidesteps the whole class of failure.
autoUpdater.disableDifferentialDownload = true;

const PREFERRED_PORT = Number(process.env.ELEVATE_DESKTOP_PORT || 9119);
const HOST = "127.0.0.1";
const HOME = os.homedir();
const START_PATH = process.env.ELEVATE_DESKTOP_START_PATH || "/chat";
const DASHBOARD_LOAD_RETRY_LIMIT = 3;
const DASHBOARD_LOAD_RETRY_DELAY_MS = 750;
const HQ_BASE_URL = (process.env.ELEVATE_BACKEND_URL || "https://api.elevationrealestatehq.com").replace(/\/+$/, "");
const LICENSE_PATH = path.join(HOME, ".elevate", "license.json");
// Refresh access tokens with this much headroom before expiry. Mirrors
// REFRESH_MARGIN_SECONDS in elevate_cli/license.py so the two stay in sync.
const ACCESS_REFRESH_MARGIN_MS = 5 * 60 * 1000;
const EMBEDDED_CHAT =
  process.env.ELEVATE_DESKTOP_EMBEDDED_CHAT !== "0" &&
  process.env.ELEVATE_DASHBOARD_TUI !== "0";
const DEFAULT_PATH = [
  path.join(HOME, ".elevate", "bin"),
  path.join(HOME, ".local", "bin"),
  "/opt/homebrew/bin",
  "/usr/local/bin",
  "/usr/bin",
  "/bin",
  "/usr/sbin",
  "/sbin",
].join(":");
const auth = createDesktopAuth({
  accessRefreshMarginMs: ACCESS_REFRESH_MARGIN_MS,
  hqBaseUrl: HQ_BASE_URL,
  licensePath: LICENSE_PATH,
  log,
});
const smsOutbox = createSmsOutbox({ log });

let mainWindow = null;
let backendProcess = null;
// Deep link (elevate://…) captured before the main window exists, replayed
// once startup finishes. macOS can fire open-url before app.whenReady().
let pendingDeepLink = null;

// The computer-use tool touches this file on every action. The desktop app
// polls its mtime and shows the screen-edge glow while it is fresh, so the
// user always sees when the agent is driving their Mac.
const COMPUTER_USE_FLAG = path.join(HOME, ".elevate", "computer-use-active");
const COMPUTER_USE_FRESH_MS = 6000;
const computerUseOverlay = createComputerUseOverlay({
  BrowserWindow,
  dirname: __dirname,
  flagPath: COMPUTER_USE_FLAG,
  freshMs: COMPUTER_USE_FRESH_MS,
  fs,
  path,
  screen,
});
let ownsBackend = false;
let backendReady = false;
let backendPort = PREFERRED_PORT;
let backendUrl = `http://${HOST}:${backendPort}`;
let dashboardLoadRetryCount = 0;
let dashboardLoadRetryTimer = null;
let lastDashboardPath = START_PATH;
const startupTracker = startupLog.createStartupLogger(log);
const gatewaySelfHeal = createGatewaySelfHeal({
  app,
  appendBackendLog,
  envWithPath,
  fileExists,
  fs,
  os,
  path,
  process,
  spawnSync,
});
const updater = createUpdaterController({
  app,
  autoUpdater,
  fs,
  ipcMain,
  log,
  mainWindow: () => mainWindow,
  resourcesPath: () => process.resourcesPath,
});
const installer = createInstallerController({
  appendBackendLog,
  dialog,
  ensureBackend,
  envWithPath,
  findCommand,
  loadAppPath,
  loadLocalPage,
  mainWindow: () => mainWindow,
  os,
  spawn,
  startPath: START_PATH,
});

app.setName("Elevate");

// Single-instance lock. A second launch (Finder double-open, or an elevate://
// link that macOS/Windows tries to open in a fresh process) must hand off to
// the already-running app rather than spin up a duplicate window + a second
// backend on the next port. The primary instance receives the second one's
// argv via `second-instance` and replays any deep link from it.
const isPrimaryInstance = app.requestSingleInstanceLock();
if (!isPrimaryInstance) {
  app.quit();
} else {
  app.on("second-instance", (_event, argv) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
    app.focus({ steal: true });
    // Windows/Linux deliver elevate:// URLs as an argv entry (macOS uses the
    // open-url event instead). Replay it through the shared handler.
    const deepLink = argv.find(
      (a) => typeof a === "string" && a.startsWith("elevate://"),
    );
    if (deepLink) handleDeepLink(deepLink);
  });
}

function markStartup(name, detail = "") {
  startupTracker.markStartup(name, detail);
}

function finishStartup(reason) {
  startupTracker.finishStartup(reason);
}

function currentMainWindowUrl() {
  try {
    if (!mainWindow || mainWindow.isDestroyed()) return "";
    return mainWindow.webContents.getURL();
  } catch {
    return "";
  }
}

function trimLogMessage(value, max = 1200) {
  return startupLog.trimLogMessage(value, max);
}

function formatCrashForLog(reason) {
  return startupLog.formatCrashForLog(reason);
}

function installMainCrashCapture() {
  startupLog.installMainCrashCapture({ app, log, formatCrashForLog });
}

installMainCrashCapture();
markStartup("main:module-loaded");

function repoRoot() {
  return path.resolve(__dirname, "..", "..");
}

// ---- Auth gate ---------------------------------------------------------
//
// The desktop app requires an Elevation Real Estate HQ login before it will
// load the local dashboard. Tokens live in ~/.elevate/license.json — the
// same file the CLI reads/writes via elevate_cli/license.py. Writing in the
// same shape means `elevate license status` (and any future shared tooling)
// sees the desktop session.

function readLicense() {
  return auth.readLicense();
}

function writeLicense(license) {
  return auth.writeLicense(license);
}

function clearLicense() {
  return auth.clearLicense();
}

function decodeJwtExp(token) {
  return auth.decodeJwtExp(token);
}

function hqJsonRequestHeaders(scope) {
  return auth.hqJsonRequestHeaders(scope);
}

async function refreshLicense(license) {
  return auth.refreshLicense(license);
}

// Retry wrapper for startup. Transient network failures during app launch
// (DNS not yet warm, VPN reconnecting, HQ briefly slow) used to trigger the
// login popup even though the user had a valid refresh_token on disk. We try
// up to 3 times with short backoff before giving up.
async function refreshLicenseWithRetry(license, attempts = 3) {
  return auth.refreshLicenseWithRetry(license, attempts);
}

// Returns a valid license, refreshing if needed. Returns null if there's no
// usable session. On startup the network may not be fully ready, so refresh
// is retried before we give up and pop the login window.
async function ensureValidLicense({ retry = false } = {}) {
  return auth.ensureValidLicense({ retry });
}

// Forces a token refresh regardless of expiry — used on window focus and a
// background interval so an admin revoking a skill pack on HQ propagates to
// the local ~/.elevate/license.json within seconds. The React dashboard
// already polls /api/license/status on focus, so once this writes the new
// entitlements the locked/unlocked tabs flip without a reload.
async function forceRefreshLicense() {
  const current = readLicense();
  if (!current || !current.refresh_token) return null;
  const next = await refreshLicense(current);
  if (next && mainWindow && !mainWindow.isDestroyed()) {
    // Nudge the React side to re-check immediately rather than wait for its
    // own 30s tick.
    mainWindow.webContents
      .executeJavaScript(
        "window.dispatchEvent(new Event('elevate:auth-changed'));",
        true,
      )
      .catch(() => {});
  }
  return next;
}

async function performLogin({ email, password }) {
  return auth.performLogin({ email, password });
}

function envWithPath(extra = {}) {
  const pythonCacheDir = path.join(HOME, "Library", "Caches", "Elevate", "python-pycache");
  const env = { ...process.env };
  // Cache compiled bytecode OUTSIDE the signed bundle so 2nd+ launches skip
  // re-parsing every .py from source (the bundled .pyc are stripped at build
  // time). Safe since 1.1.28 disabled differential updates: PYTHONPYCACHEPREFIX
  // points into ~/Library/Caches, so .pyc never land in Contents/Resources and
  // the codesign seal stays intact. We must UNSET PYTHONDONTWRITEBYTECODE rather
  // than set it to "0" — CPython treats ANY non-empty value (incl. "0") as
  // "don't write bytecode", so an inherited value would silently re-disable it.
  delete env.PYTHONDONTWRITEBYTECODE;
  env.PATH = process.env.PATH ? `${DEFAULT_PATH}:${process.env.PATH}` : DEFAULT_PATH;
  env.PYTHONPYCACHEPREFIX = process.env.PYTHONPYCACHEPREFIX || pythonCacheDir;
  return { ...env, ...extra };
}

function fileExists(filePath) {
  try {
    return fs.existsSync(filePath);
  } catch {
    return false;
  }
}

function findCommand(name) {
  try {
    return execFileSync("/usr/bin/env", ["bash", "-lc", `command -v ${name}`], {
      env: envWithPath(),
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return "";
  }
}

function resolveElevateLauncher() {
  const dashboardArgs = [
    "dashboard",
    "--port",
    String(backendPort),
    "--host",
    HOST,
    "--no-open",
  ];
  if (EMBEDDED_CHAT) {
    dashboardArgs.push("--tui");
  }

  if (process.env.ELEVATE_DESKTOP_CLI) {
    return {
      command: process.env.ELEVATE_DESKTOP_CLI,
      args: dashboardArgs,
      cwd: os.homedir(),
    };
  }

  // Bundled runtime (the .app ships its own Python + CLI source under
  // Contents/Resources so a fresh install doesn't need a separate
  // `elevate` CLI on the user's PATH). Highest priority when packaged.
  if (app.isPackaged) {
    const bundledPython = path.join(
      process.resourcesPath,
      "runtime",
      "python",
      "bin",
      "python3.12",
    );
    const bundledCli = path.join(process.resourcesPath, "cli");
    if (fileExists(bundledPython) && fileExists(bundledCli)) {
      // The agent works out of a dedicated user folder (~/Elevation), NOT its
      // own read-only bundled code. Imports still resolve via PYTHONPATH.
      const userWorkspace = path.join(os.homedir(), "Elevation");
      try {
        fs.mkdirSync(userWorkspace, { recursive: true });
      } catch (e) {
        /* best-effort */
      }
      return {
        command: bundledPython,
        args: ["-m", "elevate_cli.main", ...dashboardArgs],
        cwd: userWorkspace,
        extraEnv: {
          PYTHONPATH: bundledCli,
          PYTHONNOUSERSITE: "1",
          ELEVATE_WORKSPACE: userWorkspace,
        },
      };
    }
  }

  const root = repoRoot();
  const localPython = path.join(root, "cli", ".venv", "bin", "python");
  if (fileExists(localPython)) {
    return {
      command: localPython,
      args: [
        "-m",
        "elevate_cli.main",
        ...dashboardArgs,
      ],
      cwd: path.join(root, "cli"),
    };
  }

  const elevate = findCommand("elevate");
  if (elevate) {
    return {
      command: elevate,
      args: dashboardArgs,
      cwd: os.homedir(),
    };
  }

  return null;
}

// Run an `elevate gateway <...>` command using the SAME resolved CLI launcher as
// the dashboard (just swap the "dashboard" subcommand for "gateway"). Returns the
// spawnSync result (status/stdout/stderr captured).
function runGatewayCommand(launcher, baseEnv, gwArgs, { timeoutMs = 90000 } = {}) {
  return gatewaySelfHeal.runGatewayCommand(launcher, baseEnv, gwArgs, { timeoutMs });
}

// Records which app version the gateway last (re)started on. Lets us restart it
// exactly once after an update instead of on every launch.
function gatewayVersionMarkerPath() {
  return gatewaySelfHeal.gatewayVersionMarkerPath();
}

function readGatewayVersionMarker() {
  return gatewaySelfHeal.readGatewayVersionMarker();
}

function writeGatewayVersionMarker(version) {
  gatewaySelfHeal.writeGatewayVersionMarker(version);
}

function existingGatewayMissingResource() {
  return gatewaySelfHeal.existingGatewayMissingResource();
}

// Restart the loaded gateway so it re-execs the freshly-bundled CLI code. A
// desktop auto-update swaps the .app bundle, but the long-lived launchd gateway
// keeps running the OLD code in memory — so the seed/migration path
// (ensure_system_jobs: preinstalled fleet defaults + the sentinel-gated
// fleet-rebuild + heartbeat/automation seeding) never re-applies on update.
// Without this, every updated customer is stuck on their old roster until
// someone restarts the gateway by hand. macOS only.
function kickstartGateway(uid) {
  return gatewaySelfHeal.kickstartGateway(uid);
}

// Probe launchd for the gateway job. Distinguishes:
//   loaded  — `launchctl print gui/$UID/ai.elevate.gateway` finds the job
//   running — the loaded job actually has a pid / "state = running"
// "Could not find service" (not loaded) is exactly what a Squirrel ShipIt
// auto-update left behind on a customer Mac: the gateway got SIGTERM'd and the
// job ended up booted out of the gui domain entirely, so KeepAlive could never
// revive it and Telegram/cron stayed dead until a manual `launchctl bootstrap`.
function probeGateway(uid) {
  return gatewaySelfHeal.probeGateway(uid);
}

// Last-resort revival that does NOT depend on the Python CLI working: load the
// plist already on disk straight into the gui domain. Covers the case where
// `gateway install` itself fails (e.g. CLI broken mid-update) but a valid
// plist survived in ~/Library/LaunchAgents. bootstrap of an already-loaded
// job fails (EALREADY) — fine, the kickstart then starts a loaded-but-dead one.
function bootstrapGatewayDirect(uid, plist) {
  return gatewaySelfHeal.bootstrapGatewayDirect(uid, plist);
}

// Self-heal the gateway launchd service. The gateway runs the cron ticker that
// SEEDS + runs each account's lead/admin automations + heartbeats. If onboarding
// never installed it (the silent "no automations, no heartbeats" failure mode),
// install it now. If a desktop auto-update (ShipIt) killed it and left the job
// unloaded, re-bootstrap it. A healthy gateway on the SAME version is never
// restarted; a healthy gateway on a DIFFERENT version (i.e. just after an
// update) is restarted ONCE so the new bundled code seeds the current fleet +
// migrations. Best-effort, non-blocking, logged. macOS only.
function ensureGatewayInstalled(launcher, baseEnv) {
  gatewaySelfHeal.ensureGatewayInstalled(launcher, baseEnv);
}

function request(pathname, timeoutMs = 2000, port = backendPort) {
  return backendHttp.request({ http, host: HOST, pathname, port, timeoutMs });
}

function requestText(pathname, timeoutMs = 2000, port = backendPort) {
  return backendHttp.requestText({ http, host: HOST, pathname, port, timeoutMs });
}

async function requestJson(pathname, timeoutMs = 2000, port = backendPort) {
  return backendHttp.requestJson({ http, host: HOST, pathname, port, timeoutMs });
}

async function backendIsReady(port = backendPort) {
  return backendHttp.backendIsReady({ http, host: HOST, port });
}

async function dashboardChatEnabled(port = backendPort) {
  return backendHttp.dashboardChatEnabled({ http, host: HOST, port });
}

// Hashed asset references (assets/<name>-<hash>.js|css) declared in an
// index.html. Vite re-hashes these on every build, so the SET of entry-chunk
// references uniquely identifies a bundle. Comparing the served set to the
// bundled set is how we detect a stale dashboard — a process left running by
// the pre-update app serves the OLD index.html, whose asset hashes the new
// app expects but the old server can 404 (blank dashboard, broken
// search/collapse icons — Justin's box after the 1.2.33 auto-update). A plain
// version-string check does NOT work: the cli __version__ (0.12.x) is a
// different scheme from the desktop app version (1.2.x).
function assetRefs(html) {
  return dashboardBundle.assetRefs(html);
}

function bundledIndexHtml() {
  return dashboardBundle.bundledIndexHtml({ app, fs, path, process, repoRoot });
}

async function backendBundleMatches(port = backendPort) {
  return dashboardBundle.backendBundleMatches({
    app,
    backendPort: port,
    fs,
    path,
    process,
    repoRoot,
    requestText,
  });
}

// Kill whatever process is listening on a dashboard port — used to evict a
// stale-version dashboard so a fresh one can bind the preferred port. Scoped
// to the port via lsof, so it never touches the gateway (different port) or
// unrelated processes. Best-effort.
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
    return false; // lsof found nothing / not available
  }
}

async function backendMatchesDesktopMode(port = backendPort) {
  if (!(await backendIsReady(port))) return false;
  if (!(await backendBundleMatches(port))) return false;
  if (!EMBEDDED_CHAT) return true;
  return dashboardChatEnabled(port);
}

async function waitForBackend(timeoutMs = 180000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (await backendMatchesDesktopMode()) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

async function backendProbeSummary(port = backendPort) {
  const [statusReady, bundleMatch, chatEnabled] = await Promise.allSettled([
    backendIsReady(port),
    backendBundleMatches(port),
    dashboardChatEnabled(port),
  ]);
  const value = (result) => result.status === "fulfilled" ? String(result.value) : `error:${result.reason}`;
  return `port=${port} status=${value(statusReady)} bundle=${value(bundleMatch)} chat=${value(chatEnabled)}`;
}

async function chooseBackendPort() {
  if (await backendMatchesDesktopMode(PREFERRED_PORT)) {
    backendPort = PREFERRED_PORT;
    backendUrl = `http://${HOST}:${backendPort}`;
    return;
  }

  // A ready-but-WRONG-VERSION backend on the preferred port = a stale
  // dashboard the pre-update app left running. Adopting a higher port would
  // leave it serving the old bundle on the preferred port AND confuse anything
  // that probes the default port. Evict it so the fresh spawn binds cleanly.
  if (
    (await backendIsReady(PREFERRED_PORT)) &&
    !(await backendBundleMatches(PREFERRED_PORT))
  ) {
    log.info("[elevate-backend] stale-bundle dashboard on preferred port — evicting");
    killProcessOnPort(PREFERRED_PORT);
    // Give the socket a moment to free up before the caller spawns fresh.
    for (let i = 0; i < 20; i += 1) {
      if (!(await backendIsReady(PREFERRED_PORT))) break;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    backendPort = PREFERRED_PORT;
    backendUrl = `http://${HOST}:${backendPort}`;
    return;
  }

  for (let port = PREFERRED_PORT + 1; port <= PREFERRED_PORT + 10; port += 1) {
    if (await backendMatchesDesktopMode(port)) {
      backendPort = port;
      backendUrl = `http://${HOST}:${backendPort}`;
      return;
    }
    if (!(await backendIsReady(port))) {
      backendPort = port;
      backendUrl = `http://${HOST}:${backendPort}`;
      return;
    }
  }

  backendPort = PREFERRED_PORT;
  backendUrl = `http://${HOST}:${backendPort}`;
}

function appendBackendLog(data) {
  const text = data.toString();
  if (text.trim()) {
    console.log(`[elevate-backend] ${text.trimEnd()}`);
  }
}

function scheduleGatewaySelfHeal(launcher, baseEnv) {
  if (!launcher) return;
  // Self-heal the gateway service (cron ticker that seeds + runs automations +
  // heartbeats). Deferred so it never blocks UI startup. Idempotent.
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
  markStartup("backend:port-selected", String(backendPort));

  const launcher = resolveElevateLauncher();
  const baseEnv = {
    ELEVATE_DESKTOP_APP: "1",
    // SMS sends go via the sms-outbox spool drained by THIS foreground app
    // (the headless backend can't hold macOS Automation→Messages). See
    // startSmsOutboxWatcher + cli/elevate_cli/sender._imsg_send_via_app.
    ELEVATE_SMS_VIA_APP: "1",
    ...(EMBEDDED_CHAT ? { ELEVATE_DASHBOARD_TUI: "1" } : {}),
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
  backendProcess = spawn(launcher.command, launcher.args, {
    cwd: launcher.cwd,
    env: envWithPath({ ...baseEnv, ...(launcher.extraEnv || {}) }),
    stdio: ["ignore", "pipe", "pipe"],
  });
  ownsBackend = true;

  backendProcess.stdout.on("data", appendBackendLog);
  backendProcess.stderr.on("data", appendBackendLog);
  backendProcess.on("exit", (code, signal) => {
    console.log(`[elevate-backend] exited code=${code} signal=${signal}`);
    backendProcess = null;
    ownsBackend = false;
  });

  const ready = await waitForBackend();
  if (!ready) {
    markStartup("backend:timeout-detail", await backendProbeSummary());
  }
  markStartup(ready ? "backend:ready" : "backend:timeout");

  scheduleGatewaySelfHeal(launcher, baseEnv);

  return ready;
}

function createMenu() {
  desktopMenu.createMenu({
    app,
    backendUrl: () => backendUrl,
    clearLicense,
    hqBaseUrl: HQ_BASE_URL,
    loadAppPath,
    mainWindow: () => mainWindow,
    Menu,
    openLoginWindow,
    shell,
    startPath: START_PATH,
  });
}

function createWindow() {
  markStartup("window:create");
  mainWindow = new BrowserWindow({
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
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      // Sandbox the renderer: the preload only uses contextBridge + ipcRenderer
      // (both work under sandbox), so a renderer-side XSS can't reach Node.
      sandbox: true,
    },
  });

  mainWindow.once("ready-to-show", () => {
    markStartup("window:ready-to-show");
    mainWindow.show();
  });

  mainWindow.webContents.on("dom-ready", () => {
    const url = mainWindow && !mainWindow.isDestroyed() ? mainWindow.webContents.getURL() : "";
    markStartup("renderer:dom-ready", url.startsWith(backendUrl) ? "dashboard" : path.basename(url));
  });

  mainWindow.webContents.on("did-finish-load", () => {
    const url = mainWindow && !mainWindow.isDestroyed() ? mainWindow.webContents.getURL() : "";
    const isDashboard = url.startsWith(backendUrl);
    markStartup("renderer:did-finish-load", isDashboard ? "dashboard" : path.basename(url));
    if (isDashboard) {
      clearDashboardLoadRetryTimer();
      dashboardLoadRetryCount = 0;
      finishStartup("dashboard-loaded");
    }
  });

  mainWindow.webContents.on("did-fail-load", (_event, code, description, validatedUrl) => {
    const failedUrl = validatedUrl || currentMainWindowUrl();
    log.warn(
      `[renderer:did-fail-load] code=${code} desc=${trimLogMessage(description, 300)} url=${trimLogMessage(failedUrl, 500)}`,
    );
    if (code !== -3 && failedUrl.startsWith(backendUrl)) {
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

  // Without this, a closed main window leaves `mainWindow` pointing at a
  // destroyed BrowserWindow. The `if (!mainWindow)` guards elsewhere stay
  // truthy, so the next loadURL/loadFile throws — that's the reopen glitch.
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  mainWindow.on("page-title-updated", (event) => {
    event.preventDefault();
  });

  // Native chat apps (Claude, Codex, ChatGPT desktop) don't let you
  // refresh the window — a refresh would blow away in-memory chat
  // state and force a reconnect/re-render dance. Swallow Cmd+R /
  // Ctrl+R / F5 so users get the same "close-and-reopen-only" feel.
  mainWindow.webContents.on("before-input-event", (event, input) => {
    if (input.type !== "keyDown") return;
    const key = (input.key || "").toLowerCase();
    const isReloadCombo =
      (key === "r" && (input.meta || input.control)) || key === "f5";
    if (isReloadCombo) {
      event.preventDefault();
    }
  });

  // Native right-click menu (copy / paste / cut / select-all). Electron shows
  // no context menu by default, so wire one up like a normal mac app.
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
    if (url.startsWith(backendUrl)) {
      return { action: "allow" };
    }
    // Only hand http(s)/mailto to the OS. The renderer shows untrusted content
    // (AI output, lead/MLS fields); without this, a window.open("file://…") or
    // an OS-handler scheme would be launched via openExternal.
    try {
      const scheme = new URL(url).protocol;
      if (scheme === "https:" || scheme === "http:" || scheme === "mailto:") {
        shell.openExternal(url);
      }
    } catch {
      /* malformed URL — ignore */
    }
    return { action: "deny" };
  });

  // Lock the main window to the trusted local origin: block top-level
  // navigation elsewhere (setWindowOpenHandler only covers window.open).
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!isTrustedNavigationUrl(url, { backendUrl, appRoot: __dirname })) {
      event.preventDefault();
    }
  });
}

function createOverlay() {
  computerUseOverlay.createOverlay();
}

function setOverlayVisible(visible) {
  computerUseOverlay.setOverlayVisible(visible);
}

function startOverlayWatcher() {
  computerUseOverlay.startOverlayWatcher();
}

function loadLocalPage(fileName) {
  if (!mainWindow) return;
  markStartup("window:load-local", fileName);
  mainWindow.loadFile(path.join(__dirname, fileName));
}

function clearDashboardLoadRetryTimer() {
  if (!dashboardLoadRetryTimer) return;
  clearTimeout(dashboardLoadRetryTimer);
  dashboardLoadRetryTimer = null;
}

function scheduleDashboardLoadRetry(reason) {
  if (!mainWindow || mainWindow.isDestroyed() || dashboardLoadRetryTimer) return;
  if (dashboardLoadRetryCount >= DASHBOARD_LOAD_RETRY_LIMIT) {
    markStartup("window:dashboard-retry-exhausted", reason);
    loadLocalPage("install.html");
    return;
  }

  dashboardLoadRetryCount += 1;
  const attempt = dashboardLoadRetryCount;
  const pathname = lastDashboardPath || START_PATH;
  markStartup("window:dashboard-retry", `${attempt}:${reason}`);
  loadLocalPage("loading.html");

  dashboardLoadRetryTimer = setTimeout(async () => {
    dashboardLoadRetryTimer = null;
    if (!mainWindow || mainWindow.isDestroyed()) return;
    if (!(await backendMatchesDesktopMode())) {
      scheduleDashboardLoadRetry("backend-not-ready");
      return;
    }
    loadAppPath(pathname, { retry: true });
  }, DASHBOARD_LOAD_RETRY_DELAY_MS);
  if (typeof dashboardLoadRetryTimer.unref === "function") {
    dashboardLoadRetryTimer.unref();
  }
}

// The dashboard renders a full-screen <LoginCard /> whenever there's no valid
// license (see cli/web App.tsx's license gate), so the sign-in screen lives
// inside the app itself. We deliberately do NOT pop a separate native login
// window — that produced two competing sign-in screens stacked on top of each
// other. This just brings the dashboard forward and nudges it to re-check
// license state so the in-app card renders.
function openLoginWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.focus();
  const currentUrl = mainWindow.webContents.getURL();
  if (!currentUrl.startsWith(backendUrl)) {
    // Drifted off the dashboard origin (e.g. sitting on a local page) — load
    // it so the in-app login screen can render.
    loadAppPath(START_PATH);
  } else {
    mainWindow.webContents
      .executeJavaScript(
        "window.dispatchEvent(new Event('elevate:auth-changed'));",
        true,
      )
      .catch(() => {});
  }
}

function loadAppPath(pathname = START_PATH, options = {}) {
  if (!mainWindow) return;
  lastDashboardPath = pathname || START_PATH;
  if (!options.retry) {
    dashboardLoadRetryCount = 0;
    clearDashboardLoadRetryTimer();
  }
  markStartup("window:load-dashboard", pathname);
  mainWindow.loadURL(`${backendUrl}${pathname}`).catch((err) => {
    if (String(err && err.message ? err.message : err).includes("ERR_ABORTED")) return;
    log.warn(`[renderer:loadURL] ${trimLogMessage(err && err.message ? err.message : err, 500)}`);
    scheduleDashboardLoadRetry("loadURL-rejected");
  });
}

function setupPermissions() {
  installDesktopPermissions({ session, dashboardOrigin: backendUrl });
}

async function startDesktop() {
  markStartup("desktop:start");
  setupPermissions();
  createWindow();
  createMenu();
  startOverlayWatcher();
  // The always-on-top, non-activating overlay panel (focusable:false +
  // setVisibleOnAllWorkspaces + "screen-saver" level) can silently demote the
  // whole app to a macOS "accessory" (lsappinfo type=UIElement) when it is
  // created for computer-use. Re-assert the regular activation policy during
  // startup so the app keeps a proper Dock tile + running indicator.
  // Activation policy is app-level and persists across minimize/restore.
  if (process.platform === "darwin" && app.dock) {
    app.dock.show();
  }
  loadLocalPage("loading.html");

  const ready = await ensureBackend();
  backendReady = ready;
  if (ready) {
    markStartup("desktop:backend-ready");
    // The auth gate is enforced inside the chat endpoint, not at window load,
    // so the user can browse the dashboard while signed out. The chat will
    // reply with a "sign in required" message until ~/.elevate/license.json
    // contains a valid token.
    loadAppPath(START_PATH);
    // If no valid license is on disk, pop the in-app login window on top of
    // the dashboard so the user signs in without ever leaving the app.
    // Same window the "Sign In..." menu opens — small floating modal, not
    // a full-screen takeover.
    // On launch only: if a license file exists, give the refresh up to 3
    // attempts before popping the login window. Without retry, a transient
    // network blip at startup throws the user into a sign-in modal even
    // though their session is still valid on HQ.
    ensureValidLicense({ retry: true })
      .then((license) => {
        if (!license) {
          const onDisk = readLicense();
          if (onDisk && onDisk.refresh_token) {
            // We have a refresh_token but every retry failed. Don't pop the
            // login window — the background interval will keep trying every
            // 60s and the dashboard's gateway has its own session. If HQ is
            // truly down, the user sees a "sign in required" message inside
            // the chat panel rather than a confusing login modal.
            console.warn(
              "[license] startup refresh failed after retries — leaving session in place",
            );
            return;
          }
          openLoginWindow();
        }
      })
      .catch((err) => {
        console.warn(`[license] ensureValidLicense threw: ${err && err.message ? err.message : err}`);
        const onDisk = readLicense();
        if (!onDisk || !onDisk.refresh_token) openLoginWindow();
      });

    // Keep the local license in sync with HQ. If an admin revokes a skill
    // pack the user has, the next focus or 60s tick fetches fresh
    // entitlements via /api/license/refresh, rewrites license.json, and
    // notifies the React dashboard to re-render the sidebar/tabs.
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.on("focus", () => {
        forceRefreshLicense().catch(() => {});
      });
    }
    setInterval(() => {
      forceRefreshLicense().catch(() => {});
    }, 60_000);
  } else {
    markStartup("desktop:backend-unavailable");
    loadLocalPage("install.html");
  }
}

function runInstaller() {
  return installer.runInstaller();
}

ipcMain.handle("desktop:retry", async () => {
  return installer.retry();
});

ipcMain.handle("desktop:install", async () => runInstaller());

// ---- Auth IPC ---------------------------------------------------------
// Login form on login.html calls these. After a successful login we route
// the window straight into the dashboard so the user doesn't have to click
// anything else.

ipcMain.handle("auth:login", async (_event, payload) => {
  const result = await performLogin(payload || {});
  if (result.ok) {
    // Reload the dashboard so the chat WebSocket reopens and picks up the new
    // license. The login screen is the in-app <LoginCard /> — there's no
    // separate native login window to close.
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        loadAppPath(START_PATH);
      }
    }, 250);
  }
  return result;
});

// Routes the login page's "Forgot?" / "Create account" / "Use a code" links
// out to the user's default browser. Hard-coded to the HQ origin so a
// compromised renderer can't open arbitrary URLs.
ipcMain.handle("auth:open-external", async (_event, target) => {
  const paths = {
    forgot: "/forgot?app=1",
    signup: "/signup",
    link: "/link",
    account: "/account",
  };
  const safePath = paths[target];
  if (!safePath) return { ok: false };
  await shell.openExternal(`${HQ_BASE_URL}${safePath}`);
  return { ok: true };
});

// ---------------------------------------------------------------------------
// Auto-update
// ---------------------------------------------------------------------------
// Flow:
//   1. App boots → checkForUpdates() hits the configured generic release feed.
//   2. If a newer version is found, autoDownload=true pulls the zip silently.
//   3. We forward every event to the renderer via `updater:event` so the toast
//      UI can show progress / "restart to update".
//   4. User clicks Restart → quitAndInstall() swaps the binary and relaunches.
//   5. We also re-check every 3 minutes while the app is running.
//
function broadcastUpdaterEvent(payload) {
  updater.broadcastUpdaterEvent(payload);
}

async function runUpdaterCheck(reason) {
  return updater.runUpdaterCheck(reason);
}

updater.registerAutoUpdaterEvents();

function kickoffUpdates() {
  updater.kickoffUpdates();
}

updater.registerIpcHandlers();

// Register the elevate:// scheme so the web auth flow (a password reset
// completed in the browser) can bounce the user back into the app. The reset
// success page links to elevate://signin; macOS fires `open-url` on the running
// instance, and we just focus the dashboard (which shows the in-app login).
app.setAsDefaultProtocolClient("elevate");

// Bounce the user back into the app after a browser auth flow (e.g. a password
// reset completing on the HQ site links to elevate://signin). If the window
// isn't up yet (cold start triggered by the link itself), stash the URL and
// replay it once startDesktop() has created the window.
function handleDeepLink(url) {
  if (!url) return;
  if (!mainWindow || mainWindow.isDestroyed()) {
    pendingDeepLink = url;
    return;
  }
  // steal:true brings Elevate to the foreground over the browser the user
  // clicked the link from — window.focus() alone won't activate a backgrounded
  // macOS app.
  app.focus({ steal: true });
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
  openLoginWindow();
}

app.on("open-url", (event, url) => {
  event.preventDefault();
  handleDeepLink(url);
});

function startSmsOutboxWatcher() {
  smsOutbox.startSmsOutboxWatcher();
}

app.whenReady().then(async () => {
  // Secondary instance already handed off to the primary and is quitting.
  if (!isPrimaryInstance) return;
  markStartup("electron:ready");
  // A ShipIt-relaunched instance (post-update) can spawn without normal
  // LaunchServices activation: the app runs with no Dock tile and doesn't
  // show as a live app. Force regular-app registration + focus on every
  // launch — a no-op for a normal Finder/Dock launch.
  if (process.platform === "darwin" && app.dock) {
    // Fire-and-forget: dock.show()'s promise can take SECONDS to resolve
    // (it waits on macOS activation) — awaiting it here held window
    // creation hostage for ~11s of blank app on every launch. The Dock
    // tile registration doesn't need to precede anything.
    Promise.resolve(app.dock.show())
      .then(() => app.focus({ steal: false }))
      .catch((err) =>
        log.warn(`[startup] dock registration failed: ${err && err.message ? err.message : err}`),
      );
  }
  await startDesktop();
  startSmsOutboxWatcher();
  kickoffUpdates();
  // A deep link that launched the app fires open-url before the window exists;
  // replay it now that startDesktop() has created mainWindow.
  if (pendingDeepLink) {
    const url = pendingDeepLink;
    pendingDeepLink = null;
    handleDeepLink(url);
  }
});

app.on("activate", () => {
  // Track the main window explicitly. The computer-use overlay is lazy and may
  // be absent during idle, so BrowserWindow.getAllWindows() is not the app
  // lifecycle source of truth.
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
    return;
  }
  // Backend is already up from the first launch: skip the loading screen
  // and health check and just bring the UI straight back.
  if (backendReady) {
    createWindow();
    createMenu();
    loadAppPath(START_PATH);
    return;
  }
  startDesktop();
});

app.on("before-quit", () => {
  computerUseOverlay.dispose();
  if (ownsBackend && backendProcess) {
    backendProcess.kill();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
