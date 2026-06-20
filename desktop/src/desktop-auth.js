const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

function decodeJwtExp(token) {
  try {
    const payload = token.split(".")[1];
    const json = Buffer.from(payload.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8");
    const claims = JSON.parse(json);
    return Number(claims.exp || 0);
  } catch {
    return 0;
  }
}

function createDesktopAuth({
  log,
  hqBaseUrl,
  licensePath,
  accessRefreshMarginMs = 5 * 60 * 1000,
  fetchImpl = globalThis.fetch,
}) {
  function readLicense() {
    try {
      const raw = fs.readFileSync(licensePath, "utf8");
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  function writeLicense(license) {
    fs.mkdirSync(path.dirname(licensePath), { recursive: true });
    fs.writeFileSync(licensePath, JSON.stringify(license, null, 2), { mode: 0o600 });
  }

  function clearLicense() {
    try {
      fs.unlinkSync(licensePath);
    } catch {
      // already gone is fine
    }
  }

  function hqJsonRequestHeaders(scope) {
    const requestId = `desktop-${scope}-${crypto.randomUUID()}`;
    log.info(`[desktop:request] request_id=${requestId} scope=${scope}`);
    return {
      requestId,
      headers: {
        "Content-Type": "application/json",
        "X-Request-Id": requestId,
      },
    };
  }

  async function refreshLicense(license) {
    if (!license || !license.refresh_token) return null;
    const { requestId, headers } = hqJsonRequestHeaders("license-refresh");
    try {
      // Same endpoint the CLI's elevate_cli/license.py refresh() uses, so a
      // session refreshed here is interchangeable with one refreshed by the CLI.
      const res = await fetchImpl(`${hqBaseUrl}/api/license/refresh`, {
        method: "POST",
        headers,
        body: JSON.stringify({ refresh_token: license.refresh_token }),
      });
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        log.warn(
          `[license] refresh failed request_id=${requestId}: HTTP ${res.status} ${body.slice(0, 200)}`,
        );
        return null;
      }
      const data = await res.json();
      if (!data || !data.access_token || !data.refresh_token) {
        log.warn(`[license] refresh response missing tokens request_id=${requestId}`);
        return null;
      }
      const next = {
        ...license,
        access_token: data.access_token,
        refresh_token: data.refresh_token,
        license_id: data.license_id || license.license_id,
        tier: data.tier || license.tier,
        entitlements: data.entitlements || license.entitlements,
        expires_at: decodeJwtExp(data.access_token),
      };
      writeLicense(next);
      log.info(`[license] refresh succeeded request_id=${requestId}`);
      return next;
    } catch (err) {
      log.warn(`[license] refresh threw request_id=${requestId}: ${err && err.message ? err.message : err}`);
      return null;
    }
  }

  async function refreshLicenseWithRetry(license, attempts = 3) {
    for (let i = 0; i < attempts; i++) {
      const next = await refreshLicense(license);
      if (next) return next;
      if (i < attempts - 1) {
        await new Promise((r) => setTimeout(r, 1000 * (i + 1)));
      }
    }
    return null;
  }

  async function ensureValidLicense({ retry = false } = {}) {
    let license = readLicense();
    if (!license || !license.access_token) return null;

    const expMs = (Number(license.expires_at) || 0) * 1000;
    if (!Number.isFinite(expMs) || Date.now() > expMs - accessRefreshMarginMs) {
      license = retry
        ? await refreshLicenseWithRetry(license)
        : await refreshLicense(license);
    }
    return license;
  }

  async function performLogin({ email, password }) {
    if (!email || !password) {
      return { ok: false, error: "Email and password are required." };
    }
    const { requestId, headers } = hqJsonRequestHeaders("auth-login");
    try {
      const res = await fetchImpl(`${hqBaseUrl}/api/auth/login`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          email: String(email).trim().toLowerCase(),
          password,
          device_label: `Elevate Desktop (${os.hostname()})`,
        }),
      });

      if (res.status === 401) {
        log.warn(`[auth] login rejected request_id=${requestId}: HTTP 401`);
        return { ok: false, error: "Email or password is wrong." };
      }
      if (res.status === 402) {
        log.warn(`[auth] login rejected request_id=${requestId}: HTTP 402`);
        return {
          ok: false,
          error: "Your account has no active subscription. Upgrade in your browser, then sign in.",
        };
      }
      if (!res.ok) {
        const text = await res.text();
        log.warn(`[auth] login failed request_id=${requestId}: HTTP ${res.status} ${text.slice(0, 160)}`);
        return { ok: false, error: `Sign-in failed (${res.status}): ${text.slice(0, 160)}` };
      }

      const data = await res.json();
      const license = {
        access_token: data.access_token,
        refresh_token: data.refresh_token,
        license_id: data.license_id,
        tier: data.tier,
        email: String(email).trim().toLowerCase(),
        expires_at: decodeJwtExp(data.access_token),
        entitlements: data.entitlements || [],
      };
      writeLicense(license);
      log.info(`[auth] login succeeded request_id=${requestId}`);
      return { ok: true, license };
    } catch (err) {
      log.warn(`[auth] login threw request_id=${requestId}: ${err && err.message ? err.message : err}`);
      return {
        ok: false,
        error: `Could not reach ${hqBaseUrl}. Check your connection and try again.`,
      };
    }
  }

  return {
    clearLicense,
    decodeJwtExp,
    ensureValidLicense,
    hqJsonRequestHeaders,
    performLogin,
    readLicense,
    refreshLicense,
    refreshLicenseWithRetry,
    writeLicense,
  };
}

module.exports = {
  createDesktopAuth,
  decodeJwtExp,
};
