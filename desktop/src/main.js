const { app, BrowserWindow, Menu, dialog, ipcMain, shell } = require("electron");
const { execFileSync, spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");

const PREFERRED_PORT = Number(process.env.ELEVATE_DESKTOP_PORT || 9119);
const HOST = "127.0.0.1";
const HOME = os.homedir();
const START_PATH = process.env.ELEVATE_DESKTOP_START_PATH || "/hub";
const EMBEDDED_CHAT =
  process.env.ELEVATE_DESKTOP_EMBEDDED_CHAT === "1" ||
  process.env.ELEVATE_DASHBOARD_TUI === "1";
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
let backendProcess = null;
let ownsBackend = false;
let installProcess = null;
let backendPort = PREFERRED_PORT;
let backendUrl = `http://${HOST}:${backendPort}`;

app.setName("Elevate");

function repoRoot() {
  return path.resolve(__dirname, "..", "..");
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

async function waitForBackend(timeoutMs = 45000) {
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

  backendProcess = spawn(launcher.command, launcher.args, {
    cwd: launcher.cwd,
    env: envWithPath(EMBEDDED_CHAT ? { ELEVATE_DASHBOARD_TUI: "1" } : {}),
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
        { type: "separator" },
        { label: "Reload", accelerator: "CmdOrCtrl+R", click: () => mainWindow?.reload() },
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

  mainWindow.on("page-title-updated", (event) => {
    event.preventDefault();
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(backendUrl)) {
      return { action: "allow" };
    }
    shell.openExternal(url);
    return { action: "deny" };
  });
}

function loadLocalPage(fileName) {
  if (!mainWindow) return;
  mainWindow.loadFile(path.join(__dirname, fileName));
}

function loadAppPath(pathname = START_PATH) {
  if (!mainWindow) return;
  mainWindow.loadURL(`${backendUrl}${pathname}`);
}

async function startDesktop() {
  createWindow();
  createMenu();
  loadLocalPage("loading.html");

  const ready = await ensureBackend();
  if (ready) {
    loadAppPath(START_PATH);
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

app.whenReady().then(startDesktop);

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    startDesktop();
  }
});

app.on("before-quit", () => {
  if (ownsBackend && backendProcess) {
    backendProcess.kill();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
