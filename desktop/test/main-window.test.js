const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const path = require("node:path");
const test = require("node:test");

const { createMainWindowController } = require("../src/main-window");

function makeController(overrides = {}) {
  const marks = [];
  const logs = [];
  const shellOpened = [];
  let currentUrl = overrides.currentUrl || "http://127.0.0.1:9119/chat";
  let storedWindow = null;
  class FakeBrowserWindow extends EventEmitter {
    constructor(options) {
      super();
      this.options = options;
      this.webContents = new EventEmitter();
      this.webContents.getURL = () => currentUrl;
      this.webContents.setWindowOpenHandler = (handler) => {
        this.windowOpenHandler = handler;
      };
    }
    isDestroyed() {
      return false;
    }
    show() {
      this.showed = true;
    }
  }
  const controller = createMainWindowController({
    BrowserWindow: FakeBrowserWindow,
    Menu: {
      buildFromTemplate(items) {
        return {
          popup({ window }) {
            window.contextMenuItems = items;
          },
        };
      },
    },
    appRoot: "/app/src",
    backendUrl: () => "http://127.0.0.1:9119",
    currentMainWindowUrl: () => currentUrl,
    finishStartup: (reason) => marks.push(["finish", reason]),
    isTrustedNavigationUrl: overrides.isTrustedNavigationUrl || (() => true),
    log: {
      error: (message) => logs.push(["error", message]),
      info: (message) => logs.push(["info", message]),
      warn: (message) => logs.push(["warn", message]),
    },
    markStartup: (name, detail = "") => marks.push([name, detail]),
    path,
    process: { platform: "darwin" },
    resetDashboardLoadRetry: () => marks.push(["reset"]),
    scheduleDashboardLoadRetry: (reason) => marks.push(["retry", reason]),
    setMainWindow: (win) => {
      storedWindow = win;
    },
    shell: { openExternal: (url) => shellOpened.push(url) },
    trimLogMessage: (value) => String(value),
  });
  controller.createWindow();
  return {
    getStoredWindow: () => storedWindow,
    logs,
    marks,
    shellOpened,
    setCurrentUrl: (url) => { currentUrl = url; },
    win: storedWindow,
  };
}

test("main window uses hardened renderer options and clears singleton on close", () => {
  const { getStoredWindow, marks, win } = makeController();

  assert.equal(win.options.webPreferences.sandbox, true);
  assert.equal(win.options.webPreferences.nodeIntegration, false);
  assert.equal(win.options.webPreferences.preload, "/app/src/preload.js");
  win.emit("closed");
  assert.equal(getStoredWindow(), null);
  assert.deepEqual(marks[0], ["window:create", ""]);
});

test("main window retries dashboard loads and records renderer crashes", () => {
  const { logs, marks, win } = makeController();

  win.webContents.emit("did-fail-load", null, -2, "bad", "http://127.0.0.1:9119/chat");
  win.webContents.emit("render-process-gone", null, { reason: "crashed", exitCode: 11 });

  assert.deepEqual(marks.find(([name]) => name === "retry"), ["retry", "did-fail-load:-2"]);
  assert.match(logs.map((entry) => entry[1]).join("\n"), /\[renderer:gone\]/);
});

test("main window gates external navigation and window.open targets", () => {
  const { shellOpened, win } = makeController({
    isTrustedNavigationUrl: (url) => url.startsWith("http://127.0.0.1:9119"),
  });

  assert.deepEqual(win.windowOpenHandler({ url: "http://127.0.0.1:9119/chat" }), { action: "allow" });
  assert.deepEqual(win.windowOpenHandler({ url: "https://example.com" }), { action: "deny" });
  assert.deepEqual(shellOpened, ["https://example.com"]);

  let prevented = false;
  win.webContents.emit("will-navigate", { preventDefault: () => { prevented = true; } }, "file:///etc/passwd");
  assert.equal(prevented, true);
});
