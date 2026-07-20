"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const asar = require("@electron/asar");
const { Arch } = require("builder-util");
const yaml = require("js-yaml");

const {
  CANDIDATE_VERSION,
  RECOVERY_SOURCE_FILES,
  RECOVERY_VERSION,
  UPDATE_BASE_URL,
  requireSourceReceiptId,
} = require("../electron-builder.recovery.config");
const { BETA } = require("../src/release-profile");
const { normalizeArchitecture, verifySourceReceipt } = require("./candidate-receipt");

const DESKTOP_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(DESKTOP_ROOT, "..");
const RECOVERY_DIST_ROOT = path.join(DESKTOP_ROOT, "dist", "recovery");
const CANDIDATE_SOURCE_RECEIPT = path.join(DESKTOP_ROOT, "dist", "candidate-source.json");
const RECOVERY_EVIDENCE_SCHEMA_VERSION = 1;

const ALLOWED_ASAR_SOURCE_FILES = new Set(RECOVERY_SOURCE_FILES);
const FORBIDDEN_RESOURCE_NAMES = new Set(["backend", "cli", "gateway", "runtime", "tools"]);
const FORBIDDEN_MODULE_ROOTS = new Set([
  "@anthropic-ai",
  "@openai",
  "node-pty",
  "playwright",
  "playwright-core",
  "puppeteer",
  "puppeteer-core",
]);

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]));
  }
  return value;
}

function canonicalJson(value) {
  return JSON.stringify(canonicalize(value));
}

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function sha256File(filePath) {
  const hash = crypto.createHash("sha256");
  const descriptor = fs.openSync(filePath, "r");
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  try {
    let bytes = 0;
    while ((bytes = fs.readSync(descriptor, buffer, 0, buffer.length, null)) > 0) {
      hash.update(buffer.subarray(0, bytes));
    }
  } finally {
    fs.closeSync(descriptor);
  }
  return hash.digest("hex");
}

function recoveryArchitecture(value) {
  return normalizeArchitecture(typeof value === "number" ? Arch[value] : value);
}

function packedAppPath(appOutDir) {
  const bundles = fs.readdirSync(appOutDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name.endsWith(".app"))
    .map((entry) => path.join(appOutDir, entry.name));
  if (bundles.length !== 1) {
    throw new Error(
      `[recovery-after-pack] expected exactly one app bundle in ${appOutDir}; found ${bundles.length}`,
    );
  }
  return bundles[0];
}

function plistValue(plistPath, key, { spawn = spawnSync } = {}) {
  const result = spawn("/usr/bin/plutil", ["-extract", key, "raw", "-o", "-", plistPath], {
    encoding: "utf8",
    timeout: 15_000,
  });
  if (result.status !== 0) {
    const detail = String(result.stderr || result.stdout || result.error?.message || "plutil failed").trim();
    throw new Error(`[recovery-after-pack] could not read Info.plist ${key}: ${detail}`);
  }
  return String(result.stdout || "").trim();
}

function assertExactMetadata(metadata, sourceReceiptId) {
  const expected = {
    name: BETA.packageName,
    version: RECOVERY_VERSION,
    main: "src/recovery-main.js",
    elevateReleaseChannel: "beta",
    elevateRecoveryMode: true,
    elevateRecoveryCandidateVersion: CANDIDATE_VERSION,
    elevateRecoverySourceReceiptId: sourceReceiptId,
  };
  for (const [key, value] of Object.entries(expected)) {
    if (metadata?.[key] !== value) {
      throw new Error(
        `[recovery-after-pack] packaged metadata ${key} is ${JSON.stringify(metadata?.[key])}; `
        + `expected ${JSON.stringify(value)}`,
      );
    }
  }
  const dependencies = metadata?.dependencies || {};
  const exactDependencies = ["electron-log", "electron-updater"];
  if (canonicalJson(Object.keys(dependencies).sort()) !== canonicalJson(exactDependencies)) {
    throw new Error("[recovery-after-pack] packaged recovery dependencies drifted from updater-only closure");
  }
}

function moduleRoot(asarPath) {
  const parts = asarPath.split("/");
  if (parts[0] !== "node_modules" || !parts[1]) return null;
  return parts[1].startsWith("@") && parts[2] ? `${parts[1]}/${parts[2]}` : parts[1];
}

function assertRecoveryAsarEntries(entries) {
  const normalized = entries.map((entry) => entry.replace(/^\/+/, "")).filter(Boolean);
  for (const entry of normalized) {
    const top = entry.split("/")[0];
    if (FORBIDDEN_RESOURCE_NAMES.has(top)) {
      throw new Error(`[recovery-after-pack] forbidden recovery ASAR resource: ${entry}`);
    }
    if (top === "src" && entry !== "src" && !ALLOWED_ASAR_SOURCE_FILES.has(entry)) {
      throw new Error(`[recovery-after-pack] forbidden desktop runtime module in recovery ASAR: ${entry}`);
    }
    if (!["node_modules", "package.json", "src"].includes(top)) {
      throw new Error(`[recovery-after-pack] unexpected top-level recovery ASAR path: ${entry}`);
    }
    const root = moduleRoot(entry);
    const rootScope = root?.split("/")[0];
    if (FORBIDDEN_MODULE_ROOTS.has(root) || FORBIDDEN_MODULE_ROOTS.has(rootScope)) {
      throw new Error(`[recovery-after-pack] forbidden agent/tool module in recovery ASAR: ${root}`);
    }
  }
  for (const required of RECOVERY_SOURCE_FILES) {
    if (!normalized.includes(required)) {
      throw new Error(`[recovery-after-pack] recovery ASAR is missing ${required}`);
    }
  }
}

function assertNoForbiddenResources(resourcesPath) {
  for (const name of FORBIDDEN_RESOURCE_NAMES) {
    const item = path.join(resourcesPath, name);
    if (fs.lstatSync(item, { throwIfNoEntry: false })) {
      throw new Error(`[recovery-after-pack] forbidden packaged recovery resource: ${name}`);
    }
  }
  const unpacked = path.join(resourcesPath, "app.asar.unpacked");
  if (fs.lstatSync(unpacked, { throwIfNoEntry: false })) {
    throw new Error("[recovery-after-pack] recovery package must not contain unpacked runtime modules");
  }
}

function verifyUpdaterConfiguration(resourcesPath) {
  const updatePath = path.join(resourcesPath, "app-update.yml");
  if (!fs.statSync(updatePath, { throwIfNoEntry: false })?.isFile()) {
    throw new Error("[recovery-after-pack] packaged Beta updater configuration is missing");
  }
  const update = yaml.load(fs.readFileSync(updatePath, "utf8"));
  const expected = {
    provider: "generic",
    url: UPDATE_BASE_URL,
    channel: "beta",
    updaterCacheDirName: "elevate-beta-desktop-updater",
  };
  for (const [key, value] of Object.entries(expected)) {
    if (update?.[key] !== value) {
      throw new Error(
        `[recovery-after-pack] packaged updater ${key} is ${JSON.stringify(update?.[key])}; `
        + `expected ${JSON.stringify(value)}`,
      );
    }
  }
  return { path: updatePath, sha256: sha256File(updatePath) };
}

function verifyRecoverySourceProvenance({
  sourceReceiptId,
  receiptPath = CANDIDATE_SOURCE_RECEIPT,
  verify = verifySourceReceipt,
} = {}) {
  const receipt = verify({
    receiptPath,
    repoRoot: REPO_ROOT,
    desktopRoot: DESKTOP_ROOT,
    channel: "beta",
    version: CANDIDATE_VERSION,
  });
  if (receipt?.source_receipt_id !== sourceReceiptId) {
    throw new Error("[recovery-after-pack] candidate source receipt does not match recovery build provenance");
  }
  return receipt;
}

function verifyRecoveryBundle({
  appPath,
  architecture,
  sourceReceiptId,
  readPlist = plistValue,
} = {}) {
  if (!/^(arm64|x64)$/.test(architecture || "")) {
    throw new Error(`[recovery-after-pack] unsupported recovery architecture: ${architecture || "<missing>"}`);
  }
  if (path.basename(appPath || "") !== BETA.appBundleName) {
    throw new Error(
      `[recovery-after-pack] recovery app bundle identity is ${path.basename(appPath || "<missing>")}; `
      + `expected ${BETA.appBundleName}`,
    );
  }
  const contentsPath = path.join(appPath, "Contents");
  const resourcesPath = path.join(contentsPath, "Resources");
  const asarPath = path.join(resourcesPath, "app.asar");
  if (!fs.statSync(asarPath, { throwIfNoEntry: false })?.isFile()) {
    throw new Error("[recovery-after-pack] recovery app.asar is missing");
  }

  const plistPath = path.join(contentsPath, "Info.plist");
  const plistExpected = {
    CFBundleIdentifier: BETA.appId,
    CFBundleName: BETA.productName,
    CFBundleDisplayName: BETA.productName,
    CFBundleShortVersionString: RECOVERY_VERSION,
    CFBundleVersion: RECOVERY_VERSION,
    "CFBundleURLTypes.0.CFBundleURLSchemes.0": BETA.protocolScheme,
  };
  for (const [key, value] of Object.entries(plistExpected)) {
    const actual = readPlist(plistPath, key);
    if (actual !== value) {
      throw new Error(`[recovery-after-pack] packaged identity ${key} is ${actual}; expected ${value}`);
    }
  }

  assertNoForbiddenResources(resourcesPath);
  asar.uncache(asarPath);
  const entries = asar.listPackage(asarPath);
  assertRecoveryAsarEntries(entries);
  const metadata = JSON.parse(asar.extractFile(asarPath, "package.json").toString("utf8"));
  assertExactMetadata(metadata, sourceReceiptId);
  const updater = verifyUpdaterConfiguration(resourcesPath);

  const evidence = {
    schema_version: RECOVERY_EVIDENCE_SCHEMA_VERSION,
    kind: "elevate-beta-roll-forward-recovery-pre-sign",
    architecture,
    app_bundle_name: BETA.appBundleName,
    app_id: BETA.appId,
    package_name: BETA.packageName,
    protocol_scheme: BETA.protocolScheme,
    release_channel: "beta",
    candidate_version: CANDIDATE_VERSION,
    recovery_version: RECOVERY_VERSION,
    source_receipt_id: sourceReceiptId,
    app_asar_sha256: sha256File(asarPath),
    updater_config_sha256: updater.sha256,
    runtime_policy: {
      backend: false,
      cli: false,
      gateway: false,
      runtime: false,
      tools: false,
      profile_preserved: true,
    },
    asar_source_files: [...RECOVERY_SOURCE_FILES].sort(),
  };
  evidence.evidence_id = sha256(canonicalJson(evidence));
  return evidence;
}

function writeImmutableEvidence(outputPath, evidence) {
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  const bytes = `${JSON.stringify(canonicalize(evidence), null, 2)}\n`;
  if (fs.existsSync(outputPath)) {
    if (fs.readFileSync(outputPath, "utf8") === bytes) return evidence;
    throw new Error(`[recovery-after-pack] refusing to replace mismatched ${path.basename(outputPath)}`);
  }
  const temporary = `${outputPath}.tmp-${process.pid}-${crypto.randomUUID()}`;
  fs.writeFileSync(temporary, bytes, { flag: "wx" });
  try {
    fs.linkSync(temporary, outputPath);
  } finally {
    fs.rmSync(temporary, { force: true });
  }
  return evidence;
}

async function afterPackRecoveryMac(context) {
  if (context.electronPlatformName !== "darwin") return;
  const sourceReceiptId = requireSourceReceiptId(process.env);
  const architecture = recoveryArchitecture(context.arch);
  if (!/^(arm64|x64)$/.test(architecture || "")) {
    throw new Error(`[recovery-after-pack] unsupported recovery architecture: ${context.arch}`);
  }
  const relativeOutput = path.relative(RECOVERY_DIST_ROOT, path.resolve(context.appOutDir));
  if (relativeOutput === "" || relativeOutput.startsWith("..") || path.isAbsolute(relativeOutput)) {
    throw new Error("[recovery-after-pack] recovery app output escaped desktop/dist/recovery");
  }

  verifyRecoverySourceProvenance({ sourceReceiptId });
  const xattr = spawnSync("/usr/bin/xattr", ["-cr", context.appOutDir], { encoding: "utf8" });
  if (xattr.status !== 0) {
    const detail = String(xattr.stderr || xattr.stdout || xattr.error?.message || "xattr failed").trim();
    throw new Error(`[recovery-after-pack] failed to clear macOS extended attributes: ${detail}`);
  }
  const appPath = packedAppPath(context.appOutDir);
  const evidence = verifyRecoveryBundle({ appPath, architecture, sourceReceiptId });
  const evidencePath = path.join(RECOVERY_DIST_ROOT, `pre-sign-recovery-${architecture}.json`);
  writeImmutableEvidence(evidencePath, evidence);
  console.log(
    `[recovery-after-pack] verified ${architecture} recovery ${RECOVERY_VERSION} `
    + `${evidence.evidence_id}`,
  );
}

module.exports = {
  ALLOWED_ASAR_SOURCE_FILES,
  CANDIDATE_SOURCE_RECEIPT,
  FORBIDDEN_MODULE_ROOTS,
  FORBIDDEN_RESOURCE_NAMES,
  RECOVERY_DIST_ROOT,
  RECOVERY_EVIDENCE_SCHEMA_VERSION,
  assertExactMetadata,
  assertNoForbiddenResources,
  assertRecoveryAsarEntries,
  default: afterPackRecoveryMac,
  packedAppPath,
  plistValue,
  recoveryArchitecture,
  sha256File,
  verifyRecoveryBundle,
  verifyRecoverySourceProvenance,
  verifyUpdaterConfiguration,
  writeImmutableEvidence,
};
