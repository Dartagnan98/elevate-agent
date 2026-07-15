const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const {
  EntitlementAssertionError,
  productionKeyset,
  verifyEntitlementAssertion,
} = require("./entitlement-assertion");

const SIGNED_HQ_BASE_URL = "https://api.elevationrealestatehq.com";

class DesktopAuthError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "DesktopAuthError";
    this.code = code;
  }
}

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
  isBeta = false,
  home = os.homedir(),
  profileRoot = path.dirname(licensePath),
  accessRefreshMarginMs = 5 * 60 * 1000,
  fetchImpl = globalThis.fetch,
  fsImpl = fs,
  env = process.env,
  processImpl = process,
  entitlementKeyset = productionKeyset(),
}) {
  const effectiveHqBaseUrl = (
    isBeta ? SIGNED_HQ_BASE_URL : hqBaseUrl || SIGNED_HQ_BASE_URL
  ).replace(/\/+$/, "");
  const resolvedProfileRoot = path.resolve(profileRoot);
  const resolvedLicensePath = path.resolve(licensePath);
  const expectedBetaProfileRoot = path.resolve(home, ".elevate-beta");
  let licenseRevision = 0;
  let loginInFlight = 0;
  let refreshInFlight = null;
  let sessionOperationSequence = 0;

  function storeError(code, message) {
    return new DesktopAuthError(code, message);
  }

  function preflightLicenseStore({ writable = true } = {}) {
    if (!isBeta) return;
    if (
      resolvedProfileRoot !== expectedBetaProfileRoot ||
      path.basename(resolvedLicensePath) !== "license.json" ||
      path.dirname(resolvedLicensePath) !== resolvedProfileRoot
    ) {
      throw storeError(
        "beta_license_store_not_local",
        "Realtor Beta will only use its dedicated local Beta profile.",
      );
    }
    if (
      String(env.ELEVATE_MANAGED || "").trim() ||
      fsImpl.existsSync(path.join(resolvedProfileRoot, ".managed"))
    ) {
      throw storeError(
        "beta_license_store_managed",
        "This managed Realtor Beta profile cannot persist an account session.",
      );
    }
    try {
      const parent = path.dirname(resolvedProfileRoot);
      const parentStat = fsImpl.lstatSync(parent);
      if (!parentStat.isDirectory() || parentStat.isSymbolicLink()) {
        throw storeError(
          "beta_license_store_not_local",
          "Realtor Beta could not verify its local profile parent.",
        );
      }
      if (!fsImpl.existsSync(resolvedProfileRoot)) {
        if (!writable) {
          throw storeError(
            "beta_license_snapshot_invalid",
            "The Realtor Beta account snapshot is missing.",
          );
        }
        fsImpl.mkdirSync(resolvedProfileRoot, { mode: 0o700 });
      }
      const rootStat = fsImpl.lstatSync(resolvedProfileRoot);
      if (
        !rootStat.isDirectory() ||
        rootStat.isSymbolicLink() ||
        fsImpl.realpathSync(resolvedProfileRoot) !== resolvedProfileRoot ||
        rootStat.dev !== parentStat.dev
      ) {
        throw storeError(
          "beta_license_store_not_local",
          "Realtor Beta will not use a linked, redirected, or nonlocal profile.",
        );
      }
      if (
        typeof processImpl.getuid === "function" &&
        rootStat.uid !== processImpl.getuid()
      ) {
        throw storeError(
          "beta_license_store_not_local",
          "Realtor Beta will not use a profile owned by another account.",
        );
      }
      if ((rootStat.mode & 0o022) !== 0) {
        throw storeError(
          "beta_license_store_not_private",
          "The Realtor Beta profile is writable by another account.",
        );
      }
      if (writable && (rootStat.mode & 0o200) === 0) {
        throw storeError(
          "beta_license_store_unwritable",
          "The Realtor Beta profile is not writable by this account.",
        );
      }
      let licenseStat = null;
      try {
        licenseStat = fsImpl.lstatSync(resolvedLicensePath);
      } catch (err) {
        if (!err || err.code !== "ENOENT") throw err;
      }
      if (licenseStat) {
        if (
          !licenseStat.isFile() ||
          licenseStat.isSymbolicLink() ||
          licenseStat.nlink !== 1 ||
          (typeof processImpl.getuid === "function" &&
            licenseStat.uid !== processImpl.getuid())
        ) {
          throw storeError(
            "beta_license_store_not_local",
            "Realtor Beta will not use a linked or shared license store.",
          );
        }
        if ((licenseStat.mode & 0o077) !== 0) {
          throw storeError(
            "beta_license_store_not_private",
            "The Realtor Beta account snapshot is readable by another account.",
          );
        }
      }
      if (writable) {
        const probe = path.join(
          resolvedProfileRoot,
          `.license-preflight-${crypto.randomUUID()}`,
        );
        let fd = null;
        let probeCreated = false;
        try {
          fd = fsImpl.openSync(probe, "wx", 0o600);
          probeCreated = true;
          fsImpl.writeSync(fd, "ok");
          fsImpl.fsyncSync(fd);
          fsImpl.closeSync(fd);
          fd = null;
          fsImpl.unlinkSync(probe);
          probeCreated = false;
        } finally {
          if (fd !== null) fsImpl.closeSync(fd);
          if (probeCreated) {
            try {
              fsImpl.unlinkSync(probe);
            } catch {
              // Preserve the original probe failure.
            }
          }
        }
      }
    } catch (err) {
      if (err instanceof DesktopAuthError) throw err;
      throw storeError(
        writable
          ? "beta_license_store_unwritable"
          : "beta_license_store_unavailable",
        "Realtor Beta could not verify its local account store.",
      );
    }
  }

  function normalizeEntitlements(value) {
    let raw = null;
    if (Array.isArray(value)) {
      raw = value;
    } else if (value && typeof value === "object") {
      raw = Object.entries(value)
        .filter(([, enabled]) => Boolean(enabled))
        .map(([name]) => name);
    } else if (typeof value === "string") {
      raw = value.split(",").map((item) => item.trim());
    }
    if (!raw) return null;
    const aliases = {
      realEstateSales: "real_estate_sales",
      realEstateMarketing: "real_estate_marketing",
      realEstateAdmin: "real_estate_admin",
      realEstateCma: "real_estate_cma",
    };
    return [...new Set(raw.map((item) => aliases[String(item)] || String(item)).filter(Boolean))];
  }

  function extractEntitlements(data) {
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    for (const key of ["entitlements", "packs", "features"]) {
      if (Object.prototype.hasOwnProperty.call(data, key)) {
        return normalizeEntitlements(data[key]);
      }
    }
    return null;
  }

  function validateCompleteLicense(license, { current = true } = {}) {
    if (!isBeta) return license;
    for (const key of ["access_token", "refresh_token"]) {
      if (!String((license && license[key]) || "").trim()) {
        throw storeError(
          "beta_license_snapshot_invalid",
          "The Realtor Beta account snapshot is incomplete.",
        );
      }
    }
    if (!String((license && license.entitlement_assertion) || "").trim()) {
      throw storeError(
        "beta_entitlement_assertion_invalid",
        "The Realtor Beta account snapshot has no signed entitlement assertion.",
      );
    }
    let claims;
    try {
      claims = verifyEntitlementAssertion({
        assertion: license.entitlement_assertion,
        accessToken: license.access_token,
        refreshToken: license.refresh_token,
        keyset: entitlementKeyset,
        requireCurrent: current,
      });
    } catch (error) {
      if (error instanceof EntitlementAssertionError) {
        throw storeError(error.code, error.message);
      }
      throw storeError(
        "beta_entitlement_assertion_invalid",
        "The Realtor Beta entitlement assertion could not be verified.",
      );
    }
    const entitlements = normalizeEntitlements(license.entitlements);
    if (
      !entitlements ||
      JSON.stringify(entitlements) !== JSON.stringify(claims.entitlements) ||
      license.license_id !== claims.license_id ||
      license.email !== claims.email ||
      license.tier !== claims.tier ||
      (Object.prototype.hasOwnProperty.call(license, "expires_at") &&
        Number(license.expires_at) !== claims.exp)
    ) {
      throw storeError(
        "beta_entitlement_assertion_mismatch",
        "The Realtor Beta account snapshot does not match its signed entitlement assertion.",
      );
    }
    license.license_id = claims.license_id;
    license.email = claims.email;
    license.tier = claims.tier;
    license.entitlements = [...claims.entitlements];
    license.expires_at = claims.exp;
    return license;
  }

  function licenseFromResponse(data) {
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      throw storeError(
        "beta_license_response_invalid",
        "Elevation HQ returned an invalid account response.",
      );
    }
    if (!isBeta) return data;
    const license = {
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      entitlement_assertion: data.entitlement_assertion,
      license_id: data.license_id,
      tier: data.tier,
      email: data.email,
      entitlements: extractEntitlements(data),
    };
    return validateCompleteLicense(license, { current: true });
  }

  function readLicenseBytesUnchecked() {
    const flags = fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0);
    let fd = null;
    try {
      fd = fsImpl.openSync(resolvedLicensePath, flags);
      const fileStat = fsImpl.fstatSync(fd);
      if (
        !fileStat.isFile() ||
        fileStat.nlink !== 1 ||
        (fileStat.mode & 0o077) !== 0 ||
        (typeof processImpl.getuid === "function" &&
          fileStat.uid !== processImpl.getuid())
      ) {
        throw storeError(
          "beta_license_store_not_private",
          "Realtor Beta could not verify its private account snapshot.",
        );
      }
      return fsImpl.readFileSync(fd);
    } finally {
      if (fd !== null) fsImpl.closeSync(fd);
    }
  }

  function readLicenseUnchecked() {
    if (!isBeta) {
      return JSON.parse(fsImpl.readFileSync(resolvedLicensePath, "utf8"));
    }
    return JSON.parse(readLicenseBytesUnchecked().toString("utf8"));
  }

  async function responseJson(response) {
    try {
      return await response.json();
    } catch (err) {
      if (isBeta) {
        throw storeError(
          "beta_license_response_invalid",
          "Elevation HQ returned an invalid account response.",
        );
      }
      throw err;
    }
  }

  function readLicense() {
    try {
      preflightLicenseStore({ writable: false });
      const license = readLicenseUnchecked();
      preflightLicenseStore({ writable: false });
      validateCompleteLicense(license, { current: false });
      return license;
    } catch {
      return null;
    }
  }

  function readCurrentLicense() {
    const license = readLicense();
    if (!license) return null;
    try {
      return validateCompleteLicense(license, { current: true });
    } catch {
      return null;
    }
  }

  function atomicBetaReplace(bytes) {
    const tempPath = path.join(
      resolvedProfileRoot,
      `.license-${crypto.randomUUID()}.tmp`,
    );
    let fd = null;
    let directoryFd = null;
    try {
      fd = fsImpl.openSync(tempPath, "wx", 0o600);
      let offset = 0;
      while (offset < bytes.length) {
        const written = fsImpl.writeSync(fd, bytes, offset, bytes.length - offset);
        if (written <= 0) throw new Error("atomic license write made no progress");
        offset += written;
      }
      fsImpl.fchmodSync(fd, 0o600);
      fsImpl.fsyncSync(fd);
      fsImpl.closeSync(fd);
      fd = null;
      fsImpl.renameSync(tempPath, resolvedLicensePath);
      const persistedStat = fsImpl.lstatSync(resolvedLicensePath);
      if (!persistedStat.isFile() || persistedStat.isSymbolicLink() || persistedStat.nlink !== 1) {
        throw new Error("atomic license target is not private");
      }
      directoryFd = fsImpl.openSync(resolvedProfileRoot, "r");
      fsImpl.fsyncSync(directoryFd);
    } finally {
      if (fd !== null) fsImpl.closeSync(fd);
      if (directoryFd !== null) fsImpl.closeSync(directoryFd);
      try {
        fsImpl.unlinkSync(tempPath);
      } catch {
        // Rename removes the temporary path.
      }
    }
  }

  function writeLicense(license) {
    if (!isBeta) {
      fsImpl.mkdirSync(path.dirname(licensePath), { recursive: true });
      fsImpl.writeFileSync(licensePath, JSON.stringify(license, null, 2), { mode: 0o600 });
      licenseRevision += 1;
      return license;
    }
    validateCompleteLicense(license, { current: true });
    preflightLicenseStore({ writable: true });
    try {
      atomicBetaReplace(Buffer.from(JSON.stringify(license, null, 2)));
      preflightLicenseStore({ writable: false });
      const persisted = readLicenseUnchecked();
      validateCompleteLicense(persisted, { current: true });
      if (JSON.stringify(persisted) !== JSON.stringify(license)) {
        throw storeError(
          "beta_license_persistence_mismatch",
          "Realtor Beta could not verify its saved account snapshot.",
        );
      }
      licenseRevision += 1;
      return persisted;
    } catch (err) {
      try {
        // Never restore the previous paid snapshot after HQ returned a newer
        // one: that older state may be exactly what HQ just revoked.
        clearLicense();
      } catch {
        throw storeError(
          "beta_license_persistence_failed",
          "Realtor Beta could not save or invalidate its account snapshot.",
        );
      }
      if (err instanceof DesktopAuthError) throw err;
      throw storeError(
        "beta_license_persistence_failed",
        "Realtor Beta could not save its account snapshot.",
      );
    }
  }

  function clearLicense() {
    if (!isBeta) {
      try {
        fsImpl.unlinkSync(licensePath);
      } catch {
        // Stable keeps its legacy already-gone behavior.
      }
      licenseRevision += 1;
      return;
    }
    preflightLicenseStore({ writable: true });
    licenseRevision += 1;
    try {
      fsImpl.unlinkSync(resolvedLicensePath);
    } catch (err) {
      if (err && err.code === "ENOENT") return false;
      throw storeError(
        "beta_license_persistence_failed",
        "Realtor Beta could not clear its account snapshot.",
      );
    }
    if (fsImpl.existsSync(resolvedLicensePath)) {
      throw storeError(
        "beta_license_persistence_failed",
        "Realtor Beta could not verify account revocation.",
      );
    }
    try {
      let directoryFd = null;
      try {
        directoryFd = fsImpl.openSync(resolvedProfileRoot, "r");
        fsImpl.fsyncSync(directoryFd);
      } finally {
        if (directoryFd !== null) fsImpl.closeSync(directoryFd);
      }
    } catch (err) {
      throw storeError(
        "beta_license_persistence_failed",
        "Realtor Beta could not durably clear its account snapshot.",
      );
    }
    return true;
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

  function betaRefreshSuperseded(
    attemptedRefreshToken,
    startingRevision,
    operationSequence,
  ) {
    if (!isBeta) return { superseded: false, current: null };
    const current = readLicense();
    return {
      superseded:
        operationSequence !== sessionOperationSequence ||
        licenseRevision !== startingRevision ||
        !current ||
        current.refresh_token !== attemptedRefreshToken,
      current,
    };
  }

  function betaLoginSuperseded({
    operationSequence,
    startingRefreshToken,
    startingRevision,
  }) {
    if (!isBeta) return { superseded: false, current: null };
    const current = readLicense();
    return {
      superseded:
        operationSequence !== sessionOperationSequence ||
        licenseRevision !== startingRevision ||
        (current ? current.refresh_token : null) !== startingRefreshToken,
      current,
    };
  }

  async function refreshLicenseOnce(license) {
    if (!license || !license.refresh_token) return null;
    const attemptedRefreshToken = license.refresh_token;
    const operationSequence = isBeta ? ++sessionOperationSequence : 0;
    const startingRevision = licenseRevision;
    let writeAttempted = false;
    if (isBeta) {
      const current = readLicense();
      if (!current) return null;
      if (current.refresh_token !== attemptedRefreshToken) {
        return current;
      }
    }
    let requestId = "preflight";
    let successfulResponseReceived = false;
    try {
      preflightLicenseStore({ writable: true });
      const request = hqJsonRequestHeaders("license-refresh");
      requestId = request.requestId;
      // Same endpoint the CLI's elevate_cli/license.py refresh() uses, so a
      // session refreshed here is interchangeable with one refreshed by the CLI.
      const res = await fetchImpl(`${effectiveHqBaseUrl}/api/license/refresh`, {
        method: "POST",
        headers: request.headers,
        ...(isBeta ? { redirect: "error" } : {}),
        body: JSON.stringify({ refresh_token: attemptedRefreshToken }),
      });
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        log.warn(
          `[license] refresh failed request_id=${requestId}: HTTP ${res.status} ${body.slice(0, 200)}`,
        );
        if (isBeta && (res.status === 401 || res.status === 402)) {
          const state = betaRefreshSuperseded(
            attemptedRefreshToken,
            startingRevision,
            operationSequence,
          );
          if (state.superseded) return state.current;
          clearLicense();
          throw storeError(
            "beta_license_revoked",
            "The Realtor Beta account session was revoked. Sign in again.",
          );
        }
        if (isBeta) {
          throw storeError(
            "beta_auth_upstream_failed",
            `Elevation HQ could not refresh the account session (${res.status}).`,
          );
        }
        return null;
      }
      successfulResponseReceived = true;
      const data = await responseJson(res);
      if (!data || !data.access_token || !data.refresh_token) {
        if (isBeta) {
          throw storeError(
            "beta_license_response_invalid",
            "Elevation HQ returned an incomplete refresh response.",
          );
        }
        log.warn(`[license] refresh response missing tokens request_id=${requestId}`);
        return null;
      }
      const next = isBeta
        ? licenseFromResponse(data)
        : {
            ...license,
            access_token: data.access_token,
            refresh_token: data.refresh_token,
            license_id: data.license_id || license.license_id,
            tier: data.tier || license.tier,
            entitlements: data.entitlements || license.entitlements,
            expires_at: decodeJwtExp(data.access_token),
          };
      if (isBeta) {
        const state = betaRefreshSuperseded(
          attemptedRefreshToken,
          startingRevision,
          operationSequence,
        );
        if (state.superseded) return state.current;
      }
      writeAttempted = true;
      const persisted = writeLicense(next);
      log.info(`[license] refresh succeeded request_id=${requestId}`);
      return persisted;
    } catch (err) {
      const code = err && err.code ? ` code=${err.code}` : "";
      log.warn(
        `[license] refresh threw request_id=${requestId}${code}: ${err && err.message ? err.message : err}`,
      );
      if (isBeta) {
        if (err instanceof DesktopAuthError && err.code === "beta_license_revoked") {
          throw err;
        }
        const state = betaRefreshSuperseded(
          attemptedRefreshToken,
          startingRevision,
          operationSequence,
        );
        if (state.superseded && !writeAttempted) return state.current;
        if (successfulResponseReceived) {
          try {
            clearLicense();
          } catch (invalidateError) {
            if (invalidateError instanceof DesktopAuthError) {
              throw invalidateError;
            }
            throw storeError(
              "beta_license_persistence_failed",
              "Realtor Beta could not invalidate incomplete refresh state.",
            );
          }
        }
        if (err instanceof DesktopAuthError) throw err;
        throw storeError(
          "beta_auth_upstream_unavailable",
          "Elevation HQ could not be reached to refresh the account session.",
        );
      }
      return null;
    }
  }

  function refreshLicense(license) {
    if (!isBeta) return refreshLicenseOnce(license);
    if (loginInFlight > 0) return Promise.resolve(readCurrentLicense());
    if (refreshInFlight) return refreshInFlight;
    const pending = refreshLicenseOnce(license);
    const wrapped = pending.finally(() => {
      if (refreshInFlight === wrapped) refreshInFlight = null;
    });
    refreshInFlight = wrapped;
    return wrapped;
  }

  async function refreshLicenseWithRetry(license, attempts = 3) {
    let lastError = null;
    for (let i = 0; i < attempts; i++) {
      try {
        const next = await refreshLicense(license);
        if (next) return next;
      } catch (err) {
        lastError = err;
        const retryable = [
          "beta_auth_upstream_failed",
          "beta_auth_upstream_unavailable",
        ].includes(err && err.code);
        if (!retryable || i >= attempts - 1) throw err;
      }
      if (i < attempts - 1) {
        await new Promise((r) => setTimeout(r, 1000 * (i + 1)));
      }
    }
    if (lastError) throw lastError;
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
      return {
        ok: false,
        activation_complete: false,
        code: "auth_input_required",
        error: "Email and password are required.",
      };
    }
    let requestId = "preflight";
    let operationSequence = 0;
    let registeredLogin = false;
    let startingRefreshToken = null;
    let startingRevision = licenseRevision;
    try {
      preflightLicenseStore({ writable: true });
      if (isBeta) {
        const current = readLicense();
        startingRefreshToken = current ? current.refresh_token : null;
        startingRevision = licenseRevision;
        loginInFlight += 1;
        registeredLogin = true;
        operationSequence = ++sessionOperationSequence;
      }
      const request = hqJsonRequestHeaders("auth-login");
      requestId = request.requestId;
      const res = await fetchImpl(`${effectiveHqBaseUrl}/api/auth/login`, {
        method: "POST",
        headers: request.headers,
        ...(isBeta ? { redirect: "error" } : {}),
        body: JSON.stringify({
          email: String(email).trim().toLowerCase(),
          password,
          device_label: `Elevate Desktop (${os.hostname()})`,
        }),
      });

      if (res.status === 401) {
        log.warn(`[auth] login rejected request_id=${requestId}: HTTP 401`);
        return {
          ok: false,
          activation_complete: false,
          code: "invalid_credentials",
          error: "Email or password is wrong.",
        };
      }
      if (res.status === 402) {
        log.warn(`[auth] login rejected request_id=${requestId}: HTTP 402`);
        return {
          ok: false,
          activation_complete: false,
          code: "subscription_inactive",
          error: "Your account has no active subscription. Upgrade in your browser, then sign in.",
        };
      }
      if (!res.ok) {
        const text = await res.text();
        log.warn(`[auth] login failed request_id=${requestId}: HTTP ${res.status} ${text.slice(0, 160)}`);
        return {
          ok: false,
          activation_complete: false,
          code: "auth_upstream_failed",
          error: `Sign-in failed (${res.status}): ${text.slice(0, 160)}`,
        };
      }

      const data = await responseJson(res);
      const license = isBeta
        ? licenseFromResponse(data)
        : {
            access_token: data.access_token,
            refresh_token: data.refresh_token,
            license_id: data.license_id,
            tier: data.tier,
            email: String(email).trim().toLowerCase(),
            expires_at: decodeJwtExp(data.access_token),
            entitlements: data.entitlements || [],
          };
      if (isBeta && betaLoginSuperseded({
        operationSequence,
        startingRefreshToken,
        startingRevision,
      }).superseded) {
        return {
          ok: false,
          activation_complete: false,
          code: "beta_auth_superseded",
          error: "A newer account session replaced this sign-in attempt.",
        };
      }
      const persisted = writeLicense(license);
      log.info(`[auth] login succeeded request_id=${requestId}`);
      return { ok: true, activation_complete: true, license: persisted };
    } catch (err) {
      const failure = err;
      const code = failure && failure.code
        ? failure.code
        : isBeta
          ? "beta_auth_upstream_unavailable"
          : "desktop_auth_failed";
      log.warn(
        `[auth] login threw request_id=${requestId} code=${code}: ${failure && failure.message ? failure.message : failure}`,
      );
      return {
        ok: false,
        activation_complete: false,
        code,
        error:
          failure instanceof DesktopAuthError
            ? failure.message
            : `Could not reach ${effectiveHqBaseUrl}. Check your connection and try again.`,
      };
    } finally {
      if (registeredLogin) loginInFlight -= 1;
    }
  }

  return {
    clearLicense,
    decodeJwtExp,
    ensureValidLicense,
    hqJsonRequestHeaders,
    preflightLicenseStore,
    performLogin,
    readLicense,
    refreshLicense,
    refreshLicenseWithRetry,
    writeLicense,
  };
}

module.exports = {
  DesktopAuthError,
  SIGNED_HQ_BASE_URL,
  createDesktopAuth,
  decodeJwtExp,
};
