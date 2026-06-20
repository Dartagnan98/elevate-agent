const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const mainPath = path.resolve(__dirname, "../src/main.js");
const overlayManagerPath = path.resolve(__dirname, "../src/computer-use-overlay.js");

function readMain() {
  return fs.readFileSync(mainPath, "utf8");
}

test("closed main window clears the singleton before reopen", () => {
  const main = readMain();

  assert.match(
    main,
    /mainWindow\.on\("closed",\s*\(\) => \{\s*mainWindow = null;\s*}\);/s,
  );
});

test("activate restores existing window or recreates dashboard after close", () => {
  const main = readMain();
  const start = main.indexOf('app.on("activate"');
  const end = main.indexOf('app.on("before-quit"', start);
  const activateBlock = main.slice(start, end);

  assert.match(activateBlock, /if \(mainWindow && !mainWindow\.isDestroyed\(\)\)/);
  assert.match(activateBlock, /if \(mainWindow\.isMinimized\(\)\) mainWindow\.restore\(\)/);
  assert.match(activateBlock, /mainWindow\.show\(\)/);
  assert.match(activateBlock, /mainWindow\.focus\(\)/);
  assert.match(activateBlock, /if \(backendReady\) \{\s*createWindow\(\);\s*createMenu\(\);\s*loadAppPath\(START_PATH\);/s);
  assert.match(activateBlock, /startDesktop\(\);/);
});

test("before-quit tears down overlay watcher and overlay window", () => {
  const main = readMain();
  const overlay = fs.readFileSync(overlayManagerPath, "utf8");
  const start = main.indexOf('app.on("before-quit"');
  const beforeQuitBlock = main.slice(start);

  assert.match(beforeQuitBlock, /computerUseOverlay\.dispose\(\)/);
  assert.match(overlay, /clearInterval\(overlayWatcher\)/);
  assert.match(overlay, /overlayWatcher = null/);
  assert.match(overlay, /overlayWindow && !overlayWindow\.isDestroyed\(\)/);
  assert.match(overlay, /overlayWindow\.destroy\(\)/);
});
