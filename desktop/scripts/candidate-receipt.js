#!/usr/bin/env node
"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { once } = require("node:events");
const { StringDecoder } = require("node:string_decoder");
const yaml = require("js-yaml");
const { sanitizeFileName } = require("builder-util/out/filename");
const asar = require("@electron/asar");
const {
  npmCliPath,
  validateBetaSourceSafetyEvidence,
} = require("./beta-source-safety-gate");
const { hashRuntimeCodeTree } = require("./runtime-code-hash");
const {
  downloadAliasFileNames,
  releaseArtifactNames,
  resolveReleaseProfile,
} = require("../src/release-profile");

const DESKTOP = path.resolve(__dirname, "..");
const REPO = path.resolve(DESKTOP, "..");
const DIST = path.join(DESKTOP, "dist");
const SOURCE_RECEIPT = path.join(DIST, "candidate-source.json");
const WEB_BUILD_RECEIPT = path.join(DIST, "candidate-web.json");
const CANDIDATE_RECEIPT = path.join(DIST, "candidate-receipt.json");
const CHANNELS = new Set(["latest", "beta"]);
const ARCHITECTURES = ["x64", "arm64"];
const SOURCE_RECEIPT_SCHEMA_VERSION = 2;
const CANDIDATE_RECEIPT_SCHEMA_VERSION = 2;
const PRE_SIGN_EVIDENCE_SCHEMA_VERSION = 1;
const PUBLIC_BASE_URL = "https://api.elevationrealestatehq.com/updates";
const RECOVERY_RECEIPT_SCHEMA_VERSION = 1;
const REALTOR_BETA_RECOVERY_CANDIDATE_VERSION = "1.2.103";
const REALTOR_BETA_RECOVERY_VERSION = "1.2.104";
const REALTOR_BETA_RECOVERY_PROCEDURE_ID = "realtor-beta-recovery-roll-forward-v1";
const RECOVERY_FEED_NAME = "beta-mac.yml";
const RECOVERY_ARTIFACT_PREFIX = "Elevate-Beta-Recovery";
const RECOVERY_RUNTIME_POLICY = Object.freeze({
  backend: false,
  cli: false,
  gateway: false,
  runtime: false,
  tools: false,
  profile_preserved: true,
});
const RECOVERY_SOURCE_FILES = Object.freeze([
  "recovery-main.js",
  "recovery-preload.js",
  "recovery-containment.js",
  "recovery.html",
  "release-profile.js",
  "updater.js",
]);
const ROLLBACK_FREEZE_FILE = ".realtor-beta-rollback-freeze";
const REALTOR_BETA_ROLLBACK_PROCEDURE_ID = "realtor-beta-feed-and-alias-rollback-v2";
const TRUSTED_APPLE_TEAM_ID = "G5TK395RYH";
const SMOKE_EVIDENCE_SCHEMA_VERSION = 1;
const REALTOR_BETA_GATE_EVIDENCE_SCHEMA_VERSION = 1;
const REQUIRED_SMOKE_CHECK_IDS = [
  "candidate_binding",
  "app_version",
  "runtime_dependencies",
  "app_seal",
  "web_parity",
  "whatsapp_bridge",
  "log_hygiene",
];
const REQUIRED_LIVE_AI_CHECK_IDS = [
  ...REQUIRED_SMOKE_CHECK_IDS,
  "served_assets",
  "sidecar_ai",
  "session_persistence",
  "terminal_truth",
  "log_profile",
];
const REQUIRED_REALTOR_BETA_GATE_CHECK_IDS = [
  "candidate_binding",
  "beta_profile_coexistence",
  "installed_runtime_import",
  "tool_request_receipt_parity",
  "bc_pack_baseline",
  "bc_pack_missing_fail_closed",
  "bc_pack_corrupt_fail_closed",
  "bc_pack_decoy_fail_closed",
  "bc_pack_stale_receipt_fail_closed",
  "forms_proof_missing_fail_closed",
  "forms_proof_fake_fail_closed",
  "artifact_missing_fail_closed",
  "artifact_wrong_kind_fail_closed",
  "worker_no_callback_retry_exhaustion",
  "session_restart_resume",
  "recovery_target_metadata",
  "recovery_local_roll_forward",
  "recovery_minimal_runtime",
  "stable_feed_untouched",
];
const REALTOR_BETA_RECOVERY_CHECK_IDS = [
  "recovery_target_metadata",
  "recovery_local_roll_forward",
  "recovery_minimal_runtime",
];
const REALTOR_BETA_RECOVERY_NOT_APPLICABLE_CHECK_ID = "recovery_contract_not_applicable";
const REQUIRED_REALTOR_BETA_BASE_CHECK_IDS = REQUIRED_REALTOR_BETA_GATE_CHECK_IDS.filter(
  (check) => !REALTOR_BETA_RECOVERY_CHECK_IDS.includes(check),
);

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}

function canonicalJson(value) {
  return JSON.stringify(canonicalize(value));
}

function receiptId(receipt, idKey) {
  const body = { ...receipt };
  delete body[idKey];
  return sha256(canonicalJson(body));
}

function realtorBetaRollbackFreezeRecord(candidate) {
  if (candidate?.release?.channel !== "beta" || candidate.release.feed_name !== "beta-mac.yml") {
    throw new Error("[candidate] rollback tombstones apply only to an exact Beta candidate");
  }
  const values = {
    candidate_id: candidate.candidate_id,
    source_receipt_id: candidate.source_receipt_id,
    failed_feed_sha256: candidate.artifacts?.[candidate.release.feed_name]?.sha256,
    rollback_feed_sha256: candidate.rollback_target?.sha256,
    stable_feed_sha256: candidate.public_feeds_at_finalize?.latest?.sha256,
  };
  for (const [name, value] of Object.entries(values)) {
    if (!/^[a-f0-9]{64}$/.test(value || "")) {
      throw new Error(`[candidate] invalid Realtor Beta rollback tombstone ${name}`);
    }
  }
  const record = {
    schema_version: 1,
    kind: "elevate-realtor-beta-rollback-release-freeze",
    ...values,
    procedure_id: REALTOR_BETA_ROLLBACK_PROCEDURE_ID,
  };
  record.freeze_id = receiptId(record, "freeze_id");
  return record;
}

function realtorBetaRollbackFreezeBytes(candidate) {
  return Buffer.from(`${JSON.stringify(canonicalize(realtorBetaRollbackFreezeRecord(candidate)), null, 2)}\n`);
}

function realtorBetaRollbackClearedFile(candidate) {
  return `${ROLLBACK_FREEZE_FILE}.cleared-${realtorBetaRollbackFreezeRecord(candidate).freeze_id}`;
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeAtomicJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const temp = `${filePath}.tmp-${process.pid}`;
  fs.writeFileSync(temp, `${JSON.stringify(canonicalize(value), null, 2)}\n`, { flag: "wx" });
  fs.renameSync(temp, filePath);
}

function writeExclusiveAtomicJson(filePath, value, label = path.basename(filePath)) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const temp = `${filePath}.tmp-${process.pid}-${crypto.randomUUID()}`;
  fs.writeFileSync(temp, `${JSON.stringify(canonicalize(value), null, 2)}\n`, { flag: "wx" });
  try {
    // Linking a complete temp inode is an atomic no-replace publication. A
    // stale or concurrent evidence file therefore cannot be silently reused.
    fs.linkSync(temp, filePath);
  } catch (error) {
    if (error?.code === "EEXIST") {
      throw new Error(`[candidate] refusing to replace immutable ${label}`);
    }
    throw error;
  } finally {
    fs.rmSync(temp, { force: true });
  }
}

function writeImmutableReceipt(filePath, receipt, idKey) {
  const value = { ...receipt, [idKey]: receiptId(receipt, idKey) };
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  if (fs.existsSync(filePath)) {
    const existing = readJson(filePath);
    if (canonicalJson(existing) === canonicalJson(value)) return existing;
    throw new Error(
      `[candidate] refusing to replace immutable ${path.basename(filePath)}; use a new version/candidate`,
    );
  }
  fs.writeFileSync(filePath, `${JSON.stringify(canonicalize(value), null, 2)}\n`, { flag: "wx" });
  return value;
}

function run(command, args, { cwd = DESKTOP, timeout = 120_000, env = process.env } = {}) {
  const result = spawnSync(command, args, { cwd, env, encoding: "utf8", timeout });
  return {
    ok: result.status === 0,
    status: result.status,
    stdout: result.stdout || "",
    stderr: result.stderr || "",
    error: result.error ? result.error.message : "",
  };
}

function requireRun(command, args, options) {
  const result = run(command, args, options);
  if (!result.ok) {
    const detail = `${result.stdout}\n${result.stderr}\n${result.error}`.trim();
    throw new Error(`[candidate] ${command} ${args.join(" ")} failed${detail ? `: ${detail}` : ""}`);
  }
  return result.stdout.trim();
}

function sha256File(filePath) {
  const hash = crypto.createHash("sha256");
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  const fd = fs.openSync(filePath, "r");
  try {
    let bytes = 0;
    while ((bytes = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0) {
      hash.update(buffer.subarray(0, bytes));
    }
  } finally {
    fs.closeSync(fd);
  }
  return hash.digest("hex");
}

function hashFileWith(filePath, algorithm, encoding) {
  const hash = crypto.createHash(algorithm);
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  const fd = fs.openSync(filePath, "r");
  try {
    let bytes = 0;
    while ((bytes = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0) hash.update(buffer.subarray(0, bytes));
  } finally {
    fs.closeSync(fd);
  }
  return hash.digest(encoding);
}

function fileRecord(filePath, relativeTo = DESKTOP, { includeSha512 = false } = {}) {
  const stat = fs.statSync(filePath);
  const record = {
    path: path.relative(relativeTo, filePath),
    size: stat.size,
    sha256: sha256File(filePath),
  };
  if (includeSha512) record.sha512 = hashFileWith(filePath, "sha512", "base64");
  return record;
}

function excludedByMode(relativePath, mode) {
  const parts = relativePath.split(path.sep);
  const name = parts.at(-1) || "";
  if (name === ".DS_Store" || name === "__pycache__" || /\.py[co]$/.test(name)) return true;
  if (mode === "web-source") return parts.includes("node_modules") || parts[0] === "dist";
  if (mode === "runtime") return false;
  if (mode === "whatsapp") return parts.includes("node_modules");
  if (mode === "cli-packaging") {
    if (relativePath === path.join("elevate_cli", "web_dist") || relativePath.startsWith(`${path.join("elevate_cli", "web_dist")}${path.sep}`)) return true;
    const excludedTop = new Set([
      "web", "ui-tui", "venv", ".venv", "tests", "build", "dist", "docs", "docker", "nix", "plans",
      "website", "packaging", "datagen-config-examples", "temp_vision_images", "scripts", "assets",
      ".git", ".pytest_cache", ".ruff_cache",
    ]);
    if (excludedTop.has(parts[0])) return true;
    if (/\.(db|db-shm|db-wal|sqlite|sqlite3)$/.test(name) || name.endsWith(".egg-info")) return true;
  }
  return false;
}

function treeEntryPermissions(stat, mode) {
  if (mode !== "cli-packaging") return stat.mode & 0o777;
  // electron-builder canonicalizes copied resource modes. Model the bytes that
  // it actually emits so an otherwise-clean checkout with restrictive local
  // read bits (for example 0600 instead of Git's 0644) cannot invalidate the
  // source contract after an expensive signed build.
  if (stat.isSymbolicLink()) return 0o777;
  if (stat.isDirectory()) return 0o755;
  if (stat.isFile()) return stat.mode & 0o111 ? 0o755 : 0o644;
  return stat.mode & 0o777;
}

function assertCanonicalPackagedPermissions(root, label = path.basename(root)) {
  if (!fs.existsSync(root)) throw new Error(`[candidate] missing packaged tree: ${root}`);

  function walk(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const absolute = path.join(directory, entry.name);
      const stat = fs.lstatSync(absolute);
      if ((stat.mode & 0o7000) !== 0) {
        throw new Error(`[candidate] ${label} contains special permission bits: ${absolute}`);
      }
      const actual = stat.mode & 0o777;
      const expected = treeEntryPermissions(stat, "cli-packaging");
      if (actual !== expected) {
        throw new Error(
          `[candidate] ${label} has unsafe/noncanonical permissions at ${absolute}: `
          + `${actual.toString(8)} (expected ${expected.toString(8)})`,
        );
      }
      if (stat.isDirectory()) walk(absolute);
    }
  }

  walk(root);
  return true;
}

function hashTree(root, { mode = "default" } = {}) {
  if (!fs.existsSync(root)) throw new Error(`[candidate] missing tree: ${root}`);
  const hash = crypto.createHash("sha256");
  let fileCount = 0;
  let totalSize = 0;

  function walk(directory, relativeDirectory = "") {
    const entries = fs.readdirSync(directory, { withFileTypes: true })
      .sort((left, right) => left.name.localeCompare(right.name, "en"));
    for (const entry of entries) {
      const relative = relativeDirectory ? path.join(relativeDirectory, entry.name) : entry.name;
      if (excludedByMode(relative, mode)) continue;
      const absolute = path.join(directory, entry.name);
      const stat = fs.lstatSync(absolute);
      const permissions = treeEntryPermissions(stat, mode).toString(8).padStart(3, "0");
      if (stat.isSymbolicLink()) {
        hash.update(`l\0${relative}\0${permissions}\0${fs.readlinkSync(absolute)}\0`);
      } else if (stat.isDirectory()) {
        hash.update(`d\0${relative}\0${permissions}\0`);
        walk(absolute, relative);
      } else if (stat.isFile()) {
        hash.update(`f\0${relative}\0${permissions}\0${stat.size}\0`);
        const fd = fs.openSync(absolute, "r");
        const buffer = Buffer.allocUnsafe(1024 * 1024);
        try {
          let bytes = 0;
          while ((bytes = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0) {
            hash.update(buffer.subarray(0, bytes));
          }
        } finally {
          fs.closeSync(fd);
        }
        hash.update("\0");
        fileCount += 1;
        totalSize += stat.size;
      }
    }
  }

  walk(root);
  return { sha256: hash.digest("hex"), file_count: fileCount, size: totalSize };
}

function hashPortableTree(root, { mode = "default" } = {}) {
  if (!fs.existsSync(root)) throw new Error(`[candidate] missing tree: ${root}`);
  const hash = crypto.createHash("sha256");
  let fileCount = 0;
  let totalSize = 0;
  function walk(directory, relativeDirectory = "") {
    const entries = fs.readdirSync(directory, { withFileTypes: true })
      .sort((left, right) => left.name.localeCompare(right.name, "en"));
    for (const entry of entries) {
      const relative = relativeDirectory ? path.join(relativeDirectory, entry.name) : entry.name;
      if (excludedByMode(relative, mode)) continue;
      const portableRelative = relative.split(path.sep).join("/");
      const absolute = path.join(directory, entry.name);
      const stat = fs.lstatSync(absolute);
      if (stat.isSymbolicLink()) {
        hash.update(`l\0${portableRelative}\0${fs.readlinkSync(absolute)}\0`);
      } else if (stat.isDirectory()) {
        walk(absolute, relative);
      } else if (stat.isFile()) {
        hash.update(`f\0${portableRelative}\0${stat.size}\0`);
        const fd = fs.openSync(absolute, "r");
        const buffer = Buffer.allocUnsafe(1024 * 1024);
        try {
          let bytes = 0;
          while ((bytes = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0) hash.update(buffer.subarray(0, bytes));
        } finally {
          fs.closeSync(fd);
        }
        hash.update("\0");
        fileCount += 1;
        totalSize += stat.size;
      }
    }
  }
  walk(root);
  return { sha256: hash.digest("hex"), file_count: fileCount, size: totalSize };
}

function declaredAsarSize(asarPath) {
  const rawHeader = asar.getRawHeader(asarPath);
  if (!Number.isSafeInteger(rawHeader.headerSize) || rawHeader.headerSize < 0) {
    throw new Error(`[candidate] invalid ASAR header size: ${asarPath}`);
  }
  let packedEnd = 0n;
  function walk(entry) {
    if (!entry || typeof entry !== "object") {
      throw new Error(`[candidate] invalid ASAR header entry: ${asarPath}`);
    }
    if (entry.files && typeof entry.files === "object") {
      for (const child of Object.values(entry.files)) walk(child);
      return;
    }
    if (!Object.hasOwn(entry, "size") || entry.unpacked === true) return;
    if (!Number.isSafeInteger(entry.size) || entry.size < 0
        || typeof entry.offset !== "string" || !/^\d+$/.test(entry.offset)) {
      throw new Error(`[candidate] invalid packed ASAR file record: ${asarPath}`);
    }
    const end = BigInt(entry.offset) + BigInt(entry.size);
    if (end > packedEnd) packedEnd = end;
  }
  walk(rawHeader.header);
  return 8n + BigInt(rawHeader.headerSize) + packedEnd;
}

function assertCompleteAsar(asarPath) {
  const expectedSize = declaredAsarSize(asarPath);
  const actualSize = fs.statSync(asarPath, { bigint: true }).size;
  if (actualSize !== expectedSize) {
    const condition = actualSize < expectedSize ? "truncated" : "has trailing bytes";
    throw new Error(
      `[candidate] ASAR ${condition}: ${asarPath} `
      + `(expected ${expectedSize} bytes, found ${actualSize})`,
    );
  }
  return { expected_size: expectedSize, actual_size: actualSize };
}

async function waitForCompleteAsar(asarPath, outputStream) {
  const expectedSize = declaredAsarSize(asarPath);
  const actualSize = fs.statSync(asarPath, { bigint: true }).size;
  if (actualSize === expectedSize) return assertCompleteAsar(asarPath);
  if (actualSize > expectedSize || !outputStream || typeof outputStream.once !== "function") {
    return assertCompleteAsar(asarPath);
  }
  if (!outputStream.writableFinished) await once(outputStream, "finish");
  return assertCompleteAsar(asarPath);
}

function portableAsarDirectoryHash(asarPath, directory) {
  assertCompleteAsar(asarPath);
  asar.uncache(asarPath);
  const prefix = `${String(directory).replace(/^\/+|\/+$/g, "")}/`;
  const hash = crypto.createHash("sha256");
  let fileCount = 0;
  let totalSize = 0;
  const entries = asar.listPackage(asarPath).map((entry) => entry.replace(/^\/+/, "")).sort();
  for (const entry of entries) {
    if (entry.split("/").some((part) => part === "..") || entry.startsWith("/")) {
      throw new Error(`[candidate] unsafe ASAR entry: ${entry}`);
    }
    if (!entry.startsWith(prefix)) continue;
    const stat = asar.statFile(asarPath, entry, false);
    if (stat.files) continue;
    const relative = entry.slice(prefix.length);
    if (!relative) continue;
    if (stat.link) {
      hash.update(`l\0${relative}\0${stat.link}\0`);
      continue;
    }
    const bytes = asar.extractFile(asarPath, entry);
    hash.update(`f\0${relative}\0${bytes.length}\0`);
    hash.update(bytes);
    hash.update("\0");
    fileCount += 1;
    totalSize += bytes.length;
  }
  if (fileCount === 0) throw new Error(`[candidate] ASAR directory is empty: ${directory}`);
  return { sha256: hash.digest("hex"), file_count: fileCount, size: totalSize };
}

function treeRecord(root, mode, relativeTo = REPO, { portable = false } = {}) {
  const record = { path: path.relative(relativeTo, root), mode, ...hashTree(root, { mode }) };
  if (portable) record.portable = hashPortableTree(root, { mode });
  return record;
}

function preSignEvidencePath(distRoot, architecture) {
  const arch = normalizeArchitecture(architecture);
  if (!ARCHITECTURES.includes(arch)) throw new Error(`[candidate] unsupported architecture: ${architecture}`);
  return path.join(distRoot, `candidate-pre-sign-${arch}.json`);
}

function createPreSignEvidence({
  appPath,
  architecture,
  sourceReceiptId,
  webBuildId,
  outputPath,
  createdAt = new Date().toISOString(),
} = {}) {
  const arch = normalizeArchitecture(architecture);
  if (!ARCHITECTURES.includes(arch)) throw new Error(`[candidate] unsupported architecture: ${architecture}`);
  if (!/^[a-f0-9]{64}$/.test(sourceReceiptId || "")) {
    throw new Error("[candidate] pre-sign evidence requires a valid source receipt ID");
  }
  if (!appPath || !fs.existsSync(appPath) || !fs.statSync(appPath).isDirectory()) {
    throw new Error(`[candidate] missing pre-sign app bundle: ${appPath || "<unset>"}`);
  }
  if (!outputPath) throw new Error("[candidate] pre-sign evidence output path is required");
  const resources = path.join(appPath, "Contents", "Resources");
  const evidence = {
    schema_version: PRE_SIGN_EVIDENCE_SCHEMA_VERSION,
    kind: "elevate-pre-sign-app-contract",
    created_at: createdAt,
    architecture: arch,
    source_receipt_id: sourceReceiptId,
    web_build_id: webBuildId || null,
    app_bundle_name: path.basename(appPath),
    embedded_cli: hashTree(path.join(resources, "cli"), { mode: "cli-packaging" }),
    embedded_web: {
      ...hashTree(path.join(resources, "cli", "elevate_cli", "web_dist")),
      portable: hashPortableTree(path.join(resources, "cli", "elevate_cli", "web_dist")),
    },
    embedded_whatsapp: hashTree(
      path.join(resources, "cli", "scripts", "whatsapp-bridge"),
      { mode: "whatsapp" },
    ),
    embedded_runtime: hashTree(path.join(resources, "runtime", "python"), { mode: "runtime" }),
  };
  evidence.pre_sign_evidence_id = receiptId(evidence, "pre_sign_evidence_id");
  writeExclusiveAtomicJson(outputPath, evidence, `${arch} pre-sign evidence`);
  return evidence;
}

function assertTreeContract(actual, expected, label) {
  if (!actual || !expected
      || actual.sha256 !== expected.sha256
      || actual.file_count !== expected.file_count
      || actual.size !== expected.size) {
    throw new Error(`[candidate] ${label} does not match the source contract`);
  }
  return true;
}

function assertRuntimeCodeContract(actual, expected, label) {
  assertTreeContract(actual, expected, label);
  if (!actual?.algorithm
      || actual.algorithm !== expected?.algorithm
      || actual.macho_file_count !== expected?.macho_file_count) {
    throw new Error(`[candidate] ${label} signature-neutral code manifest mismatch`);
  }
  return true;
}

function validatePreSignEvidence(evidence, {
  architecture,
  source,
  webBuild,
  appBundleName,
} = {}) {
  const arch = normalizeArchitecture(architecture);
  if (!ARCHITECTURES.includes(arch)) throw new Error(`[candidate] unsupported architecture: ${architecture}`);
  if (!evidence
      || evidence.schema_version !== PRE_SIGN_EVIDENCE_SCHEMA_VERSION
      || evidence.kind !== "elevate-pre-sign-app-contract"
      || receiptId(evidence, "pre_sign_evidence_id") !== evidence.pre_sign_evidence_id) {
    throw new Error(`[candidate] invalid ${arch} pre-sign evidence`);
  }
  if (evidence.architecture !== arch) throw new Error(`[candidate] ${arch} pre-sign architecture mismatch`);
  if (!source?.source_receipt_id || evidence.source_receipt_id !== source.source_receipt_id) {
    throw new Error(`[candidate] ${arch} pre-sign source receipt mismatch`);
  }
  if (appBundleName && evidence.app_bundle_name !== appBundleName) {
    throw new Error(`[candidate] ${arch} pre-sign app bundle mismatch`);
  }
  assertTreeContract(
    evidence.embedded_cli,
    source.inputs?.["cli/package-input"],
    `${arch} pre-sign embedded CLI`,
  );
  assertTreeContract(
    evidence.embedded_whatsapp,
    source.inputs?.["cli/whatsapp-bridge"],
    `${arch} pre-sign embedded WhatsApp bridge`,
  );
  if (!webBuild?.web_build_id || evidence.web_build_id !== webBuild.web_build_id) {
    throw new Error(`[candidate] ${arch} pre-sign web build receipt mismatch`);
  }
  assertTreeContract(
    evidence.embedded_web,
    webBuild.generated_web?.manifest,
    `${arch} pre-sign embedded web`,
  );
  assertTreeContract(
    evidence.embedded_web?.portable,
    webBuild.generated_web?.portable,
    `${arch} pre-sign portable embedded web`,
  );
  assertTreeContract(
    evidence.embedded_runtime,
    source.inputs?.[`runtime/${arch}`],
    `${arch} pre-sign embedded runtime`,
  );
  return evidence;
}

function verifyPreSignEvidence({ evidencePath, architecture, source, webBuild, appBundleName } = {}) {
  const arch = normalizeArchitecture(architecture);
  if (!evidencePath || !fs.existsSync(evidencePath)) {
    throw new Error(`[candidate] missing ${arch} pre-sign evidence: ${evidencePath || "<unset>"}`);
  }
  return validatePreSignEvidence(readJson(evidencePath), {
    architecture: arch,
    source,
    webBuild,
    appBundleName,
  });
}

function compareSemver(left, right) {
  const parse = (value) => String(value || "").split(".").map((part) => Number.parseInt(part, 10) || 0);
  const a = parse(left);
  const b = parse(right);
  for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
    if ((a[index] || 0) > (b[index] || 0)) return 1;
    if ((a[index] || 0) < (b[index] || 0)) return -1;
  }
  return 0;
}

function assertGloballyNewVersion(version, feeds) {
  const versions = Object.values(feeds || {}).map((feed) => feed?.version).filter(Boolean);
  const highest = versions.sort(compareSemver).at(-1) || null;
  if (highest && compareSemver(version, highest) <= 0) {
    throw new Error(`[candidate] version ${version} must be newer than every public feed (highest ${highest})`);
  }
  return highest;
}

function assertPublicFeedsUnchanged(expected, actual, context = "candidate build") {
  for (const channel of CHANNELS) {
    if ((expected?.[channel]?.sha256 || null) !== (actual?.[channel]?.sha256 || null)) {
      throw new Error(`[candidate] public ${channel} feed changed during ${context}`);
    }
  }
  return true;
}

function classifyPublicCandidateFeeds(candidate, actual, context = "candidate publication") {
  const feedName = candidate?.release?.feed_name;
  const targetChannel = feedName === "latest-mac.yml"
    ? "latest"
    : (feedName === "beta-mac.yml" ? "beta" : null);
  if (!targetChannel || candidate.release.channel !== targetChannel) {
    throw new Error("[candidate] candidate release channel/feed mismatch");
  }
  const targetHash = candidate.artifacts?.[feedName]?.sha256;
  if (!/^[a-f0-9]{64}$/.test(targetHash || "")) {
    throw new Error(`[candidate] candidate is missing the finalized ${feedName} SHA256`);
  }
  const otherChannel = targetChannel === "latest" ? "beta" : "latest";
  const baseline = candidate.public_feeds_at_finalize || {};
  const same = (channel, expectedHash) =>
    (actual?.[channel]?.sha256 || null) === (expectedHash || null);
  const old = same(targetChannel, baseline[targetChannel]?.sha256)
    && same(otherChannel, baseline[otherChannel]?.sha256);
  if (old) return "old";
  const committed = same(targetChannel, targetHash)
    && same(otherChannel, baseline[otherChannel]?.sha256);
  if (committed) return "committed";
  throw new Error(
    `[candidate] public Stable/Beta feeds are neither the exact finalized baseline nor the exact committed candidate during ${context}`,
  );
}

function fetchPublicFeed(channel, { baseUrl = PUBLIC_BASE_URL } = {}) {
  if (!CHANNELS.has(channel)) throw new Error(`[candidate] unsupported channel: ${channel}`);
  const url = `${baseUrl}/${channel}-mac.yml`;
  const result = run("curl", ["--silent", "--show-error", "--location", "--max-time", "30", "--write-out", "\n%{http_code}", url]);
  if (!result.ok) throw new Error(`[candidate] could not fetch ${url}: ${(result.stderr || result.error).trim()}`);
  const split = result.stdout.lastIndexOf("\n");
  const body = split >= 0 ? result.stdout.slice(0, split) : result.stdout;
  const status = Number.parseInt(split >= 0 ? result.stdout.slice(split + 1) : "0", 10) || 0;
  if (status === 404 && channel === "beta") return { channel, url, status, version: null, sha256: null };
  if (status !== 200) throw new Error(`[candidate] ${url} returned HTTP ${status}`);
  const feed = yaml.load(body) || {};
  if (!feed.version) throw new Error(`[candidate] ${url} has no version`);
  return {
    channel,
    url,
    status,
    version: String(feed.version),
    sha256: sha256(body),
    files: (feed.files || []).map((file) => ({ url: file.url, sha512: file.sha512, size: file.size })),
  };
}

function fetchPublicFeeds(options) {
  return {
    latest: fetchPublicFeed("latest", options),
    beta: fetchPublicFeed("beta", options),
  };
}

function sourceInputs({ repoRoot = REPO, desktopRoot = DESKTOP } = {}) {
  const requiredFiles = [
    "desktop/package.json",
    "desktop/package-lock.json",
    "desktop/electron-builder.config.js",
    "desktop/entitlements.mac.plist",
    "desktop/src/release-profile.js",
    "desktop/scripts/candidate-receipt.js",
    "desktop/scripts/beta-source-safety-gate.js",
    "desktop/scripts/preflight-apple-release.js",
    "desktop/scripts/merge-mac-feed.js",
    "desktop/scripts/finalize-mac-dist.js",
    "desktop/scripts/ship-to-hetzner.js",
    "cli/uv.lock",
    "cli/web/package-lock.json",
    "cli/scripts/installed_runtime_smoke.py",
    "cli/scripts/exact_candidate_realtor_beta_gate.py",
    "cli/docs/realtor-beta-rollback-runbook.md",
  ];
  const files = Object.fromEntries(requiredFiles.map((relative) => {
    const absolute = path.join(repoRoot, relative);
    return [relative, { kind: "file", ...fileRecord(absolute, repoRoot) }];
  }));
  const x64Runtime = path.join(desktopRoot, "runtime", "x64", "python");
  const arm64Runtime = path.join(desktopRoot, "runtime", "arm64", "python");
  const runtimeRecord = (root) => ({
    kind: "tree",
    ...treeRecord(root, "runtime", repoRoot),
    code_normalized: hashRuntimeCodeTree(root),
  });
  const trees = {
    "desktop/src": { kind: "tree", ...treeRecord(path.join(desktopRoot, "src"), "default", repoRoot, { portable: true }) },
    "desktop/scripts": { kind: "tree", ...treeRecord(path.join(desktopRoot, "scripts"), "default", repoRoot) },
    "desktop/assets": { kind: "tree", ...treeRecord(path.join(desktopRoot, "assets"), "default", repoRoot) },
    "cli/package-input": { kind: "tree", ...treeRecord(path.join(repoRoot, "cli"), "cli-packaging", repoRoot) },
    "cli/web-source": { kind: "tree", ...treeRecord(path.join(repoRoot, "cli", "web"), "web-source", repoRoot) },
    "cli/whatsapp-bridge": { kind: "tree", ...treeRecord(path.join(repoRoot, "cli", "scripts", "whatsapp-bridge"), "whatsapp", repoRoot) },
    "runtime/x64": runtimeRecord(x64Runtime),
    "runtime/arm64": runtimeRecord(arm64Runtime),
  };
  return { ...files, ...trees };
}

function currentGitState(repoRoot = REPO) {
  const commit = requireRun("git", ["rev-parse", "HEAD"], { cwd: repoRoot });
  const branch = requireRun("git", ["branch", "--show-current"], { cwd: repoRoot });
  const status = requireRun("git", ["status", "--porcelain=v1", "--untracked-files=all"], { cwd: repoRoot });
  const submodules = requireRun("git", ["submodule", "status", "--recursive"], { cwd: repoRoot });
  const gitDir = requireRun("git", ["rev-parse", "--git-dir"], { cwd: repoRoot });
  const commonDir = requireRun("git", ["rev-parse", "--git-common-dir"], { cwd: repoRoot });
  return {
    commit,
    branch,
    clean: status === "",
    submodules,
    linked_worktree: path.resolve(repoRoot, gitDir) !== path.resolve(repoRoot, commonDir),
  };
}

function assertActiveNpmCli(npmCli) {
  if (!path.isAbsolute(npmCli || "")
      || !fs.statSync(npmCli, { throwIfNoEntry: false })?.isFile()) {
    throw new Error("[candidate] active npm CLI is missing or is not an absolute file");
  }
  return npmCli;
}

function releaseCommandDefaults({
  desktopRoot = DESKTOP,
  npmCli = npmCliPath(),
} = {}) {
  const activeNpmCli = assertActiveNpmCli(npmCli);
  const npm = (...args) => ({
    command: process.execPath,
    args: [activeNpmCli, ...args],
  });
  return {
    npmCli: activeNpmCli,
    builder: {
      command: process.execPath,
      args: [path.join(desktopRoot, "node_modules", "electron-builder", "cli.js")],
    },
    web: npm("--prefix", "../cli/web", "run", "build"),
    merge: npm("run", "merge:mac-feed"),
  };
}

function captureToolchain({
  desktopRoot = DESKTOP,
  repoRoot = REPO,
  npmCli = npmCliPath(),
} = {}) {
  const activeNpmCli = assertActiveNpmCli(npmCli);
  const version = (command, args, cwd = desktopRoot, full = false) => {
    const result = run(command, args, { cwd });
    const text = (result.stdout || result.stderr).trim();
    return result.ok ? (full ? text.replaceAll("\n", " / ") : text.split("\n")[0]) : "unavailable";
  };
  return {
    node: process.version,
    host_architecture: process.arch,
    npm: version(process.execPath, [activeNpmCli, "--version"]),
    electron: require(path.join(desktopRoot, "node_modules", "electron", "package.json")).version,
    electron_builder: version(
      process.execPath,
      [path.join(desktopRoot, "node_modules", "electron-builder", "cli.js"), "--version"],
    ),
    git: version("git", ["--version"], repoRoot),
    uv: version("uv", ["--version"], repoRoot),
    xcode: version("xcodebuild", ["-version"], desktopRoot, true),
    macos: version("sw_vers", ["-productVersion"]),
    x64_python: version(path.join(desktopRoot, "runtime", "x64", "python", "bin", "python3.12"), ["--version"]),
    arm64_python: version(path.join(desktopRoot, "runtime", "arm64", "python", "bin", "python3.12"), ["--version"]),
  };
}

function profileSnapshot(profile) {
  const keys = [
    "channel", "productName", "appBundleName", "appId", "packageName", "artifactPrefix",
    "downloadAliasPrefix", "downloadAliasPrefixes", "protocolScheme",
    "elevateHomeName", "workspaceName", "preferredPort", "gatewayLabel",
  ];
  if (profile.isBeta) keys.push(
    "entitlementAssertionSchema",
    "entitlementAssertionAcceptedKeyIds",
    "entitlementAssertionKeysetSha256",
  );
  return Object.fromEntries(keys.map((key) => [key, profile[key]]));
}

function recoveryArtifactNames(version = REALTOR_BETA_RECOVERY_VERSION) {
  return ARCHITECTURES.flatMap((architecture) => [
    `${RECOVERY_ARTIFACT_PREFIX}-${version}-mac-${architecture}.zip`,
    `${RECOVERY_ARTIFACT_PREFIX}-${version}-mac-${architecture}.dmg`,
  ]);
}

function recoveryAppPaths(profile = resolveReleaseProfile("beta")) {
  return {
    x64: path.join("desktop", "dist", "recovery", "mac", profile.appBundleName),
    arm64: path.join("desktop", "dist", "recovery", "mac-arm64", profile.appBundleName),
  };
}

function realtorBetaRecoverySourceContract(release) {
  if (release?.channel !== "beta" || release.version !== REALTOR_BETA_RECOVERY_CANDIDATE_VERSION) {
    return null;
  }
  const profile = profileSnapshot(resolveReleaseProfile("beta"));
  return {
    schema_version: RECOVERY_RECEIPT_SCHEMA_VERSION,
    kind: "elevate-beta-recovery-source-contract",
    candidate_version: REALTOR_BETA_RECOVERY_CANDIDATE_VERSION,
    version: REALTOR_BETA_RECOVERY_VERSION,
    reserved_version: REALTOR_BETA_RECOVERY_VERSION,
    next_full_beta_minimum_exclusive: REALTOR_BETA_RECOVERY_VERSION,
    channel: "beta",
    public_feed_name: RECOVERY_FEED_NAME,
    local_feed_path: path.join("desktop", "dist", "recovery", RECOVERY_FEED_NAME),
    profile,
    architectures: ARCHITECTURES,
    artifact_names: recoveryArtifactNames(),
    app_paths: recoveryAppPaths(),
    pre_sign_paths: Object.fromEntries(ARCHITECTURES.map((arch) => [
      arch,
      path.join("desktop", "dist", "recovery", `pre-sign-recovery-${arch}.json`),
    ])),
  };
}

function validateRealtorBetaRecoverySourceContract(release) {
  const expected = realtorBetaRecoverySourceContract(release);
  if (!expected) {
    if (release?.recovery != null) {
      throw new Error("[candidate] recovery package is attached to the wrong Beta candidate version");
    }
    return null;
  }
  if (canonicalJson(release?.recovery) !== canonicalJson(expected)) {
    throw new Error("[candidate] exact Realtor Beta recovery source contract is missing or has drifted");
  }
  if (compareSemver(expected.version, release.version) <= 0) {
    throw new Error("[candidate] recovery version must be newer than the candidate version");
  }
  return expected;
}

function assertPackagedMetadata(packageMetadata, release, expectedSourceReceiptId) {
  if (packageMetadata.version !== release.version
      || packageMetadata.name !== release.profile.packageName
      || packageMetadata.elevateReleaseChannel !== release.channel
      || !expectedSourceReceiptId
      || packageMetadata.elevateSourceReceiptId !== expectedSourceReceiptId) {
    throw new Error("[candidate] packaged release metadata drift");
  }
  return true;
}

function assertEmbeddedWebMatchesBuild(apps, webBuild) {
  for (const arch of ARCHITECTURES) {
    if (apps[arch]?.embedded_web?.sha256 !== webBuild?.generated_web?.manifest?.sha256
        || apps[arch]?.embedded_web?.portable?.sha256 !== webBuild?.generated_web?.portable?.sha256) {
      throw new Error(`[candidate] ${arch} embedded web does not match the source-bound web build receipt`);
    }
  }
  return true;
}

function createWebBuildReceipt({
  sourceReceiptId,
  webOutputPath = path.join(REPO, "cli", "elevate_cli", "web_dist"),
  outputPath = WEB_BUILD_RECEIPT,
  createdAt = new Date().toISOString(),
} = {}) {
  if (!sourceReceiptId) throw new Error("[candidate] web build requires a source receipt ID");
  if (fs.existsSync(outputPath)) {
    return verifyWebBuildReceipt({
      receiptPath: outputPath,
      sourceReceiptId,
      webOutputPath,
    });
  }
  const receipt = {
    schema_version: 1,
    kind: "elevate-candidate-web-build",
    created_at: createdAt,
    source_receipt_id: sourceReceiptId,
    generated_web: {
      path: path.relative(REPO, webOutputPath),
      manifest: hashTree(webOutputPath),
      portable: hashPortableTree(webOutputPath),
    },
  };
  return writeImmutableReceipt(outputPath, receipt, "web_build_id");
}

function verifyWebBuildReceipt({
  receiptPath = WEB_BUILD_RECEIPT,
  sourceReceiptId,
  webOutputPath,
  repoRoot = REPO,
} = {}) {
  if (!fs.existsSync(receiptPath)) throw new Error(`[candidate] missing web build receipt: ${receiptPath}`);
  const receipt = readJson(receiptPath);
  if (receiptId(receipt, "web_build_id") !== receipt.web_build_id) throw new Error("[candidate] web build receipt ID mismatch");
  if (!sourceReceiptId || receipt.source_receipt_id !== sourceReceiptId) throw new Error("[candidate] web build source receipt mismatch");
  const output = webOutputPath || path.join(repoRoot, receipt.generated_web.path);
  const manifest = hashTree(output);
  const portable = hashPortableTree(output);
  if (manifest.sha256 !== receipt.generated_web.manifest.sha256
      || portable.sha256 !== receipt.generated_web.portable.sha256) {
    throw new Error("[candidate] generated web output changed after build receipt");
  }
  return receipt;
}

function runMacBuilders(options = {}) {
  const commands = releaseCommandDefaults({ npmCli: options.npmCli || npmCliPath() });
  const {
    npmCli = commands.npmCli,
    verifySource = () => {
      const packageJson = require(path.join(DESKTOP, "package.json"));
      const channel = (process.env.ELEVATE_RELEASE_CHANNEL || "latest").trim().toLowerCase();
      return verifySourceReceipt({ channel, version: packageJson.version });
    },
    builderCommand = commands.builder.command,
    builderPrefixArgs = commands.builder.args,
    mergeCommand = commands.merge.command,
    mergeArgs = commands.merge.args,
    webCommand = commands.web.command,
    webArgs = commands.web.args,
    webOutputPath = path.join(REPO, "cli", "elevate_cli", "web_dist"),
    webReceiptPath = WEB_BUILD_RECEIPT,
    preSignEvidenceDirectory = DIST,
    cwd = DESKTOP,
    env = process.env,
    stdio = "inherit",
  } = options;
  const source = verifySource();
  const sourceReceiptId = source?.source_receipt_id;
  if (!sourceReceiptId) throw new Error("[candidate] verified source receipt has no ID");
  const buildEnv = {
    ...env,
    ELEVATE_SOURCE_RECEIPT_ID: sourceReceiptId,
    ELEVATE_RECOVERY_SOURCE_RECEIPT_ID: sourceReceiptId,
    NODE: process.execPath,
    npm_execpath: npmCli,
    npm_node_execpath: process.execPath,
    PATH: [path.dirname(process.execPath), env.PATH || ""].filter(Boolean).join(path.delimiter),
  };
  const web = spawnSync(webCommand, webArgs, { cwd, env: buildEnv, stdio });
  if (web.status !== 0) throw new Error(`[candidate] web build failed with exit ${web.status}`);
  if (verifySource().source_receipt_id !== sourceReceiptId) {
    throw new Error("[candidate] source receipt changed during web build");
  }
  createWebBuildReceipt({ sourceReceiptId, webOutputPath, outputPath: webReceiptPath });
  for (const architecture of ARCHITECTURES) {
    fs.rmSync(preSignEvidencePath(preSignEvidenceDirectory, architecture), { force: true });
  }
  for (const architecture of ARCHITECTURES) {
    const current = verifySource();
    if (current.source_receipt_id !== sourceReceiptId) {
      throw new Error("[candidate] source receipt changed between architecture builds");
    }
    fs.rmSync(preSignEvidencePath(preSignEvidenceDirectory, architecture), { force: true });
    const result = spawnSync(builderCommand, [
      ...builderPrefixArgs,
      "--config", "electron-builder.config.js", "--mac", "dmg", "zip",
      `--${architecture}`, "--publish", "never",
    ], { cwd, env: buildEnv, stdio });
    if (result.status !== 0) {
      throw new Error(`[candidate] ${architecture} electron-builder failed with exit ${result.status}`);
    }
  }
  if (verifySource().source_receipt_id !== sourceReceiptId) {
    throw new Error("[candidate] source receipt changed before feed merge");
  }
  const merge = spawnSync(mergeCommand, mergeArgs, { cwd, env: buildEnv, stdio });
  if (merge.status !== 0) throw new Error(`[candidate] feed merge failed with exit ${merge.status}`);
  return sourceReceiptId;
}

function createSourceReceipt({
  channel,
  version,
  profile,
  publicFeeds,
  sourceSafety,
  repoRoot = REPO,
  desktopRoot = DESKTOP,
  outputPath = SOURCE_RECEIPT,
  createdAt = new Date().toISOString(),
  toolchain,
  inputs,
} = {}) {
  if (!CHANNELS.has(channel)) throw new Error(`[candidate] unsupported channel: ${channel}`);
  const expectedProfile = profileSnapshot(resolveReleaseProfile(channel));
  if (canonicalJson(profileSnapshot(profile)) !== canonicalJson(expectedProfile)) {
    throw new Error("[candidate] release profile does not match the selected channel");
  }
  const git = currentGitState(repoRoot);
  if (!git.clean) throw new Error("[candidate] release worktree must be clean");
  const validatedSourceSafety = channel === "beta"
    ? validateBetaSourceSafetyEvidence(sourceSafety, { expectedGit: git, requireClean: true })
    : null;
  if (channel !== "beta" && sourceSafety != null) {
    throw new Error("[candidate] Beta source safety evidence cannot be attached to Stable");
  }
  const highestPublicVersion = assertGloballyNewVersion(version, publicFeeds);
  const resolvedInputs = inputs || sourceInputs({ repoRoot, desktopRoot });
  const resolvedToolchain = toolchain || captureToolchain({ repoRoot, desktopRoot });
  const finalGit = currentGitState(repoRoot);
  if (!finalGit.clean || canonicalJson(finalGit) !== canonicalJson(git)) {
    throw new Error("[candidate] checkout changed while the source receipt was being created");
  }
  const recovery = realtorBetaRecoverySourceContract({ channel, version });
  const receipt = {
    schema_version: SOURCE_RECEIPT_SCHEMA_VERSION,
    kind: "elevate-candidate-source",
    created_at: createdAt,
    git,
    release: {
      version,
      channel,
      profile: profileSnapshot(profile),
      architectures: ARCHITECTURES,
      feed_name: `${channel}-mac.yml`,
      artifact_names: releaseArtifactNames(profile, version),
      download_aliases: ARCHITECTURES.flatMap((arch) => downloadAliasFileNames(profile, arch)),
      ...(recovery ? { recovery } : {}),
    },
    inputs: resolvedInputs,
    toolchain: resolvedToolchain,
    ...(validatedSourceSafety ? { source_safety: validatedSourceSafety } : {}),
    public_feeds: publicFeeds,
    highest_public_version: highestPublicVersion,
    rollback_target: publicFeeds[channel] || null,
  };
  receipt.source_receipt_id = receiptId(receipt, "source_receipt_id");
  writeAtomicJson(outputPath, receipt);
  return receipt;
}

function verifySourceReceipt({
  receiptPath = SOURCE_RECEIPT,
  repoRoot = REPO,
  desktopRoot = DESKTOP,
  channel,
  version,
  requireClean = true,
} = {}) {
  if (!fs.existsSync(receiptPath)) throw new Error(`[candidate] missing source receipt: ${receiptPath}`);
  const receipt = readJson(receiptPath);
  if (
    receipt.schema_version !== SOURCE_RECEIPT_SCHEMA_VERSION ||
    receipt.kind !== "elevate-candidate-source"
  ) {
    throw new Error("[candidate] unsupported source receipt schema");
  }
  if (receiptId(receipt, "source_receipt_id") !== receipt.source_receipt_id) {
    throw new Error("[candidate] source receipt ID mismatch");
  }
  const git = currentGitState(repoRoot);
  if (git.commit !== receipt.git.commit
      || git.branch !== receipt.git.branch
      || git.linked_worktree !== Boolean(receipt.git.linked_worktree)
      || git.submodules !== (receipt.git.submodules || "")
      || (requireClean && !git.clean)) {
    throw new Error("[candidate] checkout no longer matches clean source receipt");
  }
  if (channel && channel !== receipt.release.channel) throw new Error("[candidate] release channel drift");
  if (version && version !== receipt.release.version) throw new Error("[candidate] release version drift");
  const expectedProfile = profileSnapshot(
    resolveReleaseProfile(receipt.release.channel),
  );
  if (canonicalJson(receipt.release.profile) !== canonicalJson(expectedProfile)) {
    throw new Error("[candidate] source receipt release profile drift");
  }
  validateRealtorBetaRecoverySourceContract(receipt.release);
  if (receipt.release.channel === "beta") {
    validateBetaSourceSafetyEvidence(receipt.source_safety, { expectedGit: git, requireClean: true });
  } else if (receipt.source_safety != null) {
    throw new Error("[candidate] Stable source receipt contains Beta source safety evidence");
  }
  for (const [label, expected] of Object.entries(receipt.inputs || {})) {
    const absolute = path.join(repoRoot, expected.path);
    const actual = expected.kind === "tree"
      ? hashTree(absolute, { mode: expected.mode })
      : fileRecord(absolute, repoRoot);
    if (actual.sha256 !== expected.sha256) throw new Error(`[candidate] source input drift: ${label}`);
    if (expected.kind === "tree" && expected.portable
        && hashPortableTree(absolute, { mode: expected.mode }).sha256 !== expected.portable.sha256) {
      throw new Error(`[candidate] portable source input drift: ${label}`);
    }
  }
  if (receipt.toolchain) {
    const currentToolchain = captureToolchain({ repoRoot, desktopRoot });
    if (canonicalJson(currentToolchain) !== canonicalJson(receipt.toolchain)) {
      throw new Error("[candidate] release toolchain drift");
    }
  }
  return receipt;
}

function plistJson(appPath) {
  const text = requireRun("plutil", ["-convert", "json", "-o", "-", path.join(appPath, "Contents", "Info.plist")]);
  return JSON.parse(text);
}

function appRecord(
  appPath,
  arch,
  release,
  relativeTo = DESKTOP,
  expectedSourceReceiptId = null,
  expectedDesktopSrcPortable = null,
) {
  const plist = plistJson(appPath);
  const resources = path.join(appPath, "Contents", "Resources");
  const embeddedCliRoot = path.join(resources, "cli");
  assertCanonicalPackagedPermissions(embeddedCliRoot, `${arch} packaged CLI`);
  const updatePath = path.join(resources, "app-update.yml");
  const update = yaml.load(fs.readFileSync(updatePath, "utf8")) || {};
  const asarPath = path.join(resources, "app.asar");
  assertCompleteAsar(asarPath);
  asar.uncache(asarPath);
  const packageMetadata = JSON.parse(asar.extractFile(asarPath, "package.json").toString("utf8"));
  const embeddedDesktopSrc = portableAsarDirectoryHash(asarPath, "src");
  const executable = path.join(appPath, "Contents", "MacOS", plist.CFBundleExecutable);
  const executableArchitectures = requireRun("lipo", ["-archs", executable]).split(/\s+/).filter(Boolean);
  const expectedArchitecture = arch === "x64" ? "x86_64" : "arm64";
  if (!executableArchitectures.includes(expectedArchitecture)) {
    throw new Error(`[candidate] ${arch} app executable is ${executableArchitectures.join(", ")}`);
  }
  const profile = release.profile;
  if (plist.CFBundleIdentifier !== profile.appId) throw new Error(`[candidate] ${arch} bundle ID drift`);
  if (plist.CFBundleShortVersionString !== release.version) throw new Error(`[candidate] ${arch} app version drift`);
  if (plist.CFBundleName !== profile.productName) throw new Error(`[candidate] ${arch} product name drift`);
  assertPackagedMetadata(packageMetadata, release, expectedSourceReceiptId);
  if (!expectedDesktopSrcPortable || embeddedDesktopSrc.sha256 !== expectedDesktopSrcPortable) {
    throw new Error(`[candidate] ${arch} packaged desktop/src does not match the source contract`);
  }
  if (update.provider !== "generic" || update.channel !== release.channel) {
    throw new Error(`[candidate] ${arch} app-update.yml channel/provider drift`);
  }
  if (String(update.url || "").replace(/\/+$/, "") !== PUBLIC_BASE_URL) {
    throw new Error(`[candidate] ${arch} app-update.yml feed URL drift`);
  }
  const schemes = (plist.CFBundleURLTypes || []).flatMap((item) => item.CFBundleURLSchemes || []);
  if (!schemes.includes(profile.protocolScheme)) throw new Error(`[candidate] ${arch} protocol identity drift`);
  const expectedCache = `${sanitizeFileName(profile.packageName).toLowerCase()}-updater`;
  if (update.updaterCacheDirName !== expectedCache) throw new Error(`[candidate] ${arch} updater cache identity drift`);
  const embeddedRuntimeRoot = path.join(resources, "runtime", "python");
  return {
    architecture: arch,
    app_path: path.relative(relativeTo, appPath),
    bundle_manifest: hashTree(appPath),
    embedded_cli: hashTree(embeddedCliRoot, { mode: "cli-packaging" }),
    embedded_web: {
      ...hashTree(path.join(resources, "cli", "elevate_cli", "web_dist")),
      portable: hashPortableTree(path.join(resources, "cli", "elevate_cli", "web_dist")),
    },
    embedded_whatsapp: hashTree(path.join(resources, "cli", "scripts", "whatsapp-bridge"), { mode: "whatsapp" }),
    embedded_runtime: {
      ...hashTree(embeddedRuntimeRoot, { mode: "runtime" }),
      code_normalized: hashRuntimeCodeTree(embeddedRuntimeRoot),
    },
    embedded_desktop_src: embeddedDesktopSrc,
    info_plist: {
      sha256: sha256File(path.join(appPath, "Contents", "Info.plist")),
      CFBundleIdentifier: plist.CFBundleIdentifier,
      CFBundleName: plist.CFBundleName,
      CFBundleDisplayName: plist.CFBundleDisplayName || null,
      CFBundleExecutable: plist.CFBundleExecutable,
      CFBundleShortVersionString: plist.CFBundleShortVersionString,
      CFBundleVersion: plist.CFBundleVersion,
      CFBundleURLTypes: plist.CFBundleURLTypes || [],
    },
    app_update: {
      sha256: sha256File(updatePath),
      provider: update.provider,
      url: update.url,
      channel: update.channel,
      updaterCacheDirName: update.updaterCacheDirName,
    },
    packaged_metadata: {
      asar_sha256: sha256File(asarPath),
      name: packageMetadata.name,
      version: packageMetadata.version,
      elevateReleaseChannel: packageMetadata.elevateReleaseChannel,
      elevateSourceReceiptId: packageMetadata.elevateSourceReceiptId || null,
    },
    executable_architectures: executableArchitectures,
  };
}

function assertBundleManifest(actual, expected, label) {
  if (!actual || !expected || actual.sha256 !== expected.sha256
      || actual.file_count !== expected.file_count || actual.size !== expected.size) {
    throw new Error(`[candidate] ${label} app payload does not match the smoke-tested app bundle`);
  }
  return true;
}

function validateZipEntries(entries, appBundleName) {
  if (!Array.isArray(entries) || entries.length === 0) throw new Error("[candidate] ZIP has no entries");
  const seen = new Set();
  for (const raw of entries) validateZipEntry(raw, appBundleName, seen);
  return true;
}

function validateZipEntry(raw, appBundleName, seen) {
  const entry = String(raw || "");
  if (!entry || entry.includes("\\") || entry.startsWith("/") || entry.includes("\0")) {
    throw new Error(`[candidate] unsafe ZIP entry: ${entry}`);
  }
  const parts = entry.split("/").filter(Boolean);
  if (parts.some((part) => part === "..") || parts[0] !== appBundleName) {
    throw new Error(`[candidate] ZIP entry escapes the expected app bundle: ${entry}`);
  }
  const normalized = parts.join("/");
  if (seen.has(normalized)) throw new Error(`[candidate] duplicate ZIP entry: ${entry}`);
  seen.add(normalized);
}

function validateZipEntryListing(listingPath, appBundleName) {
  const fd = fs.openSync(listingPath, "r");
  const decoder = new StringDecoder("utf8");
  const buffer = Buffer.allocUnsafe(64 * 1024);
  const seen = new Set();
  let pending = "";
  let entryCount = 0;
  const consume = (text, final = false) => {
    pending += text;
    const lines = pending.split("\n");
    const tail = lines.pop();
    pending = final ? "" : tail;
    for (const line of lines) {
      validateZipEntry(line.endsWith("\r") ? line.slice(0, -1) : line, appBundleName, seen);
      entryCount += 1;
    }
    if (final && tail) {
      validateZipEntry(tail.endsWith("\r") ? tail.slice(0, -1) : tail, appBundleName, seen);
      entryCount += 1;
    }
  };
  try {
    let bytes = 0;
    while ((bytes = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0) {
      consume(decoder.write(buffer.subarray(0, bytes)));
    }
    consume(decoder.end(), true);
  } finally {
    fs.closeSync(fd);
  }
  if (entryCount === 0) throw new Error("[candidate] ZIP has no entries");
  return true;
}

function validateZipArchiveEntries(zipPath, appBundleName) {
  const listingPath = path.join(os.tmpdir(), `elevate-zip-entries-${process.pid}-${crypto.randomUUID()}.txt`);
  let outputFd = null;
  try {
    outputFd = fs.openSync(listingPath, "wx", 0o600);
    const result = spawnSync("unzip", ["-Z1", zipPath], {
      cwd: DESKTOP,
      encoding: "utf8",
      timeout: 120_000,
      stdio: ["ignore", outputFd, "pipe"],
    });
    const completedOutputFd = outputFd;
    outputFd = null;
    fs.closeSync(completedOutputFd);
    if (result?.status !== 0 || result?.error) {
      const detail = `${result?.stderr || ""}\n${result?.error?.message || ""}`.trim();
      throw new Error(`[candidate] unzip -Z1 ${zipPath} failed${detail ? `: ${detail}` : ""}`);
    }
    return validateZipEntryListing(listingPath, appBundleName);
  } finally {
    if (outputFd !== null) fs.closeSync(outputFd);
    fs.rmSync(listingPath, { force: true });
  }
}

function assertContainedSymlinks(root) {
  const absoluteRoot = path.resolve(root);
  function walk(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const absolute = path.join(directory, entry.name);
      const stat = fs.lstatSync(absolute);
      if (stat.isSymbolicLink()) {
        const resolved = path.resolve(path.dirname(absolute), fs.readlinkSync(absolute));
        if (resolved !== absoluteRoot && !resolved.startsWith(`${absoluteRoot}${path.sep}`)) {
          throw new Error(`[candidate] extracted app contains escaping symlink: ${path.relative(absoluteRoot, absolute)}`);
        }
      } else if (stat.isDirectory()) {
        walk(absolute);
      }
    }
  }
  walk(absoluteRoot);
}

function verifyZipAppPayload(zipPath, appBundleName, expectedManifest) {
  validateZipArchiveEntries(zipPath, appBundleName);
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-candidate-zip-"));
  try {
    requireRun("ditto", ["-x", "-k", zipPath, temp], { timeout: 600_000 });
    const appPath = path.join(temp, appBundleName);
    if (!fs.statSync(appPath).isDirectory()) throw new Error(`[candidate] ZIP missing ${appBundleName}`);
    assertContainedSymlinks(appPath);
    const manifest = hashTree(appPath);
    assertBundleManifest(manifest, expectedManifest, path.basename(zipPath));
    return { method: "safe-zip-extract", app_bundle_name: appBundleName, bundle_manifest: manifest };
  } finally {
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

function verifyDmgAppPayload(dmgPath, appBundleName, expectedManifest) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-candidate-dmg-"));
  let attached = false;
  try {
    requireRun("hdiutil", ["attach", "-readonly", "-nobrowse", "-mountpoint", temp, dmgPath], { timeout: 300_000 });
    attached = true;
    const appPath = path.join(temp, appBundleName);
    if (!fs.statSync(appPath).isDirectory()) throw new Error(`[candidate] DMG missing ${appBundleName}`);
    assertContainedSymlinks(appPath);
    const manifest = hashTree(appPath);
    assertBundleManifest(manifest, expectedManifest, path.basename(dmgPath));
    return { method: "readonly-dmg-mount", app_bundle_name: appBundleName, bundle_manifest: manifest };
  } finally {
    const detach = run("hdiutil", ["detach", "-force", temp], { timeout: attached ? 120_000 : 30_000 });
    if (attached && !detach.ok) {
      throw new Error(`[candidate] failed to detach DMG mount ${temp}`);
    }
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

function verifyArtifactPayloads({
  release,
  apps,
  desktopRoot = DESKTOP,
  artifactRoot = path.join(desktopRoot, "dist"),
} = {}) {
  const evidence = {};
  for (const arch of ARCHITECTURES) {
    const zip = release.artifact_names.find((name) => name.endsWith(`-mac-${arch}.zip`));
    const dmg = release.artifact_names.find((name) => name.endsWith(`-mac-${arch}.dmg`));
    if (!zip || !dmg) throw new Error(`[candidate] missing ${arch} ZIP/DMG artifact names`);
    evidence[arch] = {
      zip: { artifact: zip, ...verifyZipAppPayload(path.join(artifactRoot, zip), release.profile.appBundleName, apps[arch].bundle_manifest) },
      dmg: { artifact: dmg, ...verifyDmgAppPayload(path.join(artifactRoot, dmg), release.profile.appBundleName, apps[arch].bundle_manifest) },
    };
  }
  return evidence;
}

function normalizedEvidence(result, roots = [REPO, DESKTOP]) {
  let output = `${result.stdout || ""}\n${result.stderr || ""}`.trim();
  for (const root of roots) output = output.replaceAll(root, "<repo>");
  if (output.length > 16_000) output = `${output.slice(0, 16_000)}\n<truncated>`;
  return { ok: result.ok, status: result.status, output, output_sha256: sha256(output) };
}

function assertTrustedSignerEvidence(details, requirement, label = "signed artifact") {
  const authorityPattern = new RegExp(`Authority=Developer ID Application:.*\\(${TRUSTED_APPLE_TEAM_ID}\\)`);
  const teamPattern = new RegExp(`TeamIdentifier=${TRUSTED_APPLE_TEAM_ID}`);
  const requirementPattern = new RegExp(`certificate leaf\\[subject\\.OU\\] = ${TRUSTED_APPLE_TEAM_ID}`);
  if (!authorityPattern.test(details || "") || !teamPattern.test(details || "")
      || !/anchor apple generic/.test(requirement || "") || !requirementPattern.test(requirement || "")) {
    throw new Error(`[candidate] ${label} is not signed by trusted TeamIdentifier ${TRUSTED_APPLE_TEAM_ID}`);
  }
  return true;
}

function collectAppSigningEvidence(appPath) {
  const commands = {
    codesign_verify: ["codesign", ["--verify", "--deep", "--strict", "--verbose=2", appPath]],
    codesign_details: ["codesign", ["-d", "--verbose=4", appPath]],
    designated_requirement: ["codesign", ["-d", "-r-", appPath]],
    gatekeeper: ["spctl", ["--assess", "--type", "execute", "--verbose=4", appPath]],
    staple: ["xcrun", ["stapler", "validate", appPath]],
    entitlements: ["codesign", ["-d", "--entitlements", ":-", appPath]],
  };
  const evidence = Object.fromEntries(Object.entries(commands).map(([key, [command, args]]) => {
    const result = run(command, args, { timeout: 600_000 });
    return [key, normalizedEvidence(result)];
  }));
  for (const [name, item] of Object.entries(evidence)) {
    if (!item.ok) throw new Error(`[candidate] app signing evidence failed: ${name}`);
  }
  if (!/runtime/i.test(evidence.codesign_details.output)) {
    throw new Error("[candidate] hardened-runtime flag missing from codesign details");
  }
  assertTrustedSignerEvidence(
    evidence.codesign_details.output,
    evidence.designated_requirement.output,
    "app bundle",
  );
  return evidence;
}

function collectDmgSigningEvidence(dmgPath) {
  const commands = {
    codesign_verify: ["codesign", ["--verify", "--verbose=2", dmgPath]],
    codesign_details: ["codesign", ["-d", "--verbose=4", dmgPath]],
    designated_requirement: ["codesign", ["-d", "-r-", dmgPath]],
    gatekeeper: ["spctl", ["-a", "-vv", "--type", "open", "--context", "context:primary-signature", dmgPath]],
    staple: ["xcrun", ["stapler", "validate", dmgPath]],
  };
  const evidence = Object.fromEntries(Object.entries(commands).map(([key, [command, args]]) => {
    const result = run(command, args, { timeout: 600_000 });
    return [key, normalizedEvidence(result)];
  }));
  for (const [name, item] of Object.entries(evidence)) {
    if (!item.ok) throw new Error(`[candidate] recovery DMG signing evidence failed: ${name}`);
  }
  assertTrustedSignerEvidence(
    evidence.codesign_details.output,
    evidence.designated_requirement.output,
    path.basename(dmgPath),
  );
  return evidence;
}

function assertStoredSigningEvidence(evidence, label, { hardenedRuntime = false } = {}) {
  const required = [
    "codesign_verify",
    "codesign_details",
    "designated_requirement",
    "gatekeeper",
    "staple",
  ];
  for (const name of required) {
    const item = evidence?.[name];
    if (!item || item.ok !== true || item.status !== 0
        || !/^[a-f0-9]{64}$/.test(item.output_sha256 || "")) {
      throw new Error(`[candidate] ${label} has invalid ${name} provenance`);
    }
  }
  if (hardenedRuntime && !/runtime/i.test(evidence.codesign_details.output || "")) {
    throw new Error(`[candidate] ${label} hardened-runtime provenance is missing`);
  }
  assertTrustedSignerEvidence(
    evidence.codesign_details.output,
    evidence.designated_requirement.output,
    label,
  );
  return true;
}

function signingTrustRecord(evidence) {
  return {
    signed: true,
    notarized: true,
    stapled: true,
    verification_method: "codesign-gatekeeper-stapled-ticket",
    signing_evidence_sha256: sha256(canonicalJson(evidence)),
    notarization_evidence_sha256: evidence.staple.output_sha256,
    stapling_evidence_sha256: evidence.staple.output_sha256,
  };
}

function embeddedRecoverySources(asarPath, desktopSrcRoot = path.join(DESKTOP, "src")) {
  const sources = {};
  for (const name of RECOVERY_SOURCE_FILES) {
    const entry = `src/${name}`;
    const bytes = asar.extractFile(asarPath, entry);
    const sourcePath = path.join(desktopSrcRoot, name);
    const sourceBytes = fs.readFileSync(sourcePath);
    if (!bytes.equals(sourceBytes)) {
      throw new Error(`[candidate] packaged recovery source drift: ${entry}`);
    }
    sources[entry] = {
      size: bytes.length,
      sha256: sha256(bytes),
    };
  }
  return sources;
}

function recoveryAppRecord({
  appPath,
  architecture,
  sourceReceiptId,
  relativeTo = DESKTOP,
  desktopSrcRoot = path.join(DESKTOP, "src"),
} = {}) {
  const arch = normalizeArchitecture(architecture);
  if (!ARCHITECTURES.includes(arch)) throw new Error(`[candidate] unsupported recovery architecture: ${architecture}`);
  if (!/^[a-f0-9]{64}$/.test(sourceReceiptId || "")) {
    throw new Error("[candidate] recovery package requires a valid source receipt ID");
  }
  const profile = profileSnapshot(resolveReleaseProfile("beta"));
  const plist = plistJson(appPath);
  const resources = path.join(appPath, "Contents", "Resources");
  const asarPath = path.join(resources, "app.asar");
  const updatePath = path.join(resources, "app-update.yml");
  assertCompleteAsar(asarPath);
  asar.uncache(asarPath);
  const packageMetadata = JSON.parse(asar.extractFile(asarPath, "package.json").toString("utf8"));
  const update = yaml.load(fs.readFileSync(updatePath, "utf8")) || {};
  const executable = path.join(appPath, "Contents", "MacOS", plist.CFBundleExecutable);
  const executableArchitectures = requireRun("lipo", ["-archs", executable]).split(/\s+/).filter(Boolean);
  const expectedArchitecture = arch === "x64" ? "x86_64" : "arm64";
  const schemes = (plist.CFBundleURLTypes || []).flatMap((item) => item.CFBundleURLSchemes || []);
  const expectedCache = `${sanitizeFileName(profile.packageName).toLowerCase()}-updater`;
  if (!executableArchitectures.includes(expectedArchitecture)
      || plist.CFBundleIdentifier !== profile.appId
      || plist.CFBundleShortVersionString !== REALTOR_BETA_RECOVERY_VERSION
      || plist.CFBundleName !== profile.productName
      || (plist.CFBundleDisplayName || profile.productName) !== profile.productName
      || !schemes.includes(profile.protocolScheme)
      || packageMetadata.name !== profile.packageName
      || packageMetadata.version !== REALTOR_BETA_RECOVERY_VERSION
      || packageMetadata.main !== "src/recovery-main.js"
      || packageMetadata.elevateReleaseChannel !== "beta"
      || packageMetadata.elevateRecoveryMode !== true
      || packageMetadata.elevateRecoverySourceReceiptId !== sourceReceiptId
      || update.provider !== "generic"
      || update.channel !== "beta"
      || String(update.url || "").replace(/\/+$/, "") !== PUBLIC_BASE_URL
      || update.updaterCacheDirName !== expectedCache) {
    throw new Error(`[candidate] ${arch} recovery app identity or source binding drift`);
  }
  const signing = collectAppSigningEvidence(appPath);
  return {
    architecture: arch,
    app_path: path.relative(relativeTo, appPath),
    bundle_manifest: hashTree(appPath),
    embedded_recovery_sources: embeddedRecoverySources(asarPath, desktopSrcRoot),
    info_plist: {
      sha256: sha256File(path.join(appPath, "Contents", "Info.plist")),
      CFBundleIdentifier: plist.CFBundleIdentifier,
      CFBundleName: plist.CFBundleName,
      CFBundleDisplayName: plist.CFBundleDisplayName || null,
      CFBundleExecutable: plist.CFBundleExecutable,
      CFBundleShortVersionString: plist.CFBundleShortVersionString,
      CFBundleVersion: plist.CFBundleVersion,
      CFBundleURLTypes: plist.CFBundleURLTypes || [],
    },
    app_update: {
      sha256: sha256File(updatePath),
      provider: update.provider,
      url: update.url,
      channel: update.channel,
      updaterCacheDirName: update.updaterCacheDirName,
    },
    packaged_metadata: {
      asar_sha256: sha256File(asarPath),
      name: packageMetadata.name,
      version: packageMetadata.version,
      main: packageMetadata.main,
      elevateReleaseChannel: packageMetadata.elevateReleaseChannel,
      elevateRecoveryMode: packageMetadata.elevateRecoveryMode,
      elevateRecoverySourceReceiptId: packageMetadata.elevateRecoverySourceReceiptId,
    },
    executable_architectures: executableArchitectures,
    signing,
    trust: signingTrustRecord(signing),
  };
}

function assertFileRecord(filePath, expected, label = path.basename(filePath)) {
  if (!expected || !Number.isSafeInteger(expected.size) || expected.size < 0
      || !/^[a-f0-9]{64}$/.test(expected.sha256 || "")) {
    throw new Error(`[candidate] ${label} has an invalid file record`);
  }
  const actualSize = fs.statSync(filePath).size;
  if (actualSize !== expected.size) throw new Error(`[candidate] ${label} size mismatch`);
  const actualHash = sha256File(filePath);
  if (actualHash !== expected.sha256) throw new Error(`[candidate] ${label} SHA256 mismatch`);
  if (expected.sha512 != null) {
    const decoded = Buffer.from(String(expected.sha512), "base64");
    if (decoded.length !== 64 || decoded.toString("base64") !== expected.sha512) {
      throw new Error(`[candidate] ${label} has an invalid SHA512`);
    }
    const actualSha512 = hashFileWith(filePath, "sha512", "base64");
    if (actualSha512 !== expected.sha512) throw new Error(`[candidate] ${label} SHA512 mismatch`);
  }
  return true;
}

function validateFeed(feed, release, artifacts) {
  if (!feed || String(feed.version || "") !== release.version) throw new Error("[candidate] feed version drift");
  const expectedNames = release.artifact_names.slice().sort();
  const entries = Array.isArray(feed.files) ? feed.files : [];
  const urls = entries.map((entry) => entry?.url);
  for (const url of urls) {
    if (typeof url !== "string" || !url || path.posix.basename(url) !== url
        || url.includes("\\") || url.includes("?") || url.includes("#") || url === "." || url === "..") {
      throw new Error(`[candidate] unsafe feed artifact URL: ${url}`);
    }
  }
  if (new Set(urls).size !== urls.length) throw new Error("[candidate] feed contains duplicate artifact URLs");
  if (canonicalJson(urls.slice().sort()) !== canonicalJson(expectedNames)) {
    throw new Error("[candidate] feed artifact URL set does not exactly match the candidate");
  }
  for (const entry of entries) {
    const expected = artifacts[entry.url];
    if (!expected || Number(entry.size) !== expected.size || entry.sha512 !== expected.sha512) {
      throw new Error(`[candidate] feed metadata mismatch for ${entry.url}`);
    }
  }
  const primary = release.artifact_names.find((name) => name.endsWith("-mac-x64.zip"));
  const primaryEntry = entries.find((entry) => entry.url === primary);
  if (!primary || feed.path !== primary || !primaryEntry || feed.sha512 !== primaryEntry.sha512) {
    throw new Error("[candidate] feed top-level path/sha512 does not identify the primary x64 updater ZIP");
  }
  return true;
}

function validateRecoveryPreSignEvidence(evidence, {
  architecture,
  sourceReceiptId,
  app,
  contract,
} = {}) {
  const expectedSourceFiles = RECOVERY_SOURCE_FILES.map((name) => `src/${name}`).sort();
  if (!evidence
      || evidence.schema_version !== 1
      || evidence.kind !== "elevate-beta-roll-forward-recovery-pre-sign"
      || receiptId(evidence, "evidence_id") !== evidence.evidence_id
      || evidence.architecture !== architecture
      || evidence.app_bundle_name !== contract.profile.appBundleName
      || evidence.app_id !== contract.profile.appId
      || evidence.package_name !== contract.profile.packageName
      || evidence.protocol_scheme !== contract.profile.protocolScheme
      || evidence.release_channel !== "beta"
      || evidence.candidate_version !== contract.candidate_version
      || evidence.recovery_version !== contract.version
      || evidence.source_receipt_id !== sourceReceiptId
      || evidence.app_asar_sha256 !== app.packaged_metadata.asar_sha256
      || evidence.updater_config_sha256 !== app.app_update.sha256
      || canonicalJson(evidence.runtime_policy) !== canonicalJson(RECOVERY_RUNTIME_POLICY)
      || canonicalJson(evidence.asar_source_files) !== canonicalJson(expectedSourceFiles)) {
    throw new Error(`[candidate] invalid ${architecture} recovery pre-sign evidence`);
  }
  return evidence;
}

function recoveryRuntimePolicy(preSignContracts) {
  for (const arch of ARCHITECTURES) {
    if (canonicalJson(preSignContracts?.[arch]?.runtime_policy) !== canonicalJson(RECOVERY_RUNTIME_POLICY)) {
      throw new Error(`[candidate] ${arch} recovery runtime policy is missing or unsafe`);
    }
  }
  return { ...RECOVERY_RUNTIME_POLICY };
}

function recoveryStaticProvenance(recovery) {
  return {
    schema_version: 1,
    kind: "elevate-beta-recovery-static-provenance",
    source_receipt_id: recovery.source_receipt_id,
    candidate_version: recovery.candidate_version,
    recovery_version: recovery.version,
    profile_sha256: sha256(canonicalJson(recovery.profile)),
    feed_sha256: recovery.local_feed.sha256,
    feed_sha512: recovery.local_feed.sha512,
    artifact_sha256: Object.fromEntries(recovery.artifact_names.map((name) => [name, recovery.artifacts[name].sha256])),
    artifact_sha512: Object.fromEntries(recovery.artifact_names.map((name) => [name, recovery.artifacts[name].sha512])),
    artifact_provenance_sha256: Object.fromEntries(recovery.artifact_names.map((name) => [
      name,
      sha256(canonicalJson({
        architecture: recovery.artifacts[name].architecture,
        format: recovery.artifacts[name].format,
        packaged_app: recovery.artifacts[name].packaged_app,
        container_trust: recovery.artifacts[name].container_trust,
      })),
    ])),
    app_bundle_sha256: Object.fromEntries(ARCHITECTURES.map((arch) => [arch, recovery.apps[arch].bundle_manifest.sha256])),
    app_signing_sha256: Object.fromEntries(ARCHITECTURES.map((arch) => [arch, recovery.apps[arch].trust.signing_evidence_sha256])),
    dmg_signing_sha256: Object.fromEntries(ARCHITECTURES.map((arch) => [arch, recovery.signing.dmgs[arch].trust.signing_evidence_sha256])),
    pre_sign_evidence_id: Object.fromEntries(ARCHITECTURES.map((arch) => [arch, recovery.pre_sign_contracts[arch].evidence_id])),
    runtime_policy: recoveryRuntimePolicy(recovery.pre_sign_contracts),
  };
}

function createRecoveryReceipt({
  source,
  release,
  desktopRoot = DESKTOP,
  repoRoot = REPO,
} = {}) {
  const contract = validateRealtorBetaRecoverySourceContract(release);
  if (!contract) return null;
  if (!/^[a-f0-9]{64}$/.test(source?.source_receipt_id || "")) {
    throw new Error("[candidate] recovery finalization requires the exact source receipt ID");
  }
  const recoveryRoot = path.join(desktopRoot, "dist", "recovery");
  const recoveryRelease = {
    version: contract.version,
    channel: contract.channel,
    profile: contract.profile,
    architectures: contract.architectures,
    feed_name: contract.public_feed_name,
    artifact_names: contract.artifact_names,
  };
  const artifacts = Object.fromEntries(contract.artifact_names.map((name) => {
    const architecture = name.includes("-arm64.") ? "arm64" : "x64";
    const format = path.extname(name).slice(1);
    return [name, {
      ...fileRecord(path.join(recoveryRoot, name), repoRoot, { includeSha512: true }),
      architecture,
      format,
    }];
  }));
  const feedPath = path.join(recoveryRoot, RECOVERY_FEED_NAME);
  const feedManifest = yaml.load(fs.readFileSync(feedPath, "utf8")) || {};
  validateFeed(feedManifest, recoveryRelease, artifacts);
  const apps = Object.fromEntries(ARCHITECTURES.map((arch) => [arch, recoveryAppRecord({
    appPath: path.join(repoRoot, contract.app_paths[arch]),
    architecture: arch,
    sourceReceiptId: source.source_receipt_id,
    relativeTo: repoRoot,
    desktopSrcRoot: path.join(desktopRoot, "src"),
  })]));
  if (canonicalJson(apps.x64.embedded_recovery_sources) !== canonicalJson(apps.arm64.embedded_recovery_sources)) {
    throw new Error("[candidate] recovery source payload differs across architectures");
  }
  const preSignContracts = Object.fromEntries(ARCHITECTURES.map((arch) => {
    const evidencePath = path.join(repoRoot, contract.pre_sign_paths[arch]);
    if (!fs.existsSync(evidencePath)) {
      throw new Error(`[candidate] missing ${arch} recovery pre-sign evidence: ${evidencePath}`);
    }
    const evidence = readJson(evidencePath);
    return [arch, validateRecoveryPreSignEvidence(evidence, {
      architecture: arch,
      sourceReceiptId: source.source_receipt_id,
      app: apps[arch],
      contract,
    })];
  }));
  const dmgs = Object.fromEntries(ARCHITECTURES.map((arch) => {
    const name = contract.artifact_names.find((artifact) => artifact.endsWith(`-mac-${arch}.dmg`));
    const evidence = collectDmgSigningEvidence(path.join(recoveryRoot, name));
    return [arch, { artifact: name, evidence, trust: signingTrustRecord(evidence) }];
  }));
  for (const name of contract.artifact_names) {
    const record = artifacts[name];
    record.packaged_app = {
      bundle_manifest_sha256: apps[record.architecture].bundle_manifest.sha256,
      ...apps[record.architecture].trust,
    };
    record.container_trust = record.format === "dmg" ? dmgs[record.architecture].trust : null;
  }
  const recovery = {
    schema_version: RECOVERY_RECEIPT_SCHEMA_VERSION,
    kind: "elevate-beta-recovery-package",
    candidate_version: release.version,
    version: contract.version,
    reserved_version: contract.reserved_version,
    next_full_beta_minimum_exclusive: contract.next_full_beta_minimum_exclusive,
    source_receipt_id: source.source_receipt_id,
    channel: contract.channel,
    public_feed_name: contract.public_feed_name,
    profile: contract.profile,
    architectures: contract.architectures,
    artifact_names: contract.artifact_names,
    local_feed: {
      ...fileRecord(feedPath, repoRoot, { includeSha512: true }),
      manifest: feedManifest,
    },
    artifacts,
    apps,
    pre_sign_contracts: preSignContracts,
    artifact_payloads: verifyArtifactPayloads({
      release: recoveryRelease,
      apps,
      desktopRoot,
      artifactRoot: recoveryRoot,
    }),
    signing: { dmgs },
  };
  recovery.static_provenance = recoveryStaticProvenance(recovery);
  return recovery;
}

function assertRecoveryTreeRecord(record, label) {
  if (!record || !Number.isSafeInteger(record.file_count) || record.file_count < 1
      || !Number.isSafeInteger(record.size) || record.size < 1
      || !/^[a-f0-9]{64}$/.test(record.sha256 || "")) {
    throw new Error(`[candidate] invalid recovery ${label} manifest`);
  }
}

function validateRecoveryAppReceipt(app, arch, contract, sourceReceiptId) {
  const expectedExecutableArchitecture = arch === "x64" ? "x86_64" : "arm64";
  const profile = contract.profile;
  if (app?.architecture !== arch
      || app.app_path !== contract.app_paths[arch]
      || app.info_plist?.CFBundleIdentifier !== profile.appId
      || app.info_plist?.CFBundleName !== profile.productName
      || app.info_plist?.CFBundleShortVersionString !== contract.version
      || app.packaged_metadata?.name !== profile.packageName
      || app.packaged_metadata?.version !== contract.version
      || app.packaged_metadata?.main !== "src/recovery-main.js"
      || app.packaged_metadata?.elevateReleaseChannel !== "beta"
      || app.packaged_metadata?.elevateRecoveryMode !== true
      || app.packaged_metadata?.elevateRecoverySourceReceiptId !== sourceReceiptId
      || app.app_update?.provider !== "generic"
      || app.app_update?.channel !== "beta"
      || String(app.app_update?.url || "").replace(/\/+$/, "") !== PUBLIC_BASE_URL
      || app.app_update?.updaterCacheDirName !== `${sanitizeFileName(profile.packageName).toLowerCase()}-updater`
      || !Array.isArray(app.executable_architectures)
      || !app.executable_architectures.includes(expectedExecutableArchitecture)) {
    throw new Error(`[candidate] ${arch} recovery receipt identity or source binding is invalid`);
  }
  assertRecoveryTreeRecord(app.bundle_manifest, `${arch} app`);
  if (canonicalJson(Object.keys(app.embedded_recovery_sources || {}).sort())
      !== canonicalJson(RECOVERY_SOURCE_FILES.map((name) => `src/${name}`).sort())) {
    throw new Error(`[candidate] ${arch} recovery static source provenance is incomplete`);
  }
  for (const [name, record] of Object.entries(app.embedded_recovery_sources)) {
    if (!Number.isSafeInteger(record?.size) || record.size < 1 || !/^[a-f0-9]{64}$/.test(record.sha256 || "")) {
      throw new Error(`[candidate] ${arch} recovery static source provenance is invalid: ${name}`);
    }
  }
  assertStoredSigningEvidence(app.signing, `${arch} recovery app`, { hardenedRuntime: true });
  if (canonicalJson(app.trust) !== canonicalJson(signingTrustRecord(app.signing))) {
    throw new Error(`[candidate] ${arch} recovery app trust provenance mismatch`);
  }
  return true;
}

function validateRecoveryReceipt(receipt, {
  desktopRoot = DESKTOP,
  repoRoot = REPO,
  requireFiles = true,
  requireApps = true,
} = {}) {
  const contract = realtorBetaRecoverySourceContract(receipt?.release);
  if (!contract) {
    if (receipt?.recovery != null) throw new Error("[candidate] recovery package is attached to the wrong candidate");
    return null;
  }
  if (receipt.release?.recovery != null) validateRealtorBetaRecoverySourceContract(receipt.release);
  const recovery = receipt.recovery;
  const exactProfile = profileSnapshot(resolveReleaseProfile("beta"));
  if (!recovery
      || recovery.schema_version !== RECOVERY_RECEIPT_SCHEMA_VERSION
      || recovery.kind !== "elevate-beta-recovery-package"
      || recovery.candidate_version !== receipt.release.version
      || recovery.version !== contract.version
      || recovery.reserved_version !== contract.version
      || recovery.next_full_beta_minimum_exclusive !== contract.version
      || recovery.source_receipt_id !== receipt.source_receipt_id
      || !/^[a-f0-9]{64}$/.test(recovery.source_receipt_id || "")
      || recovery.channel !== "beta"
      || recovery.public_feed_name !== RECOVERY_FEED_NAME
      || canonicalJson(receipt.release.profile) !== canonicalJson(exactProfile)
      || canonicalJson(recovery.profile) !== canonicalJson(exactProfile)
      || canonicalJson(recovery.architectures) !== canonicalJson(ARCHITECTURES)
      || canonicalJson(recovery.artifact_names) !== canonicalJson(contract.artifact_names)
      || compareSemver(recovery.version, receipt.release.version) <= 0) {
    throw new Error(
      `[candidate] exact Realtor Beta ${REALTOR_BETA_RECOVERY_VERSION} recovery package contract is missing or invalid`,
    );
  }
  if (recovery.local_feed?.path !== contract.local_feed_path) {
    throw new Error("[candidate] recovery local feed path is invalid");
  }
  const artifactKeys = Object.keys(recovery.artifacts || {}).sort();
  if (canonicalJson(artifactKeys) !== canonicalJson(contract.artifact_names.slice().sort())) {
    throw new Error("[candidate] recovery artifact set is incomplete or forged");
  }
  const recoveryHashes = new Set();
  const candidateHashes = new Set(Object.values(receipt.artifacts || {}).map((record) => record?.sha256).filter(Boolean));
  for (const name of contract.artifact_names) {
    const record = recovery.artifacts[name];
    const architecture = name.includes("-arm64.") ? "arm64" : "x64";
    const format = path.extname(name).slice(1);
    const expectedPath = path.join("desktop", "dist", "recovery", name);
    if (record.path !== expectedPath || record.architecture !== architecture || record.format !== format
        || recoveryHashes.has(record.sha256) || candidateHashes.has(record.sha256)) {
      throw new Error(`[candidate] recovery artifact is missing, forged, or reused: ${name}`);
    }
    recoveryHashes.add(record.sha256);
    if (canonicalJson(record.packaged_app) !== canonicalJson({
      bundle_manifest_sha256: recovery.apps?.[architecture]?.bundle_manifest?.sha256,
      ...recovery.apps?.[architecture]?.trust,
    })) {
      throw new Error(`[candidate] recovery artifact app provenance mismatch: ${name}`);
    }
    const expectedContainerTrust = format === "dmg" ? recovery.signing?.dmgs?.[architecture]?.trust : null;
    if (canonicalJson(record.container_trust) !== canonicalJson(expectedContainerTrust)) {
      throw new Error(`[candidate] recovery artifact container provenance mismatch: ${name}`);
    }
    if (requireFiles) assertFileRecord(path.join(repoRoot, record.path), record, `recovery ${name}`);
  }
  validateFeed(recovery.local_feed.manifest, {
    version: recovery.version,
    artifact_names: recovery.artifact_names,
  }, recovery.artifacts);
  if (requireFiles) {
    const feedPath = path.join(repoRoot, recovery.local_feed.path);
    assertFileRecord(feedPath, recovery.local_feed, "recovery beta-mac.yml");
    const actualManifest = yaml.load(fs.readFileSync(feedPath, "utf8")) || {};
    if (canonicalJson(actualManifest) !== canonicalJson(recovery.local_feed.manifest)) {
      throw new Error("[candidate] recovery feed manifest does not match its finalized bytes");
    }
  }
  for (const arch of ARCHITECTURES) {
    validateRecoveryAppReceipt(recovery.apps?.[arch], arch, contract, recovery.source_receipt_id);
    const preSign = validateRecoveryPreSignEvidence(recovery.pre_sign_contracts?.[arch], {
      architecture: arch,
      sourceReceiptId: recovery.source_receipt_id,
      app: recovery.apps[arch],
      contract,
    });
    if (requireFiles) {
      const preSignPath = path.join(repoRoot, contract.pre_sign_paths[arch]);
      if (canonicalJson(readJson(preSignPath)) !== canonicalJson(preSign)) {
        throw new Error(`[candidate] ${arch} recovery pre-sign evidence changed after finalization`);
      }
    }
    const mainManifest = receipt.apps?.[arch]?.bundle_manifest?.sha256;
    if (mainManifest && recovery.apps[arch].bundle_manifest.sha256 === mainManifest) {
      throw new Error(`[candidate] ${arch} recovery app reuses the full candidate app payload`);
    }
    const dmg = recovery.signing?.dmgs?.[arch];
    const expectedDmg = contract.artifact_names.find((name) => name.endsWith(`-mac-${arch}.dmg`));
    if (dmg?.artifact !== expectedDmg) throw new Error(`[candidate] ${arch} recovery DMG provenance is missing`);
    assertStoredSigningEvidence(dmg.evidence, `${arch} recovery DMG`);
    if (canonicalJson(dmg.trust) !== canonicalJson(signingTrustRecord(dmg.evidence))) {
      throw new Error(`[candidate] ${arch} recovery DMG trust provenance mismatch`);
    }
  }
  if (canonicalJson(recovery.static_provenance) !== canonicalJson(recoveryStaticProvenance(recovery))) {
    throw new Error("[candidate] recovery static provenance mismatch");
  }
  if (requireApps) {
    const actualApps = Object.fromEntries(ARCHITECTURES.map((arch) => [arch, recoveryAppRecord({
      appPath: path.join(repoRoot, contract.app_paths[arch]),
      architecture: arch,
      sourceReceiptId: receipt.source_receipt_id,
      relativeTo: repoRoot,
      desktopSrcRoot: path.join(desktopRoot, "src"),
    })]));
    const stableFields = [
      "architecture", "app_path", "bundle_manifest", "embedded_recovery_sources",
      "info_plist", "app_update", "packaged_metadata", "executable_architectures",
    ];
    for (const arch of ARCHITECTURES) {
      for (const field of stableFields) {
        if (canonicalJson(actualApps[arch][field]) !== canonicalJson(recovery.apps[arch][field])) {
          throw new Error(`[candidate] ${arch} recovery app changed after finalization: ${field}`);
        }
      }
    }
    const actualPayloads = verifyArtifactPayloads({
      release: {
        version: recovery.version,
        profile: recovery.profile,
        artifact_names: recovery.artifact_names,
      },
      apps: actualApps,
      desktopRoot,
      artifactRoot: path.join(desktopRoot, "dist", "recovery"),
    });
    if (canonicalJson(actualPayloads) !== canonicalJson(recovery.artifact_payloads)) {
      throw new Error("[candidate] recovery artifact payload provenance changed after finalization");
    }
  }
  return recovery;
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'\\''`)}'`;
}

function realtorBetaRetainedRecoveryFeedName(version, feedName = "beta-mac.yml") {
  return `.realtor-beta-recovery-${version}-${feedName}`;
}

function remotePublishPlan({
  candidate,
  remote = "/var/www/elevate-updates/",
  stagingName,
  owner = "www-data:www-data",
} = {}) {
  const candidateId = candidate?.candidate_id;
  if (!/^[a-f0-9]{64}$/.test(candidateId || "")
      || !/^\.candidate-[a-f0-9]{64}-[A-Za-z0-9_-]+$/.test(stagingName || "")
      || stagingName === `.candidate-${candidateId}-publish-state`
      || remote === "/" || !/^\/[A-Za-z0-9._/-]+\/$/.test(remote) || remote.split("/").includes("..")
      || (owner !== null && !/^[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$/.test(owner || ""))) {
    throw new Error("[candidate] incomplete or unsafe remote staging inputs");
  }
  const channel = candidate.release?.channel;
  const feedName = candidate.release?.feed_name;
  if (!CHANNELS.has(channel) || feedName !== `${channel}-mac.yml`) {
    throw new Error("[candidate] candidate release channel/feed mismatch");
  }
  const artifactNames = candidate.release?.artifact_names || [];
  const aliases = candidate.release?.download_aliases || [];
  const stagedNames = [...artifactNames, feedName];
  if (!artifactNames.length || !aliases.length || new Set([...stagedNames, ...aliases]).size !== stagedNames.length + aliases.length) {
    throw new Error("[candidate] incomplete or duplicate release paths");
  }
  for (const name of [...stagedNames, ...aliases]) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]+$/.test(name) || path.posix.basename(name) !== name) {
      throw new Error(`[candidate] unsafe release path: ${name}`);
    }
  }
  for (const name of stagedNames) {
    if (!/^[a-f0-9]{64}$/.test(candidate.artifacts?.[name]?.sha256 || "")) {
      throw new Error(`[candidate] missing SHA256 for staged release file: ${name}`);
    }
  }
  const oldFeeds = Object.fromEntries([...CHANNELS].map((name) => {
    const value = candidate.public_feeds_at_finalize?.[name]?.sha256 || null;
    if (value !== null && !/^[a-f0-9]{64}$/.test(value)) {
      throw new Error(`[candidate] invalid finalized ${name} feed SHA256`);
    }
    return [name, value];
  }));
  const aliasPairs = aliases.map((alias, index) => {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    const source = artifactNames.find((name) => name.endsWith(`-mac-${arch}.dmg`));
    if (!source) throw new Error(`[candidate] no ${arch} DMG for alias ${alias}`);
    return { alias, source, index };
  });
  let recoveryPlan = null;
  if (candidate.recovery != null) {
    if (channel !== "beta") throw new Error("[candidate] recovery retention requires the beta channel");
    const recovery = candidate.recovery;
    const recoveryNames = recovery.artifact_names || [];
    if (!recoveryNames.length
        || !/^\d+\.\d+\.\d+$/.test(recovery.version || "")
        || !/^[a-f0-9]{64}$/.test(recovery.local_feed?.sha256 || "")) {
      throw new Error("[candidate] incomplete recovery retention contract");
    }
    for (const name of recoveryNames) {
      if (!/^[A-Za-z0-9][A-Za-z0-9._-]+$/.test(name) || path.posix.basename(name) !== name) {
        throw new Error(`[candidate] unsafe recovery release path: ${name}`);
      }
      if (!/^[a-f0-9]{64}$/.test(recovery.artifacts?.[name]?.sha256 || "")) {
        throw new Error(`[candidate] missing SHA256 for recovery release file: ${name}`);
      }
    }
    const stagedFeedName = `recovery-${feedName}`;
    const retainedFeedName = realtorBetaRetainedRecoveryFeedName(recovery.version, feedName);
    const allNames = new Set([...stagedNames, ...aliases, ...recoveryNames, stagedFeedName, retainedFeedName]);
    if (allNames.size !== stagedNames.length + aliases.length + recoveryNames.length + 2) {
      throw new Error("[candidate] recovery release paths collide with the candidate");
    }
    recoveryPlan = {
      names: recoveryNames,
      stagedFeedName,
      retainedFeedName,
      version: recovery.version,
      feedSha256: recovery.local_feed.sha256,
      artifactSha256: Object.fromEntries(recoveryNames.map((name) => [name, recovery.artifacts[name].sha256])),
    };
  }
  const journal = {
    schema_version: 1,
    kind: "elevate-remote-publish-journal",
    candidate_id: candidateId,
    channel,
    feed_name: feedName,
    feed_sha256: candidate.artifacts[feedName].sha256,
    finalized_feed_sha256: oldFeeds,
    artifact_sha256: Object.fromEntries(artifactNames.map((name) => [name, candidate.artifacts[name].sha256])),
    aliases: aliasPairs.map(({ alias, source }) => ({
      alias,
      source,
      sha256: candidate.artifacts[source].sha256,
    })),
    ...(recoveryPlan ? {
      recovery: {
        version: recoveryPlan.version,
        retained_feed_name: recoveryPlan.retainedFeedName,
        feed_sha256: recoveryPlan.feedSha256,
        artifact_sha256: recoveryPlan.artifactSha256,
      },
    } : {}),
  };
  const journalBytes = `${canonicalJson(journal)}\n`;
  const rollbackClearedFile = channel === "beta"
    ? realtorBetaRollbackClearedFile(candidate)
    : null;
  const rollbackFreezeSha256 = channel === "beta"
    ? sha256(realtorBetaRollbackFreezeBytes(candidate))
    : null;
  return {
    candidateId,
    channel,
    feedName,
    artifactNames,
    stagedNames,
    aliasPairs,
    oldFeeds,
    stage: `${remote}${stagingName}/`,
    transaction: `${remote}.candidate-${candidateId}-publish-state/`,
    rollbackFreeze: `${remote}${ROLLBACK_FREEZE_FILE}`,
    rollbackCleared: rollbackClearedFile ? `${remote}${rollbackClearedFile}` : null,
    rollbackFreezeSha256,
    recoveryPlan,
    journalBytes,
    journalSha256: sha256(journalBytes),
    owner,
    remote,
  };
}

function buildRemotePublishInnerScript({
  candidate,
  remote = "/var/www/elevate-updates/",
  stagingName,
  owner = "www-data:www-data",
  testCrashAfterPointerMoves = 0,
  testCrashSignal = "KILL",
} = {}) {
  const plan = remotePublishPlan({ candidate, remote, stagingName, owner });
  if (!Number.isInteger(testCrashAfterPointerMoves)
      || testCrashAfterPointerMoves < 0
      || testCrashAfterPointerMoves > plan.aliasPairs.length + 1
      || !new Set(["KILL", "TERM", "HUP"]).has(testCrashSignal)) {
    throw new Error("[candidate] invalid publisher crash injection");
  }
  const {
    candidateId, channel, feedName, artifactNames, stagedNames, aliasPairs,
    oldFeeds, stage, transaction, rollbackFreeze, rollbackCleared,
    rollbackFreezeSha256, recoveryPlan, journalBytes, journalSha256,
  } = plan;
  const otherChannel = channel === "latest" ? "beta" : "latest";
  const targetFeed = `${remote}${feedName}`;
  const otherFeed = `${remote}${otherChannel}-mac.yml`;
  const expected = (value) => value || "ABSENT";
  const setOwner = owner === null ? ":" : `chown ${shellQuote(owner)} -- \"$1\"`;
  const backupPath = (index) => `${transaction}backup-alias-${index}`;
  const absentPath = (index) => `${transaction}backup-alias-${index}.absent`;
  const nextPath = (index) => `${transaction}next-alias-${index}`;
  const transactionNewPrefix = `${transaction.slice(0, -1)}.new`;
  const renderManifest = [
    "render_backup_manifest() {",
    "  local base=\"$1\"",
    "  if regular_file \"$base/backup-feed\"; then printf 'feed|%s\\n' \"$(file_hash \"$base/backup-feed\")\"; elif regular_file \"$base/backup-feed.absent\"; then printf 'feed|ABSENT\\n'; else return 1; fi",
    ...aliasPairs.map(({ index }) =>
      `  if regular_file \"$base/backup-alias-${index}\"; then printf 'alias|${index}|%s\\n' \"$(file_hash \"$base/backup-alias-${index}\")\"; elif regular_file \"$base/backup-alias-${index}.absent\"; then printf 'alias|${index}|ABSENT\\n'; else return 1; fi`),
    "}",
  ];
  const oldAliasesCheck = aliasPairs.map(({ alias, index }) =>
    `{ (regular_file ${shellQuote(backupPath(index))} && same_bytes ${shellQuote(`${remote}${alias}`)} ${shellQuote(backupPath(index))}) || (regular_file ${shellQuote(absentPath(index))} && path_absent ${shellQuote(`${remote}${alias}`)}); }`).join(" && ");
  const knownAliasesCheck = aliasPairs.map(({ alias, source, index }) =>
    `{ ((regular_file ${shellQuote(backupPath(index))} && same_bytes ${shellQuote(`${remote}${alias}`)} ${shellQuote(backupPath(index))}) || (regular_file ${shellQuote(absentPath(index))} && path_absent ${shellQuote(`${remote}${alias}`)})) || hash_is ${shellQuote(`${remote}${alias}`)} ${shellQuote(candidate.artifacts[source].sha256)}; }`).join(" && ");
  const newAliasesCheck = aliasPairs.map(({ alias, source }) =>
    `hash_is ${shellQuote(`${remote}${alias}`)} ${shellQuote(candidate.artifacts[source].sha256)}`).join(" && ");
  const artifactsCommittedCheck = artifactNames.map((name) =>
    `hash_is ${shellQuote(`${remote}${name}`)} ${shellQuote(candidate.artifacts[name].sha256)}`).join(" && ");
  const artifactsKnownCheck = artifactNames.map((name) =>
    `{ path_absent ${shellQuote(`${remote}${name}`)} || hash_is ${shellQuote(`${remote}${name}`)} ${shellQuote(candidate.artifacts[name].sha256)}; }`).join(" && ");
  // Roll-forward recovery retention: every recovery byte must be committed to
  // its final public/retained name before any candidate pointer moves, so an
  // incident can activate 1.2.104 without any build-machine dependency.
  const recoveryFinalPairs = recoveryPlan
    ? [
      ...recoveryPlan.names.map((name) => ({ staged: name, final: name, hash: recoveryPlan.artifactSha256[name] })),
      { staged: recoveryPlan.stagedFeedName, final: recoveryPlan.retainedFeedName, hash: recoveryPlan.feedSha256 },
    ]
    : [];
  const recoveryCommittedCheck = recoveryFinalPairs.map(({ final, hash }) =>
    `hash_is ${shellQuote(`${remote}${final}`)} ${shellQuote(hash)}`).join(" && ");
  const recoveryKnownCheck = recoveryFinalPairs.map(({ final, hash }) =>
    `{ path_absent ${shellQuote(`${remote}${final}`)} || hash_is ${shellQuote(`${remote}${final}`)} ${shellQuote(hash)}; }`).join(" && ");
  const retainRecovery = recoveryFinalPairs.flatMap(({ staged, final, hash }) => [
    `if hash_is ${shellQuote(`${remote}${final}`)} ${shellQuote(hash)}; then rm -f -- ${shellQuote(`${stage}${staged}`)}; elif path_absent ${shellQuote(`${remote}${final}`)}; then mv -- ${shellQuote(`${stage}${staged}`)} ${shellQuote(`${remote}${final}`)}; else echo ${shellQuote(`RECOVERY_FINAL_COLLISION ${final}`)} >&2; exit 44; fi`,
    `set_file_owner ${shellQuote(`${remote}${final}`)}`,
    `chmod 0644 ${shellQuote(`${remote}${final}`)}`,
    `durable_sync ${shellQuote(`${remote}${final}`)}`,
  ]);
  const backupAliases = aliasPairs.flatMap(({ alias, index }) => [
    `if regular_file ${shellQuote(`${remote}${alias}`)}; then cp -- ${shellQuote(`${remote}${alias}`)} \"$transaction_new/${path.basename(backupPath(index))}\"; durable_sync \"$transaction_new/${path.basename(backupPath(index))}\"; elif path_absent ${shellQuote(`${remote}${alias}`)}; then : > \"$transaction_new/${path.basename(absentPath(index))}\"; durable_sync \"$transaction_new/${path.basename(absentPath(index))}\"; else echo ${shellQuote(`PUBLISH_ALIAS_BASELINE_UNSAFE ${alias}`)} >&2; exit 47; fi`,
  ]);
  const publishArtifacts = artifactNames.flatMap((name) => [
    `if hash_is ${shellQuote(`${remote}${name}`)} ${shellQuote(candidate.artifacts[name].sha256)}; then rm -f -- ${shellQuote(`${stage}${name}`)}; elif path_absent ${shellQuote(`${remote}${name}`)}; then mv -- ${shellQuote(`${stage}${name}`)} ${shellQuote(`${remote}${name}`)}; else echo ${shellQuote(`FINAL_COLLISION ${name}`)} >&2; exit 44; fi`,
    `set_file_owner ${shellQuote(`${remote}${name}`)}`,
    `chmod 0644 ${shellQuote(`${remote}${name}`)}`,
    `durable_sync ${shellQuote(`${remote}${name}`)}`,
  ]);
  const prepareAliases = aliasPairs.flatMap(({ source, index }) => [
    `cp -- ${shellQuote(`${remote}${source}`)} ${shellQuote(nextPath(index))}`,
    `hash_is ${shellQuote(nextPath(index))} ${shellQuote(candidate.artifacts[source].sha256)} || { echo ${shellQuote(`ALIAS_HASH_FAILED ${index}`)} >&2; exit 45; }`,
    `set_file_owner ${shellQuote(nextPath(index))}`,
    `chmod 0644 ${shellQuote(nextPath(index))}`,
    `durable_sync ${shellQuote(nextPath(index))}`,
  ]);
  const publishAliases = aliasPairs.map(({ alias, index }) =>
    `atomic_replace ${shellQuote(nextPath(index))} ${shellQuote(`${remote}${alias}`)}`);
  const restoreAliases = aliasPairs.map(({ alias, index }) =>
    `restore_pointer ${shellQuote(backupPath(index))} ${shellQuote(absentPath(index))} ${shellQuote(`${remote}${alias}`)}`);
  const script = [
    "set -euo pipefail",
    "umask 077",
    "durable_sync() { sync -f \"$1\" 2>/dev/null || sync; }",
    "regular_file() { test -f \"$1\" && ! test -L \"$1\"; }",
    "path_absent() { ! test -e \"$1\" && ! test -L \"$1\"; }",
    "file_hash() { sha256sum -- \"$1\" | awk '{print $1}'; }",
    "hash_is() { regular_file \"$1\" && test \"$(file_hash \"$1\")\" = \"$2\"; }",
    "same_bytes() { regular_file \"$1\" && regular_file \"$2\" && cmp -s -- \"$1\" \"$2\"; }",
    "matches_expected() { if test \"$2\" = ABSENT; then path_absent \"$1\"; else hash_is \"$1\" \"$2\"; fi; }",
    `set_file_owner() { ${setOwner}; }`,
    `pointer_moves=0`,
    `crash_after=${testCrashAfterPointerMoves}`,
    `crash_signal=${shellQuote(testCrashSignal)}`,
    "after_pointer_move() { pointer_moves=$((pointer_moves + 1)); if test \"$crash_after\" -gt 0 && test \"$pointer_moves\" -eq \"$crash_after\"; then kill \"-$crash_signal\" \"$$\"; fi; }",
    "atomic_replace() { local source=\"$1\" destination=\"$2\" temp=\"$2.publish-tmp\"; rm -f -- \"$temp\"; cp -- \"$source\" \"$temp\"; set_file_owner \"$temp\"; chmod 0644 \"$temp\"; durable_sync \"$temp\"; mv -f -- \"$temp\" \"$destination\"; durable_sync \"$destination\"; durable_sync " + shellQuote(remote) + "; after_pointer_move; }",
    "restore_pointer() { local backup=\"$1\" absent=\"$2\" destination=\"$3\" temp=\"$3.restore-tmp\"; if regular_file \"$backup\"; then rm -f -- \"$temp\"; cp -- \"$backup\" \"$temp\"; set_file_owner \"$temp\"; chmod 0644 \"$temp\"; durable_sync \"$temp\"; mv -f -- \"$temp\" \"$destination\"; durable_sync \"$destination\"; elif regular_file \"$absent\"; then rm -f -- \"$destination\"; else return 1; fi; durable_sync " + shellQuote(remote) + "; }",
    ...renderManifest,
    "trusted_transaction() {",
    `  test -d ${shellQuote(transaction)} && ! test -L ${shellQuote(transaction)} || return 1`,
    `  hash_is ${shellQuote(`${transaction}journal.json`)} ${shellQuote(journalSha256)} || return 1`,
    `  regular_file ${shellQuote(`${transaction}backups.manifest`)} && regular_file ${shellQuote(`${transaction}ready`)} || return 1`,
    `  test "$(render_backup_manifest ${shellQuote(transaction.slice(0, -1))})" = "$(cat ${shellQuote(`${transaction}backups.manifest`)})" || return 1`,
    `  test "$( { cat ${shellQuote(`${transaction}journal.json`)}; cat ${shellQuote(`${transaction}backups.manifest`)}; } | sha256sum | awk '{print $1}')" = "$(cat ${shellQuote(`${transaction}ready`)})" || return 1`,
    `  matches_expected ${shellQuote(`${transaction}backup-feed`)} ${shellQuote(expected(oldFeeds[channel]))} || { test ${shellQuote(expected(oldFeeds[channel]))} = ABSENT && regular_file ${shellQuote(`${transaction}backup-feed.absent`)}; }`,
    "}",
    `old_feeds_ok() { matches_expected ${shellQuote(targetFeed)} ${shellQuote(expected(oldFeeds[channel]))} && matches_expected ${shellQuote(otherFeed)} ${shellQuote(expected(oldFeeds[otherChannel]))}; }`,
    `other_feed_ok() { matches_expected ${shellQuote(otherFeed)} ${shellQuote(expected(oldFeeds[otherChannel]))}; }`,
    `old_aliases_ok() { ${oldAliasesCheck || ":"}; }`,
    `known_aliases_ok() { ${knownAliasesCheck || ":"}; }`,
    `new_aliases_ok() { ${newAliasesCheck || ":"}; }`,
    `artifacts_committed_ok() { ${artifactsCommittedCheck || ":"}; }`,
    `artifacts_known_ok() { ${artifactsKnownCheck || ":"}; }`,
    `recovery_committed_ok() { ${recoveryCommittedCheck || ":"}; }`,
    `recovery_known_ok() { ${recoveryKnownCheck || ":"}; }`,
    `committed_ok() { hash_is ${shellQuote(targetFeed)} ${shellQuote(candidate.artifacts[feedName].sha256)} && other_feed_ok && new_aliases_ok && artifacts_committed_ok && recovery_committed_ok; }`,
    "known_pointer_state_ok() { other_feed_ok && { matches_expected " + shellQuote(targetFeed) + " " + shellQuote(expected(oldFeeds[channel])) + " || hash_is " + shellQuote(targetFeed) + " " + shellQuote(candidate.artifacts[feedName].sha256) + "; } && known_aliases_ok && artifacts_known_ok; }",
    "restore_old_state() {",
    ...restoreAliases.map((line) => `  ${line}`),
    `  restore_pointer ${shellQuote(`${transaction}backup-feed`)} ${shellQuote(`${transaction}backup-feed.absent`)} ${shellQuote(targetFeed)}`,
    "  old_feeds_ok && old_aliases_ok",
    "}",
    "retire_transaction() { if test -e " + shellQuote(transaction) + " || test -L " + shellQuote(transaction) + "; then test -d " + shellQuote(transaction) + " && ! test -L " + shellQuote(transaction) + " || return 1; local retired=" + shellQuote(`${transaction.slice(0, -1)}.retired`) + ".$$; path_absent \"$retired\" || return 1; mv -- " + shellQuote(transaction.slice(0, -1)) + " \"$retired\"; durable_sync " + shellQuote(remote) + "; rm -rf -- \"$retired\"; durable_sync " + shellQuote(remote) + "; fi; }",
    "mutation_started=0",
    "committed=0",
    "transaction_new=''",
    "cleanup() { local status=\"${1:-$?}\" restore_status=0; trap - EXIT HUP INT TERM; if test \"$status\" -ne 0 && test \"$mutation_started\" -eq 1 && test \"$committed\" -eq 0; then set +e; restore_old_state; restore_status=$?; set -e; if test \"$restore_status\" -ne 0; then echo PUBLISH_COMPENSATION_FAILED >&2; fi; fi; rm -rf -- " + shellQuote(stage) + "; if test -n \"$transaction_new\" && test -d \"$transaction_new\" && ! test -L \"$transaction_new\"; then rm -rf -- \"$transaction_new\"; durable_sync " + shellQuote(remote) + "; fi; if test \"$restore_status\" -ne 0; then exit 70; fi; exit \"$status\"; }",
    "trap cleanup EXIT",
    "trap 'cleanup 129' HUP",
    "trap 'cleanup 130' INT",
    "trap 'cleanup 143' TERM",
    `test -d ${shellQuote(stage)} && ! test -L ${shellQuote(stage)} || { echo PUBLISH_UPLOAD_STAGE_UNSAFE >&2; exit 41; }`,
    `if test -e ${shellQuote(rollbackFreeze)} || test -L ${shellQuote(rollbackFreeze)}; then echo RELEASE_FREEZE_ACTIVE >&2; exit 46; fi`,
    ...(rollbackCleared ? [
      `if test -e ${shellQuote(rollbackCleared)} || test -L ${shellQuote(rollbackCleared)}; then hash_is ${shellQuote(rollbackCleared)} ${shellQuote(rollbackFreezeSha256)} || { echo RELEASE_ROLLBACK_TOMBSTONE_CONFLICT >&2; exit 47; }; echo RELEASE_CANDIDATE_ALREADY_ROLLED_BACK >&2; exit 47; fi`,
    ] : []),
    ...stagedNames.map((name) =>
      `hash_is ${shellQuote(`${stage}${name}`)} ${shellQuote(candidate.artifacts[name].sha256)} || { echo ${shellQuote(`STAGED_HASH_FAILED ${name}`)} >&2; exit 43; }`),
    ...stagedNames.map((name) => `durable_sync ${shellQuote(`${stage}${name}`)}`),
    ...recoveryFinalPairs.map(({ staged, hash }) =>
      `hash_is ${shellQuote(`${stage}${staged}`)} ${shellQuote(hash)} || { echo ${shellQuote(`STAGED_HASH_FAILED ${staged}`)} >&2; exit 43; }`),
    ...recoveryFinalPairs.map(({ staged }) => `durable_sync ${shellQuote(`${stage}${staged}`)}`),
    `if committed_ok; then retire_transaction; ${channel === "latest" ? `find ${shellQuote(remote)} -maxdepth 1 -type f -name '*.zip.blockmap' -delete; durable_sync ${shellQuote(remote)};` : ""} echo 'REMOTE_PUBLISH_OK state=already_committed'; exit 0; fi`,
    `transaction_preexisted=0`,
    `if test -e ${shellQuote(transaction)} || test -L ${shellQuote(transaction)}; then transaction_preexisted=1; trusted_transaction || { echo PUBLISH_JOURNAL_UNTRUSTED >&2; exit 48; }; else`,
    "  old_feeds_ok || { echo PUBLISH_STATE_NOT_OLD >&2; exit 42; }",
    `  transaction_new=${shellQuote(transactionNewPrefix)}.$$`,
    "  path_absent \"$transaction_new\" || { echo PUBLISH_TEMP_COLLISION >&2; exit 48; }",
    "  mkdir -m 0700 -- \"$transaction_new\"",
    `  if test ${shellQuote(expected(oldFeeds[channel]))} = ABSENT; then : > \"$transaction_new/backup-feed.absent\"; durable_sync \"$transaction_new/backup-feed.absent\"; else cp -- ${shellQuote(targetFeed)} \"$transaction_new/backup-feed\"; hash_is \"$transaction_new/backup-feed\" ${shellQuote(expected(oldFeeds[channel]))} || exit 42; durable_sync \"$transaction_new/backup-feed\"; fi`,
    ...backupAliases.map((line) => `  ${line}`),
    `  printf '%s' ${shellQuote(journalBytes)} > \"$transaction_new/journal.json\"`,
    `  hash_is \"$transaction_new/journal.json\" ${shellQuote(journalSha256)} || exit 48`,
    "  durable_sync \"$transaction_new/journal.json\"",
    `  transaction=${shellQuote(transaction)}`,
    "  render_backup_manifest \"$transaction_new\" > \"$transaction_new/backups.manifest\"",
    "  durable_sync \"$transaction_new/backups.manifest\"",
    "  { cat \"$transaction_new/journal.json\"; cat \"$transaction_new/backups.manifest\"; } | sha256sum | awk '{print $1}' > \"$transaction_new/ready\"",
    "  durable_sync \"$transaction_new/ready\"",
    "  durable_sync \"$transaction_new\"",
    `  mv -- \"$transaction_new\" ${shellQuote(transaction.slice(0, -1))}`,
    `  durable_sync ${shellQuote(remote)}`,
    "  trusted_transaction || { echo PUBLISH_JOURNAL_COMMIT_FAILED >&2; exit 48; }",
    "fi",
    "known_pointer_state_ok || { echo PUBLISH_STATE_UNKNOWN >&2; exit 49; }",
    ...(recoveryPlan ? ["recovery_known_ok || { echo PUBLISH_RECOVERY_STATE_UNKNOWN >&2; exit 51; }"] : []),
    ...retainRecovery,
    ...(recoveryPlan ? [`durable_sync ${shellQuote(remote)}`] : []),
    ...publishArtifacts,
    `durable_sync ${shellQuote(remote)}`,
    ...prepareAliases,
    `cp -- ${shellQuote(`${stage}${feedName}`)} ${shellQuote(`${transaction}next-feed`)}`,
    `hash_is ${shellQuote(`${transaction}next-feed`)} ${shellQuote(candidate.artifacts[feedName].sha256)} || { echo FEED_HASH_FAILED >&2; exit 45; }`,
    `set_file_owner ${shellQuote(`${transaction}next-feed`)}`,
    `chmod 0644 ${shellQuote(`${transaction}next-feed`)}`,
    `durable_sync ${shellQuote(`${transaction}next-feed`)}`,
    `durable_sync ${shellQuote(transaction)}`,
    "mutation_started=1",
    ...publishAliases,
    `atomic_replace ${shellQuote(`${transaction}next-feed`)} ${shellQuote(targetFeed)}`,
    `durable_sync ${shellQuote(remote)}`,
    "committed_ok || { echo PUBLISH_COMMIT_VALIDATION_FAILED >&2; exit 50; }",
    "committed=1",
    ...(channel === "latest"
      ? [`find ${shellQuote(remote)} -maxdepth 1 -type f -name '*.zip.blockmap' -delete`, `durable_sync ${shellQuote(remote)}`]
      : []),
    "retire_transaction",
    "if test \"$transaction_preexisted\" -eq 1; then echo 'REMOTE_PUBLISH_OK state=recovered_committed'; else echo 'REMOTE_PUBLISH_OK state=committed'; fi",
  ].join("\n");
  return script;
}

function buildRemotePublishTransaction({
  candidate,
  remote = "/var/www/elevate-updates/",
  stagingName,
  owner = "www-data:www-data",
  globalLock = "/var/lock/elevate-release-publish.lock",
} = {}) {
  if (!/^\/[A-Za-z0-9._/-]+$/.test(globalLock || "") || globalLock.split("/").includes("..")) {
    throw new Error("[candidate] unsafe global publication lock path");
  }
  const script = buildRemotePublishInnerScript({ candidate, remote, stagingName, owner });
  // Publisher, rollback, and pruning all serialize through this bounded lock.
  return `flock -x -w 300 ${shellQuote(globalLock)} bash -c ${shellQuote(script)}`;
}

function createFinalReceipt({
  sourceReceiptPath = SOURCE_RECEIPT,
  webBuildReceiptPath = WEB_BUILD_RECEIPT,
  outputPath = CANDIDATE_RECEIPT,
  desktopRoot = DESKTOP,
  repoRoot = REPO,
  publicFeeds,
  dmgEvidence,
  preSignEvidenceDirectory,
  createdAt = new Date().toISOString(),
} = {}) {
  const source = verifySourceReceipt({ receiptPath: sourceReceiptPath, repoRoot });
  const release = source.release;
  const webBuild = verifyWebBuildReceipt({
    receiptPath: webBuildReceiptPath,
    sourceReceiptId: source.source_receipt_id,
    repoRoot,
  });
  assertGloballyNewVersion(release.version, publicFeeds);
  assertPublicFeedsUnchanged(source.public_feeds, publicFeeds, "candidate build; run a fresh preflight");
  const stableUntouched = release.channel !== "beta"
    || source.public_feeds?.latest?.sha256 === publicFeeds?.latest?.sha256;
  const preSignRoot = preSignEvidenceDirectory || path.join(desktopRoot, "dist");
  const preSignContracts = Object.fromEntries(ARCHITECTURES.map((arch) => [arch, verifyPreSignEvidence({
    evidencePath: preSignEvidencePath(preSignRoot, arch),
    architecture: arch,
    source,
    webBuild,
    appBundleName: release.profile.appBundleName,
  })]));

  const apps = {
    x64: appRecord(path.join(desktopRoot, "dist", "mac", release.profile.appBundleName), "x64", release, desktopRoot, source.source_receipt_id, source.inputs["desktop/src"].portable.sha256),
    arm64: appRecord(path.join(desktopRoot, "dist", "mac-arm64", release.profile.appBundleName), "arm64", release, desktopRoot, source.source_receipt_id, source.inputs["desktop/src"].portable.sha256),
  };
  if (apps.x64.embedded_cli.sha256 !== apps.arm64.embedded_cli.sha256) throw new Error("[candidate] embedded CLI differs across architectures");
  if (apps.x64.embedded_web.sha256 !== apps.arm64.embedded_web.sha256) throw new Error("[candidate] embedded web bundle differs across architectures");
  if (apps.x64.embedded_whatsapp.sha256 !== apps.arm64.embedded_whatsapp.sha256) throw new Error("[candidate] embedded WhatsApp bridge differs across architectures");
  if (canonicalJson(apps.x64.app_update) !== canonicalJson(apps.arm64.app_update)) throw new Error("[candidate] updater identity differs across architectures");
  assertEmbeddedWebMatchesBuild(apps, webBuild);
  for (const arch of ARCHITECTURES) {
    if (apps[arch].embedded_cli.sha256 !== source.inputs["cli/package-input"].sha256) {
      throw new Error(`[candidate] ${arch} embedded CLI does not match the source contract`);
    }
    if (apps[arch].embedded_whatsapp.sha256 !== source.inputs["cli/whatsapp-bridge"].sha256) {
      throw new Error(`[candidate] ${arch} embedded WhatsApp bridge does not match the source contract`);
    }
    assertRuntimeCodeContract(
      apps[arch].embedded_runtime.code_normalized,
      source.inputs[`runtime/${arch}`].code_normalized,
      `${arch} signed runtime code`,
    );
  }

  const artifacts = Object.fromEntries(release.artifact_names.map((name) => {
    const filePath = path.join(desktopRoot, "dist", name);
    return [name, fileRecord(filePath, desktopRoot, { includeSha512: true })];
  }));
  const feedName = release.feed_name;
  artifacts[feedName] = fileRecord(path.join(desktopRoot, "dist", feedName), desktopRoot);
  const feed = yaml.load(fs.readFileSync(path.join(desktopRoot, "dist", feedName), "utf8")) || {};
  validateFeed(feed, release, artifacts);
  const artifactPayloads = verifyArtifactPayloads({ release, apps, desktopRoot });

  const appSigning = {
    x64: collectAppSigningEvidence(path.join(desktopRoot, "dist", "mac", release.profile.appBundleName)),
    arm64: collectAppSigningEvidence(path.join(desktopRoot, "dist", "mac-arm64", release.profile.appBundleName)),
  };
  const recovery = createRecoveryReceipt({ source, release, desktopRoot, repoRoot });
  const receipt = {
    schema_version: CANDIDATE_RECEIPT_SCHEMA_VERSION,
    kind: "elevate-final-candidate",
    created_at: createdAt,
    source_receipt_id: source.source_receipt_id,
    source,
    web_build: webBuild,
    pre_sign_contracts: preSignContracts,
    release,
    apps,
    artifacts,
    artifact_payloads: artifactPayloads,
    signing: { apps: appSigning, dmgs: dmgEvidence },
    ...(recovery ? { recovery } : {}),
    public_feeds_at_finalize: publicFeeds,
    rollback_target: publicFeeds[release.channel] || null,
    production_feed_untouched: stableUntouched,
    smoke_entrypoint: fileRecord(path.join(repoRoot, "cli", "scripts", "installed_runtime_smoke.py"), repoRoot),
    realtor_beta_gate_entrypoint: release.channel === "beta"
      ? fileRecord(path.join(repoRoot, "cli", "scripts", "exact_candidate_realtor_beta_gate.py"), repoRoot)
      : null,
    realtor_beta_rollback_runbook: release.channel === "beta"
      ? fileRecord(path.join(repoRoot, "cli", "docs", "realtor-beta-rollback-runbook.md"), repoRoot)
      : null,
    required_evidence: {
      x64_smoke: "desktop/dist/evidence/smoke-x64.json",
      arm64_smoke: "desktop/dist/evidence/smoke-arm64.json",
      live_ai: "desktop/dist/evidence/live-ai.json",
      ...(release.channel === "beta"
        ? { realtor_beta_gate: "desktop/dist/evidence/realtor-beta-gate.json" }
        : {}),
    },
  };
  return writeImmutableReceipt(outputPath, receipt, "candidate_id");
}

function verifyCandidateReceipt({
  receiptPath = CANDIDATE_RECEIPT,
  desktopRoot = DESKTOP,
  repoRoot = REPO,
  requireApps = true,
  requireEvidence = false,
  requireSource = true,
  evidenceHome = os.homedir(),
  hostArchitecture = process.arch,
} = {}) {
  if (!fs.existsSync(receiptPath)) throw new Error(`[candidate] missing final receipt: ${receiptPath}`);
  const receipt = readJson(receiptPath);
  if (
    receipt.schema_version !== CANDIDATE_RECEIPT_SCHEMA_VERSION ||
    receipt.kind !== "elevate-final-candidate"
  ) {
    throw new Error("[candidate] unsupported final candidate receipt schema");
  }
  if (receiptId(receipt, "candidate_id") !== receipt.candidate_id) throw new Error("[candidate] candidate receipt ID mismatch");
  if (requireSource) {
    const source = verifySourceReceipt({
      receiptPath: path.resolve(path.dirname(receiptPath), "candidate-source.json"),
      repoRoot,
      channel: receipt.release.channel,
      version: receipt.release.version,
    });
    if (source.source_receipt_id !== receipt.source_receipt_id) throw new Error("[candidate] source receipt changed after finalization");
    const webBuild = verifyWebBuildReceipt({
      receiptPath: path.resolve(path.dirname(receiptPath), "candidate-web.json"),
      sourceReceiptId: receipt.source_receipt_id,
      repoRoot,
    });
    if (webBuild.web_build_id !== receipt.web_build?.web_build_id) {
      throw new Error("[candidate] web build receipt changed after finalization");
    }
    assertFileRecord(
      path.join(repoRoot, receipt.smoke_entrypoint?.path || ""),
      receipt.smoke_entrypoint,
      "installed runtime smoke entrypoint",
    );
    if (receipt.release.channel === "beta") {
      assertFileRecord(
        path.join(repoRoot, receipt.realtor_beta_gate_entrypoint?.path || ""),
        receipt.realtor_beta_gate_entrypoint,
        "Realtor Beta gate entrypoint",
      );
      assertFileRecord(
        path.join(repoRoot, receipt.realtor_beta_rollback_runbook?.path || ""),
        receipt.realtor_beta_rollback_runbook,
        "Realtor Beta rollback runbook",
      );
    }
    for (const arch of ARCHITECTURES) {
      validatePreSignEvidence(receipt.pre_sign_contracts?.[arch], {
        architecture: arch,
        source: receipt.source,
        webBuild: receipt.web_build,
        appBundleName: receipt.release.profile.appBundleName,
      });
    }
  }
  for (const [name, record] of Object.entries(receipt.artifacts || {})) {
    assertFileRecord(path.join(desktopRoot, record.path), record, name);
  }
  validateRecoveryReceipt(receipt, { desktopRoot, repoRoot, requireFiles: true, requireApps });
  if (requireApps) {
    for (const arch of ARCHITECTURES) {
      const expected = receipt.apps[arch];
      const appPath = path.join(desktopRoot, expected.app_path);
      const actual = appRecord(
        appPath,
        arch,
        receipt.release,
        desktopRoot,
        receipt.source_receipt_id,
        receipt.source.inputs["desktop/src"].portable.sha256,
      );
      if (actual.bundle_manifest.sha256 !== expected.bundle_manifest.sha256) throw new Error(`[candidate] ${arch} app bundle changed after finalization`);
      for (const field of ["embedded_cli", "embedded_web", "embedded_whatsapp", "embedded_runtime"]) {
        if (actual[field].sha256 !== expected[field].sha256) throw new Error(`[candidate] ${arch} ${field} changed after finalization`);
      }
      assertRuntimeCodeContract(
        actual.embedded_runtime.code_normalized,
        receipt.source.inputs[`runtime/${arch}`].code_normalized,
        `${arch} signed runtime code`,
      );
      assertEmbeddedWebMatchesBuild({ [arch]: actual, [arch === "x64" ? "arm64" : "x64"]: receipt.apps[arch === "x64" ? "arm64" : "x64"] }, receipt.web_build);
    }
  }
  if (requireEvidence) {
    const requiredKeys = requireEvidence === "static"
      ? ["x64_smoke", "arm64_smoke"]
      : [
        "x64_smoke",
        "arm64_smoke",
        "live_ai",
        ...(receipt.release.channel === "beta" ? ["realtor_beta_gate"] : []),
      ];
    for (const key of requiredKeys) {
      const relative = receipt.required_evidence?.[key];
      if (!relative) throw new Error(`[candidate] final receipt is missing required evidence pointer: ${key}`);
      const evidencePath = path.join(repoRoot, relative);
      if (!fs.existsSync(evidencePath)) throw new Error(`[candidate] missing required evidence: ${key}`);
      const evidence = readJson(evidencePath);
      if (key === "realtor_beta_gate") {
        validateRealtorBetaGateEvidence(
          evidence,
          receipt,
          normalizeArchitecture(hostArchitecture),
          receiptPath,
          key,
        );
        continue;
      }
      const live = key === "live_ai";
      const expectedArch = live ? normalizeArchitecture(hostArchitecture) : (key.startsWith("x64") ? "x64" : "arm64");
      validateSmokeEvidence(evidence, receipt, expectedArch, receiptPath, key, {
        live,
        home: evidenceHome,
      });
    }
  }
  return receipt;
}

function verifyAppAgainstReceipt({ receiptPath, appPath, architecture }) {
  const receipt = readJson(receiptPath);
  if (receiptId(receipt, "candidate_id") !== receipt.candidate_id) throw new Error("[candidate] candidate receipt ID mismatch");
  if (!ARCHITECTURES.includes(architecture)) throw new Error(`[candidate] unsupported architecture: ${architecture}`);
  const actual = appRecord(
    appPath,
    architecture,
    receipt.release,
    path.dirname(path.dirname(appPath)),
    receipt.source_receipt_id,
    receipt.source.inputs["desktop/src"].portable.sha256,
  );
  const expected = receipt.apps[architecture];
  for (const field of ["bundle_manifest", "embedded_cli", "embedded_web", "embedded_whatsapp", "embedded_runtime"]) {
    if (actual[field].sha256 !== expected[field].sha256) throw new Error(`[candidate] ${architecture} ${field} mismatch`);
  }
  assertRuntimeCodeContract(
    actual.embedded_runtime.code_normalized,
    receipt.source.inputs[`runtime/${architecture}`].code_normalized,
    `${architecture} signed runtime code`,
  );
  if (actual.embedded_web.sha256 !== receipt.web_build.generated_web.manifest.sha256
      || actual.embedded_web.portable.sha256 !== receipt.web_build.generated_web.portable.sha256) {
    throw new Error(`[candidate] ${architecture} embedded web build receipt mismatch`);
  }
  return {
    candidate_id: receipt.candidate_id,
    source_receipt_id: receipt.source_receipt_id,
    candidate_architecture: architecture,
    receipt_sha256: sha256File(receiptPath),
    app_version: receipt.release.version,
    app_bundle_manifest_sha256: receipt.apps[architecture].bundle_manifest.sha256,
  };
}

function evidenceIntegrity(evidence) {
  const body = { ...evidence };
  delete body.evidence_integrity_sha256;
  return sha256(canonicalJson(body));
}

function normalizeArchitecture(value) {
  if (value === 1 || value === "1") return "x64";
  if (value === 3 || value === "3") return "arm64";
  const architecture = String(value || "").toLowerCase();
  if (architecture === "aarch64") return "arm64";
  if (architecture === "x86_64" || architecture === "amd64") return "x64";
  return architecture;
}

function validateSmokeEvidence(
  evidence,
  receipt,
  architecture,
  receiptPath,
  label = architecture,
  { live = false, home = os.homedir() } = {},
) {
  if (!ARCHITECTURES.includes(architecture) || !receipt.apps?.[architecture]) {
    throw new Error(`[candidate] invalid required smoke evidence: ${label}`);
  }
  if (evidence.evidence_schema_version !== SMOKE_EVIDENCE_SCHEMA_VERSION
      || evidence.ok !== true
      || !Array.isArray(evidence.failures) || evidence.failures.length !== 0
      || !Array.isArray(evidence.log_hits) || evidence.log_hits.length !== 0
      || evidence.candidate_id !== receipt.candidate_id
      || evidence.source_receipt_id !== receipt.source_receipt_id
      || evidence.candidate_architecture !== architecture
      || evidence.candidate_receipt_sha256 !== sha256File(receiptPath)
      || evidence.candidate_app_version !== receipt.release.version
      || evidence.candidate_app_bundle_manifest_sha256 !== receipt.apps[architecture].bundle_manifest.sha256) {
    throw new Error(`[candidate] invalid required smoke evidence: ${label}`);
  }
  const requiredCheckIds = live ? REQUIRED_LIVE_AI_CHECK_IDS : REQUIRED_SMOKE_CHECK_IDS;
  if (!Array.isArray(evidence.check_ids)
      || requiredCheckIds.some((check) => !evidence.check_ids.includes(check))) {
    throw new Error(`[candidate] smoke evidence is missing required checks: ${label}`);
  }
  if (evidence.test_profile?.name !== (live ? "release-candidate-live-v1" : "release-candidate-static-v1")
      || evidence.test_profile.skip_seal !== false
      || evidence.test_profile.skip_parity !== false
      || evidence.test_profile.skip_sidecar !== !live
      || evidence.test_profile.telegram_fixture !== false
      || evidence.test_profile.telegram_hygiene_soak !== false
      || evidence.test_profile.desktop_compacted_followup !== false) {
    throw new Error(`[candidate] smoke evidence used the wrong test profile: ${label}`);
  }
  if (live) {
    const expectedText = `live candidate ${receipt.candidate_id.slice(0, 12)} ok`;
    const expectedLog = path.join(home, "Library", "Logs", receipt.release.profile.productName, "main.log");
    const port = Number(evidence.dashboard_port);
    if (evidence.host_architecture !== architecture
        || evidence.release_channel !== receipt.release.channel
        || evidence.release_app_bundle_name !== receipt.release.profile.appBundleName
        || path.basename(evidence.installed_app_path || "") !== receipt.release.profile.appBundleName
        || path.resolve(evidence.main_log_path || "") !== path.resolve(expectedLog)
        || evidence.prompt_text !== `Reply exactly: ${expectedText}`
        || evidence.expected_text !== expectedText
        || evidence.final_text !== expectedText
        || evidence.terminal_status !== "complete"
        || typeof evidence.persisted_session_id !== "string"
        || typeof evidence.resumed_session_id !== "string"
        || !Number.isInteger(evidence.resumed_message_count) || evidence.resumed_message_count < 2
        || evidence.license_authenticated !== true
        || evidence.license_expired !== false
        || !Number.isInteger(port)
        || port < receipt.release.profile.preferredPort
        || port > receipt.release.profile.preferredPort + 10) {
      throw new Error(`[candidate] invalid live AI evidence: ${label}`);
    }
  }
  const started = Date.parse(evidence.started_at || "");
  const completed = Date.parse(evidence.completed_at || "");
  if (!Number.isFinite(started) || !Number.isFinite(completed) || completed < started
      || !Number.isFinite(evidence.duration_ms) || evidence.duration_ms < 0) {
    throw new Error(`[candidate] smoke evidence has invalid timing: ${label}`);
  }
  if (evidence.evidence_integrity_sha256 !== evidenceIntegrity(evidence)) {
    throw new Error(`[candidate] smoke evidence integrity mismatch: ${label}`);
  }
  return true;
}

function validateRealtorBetaGateEvidence(
  evidence,
  receipt,
  architecture,
  receiptPath,
  label = "realtor_beta_gate",
) {
  const release = receipt.release || {};
  const profile = release.profile || {};
  const recovery = evidence.recovery || {};
  const expectedRecovery = receipt.recovery;
  const recoveryApplicable = expectedRecovery != null;
  const stable = receipt.public_feeds_at_finalize?.latest || {};
  const candidateFeed = receipt.artifacts?.[release.feed_name] || {};
  if (release.channel !== "beta"
      || profile.appBundleName !== "Elevate Beta.app"
      || receipt.production_feed_untouched !== true
      || !ARCHITECTURES.includes(architecture)
      || !receipt.apps?.[architecture]) {
    throw new Error(`[candidate] invalid Realtor Beta gate context: ${label}`);
  }
  if (evidence.evidence_schema_version !== REALTOR_BETA_GATE_EVIDENCE_SCHEMA_VERSION
      || evidence.kind !== "elevate-realtor-beta-prepublish-gate"
      || evidence.ok !== true
      || !Array.isArray(evidence.failures) || evidence.failures.length !== 0
      || evidence.candidate_id !== receipt.candidate_id
      || evidence.source_receipt_id !== receipt.source_receipt_id
      || evidence.candidate_architecture !== architecture
      || evidence.candidate_receipt_sha256 !== sha256File(receiptPath)
      || evidence.candidate_app_version !== release.version
      || evidence.candidate_app_bundle_manifest_sha256 !== receipt.apps[architecture].bundle_manifest.sha256
      || evidence.release_channel !== "beta"
      || evidence.release_app_bundle_name !== profile.appBundleName
      || evidence.installed_app_name !== profile.appBundleName) {
    throw new Error(`[candidate] invalid required Realtor Beta gate evidence: ${label}`);
  }
  const requiredCheckIds = recoveryApplicable
    ? REQUIRED_REALTOR_BETA_GATE_CHECK_IDS
    : [...REQUIRED_REALTOR_BETA_BASE_CHECK_IDS, REALTOR_BETA_RECOVERY_NOT_APPLICABLE_CHECK_ID];
  const forbiddenCheckIds = recoveryApplicable
    ? [REALTOR_BETA_RECOVERY_NOT_APPLICABLE_CHECK_ID]
    : REALTOR_BETA_RECOVERY_CHECK_IDS;
  if (!Array.isArray(evidence.check_ids)
      || evidence.check_ids.length !== new Set(evidence.check_ids).size
      || requiredCheckIds.some((check) => !evidence.check_ids.includes(check))
      || forbiddenCheckIds.some((check) => evidence.check_ids.includes(check))) {
    throw new Error(`[candidate] Realtor Beta gate evidence is missing required checks: ${label}`);
  }
  if (evidence.test_profile?.name !== "exact-installed-realtor-beta-prepublish-v1"
      || evidence.test_profile.isolated_home !== true
      || evidence.test_profile.installed_profile_mutation !== false
      || evidence.test_profile.remote_mutation !== false
      || evidence.test_profile.public_feed_mutation !== false
      || evidence.profile?.identities_distinct !== true
      || evidence.profile?.production_feed_untouched !== true
      || !Number.isInteger(evidence.profile?.preferred_port)
      || evidence.profile.preferred_port !== Number(profile.preferredPort)) {
    throw new Error(`[candidate] Realtor Beta gate used the wrong isolation profile: ${label}`);
  }
  if (evidence.installed_runtime?.module_count < 7
      || evidence.installed_runtime?.python_major !== 3
      || evidence.tool_parity?.request_count !== evidence.tool_parity?.receipt_count
      || evidence.tool_parity?.request_count < 2
      || evidence.pack?.form_count !== 34
      || !/^[a-f0-9]{64}$/.test(evidence.pack?.pack_sha256 || "")
      || evidence.action_faults?.forms_missing_available !== false
      || evidence.action_faults?.forms_fake_available !== false
      || evidence.action_faults?.artifact_rejections !== 2
      || evidence.action_faults?.worker_retry_count !== 1
      || evidence.action_faults?.worker_terminal_status !== "failed"
      || evidence.session_resume?.session_id_preserved !== true
      || evidence.session_resume?.message_count < 1
      || evidence.session_resume?.resume_pending_cleared !== true) {
    throw new Error(`[candidate] Realtor Beta installed fault evidence is invalid: ${label}`);
  }
  if (recoveryApplicable) {
    if (recovery.mode !== "local-fixture-roll-forward"
        || recovery.candidate_version !== release.version
        || recovery.recovery_version !== expectedRecovery.version
        || recovery.source_receipt_id !== receipt.source_receipt_id
        || recovery.recovery_feed_sha256 !== expectedRecovery.local_feed?.sha256
        || recovery.beta_after_sha256 !== expectedRecovery.local_feed?.sha256
        || recovery.candidate_feed_sha256 !== candidateFeed.sha256
        || recovery.stable_before_sha256 !== stable.sha256
        || recovery.stable_after_sha256 !== stable.sha256
        || recovery.stable_expected_sha256 !== stable.sha256
        || recovery.stable_alias_count !== 2
        || recovery.recovery_alias_count !== 4
        || recovery.recovery_artifact_count !== 4
        || recovery.recovery_architecture_count !== 2
        || recovery.signed_app_count !== 2
        || recovery.notarized_app_count !== 2
        || recovery.stapled_app_count !== 2
        || recovery.runtime_actor_count !== 0
        || recovery.backend_actor_count !== 0
        || recovery.gateway_actor_count !== 0
        || recovery.tool_actor_count !== 0
        || recovery.artifact_bytes_mode !== "synthetic-local-fixture"
        || recovery.remote_mutation !== false
        || recovery.production_mutated !== false
        || recovery.profile_data_mutations !== 0
        || recovery.rpo_seconds !== 0
        || recovery.procedure_id !== REALTOR_BETA_RECOVERY_PROCEDURE_ID) {
      throw new Error(`[candidate] Realtor Beta recovery roll-forward drill evidence is invalid: ${label}`);
    }
  } else if (canonicalJson(recovery) !== canonicalJson({
    mode: "not-applicable",
    candidate_version: release.version,
    source_receipt_id: receipt.source_receipt_id,
    reason: "candidate-has-no-recovery-contract",
    remote_mutation: false,
    production_mutated: false,
    profile_data_mutations: 0,
  })) {
    throw new Error(`[candidate] Realtor Beta recovery applicability evidence is invalid: ${label}`);
  }
  const started = Date.parse(evidence.started_at || "");
  const completed = Date.parse(evidence.completed_at || "");
  if (!Number.isFinite(started) || !Number.isFinite(completed) || completed < started
      || !Number.isFinite(evidence.duration_ms) || evidence.duration_ms < 0) {
    throw new Error(`[candidate] Realtor Beta gate evidence has invalid timing: ${label}`);
  }
  if (evidence.evidence_integrity_sha256 !== evidenceIntegrity(evidence)) {
    throw new Error(`[candidate] Realtor Beta gate evidence integrity mismatch: ${label}`);
  }
  return true;
}

function syncPath(filePath) {
  const fd = fs.openSync(filePath, "r");
  try {
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
}

function verifyReleaseArchive(archivePath) {
  const manifestPath = path.join(archivePath, "archive.json");
  if (!fs.existsSync(manifestPath)) throw new Error(`[candidate] release archive is missing archive.json: ${archivePath}`);
  const manifest = readJson(manifestPath);
  if (manifest.kind !== "elevate-release-archive"
      || receiptId(manifest, "archive_id") !== manifest.archive_id) {
    throw new Error("[candidate] release archive receipt ID mismatch");
  }
  for (const [relative, record] of Object.entries(manifest.files || {})) {
    if (path.isAbsolute(relative) || relative.includes("\\") || relative.split("/").includes("..")) {
      throw new Error(`[candidate] unsafe release archive path: ${relative}`);
    }
    assertFileRecord(path.join(archivePath, relative), record, `archived ${relative}`);
  }
  return manifest;
}

function successfulReleaseActiveFiles({
  candidate,
  distRoot = DIST,
  repoRoot = REPO,
  sourceReceiptPath = path.join(distRoot, "candidate-source.json"),
  webBuildReceiptPath = path.join(distRoot, "candidate-web.json"),
  candidateReceiptPath = path.join(distRoot, "candidate-receipt.json"),
  publicReadbackPath = path.join(distRoot, "evidence", "public-readback.json"),
  shipRecordPath = path.join(distRoot, "evidence", "ship.json"),
} = {}) {
  const archiveEvidenceKeys = [
    "x64_smoke",
    "arm64_smoke",
    "live_ai",
    ...(candidate.release.channel === "beta" ? ["realtor_beta_gate"] : []),
  ];
  const active = [
    ["candidate-source.json", sourceReceiptPath],
    ["candidate-web.json", webBuildReceiptPath],
    ["candidate-receipt.json", candidateReceiptPath],
    ...archiveEvidenceKeys.map((key) => {
      const relative = candidate.required_evidence?.[key];
      if (typeof relative !== "string" || !relative || path.isAbsolute(relative)
          || relative.includes("\\") || relative.split("/").includes("..")) {
        throw new Error(`[candidate] missing or unsafe archive evidence pointer: ${key}`);
      }
      return [`evidence/${path.basename(relative)}`, path.join(repoRoot, relative)];
    }),
    ["evidence/public-readback.json", publicReadbackPath],
    ["evidence/ship.json", shipRecordPath],
  ];
  if (new Set(active.map(([relative]) => relative)).size !== active.length) {
    throw new Error("[candidate] successful release archive paths are not unique");
  }
  return active;
}

function assertArchiveRecordEquals(actual, expected, label) {
  if (!actual || actual.size !== expected?.size || actual.sha256 !== expected?.sha256) {
    throw new Error(`[candidate] release archive ${label} does not match the candidate`);
  }
}

function loadSuccessfulReleaseArchive({
  archivePath,
  expectedCandidate = null,
  expectedChannel = null,
  expectedVersion = null,
} = {}) {
  const stat = fs.lstatSync(archivePath, { throwIfNoEntry: false });
  if (!stat || !stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error(`[candidate] successful release archive is not a real directory: ${archivePath}`);
  }
  const manifest = verifyReleaseArchive(archivePath);
  if (manifest.schema_version !== 1 || !Number.isFinite(Date.parse(manifest.archived_at || ""))) {
    throw new Error("[candidate] release archive manifest schema or timestamp is invalid");
  }
  const candidate = readJson(path.join(archivePath, "candidate-receipt.json"));
  if (candidate?.kind !== "elevate-final-candidate"
      || !candidate.candidate_id
      || receiptId(candidate, "candidate_id") !== candidate.candidate_id) {
    throw new Error("[candidate] archived final candidate receipt is invalid");
  }
  if (!CHANNELS.has(candidate.release?.channel)
      || !/^\d+\.\d+\.\d+$/.test(candidate.release?.version || "")) {
    throw new Error("[candidate] archived final candidate release identity is invalid");
  }
  if (expectedCandidate && canonicalJson(candidate) !== canonicalJson(expectedCandidate)) {
    throw new Error("[candidate] release archive belongs to a different candidate");
  }
  if ((expectedChannel && candidate.release?.channel !== expectedChannel)
      || (expectedVersion && candidate.release?.version !== expectedVersion)) {
    throw new Error("[candidate] release archive channel/version does not match the requested ship");
  }
  const expectedName = `${candidate.release.version}-${candidate.candidate_id}`;
  if (path.basename(path.resolve(archivePath)) !== expectedName
      || manifest.candidate_id !== candidate.candidate_id
      || manifest.source_receipt_id !== candidate.source_receipt_id
      || manifest.channel !== candidate.release.channel
      || manifest.version !== candidate.release.version) {
    throw new Error("[candidate] release archive identity is not bound to its candidate");
  }

  const active = successfulReleaseActiveFiles({
    candidate,
    distRoot: path.dirname(path.dirname(path.dirname(path.resolve(archivePath)))),
    repoRoot: REPO,
  });
  const expectedFiles = active.map(([relative]) => relative).sort();
  if (canonicalJson(Object.keys(manifest.files || {}).sort()) !== canonicalJson(expectedFiles)) {
    throw new Error("[candidate] release archive file manifest is incomplete or contains extras");
  }
  const source = readJson(path.join(archivePath, "candidate-source.json"));
  const web = readJson(path.join(archivePath, "candidate-web.json"));
  if (canonicalJson(source) !== canonicalJson(candidate.source)
      || canonicalJson(web) !== canonicalJson(candidate.web_build)) {
    throw new Error("[candidate] archived source/web receipts do not match the final candidate");
  }
  const candidateReceiptRecord = manifest.files["candidate-receipt.json"];
  if (candidateReceiptRecord.sha256 !== sha256File(path.join(archivePath, "candidate-receipt.json"))) {
    throw new Error("[candidate] archived candidate receipt digest is invalid");
  }
  for (const relative of expectedFiles.filter((name) => name.startsWith("evidence/")
    && !name.endsWith("public-readback.json") && !name.endsWith("ship.json"))) {
    if (readJson(path.join(archivePath, relative)).candidate_id !== candidate.candidate_id) {
      throw new Error(`[candidate] archived release evidence belongs to another candidate: ${relative}`);
    }
  }

  const feedName = candidate.release.feed_name;
  const publicReadback = readJson(path.join(archivePath, "evidence", "public-readback.json"));
  if (publicReadback?.schema_version !== 1 || publicReadback.kind !== "elevate-public-readback"
      || publicReadback.candidate_id !== candidate.candidate_id
      || publicReadback.source_receipt_id !== candidate.source_receipt_id
      || publicReadback.candidate_receipt_sha256 !== candidateReceiptRecord.sha256
      || publicReadback.channel !== candidate.release.channel
      || publicReadback.version !== candidate.release.version
      || publicReadback.feed?.url !== `${PUBLIC_BASE_URL}/${feedName}`
      || publicReadback.feed?.sha256 !== candidate.artifacts?.[feedName]?.sha256
      || publicReadback.feed?.size !== candidate.artifacts?.[feedName]?.size
      || !Number.isFinite(Date.parse(publicReadback.verified_at || ""))) {
    throw new Error("[candidate] archived public readback is not exact candidate completion evidence");
  }
  const artifactNames = candidate.release.artifact_names || [];
  if (canonicalJson(Object.keys(publicReadback.artifacts || {}).sort())
      !== canonicalJson([...artifactNames].sort())) {
    throw new Error("[candidate] archived public readback artifact manifest is incomplete");
  }
  for (const name of artifactNames) {
    assertArchiveRecordEquals(publicReadback.artifacts[name], candidate.artifacts[name], `public artifact ${name}`);
    if (publicReadback.artifacts[name].url !== `${PUBLIC_BASE_URL}/${name}`) {
      throw new Error(`[candidate] archived public artifact URL mismatch: ${name}`);
    }
  }
  const aliases = candidate.release.download_aliases || [];
  if (canonicalJson(Object.keys(publicReadback.aliases || {}).sort()) !== canonicalJson([...aliases].sort())) {
    throw new Error("[candidate] archived public readback alias manifest is incomplete");
  }
  for (const alias of aliases) {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    const sourceName = artifactNames.find((name) => name.endsWith(`-mac-${arch}.dmg`));
    if (!sourceName) throw new Error(`[candidate] archived candidate has no ${arch} alias source`);
    assertArchiveRecordEquals(publicReadback.aliases[alias], candidate.artifacts[sourceName], `public alias ${alias}`);
    if (publicReadback.aliases[alias].url !== `${PUBLIC_BASE_URL}/${alias}`) {
      throw new Error(`[candidate] archived public alias URL mismatch: ${alias}`);
    }
  }

  const ship = readJson(path.join(archivePath, "evidence", "ship.json"));
  if (ship?.schema_version !== 1 || ship.kind !== "elevate-ship-record"
      || ship.candidate_id !== candidate.candidate_id
      || ship.source_receipt_id !== candidate.source_receipt_id
      || ship.candidate_receipt_sha256 !== candidateReceiptRecord.sha256
      || ship.channel !== candidate.release.channel
      || ship.version !== candidate.release.version
      || !new Set(["committed", "recovered_committed", "already_committed"]).has(ship.remote_publish_state)
      || ship.public_feed !== `${PUBLIC_BASE_URL}/${feedName}`
      || ship.public_readback_sha256 !== manifest.files["evidence/public-readback.json"].sha256
      || ship.live_ai_evidence_sha256 !== manifest.files["evidence/live-ai.json"].sha256
      || !Number.isFinite(Date.parse(ship.shipped_at || ""))) {
    throw new Error("[candidate] archived ship record is not exact remote completion evidence");
  }
  if (canonicalJson(ship.rollback_target) !== canonicalJson(candidate.rollback_target)
      || canonicalJson(Object.keys(ship.public_artifacts || {}).sort()) !== canonicalJson([...artifactNames].sort())) {
    throw new Error("[candidate] archived ship record candidate manifest is incomplete");
  }
  for (const name of artifactNames) {
    if (canonicalJson(ship.public_artifacts[name]) !== canonicalJson(candidate.artifacts[name])) {
      throw new Error(`[candidate] archived ship record artifact mismatch: ${name}`);
    }
  }
  return { archivePath: path.resolve(archivePath), archive: manifest, candidate, publicReadback, ship };
}

function findSuccessfulReleaseArchive({ distRoot = DIST, channel, version } = {}) {
  if (!CHANNELS.has(channel) || !/^\d+\.\d+\.\d+$/.test(version || "")) {
    throw new Error("[candidate] exact release channel/version is required for archive recovery");
  }
  const parent = path.join(distRoot, "release-receipts", channel);
  const parentStat = fs.lstatSync(parent, { throwIfNoEntry: false });
  if (!parentStat) return null;
  if (!parentStat.isDirectory() || parentStat.isSymbolicLink()) {
    throw new Error("[candidate] release archive parent is not a real directory");
  }
  const pattern = new RegExp(`^${version.replaceAll(".", "\\.")}-[a-f0-9]{64}$`);
  const matches = fs.readdirSync(parent, { withFileTypes: true })
    .filter((entry) => pattern.test(entry.name))
    .map((entry) => {
      if (!entry.isDirectory() || entry.isSymbolicLink()) {
        throw new Error(`[candidate] matching release archive is not a real directory: ${entry.name}`);
      }
      return loadSuccessfulReleaseArchive({
        archivePath: path.join(parent, entry.name),
        expectedChannel: channel,
        expectedVersion: version,
      });
    });
  if (matches.length > 1) {
    throw new Error(`[candidate] multiple successful release archives match ${channel} ${version}`);
  }
  return matches[0] || null;
}

function resolveReleaseCandidateForShip({
  distRoot = DIST,
  channel,
  version,
  verifyActiveCandidate,
} = {}) {
  const archiveRecovery = findSuccessfulReleaseArchive({ distRoot, channel, version });
  if (archiveRecovery) return { candidate: archiveRecovery.candidate, archiveRecovery };
  if (typeof verifyActiveCandidate !== "function") {
    throw new Error("[candidate] active candidate verifier is required when no successful archive exists");
  }
  return { candidate: verifyActiveCandidate(), archiveRecovery: null };
}

function retireSuccessfulReleaseActivePointers({ active, archive, crashAfterStep = 0, startingStep = 1 }) {
  for (const [relative, filePath] of active) {
    const stat = fs.lstatSync(filePath, { throwIfNoEntry: false });
    if (!stat) continue;
    if (!stat.isFile() || stat.isSymbolicLink()) {
      throw new Error(`[candidate] refusing to remove unsafe active release pointer: ${filePath}`);
    }
    assertFileRecord(filePath, archive.files[relative], `active ${relative}`);
  }
  let step = startingStep;
  for (const [relative, filePath] of active) {
    const stat = fs.lstatSync(filePath, { throwIfNoEntry: false });
    if (stat) {
      if (!stat.isFile() || stat.isSymbolicLink()) {
        throw new Error(`[candidate] refusing to remove unsafe active release pointer: ${filePath}`);
      }
      assertFileRecord(filePath, archive.files[relative], `active ${relative}`);
      fs.unlinkSync(filePath);
      syncPath(path.dirname(filePath));
    }
    step += 1;
    if (crashAfterStep === step) {
      throw new Error(`[candidate] injected archive crash after active pointer ${relative}`);
    }
  }
}

function archiveSuccessfulRelease({
  candidate,
  distRoot = DIST,
  repoRoot = REPO,
  sourceReceiptPath = path.join(distRoot, "candidate-source.json"),
  webBuildReceiptPath = path.join(distRoot, "candidate-web.json"),
  candidateReceiptPath = path.join(distRoot, "candidate-receipt.json"),
  publicReadbackPath = path.join(distRoot, "evidence", "public-readback.json"),
  shipRecordPath = path.join(distRoot, "evidence", "ship.json"),
  archivedAt = new Date().toISOString(),
  crashAfterStep = 0,
} = {}) {
  if (!candidate?.candidate_id || receiptId(candidate, "candidate_id") !== candidate.candidate_id) {
    throw new Error("[candidate] cannot archive an invalid final candidate");
  }
  if (!CHANNELS.has(candidate.release?.channel)
      || !/^\d+\.\d+\.\d+$/.test(candidate.release?.version || "")) {
    throw new Error("[candidate] cannot archive an invalid release identity");
  }
  const active = successfulReleaseActiveFiles({
    candidate,
    distRoot,
    repoRoot,
    sourceReceiptPath,
    webBuildReceiptPath,
    candidateReceiptPath,
    publicReadbackPath,
    shipRecordPath,
  });
  if (!Number.isSafeInteger(crashAfterStep) || crashAfterStep < 0 || crashAfterStep > active.length + 1) {
    throw new Error("[candidate] invalid release archive crash injection");
  }
  const parent = path.join(distRoot, "release-receipts", candidate.release.channel);
  const target = path.join(parent, `${candidate.release.version}-${candidate.candidate_id}`);
  fs.mkdirSync(parent, { recursive: true });
  const parentStat = fs.lstatSync(parent, { throwIfNoEntry: false });
  if (!parentStat?.isDirectory() || parentStat.isSymbolicLink()) {
    throw new Error("[candidate] release archive parent is not a real directory");
  }
  if (fs.existsSync(target)) {
    const adopted = loadSuccessfulReleaseArchive({ archivePath: target, expectedCandidate: candidate });
    retireSuccessfulReleaseActivePointers({ active, archive: adopted.archive });
    return { archivePath: target, archive: adopted.archive, adopted: true };
  }
  for (const [, filePath] of active) {
    if (!fs.existsSync(filePath)) throw new Error(`[candidate] successful release archive input is missing: ${filePath}`);
  }
  if (canonicalJson(readJson(sourceReceiptPath)) !== canonicalJson(candidate.source)
      || canonicalJson(readJson(webBuildReceiptPath)) !== canonicalJson(candidate.web_build)
      || canonicalJson(readJson(candidateReceiptPath)) !== canonicalJson(candidate)) {
    throw new Error("[candidate] active receipt pointers do not match the shipped candidate");
  }
  for (const [, filePath] of active.slice(3)) {
    if (readJson(filePath).candidate_id !== candidate.candidate_id) {
      throw new Error(`[candidate] archive evidence belongs to a different candidate: ${filePath}`);
    }
  }

  const temp = `${target}.tmp-${process.pid}-${crypto.randomUUID()}`;
  fs.mkdirSync(temp);
  try {
    const records = {};
    for (const [relative, source] of active) {
      const destination = path.join(temp, relative);
      fs.mkdirSync(path.dirname(destination), { recursive: true });
      fs.copyFileSync(source, destination, fs.constants.COPYFILE_EXCL);
      syncPath(destination);
      records[relative] = fileRecord(destination, temp);
      assertFileRecord(destination, records[relative], `archived ${relative}`);
    }
    const archive = writeImmutableReceipt(path.join(temp, "archive.json"), {
      schema_version: 1,
      kind: "elevate-release-archive",
      archived_at: archivedAt,
      candidate_id: candidate.candidate_id,
      source_receipt_id: candidate.source_receipt_id,
      channel: candidate.release.channel,
      version: candidate.release.version,
      files: records,
    }, "archive_id");
    syncPath(path.join(temp, "archive.json"));
    verifyReleaseArchive(temp);
    syncPath(temp);
    fs.renameSync(temp, target);
    syncPath(parent);
    const verifiedRelease = loadSuccessfulReleaseArchive({ archivePath: target, expectedCandidate: candidate });
    const verified = verifiedRelease.archive;
    if (verified.archive_id !== archive.archive_id) throw new Error("[candidate] release archive changed during commit");
    if (crashAfterStep === 1) throw new Error("[candidate] injected archive crash after durable archive rename");
    retireSuccessfulReleaseActivePointers({ active, archive: verified, crashAfterStep, startingStep: 1 });
    return { archivePath: target, archive: verified, adopted: false };
  } catch (error) {
    fs.rmSync(temp, { recursive: true, force: true });
    throw error;
  }
}

function main(argv = process.argv.slice(2)) {
  const command = argv[0];
  if (command === "verify-source") {
    const packageJson = require(path.join(DESKTOP, "package.json"));
    const channel = (process.env.ELEVATE_RELEASE_CHANNEL || "latest").trim().toLowerCase();
    const receipt = verifySourceReceipt({ channel, version: packageJson.version });
    console.log(receipt.source_receipt_id);
    return;
  }
  if (command === "build-mac") {
    console.log(runMacBuilders());
    return;
  }
  if (command === "verify-final") {
    const requireEvidence = argv.includes("--require-evidence")
      ? true
      : (argv.includes("--require-static-evidence") ? "static" : false);
    const receipt = verifyCandidateReceipt({ requireEvidence });
    console.log(receipt.candidate_id);
    return;
  }
  if (command === "verify-app") {
    const value = (flag) => {
      const index = argv.indexOf(flag);
      if (index < 0 || !argv[index + 1]) throw new Error(`[candidate] missing ${flag}`);
      return argv[index + 1];
    };
    const result = verifyAppAgainstReceipt({
      receiptPath: path.resolve(value("--receipt")),
      appPath: path.resolve(value("--app")),
      architecture: value("--arch"),
    });
    console.log(JSON.stringify(result));
    return;
  }
  throw new Error("usage: candidate-receipt.js verify-source|build-mac|verify-final|verify-app");
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error?.message || String(error));
    process.exit(1);
  }
}

module.exports = {
  ARCHITECTURES,
  CANDIDATE_RECEIPT_SCHEMA_VERSION,
  CANDIDATE_RECEIPT,
  PRE_SIGN_EVIDENCE_SCHEMA_VERSION,
  REALTOR_BETA_GATE_EVIDENCE_SCHEMA_VERSION,
  REQUIRED_LIVE_AI_CHECK_IDS,
  REQUIRED_REALTOR_BETA_BASE_CHECK_IDS,
  REQUIRED_REALTOR_BETA_GATE_CHECK_IDS,
  REQUIRED_SMOKE_CHECK_IDS,
  REALTOR_BETA_RECOVERY_NOT_APPLICABLE_CHECK_ID,
  REALTOR_BETA_RECOVERY_PROCEDURE_ID,
  REALTOR_BETA_ROLLBACK_PROCEDURE_ID,
  ROLLBACK_FREEZE_FILE,
  SOURCE_RECEIPT_SCHEMA_VERSION,
  SOURCE_RECEIPT,
  SMOKE_EVIDENCE_SCHEMA_VERSION,
  TRUSTED_APPLE_TEAM_ID,
  WEB_BUILD_RECEIPT,
  assertCompleteAsar,
  assertBundleManifest,
  assertCanonicalPackagedPermissions,
  assertEmbeddedWebMatchesBuild,
  assertFileRecord,
  assertGloballyNewVersion,
  assertPackagedMetadata,
  assertPublicFeedsUnchanged,
  assertRuntimeCodeContract,
  assertTrustedSignerEvidence,
  archiveSuccessfulRelease,
  buildRemotePublishInnerScript,
  buildRemotePublishTransaction,
  canonicalJson,
  captureToolchain,
  classifyPublicCandidateFeeds,
  collectAppSigningEvidence,
  compareSemver,
  createFinalReceipt,
  createPreSignEvidence,
  createSourceReceipt,
  createWebBuildReceipt,
  evidenceIntegrity,
  fetchPublicFeeds,
  findSuccessfulReleaseArchive,
  fileRecord,
  hashTree,
  hashPortableTree,
  normalizeArchitecture,
  loadSuccessfulReleaseArchive,
  portableAsarDirectoryHash,
  preSignEvidencePath,
  profileSnapshot,
  releaseCommandDefaults,
  realtorBetaRetainedRecoveryFeedName,
  realtorBetaRollbackClearedFile,
  realtorBetaRollbackFreezeBytes,
  realtorBetaRollbackFreezeRecord,
  resolveReleaseCandidateForShip,
  receiptId,
  recoveryStaticProvenance,
  runMacBuilders,
  sha256File,
  verifyAppAgainstReceipt,
  validateSmokeEvidence,
  validateRealtorBetaGateEvidence,
  validateZipArchiveEntries,
  validateZipEntries,
  validateZipEntryListing,
  verifyCandidateReceipt,
  verifyPreSignEvidence,
  verifySourceReceipt,
  verifyWebBuildReceipt,
  validateFeed,
  verifyReleaseArchive,
  waitForCompleteAsar,
  writeAtomicJson,
  writeImmutableReceipt,
};
