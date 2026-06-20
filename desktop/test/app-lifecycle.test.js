const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const test = require("node:test");

const { createAppLifecycle } = require("../src/app-lifecycle");

function makeWindow() {
  const calls = [];
  return {
    calls,
    focus: () => calls.push("focus"),
    isDestroyed: () => false,
    isMinimized: () => true,
    restore: () => calls.push("restore"),
    show: () => calls.push("show"),
  };
}

function makeLifecycle(overrides = {}) {
  const calls = [];
  const app = new EventEmitter();
  app.focus = (options) => calls.push(["app.focus", options]);
  app.quit = () => calls.push(["app.quit"]);
  app.requestSingleInstanceLock = () => overrides.primary !== false;
  app.whenReady = () => Promise.resolve();
  let win = overrides.window || null;
  const lifecycle = createAppLifecycle({
    app,
    backendProcess: () => overrides.backendProcess || null,
    backendReady: () => Boolean(overrides.backendReady),
    computerUseOverlay: { dispose: () => calls.push(["overlay.dispose"]) },
    createMenu: () => calls.push(["createMenu"]),
    createWindow: () => calls.push(["createWindow"]),
    deepLinks: {
      handleDeepLink: (url) => calls.push(["deepLink", url]),
      replayPending: () => calls.push(["replayPending"]),
    },
    kickoffUpdates: () => calls.push(["kickoffUpdates"]),
    loadAppPath: (pathname) => calls.push(["loadAppPath", pathname]),
    log: { warn: (message) => calls.push(["warn", message]) },
    mainWindow: () => win,
    markStartup: (name) => calls.push(["mark", name]),
    ownsBackend: () => Boolean(overrides.ownsBackend),
    process: { platform: overrides.platform || "darwin" },
    startDesktop: async () => calls.push(["startDesktop"]),
    startPath: "/chat",
    startSmsOutboxWatcher: () => calls.push(["sms"]),
  });
  return { app, calls, lifecycle, setWindow: (value) => { win = value; } };
}

test("app lifecycle hands second instances to the primary window", () => {
  const win = makeWindow();
  const { app, calls, lifecycle } = makeLifecycle({ window: win });

  assert.equal(lifecycle.registerSingleInstance(), true);
  app.emit("second-instance", null, ["foo", "elevate://signin"]);

  assert.deepEqual(win.calls, ["restore", "show", "focus"]);
  assert.deepEqual(calls.filter(([name]) => name === "deepLink"), [["deepLink", "elevate://signin"]]);
});

test("app lifecycle activate reuses windows or recreates dashboard", () => {
  const win = makeWindow();
  const first = makeLifecycle({ window: win });
  first.lifecycle.registerAppEvents(true);
  first.app.emit("activate");
  assert.deepEqual(win.calls, ["restore", "show", "focus"]);

  const second = makeLifecycle({ backendReady: true });
  second.lifecycle.registerAppEvents(true);
  second.app.emit("activate");
  assert.deepEqual(second.calls, [["createWindow"], ["createMenu"], ["loadAppPath", "/chat"]]);
});

test("app lifecycle tears down overlay and owned backend before quit", () => {
  const killed = [];
  const { app, calls, lifecycle } = makeLifecycle({
    backendProcess: { kill: () => killed.push("kill") },
    ownsBackend: true,
  });

  lifecycle.registerAppEvents(true);
  app.emit("before-quit");

  assert.deepEqual(calls, [["overlay.dispose"]]);
  assert.deepEqual(killed, ["kill"]);
});
