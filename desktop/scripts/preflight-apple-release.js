#!/usr/bin/env node
// Local release gate for the Developer ID notarized macOS distribution lane.

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const ROOT = path.resolve(__dirname, "..");
const REPO = path.resolve(ROOT, "..");
const RELEASE_CHANNEL = (process.env.ELEVATE_RELEASE_CHANNEL || "latest").trim().toLowerCase();
if (!["latest", "beta"].includes(RELEASE_CHANNEL)) {
  throw new Error(`[preflight] unsupported release channel: ${RELEASE_CHANNEL}`);
}
const packageJson = require(path.join(ROOT, "package.json"));
const packageLock = require(path.join(ROOT, "package-lock.json"));
const createBuilderConfig = require(path.join(ROOT, "electron-builder.config.js"));
const { resolveReleaseProfile } = require(path.join(ROOT, "src", "release-profile.js"));
const {
  compareSemver,
  createSourceReceipt,
  fetchPublicFeeds,
  TRUSTED_APPLE_TEAM_ID,
} = require(path.join(ROOT, "scripts", "candidate-receipt.js"));
const releaseProfile = resolveReleaseProfile(RELEASE_CHANNEL);
const stableProfile = resolveReleaseProfile("latest");
const effectiveBuild = createBuilderConfig();

const checks = [];

function record(name, ok, detail = "") {
  checks.push({ name, ok, detail });
}

function commandExists(command, args = ["--version"]) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    encoding: "utf8",
    timeout: 15_000,
  });
  return result.status === 0;
}

function commandAvailable(command) {
  const result = spawnSync("/usr/bin/which", [command], {
    cwd: ROOT,
    encoding: "utf8",
    timeout: 15_000,
  });
  return result.status === 0;
}

function output(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || ROOT,
    encoding: "utf8",
    timeout: options.timeout || 30_000,
  });
  return {
    ok: result.status === 0,
    stdout: result.stdout || "",
    stderr: result.stderr || "",
    status: result.status,
  };
}

function exists(relativePath) {
  return fs.existsSync(path.join(REPO, relativePath));
}

function isExecutable(relativePath) {
  try {
    const stat = fs.statSync(path.join(REPO, relativePath));
    return Boolean(stat.mode & 0o111);
  } catch {
    return false;
  }
}

function currentNodeVersionAtLeast(major, minor) {
  const parts = process.versions.node.split(".").map((part) => Number.parseInt(part, 10) || 0);
  if (parts[0] > major) return true;
  if (parts[0] < major) return false;
  return parts[1] >= minor;
}

function plistContains(relativePath, key) {
  const text = fs.readFileSync(path.join(REPO, relativePath), "utf8");
  return text.includes(`<key>${key}</key>`);
}

function developerIdIdentity() {
  if (process.env.CODESIGN_IDENTITY) return process.env.CODESIGN_IDENTITY;
  const cscName = (process.env.CSC_NAME || "").trim();
  if (cscName) {
    return cscName.startsWith("Developer ID Application:")
      ? cscName
      : `Developer ID Application: ${cscName}`;
  }
  const identities = output("security", ["find-identity", "-v", "-p", "codesigning"]);
  const match = identities.stdout.match(/"([^"]*Developer ID Application:[^"]+)"/);
  return match ? match[1] : "";
}

function notaryProfileWorks(profile) {
  if (process.env.ELEVATE_SKIP_NOTARY_PREFLIGHT === "1") {
    return { ok: true, skipped: true };
  }
  const result = output(
    "xcrun",
    ["notarytool", "history", "--keychain-profile", profile],
    { timeout: 45_000 }
  );
  return { ok: result.ok, skipped: false, status: result.status };
}

const RUNTIME_AGENT_PROBE = `
import sys
sys.path.insert(0, sys.argv[1])
import elevate_cli.main
from run_agent import AIAgent
AIAgent(
    model="dependency-smoke",
    provider="custom",
    base_url="http://127.0.0.1:9/v1",
    api_key="dependency-smoke",
    enabled_toolsets=[],
    quiet_mode=True,
    skip_context_files=True,
    skip_memory=True,
    persist_session=False,
)
`;

function summarizeProbe(result, successDetail) {
  if (result.status === 0) return { ok: true, detail: successDetail };
  const text = `${result.stdout || ""}\n${result.stderr || ""}`.trim();
  const detail = text
    ? text.split("\n").filter(Boolean).slice(-8).join(" | ")
    : result.error?.message || `exit ${result.status}`;
  return { ok: false, detail };
}

function probeBundledRuntime(relativePython) {
  const runtimePython = path.join(REPO, relativePython);
  const cliRoot = path.join(REPO, "cli");
  const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), "elevate-runtime-preflight-"));
  const env = {
    ...process.env,
    HOME: tempHome,
    ELEVATE_HOME: path.join(tempHome, ".elevate"),
    NO_COLOR: "1",
  };
  for (const key of Object.keys(env)) {
    if (
      ["PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE"].includes(key)
      || /(_API_KEY|_TOKEN|_SECRET|_KEY)$/.test(key)
    ) {
      delete env[key];
    }
  }

  const run = (args) => spawnSync(runtimePython, args, {
    cwd: tempHome,
    env,
    encoding: "utf8",
    timeout: 60_000,
  });
  try {
    return {
      dependencies: summarizeProbe(
        run(["-I", "-B", "-m", "pip", "check"]),
        "pip check passed",
      ),
      agent: summarizeProbe(
        run(["-I", "-B", "-c", RUNTIME_AGENT_PROBE, cliRoot]),
        "backend and AIAgent initialized",
      ),
    };
  } finally {
    fs.rmSync(tempHome, { recursive: true, force: true });
  }
}

record("running on macOS", process.platform === "darwin", process.platform);
record("Node.js 22.12 or newer", currentNodeVersionAtLeast(22, 12), process.version);
record("package version matches lockfile", packageJson.version === packageLock.version, `${packageJson.version} / ${packageLock.version}`);
record(
  "package root version matches lockfile package",
  packageJson.version === packageLock.packages?.[""]?.version,
  `${packageJson.version} / ${packageLock.packages?.[""]?.version || "missing"}`
);
record(
  "release build identity matches selected channel",
  effectiveBuild.productName === releaseProfile.productName
    && effectiveBuild.appId === releaseProfile.appId
    && effectiveBuild.extraMetadata?.name === releaseProfile.packageName
    && effectiveBuild.extraMetadata?.elevateReleaseChannel === releaseProfile.channel
    && effectiveBuild.artifactName === `${releaseProfile.artifactPrefix}-\${version}-\${os}-\${arch}.\${ext}`
    && effectiveBuild.protocols?.[0]?.schemes?.[0] === releaseProfile.protocolScheme
    && effectiveBuild.publish?.every((entry) => entry.channel === releaseProfile.channel),
  `${releaseProfile.productName} / ${releaseProfile.appId} / ${releaseProfile.protocolScheme}://`,
);
record(
  "Beta install identity and runtime defaults are isolated from Stable",
  !releaseProfile.isBeta || [
    "productName",
    "appBundleName",
    "appId",
    "packageName",
    "artifactPrefix",
    "downloadAliasPrefix",
    "downloadAliasPrefixes",
    "protocolScheme",
    "elevateHomeName",
    "workspaceName",
    "preferredPort",
    "gatewayLabel",
  ].every((key) => releaseProfile[key] !== stableProfile[key]),
  releaseProfile.isBeta ? `${releaseProfile.elevateHomeName} / port ${releaseProfile.preferredPort}` : "Stable lane",
);

let publicFeeds = {};
let feed = { version: null };
let baselineDetail = "public feeds unavailable";
try {
  publicFeeds = fetchPublicFeeds();
  const versions = Object.values(publicFeeds).map((item) => item.version).filter(Boolean);
  const highest = versions.sort(compareSemver).at(-1) || null;
  feed = { version: highest };
  baselineDetail = `max(beta ${publicFeeds.beta.version || "unpublished"}, latest ${publicFeeds.latest.version})`;
  record("both public release feeds readable", true, baselineDetail);
} catch (error) {
  record("both public release feeds readable", false, error?.message || String(error));
}
record(
  "package version is globally newer than Stable and Beta",
  Boolean(feed.version) && compareSemver(packageJson.version, feed.version) > 0,
  feed.version ? `${packageJson.version} > ${feed.version} (${baselineDetail})` : baselineDetail
);

const gitStatus = output("git", ["status", "--porcelain=v1", "--untracked-files=all"], { cwd: REPO });
record("release worktree is clean", gitStatus.ok && gitStatus.stdout.trim() === "", gitStatus.stdout.trim() || "clean");

record("xcrun available", commandExists("xcrun", ["--version"]));
record("codesign available", commandAvailable("codesign"));
record("spctl available", commandAvailable("spctl"));
record("security available", commandExists("security", ["find-identity", "-v", "-p", "codesigning"]));

const xcode = output("xcodebuild", ["-version"]);
const xcodeMajor = Number.parseInt((xcode.stdout.match(/Xcode\s+(\d+)/) || [])[1] || "0", 10);
record("Xcode 14 or newer installed", xcode.ok && xcodeMajor >= 14, xcode.stdout.split("\n")[0] || "not found");
record("notarytool available", commandExists("xcrun", ["notarytool", "--version"]));

const identity = developerIdIdentity();
record("Developer ID Application identity available", Boolean(identity), identity || "missing");
record(
  `Developer ID identity belongs to trusted Team ${TRUSTED_APPLE_TEAM_ID}`,
  identity.startsWith("Developer ID Application:") && identity.includes(`(${TRUSTED_APPLE_TEAM_ID})`),
  identity || "missing",
);

const profile = process.env.APPLE_KEYCHAIN_PROFILE || "elevate-notarization";
const notary = notaryProfileWorks(profile);
record(
  "notary keychain profile works",
  notary.ok,
  notary.skipped ? "skipped by ELEVATE_SKIP_NOTARY_PREFLIGHT=1" : profile
);

record("hardened runtime enabled", packageJson.build?.mac?.hardenedRuntime === true);
record("electron-builder notarization enabled", packageJson.build?.mac?.notarize === true);
record("macOS extended-attribute cleanup hook enabled", packageJson.build?.afterPack === "scripts/after-pack-mac.js");
record("macOS minimum version pinned", packageJson.build?.mac?.extendInfo?.LSMinimumSystemVersion === "12.0", packageJson.build?.mac?.extendInfo?.LSMinimumSystemVersion || "missing");
record("Developer ID targets configured", JSON.stringify(packageJson.build?.mac?.target || []).includes("dmg"));
record("app icon present", exists("desktop/assets/icon.icns"));
record("web dashboard source present", exists("cli/web/package.json"));
record("arm64 bundled Python present", isExecutable("desktop/runtime/arm64/python/bin/python3.12"));
record("x64 bundled Python present", isExecutable("desktop/runtime/x64/python/bin/python3.12"));
const arm64Runtime = probeBundledRuntime("desktop/runtime/arm64/python/bin/python3.12");
record("arm64 bundled Python dependency closure complete", arm64Runtime.dependencies.ok, arm64Runtime.dependencies.detail);
record("arm64 bundled backend/agent initializes", arm64Runtime.agent.ok, arm64Runtime.agent.detail);
const x64Runtime = probeBundledRuntime("desktop/runtime/x64/python/bin/python3.12");
record("x64 bundled Python dependency closure complete", x64Runtime.dependencies.ok, x64Runtime.dependencies.detail);
record("x64 bundled backend/agent initializes", x64Runtime.agent.ok, x64Runtime.agent.detail);
record("WhatsApp bridge script present", exists("cli/scripts/whatsapp-bridge/bridge.js"));
record("WhatsApp bridge package present", exists("cli/scripts/whatsapp-bridge/package.json"));

const runtimeResource = (packageJson.build?.extraResources || []).find(
  (resource) => resource.from === "runtime/${arch}/python",
);
record(
  "bundled runtime excludes .DS_Store files",
  runtimeResource?.filter?.includes("!**/.DS_Store") === true,
);

record("Apple Events entitlement present", plistContains("desktop/entitlements.mac.plist", "com.apple.security.automation.apple-events"));
record("microphone entitlement present", plistContains("desktop/entitlements.mac.plist", "com.apple.security.device.audio-input"));
record("JIT entitlement present for Electron", plistContains("desktop/entitlements.mac.plist", "com.apple.security.cs.allow-jit"));
record("debug entitlement absent", !plistContains("desktop/entitlements.mac.plist", "com.apple.security.get-task-allow"));

if (checks.every((check) => check.ok)) {
  try {
    const sourceReceipt = createSourceReceipt({
      channel: RELEASE_CHANNEL,
      version: packageJson.version,
      profile: releaseProfile,
      publicFeeds,
    });
    record("immutable candidate source contract written", true, sourceReceipt.source_receipt_id);
  } catch (error) {
    record("immutable candidate source contract written", false, error?.message || String(error));
  }
}

const failures = checks.filter((check) => !check.ok);
for (const check of checks) {
  const marker = check.ok ? "PASS" : "FAIL";
  const detail = check.detail ? ` - ${check.detail}` : "";
  console.log(`${marker} ${check.name}${detail}`);
}

if (failures.length > 0) {
  console.error(`\nApple release preflight failed: ${failures.length} blocking check(s).`);
  process.exit(1);
}

console.log("\nApple release preflight passed for Developer ID notarized distribution.");
