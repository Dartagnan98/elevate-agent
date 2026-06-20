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
const { registerAuthIpc } = require("./auth-ipc");
const backendHttp = require("./backend-http");
const { createBackendPortController } = require("./backend-port");
const { createBackendRunner } = require("./backend-runner");
const { createComputerUseOverlay } = require("./computer-use-overlay");
const dashboardBundle = require("./dashboard-bundle");
const { createDashboardNavigation } = require("./dashboard-navigation");
const { createDeepLinks } = require("./deep-links");
const { createDesktopAuth } = require("./desktop-auth");
const { createGatewaySelfHeal } = require("./gateway-self-heal");
const { createLauncherTools } = require("./launcher");
const { createMainWindowController } = require("./main-window");
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
const startupTracker = startupLog.createStartupLogger(log);
const launcherTools = createLauncherTools({
  app,
  backendPort: () => backendPort,
  defaultPath: DEFAULT_PATH,
  embeddedChat: EMBEDDED_CHAT,
  execFileSync,
  fileExists: (filePath) => fs.existsSync(filePath),
  fs,
  home: HOME,
  host: HOST,
  os,
  path,
  process,
  repoRoot,
});
const backendPorts = createBackendPortController({
  backendBundleMatches,
  backendIsReady,
  dashboardChatEnabled,
  embeddedChat: EMBEDDED_CHAT,
  execFileSync,
  getBackendPort: () => backendPort,
  log,
  preferredPort: PREFERRED_PORT,
  setBackendPort: (port) => {
    backendPort = port;
    backendUrl = `http://${HOST}:${backendPort}`;
  },
  setTimeout,
});
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
const backendRunner = createBackendRunner({
  backendMatchesDesktopMode,
  backendProbeSummary,
  chooseBackendPort,
  embeddedChat: EMBEDDED_CHAT,
  ensureGatewayInstalled,
  envWithPath,
  getBackendPort: () => backendPort,
  markStartup,
  path,
  resolveElevateLauncher,
  setBackendProcess: (proc) => {
    backendProcess = proc;
  },
  setOwnsBackend: (value) => {
    ownsBackend = value;
  },
  setTimeout,
  spawn,
  waitForBackend,
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
const deepLinks = createDeepLinks({
  app,
  mainWindow: () => mainWindow,
  openLoginWindow,
});
const dashboardNavigation = createDashboardNavigation({
  appRoot: __dirname,
  backendMatchesDesktopMode,
  backendUrl: () => backendUrl,
  delayMs: DASHBOARD_LOAD_RETRY_DELAY_MS,
  limit: DASHBOARD_LOAD_RETRY_LIMIT,
  log,
  mainWindow: () => mainWindow,
  markStartup,
  path,
  setTimeout,
  startPath: START_PATH,
  trimLogMessage,
});
const mainWindowController = createMainWindowController({
  BrowserWindow,
  Menu,
  appRoot: __dirname,
  backendUrl: () => backendUrl,
  currentMainWindowUrl,
  finishStartup,
  isTrustedNavigationUrl,
  log,
  markStartup,
  path,
  process,
  resetDashboardLoadRetry,
  scheduleDashboardLoadRetry,
  setMainWindow: (win) => {
    mainWindow = win;
  },
  shell,
  trimLogMessage,
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
    if (deepLink) deepLinks.handleDeepLink(deepLink);
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
  return launcherTools.envWithPath(extra);
}

function fileExists(filePath) {
  return launcherTools.fileExists(filePath);
}

function findCommand(name) {
  return launcherTools.findCommand(name);
}

function resolveElevateLauncher() {
  return launcherTools.resolveElevateLauncher();
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
  return backendPorts.killProcessOnPort(port);
}

async function backendMatchesDesktopMode(port = backendPort) {
  return backendPorts.backendMatchesDesktopMode(port);
}

async function waitForBackend(timeoutMs = 180000) {
  return backendPorts.waitForBackend(timeoutMs);
}

async function backendProbeSummary(port = backendPort) {
  return backendPorts.backendProbeSummary(port);
}

async function chooseBackendPort() {
  return backendPorts.chooseBackendPort();
}

function appendBackendLog(data) {
  backendRunner.appendBackendLog(data);
}

function scheduleGatewaySelfHeal(launcher, baseEnv) {
  backendRunner.scheduleGatewaySelfHeal(launcher, baseEnv);
}

async function ensureBackend() {
  return backendRunner.ensureBackend();
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
  mainWindowController.createWindow();
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
  dashboardNavigation.loadLocalPage(fileName);
}

function clearDashboardLoadRetryTimer() {
  dashboardNavigation.clearDashboardLoadRetryTimer();
}

function resetDashboardLoadRetry() {
  dashboardNavigation.resetDashboardLoadRetry();
}

function scheduleDashboardLoadRetry(reason) {
  dashboardNavigation.scheduleDashboardLoadRetry(reason);
}

// The dashboard renders a full-screen <LoginCard /> whenever there's no valid
// license (see cli/web App.tsx's license gate), so the sign-in screen lives
// inside the app itself. We deliberately do NOT pop a separate native login
// window — that produced two competing sign-in screens stacked on top of each
// other. This just brings the dashboard forward and nudges it to re-check
// license state so the in-app card renders.
function openLoginWindow() {
  dashboardNavigation.openLoginWindow();
}

function loadAppPath(pathname = START_PATH, options = {}) {
  dashboardNavigation.loadAppPath(pathname, options);
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

registerAuthIpc({
  hqBaseUrl: HQ_BASE_URL,
  ipcMain,
  loadAppPath,
  mainWindow: () => mainWindow,
  performLogin,
  setTimeout,
  shell,
  startPath: START_PATH,
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

deepLinks.registerProtocolClient();
deepLinks.registerOpenUrl();

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
  deepLinks.replayPending();
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
