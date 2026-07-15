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

function betaRuntimeMatches(payload, expectedRuntime) {
  const receipt = payload && payload.beta_runtime;
  return Boolean(
    receipt &&
      typeof receipt === "object" &&
      receipt.releaseChannel === expectedRuntime.releaseChannel &&
      receipt.elevateHome === expectedRuntime.elevateHome &&
      receipt.providerPolicyVersion === expectedRuntime.providerPolicyVersion &&
      receipt.allowedModelsVersion === expectedRuntime.allowedModelsVersion &&
      receipt.entitlementAssertionSchema === expectedRuntime.entitlementAssertionSchema &&
      receipt.entitlementAssertionKeyId === expectedRuntime.entitlementAssertionKeyId &&
      receipt.entitlementVerifierReady === true &&
      receipt.allowedProvider === expectedRuntime.allowedProvider &&
      receipt.configuredProvider === expectedRuntime.allowedProvider &&
      typeof receipt.configuredModel === "string" &&
      Array.isArray(expectedRuntime.allowedModels) &&
      expectedRuntime.allowedModels.includes(receipt.configuredModel) &&
      receipt.authReady === true &&
      receipt.authReason === null &&
      receipt.runtimeReady === true &&
      receipt.blockedReason === null
  );
}

function betaRuntimeCompatible(payload, expectedRuntime) {
  const receipt = payload && payload.beta_runtime;
  return Boolean(
    receipt &&
      typeof receipt === "object" &&
      receipt.releaseChannel === expectedRuntime.releaseChannel &&
      receipt.elevateHome === expectedRuntime.elevateHome &&
      receipt.providerPolicyVersion === expectedRuntime.providerPolicyVersion &&
      receipt.allowedModelsVersion === expectedRuntime.allowedModelsVersion &&
      receipt.entitlementAssertionSchema === expectedRuntime.entitlementAssertionSchema &&
      receipt.entitlementAssertionKeyId === expectedRuntime.entitlementAssertionKeyId &&
      receipt.entitlementVerifierReady === true &&
      receipt.allowedProvider === expectedRuntime.allowedProvider &&
      typeof receipt.configuredProvider === "string" &&
      typeof receipt.configuredModel === "string" &&
      typeof receipt.authReady === "boolean" &&
      (receipt.authReason === null || typeof receipt.authReason === "string") &&
      typeof receipt.runtimeReady === "boolean" &&
      (receipt.blockedReason === null || typeof receipt.blockedReason === "string")
  );
}

async function backendIsReady({ http, host, port, expectedRuntime = null }) {
  const status = await request({ http, host, pathname: "/api/status", timeoutMs: 2000, port });
  if (status !== 200) return false;
  const payload = await requestJson({ http, host, pathname: "/api/status", timeoutMs: 2000, port });
  const legacyReady = Boolean(
    payload &&
      typeof payload === "object" &&
      typeof payload.version === "string" &&
      Object.prototype.hasOwnProperty.call(payload, "gateway_running"),
  );
  if (!legacyReady) return false;
  if (!expectedRuntime) return true;
  return betaRuntimeMatches(payload, expectedRuntime);
}

async function backendCanServeApp({ http, host, port, expectedRuntime = null }) {
  const status = await request({ http, host, pathname: "/api/status", timeoutMs: 2000, port });
  if (status !== 200) return false;
  const payload = await requestJson({ http, host, pathname: "/api/status", timeoutMs: 2000, port });
  const legacyCompatible = Boolean(
    payload &&
      typeof payload === "object" &&
      typeof payload.version === "string" &&
      Object.prototype.hasOwnProperty.call(payload, "gateway_running"),
  );
  if (!legacyCompatible) return false;
  if (!expectedRuntime) return true;
  return betaRuntimeCompatible(payload, expectedRuntime);
}

async function dashboardChatEnabled({ http, host, port }) {
  const html = await requestText({ http, host, pathname: "/", timeoutMs: 2000, port });
  return html.includes("window.__ELEVATE_DASHBOARD_EMBEDDED_CHAT__=true");
}

module.exports = {
  backendCanServeApp,
  backendIsReady,
  betaRuntimeCompatible,
  betaRuntimeMatches,
  dashboardChatEnabled,
  request,
  requestJson,
  requestText,
};
