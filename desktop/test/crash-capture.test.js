const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const mainPath = path.resolve(__dirname, "../src/main.js");

function readMain() {
  return fs.readFileSync(mainPath, "utf8");
}

test("main process crash handlers write supportable log breadcrumbs", () => {
  const main = readMain();

  assert.match(main, /function formatCrashForLog\(reason\)/);
  assert.match(main, /reason && reason\.stack/);
  assert.match(main, /process\.on\("uncaughtException",\s*\(err\) =>/);
  assert.match(main, /\[main:uncaughtException\]/);
  assert.match(main, /app\.exit\(1\)/);
  assert.match(main, /process\.on\("unhandledRejection",\s*\(reason\) =>/);
  assert.match(main, /\[main:unhandledRejection\]/);
  assert.match(main, /installMainCrashCapture\(\);\s*markStartup\("main:module-loaded"\);/);
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
