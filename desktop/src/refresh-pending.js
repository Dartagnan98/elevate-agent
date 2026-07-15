"use strict";

// Shared with cli/elevate_cli/refresh_pending.py. Keep names and schemas exact:
// both runtimes coordinate through the same BSD flock and durable markers.
const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const LOCK_NAME = ".license-refresh.lock";
const MARKER_NAME = ".license-refresh-pending.json";
const DEVICE_MARKER_NAME = ".license-device-pending.json";
const READY_LINE = "ELEVATE_REFRESH_LOCK_READY_V1\n";
const MAX_MARKER_BYTES = 16 * 1024;
const SCHEMA_KEYS = [
  "attempt_id",
  "created_at",
  "current_refresh_token",
  "license_id",
  "operation",
  "schema",
  "successor_refresh_token",
];
const DEVICE_SCHEMA_KEYS = [
  "created_at",
  "device_code",
  "initial_refresh_token",
  "operation",
  "recovery_attempt_id",
  "recovery_refresh_token",
  "schema",
];

class RefreshPendingError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "RefreshPendingError";
    this.code = code;
  }
}

function canonicalToken32(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(value)) {
    return false;
  }
  try {
    const decoded = Buffer.from(value, "base64url");
    return decoded.length === 32 && decoded.toString("base64url") === value;
  } catch {
    return false;
  }
}

function generateToken32() {
  return crypto.randomBytes(32).toString("base64url");
}

function scanJsonString(text, start) {
  let index = start + 1;
  while (index < text.length) {
    if (text[index] === "\\") {
      index += 2;
      continue;
    }
    if (text[index] === '"') {
      const end = index + 1;
      return { value: JSON.parse(text.slice(start, end)), end };
    }
    index += 1;
  }
  throw new SyntaxError("unterminated JSON string");
}

function skipWhitespace(text, start) {
  let index = start;
  while (/\s/.test(text[index] || "")) index += 1;
  return index;
}

function skipJsonValue(text, start) {
  if (text[start] === '"') return scanJsonString(text, start).end;
  if (text[start] !== "{" && text[start] !== "[") {
    let index = start;
    while (index < text.length && text[index] !== "," && text[index] !== "}") {
      index += 1;
    }
    return index;
  }
  const closes = [];
  let index = start;
  while (index < text.length) {
    const char = text[index];
    if (char === '"') {
      index = scanJsonString(text, index).end;
      continue;
    }
    if (char === "{" || char === "[") closes.push(char === "{" ? "}" : "]");
    if (char === "}" || char === "]") {
      if (closes.pop() !== char) throw new SyntaxError("invalid JSON nesting");
      if (closes.length === 0) return index + 1;
    }
    index += 1;
  }
  throw new SyntaxError("unterminated JSON value");
}

function rejectTopLevelDuplicateKeys(text) {
  let index = skipWhitespace(text, 0);
  if (text[index] !== "{") throw new SyntaxError("marker is not an object");
  index += 1;
  const keys = new Set();
  const sources = new Map();
  while (true) {
    index = skipWhitespace(text, index);
    if (text[index] === "}") break;
    if (text[index] !== '"') throw new SyntaxError("invalid object key");
    const parsed = scanJsonString(text, index);
    if (keys.has(parsed.value)) throw new SyntaxError(`duplicate key: ${parsed.value}`);
    keys.add(parsed.value);
    index = skipWhitespace(text, parsed.end);
    if (text[index] !== ":") throw new SyntaxError("missing object colon");
    index = skipWhitespace(text, index + 1);
    const valueStart = index;
    index = skipJsonValue(text, index);
    sources.set(parsed.value, text.slice(valueStart, index).trim());
    index = skipWhitespace(text, index);
    if (text[index] === ",") {
      index += 1;
      continue;
    }
    if (text[index] === "}") break;
    throw new SyntaxError("invalid object separator");
  }
  return sources;
}

function parseDevicePending(bytes) {
  if (!bytes || bytes.length > MAX_MARKER_BYTES) {
    throw new RefreshPendingError(
      "beta_device_state_corrupt",
      "The Realtor Beta pending Device authorization state is too large.",
    );
  }
  let value;
  let memberSources;
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    memberSources = rejectTopLevelDuplicateKeys(text);
    value = JSON.parse(text);
  } catch (cause) {
    const failure = new RefreshPendingError(
      "beta_device_state_corrupt",
      "The Realtor Beta pending Device authorization state is unreadable.",
    );
    failure.cause = cause;
    throw failure;
  }
  const tokens = value && typeof value === "object"
    ? [
        value.device_code,
        value.initial_refresh_token,
        value.recovery_refresh_token,
        value.recovery_attempt_id,
      ]
    : [];
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    JSON.stringify(Object.keys(value).sort()) !== JSON.stringify(DEVICE_SCHEMA_KEYS) ||
    memberSources.get("schema") !== "1" ||
    value.schema !== 1 ||
    value.operation !== "device" ||
    !/^(0|[1-9][0-9]*)$/.test(memberSources.get("created_at") || "") ||
    !Number.isSafeInteger(value.created_at) ||
    value.created_at < 0 ||
    !tokens.every(canonicalToken32) ||
    new Set(tokens).size !== tokens.length
  ) {
    throw new RefreshPendingError(
      "beta_device_state_corrupt",
      "The Realtor Beta pending Device authorization state failed validation.",
    );
  }
  return Object.freeze({ ...value });
}

function createRefreshPendingStore({
  root,
  fsImpl = fs,
  processImpl = process,
  spawnImpl = childProcess.spawn,
  lockfPath = "/usr/bin/lockf",
  lockTimeoutMs = 30_000,
} = {}) {
  const resolvedRoot = path.resolve(root);
  const lockPath = path.join(resolvedRoot, LOCK_NAME);
  const markerPath = path.join(resolvedRoot, MARKER_NAME);
  const deviceMarkerPath = path.join(resolvedRoot, DEVICE_MARKER_NAME);

  function error(code, message, cause) {
    const failure = new RefreshPendingError(code, message);
    if (cause) failure.cause = cause;
    return failure;
  }

  function fsyncDirectory() {
    let fd = null;
    try {
      fd = fsImpl.openSync(resolvedRoot, "r");
      fsImpl.fsyncSync(fd);
    } finally {
      if (fd !== null) fsImpl.closeSync(fd);
    }
  }

  function validatePrivateFile(
    fd,
    artifact,
    {
      empty = false,
      stateLabel = "refresh",
      unsafeCode = "beta_refresh_state_unsafe",
    } = {},
  ) {
    const stat = fsImpl.fstatSync(fd);
    if (
      !stat.isFile() ||
      stat.nlink !== 1 ||
      (stat.mode & 0o7777) !== 0o600 ||
      (typeof processImpl.getuid === "function" && stat.uid !== processImpl.getuid()) ||
      (empty && stat.size !== 0)
    ) {
      throw error(
        unsafeCode,
        `Realtor Beta could not verify its private ${stateLabel} ${artifact}.`,
      );
    }
    return stat;
  }

  function verifyNamedFd(
    target,
    opened,
    artifact,
    {
      stateLabel = "refresh",
      unsafeCode = "beta_refresh_state_unsafe",
    } = {},
  ) {
    const named = fsImpl.lstatSync(target);
    if (
      !named.isFile() ||
      named.isSymbolicLink() ||
      named.nlink !== 1 ||
      named.dev !== opened.dev ||
      named.ino !== opened.ino
    ) {
      throw error(
        unsafeCode,
        `Realtor Beta could not verify its ${stateLabel} ${artifact} path.`,
      );
    }
  }

  function openLock() {
    const noFollow = fs.constants.O_NOFOLLOW || 0;
    const baseFlags = fs.constants.O_RDWR | noFollow;
    let fd = null;
    let created = false;
    try {
      try {
        fd = fsImpl.openSync(
          lockPath,
          baseFlags | fs.constants.O_CREAT | fs.constants.O_EXCL,
          0o600,
        );
        created = true;
      } catch (err) {
        if (!err || err.code !== "EEXIST") throw err;
        fd = fsImpl.openSync(lockPath, baseFlags);
      }
      if (created) {
        fsImpl.fchmodSync(fd, 0o600);
        fsImpl.fsyncSync(fd);
        fsyncDirectory();
      }
      const opened = validatePrivateFile(fd, "lock", { empty: true });
      verifyNamedFd(lockPath, opened, "lock");
      return fd;
    } catch (err) {
      if (fd !== null) fsImpl.closeSync(fd);
      if (err instanceof RefreshPendingError) throw err;
      throw error(
        "beta_refresh_state_unsafe",
        "Realtor Beta could not open its protected refresh lock.",
        err,
      );
    }
  }

  function startLockHolder(lockFd) {
    return new Promise((resolve, reject) => {
      const timeoutSeconds = Math.max(1, Math.ceil(lockTimeoutMs / 1000));
      let child;
      try {
        child = spawnImpl(
          lockfPath,
          ["-k", "-t", String(timeoutSeconds), "/dev/fd/3", "/bin/cat"],
          { stdio: ["pipe", "pipe", "pipe", lockFd] },
        );
      } catch (err) {
        reject(error(
          "beta_refresh_lock_unavailable",
          "Realtor Beta could not start its protected refresh lock.",
          err,
        ));
        return;
      }

      let ready = false;
      let output = "";
      let stderr = "";
      let settled = false;
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        child.kill("SIGTERM");
        reject(error(
          "beta_refresh_lock_timeout",
          "Another Realtor Beta process is still refreshing this account.",
        ));
      }, lockTimeoutMs + 2_000);

      function failBeforeReady(code, message, cause) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(error(code, message, cause));
      }

      child.once("error", (err) => failBeforeReady(
        "beta_refresh_lock_unavailable",
        "Realtor Beta could not start its protected refresh lock.",
        err,
      ));
      child.stderr.on("data", (chunk) => {
        if (stderr.length < 1024) stderr += chunk.toString("utf8");
      });
      child.stdout.on("data", (chunk) => {
        if (ready || settled) return;
        output += chunk.toString("utf8");
        if (output.length > READY_LINE.length || !READY_LINE.startsWith(output)) {
          failBeforeReady(
            "beta_refresh_lock_unavailable",
            "Realtor Beta received an invalid refresh-lock handshake.",
          );
          child.kill("SIGTERM");
          return;
        }
        if (output === READY_LINE) {
          ready = true;
          settled = true;
          clearTimeout(timer);
          resolve(child);
        }
      });
      child.once("exit", (code, signal) => {
        if (!ready) {
          failBeforeReady(
            code === 75 ? "beta_refresh_lock_timeout" : "beta_refresh_lock_unavailable",
            code === 75
              ? "Another Realtor Beta process is still refreshing this account."
              : "Realtor Beta could not acquire its protected refresh lock.",
            new Error(`lockf exited code=${code} signal=${signal} ${stderr.trim()}`),
          );
        }
      });
      child.stdin.on("error", (err) => failBeforeReady(
        "beta_refresh_lock_unavailable",
        "Realtor Beta lost its refresh-lock readiness channel.",
        err,
      ));
      child.stdin.write(READY_LINE);
    });
  }

  async function releaseLockHolder(child) {
    if (child.exitCode !== null || child.signalCode !== null) return;
    await new Promise((resolve) => {
      const timer = setTimeout(() => {
        child.kill("SIGTERM");
      }, 2_000);
      child.once("exit", () => {
        clearTimeout(timer);
        resolve();
      });
      child.stdin.end();
    });
  }

  async function withLock(callback) {
    const lockFd = openLock();
    let child = null;
    let lockLost = false;
    try {
      child = await startLockHolder(lockFd);
      child.once("exit", () => {
        lockLost = true;
      });
      const guard = {
        assertHeld() {
          if (lockLost || child.exitCode !== null || child.signalCode !== null) {
            throw error(
              "beta_refresh_lock_lost",
              "Realtor Beta lost its protected refresh lock.",
            );
          }
          const opened = validatePrivateFile(lockFd, "lock", { empty: true });
          verifyNamedFd(lockPath, opened, "lock");
        },
      };
      guard.assertHeld();
      return await callback(guard);
    } finally {
      if (child) await releaseLockHolder(child);
      fsImpl.closeSync(lockFd);
    }
  }

  function parseMarker(bytes) {
    if (bytes.length > MAX_MARKER_BYTES) {
      throw error(
        "beta_refresh_state_corrupt",
        "The Realtor Beta pending refresh state is too large.",
      );
    }
    let value;
    try {
      const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      // JSON.parse keeps only the last duplicate key. Reject duplicates before
      // parsing so corrupted A/B/I state can never be interpreted differently
      // by the Python and Desktop runtimes. The approved schema is flat, so
      // only top-level keys can survive the exact-schema check below.
      rejectTopLevelDuplicateKeys(text);
      value = JSON.parse(text);
    } catch (err) {
      throw error(
        "beta_refresh_state_corrupt",
        "The Realtor Beta pending refresh state is unreadable.",
        err,
      );
    }
    if (
      !value ||
      typeof value !== "object" ||
      Array.isArray(value) ||
      JSON.stringify(Object.keys(value).sort()) !== JSON.stringify(SCHEMA_KEYS) ||
      value.schema !== 1 ||
      value.operation !== "refresh" ||
      typeof value.license_id !== "string" ||
      !value.license_id ||
      !Number.isSafeInteger(value.created_at) ||
      value.created_at < 0 ||
      !canonicalToken32(value.current_refresh_token) ||
      !canonicalToken32(value.successor_refresh_token) ||
      !canonicalToken32(value.attempt_id) ||
      value.current_refresh_token === value.successor_refresh_token
    ) {
      throw error(
        "beta_refresh_state_corrupt",
        "The Realtor Beta pending refresh state failed validation.",
      );
    }
    return Object.freeze({ ...value });
  }

  function openMarker() {
    const flags =
      fs.constants.O_RDONLY |
      (fs.constants.O_NOFOLLOW || 0) |
      (fs.constants.O_NONBLOCK || 0);
    let fd = null;
    try {
      try {
        fd = fsImpl.openSync(markerPath, flags);
      } catch (err) {
        if (err && err.code === "ENOENT") return null;
        throw err;
      }
      const opened = validatePrivateFile(fd, "marker");
      verifyNamedFd(markerPath, opened, "marker");
      if (opened.size > MAX_MARKER_BYTES) {
        throw error(
          "beta_refresh_state_corrupt",
          "The Realtor Beta pending refresh state is too large.",
        );
      }
      return { fd, opened, marker: parseMarker(fsImpl.readFileSync(fd)) };
    } catch (err) {
      if (fd !== null) fsImpl.closeSync(fd);
      if (err instanceof RefreshPendingError) throw err;
      throw error(
        "beta_refresh_state_unsafe",
        "Realtor Beta could not safely read its pending refresh state.",
        err,
      );
    }
  }

  function read() {
    const openedMarker = openMarker();
    if (openedMarker === null) return null;
    try {
      return openedMarker.marker;
    } finally {
      fsImpl.closeSync(openedMarker.fd);
    }
  }

  function openDeviceMarker() {
    const flags =
      fs.constants.O_RDONLY |
      (fs.constants.O_NOFOLLOW || 0) |
      (fs.constants.O_NONBLOCK || 0);
    let fd = null;
    try {
      try {
        fd = fsImpl.openSync(deviceMarkerPath, flags);
      } catch (err) {
        if (err && err.code === "ENOENT") return null;
        throw err;
      }
      const deviceOptions = {
        stateLabel: "Device authorization",
        unsafeCode: "beta_device_state_unsafe",
      };
      const opened = validatePrivateFile(fd, "marker", deviceOptions);
      verifyNamedFd(deviceMarkerPath, opened, "marker", deviceOptions);
      if (opened.size > MAX_MARKER_BYTES) {
        throw error(
          "beta_device_state_corrupt",
          "The Realtor Beta pending Device authorization state is too large.",
        );
      }
      return {
        fd,
        opened,
        marker: parseDevicePending(fsImpl.readFileSync(fd)),
      };
    } catch (err) {
      if (fd !== null) fsImpl.closeSync(fd);
      if (err instanceof RefreshPendingError) throw err;
      throw error(
        "beta_device_state_unsafe",
        "Realtor Beta could not safely read its pending Device authorization state.",
        err,
      );
    }
  }

  function readDevice() {
    const openedMarker = openDeviceMarker();
    if (openedMarker === null) return null;
    try {
      return openedMarker.marker;
    } finally {
      fsImpl.closeSync(openedMarker.fd);
    }
  }

  function create({ licenseId, currentRefreshToken, createdAt = Math.floor(Date.now() / 1000) }) {
    if (
      typeof licenseId !== "string" ||
      !licenseId ||
      !canonicalToken32(currentRefreshToken)
    ) {
      throw error(
        "beta_refresh_token_invalid",
        "The Realtor Beta refresh token is not a canonical 256-bit token.",
      );
    }
    if (!Number.isSafeInteger(createdAt) || createdAt < 0) {
      throw error(
        "beta_refresh_state_corrupt",
        "The Realtor Beta pending refresh timestamp is invalid.",
      );
    }
    if (read() !== null || readDevice() !== null) {
      throw error(
        "beta_refresh_state_conflict",
        "A Realtor Beta refresh attempt already exists.",
      );
    }
    let successor = generateToken32();
    while (successor === currentRefreshToken) successor = generateToken32();
    const marker = {
      schema: 1,
      operation: "refresh",
      license_id: licenseId,
      current_refresh_token: currentRefreshToken,
      successor_refresh_token: successor,
      attempt_id: generateToken32(),
      created_at: createdAt,
    };
    const bytes = Buffer.from(`${JSON.stringify(marker)}\n`, "utf8");
    const tempPath = path.join(
      resolvedRoot,
      `.license-refresh-pending-${crypto.randomUUID()}.tmp`,
    );
    let fd = null;
    try {
      fd = fsImpl.openSync(
        tempPath,
        fs.constants.O_WRONLY |
          fs.constants.O_CREAT |
          fs.constants.O_EXCL |
          (fs.constants.O_NOFOLLOW || 0),
        0o600,
      );
      let offset = 0;
      while (offset < bytes.length) {
        const written = fsImpl.writeSync(fd, bytes, offset, bytes.length - offset);
        if (written <= 0) throw new Error("pending refresh write made no progress");
        offset += written;
      }
      fsImpl.fchmodSync(fd, 0o600);
      fsImpl.fsyncSync(fd);
      fsImpl.closeSync(fd);
      fd = null;
      fsImpl.renameSync(tempPath, markerPath);
      fsyncDirectory();
      const persisted = read();
      if (JSON.stringify(persisted) !== JSON.stringify(marker)) {
        throw error(
          "beta_refresh_persistence_failed",
          "Realtor Beta could not verify its pending refresh state.",
        );
      }
      return persisted;
    } catch (err) {
      if (err instanceof RefreshPendingError) throw err;
      throw error(
        "beta_refresh_persistence_failed",
        "Realtor Beta could not durably save its pending refresh state.",
        err,
      );
    } finally {
      if (fd !== null) fsImpl.closeSync(fd);
      try {
        fsImpl.unlinkSync(tempPath);
      } catch {
        // Rename removes the temporary path.
      }
    }
  }

  function remove() {
    let openedMarker = null;
    try {
      openedMarker = openMarker();
      if (openedMarker === null) return false;
      // Keep the authenticated inode open and revalidate the named path at
      // the deletion boundary. A swapped symlink or different inode is
      // retained and reported instead of being unlinked on trust.
      verifyNamedFd(markerPath, openedMarker.opened, "marker");
      fsImpl.unlinkSync(markerPath);
      if (fsImpl.existsSync(markerPath)) {
        throw new Error("pending refresh removal could not be verified");
      }
      fsyncDirectory();
      return true;
    } catch (err) {
      if (err instanceof RefreshPendingError) throw err;
      throw error(
        "beta_refresh_persistence_failed",
        "Realtor Beta could not durably clear its pending refresh state.",
        err,
      );
    } finally {
      if (openedMarker !== null) fsImpl.closeSync(openedMarker.fd);
    }
  }

  function writeDevice({
    deviceCode,
    initialRefreshToken,
    recoveryRefreshToken,
    recoveryAttemptId,
    createdAt = Math.floor(Date.now() / 1000),
  }) {
    const marker = parseDevicePending(Buffer.from(`${JSON.stringify({
      schema: 1,
      operation: "device",
      device_code: deviceCode,
      initial_refresh_token: initialRefreshToken,
      recovery_refresh_token: recoveryRefreshToken,
      recovery_attempt_id: recoveryAttemptId,
      created_at: createdAt,
    })}\n`, "utf8"));
    if (readDevice() !== null || read() !== null) {
      throw error(
        "beta_device_state_conflict",
        "A Realtor Beta credential transition already exists.",
      );
    }
    const bytes = Buffer.from(`${JSON.stringify(marker)}\n`, "utf8");
    const tempPath = path.join(
      resolvedRoot,
      `.license-device-pending-${crypto.randomUUID()}.tmp`,
    );
    let fd = null;
    try {
      fd = fsImpl.openSync(
        tempPath,
        fs.constants.O_WRONLY |
          fs.constants.O_CREAT |
          fs.constants.O_EXCL |
          (fs.constants.O_NOFOLLOW || 0),
        0o600,
      );
      let offset = 0;
      while (offset < bytes.length) {
        const written = fsImpl.writeSync(fd, bytes, offset, bytes.length - offset);
        if (written <= 0) throw new Error("pending Device write made no progress");
        offset += written;
      }
      fsImpl.fchmodSync(fd, 0o600);
      fsImpl.fsyncSync(fd);
      fsImpl.closeSync(fd);
      fd = null;
      fsImpl.renameSync(tempPath, deviceMarkerPath);
      fsyncDirectory();
      const persisted = readDevice();
      if (!deviceMarkersEqual(persisted, marker)) {
        throw error(
          "beta_device_persistence_failed",
          "Realtor Beta could not verify its pending Device authorization state.",
        );
      }
      return persisted;
    } catch (err) {
      if (err instanceof RefreshPendingError) throw err;
      throw error(
        "beta_device_persistence_failed",
        "Realtor Beta could not durably save its pending Device authorization state.",
        err,
      );
    } finally {
      if (fd !== null) fsImpl.closeSync(fd);
      try {
        fsImpl.unlinkSync(tempPath);
      } catch {
        // Rename removes the temporary path.
      }
    }
  }

  function deviceMarkersEqual(left, right) {
    return Boolean(left) && Boolean(right) && DEVICE_SCHEMA_KEYS.every(
      (key) => left[key] === right[key],
    );
  }

  function normalizeExpectedDevice(expected) {
    try {
      if (
        !expected ||
        typeof expected !== "object" ||
        Array.isArray(expected) ||
        JSON.stringify(Object.keys(expected).sort()) !== JSON.stringify(DEVICE_SCHEMA_KEYS)
      ) {
        throw new TypeError("expected Device marker does not have the exact schema");
      }
      return parseDevicePending(Buffer.from(JSON.stringify(expected), "utf8"));
    } catch (err) {
      if (err instanceof RefreshPendingError) throw err;
      throw error(
        "beta_device_state_corrupt",
        "The Realtor Beta expected Device authorization state is invalid.",
        err,
      );
    }
  }

  function removeDevice(expected) {
    const expectedMarker = normalizeExpectedDevice(expected);
    let openedMarker = null;
    try {
      openedMarker = openDeviceMarker();
      if (
        openedMarker === null ||
        !deviceMarkersEqual(openedMarker.marker, expectedMarker)
      ) {
        return false;
      }
      verifyNamedFd(deviceMarkerPath, openedMarker.opened, "marker", {
        stateLabel: "Device authorization",
        unsafeCode: "beta_device_state_unsafe",
      });
      fsImpl.unlinkSync(deviceMarkerPath);
      if (fsImpl.existsSync(deviceMarkerPath)) {
        throw new Error("pending Device removal could not be verified");
      }
      fsyncDirectory();
      return true;
    } catch (err) {
      if (err instanceof RefreshPendingError) throw err;
      throw error(
        "beta_device_persistence_failed",
        "Realtor Beta could not durably clear its pending Device authorization state.",
        err,
      );
    } finally {
      if (openedMarker !== null) fsImpl.closeSync(openedMarker.fd);
    }
  }

  return {
    create,
    deviceMarkerPath,
    lockPath,
    markerPath,
    parseDevice: parseDevicePending,
    read,
    readDevice,
    remove,
    removeDevice,
    withLock,
    writeDevice,
  };
}

module.exports = {
  DEVICE_MARKER_NAME,
  LOCK_NAME,
  MARKER_NAME,
  RefreshPendingError,
  canonicalToken32,
  createRefreshPendingStore,
  generateToken32,
  parseDevicePending,
};
