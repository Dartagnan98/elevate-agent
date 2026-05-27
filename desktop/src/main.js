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
const { execFileSync, spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const { autoUpdater } = require("electron-updater");
const log = require("electron-log");

// Send autoUpdater logs to a file so we can debug what the user saw.
// Tail with: tail -f ~/Library/Logs/Elevate/main.log
log.transports.file.level = "info";
autoUpdater.logger = log;
autoUpdater.autoDownload = true; // download in background as soon as available
autoUpdater.autoInstallOnAppQuit = true; // safety net if user ignores the toast

const PREFERRED_PORT = Number(process.env.ELEVATE_DESKTOP_PORT || 9119);
const HOST = "127.0.0.1";
const HOME = os.homedir();
const START_PATH = process.env.ELEVATE_DESKTOP_START_PATH || "/hub";
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
let updateToastWindow = null;
let loginWindow = null;

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

app.setName("Elevate");

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

async function refreshLicense(license) {
  if (!license || !license.refresh_token) return null;
  try {
    // Same endpoint the CLI's elevate_cli/license.py refresh() uses, so a
     // session refreshed here is interchangeable with one refreshed by the CLI.
    const res = await fetch(`${HQ_BASE_URL}/api/license/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: license.refresh_token }),
    });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      console.warn(`[license] refresh failed: HTTP ${res.status} ${body.slice(0, 200)}`);
      return null;
    }
    const data = await res.json();
    if (!data || !data.access_token || !data.refresh_token) {
      console.warn("[license] refresh response missing tokens");
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
    return next;
  } catch (err) {
    console.warn(`[license] refresh threw: ${err && err.message ? err.message : err}`);
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
  try {
    const res = await fetch(`${HQ_BASE_URL}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: String(email).trim().toLowerCase(),
        password,
        device_label: `Elevate Desktop (${os.hostname()})`,
      }),
    });

    if (res.status === 401) {
      return { ok: false, error: "Email or password is wrong." };
    }
    if (res.status === 402) {
      return {
        ok: false,
        error: "Your account has no active subscription. Upgrade in your browser, then sign in.",
      };
    }
    if (!res.ok) {
      const text = await res.text();
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
    return { ok: true, license };
  } catch (err) {
    return {
      ok: false,
      error: `Could not reach ${HQ_BASE_URL}. Check your connection and try again.`,
    };
  }
}

function envWithPath(extra = {}) {
  return {
    ...process.env,
    PATH: process.env.PATH ? `${DEFAULT_PATH}:${process.env.PATH}` : DEFAULT_PATH,
    ...extra,
  };
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
      return {
        command: bundledPython,
        args: ["-m", "elevate_cli.main", ...dashboardArgs],
        cwd: bundledCli,
        extraEnv: {
          PYTHONPATH: bundledCli,
          PYTHONNOUSERSITE: "1",
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

function request(pathname, timeoutMs = 2000, port = backendPort) {
  return new Promise((resolve) => {
    const req = http.get(
      {
        host: HOST,
        port,
        path: pathname,
        timeout: timeoutMs,
      },
      (res) => {
        res.resume();
        resolve(res.statusCode || 0);
      },
    );
    req.on("timeout", () => {
      req.destroy();
      resolve(0);
    });
    req.on("error", () => resolve(0));
  });
}

function requestText(pathname, timeoutMs = 2000, port = backendPort) {
  return new Promise((resolve) => {
    let body = "";
    const req = http.get(
      {
        host: HOST,
        port,
        path: pathname,
        timeout: timeoutMs,
      },
      (res) => {
        res.setEncoding("utf8");
        res.on("data", (chunk) => {
          body += chunk;
          if (body.length > 1024 * 1024) req.destroy();
        });
        res.on("end", () => resolve(body));
      },
    );
    req.on("timeout", () => {
      req.destroy();
      resolve("");
    });
    req.on("error", () => resolve(""));
  });
}

async function backendIsReady(port = backendPort) {
  const status = await request("/api/status", 2000, port);
  return status >= 200 && status < 500;
}

async function dashboardChatEnabled(port = backendPort) {
  const html = await requestText("/", 2000, port);
  return html.includes("window.__ELEVATE_DASHBOARD_EMBEDDED_CHAT__=true");
}

async function backendMatchesDesktopMode(port = backendPort) {
  if (!(await backendIsReady(port))) return false;
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

async function chooseBackendPort() {
  if (await backendMatchesDesktopMode(PREFERRED_PORT)) {
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

async function ensureBackend() {
  await chooseBackendPort();

  if (await backendMatchesDesktopMode()) {
    return true;
  }

  const launcher = resolveElevateLauncher();
  if (!launcher) {
    return false;
  }

  const baseEnv = EMBEDDED_CHAT ? { ELEVATE_DASHBOARD_TUI: "1" } : {};
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

  return waitForBackend();
}

function createMenu() {
  const template = [
    {
      label: "Elevate",
      submenu: [
        { role: "about" },
        { type: "separator" },
        {
          label: "Sign In...",
          accelerator: "CmdOrCtrl+L",
          click: () => openLoginWindow(),
        },
        {
          label: "Account...",
          click: () => shell.openExternal(`${HQ_BASE_URL}/account`),
        },
        {
          label: "Sign Out",
          click: () => {
            clearLicense();
            if (mainWindow && !mainWindow.isDestroyed()) {
              // Reload so the chat WebSocket reconnects and now sees no
              // license — the sign-in banner will render in the chat pane.
              loadAppPath(START_PATH);
            }
          },
        },
        { type: "separator" },
        {
          label: "Quit Elevate",
          accelerator: "CmdOrCtrl+Q",
          click: () => app.quit(),
        },
      ],
    },
    {
      label: "Edit",
      submenu: [
        { role: "undo" },
        { role: "redo" },
        { type: "separator" },
        { role: "cut" },
        { role: "copy" },
        { role: "paste" },
        { role: "pasteAndMatchStyle" },
        { role: "delete" },
        { role: "selectAll" },
      ],
    },
    {
      label: "Navigate",
      submenu: [
        { label: "Chat", accelerator: "CmdOrCtrl+1", click: () => loadAppPath("/chat") },
        { label: "Agent Hub", accelerator: "CmdOrCtrl+2", click: () => loadAppPath("/hub") },
        { label: "Setup", accelerator: "CmdOrCtrl+3", click: () => loadAppPath("/desktop-setup") },
        { label: "Tasks", accelerator: "CmdOrCtrl+4", click: () => loadAppPath("/tasks") },
        { label: "Memory", accelerator: "CmdOrCtrl+5", click: () => loadAppPath("/memory") },
      ],
    },
    {
      label: "Window",
      submenu: [
        { role: "minimize" },
        { role: "zoom" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    {
      label: "Help",
      submenu: [
        {
          label: "Open Dashboard In Browser",
          click: () => shell.openExternal(backendUrl),
        },
        {
          label: "Toggle Developer Tools",
          accelerator: "Alt+CmdOrCtrl+I",
          click: () => mainWindow?.webContents.toggleDevTools(),
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 980,
    minHeight: 680,
    title: "Elevate",
    backgroundColor: "#1a1b1a",
    show: false,
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
    trafficLightPosition:
      process.platform === "darwin" ? { x: 14, y: 18 } : undefined,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
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

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(backendUrl)) {
      return { action: "allow" };
    }
    shell.openExternal(url);
    return { action: "deny" };
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
  if (!overlayWindow || overlayWindow.isDestroyed()) return;
  if (visible && !overlayWindow.isVisible()) {
    const { x, y, width, height } = screen.getPrimaryDisplay().bounds;
    overlayWindow.setBounds({ x, y, width, height });
    overlayWindow.showInactive();
  } else if (!visible && overlayWindow.isVisible()) {
    overlayWindow.hide();
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
  mainWindow.loadFile(path.join(__dirname, fileName));
}

// Pops the login form in a small floating window (instead of swapping the
// main window) so the dashboard stays put underneath. The auth:login IPC
// handler closes this window and reloads the dashboard on success.
function openLoginWindow() {
  // Nudge the dashboard renderer to re-check /api/license/status. Without
  // this the SidebarUserPill can sit with stale "signed in as foo" state
  // (loaded earlier in the session) while we pop the modal because the
  // license file was cleared out from under it. The pill seeing the same
  // 401 and rendering "Not signed in" makes the modal experience make sense.
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents
      .executeJavaScript(
        "window.dispatchEvent(new Event('elevate:auth-changed'));",
        true,
      )
      .catch(() => {});
  }
  if (loginWindow && !loginWindow.isDestroyed()) {
    loginWindow.focus();
    return;
  }
  loginWindow = new BrowserWindow({
    width: 460,
    height: 560,
    resizable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    title: "Sign in to Elevate",
    backgroundColor: "#1a1b1a",
    parent: mainWindow || undefined,
    modal: false,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  loginWindow.once("ready-to-show", () => {
    loginWindow.show();
  });
  loginWindow.on("closed", () => {
    loginWindow = null;
  });
  loginWindow.loadFile(path.join(__dirname, "login.html"));
}

function loadAppPath(pathname = START_PATH) {
  if (!mainWindow) return;
  mainWindow.loadURL(`${backendUrl}${pathname}`);
}

// Grant microphone access to the in-app voice-input feature. Without an
// explicit handler some Electron builds deny `media` requests, which makes
// getUserMedia (used by the chat composer's voice button) fail silently.
// macOS still gates the device behind its own TCC prompt — backed by the
// NSMicrophoneUsageDescription string Electron ships in Info.plist.
function setupPermissions() {
  const ses = session.defaultSession;
  if (!ses) return;
  ses.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(permission === "media" || permission === "audioCapture");
  });
  // The dashboard is a local, trusted origin. Keep the permission check
  // permissive so getUserMedia's pre-flight passes without tightening any
  // other permission the app already relied on.
  ses.setPermissionCheckHandler(() => true);
}

async function startDesktop() {
  setupPermissions();
  createWindow();
  createMenu();
  createOverlay();
  startOverlayWatcher();
  loadLocalPage("loading.html");

  const ready = await ensureBackend();
  backendReady = ready;
  if (ready) {
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
      if (ready) loadAppPath(START_PATH);
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
    // Close the floating login window (if this came from one) and reload the
    // dashboard so the chat WebSocket reopens and picks up the new license.
    setTimeout(() => {
      if (loginWindow && !loginWindow.isDestroyed()) {
        loginWindow.close();
        loginWindow = null;
      }
      if (mainWindow && !mainWindow.isDestroyed()) {
        loadAppPath(START_PATH);
      }
    }, 250);
  }
  return result;
});

ipcMain.handle("auth:status", async () => {
  const license = await ensureValidLicense();
  if (!license) return { signedIn: false };
  return {
    signedIn: true,
    email: license.email,
    tier: license.tier,
    license_id: license.license_id,
    expires_at: license.expires_at,
  };
});

ipcMain.handle("auth:logout", async () => {
  clearLicense();
  loadLocalPage("login.html");
  return { ok: true };
});

// Routes the login page's "Forgot?" / "Create account" / "Use a code" links
// out to the user's default browser. Hard-coded to the HQ origin so a
// compromised renderer can't open arbitrary URLs.
ipcMain.handle("auth:open-external", async (_event, target) => {
  const paths = {
    forgot: "/forgot",
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
//   1. App boots → checkForUpdates() hits the GitHub release feed.
//   2. If a newer version is found, autoDownload=true pulls the zip silently.
//   3. We forward every event to the renderer via `updater:event` so the toast
//      UI can show progress / "restart to update".
//   4. User clicks Restart → quitAndInstall() swaps the binary and relaunches.
//   5. We also re-check every 2 hours while the app is running.
//
// Skipped in dev (running from `npm start` rather than a packaged build) — the
// updater throws "no app-update.yml" without a real install.
let updateState = { status: "idle", info: null, progress: null, error: null };

// "checking" and "current" stay silent so the toast doesn't flash on every poll.
const TOAST_VISIBLE_STATES = new Set([
  "available",
  "downloading",
  "ready",
  "error",
]);
// Once the user hits "Later", suppress re-pops for everything *except* a
// transition into "ready" — that's a new ask (restart now) worth nagging.
let toastDismissedFor = null; // status string the user dismissed under

function broadcastUpdaterEvent(payload) {
  const prevStatus = updateState.status;
  updateState = { ...updateState, ...payload };
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("updater:event", updateState);
  }
  if (updateToastWindow && !updateToastWindow.isDestroyed()) {
    updateToastWindow.webContents.send("updater:event", updateState);
  }
  // Reset suppression when we enter "ready" so the user always sees that ask.
  if (updateState.status === "ready" && prevStatus !== "ready") {
    toastDismissedFor = null;
  }
  if (
    TOAST_VISIBLE_STATES.has(updateState.status) &&
    toastDismissedFor !== updateState.status
  ) {
    showUpdateToast();
  }
}

function createUpdateToast() {
  if (updateToastWindow && !updateToastWindow.isDestroyed()) return;
  const display = screen.getPrimaryDisplay();
  const { x, y, width, height } = display.workArea;
  // Bottom-right corner, with a small inset off the screen edge.
  const w = 340;
  const h = 150;
  const margin = 16;
  updateToastWindow = new BrowserWindow({
    width: w,
    height: h,
    x: x + width - w - margin,
    y: y + height - h - margin,
    show: false,
    frame: false,
    transparent: true,
    hasShadow: false,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    focusable: false,
    backgroundColor: "#00000000",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  updateToastWindow.setAlwaysOnTop(true, "floating");
  if (process.platform === "darwin") {
    updateToastWindow.setVisibleOnAllWorkspaces(true, {
      visibleOnFullScreen: true,
    });
  }
  updateToastWindow.loadFile(path.join(__dirname, "update-toast.html"));
  updateToastWindow.on("closed", () => {
    updateToastWindow = null;
  });
}

function showUpdateToast() {
  createUpdateToast();
  if (!updateToastWindow) return;
  if (!updateToastWindow.isVisible()) {
    updateToastWindow.showInactive();
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
  // Auto-update disabled until the Mac build is signed with a Developer ID +
  // shipped through a real publish channel. Without signing, electron-updater
  // downloads the new bundle but macOS refuses the cert-mismatched swap, so
  // the popup just confuses users. Clients install updates manually for now.
  log.info("[updater] disabled — manual updates only (no Developer ID signing yet)");
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
  setImmediate(() => autoUpdater.quitAndInstall(false, true));
  return { ok: true };
});

// Toast clicked "Later" — hide window + remember the current state so
// background events (download-progress) don't re-pop it.
ipcMain.handle("updater:dismiss-toast", () => {
  toastDismissedFor = updateState.status;
  if (updateToastWindow && !updateToastWindow.isDestroyed()) {
    updateToastWindow.hide();
  }
  return { ok: true };
});

// Manual "check now" button (useful from a Help menu).
ipcMain.handle("updater:check", async () => {
  if (!app.isPackaged) {
    return { ok: false, message: "Updates only run in packaged builds." };
  }
  try {
    const result = await autoUpdater.checkForUpdates();
    return { ok: true, version: result && result.updateInfo ? result.updateInfo.version : null };
  } catch (err) {
    return { ok: false, message: err && err.message ? err.message : String(err) };
  }
});

app.whenReady().then(async () => {
  await startDesktop();
  kickoffUpdates();
});

app.on("activate", () => {
  // The hidden overlay window keeps the app alive after the main window is
  // closed, so BrowserWindow.getAllWindows() is never empty — track the
  // main window explicitly instead.
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
