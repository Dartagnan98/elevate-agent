"use strict";

const os = require("os");
const path = require("path");
const nodeFs = require("fs");

// B4 — opt-in Electron crash/error telemetry. The Python side already ships a
// flight recorder + uploader; the Electron MAIN process was the only blind
// spot. A box enables reports via ELEVATE_CRASH_REPORTS=1 or a
// ~/.elevate/crash-reports file. Default OFF — never send anything from a
// paying customer's machine without consent, and never send transcript content
// (only version/arch/kind + a redacted message + stack).
function createCrashReporter({
  app,
  log = console,
  fetchImpl,
  homedir = os.homedir,
  env = process.env,
  fs = nodeFs,
  endpoint = "https://api.elevationrealestatehq.com/api/diagnostics/crash",
  version,
  timeline = () => [],
  now = () => Date.now(),
} = {}) {
  function optedIn() {
    if (String(env.ELEVATE_CRASH_REPORTS || "").trim() === "1") return true;
    try {
      return fs.existsSync(path.join(homedir(), ".elevate", "crash-reports"));
    } catch {
      return false;
    }
  }

  // Strip anything that could carry PII or secrets before it leaves the box.
  function redact(text) {
    return String(text == null ? "" : text)
      .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[redacted-email]")
      .replace(/\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}\b/g, "[redacted-secret]")
      .replace(/\b(token|password|secret|api[_-]?key)=([^\s&]+)/gi, "$1=[redacted-secret]")
      .replace(/\/Users\/[^\s"'`]+/g, (match) => `[path:${match.split("/").pop() || "path"}]`)
      .replace(/\/home\/[^\s"'`]+/g, (match) => `[path:${match.split("/").pop() || "path"}]`);
  }

  function appVersion() {
    if (version) return version;
    try {
      return app && typeof app.getVersion === "function" ? app.getVersion() : "unknown";
    } catch {
      return "unknown";
    }
  }

  async function reportCrash(error, kind) {
    if (!optedIn()) return { sent: false, reason: "opt-out" };
    const doFetch = fetchImpl || (typeof fetch === "function" ? fetch : null);
    if (!doFetch) return { sent: false, reason: "no-fetch" };

    const payload = {
      version: appVersion(),
      platform: process.platform,
      arch: process.arch,
      kind: String(kind || "uncaughtException").slice(0, 40),
      message: redact(error && error.message ? error.message : error).slice(0, 500),
      stack: redact(error && error.stack ? error.stack : "").slice(0, 4000),
      timeline: (timeline() || []).slice(-40),
      at: now(),
    };

    try {
      await doFetch(endpoint, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      return { sent: true, payload };
    } catch (err) {
      log.warn(`[crash-reporter] send failed: ${err && err.message ? err.message : err}`);
      return { sent: false, reason: "network", payload };
    }
  }

  return { optedIn, redact, reportCrash };
}

module.exports = { createCrashReporter };
