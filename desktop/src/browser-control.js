"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const MAX_BODY = 16 << 20;

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY) {
        reject(new Error("body too large"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function tokenMatches(header, token) {
  const supplied = Buffer.from(String(header || ""), "utf8");
  const expected = Buffer.from(`Bearer ${token}`, "utf8");
  return supplied.length === expected.length && crypto.timingSafeEqual(supplied, expected);
}

const COMMANDS = {
  status: (pane, params) => pane.status(params.sessionKey),
  profile_status: (pane) => pane.profileStatus(),
  import_cookies: (pane, params) =>
    pane.importCookies(params.cookies, {
      sourceProfile: params.sourceProfile,
    }),
  list: (pane, params) => pane.list(params.sessionKey),
  new_tab: (pane, params) => ({
    tabId: pane.newTab(params.url, params.sessionKey),
  }),
  close_tab: (pane, params) => ({
    ok: pane.closeTab(params.tabId, params.sessionKey),
  }),
  select_tab: (pane, params) => ({
    ok: pane.selectTab(params.tabId, params.sessionKey),
  }),
  navigate: (pane, params) =>
    pane.navigate(params.tabId, params.url, params.sessionKey),
  read_page: (pane, params) => pane.readPage(params.tabId, params.sessionKey),
  click: (pane, params) =>
    pane.click(params.tabId, params.ref, params.sessionKey),
  drag: (pane, params) =>
    pane.drag(params.tabId, params.sourceRef, params.targetRef, params.sessionKey),
  fill: (pane, params) =>
    pane.fill(params.tabId, params.ref, params.value, params.sessionKey),
  type: (pane, params) =>
    pane.type(params.tabId, params.text, params.sessionKey),
  key: (pane, params) => pane.key(params.tabId, params.key, params.sessionKey),
  scroll: (pane, params) =>
    pane.scroll(params.tabId, params.dy, params.sessionKey),
  back: (pane, params) => pane.back(params.tabId, params.sessionKey),
  forward: (pane, params) => pane.forward(params.tabId, params.sessionKey),
  reload: (pane, params) => pane.reload(params.tabId, params.sessionKey),
  eval: (pane, params) =>
    pane.evaluate(params.tabId, params.expression, params.sessionKey),
  screenshot: (pane, params) =>
    pane.screenshot(params.tabId, params.sessionKey),
  console: (pane, params) => pane.console(params.tabId, params.sessionKey),
};

const AGENT_ACTION_COMMANDS = new Set([
  "new_tab",
  "close_tab",
  "select_tab",
  "navigate",
  "click",
  "drag",
  "fill",
  "type",
  "key",
  "scroll",
  "back",
  "forward",
  "reload",
]);

function startControlServer({ pane, elevateHome, log = console }) {
  const token = crypto.randomBytes(32).toString("hex");
  const endpointFile = path.join(elevateHome, "browser-pane.json");
  let stopped = false;

  const server = http.createServer(async (req, res) => {
    const send = (status, body) => {
      const json = JSON.stringify(body);
      res.writeHead(status, {
        "content-type": "application/json",
        "content-length": Buffer.byteLength(json),
      });
      res.end(json);
    };

    try {
      if (req.method !== "POST" || req.url !== "/rpc") {
        send(404, { error: "not found" });
        return;
      }
      if (!tokenMatches(req.headers.authorization, token)) {
        send(401, { error: "unauthorized" });
        return;
      }
      const payload = JSON.parse(await readBody(req));
      const handler = COMMANDS[payload.method];
      if (!handler) {
        send(400, { error: `unknown method: ${payload.method}` });
        return;
      }
      if (AGENT_ACTION_COMMANDS.has(payload.method)) {
        pane.noteAgentAction(payload.params?.sessionKey, payload.method);
      }
      send(200, { result: await handler(pane, payload.params || {}) });
    } catch (error) {
      log.warn?.(`[browser-control] ${error && error.message ? error.message : error}`);
      send(500, { error: String(error && error.message ? error.message : error) });
    }
  });

  server.listen(0, "127.0.0.1", () => {
    const address = server.address();
    if (!address || typeof address === "string" || stopped) return;
    fs.mkdirSync(elevateHome, { recursive: true });
    fs.writeFileSync(
      endpointFile,
      JSON.stringify({ port: address.port, token }),
      { mode: 0o600 },
    );
    log.info?.(`[browser-control] listening on 127.0.0.1:${address.port}`);
  });

  return {
    stop() {
      if (stopped) return;
      stopped = true;
      server.close();
      fs.rmSync(endpointFile, { force: true });
    },
  };
}

module.exports = { startControlServer };
