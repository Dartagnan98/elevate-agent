"use strict";

function request({ http, host, pathname, port, timeoutMs = 2000 }) {
  return new Promise((resolve) => {
    const req = http.get(
      {
        host,
        port,
        path: pathname,
        timeout: timeoutMs,
      },
      (res) => {
        res.resume();
        resolve(res.statusCode || 0);
      },
    );
    req.on("timeout", () => {
      req.destroy();
      resolve(0);
    });
    req.on("error", () => resolve(0));
  });
}

function requestText({ http, host, pathname, port, timeoutMs = 2000 }) {
  return new Promise((resolve) => {
    let body = "";
    const req = http.get(
      {
        host,
        port,
        path: pathname,
        timeout: timeoutMs,
      },
      (res) => {
        res.setEncoding("utf8");
        res.on("data", (chunk) => {
          body += chunk;
          if (body.length > 1024 * 1024) req.destroy();
        });
        res.on("end", () => resolve(body));
      },
    );
    req.on("timeout", () => {
      req.destroy();
      resolve("");
    });
    req.on("error", () => resolve(""));
  });
}

async function requestJson(deps) {
  const body = await requestText(deps);
  if (!body) return null;
  try {
    return JSON.parse(body);
  } catch {
    return null;
  }
}

async function backendIsReady({ http, host, port }) {
  const status = await request({ http, host, pathname: "/api/status", timeoutMs: 2000, port });
  if (status !== 200) return false;
  const payload = await requestJson({ http, host, pathname: "/api/status", timeoutMs: 2000, port });
  return Boolean(
    payload &&
      typeof payload === "object" &&
      typeof payload.version === "string" &&
      Object.prototype.hasOwnProperty.call(payload, "gateway_running"),
  );
}

async function dashboardChatEnabled({ http, host, port }) {
  const html = await requestText({ http, host, pathname: "/", timeoutMs: 2000, port });
  return html.includes("window.__ELEVATE_DASHBOARD_EMBEDDED_CHAT__=true");
}

module.exports = {
  backendIsReady,
  dashboardChatEnabled,
  request,
  requestJson,
  requestText,
};
