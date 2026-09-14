#!/usr/bin/env node
// Local release gate for the Developer ID notarized macOS distribution lane.

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const ROOT = path.resolve(__dirname, "..");
const REPO = path.resolve(ROOT, "..");
const PUBLIC_FEED_URL = "https://api.elevationrealestatehq.com/updates/latest-mac.yml";
const packageJson = require(path.join(ROOT, "package.json"));
const packageLock = require(path.join(ROOT, "package-lock.json"));

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

function compareSemver(left, right) {
  const a = String(left).split(".").map((part) => Number.parseInt(part, 10) || 0);
  const b = String(right).split(".").map((part) => Number.parseInt(part, 10) || 0);
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    if ((a[i] || 0) > (b[i] || 0)) return 1;
    if ((a[i] || 0) < (b[i] || 0)) return -1;
  }
  return 0;
}

function currentNodeVersionAtLeast(major, minor) {
  const parts = process.versions.node.split(".").map((part) => Number.parseInt(part, 10) || 0);
  if (parts[0] > major) return true;
  if (parts[0] < major) return false;
  return parts[1] >= minor;
}

function latestFeedVersion() {
  const result = spawnSync(
    "curl",
    ["--fail", "--silent", "--show-error", "--location", "--max-time", "20", PUBLIC_FEED_URL],
    { cwd: ROOT, encoding: "utf8", timeout: 30_000 },
  );
  if (result.status !== 0) {
    return { version: null, error: (result.stderr || result.stdout || "").trim() || `curl exited ${result.status}` };
  }
  const text = result.stdout || "";
  const match = text.match(/^version:\s*([^\s]+)/m);
  return { version: match ? match[1].trim() : null, error: match ? "" : "missing version" };
}

function hasDsStore(relativePath) {
  const root = path.join(REPO, relativePath);
  const stack = [root];
  while (stack.length > 0) {
    const current = stack.pop();
    if (!fs.existsSync(current)) continue;
    const stat = fs.statSync(current);
    if (stat.isDirectory()) {
      for (const entry of fs.readdirSync(current)) stack.push(path.join(current, entry));
    } else if (path.basename(current) === ".DS_Store") {
      return path.relative(REPO, current);
    }
  }
  return "";
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

record("running on macOS", process.platform === "darwin", process.platform);
record("Node.js 22.12 or newer", currentNodeVersionAtLeast(22, 12), process.version);
record("package version matches lockfile", packageJson.version === packageLock.version, `${packageJson.version} / ${packageLock.version}`);
record(
  "package root version matches lockfile package",
  packageJson.version === packageLock.packages?.[""]?.version,
  `${packageJson.version} / ${packageLock.packages?.[""]?.version || "missing"}`
);

const feed = latestFeedVersion();
record(
  "package version is newer than public update feed",
  Boolean(feed.version) && compareSemver(packageJson.version, feed.version) > 0,
  feed.version ? `${packageJson.version} > ${feed.version}` : feed.error
);

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

const profile = process.env.APPLE_KEYCHAIN_PROFILE || "elevate-notarization";
const notary = notaryProfileWorks(profile);
record(
  "notary keychain profile works",
  notary.ok,
  notary.skipped ? "skipped by ELEVATE_SKIP_NOTARY_PREFLIGHT=1" : profile
);

record("hardened runtime enabled", packageJson.build?.mac?.hardenedRuntime === true);
record("electron-builder notarization enabled", packageJson.build?.mac?.notarize === true);
record("macOS minimum version pinned", packageJson.build?.mac?.extendInfo?.LSMinimumSystemVersion === "12.0", packageJson.build?.mac?.extendInfo?.LSMinimumSystemVersion || "missing");
record("Developer ID targets configured", JSON.stringify(packageJson.build?.mac?.target || []).includes("dmg"));
record("app icon present", exists("desktop/assets/icon.icns"));
record("web dashboard source present", exists("cli/web/package.json"));
record("arm64 bundled Python present", isExecutable("desktop/runtime/arm64/python/bin/python3.12"));
record("x64 bundled Python present", isExecutable("desktop/runtime/x64/python/bin/python3.12"));
record("WhatsApp bridge script present", exists("cli/scripts/whatsapp-bridge/bridge.js"));
record("WhatsApp bridge package present", exists("cli/scripts/whatsapp-bridge/package.json"));

const runtimeDsStore = hasDsStore("desktop/runtime");
record("bundled runtime has no .DS_Store files", !runtimeDsStore, runtimeDsStore || "clean");

record("Apple Events entitlement present", plistContains("desktop/entitlements.mac.plist", "com.apple.security.automation.apple-events"));
record("microphone entitlement present", plistContains("desktop/entitlements.mac.plist", "com.apple.security.device.audio-input"));
record("JIT entitlement present for Electron", plistContains("desktop/entitlements.mac.plist", "com.apple.security.cs.allow-jit"));
record("debug entitlement absent", !plistContains("desktop/entitlements.mac.plist", "com.apple.security.get-task-allow"));

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
