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
const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { autoUpdater } = require("electron-updater");
const log = require("electron-log");
const { isTrustedNavigationUrl } = require("./navigation-guard");
const {
  isAllowedAudioPermission,
  requestPermissionOrigin,
} = require("./permission-guard");
const backendHttp = require("./backend-http");
const dashboardBundle = require("./dashboard-bundle");
const desktopMenu = require("./menu");

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

let mainWindow = null;
let overlayWindow = null;
let overlayWatcher = null;
let backendProcess = null;
// Deep link (elevate://…) captured before the main window exists, replayed
// once startup finishes. macOS can fire open-url before app.whenReady().
let pendingDeepLink = null;

// The computer-use tool touches this file on every action. The desktop app
// polls its mtime and shows the screen-edge glow while it is fresh, so the
// user always sees when the agent is driving their Mac.
const COMPUTER_USE_FLAG = path.join(HOME, ".elevate", "computer-use-active");
const COMPUTER_USE_FRESH_MS = 6000;
let ownsBackend = false;
let backendReady = false;
let installProcess = null;
let backendPort = PREFERRED_PORT;
let backendUrl = `http://${HOST}:${backendPort}`;
let dashboardLoadRetryCount = 0;
let dashboardLoadRetryTimer = null;
let lastDashboardPath = START_PATH;
const startupStartedAt = Date.now();
const startupEvents = [];
let startupSummaryLogged = false;

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
  const ms = Date.now() - startupStartedAt;
  const event = { ms, name, detail };
  startupEvents.push(event);
  log.info(`[startup] ${ms}ms ${name}${detail ? ` ${detail}` : ""}`);
}

function finishStartup(reason) {
  if (startupSummaryLogged) return;
  startupSummaryLogged = true;
  const total = Date.now() - startupStartedAt;
  const timeline = startupEvents
    .map((event) => `${event.ms}ms:${event.name}${event.detail ? `(${event.detail})` : ""}`)
    .join(" | ");
  log.info(`[startup-summary] ${reason} ${total}ms ${timeline}`);
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
  const text = String(value ?? "");
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function formatCrashForLog(reason) {
  if (reason && reason.stack) return trimLogMessage(reason.stack, 4000);
  if (reason && reason.message) return trimLogMessage(reason.message, 4000);
  return trimLogMessage(reason, 4000);
}

function installMainCrashCapture() {
  process.on("uncaughtException", (err) => {
    log.error(`[main:uncaughtException] ${formatCrashForLog(err)}`);
    try {
      app.exit(1);
    } catch {
      process.exit(1);
    }
  });

  process.on("unhandledRejection", (reason) => {
    log.error(`[main:unhandledRejection] ${formatCrashForLog(reason)}`);
  });
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
  try {
    const raw = fs.readFileSync(LICENSE_PATH, "utf8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function writeLicense(license) {
  fs.mkdirSync(path.dirname(LICENSE_PATH), { recursive: true });
  fs.writeFileSync(LICENSE_PATH, JSON.stringify(license, null, 2), { mode: 0o600 });
}

function clearLicense() {
  try {
    fs.unlinkSync(LICENSE_PATH);
  } catch {
    // already gone is fine
  }
}

function decodeJwtExp(token) {
  try {
    const payload = token.split(".")[1];
    const json = Buffer.from(payload.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8");
    const claims = JSON.parse(json);
    return Number(claims.exp || 0);
  } catch {
    return 0;
  }
}

function hqJsonRequestHeaders(scope) {
  const requestId = `desktop-${scope}-${crypto.randomUUID()}`;
  log.info(`[desktop:request] request_id=${requestId} scope=${scope}`);
  return {
    requestId,
    headers: {
      "Content-Type": "application/json",
      "X-Request-Id": requestId,
    },
  };
}

async function refreshLicense(license) {
  if (!license || !license.refresh_token) return null;
  const { requestId, headers } = hqJsonRequestHeaders("license-refresh");
  try {
    // Same endpoint the CLI's elevate_cli/license.py refresh() uses, so a
     // session refreshed here is interchangeable with one refreshed by the CLI.
    const res = await fetch(`${HQ_BASE_URL}/api/license/refresh`, {
      method: "POST",
      headers,
      body: JSON.stringify({ refresh_token: license.refresh_token }),
    });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      log.warn(
        `[license] refresh failed request_id=${requestId}: HTTP ${res.status} ${body.slice(0, 200)}`,
      );
      return null;
    }
    const data = await res.json();
    if (!data || !data.access_token || !data.refresh_token) {
      log.warn(`[license] refresh response missing tokens request_id=${requestId}`);
      return null;
    }
    const next = {
      ...license,
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      license_id: data.license_id || license.license_id,
      tier: data.tier || license.tier,
      entitlements: data.entitlements || license.entitlements,
      expires_at: decodeJwtExp(data.access_token),
    };
    writeLicense(next);
    log.info(`[license] refresh succeeded request_id=${requestId}`);
    return next;
  } catch (err) {
    log.warn(`[license] refresh threw request_id=${requestId}: ${err && err.message ? err.message : err}`);
    return null;
  }
}

// Retry wrapper for startup. Transient network failures during app launch
// (DNS not yet warm, VPN reconnecting, HQ briefly slow) used to trigger the
// login popup even though the user had a valid refresh_token on disk. We try
// up to 3 times with short backoff before giving up.
async function refreshLicenseWithRetry(license, attempts = 3) {
  for (let i = 0; i < attempts; i++) {
    const next = await refreshLicense(license);
    if (next) return next;
    if (i < attempts - 1) {
      await new Promise((r) => setTimeout(r, 1000 * (i + 1)));
    }
  }
  return null;
}

// Returns a valid license, refreshing if needed. Returns null if there's no
// usable session. On startup the network may not be fully ready, so refresh
// is retried before we give up and pop the login window.
async function ensureValidLicense({ retry = false } = {}) {
  let license = readLicense();
  if (!license || !license.access_token) return null;

  const expMs = (Number(license.expires_at) || 0) * 1000;
  if (!Number.isFinite(expMs) || Date.now() > expMs - ACCESS_REFRESH_MARGIN_MS) {
    license = retry
      ? await refreshLicenseWithRetry(license)
      : await refreshLicense(license);
  }
  return license;
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
  if (!email || !password) {
    return { ok: false, error: "Email and password are required." };
  }
  const { requestId, headers } = hqJsonRequestHeaders("auth-login");
  try {
    const res = await fetch(`${HQ_BASE_URL}/api/auth/login`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        email: String(email).trim().toLowerCase(),
        password,
        device_label: `Elevate Desktop (${os.hostname()})`,
      }),
    });

    if (res.status === 401) {
      log.warn(`[auth] login rejected request_id=${requestId}: HTTP 401`);
      return { ok: false, error: "Email or password is wrong." };
    }
    if (res.status === 402) {
      log.warn(`[auth] login rejected request_id=${requestId}: HTTP 402`);
      return {
        ok: false,
        error: "Your account has no active subscription. Upgrade in your browser, then sign in.",
      };
    }
    if (!res.ok) {
      const text = await res.text();
      log.warn(`[auth] login failed request_id=${requestId}: HTTP ${res.status} ${text.slice(0, 160)}`);
      return { ok: false, error: `Sign-in failed (${res.status}): ${text.slice(0, 160)}` };
    }

    const data = await res.json();
    const license = {
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      license_id: data.license_id,
      tier: data.tier,
      email: String(email).trim().toLowerCase(),
      expires_at: decodeJwtExp(data.access_token),
      entitlements: data.entitlements || [],
    };
    writeLicense(license);
    log.info(`[auth] login succeeded request_id=${requestId}`);
    return { ok: true, license };
  } catch (err) {
    log.warn(`[auth] login threw request_id=${requestId}: ${err && err.message ? err.message : err}`);
    return {
      ok: false,
      error: `Could not reach ${HQ_BASE_URL}. Check your connection and try again.`,
    };
  }
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
  const idx = launcher.args.indexOf("dashboard");
  const prefix = idx >= 0 ? launcher.args.slice(0, idx) : [];
  const args = [...prefix, "gateway", ...gwArgs];
  return spawnSync(launcher.command, args, {
    cwd: launcher.cwd,
    env: envWithPath({ ...baseEnv, ...(launcher.extraEnv || {}) }),
    timeout: timeoutMs,
    encoding: "utf8",
  });
}

// Records which app version the gateway last (re)started on. Lets us restart it
// exactly once after an update instead of on every launch.
function gatewayVersionMarkerPath() {
  return path.join(os.homedir(), ".elevate", ".gateway_version");
}

function readGatewayVersionMarker() {
  try {
    return fs.readFileSync(gatewayVersionMarkerPath(), "utf8").trim();
  } catch (e) {
    return "";
  }
}

function writeGatewayVersionMarker(version) {
  try {
    fs.mkdirSync(path.join(os.homedir(), ".elevate"), { recursive: true });
    fs.writeFileSync(gatewayVersionMarkerPath(), `${version}\n`, "utf8");
  } catch (e) {
    appendBackendLog(`[gateway] version marker write failed: ${e}\n`);
  }
}

function existingGatewayMissingResource() {
  try {
    const statusPath = path.join(os.homedir(), ".elevate", "gateway_state.json");
    const payload = JSON.parse(fs.readFileSync(statusPath, "utf8"));
    const platforms = payload && typeof payload === "object" ? payload.platforms : null;
    if (!platforms || typeof platforms !== "object") return "";

    for (const [name, state] of Object.entries(platforms)) {
      if (!state || typeof state !== "object") continue;
      const code = String(state.error_code || "");
      if (!code.endsWith("_missing")) continue;
      const message = String(state.error_message || "");
      const marker = " missing at ";
      const idx = message.indexOf(marker);
      if (idx < 0) continue;
      const candidate = message.slice(idx + marker.length).trim().replace(/\.$/, "");
      if (candidate && fileExists(candidate)) {
        return `${name}:${code}:${candidate}`;
      }
    }
  } catch {
    // no status yet, malformed JSON, or unreadable file: not a recovery signal
  }
  return "";
}

// Restart the loaded gateway so it re-execs the freshly-bundled CLI code. A
// desktop auto-update swaps the .app bundle, but the long-lived launchd gateway
// keeps running the OLD code in memory — so the seed/migration path
// (ensure_system_jobs: preinstalled fleet defaults + the sentinel-gated
// fleet-rebuild + heartbeat/automation seeding) never re-applies on update.
// Without this, every updated customer is stuck on their old roster until
// someone restarts the gateway by hand. macOS only.
function kickstartGateway(uid) {
  const res = spawnSync(
    "launchctl",
    ["kickstart", "-k", `gui/${uid}/ai.elevate.gateway`],
    { encoding: "utf8", timeout: 15000 },
  );
  const out = String(res.stdout || res.stderr || "").trim().slice(-300);
  appendBackendLog(`[gateway] kickstart rc=${res.status}\n${out}\n`);
  return res.status === 0;
}

// Probe launchd for the gateway job. Distinguishes:
//   loaded  — `launchctl print gui/$UID/ai.elevate.gateway` finds the job
//   running — the loaded job actually has a pid / "state = running"
// "Could not find service" (not loaded) is exactly what a Squirrel ShipIt
// auto-update left behind on a customer Mac: the gateway got SIGTERM'd and the
// job ended up booted out of the gui domain entirely, so KeepAlive could never
// revive it and Telegram/cron stayed dead until a manual `launchctl bootstrap`.
function probeGateway(uid) {
  try {
    const probe = spawnSync(
      "launchctl",
      ["print", `gui/${uid}/ai.elevate.gateway`],
      { encoding: "utf8", timeout: 8000 },
    );
    const out = String(probe.stdout || "");
    const loaded = probe.status === 0;
    const running =
      loaded && (/\bpid = \d+/.test(out) || /state = running/.test(out));
    return { loaded, running };
  } catch (e) {
    return { loaded: false, running: false };
  }
}

// Last-resort revival that does NOT depend on the Python CLI working: load the
// plist already on disk straight into the gui domain. Covers the case where
// `gateway install` itself fails (e.g. CLI broken mid-update) but a valid
// plist survived in ~/Library/LaunchAgents. bootstrap of an already-loaded
// job fails (EALREADY) — fine, the kickstart then starts a loaded-but-dead one.
function bootstrapGatewayDirect(uid, plist) {
  const bs = spawnSync(
    "launchctl",
    ["bootstrap", `gui/${uid}`, plist],
    { encoding: "utf8", timeout: 15000 },
  );
  appendBackendLog(
    `[gateway] direct bootstrap rc=${bs.status} ${String(bs.stdout || bs.stderr || "").trim().slice(-200)}\n`,
  );
  if (!probeGateway(uid).running) kickstartGateway(uid);
  return probeGateway(uid).running;
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
  if (process.platform !== "darwin") return;
  try {
    const plist = path.join(
      os.homedir(),
      "Library",
      "LaunchAgents",
      "ai.elevate.gateway.plist",
    );
    const uid = typeof process.getuid === "function" ? process.getuid() : "";
    const { loaded, running } = probeGateway(uid);
    const appVersion = app.getVersion();
    if (fileExists(plist) && loaded && !running) {
      // Loaded but dead (no pid): e.g. a stale pre-KeepAlive plist whose
      // process was SIGTERM'd and never revived. kickstart restarts it in
      // place; if that fails fall through to the full install path below.
      appendBackendLog(
        "[gateway] self-heal: loaded but NOT running -> kickstart\n",
      );
      if (kickstartGateway(uid) && probeGateway(uid).running) return;
    } else if (fileExists(plist) && loaded) {
      const lastVersion = readGatewayVersionMarker();
      if (lastVersion !== appVersion) {
        appendBackendLog(
          `[gateway] version change ${lastVersion || "(none)"} -> ${appVersion}; reinstalling to load new code + refresh plist env\n`,
        );
        // Run `gateway install` (not a bare kickstart) so a STALE plist is
        // rewritten + bootout/bootstrapped. Critical: older plists lack
        // PYTHONPYCACHEPREFIX, so the launchd gateway wrote .pyc INTO the signed
        // bundle and broke the codesign seal ("Elevate is damaged"). install →
        // refresh_launchd_plist_if_needed applies the new env; a bare kickstart
        // would just restart under the old (broken) plist. Falls back to
        // kickstart if install fails.
        const reinstall = runGatewayCommand(launcher, baseEnv, ["install"]);
        const rout = String(reinstall.stdout || reinstall.stderr || "").trim().slice(-300);
        appendBackendLog(`[gateway] version-change reinstall rc=${reinstall.status}\n${rout}\n`);
        if (reinstall.status === 0) {
          if (kickstartGateway(uid)) {
            writeGatewayVersionMarker(appVersion);
          }
        } else if (kickstartGateway(uid)) {
          writeGatewayVersionMarker(appVersion);
        }
      } else {
        const missingResource = existingGatewayMissingResource();
        if (missingResource) {
          appendBackendLog(
            `[gateway] self-heal: packaged resource recovered (${missingResource}); reinstalling gateway\n`,
          );
          const reinstall = runGatewayCommand(launcher, baseEnv, ["install"]);
          const rout = String(reinstall.stdout || reinstall.stderr || "").trim().slice(-300);
          appendBackendLog(`[gateway] recovered-resource reinstall rc=${reinstall.status}\n${rout}\n`);
          if (reinstall.status === 0) {
            if (kickstartGateway(uid)) {
              writeGatewayVersionMarker(appVersion);
            }
          } else if (kickstartGateway(uid)) {
            writeGatewayVersionMarker(appVersion);
          }
        } else {
          appendBackendLog(
            "[gateway] self-heal: healthy (plist present + loaded, version current)\n",
          );
        }
      }
      return;
    }
    appendBackendLog(
      `[gateway] self-heal: plist=${fileExists(plist)} loaded=${loaded} running=${running} -> installing\n`,
    );
    // `gateway install` is now load-aware on the CLI side: with a current
    // plist but an unloaded job it re-bootstraps + kickstarts + verifies
    // (instead of the old "Service already installed" no-op).
    const res = runGatewayCommand(launcher, baseEnv, ["install"]);
    const out = String(res.stdout || res.stderr || "").trim().slice(-400);
    appendBackendLog(`[gateway] self-heal install rc=${res.status}\n${out}\n`);
    if (res.status === 0) writeGatewayVersionMarker(appVersion);
    // Belt-and-suspenders: verify the job actually came back. If `gateway
    // install` could not (broken/missing CLI mid-update) but a plist file
    // exists on disk, load it directly — no Python required.
    if (!probeGateway(uid).running && fileExists(plist)) {
      appendBackendLog(
        "[gateway] self-heal: install did not yield a running job; direct launchctl bootstrap fallback\n",
      );
      const revived = bootstrapGatewayDirect(uid, plist);
      appendBackendLog(
        `[gateway] self-heal: direct bootstrap ${revived ? "revived the gateway" : "FAILED — gateway still down"}\n`,
      );
    }
  } catch (e) {
    appendBackendLog(`[gateway] self-heal error: ${e}\n`);
  }
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
  // Reusing the existing overlay avoids leaking a window each time the
  // desktop is (re)started.
  if (overlayWindow && !overlayWindow.isDestroyed()) return;
  // A frameless, transparent, click-through window that draws a pulsing glow
  // around the screen while the computer-use tool is active. It floats above
  // everything (including full-screen apps) and never steals focus or clicks.
  const display = screen.getPrimaryDisplay();
  const { x, y, width, height } = display.bounds;
  overlayWindow = new BrowserWindow({
    x,
    y,
    width,
    height,
    show: false,
    frame: false,
    transparent: true,
    hasShadow: false,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    focusable: false,
    skipTaskbar: true,
    acceptFirstMouse: false,
    enableLargerThanScreen: true,
    backgroundColor: "#00000000",
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  overlayWindow.setIgnoreMouseEvents(true, { forward: true });
  overlayWindow.setAlwaysOnTop(true, "screen-saver");
  if (process.platform === "darwin") {
    overlayWindow.setVisibleOnAllWorkspaces(true, {
      visibleOnFullScreen: true,
    });
  }
  overlayWindow.loadFile(path.join(__dirname, "overlay.html"));
  overlayWindow.on("closed", () => {
    overlayWindow = null;
  });
}

function setOverlayVisible(visible) {
  if (visible) {
    createOverlay();
  }
  if (!overlayWindow || overlayWindow.isDestroyed()) return;
  if (visible && !overlayWindow.isVisible()) {
    const { x, y, width, height } = screen.getPrimaryDisplay().bounds;
    overlayWindow.setBounds({ x, y, width, height });
    overlayWindow.showInactive();
  } else if (!visible) {
    overlayWindow.destroy();
    overlayWindow = null;
  }
}

function startOverlayWatcher() {
  if (overlayWatcher) return;
  overlayWatcher = setInterval(() => {
    let fresh = false;
    try {
      const stat = fs.statSync(COMPUTER_USE_FLAG);
      fresh = Date.now() - stat.mtimeMs < COMPUTER_USE_FRESH_MS;
    } catch {
      fresh = false;
    }
    setOverlayVisible(fresh);
  }, 1000);
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

// Grant microphone access to the in-app voice-input feature. Without an
// explicit handler some Electron builds deny `media` requests, which makes
// getUserMedia (used by the chat composer's voice button) fail silently.
// macOS still gates the device behind its own TCC prompt — backed by the
// NSMicrophoneUsageDescription string Electron ships in Info.plist.
function setupPermissions() {
  const ses = session.defaultSession;
  if (!ses) return;
  ses.setPermissionRequestHandler((_webContents, permission, callback, details = {}) => {
    callback(
      isAllowedAudioPermission(
        permission,
        requestPermissionOrigin(details),
        details,
        backendUrl,
      ),
    );
  });
  // Only auto-pass the getUserMedia pre-flight; deny every other permission
  // check (geolocation, clipboard-read, MIDI, notifications, …) instead of the
  // previous blanket allow.
  ses.setPermissionCheckHandler((_webContents, permission, requestingOrigin, details = {}) => {
    return isAllowedAudioPermission(
      permission,
      requestingOrigin || details.securityOrigin || details.requestingUrl,
      details,
      backendUrl,
    );
  });
  // Defense-in-depth CSP for the local dashboard origin: a renderer XSS has no
  // 'self' backstop without this. The dashboard already serves only its own
  // bundled assets, so script-src 'self' is safe.
  ses.webRequest.onHeadersReceived((details, callback) => {
    const isFilePreview = (() => {
      try {
        return new URL(details.url).pathname === "/api/files/preview";
      } catch {
        return false;
      }
    })();
    const frameAncestors = isFilePreview ? "'self'" : "'none'";
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        // Permissive on passive resources (styles/fonts/images — the app loads
        // Google Fonts + data/blob) so this can't break rendering; strict where
        // it matters: no plugins/embeds, no external framing, scripts only
        // from self + localhost (+ inline, which the bundled app needs).
        // File previews are the one same-origin frame: PDF artifacts need the
        // local inline viewer to load /api/files/preview directly.
        "Content-Security-Policy": [
          "default-src 'self' data: blob: http://127.0.0.1:* http://localhost:*; " +
            "script-src 'self' 'unsafe-inline' http://127.0.0.1:* http://localhost:*; " +
            "style-src 'self' 'unsafe-inline' https: data:; " +
            "font-src 'self' https: data:; " +
            "img-src 'self' data: blob: https: http://127.0.0.1:* http://localhost:*; " +
            "connect-src 'self' ws: wss: http://127.0.0.1:* http://localhost:* https:; " +
            "frame-src 'self' blob: http://127.0.0.1:* http://localhost:*; " +
            `object-src 'none'; frame-ancestors ${frameAncestors}`,
        ],
      },
    });
  });
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
  if (installProcess) {
    return { ok: false, message: "Install is already running." };
  }

  const npx = findCommand("npx");
  if (!npx) {
    return { ok: false, message: "npx was not found. Install Node.js first, then retry." };
  }

  installProcess = spawn(
    npx,
    ["--yes", "github:Dartagnan98/elevate-agent", "install", "--skip-setup"],
    {
      cwd: os.homedir(),
      env: envWithPath(),
      stdio: ["ignore", "pipe", "pipe"],
    },
  );

  installProcess.stdout.on("data", appendBackendLog);
  installProcess.stderr.on("data", appendBackendLog);
  installProcess.on("exit", async (code) => {
    installProcess = null;
    if (code === 0 && mainWindow) {
      const ready = await ensureBackend();
      if (ready) {
        loadAppPath(START_PATH);
        return;
      }
      loadLocalPage("install.html");
      dialog.showErrorBox("Elevate install failed", "The installer finished, but Elevate was still not ready. Check the terminal logs and try again.");
    } else if (mainWindow) {
      dialog.showErrorBox("Elevate install failed", "The installer exited before Elevate was ready. Check the terminal logs and try again.");
    }
  });

  return { ok: true, message: "Install started." };
}

ipcMain.handle("desktop:retry", async () => {
  loadLocalPage("loading.html");
  const ready = await ensureBackend();
  if (ready) {
    loadAppPath(START_PATH);
    return { ok: true };
  }
  loadLocalPage("install.html");
  return { ok: false };
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
// Skipped in dev (running from `npm start` rather than a packaged build) — the
// updater throws "no app-update.yml" without a real install.
let updateState = { status: "idle", info: null, progress: null, error: null };
let updateCheckInFlight = false;
const updateBusyStatuses = new Set(["checking", "available", "downloading", "ready"]);
const UPDATE_CONFIG_PATH = path.join(process.resourcesPath, "app-update.yml");

function broadcastUpdaterEvent(payload) {
  updateState = { ...updateState, ...payload };
  // The floating "update available" toast window was removed — the in-app
  // update card (App.tsx, fed by these same events) is the single update UI.
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("updater:event", updateState);
  }
}

async function runUpdaterCheck(reason) {
  if (app.isPackaged && !fs.existsSync(UPDATE_CONFIG_PATH)) {
    const message = "update metadata is not bundled";
    log.warn(`[updater] skip check (${reason}) — ${message}`);
    broadcastUpdaterEvent({ status: "error", info: null, progress: null, error: message });
    return { ok: false, message };
  }

  if (updateCheckInFlight || updateBusyStatuses.has(updateState.status)) {
    const message = updateCheckInFlight
      ? "a check is already in flight"
      : `update already ${updateState.status}`;
    log.info(`[updater] skip check (${reason}) — ${message}`);
    return { ok: true, skipped: true, message };
  }

  updateCheckInFlight = true;
  try {
    log.info(`[updater] checking for updates (${reason})`);
    const result = await autoUpdater.checkForUpdates();
    return {
      ok: true,
      version: result && result.updateInfo ? result.updateInfo.version : null,
    };
  } catch (err) {
    const message = err && err.message ? err.message : String(err);
    log.warn(`[updater] check failed (${reason}): ${message}`);
    broadcastUpdaterEvent({ status: "error", error: message });
    return { ok: false, message };
  } finally {
    updateCheckInFlight = false;
  }
}

autoUpdater.on("checking-for-update", () => {
  broadcastUpdaterEvent({ status: "checking", error: null });
});
autoUpdater.on("update-available", (info) => {
  broadcastUpdaterEvent({ status: "available", info, error: null });
});
autoUpdater.on("update-not-available", (info) => {
  broadcastUpdaterEvent({ status: "current", info, error: null });
});
autoUpdater.on("download-progress", (progress) => {
  broadcastUpdaterEvent({ status: "downloading", progress, error: null });
});
autoUpdater.on("update-downloaded", (info) => {
  broadcastUpdaterEvent({ status: "ready", info, progress: null, error: null });
});
autoUpdater.on("error", (err) => {
  broadcastUpdaterEvent({
    status: "error",
    error: err && err.message ? err.message : String(err),
  });
});

function kickoffUpdates() {
  if (!app.isPackaged) {
    log.info("[updater] skipped in development build");
    return;
  }

  runUpdaterCheck("startup");
  // Poll frequently so a freshly-shipped build reaches the device within
  // minutes. autoDownload pulls it silently; the user still applies it via the
  // one-click "Restart to update" card — no auto-relaunch, no forced install.
  const timer = setInterval(() => runUpdaterCheck("poll"), 3 * 60 * 1000);
  if (typeof timer.unref === "function") timer.unref();
  // Also check the instant the app regains focus, so an update that shipped
  // while you were away shows up right when you come back. Debounced so rapid
  // focus changes don't hammer the feed.
  let lastFocusCheck = 0;
  app.on("browser-window-focus", () => {
    const now = Date.now();
    if (now - lastFocusCheck < 60 * 1000) return;
    lastFocusCheck = now;
    runUpdaterCheck("focus");
  });
}

// Renderer can ask "what's the latest status?" on mount so it doesn't miss
// events that fired before the listener was attached.
ipcMain.handle("updater:status", () => updateState);

// Renderer fires this when the user clicks "Restart to update".
ipcMain.handle("updater:install", () => {
  if (updateState.status !== "ready") {
    return { ok: false, message: "Update is not ready yet." };
  }
  // setImmediate so the IPC reply is sent before quit kicks in.
  setImmediate(() => {
    try {
      autoUpdater.quitAndInstall(false, true);
    } catch (err) {
      const message = err && err.message ? err.message : String(err);
      log.warn(`[updater] install failed: ${message}`);
      broadcastUpdaterEvent({ status: "error", error: message });
    }
  });
  return { ok: true };
});

// Manual "check now" button (useful from a Help menu).
ipcMain.handle("updater:check", async () => {
  if (!app.isPackaged) {
    return { ok: false, message: "Updates only run in packaged builds." };
  }
  return runUpdaterCheck("manual");
});

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

// ── SMS outbox: deliver approved SMS from the FOREGROUND app ──────────────────
// The headless backend can't get macOS Automation→Messages, so it can't run
// `imsg`. This GUI process can (entitlement + one-time "control Messages"
// prompt). The backend drops a <id>.req.json into ~/.elevate/sms-outbox/ with
// {to,text,service}; we run imsg here and write <id>.res.json with the result.
// See cli/docs/mac-sms-transport.md.
let smsImsgPath = null;
function resolveImsg() {
  if (smsImsgPath !== null) return smsImsgPath;
  const candidates = ["/opt/homebrew/bin/imsg", "/usr/local/bin/imsg"];
  for (const c of candidates) {
    try { if (fs.existsSync(c)) { smsImsgPath = c; return c; } } catch {}
  }
  try {
    const found = execFileSync("/usr/bin/env", ["bash", "-lc", "command -v imsg"], {
      encoding: "utf8",
    }).trim();
    smsImsgPath = found || "";
  } catch { smsImsgPath = ""; }
  return smsImsgPath;
}

// Restart Messages.app — it wedges under repeated sends (AppleEvent timed out
// -1712), which is the single biggest reliability hole in Mac SMS. A quit+reopen
// reliably clears it. Returns a promise that resolves after Messages is back.
function restartMessages() {
  return new Promise((resolve) => {
    try { execFileSync("/usr/bin/killall", ["Messages"]); } catch {}
    setTimeout(() => {
      try { spawn("/usr/bin/open", ["-g", "-a", "Messages"], { stdio: "ignore" }); } catch {}
      setTimeout(resolve, 4000);
    }, 1500);
  });
}

function startSmsOutboxWatcher() {
  const dir = path.join(os.homedir(), ".elevate", "sms-outbox");
  try { fs.mkdirSync(dir, { recursive: true }); } catch {}
  const inFlight = new Set();

  // Run one imsg send; resolves {ok, code, stdout, error}. Hang -> killed at 30s.
  const runImsg = (imsg, args) => new Promise((resolve) => {
    const child = spawn(imsg, args, { stdio: ["ignore", "pipe", "pipe"] });
    let out = "", err = "", done = false;
    const finish = (r) => { if (!done) { done = true; resolve(r); } };
    const killer = setTimeout(() => { try { child.kill("SIGKILL"); } catch {} finish({ ok: false, code: null, error: "imsg timed out (Messages wedged?)" }); }, 30000);
    child.stdout.on("data", (d) => { out += d; });
    child.stderr.on("data", (d) => { err += d; });
    child.on("close", (code) => { clearTimeout(killer); finish({ ok: code === 0, code, stdout: out.slice(-500), error: code === 0 ? null : (err || out).slice(-300) }); });
    child.on("error", (e) => { clearTimeout(killer); finish({ ok: false, code: null, error: String(e).slice(-300) }); });
  });

  const drain = async () => {
    let files;
    try { files = fs.readdirSync(dir); } catch { return; }
    for (const f of files) {
      if (!f.endsWith(".req.json") || inFlight.has(f)) continue;
      inFlight.add(f);
      const id = f.slice(0, -".req.json".length);
      const reqPath = path.join(dir, f);
      const resPath = path.join(dir, `${id}.res.json`);
      let req;
      try { req = JSON.parse(fs.readFileSync(reqPath, "utf8")); }
      catch { try { fs.unlinkSync(reqPath); } catch {} inFlight.delete(f); continue; }
      // Remove the request first so a crash can't reprocess/duplicate a send.
      try { fs.unlinkSync(reqPath); } catch {}
      const writeRes = (obj) => {
        try { const tmp = `${resPath}.tmp`; fs.writeFileSync(tmp, JSON.stringify(obj)); fs.renameSync(tmp, resPath); } catch {}
        inFlight.delete(f);
      };
      const imsg = resolveImsg();
      if (!imsg) { writeRes({ ok: false, error: "imsg not installed" }); continue; }
      const svc = String(req.service || "sms").toLowerCase() === "imessage" ? "imessage" : "sms";
      const args = ["send", "--to", String(req.to || ""), "--text", String(req.text || ""), "--service", svc, "--json"];
      let res = await runImsg(imsg, args);
      // Self-heal: if it hung/failed, Messages is likely wedged — restart it and
      // retry ONCE. This is what made every "it stopped working" recover today.
      if (!res.ok) {
        log.warn("[sms-outbox] send failed, restarting Messages + retrying:", res.error);
        await restartMessages();
        res = await runImsg(imsg, args);
      }
      writeRes(res);
    }
  };
  setInterval(() => { drain().catch(() => {}); }, 1500);
  log.info("[sms-outbox] watcher started:", dir);
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
  if (overlayWatcher) {
    clearInterval(overlayWatcher);
    overlayWatcher = null;
  }
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.destroy();
  }
  if (ownsBackend && backendProcess) {
    backendProcess.kill();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
