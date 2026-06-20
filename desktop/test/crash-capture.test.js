const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const mainPath = path.resolve(__dirname, "../src/main.js");
const mainWindowPath = path.resolve(__dirname, "../src/main-window.js");
const startupLogPath = path.resolve(__dirname, "../src/startup-log.js");

function readMain() {
  return fs.readFileSync(mainPath, "utf8");
}

function readStartupLog() {
  return fs.readFileSync(startupLogPath, "utf8");
}

test("main process crash handlers write supportable log breadcrumbs", () => {
  const main = readMain();
  const startupLog = readStartupLog();

  assert.match(main, /function formatCrashForLog\(reason\)/);
  assert.match(main, /installMainCrashCapture\(\{\s*app,\s*log,\s*formatCrashForLog\s*\}\)/);
  assert.match(main, /installMainCrashCapture\(\);\s*markStartup\("main:module-loaded"\);/);
  assert.match(startupLog, /reason && reason\.stack/);
  assert.match(startupLog, /process\.on\("uncaughtException",\s*\(err\) =>/);
  assert.match(startupLog, /\[main:uncaughtException\]/);
  assert.match(startupLog, /app\.exit\(1\)/);
  assert.match(startupLog, /process\.on\("unhandledRejection",\s*\(reason\) =>/);
  assert.match(startupLog, /\[main:unhandledRejection\]/);
});

test("renderer crash and hang states write supportable log breadcrumbs", () => {
  const mainWindow = fs.readFileSync(mainWindowPath, "utf8");

  assert.match(mainWindow, /webContents\.on\("render-process-gone"/);
  assert.match(mainWindow, /\[renderer:gone\]/);
  assert.match(mainWindow, /mainWindow\.on\("unresponsive"/);
  assert.match(mainWindow, /\[renderer:unresponsive\]/);
  assert.match(mainWindow, /mainWindow\.on\("responsive"/);
  assert.match(mainWindow, /\[renderer:responsive\]/);
});
