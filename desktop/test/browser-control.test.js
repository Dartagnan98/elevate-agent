const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { startControlServer } = require("../src/browser-control");

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
    list: () => [{ id: "tab_1", active: true }],
    navigate: async (tabId, url) => {
      calls.push({ tabId, url });
      return { ok: true, url };
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
  const listed = await rpc(endpoint, "list");
  const navigated = await rpc(endpoint, "navigate", {
    tabId: "tab_1",
    url: "https://example.com/",
  });

  assert.equal(listed.status, 200);
  assert.deepEqual(listed.body.result, [{ id: "tab_1", active: true }]);
  assert.equal(navigated.status, 200);
  assert.deepEqual(navigated.body.result, {
    ok: true,
    url: "https://example.com/",
  });
  assert.deepEqual(calls, [{
    tabId: "tab_1",
    url: "https://example.com/",
  }]);
  assert.equal(fs.statSync(endpointPath).mode & 0o777, 0o600);
});
