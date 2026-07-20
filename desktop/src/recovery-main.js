"use strict";

const { app, BrowserWindow, ipcMain } = require("electron");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { autoUpdater } = require("electron-updater");
const log = require("electron-log");

const { quiesceBetaGateway } = require("./recovery-containment");
const { applyElectronProfile, BETA, resolveRuntimePaths } = require("./release-profile");
const { createUpdaterController } = require("./updater");

const packageMetadata = require("../package.json");
if (packageMetadata.elevateRecoveryMode !== true
    || packageMetadata.elevateReleaseChannel !== "beta") {
  throw new Error("The recovery entrypoint may run only from a bound Beta recovery package.");
}

const home = os.homedir();
const paths = resolveRuntimePaths({ profile: BETA, home, env: process.env });
applyElectronProfile({ app, fs, profile: BETA, paths });
process.env.ELEVATE_RELEASE_CHANNEL = "beta";
process.env.ELEVATE_HOME = paths.elevateHome;

log.transports.file.level = "info";
autoUpdater.logger = log;
autoUpdater.autoDownload = true;
autoUpdater.autoInstallOnAppQuit = false;
autoUpdater.disableDifferentialDownload = true;

let mainWindow = null;
let containmentState = Object.freeze({
  ok: false,
  status: "verifying",
  error: "",
  profilePreserved: true,
});

const updater = createUpdaterController({
  app,
  autoUpdater,
  fs,
  ipcMain,
  log,
  mainWindow: () => mainWindow,
  packagedChannel: "beta",
  stateRoot: paths.elevateHome,
});

ipcMain.handle("recovery:containment", () => containmentState);

function installNavigationGuards(webContents, recoveryUrl) {
  webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  webContents.on("will-navigate", (event, targetUrl) => {
    if (targetUrl !== recoveryUrl) event.preventDefault();
  });
  webContents.on("will-redirect", (event) => event.preventDefault());
}

function createRecoveryWindow() {
  const recoveryPath = path.join(__dirname, "recovery.html");
  const recoveryUrl = pathToFileURL(recoveryPath).href;
  mainWindow = new BrowserWindow({
    width: 760,
    height: 600,
    minWidth: 640,
    minHeight: 520,
    title: "Elevate Beta Recovery",
    backgroundColor: "#0c1017",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, "recovery-preload.js"),
    },
  });
  mainWindow.removeMenu();
  installNavigationGuards(mainWindow.webContents, recoveryUrl);
  mainWindow.loadFile(recoveryPath);
  mainWindow.on("closed", () => { mainWindow = null; });
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
  app.whenReady().then(async () => {
    try {
      const containment = await quiesceBetaGateway({ home });
      containmentState = Object.freeze({
        ok: true,
        status: "contained",
        error: "",
        profilePreserved: containment.profilePreserved === true,
        plistPreserved: containment.plistPreserved === true,
        actorsStopped: containment.killed.length,
      });
      log.info(`[recovery] quiesced ${containment.service}; preserved ${containment.profileRoot}`);
    } catch (error) {
      containmentState = Object.freeze({
        ok: false,
        status: "blocked",
        error: error?.message || String(error),
        profilePreserved: true,
      });
      log.error(`[recovery] ${containmentState.error}`);
    }
    if (containmentState.ok) {
      updater.registerAutoUpdaterEvents();
      updater.registerIpcHandlers();
    }
    createRecoveryWindow();
    if (containmentState.ok) updater.kickoffUpdates();
  });
  app.on("activate", () => { if (!mainWindow) createRecoveryWindow(); });
  app.on("window-all-closed", () => app.quit());
}

module.exports = { installNavigationGuards };
