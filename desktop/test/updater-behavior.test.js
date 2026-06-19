const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const mainPath = path.resolve(__dirname, "../src/main.js");

function loadUpdater({
  isPackaged = true,
  hasMetadata = true,
  checkForUpdates,
  quitAndInstall,
} = {}) {
  const main = fs.readFileSync(mainPath, "utf8");
  const start = main.indexOf('let updateState = { status: "idle"');
  const end = main.indexOf("// Register the elevate:// scheme");
  assert.ok(start > 0);
  assert.ok(end > start);

  const handlers = new Map();
  const updaterEvents = new Map();
  const sent = [];
  const quitCalls = [];
  let checkCalls = 0;

  const context = {
    path,
    process: { resourcesPath: "/tmp/elevate-updater-test" },
    fs: { existsSync: () => hasMetadata },
    log: { info() {}, warn() {} },
    app: { isPackaged, on() {} },
    mainWindow: {
      isDestroyed: () => false,
      webContents: {
        send(channel, payload) {
          sent.push({ channel, payload });
        },
      },
    },
    ipcMain: {
      handle(channel, handler) {
        handlers.set(channel, handler);
      },
    },
    autoUpdater: {
      on(event, handler) {
        updaterEvents.set(event, handler);
      },
      async checkForUpdates() {
        checkCalls += 1;
        return checkForUpdates ? checkForUpdates() : { updateInfo: { version: "9.9.9" } };
      },
      quitAndInstall(...args) {
        quitCalls.push(args);
        if (quitAndInstall) quitAndInstall(...args);
      },
    },
    setImmediate(callback) {
      callback();
    },
    setInterval() {
      return { unref() {} };
    },
    Date,
    Set,
    String,
  };

  vm.runInNewContext(main.slice(start, end), context);
  return {
    handlers,
    updaterEvents,
    sent,
    quitCalls,
    get checkCalls() {
      return checkCalls;
    },
  };
}

test("missing packaged update metadata is a visible updater failure", async () => {
  const updater = loadUpdater({ hasMetadata: false });

  const result = await updater.handlers.get("updater:check")();

  assert.equal(result.ok, false);
  assert.equal(result.message, "update metadata is not bundled");
  assert.equal(updater.handlers.get("updater:status")().status, "error");
  assert.equal(updater.sent.at(-1).channel, "updater:event");
  assert.equal(updater.sent.at(-1).payload.error, "update metadata is not bundled");
  assert.equal(updater.checkCalls, 0);
});

test("manual updater check rejects unpackaged builds without hitting updater", async () => {
  const updater = loadUpdater({ isPackaged: false });

  const result = await updater.handlers.get("updater:check")();

  assert.equal(result.ok, false);
  assert.equal(result.message, "Updates only run in packaged builds.");
  assert.equal(updater.checkCalls, 0);
});

test("updater skips duplicate checks while update is busy", async () => {
  const updater = loadUpdater();
  updater.updaterEvents.get("update-available")({ version: "9.9.9" });

  const result = await updater.handlers.get("updater:check")();

  assert.equal(result.ok, true);
  assert.equal(result.skipped, true);
  assert.equal(result.message, "update already available");
  assert.equal(updater.checkCalls, 0);
});

test("updater install only runs once an update is ready", () => {
  const updater = loadUpdater();

  const notReady = updater.handlers.get("updater:install")();
  assert.equal(notReady.ok, false);
  assert.equal(notReady.message, "Update is not ready yet.");

  updater.updaterEvents.get("update-downloaded")({ version: "9.9.9" });

  assert.equal(updater.handlers.get("updater:install")().ok, true);
  assert.deepEqual(updater.quitCalls, [[false, true]]);
});

test("updater check failures are visible and can be retried", async () => {
  let attempts = 0;
  const updater = loadUpdater({
    checkForUpdates() {
      attempts += 1;
      if (attempts === 1) throw new Error("feed unavailable");
      return { updateInfo: { version: "9.9.9" } };
    },
  });

  const first = await updater.handlers.get("updater:check")();
  assert.equal(first.ok, false);
  assert.equal(first.message, "feed unavailable");
  assert.equal(updater.handlers.get("updater:status")().status, "error");
  assert.equal(updater.sent.at(-1).payload.error, "feed unavailable");

  const retry = await updater.handlers.get("updater:check")();
  assert.equal(retry.ok, true);
  assert.equal(retry.version, "9.9.9");
  assert.equal(updater.checkCalls, 2);
});

test("updater error events stay visible without blocking retry", async () => {
  const updater = loadUpdater();

  updater.updaterEvents.get("error")(new Error("download failed"));

  assert.equal(updater.handlers.get("updater:status")().status, "error");
  assert.equal(updater.sent.at(-1).payload.error, "download failed");

  const retry = await updater.handlers.get("updater:check")();
  assert.equal(retry.ok, true);
  assert.equal(retry.version, "9.9.9");
  assert.equal(updater.checkCalls, 1);
});

test("updater install failures are visible and can be retried", async () => {
  const updater = loadUpdater({
    quitAndInstall() {
      throw new Error("ShipIt failed");
    },
  });
  updater.updaterEvents.get("update-downloaded")({ version: "9.9.9" });

  const install = updater.handlers.get("updater:install")();

  assert.equal(install.ok, true);
  assert.equal(updater.handlers.get("updater:status")().status, "error");
  assert.equal(updater.sent.at(-1).payload.error, "ShipIt failed");
  assert.deepEqual(updater.quitCalls, [[false, true]]);

  const retry = await updater.handlers.get("updater:check")();
  assert.equal(retry.ok, true);
  assert.equal(retry.version, "9.9.9");
  assert.equal(updater.checkCalls, 1);
});
