#!/usr/bin/env node
"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const yaml = require("js-yaml");
const { sanitizeFileName } = require("builder-util/out/filename");
const asar = require("@electron/asar");
const { hashRuntimeCodeTree } = require("./runtime-code-hash");
const {
  downloadAliasFileNames,
  releaseArtifactNames,
} = require("../src/release-profile");

const DESKTOP = path.resolve(__dirname, "..");
const REPO = path.resolve(DESKTOP, "..");
const DIST = path.join(DESKTOP, "dist");
const SOURCE_RECEIPT = path.join(DIST, "candidate-source.json");
const WEB_BUILD_RECEIPT = path.join(DIST, "candidate-web.json");
const CANDIDATE_RECEIPT = path.join(DIST, "candidate-receipt.json");
const CHANNELS = new Set(["latest", "beta"]);
const ARCHITECTURES = ["x64", "arm64"];
const PRE_SIGN_EVIDENCE_SCHEMA_VERSION = 1;
const PUBLIC_BASE_URL = "https://api.elevationrealestatehq.com/updates";
const TRUSTED_APPLE_TEAM_ID = "G5TK395RYH";
const SMOKE_EVIDENCE_SCHEMA_VERSION = 1;
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
      "web", "ui-tui", "venv", ".venv", "tests", "docs", "docker", "nix", "plans",
      "website", "packaging", "datagen-config-examples", "temp_vision_images", "scripts", "assets",
      ".git", ".pytest_cache",
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

function portableAsarDirectoryHash(asarPath, directory) {
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
    "desktop/scripts/preflight-apple-release.js",
    "desktop/scripts/merge-mac-feed.js",
    "desktop/scripts/finalize-mac-dist.js",
    "desktop/scripts/ship-to-hetzner.js",
    "cli/uv.lock",
    "cli/web/package-lock.json",
    "cli/scripts/installed_runtime_smoke.py",
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

function captureToolchain({ desktopRoot = DESKTOP, repoRoot = REPO } = {}) {
  const version = (command, args, cwd = desktopRoot, full = false) => {
    const result = run(command, args, { cwd });
    const text = (result.stdout || result.stderr).trim();
    return result.ok ? (full ? text.replaceAll("\n", " / ") : text.split("\n")[0]) : "unavailable";
  };
  return {
    node: process.version,
    host_architecture: process.arch,
    npm: version("npm", ["--version"]),
    electron: require(path.join(desktopRoot, "node_modules", "electron", "package.json")).version,
    electron_builder: version(path.join(desktopRoot, "node_modules", ".bin", "electron-builder"), ["--version"]),
    git: version("git", ["--version"], repoRoot),
    uv: version("uv", ["--version"], repoRoot),
    xcode: version("xcodebuild", ["-version"], desktopRoot, true),
    macos: version("sw_vers", ["-productVersion"]),
    x64_python: version(path.join(desktopRoot, "runtime", "x64", "python", "bin", "python3.12"), ["--version"]),
    arm64_python: version(path.join(desktopRoot, "runtime", "arm64", "python", "bin", "python3.12"), ["--version"]),
  };
}

function profileSnapshot(profile) {
  return Object.fromEntries([
    "channel", "productName", "appBundleName", "appId", "packageName", "artifactPrefix",
    "downloadAliasPrefix", "downloadAliasPrefixes", "protocolScheme",
    "elevateHomeName", "workspaceName", "preferredPort", "gatewayLabel",
  ].map((key) => [key, profile[key]]));
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

function runMacBuilders({
  verifySource = () => {
    const packageJson = require(path.join(DESKTOP, "package.json"));
    const channel = (process.env.ELEVATE_RELEASE_CHANNEL || "latest").trim().toLowerCase();
    return verifySourceReceipt({ channel, version: packageJson.version });
  },
  builderCommand = path.join(DESKTOP, "node_modules", ".bin", "electron-builder"),
  builderPrefixArgs = [],
  mergeCommand = "npm",
  mergeArgs = ["run", "merge:mac-feed"],
  webCommand = "npm",
  webArgs = ["--prefix", "../cli/web", "run", "build"],
  webOutputPath = path.join(REPO, "cli", "elevate_cli", "web_dist"),
  webReceiptPath = WEB_BUILD_RECEIPT,
  preSignEvidenceDirectory = DIST,
  cwd = DESKTOP,
  env = process.env,
  stdio = "inherit",
} = {}) {
  const source = verifySource();
  const sourceReceiptId = source?.source_receipt_id;
  if (!sourceReceiptId) throw new Error("[candidate] verified source receipt has no ID");
  const buildEnv = { ...env, ELEVATE_SOURCE_RECEIPT_ID: sourceReceiptId };
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
  repoRoot = REPO,
  desktopRoot = DESKTOP,
  outputPath = SOURCE_RECEIPT,
  createdAt = new Date().toISOString(),
  toolchain,
  inputs,
} = {}) {
  if (!CHANNELS.has(channel)) throw new Error(`[candidate] unsupported channel: ${channel}`);
  const git = currentGitState(repoRoot);
  if (!git.clean) throw new Error("[candidate] release worktree must be clean");
  const highestPublicVersion = assertGloballyNewVersion(version, publicFeeds);
  const resolvedInputs = inputs || sourceInputs({ repoRoot, desktopRoot });
  const resolvedToolchain = toolchain || captureToolchain({ repoRoot, desktopRoot });
  const finalGit = currentGitState(repoRoot);
  if (!finalGit.clean || canonicalJson(finalGit) !== canonicalJson(git)) {
    throw new Error("[candidate] checkout changed while the source receipt was being created");
  }
  const receipt = {
    schema_version: 1,
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
    },
    inputs: resolvedInputs,
    toolchain: resolvedToolchain,
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
  const updatePath = path.join(resources, "app-update.yml");
  const update = yaml.load(fs.readFileSync(updatePath, "utf8")) || {};
  const asarPath = path.join(resources, "app.asar");
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
    embedded_cli: hashTree(path.join(resources, "cli"), { mode: "cli-packaging" }),
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
  for (const raw of entries) {
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
  return true;
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
  const list = requireRun("unzip", ["-Z1", zipPath], { timeout: 120_000 }).split("\n").filter(Boolean);
  validateZipEntries(list, appBundleName);
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

function verifyArtifactPayloads({ release, apps, desktopRoot = DESKTOP } = {}) {
  const evidence = {};
  for (const arch of ARCHITECTURES) {
    const zip = release.artifact_names.find((name) => name.endsWith(`-mac-${arch}.zip`));
    const dmg = release.artifact_names.find((name) => name.endsWith(`-mac-${arch}.dmg`));
    if (!zip || !dmg) throw new Error(`[candidate] missing ${arch} ZIP/DMG artifact names`);
    evidence[arch] = {
      zip: { artifact: zip, ...verifyZipAppPayload(path.join(desktopRoot, "dist", zip), release.profile.appBundleName, apps[arch].bundle_manifest) },
      dmg: { artifact: dmg, ...verifyDmgAppPayload(path.join(desktopRoot, "dist", dmg), release.profile.appBundleName, apps[arch].bundle_manifest) },
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

function assertFileRecord(filePath, expected, label = path.basename(filePath)) {
  const actualSize = fs.statSync(filePath).size;
  if (actualSize !== expected.size) throw new Error(`[candidate] ${label} size mismatch`);
  const actualHash = sha256File(filePath);
  if (actualHash !== expected.sha256) throw new Error(`[candidate] ${label} SHA256 mismatch`);
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

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'\\''`)}'`;
}

function buildRemotePublishTransaction({
  candidate,
  remote = "/var/www/elevate-updates/",
  stagingName,
} = {}) {
  if (!candidate || !/^\.candidate-[a-f0-9]{64}-[A-Za-z0-9_-]+$/.test(stagingName || "")
      || !/^\/[A-Za-z0-9._/-]+\/$/.test(remote) || remote.split("/").includes("..")) {
    throw new Error("[candidate] incomplete or unsafe remote staging inputs");
  }
  const feedName = candidate.release.feed_name;
  const stage = `${remote}${stagingName}/`;
  const stagedNames = [...candidate.release.artifact_names, feedName];
  for (const name of stagedNames) {
    if (!/^[a-f0-9]{64}$/.test(candidate.artifacts?.[name]?.sha256 || "")) {
      throw new Error(`[candidate] missing SHA256 for staged release file: ${name}`);
    }
  }
  const aliasPairs = candidate.release.download_aliases.map((alias) => {
    const arch = alias.includes("-arm64.") ? "arm64" : "x64";
    const source = candidate.release.artifact_names.find((name) => name.endsWith(`-mac-${arch}.dmg`));
    if (!source) throw new Error(`[candidate] no ${arch} DMG for alias ${alias}`);
    return { alias, source };
  });
  const checks = ["latest", "beta"].map((channel) => {
    const target = `${remote}${channel}-mac.yml`;
    const expected = candidate.public_feeds_at_finalize[channel]?.sha256 || null;
    return expected
      ? `test -f ${shellQuote(target)} && test "$(sha256sum ${shellQuote(target)} | awk '{print $1}')" = ${shellQuote(expected)} || { echo ${shellQuote(`CAS_FAILED ${channel}`)} >&2; exit 42; }`
      : `test ! -e ${shellQuote(target)} || { echo ${shellQuote(`CAS_FAILED ${channel}`)} >&2; exit 42; }`;
  });
  const stagedChecks = stagedNames.map((name) =>
    `test -f ${shellQuote(`${stage}${name}`)} && test "$(sha256sum ${shellQuote(`${stage}${name}`)} | awk '{print $1}')" = ${shellQuote(candidate.artifacts[name].sha256)} || { echo ${shellQuote(`STAGED_HASH_FAILED ${name}`)} >&2; exit 43; }`);
  const collisionChecks = candidate.release.artifact_names.map((name) =>
    `if test -e ${shellQuote(`${remote}${name}`)}; then test -f ${shellQuote(`${remote}${name}`)} && test "$(sha256sum ${shellQuote(`${remote}${name}`)} | awk '{print $1}')" = ${shellQuote(candidate.artifacts[name].sha256)} || { echo ${shellQuote(`FINAL_COLLISION ${name}`)} >&2; exit 44; }; fi`);
  const publishArtifacts = candidate.release.artifact_names.flatMap((name) => [
    `if test -e ${shellQuote(`${remote}${name}`)}; then rm -f -- ${shellQuote(`${stage}${name}`)}; else mv ${shellQuote(`${stage}${name}`)} ${shellQuote(`${remote}${name}`)}; fi`,
    `chown www-data:www-data ${shellQuote(`${remote}${name}`)}`,
  ]);
  const prepareAliases = aliasPairs.flatMap(({ source, alias }) => [
    `cp ${shellQuote(`${remote}${source}`)} ${shellQuote(`${stage}${alias}`)}`,
    `test "$(sha256sum ${shellQuote(`${stage}${alias}`)} | awk '{print $1}')" = ${shellQuote(candidate.artifacts[source].sha256)} || { echo ${shellQuote(`ALIAS_HASH_FAILED ${alias}`)} >&2; exit 45; }`,
    `chown www-data:www-data ${shellQuote(`${stage}${alias}`)}`,
  ]);
  const publishAliases = aliasPairs.map(({ alias }) =>
    `mv -f ${shellQuote(`${stage}${alias}`)} ${shellQuote(`${remote}${alias}`)}`);
  const script = [
    "set -euo pipefail",
    `trap ${shellQuote(`rm -rf -- "${stage}"`)} EXIT`,
    ...checks,
    ...stagedChecks,
    ...collisionChecks,
    ...publishArtifacts,
    ...prepareAliases,
    ...(candidate.release.channel === "latest"
      ? [`find ${shellQuote(remote)} -maxdepth 1 -type f -name '*.zip.blockmap' -delete`]
      : []),
    ...publishAliases,
    `chown www-data:www-data ${shellQuote(`${stage}${feedName}`)}`,
    `mv -f ${shellQuote(`${stage}${feedName}`)} ${shellQuote(`${remote}${feedName}`)}`,
  ].join("\n");
  return `flock -x /var/lock/elevate-release-publish.lock bash -c ${shellQuote(script)}`;
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
  const receipt = {
    schema_version: 1,
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
    public_feeds_at_finalize: publicFeeds,
    rollback_target: publicFeeds[release.channel] || null,
    production_feed_untouched: stableUntouched,
    smoke_entrypoint: fileRecord(path.join(repoRoot, "cli", "scripts", "installed_runtime_smoke.py"), repoRoot),
    required_evidence: {
      x64_smoke: "desktop/dist/evidence/smoke-x64.json",
      arm64_smoke: "desktop/dist/evidence/smoke-arm64.json",
      live_ai: "desktop/dist/evidence/live-ai.json",
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
      : ["x64_smoke", "arm64_smoke", "live_ai"];
    for (const key of requiredKeys) {
      const relative = receipt.required_evidence?.[key];
      if (!relative) throw new Error(`[candidate] final receipt is missing required evidence pointer: ${key}`);
      const evidencePath = path.join(repoRoot, relative);
      if (!fs.existsSync(evidencePath)) throw new Error(`[candidate] missing required evidence: ${key}`);
      const evidence = readJson(evidencePath);
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
} = {}) {
  if (!candidate?.candidate_id || receiptId(candidate, "candidate_id") !== candidate.candidate_id) {
    throw new Error("[candidate] cannot archive an invalid final candidate");
  }
  const active = [
    ["candidate-source.json", sourceReceiptPath],
    ["candidate-web.json", webBuildReceiptPath],
    ["candidate-receipt.json", candidateReceiptPath],
    ...["x64_smoke", "arm64_smoke", "live_ai"].map((key) => {
      const relative = candidate.required_evidence?.[key];
      if (!relative) throw new Error(`[candidate] missing archive evidence pointer: ${key}`);
      return [`evidence/${path.basename(relative)}`, path.join(repoRoot, relative)];
    }),
    ["evidence/public-readback.json", publicReadbackPath],
    ["evidence/ship.json", shipRecordPath],
  ];
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

  const parent = path.join(distRoot, "release-receipts", candidate.release.channel);
  const target = path.join(parent, `${candidate.release.version}-${candidate.candidate_id}`);
  fs.mkdirSync(parent, { recursive: true });
  if (fs.existsSync(target)) throw new Error(`[candidate] release archive already exists: ${target}`);
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
    const verified = verifyReleaseArchive(target);
    if (verified.archive_id !== archive.archive_id) throw new Error("[candidate] release archive changed during commit");
    for (const [, filePath] of active) fs.unlinkSync(filePath);
    syncPath(distRoot);
    syncPath(path.join(distRoot, "evidence"));
    return { archivePath: target, archive: verified };
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
  CANDIDATE_RECEIPT,
  PRE_SIGN_EVIDENCE_SCHEMA_VERSION,
  REQUIRED_LIVE_AI_CHECK_IDS,
  REQUIRED_SMOKE_CHECK_IDS,
  SOURCE_RECEIPT,
  SMOKE_EVIDENCE_SCHEMA_VERSION,
  TRUSTED_APPLE_TEAM_ID,
  WEB_BUILD_RECEIPT,
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
  buildRemotePublishTransaction,
  canonicalJson,
  collectAppSigningEvidence,
  compareSemver,
  createFinalReceipt,
  createPreSignEvidence,
  createSourceReceipt,
  createWebBuildReceipt,
  evidenceIntegrity,
  fetchPublicFeeds,
  fileRecord,
  hashTree,
  hashPortableTree,
  normalizeArchitecture,
  portableAsarDirectoryHash,
  preSignEvidencePath,
  receiptId,
  runMacBuilders,
  sha256File,
  verifyAppAgainstReceipt,
  validateSmokeEvidence,
  validateZipEntries,
  verifyCandidateReceipt,
  verifyPreSignEvidence,
  verifySourceReceipt,
  verifyWebBuildReceipt,
  validateFeed,
  verifyReleaseArchive,
  writeAtomicJson,
  writeImmutableReceipt,
};
