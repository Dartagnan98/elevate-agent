const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appLifecyclePath = path.resolve(__dirname, "../src/app-lifecycle.js");
const mainWindowPath = path.resolve(__dirname, "../src/main-window.js");
const overlayManagerPath = path.resolve(__dirname, "../src/computer-use-overlay.js");

test("closed main window clears the singleton before reopen", () => {
  const mainWindow = fs.readFileSync(mainWindowPath, "utf8");

  assert.match(
    mainWindow,
    /mainWindow\.on\("closed",\s*\(\) => \{\s*setMainWindow\(null\);\s*}\);/s,
  );
});

test("activate restores existing window or recreates dashboard after close", () => {
  const lifecycle = fs.readFileSync(appLifecyclePath, "utf8");
  const start = lifecycle.indexOf('app.on("activate"');
  const end = lifecycle.indexOf('app.on("before-quit"', start);
  const activateBlock = lifecycle.slice(start, end);

  assert.match(activateBlock, /if \(win && !win\.isDestroyed\(\)\)/);
  assert.match(activateBlock, /if \(win\.isMinimized\(\)\) win\.restore\(\)/);
  assert.match(activateBlock, /win\.show\(\)/);
  assert.match(activateBlock, /win\.focus\(\)/);
  assert.match(activateBlock, /if \(backendReady\(\)\) \{\s*createWindow\(\);\s*createMenu\(\);\s*loadAppPath\(startPath\);/s);
  assert.match(activateBlock, /startDesktop\(\);/);
});

test("before-quit tears down overlay watcher and overlay window", () => {
  const lifecycle = fs.readFileSync(appLifecyclePath, "utf8");
  const overlay = fs.readFileSync(overlayManagerPath, "utf8");
  const start = lifecycle.indexOf('app.on("before-quit"');
  const beforeQuitBlock = lifecycle.slice(start);

  assert.match(beforeQuitBlock, /computerUseOverlay\.dispose\(\)/);
  assert.match(overlay, /clearInterval\(overlayWatcher\)/);
  assert.match(overlay, /overlayWatcher = null/);
  assert.match(overlay, /overlayWindow && !overlayWindow\.isDestroyed\(\)/);
  assert.match(overlay, /overlayWindow\.destroy\(\)/);
});
