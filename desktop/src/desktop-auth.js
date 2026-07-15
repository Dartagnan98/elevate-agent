const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const {
  EntitlementAssertionError,
  productionKeyset,
  verifyEntitlementAssertion,
} = require("./entitlement-assertion");
const {
  RefreshPendingError,
  createRefreshPendingStore,
  initialAuthPendingMatches,
  isInitialAuthPending,
} = require("./refresh-pending");

const SIGNED_HQ_BASE_URL = "https://api.elevationrealestatehq.com";
const SIGNED_SUBJECT = Symbol("signed-entitlement-subject");
const INVALID_SNAPSHOT = Symbol("invalid-license-snapshot");

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
  authRequestTimeoutMs = 15_000,
  fetchImpl = globalThis.fetch,
  fsImpl = fs,
  env = process.env,
  processImpl = process,
  entitlementKeyset = productionKeyset(),
  refreshLockTimeoutMs = 30_000,
  refreshLockfPath = "/usr/bin/lockf",
  spawnImpl,
}) {
  const effectiveHqBaseUrl = (
    isBeta ? SIGNED_HQ_BASE_URL : hqBaseUrl || SIGNED_HQ_BASE_URL
  ).replace(/\/+$/, "");
  const resolvedProfileRoot = path.resolve(profileRoot);
  const resolvedLicensePath = path.resolve(licensePath);
  const resolvedActivationReceiptPath = path.join(
    resolvedProfileRoot,
    ".license-activation.json",
  );
  const expectedBetaProfileRoot = path.resolve(home, ".elevate-beta");
  let licenseRevision = 0;
  let loginInFlight = 0;
  let refreshInFlight = null;
  let sessionOperationSequence = 0;
  const refreshPending = isBeta
    ? createRefreshPendingStore({
        root: resolvedProfileRoot,
        fsImpl,
        processImpl,
        ...(spawnImpl ? { spawnImpl } : {}),
        lockfPath: refreshLockfPath,
        lockTimeoutMs: refreshLockTimeoutMs,
      })
    : null;

  function storeError(code, message) {
    return new DesktopAuthError(code, message);
  }

  function betaRequestAbort() {
    if (!isBeta) return { signal: undefined, cancel() {} };
    const controller = new AbortController();
    const timeout = setTimeout(
      () => controller.abort(),
      Number.isFinite(authRequestTimeoutMs) && authRequestTimeoutMs > 0
        ? authRequestTimeoutMs
        : 15_000,
    );
    return {
      signal: controller.signal,
      cancel() {
        clearTimeout(timeout);
      },
    };
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
    Object.defineProperty(license, SIGNED_SUBJECT, {
      value: claims.sub,
      configurable: true,
      enumerable: false,
      writable: true,
    });
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
        if (err && err.name === "AbortError") {
          throw storeError(
            "beta_auth_upstream_unavailable",
            "Elevation HQ did not finish the account response in time.",
          );
        }
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

  function readBetaLicenseStrict({ current = false } = {}) {
    preflightLicenseStore({ writable: false });
    let license;
    try {
      license = readLicenseUnchecked();
    } catch (err) {
      if (err instanceof DesktopAuthError) throw err;
      throw storeError(
        "beta_license_snapshot_invalid",
        "The Realtor Beta account snapshot is missing or unreadable.",
      );
    }
    preflightLicenseStore({ writable: false });
    return validateCompleteLicense(license, { current });
  }

  function sameSignedSnapshot(left, right) {
    return Boolean(
      left &&
      right &&
      left.access_token === right.access_token &&
      left.refresh_token === right.refresh_token &&
      left.license_id === right.license_id &&
      left.entitlement_assertion === right.entitlement_assertion &&
      left[SIGNED_SUBJECT] === right[SIGNED_SUBJECT]
    );
  }

  function invalidSnapshotFingerprint(bytes) {
    const fingerprint = {
      sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
      size: bytes.length,
    };
    Object.defineProperty(fingerprint, INVALID_SNAPSHOT, {
      value: true,
      enumerable: false,
    });
    return Object.freeze(fingerprint);
  }

  function isInvalidSnapshot(value) {
    return Boolean(value && value[INVALID_SNAPSHOT]);
  }

  function readBetaLocalSnapshotState() {
    preflightLicenseStore({ writable: false });
    if (!fsImpl.existsSync(resolvedLicensePath)) return null;
    let bytes;
    try {
      bytes = readLicenseBytesUnchecked();
    } catch (err) {
      if (err && err.code === "ENOENT") return null;
      throw err;
    }
    preflightLicenseStore({ writable: false });
    const fingerprint = invalidSnapshotFingerprint(bytes);
    let parsed;
    try {
      parsed = JSON.parse(bytes.toString("utf8"));
      return validateCompleteLicense(parsed, { current: false });
    } catch (err) {
      if (
        err instanceof DesktopAuthError &&
        err.code === "beta_entitlement_verifier_unavailable"
      ) {
        throw err;
      }
      return fingerprint;
    }
  }

  function sameLocalSnapshotState(left, right) {
    if (left === null || right === null) return left === null && right === null;
    if (isInvalidSnapshot(left) || isInvalidSnapshot(right)) {
      return Boolean(
        isInvalidSnapshot(left) &&
        isInvalidSnapshot(right) &&
        left.sha256 === right.sha256 &&
        left.size === right.size
      );
    }
    return sameSignedSnapshot(left, right);
  }

  function sameSignedIdentity(left, right) {
    return Boolean(
      left &&
      right &&
      left.license_id === right.license_id &&
      left.email === right.email &&
      left[SIGNED_SUBJECT] === right[SIGNED_SUBJECT]
    );
  }

  function reconciliationOutcome(status, license = null, pending = null) {
    return Object.freeze({ status, license, pending });
  }

  function verifyDesktopEntitlementMirror(license, { current = true } = {}) {
    const persisted = readBetaLicenseStrict({ current });
    if (JSON.stringify(persisted) !== JSON.stringify(license)) {
      throw storeError(
        "beta_entitlement_persistence_mismatch",
        "The Realtor Beta entitlement mirror did not match its signed account snapshot.",
      );
    }
    return persisted;
  }

  function readCredentialMarkersStrict() {
    const pendingRefresh = refreshPending.read();
    const pendingDevice = refreshPending.readDevice();
    if (pendingRefresh && pendingDevice) {
      throw storeError(
        "beta_device_state_conflict",
        "Realtor Beta found overlapping credential transitions. No account state was changed.",
      );
    }
    return { pendingRefresh, pendingDevice };
  }

  function removeExactDevicePending(pendingDevice, {
    failureCode,
    failureMessage,
  }) {
    if (!refreshPending.removeDevice(pendingDevice)) {
      throw storeError(failureCode, failureMessage);
    }
  }

  function reconcileDevicePendingUnlocked(guard) {
    const { pendingDevice } = readCredentialMarkersStrict();
    if (!pendingDevice) return reconciliationOutcome("none");
    if (!fsImpl.existsSync(resolvedLicensePath)) {
      return reconciliationOutcome("pending", null, pendingDevice);
    }

    const historical = readBetaLicenseStrict({ current: false });
    const belongsToDevice = [
      pendingDevice.initial_refresh_token,
      pendingDevice.recovery_refresh_token,
    ].includes(historical.refresh_token);
    if (belongsToDevice) {
      const current = readBetaLicenseStrict({ current: true });
      verifyDesktopEntitlementMirror(current, { current: true });
      guard.assertHeld();
      removeExactDevicePending(pendingDevice, {
        failureCode: "beta_auth_superseded",
        failureMessage:
          "A newer Realtor Beta Device authorization replaced the recovery state before it could be completed.",
      });
      return reconciliationOutcome("already_persisted", current);
    }

    // A different signature-verified token is a later explicit auth commit.
    // Historical validity is sufficient so normal expiry cannot strand a
    // stale Device marker. Paid access remains fail-closed while expired;
    // readiness refreshes and validates the current entitlement projection.
    guard.assertHeld();
    removeExactDevicePending(pendingDevice, {
      failureCode: "beta_auth_superseded",
      failureMessage:
        "A newer Realtor Beta Device authorization replaced the stale recovery state.",
    });
    return reconciliationOutcome("beta_auth_superseded", historical);
  }

  function reconcileDevicePending() {
    if (!isBeta) return Promise.resolve(reconciliationOutcome("none"));
    preflightLicenseStore({ writable: true });
    return refreshPending
      .withLock(async (guard) => {
        preflightLicenseStore({ writable: true });
        guard.assertHeld();
        return reconcileDevicePendingUnlocked(guard);
      })
      .catch((err) => {
        if (err instanceof RefreshPendingError) {
          throw storeError(err.code, err.message);
        }
        throw err;
      });
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

  function writeLicenseUnlocked(license, { startingSnapshot = null } = {}) {
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
        // one: that older state may be exactly what HQ just revoked. A valid
        // different signed snapshot, however, is a newer concurrent winner
        // and must never be erased by this late failure.
        const installed = readBetaLocalSnapshotState();
        if (
          (isInvalidSnapshot(installed) && !isInvalidSnapshot(startingSnapshot)) ||
          sameLocalSnapshotState(installed, license) ||
          sameLocalSnapshotState(installed, startingSnapshot)
        ) {
          clearLicenseUnlocked();
        }
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

  function persistBetaRefreshSnapshot(license, expected, guard) {
    validateCompleteLicense(license, { current: true });
    const current = readBetaLicenseStrict({ current: false });
    if (!sameSignedSnapshot(current, expected)) return current;
    try {
      guard.assertHeld();
      atomicBetaReplace(Buffer.from(JSON.stringify(license, null, 2)));
      preflightLicenseStore({ writable: false });
      const persisted = readBetaLicenseStrict({ current: true });
      if (JSON.stringify(persisted) !== JSON.stringify(license)) {
        throw storeError(
          "beta_license_persistence_mismatch",
          "Realtor Beta could not verify its saved refresh snapshot.",
        );
      }
      licenseRevision += 1;
      return persisted;
    } catch (err) {
      // Never clear A or B here. A/B/I is the recovery record after HQ may
      // have rotated, and a verified B may already be durably installed.
      if (err instanceof DesktopAuthError) throw err;
      throw storeError(
        "beta_license_persistence_failed",
        "Realtor Beta could not durably save its refreshed account snapshot.",
      );
    }
  }

  function clearLicenseUnlocked() {
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

  function clearActivationReceiptUnlocked() {
    if (!isBeta) return false;
    let removed = false;
    try {
      fsImpl.unlinkSync(resolvedActivationReceiptPath);
      removed = true;
    } catch (err) {
      if (!err || err.code !== "ENOENT") {
        throw storeError(
          "beta_activation_receipt_failed",
          "Realtor Beta could not clear required setup completion.",
        );
      }
    }
    if (fsImpl.existsSync(resolvedActivationReceiptPath)) {
      throw storeError(
        "beta_activation_receipt_failed",
        "Realtor Beta could not verify required setup revocation.",
      );
    }
    if (removed) {
      let directoryFd = null;
      try {
        directoryFd = fsImpl.openSync(resolvedProfileRoot, "r");
        fsImpl.fsyncSync(directoryFd);
      } catch {
        throw storeError(
          "beta_activation_receipt_failed",
          "Realtor Beta could not durably clear required setup completion.",
        );
      } finally {
        if (directoryFd !== null) fsImpl.closeSync(directoryFd);
      }
    }
    return removed;
  }

  function invalidateBetaSnapshotIfMatchesUnlocked(...expectedSnapshots) {
    const current = readBetaLocalSnapshotState();
    if (current === null) return false;
    if (!expectedSnapshots.some(
      (expected) => expected && sameLocalSnapshotState(current, expected),
    )) return false;
    clearLicenseUnlocked();
    return true;
  }

  function writeLicense(license, options) {
    if (!isBeta) return writeLicenseUnlocked(license);
    const expected = options?.expected ?? null;
    preflightLicenseStore({ writable: true });
    return refreshPending
      .withLock(async (guard) => {
        guard.assertHeld();
        validateCompleteLicense(license, { current: true });
        const pending = refreshPending.read();
        const current = fsImpl.existsSync(resolvedLicensePath)
          ? readBetaLicenseStrict({ current: false })
          : null;
        if (!current) {
          if (expected) {
            throw storeError(
              "beta_auth_superseded",
              "A newer Realtor Beta session removed this account snapshot.",
            );
          }
        } else if (!sameSignedSnapshot(current, license)) {
          if (!expected) {
            throw storeError(
              "beta_auth_superseded",
              "A newer Realtor Beta session replaced this account snapshot.",
            );
          }
          validateCompleteLicense(expected, { current: false });
          if (!sameSignedSnapshot(current, expected)) {
            throw storeError(
              "beta_auth_superseded",
              "A newer Realtor Beta session replaced this account snapshot.",
            );
          }
        }
        guard.assertHeld();
        const persisted = writeLicenseUnlocked(license, {
          startingSnapshot: current,
        });
        if (
          pending &&
          !(
            persisted.license_id === pending.license_id &&
            persisted.refresh_token === pending.current_refresh_token
          )
        ) {
          guard.assertHeld();
          refreshPending.remove();
        }
        return persisted;
      })
      .catch((err) => {
        if (err instanceof RefreshPendingError) {
          throw storeError(err.code, err.message);
        }
        throw err;
      });
  }

  function clearLicense() {
    if (!isBeta) return clearLicenseUnlocked();
    preflightLicenseStore({ writable: true });
    return refreshPending
      .withLock(async (guard) => {
        guard.assertHeld();
        let cleared = false;
        let cleanupFailure = null;
        try {
          cleared = clearLicenseUnlocked();
        } catch (err) {
          cleanupFailure = err;
        }
        try {
          guard.assertHeld();
          const pending = refreshPending.read();
          if (pending) {
            guard.assertHeld();
            refreshPending.remove();
          }
        } catch (err) {
          cleanupFailure = err;
        }
        try {
          guard.assertHeld();
          const pendingDevice = refreshPending.readDevice();
          if (pendingDevice) {
            guard.assertHeld();
            removeExactDevicePending(pendingDevice, {
              failureCode: "beta_device_state_superseded",
              failureMessage:
                "A newer Realtor Beta Device authorization replaced the state being cleared.",
            });
          }
        } catch (err) {
          if (!cleanupFailure) cleanupFailure = err;
        }
        try {
          guard.assertHeld();
          clearActivationReceiptUnlocked();
        } catch (err) {
          if (!cleanupFailure) cleanupFailure = err;
        }
        if (cleanupFailure) throw cleanupFailure;
        return cleared;
      })
      .catch((err) => {
        if (err instanceof RefreshPendingError) {
          throw storeError(err.code, err.message);
        }
        throw err;
      });
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

  async function refreshBetaLicenseOnce(license) {
    if (!license || !license.refresh_token) return null;
    ++sessionOperationSequence;
    let requestId = "preflight";
    try {
      preflightLicenseStore({ writable: true });
      return await refreshPending.withLock(async (guard) => {
        preflightLicenseStore({ writable: true });
        let current = readBetaLicenseStrict({ current: false });
        let pending = refreshPending.read();

        if (pending && isInitialAuthPending(pending)) {
          // A complete signed snapshot is an authoritative later commit. It
          // safely supersedes a pre-license initial-auth marker left behind by
          // a discarded response or another runtime.
          guard.assertHeld();
          refreshPending.remove();
          pending = null;
        }

        if (pending) {
          if (
            current.license_id !== pending.license_id ||
            ![
              pending.current_refresh_token,
              pending.successor_refresh_token,
            ].includes(current.refresh_token)
          ) {
            guard.assertHeld();
            refreshPending.remove();
            return current;
          }
          if (current.refresh_token === pending.successor_refresh_token) {
            try {
              validateCompleteLicense(current, { current: true });
            } catch (err) {
              if (
                !(err instanceof DesktopAuthError) ||
                err.code !== "beta_entitlement_assertion_expired"
              ) {
                throw err;
              }
              // Historical signed B needs the exact A/B/I replay to mint a
              // fresh assertion; it must not strand the durable marker.
            }
            if (Number(current.expires_at) * 1000 > Date.now()) {
              guard.assertHeld();
              refreshPending.remove();
              return current;
            }
          }
        } else {
          if (!sameSignedSnapshot(current, license)) return current;
          pending = refreshPending.create({
            licenseId: current.license_id,
            currentRefreshToken: current.refresh_token,
          });
        }

        const abort = betaRequestAbort();
        try {
          guard.assertHeld();
          const request = hqJsonRequestHeaders("license-refresh");
          requestId = request.requestId;
          const res = await fetchImpl(`${effectiveHqBaseUrl}/api/license/refresh`, {
            method: "POST",
            headers: request.headers,
            redirect: "error",
            signal: abort.signal,
            body: JSON.stringify({
              refresh_token: pending.current_refresh_token,
              next_refresh_token: pending.successor_refresh_token,
              refresh_attempt_id: pending.attempt_id,
            }),
          });

          if (!res.ok) {
            log.warn(
              `[license] refresh failed request_id=${requestId}: HTTP ${res.status}`,
            );
            if (res.status === 401 || res.status === 402) {
              const latest = readBetaLicenseStrict({ current: false });
              if (!sameSignedSnapshot(latest, current)) {
                guard.assertHeld();
                refreshPending.remove();
                return latest;
              }
              guard.assertHeld();
              clearLicenseUnlocked();
              refreshPending.remove();
              throw storeError(
                "beta_license_revoked",
                "The Realtor Beta account session was revoked. Sign in again.",
              );
            }
            if (res.status >= 400 && res.status < 500) {
              throw storeError(
                "beta_refresh_protocol_rejected",
                "Elevation HQ rejected the recoverable refresh protocol. " +
                  "The existing session and retry state were preserved; " +
                  "Realtor Beta will not downgrade this attempt.",
              );
            }
            throw storeError(
              "beta_auth_upstream_failed",
              `Elevation HQ could not refresh the account session (${res.status}).`,
            );
          }

          const data = await responseJson(res);
          if (!data || !data.access_token || !data.refresh_token) {
            throw storeError(
              "beta_license_response_invalid",
              "Elevation HQ returned an incomplete refresh response.",
            );
          }
          const next = licenseFromResponse(data);
          if (!sameSignedIdentity(current, next)) {
            throw storeError(
              "beta_entitlement_response_mismatch",
              "The refreshed Realtor Beta account changed signed identity.",
            );
          }
          if (next.refresh_token !== pending.successor_refresh_token) {
            throw storeError(
              "beta_refresh_successor_mismatch",
              "Elevation HQ returned a refresh token that did not match " +
                "the protected Beta refresh attempt.",
            );
          }

          const latest = readBetaLicenseStrict({ current: false });
          if (!sameSignedSnapshot(latest, current)) {
            if (
              latest.license_id === pending.license_id &&
              latest.refresh_token === pending.successor_refresh_token
            ) {
              validateCompleteLicense(latest, { current: true });
            }
            guard.assertHeld();
            refreshPending.remove();
            return latest;
          }

          const persisted = persistBetaRefreshSnapshot(next, current, guard);
          if (!sameSignedSnapshot(persisted, next)) {
            guard.assertHeld();
            refreshPending.remove();
            return persisted;
          }
          guard.assertHeld();
          refreshPending.remove();
          log.info(`[license] refresh succeeded request_id=${requestId}`);
          return persisted;
        } finally {
          abort.cancel();
        }
      });
    } catch (err) {
      const failure = err instanceof RefreshPendingError
        ? storeError(err.code, err.message)
        : err;
      const code = failure && failure.code ? ` code=${failure.code}` : "";
      log.warn(
        `[license] refresh threw request_id=${requestId}${code}: ${failure && failure.message ? failure.message : failure}`,
      );
      if (failure instanceof DesktopAuthError) throw failure;
      throw storeError(
        "beta_auth_upstream_unavailable",
        "Elevation HQ could not be reached to refresh the account session.",
      );
    }
  }

  async function refreshLicenseOnce(license) {
    if (isBeta) return refreshBetaLicenseOnce(license);
    if (!license || !license.refresh_token) return null;
    const attemptedRefreshToken = license.refresh_token;
    const operationSequence = isBeta ? ++sessionOperationSequence : 0;
    const startingRevision = licenseRevision;
    const abort = betaRequestAbort();
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
        ...(isBeta ? { redirect: "error", signal: abort.signal } : {}),
        body: JSON.stringify({ refresh_token: attemptedRefreshToken }),
      });
      if (!res.ok) {
        const body = isBeta ? "" : await res.text().catch(() => "");
        log.warn(
          isBeta
            ? `[license] refresh failed request_id=${requestId}: HTTP ${res.status}`
            : `[license] refresh failed request_id=${requestId}: HTTP ${res.status} ${body.slice(0, 200)}`,
        );
        if (isBeta && (res.status === 401 || res.status === 402)) {
          const state = betaRefreshSuperseded(
            attemptedRefreshToken,
            startingRevision,
            operationSequence,
          );
          if (state.superseded) return state.current;
          await clearLicense();
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
      const persisted = await writeLicense(next);
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
            await clearLicense();
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
    } finally {
      abort.cancel();
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
    const reconciliation = isBeta ? await reconcileDevicePending() : null;
    let license = reconciliation && reconciliation.license
      ? reconciliation.license
      : readLicense();
    if (!license || !license.access_token) return null;

    const expMs = (Number(license.expires_at) || 0) * 1000;
    if (!Number.isFinite(expMs) || Date.now() > expMs - accessRefreshMarginMs) {
      license = retry
        ? await refreshLicenseWithRetry(license)
        : await refreshLicense(license);
    }
    return license;
  }

  function samePendingMarker(left, right) {
    return Boolean(left) && Boolean(right) &&
      JSON.stringify(left) === JSON.stringify(right);
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
    let abort = { signal: undefined, cancel() {} };
    let startingRefreshToken = null;
    let startingSnapshot = null;
    let startingRevision = licenseRevision;
    let initialAuthPending = null;
    let recoverInitialAuth = false;
    let responseWasRecovery = false;
    try {
      if (isBeta && refreshInFlight) {
        try {
          await refreshInFlight;
        } catch {
          // A failed refresh must not prevent an explicit sign-in attempt.
        }
      }
      preflightLicenseStore({ writable: true });
      const requestedEmail = String(email).trim().toLowerCase();
      if (isBeta) {
        const prepared = await refreshPending.withLock(async (guard) => {
          guard.assertHeld();
          const snapshot = readBetaLocalSnapshotState();
          if (snapshot !== null && !isInvalidSnapshot(snapshot)) {
            throw storeError(
              "beta_auth_sign_out_required",
              "Sign out of the current Realtor Beta account before starting another email-and-password sign-in.",
            );
          }
          let deviceTransitionExists = false;
          try {
            fsImpl.lstatSync(refreshPending.deviceMarkerPath);
            deviceTransitionExists = true;
          } catch (err) {
            if (!err || err.code !== "ENOENT") deviceTransitionExists = true;
          }
          if (deviceTransitionExists) {
            throw storeError(
              "beta_auth_transition_conflict",
              "Finish or cancel the pending Realtor Beta Device sign-in before using email and password.",
            );
          }
          const pendingRefresh = refreshPending.read();
          if (
            pendingRefresh &&
            initialAuthPendingMatches(pendingRefresh, requestedEmail, {
              authKind: "login",
            })
          ) {
            return {
              snapshot,
              pending: pendingRefresh,
              recover: true,
            };
          }
          if (!pendingRefresh) {
            guard.assertHeld();
            return {
              snapshot,
              pending: refreshPending.createInitialAuth({
                email: requestedEmail,
                authKind: "login",
              }),
              recover: false,
            };
          }
          throw storeError(
            "beta_auth_transition_conflict",
            isInitialAuthPending(pendingRefresh)
              ? "A different Realtor Beta password sign-in is awaiting recovery. Finish it with the same email and Sign in/Create account action before starting another one."
              : "Realtor Beta is already recovering another account session. Let it finish before signing in with a password.",
          );
        });
        startingSnapshot = prepared.snapshot;
        initialAuthPending = prepared.pending;
        recoverInitialAuth = prepared.recover;
        loginInFlight += 1;
        registeredLogin = true;
        operationSequence = ++sessionOperationSequence;
        startingRefreshToken =
          startingSnapshot && !isInvalidSnapshot(startingSnapshot)
            ? startingSnapshot.refresh_token
            : null;
        startingRevision = licenseRevision;
      }

      const postBeta = async (pathName, scope, body) => {
        abort.cancel();
        abort = betaRequestAbort();
        const request = hqJsonRequestHeaders(scope);
        requestId = request.requestId;
        return fetchImpl(`${effectiveHqBaseUrl}${pathName}`, {
          method: "POST",
          headers: request.headers,
          redirect: "error",
          signal: abort.signal,
          body: JSON.stringify(body),
        });
      };

      let res = null;
      if (isBeta && recoverInitialAuth) {
        try {
          const recovery = await postBeta(
            "/api/license/refresh",
            "auth-initial-recovery",
            {
              refresh_token: initialAuthPending.current_refresh_token,
              next_refresh_token: initialAuthPending.successor_refresh_token,
              refresh_attempt_id: initialAuthPending.attempt_id,
            },
          );
          if (recovery.ok) {
            res = recovery;
            responseWasRecovery = true;
          } else if (recovery.status === 401) {
            // HQ definitively rejected B. Password auth may safely retry with
            // the exact same caller-owned token.
          } else if (recovery.status === 402) {
            if (operationSequence === sessionOperationSequence) {
              await refreshPending.withLock(async (guard) => {
                guard.assertHeld();
                const currentPending = refreshPending.read();
                if (samePendingMarker(currentPending, initialAuthPending)) {
                  refreshPending.remove();
                }
              });
            }
            return {
              ok: false,
              activation_complete: false,
              code: "subscription_inactive",
              error: "Your account has no active subscription. Upgrade in your browser, then sign in.",
            };
          } else {
            log.warn(
              `[auth] initial recovery ambiguous request_id=${requestId}: HTTP ${recovery.status}`,
            );
            return {
              ok: false,
              activation_complete: false,
              code: "beta_initial_auth_recovery_ambiguous",
              error: "Realtor Beta could not confirm the pending sign-in. Try again to resume it safely.",
            };
          }
        } catch (recoveryError) {
          const code = recoveryError && recoveryError.code
            ? recoveryError.code
            : "beta_auth_upstream_unavailable";
          log.warn(
            `[auth] initial recovery unavailable request_id=${requestId} code=${code}`,
          );
          return {
            ok: false,
            activation_complete: false,
            code: "beta_initial_auth_recovery_ambiguous",
            error: "Realtor Beta could not confirm the pending sign-in. Try again to resume it safely.",
          };
        }
      }

      if (!res) {
        if (isBeta) {
          res = await postBeta("/api/auth/login", "auth-login", {
            email: requestedEmail,
            password,
            device_label: `Elevate Desktop (${os.hostname()})`,
            initial_refresh_token: initialAuthPending.current_refresh_token,
          });
        } else {
          const request = hqJsonRequestHeaders("auth-login");
          requestId = request.requestId;
          res = await fetchImpl(`${effectiveHqBaseUrl}/api/auth/login`, {
            method: "POST",
            headers: request.headers,
            body: JSON.stringify({
              email: requestedEmail,
              password,
              device_label: `Elevate Desktop (${os.hostname()})`,
            }),
          });
        }
      }

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
        const text = isBeta ? "" : await res.text();
        log.warn(
          isBeta
            ? `[auth] login failed request_id=${requestId}: HTTP ${res.status}`
            : `[auth] login failed request_id=${requestId}: HTTP ${res.status} ${text.slice(0, 160)}`,
        );
        return {
          ok: false,
          activation_complete: false,
          code: "auth_upstream_failed",
          error: isBeta
            ? `Sign-in failed (${res.status}).`
            : `Sign-in failed (${res.status}): ${text.slice(0, 160)}`,
        };
      }

      const data = await responseJson(res);
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
      if (
        isBeta &&
        license.refresh_token !== (
          responseWasRecovery
            ? initialAuthPending.successor_refresh_token
            : initialAuthPending.current_refresh_token
        )
      ) {
        throw storeError(
          "beta_refresh_successor_mismatch",
          "Elevation HQ returned an account token that did not match the protected sign-in recovery.",
        );
      }
      if (isBeta && license.email !== requestedEmail) {
        throw storeError(
          "beta_entitlement_response_mismatch",
          "The signed Realtor Beta account did not match the requested email.",
        );
      }
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
      let persisted;
      if (isBeta) {
        persisted = await refreshPending.withLock(async (guard) => {
          guard.assertHeld();
          let installedBefore = null;
          let saved = null;
          let predecessorAuthorized = false;
          let writeAttempted = false;
          let verifiedCommit = false;
          try {
            installedBefore = readBetaLocalSnapshotState();
            const predecessorMatches = sameLocalSnapshotState(
              installedBefore,
              startingSnapshot,
            );
            if (!predecessorMatches) {
              throw storeError(
                "beta_auth_superseded",
                "A newer account session replaced this sign-in attempt.",
              );
            }
            predecessorAuthorized = true;
            const { pendingRefresh, pendingDevice } = readCredentialMarkersStrict();
            if (!samePendingMarker(pendingRefresh, initialAuthPending)) {
              // A cross-process cancel/replacement owns the local transition.
              // Never install this stale HQ result or erase the newer marker.
              predecessorAuthorized = false;
              throw storeError(
                "beta_auth_superseded",
                "A newer Realtor Beta sign-in replaced this attempt.",
              );
            }
            guard.assertHeld();
            writeAttempted = true;
            saved = writeLicenseUnlocked(license, {
              startingSnapshot: installedBefore,
            });
            const verified = verifyDesktopEntitlementMirror(saved, { current: true });
            // The signed account is now the authoritative commit. Cleanup
            // durability failures may leave retry state behind or report an
            // error, but must not erase the verified account after the marker
            // was already unlinked.
            verifiedCommit = true;
            if (pendingRefresh) {
              guard.assertHeld();
              refreshPending.remove();
            }
            if (pendingDevice) {
              guard.assertHeld();
              removeExactDevicePending(pendingDevice, {
                failureCode: "beta_auth_superseded",
                failureMessage:
                  "A newer Realtor Beta Device authorization superseded this sign-in result.",
              });
            }
            return verified;
          } catch (err) {
            if (predecessorAuthorized && !verifiedCommit) {
              guard.assertHeld();
              try {
                invalidateBetaSnapshotIfMatchesUnlocked(
                  ...(writeAttempted ? [license] : []),
                  startingSnapshot,
                );
              } catch {
                throw storeError(
                  "beta_license_persistence_failed",
                  "Realtor Beta could not roll back an incomplete sign-in.",
                );
              }
            }
            throw err;
          }
        });
      } else {
        persisted = writeLicenseUnlocked(license);
      }
      log.info(`[auth] login succeeded request_id=${requestId}`);
      return { ok: true, activation_complete: true, license: persisted };
    } catch (err) {
      const failure = err instanceof RefreshPendingError
        ? storeError(err.code, err.message)
        : err;
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
      abort.cancel();
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
    reconcileDevicePending,
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
