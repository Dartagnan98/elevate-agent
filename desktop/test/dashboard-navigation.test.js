const assert = require("node:assert/strict");
const test = require("node:test");

const { createDashboardNavigation } = require("../src/dashboard-navigation");

function makeWindow({ currentUrl = "http://127.0.0.1:9119/chat", rejectLoad = null } = {}) {
  const calls = [];
  return {
    calls,
    focus: () => calls.push(["focus"]),
    isDestroyed: () => false,
    loadFile: (file) => calls.push(["loadFile", file]),
    loadURL: (url) => {
      calls.push(["loadURL", url]);
      return rejectLoad ? Promise.reject(rejectLoad) : Promise.resolve();
    },
    webContents: {
      executeJavaScript: (script) => {
        calls.push(["executeJavaScript", script]);
        return Promise.resolve();
      },
      getURL: () => currentUrl,
    },
  };
}

function makeNavigation(overrides = {}) {
  const marks = [];
  const logs = [];
  const timers = [];
  const win = overrides.win || makeWindow();
  const nav = createDashboardNavigation({
    appRoot: "/app/src",
    backendMatchesDesktopMode: overrides.backendMatchesDesktopMode || (async () => true),
    backendUrl: () => "http://127.0.0.1:9119",
    delayMs: 750,
    limit: overrides.limit || 3,
    log: { warn: (message) => logs.push(message) },
    mainWindow: () => win,
    markStartup: (name, detail = "") => marks.push([name, detail]),
    path: { join: (...parts) => parts.join("/") },
    setTimeout: (callback, delay) => {
      timers.push({ callback, delay });
      return { unref() {} };
    },
    startPath: "/chat",
    trimLogMessage: (value) => String(value),
  });
  return { logs, marks, nav, timers, win };
}

test("dashboard navigation loads local and dashboard pages", () => {
  const { marks, nav, win } = makeNavigation();

  nav.loadLocalPage("loading.html");
  nav.loadAppPath("/leads");

  assert.deepEqual(win.calls[0], ["loadFile", "/app/src/loading.html"]);
  assert.deepEqual(win.calls[1], ["loadURL", "http://127.0.0.1:9119/leads"]);
  assert.deepEqual(marks, [
    ["window:load-local", "loading.html"],
    ["window:load-dashboard", "/leads"],
  ]);
});

test("dashboard navigation retries the last dashboard path", async () => {
  const { marks, nav, timers, win } = makeNavigation();

  nav.loadAppPath("/deals");
  nav.scheduleDashboardLoadRetry("did-fail-load:-2");
  await timers[0].callback();

  assert.deepEqual(
    win.calls.filter(([name]) => name === "loadURL").map((call) => call[1]),
    ["http://127.0.0.1:9119/deals", "http://127.0.0.1:9119/deals"],
  );
  assert.ok(marks.some(([name, detail]) => name === "window:dashboard-retry" && detail === "1:did-fail-load:-2"));
});

test("dashboard navigation falls back to install page after retry limit", async () => {
  const { nav, timers, win } = makeNavigation({
    backendMatchesDesktopMode: async () => false,
    limit: 1,
  });

  nav.scheduleDashboardLoadRetry("first");
  await timers[0].callback();

  assert.deepEqual(win.calls.at(-1), ["loadFile", "/app/src/install.html"]);
});

test("dashboard navigation focuses login or reloads dashboard from local pages", () => {
  const dashboardWin = makeWindow();
  const dashboardNav = makeNavigation({ win: dashboardWin }).nav;
  dashboardNav.openLoginWindow();
  assert.equal(dashboardWin.calls[1][0], "executeJavaScript");

  const localWin = makeWindow({ currentUrl: "file:///app/src/install.html" });
  const localNav = makeNavigation({ win: localWin }).nav;
  localNav.openLoginWindow();
  assert.deepEqual(localWin.calls.at(-1), ["loadURL", "http://127.0.0.1:9119/chat"]);
});
