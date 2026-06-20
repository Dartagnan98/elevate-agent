const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const mainPath = path.resolve(__dirname, "../src/main.js");
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
  const main = readMain();

  assert.match(main, /webContents\.on\("render-process-gone"/);
  assert.match(main, /\[renderer:gone\]/);
  assert.match(main, /mainWindow\.on\("unresponsive"/);
  assert.match(main, /\[renderer:unresponsive\]/);
  assert.match(main, /mainWindow\.on\("responsive"/);
  assert.match(main, /\[renderer:responsive\]/);
});
