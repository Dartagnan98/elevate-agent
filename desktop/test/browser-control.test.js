const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { startControlServer } = require("../src/browser-control");
const {
  clampPaneBounds,
  normalizeWorkspaceId,
  standardBrowserUserAgent,
} = require("../src/browser-pane");

function waitForEndpoint(filePath) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + 2000;
    const check = () => {
      try {
        resolve(JSON.parse(fs.readFileSync(filePath, "utf8")));
      } catch (error) {
        if (Date.now() >= deadline) reject(error);
        else setTimeout(check, 10);
      }
    };
    check();
  });
}

function rpc({ port, token }, method, params = {}) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ method, params });
    const request = http.request(
      {
        host: "127.0.0.1",
        port,
        path: "/rpc",
        method: "POST",
        headers: {
          authorization: `Bearer ${token}`,
          "content-type": "application/json",
          "content-length": Buffer.byteLength(body),
        },
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () => {
          resolve({
            status: response.statusCode,
            body: JSON.parse(Buffer.concat(chunks).toString("utf8")),
          });
        });
      },
    );
    request.on("error", reject);
    request.end(body);
  });
}

test("browser control endpoint authenticates and targets the shared pane", async (t) => {
  const elevateHome = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-browser-control-"));
  const calls = [];
  const pane = {
    status: (sessionKey) => ({
      open: true,
      workspaceId: sessionKey,
      activeTabId: "tab_1",
    }),
    list: (sessionKey) => [{ id: "tab_1", active: true, sessionKey }],
    navigate: async (tabId, url, sessionKey) => {
      calls.push({ tabId, url, sessionKey });
      return { ok: true, url };
    },
    noteAgentAction: (sessionKey, method) => {
      calls.push({ sessionKey, method });
    },
  };
  const controller = startControlServer({
    pane,
    elevateHome,
    log: { info() {}, warn() {} },
  });
  t.after(() => {
    controller.stop();
    fs.rmSync(elevateHome, { recursive: true, force: true });
  });

  const endpointPath = path.join(elevateHome, "browser-pane.json");
  const endpoint = await waitForEndpoint(endpointPath);
  const status = await rpc(endpoint, "status", { sessionKey: "chat-a" });
  const listed = await rpc(endpoint, "list", { sessionKey: "chat-a" });
  const navigated = await rpc(endpoint, "navigate", {
    sessionKey: "chat-a",
    tabId: "tab_1",
    url: "https://example.com/",
  });

  assert.equal(status.status, 200);
  assert.deepEqual(status.body.result, {
    open: true,
    workspaceId: "chat-a",
    activeTabId: "tab_1",
  });
  assert.equal(listed.status, 200);
  assert.deepEqual(listed.body.result, [{
    id: "tab_1",
    active: true,
    sessionKey: "chat-a",
  }]);
  assert.equal(navigated.status, 200);
  assert.deepEqual(navigated.body.result, {
    ok: true,
    url: "https://example.com/",
  });
  assert.deepEqual(calls, [
    { sessionKey: "chat-a", method: "navigate" },
    {
      tabId: "tab_1",
      url: "https://example.com/",
      sessionKey: "chat-a",
    },
  ]);
  assert.equal(fs.statSync(endpointPath).mode & 0o777, 0o600);
});

test("embedded browser identity omits Electron and app-brand tokens", () => {
  const userAgent = standardBrowserUserAgent("darwin", "142.0.7444.265");

  assert.match(userAgent, /Chrome\/142\.0\.7444\.265/);
  assert.doesNotMatch(userAgent, /Electron|Elevate/i);
});

test("agent tab actions activate the matching browser workspace", async (t) => {
  const elevateHome = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-browser-tabs-"));
  const calls = [];
  const pane = {
    newTab: (url, sessionKey) => {
      calls.push({ action: "newTab", url, sessionKey });
      return "tab_2";
    },
    selectTab: (tabId, sessionKey) => {
      calls.push({ action: "selectTab", tabId, sessionKey });
      return true;
    },
    closeTab: (tabId, sessionKey) => {
      calls.push({ action: "closeTab", tabId, sessionKey });
      return true;
    },
    noteAgentAction: (sessionKey, method) => {
      calls.push({ action: "noteAgentAction", sessionKey, method });
    },
  };
  const controller = startControlServer({
    pane,
    elevateHome,
    log: { info() {}, warn() {} },
  });
  t.after(() => {
    controller.stop();
    fs.rmSync(elevateHome, { recursive: true, force: true });
  });

  const endpoint = await waitForEndpoint(
    path.join(elevateHome, "browser-pane.json"),
  );
  await rpc(endpoint, "new_tab", {
    sessionKey: "chat-tabs",
    url: "https://example.com/",
  });
  await rpc(endpoint, "select_tab", {
    sessionKey: "chat-tabs",
    tabId: "tab_2",
  });
  await rpc(endpoint, "close_tab", {
    sessionKey: "chat-tabs",
    tabId: "tab_2",
  });

  assert.deepEqual(calls, [
    {
      action: "noteAgentAction",
      sessionKey: "chat-tabs",
      method: "new_tab",
    },
    {
      action: "newTab",
      url: "https://example.com/",
      sessionKey: "chat-tabs",
    },
    {
      action: "noteAgentAction",
      sessionKey: "chat-tabs",
      method: "select_tab",
    },
    { action: "selectTab", tabId: "tab_2", sessionKey: "chat-tabs" },
    {
      action: "noteAgentAction",
      sessionKey: "chat-tabs",
      method: "close_tab",
    },
    { action: "closeTab", tabId: "tab_2", sessionKey: "chat-tabs" },
  ]);
});

test("embedded browser bounds cannot escape the app content area", () => {
  assert.deepEqual(
    clampPaneBounds(
      { x: -50, y: 40, width: 2000, height: 1200 },
      { width: 1280, height: 800 },
    ),
    { x: 0, y: 40, width: 1280, height: 760 },
  );
});

test("browser workspace ids are stable and bounded", () => {
  assert.equal(normalizeWorkspaceId(""), "default");
  assert.equal(normalizeWorkspaceId(" chat-a "), "chat-a");
  assert.equal(normalizeWorkspaceId("x".repeat(300)).length, 256);
});
