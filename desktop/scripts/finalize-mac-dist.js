#!/usr/bin/env node
// Finalize macOS distribution artifacts after electron-builder:
//   - sign DMG containers
//   - notarize and staple DMG tickets
//   - refresh latest-mac.yml hashes/sizes after stapling changes DMG bytes

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const yaml = require("js-yaml");

const ROOT = path.resolve(__dirname, "..");
const DIST = path.join(ROOT, "dist");
const FEED = path.join(DIST, "latest-mac.yml");
const packageJson = require(path.join(ROOT, "package.json"));

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    stdio: "inherit",
    ...options,
  });
  if (result.status !== 0) {
    const rendered = [command, ...args].join(" ");
    throw new Error(`${rendered} failed with exit ${result.status}`);
  }
}

function output(command, args) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    encoding: "utf8",
  });
  if (result.status !== 0) return "";
  return result.stdout || "";
}

function resolveIdentity() {
  if (process.env.CODESIGN_IDENTITY) return process.env.CODESIGN_IDENTITY;
  const cscName = (process.env.CSC_NAME || "").trim();
  if (cscName) {
    if (cscName.startsWith("Developer ID Application:")) return cscName;
    return `Developer ID Application: ${cscName}`;
  }

  const identities = output("security", ["find-identity", "-v", "-p", "codesigning"]);
  const match = identities.match(/"([^"]*Developer ID Application:[^"]+)"/);
  if (match) return match[1];
  throw new Error("No Developer ID Application identity found. Set CODESIGN_IDENTITY or CSC_NAME.");
}

function artifactPath(fileName) {
  return path.join(DIST, fileName);
}

function refreshFeedHashes() {
  const feed = yaml.load(fs.readFileSync(FEED, "utf8"));
  for (const file of feed.files || []) {
    const filePath = artifactPath(file.url);
    const bytes = fs.readFileSync(filePath);
    file.sha512 = crypto.createHash("sha512").update(bytes).digest("base64");
    file.size = bytes.length;
    if (feed.path === file.url) {
      feed.sha512 = file.sha512;
    }
  }
  fs.writeFileSync(FEED, yaml.dump(feed, { lineWidth: -1, noRefs: true }));
  console.log(`[finalize] refreshed hashes in ${path.relative(ROOT, FEED)}`);
}

if (!fs.existsSync(FEED)) {
  throw new Error(`[finalize] missing ${FEED}; run electron-builder first`);
}

const identity = resolveIdentity();
const profile = process.env.APPLE_KEYCHAIN_PROFILE || "elevate-notarization";
const version = packageJson.version;
const feed = yaml.load(fs.readFileSync(FEED, "utf8"));
const dmgs = (feed.files || [])
  .map((file) => file.url)
  .filter((name) => name.endsWith(".dmg") && name.includes(`-${version}-`));

if (dmgs.length === 0) {
  throw new Error(`[finalize] no ${version} DMG artifacts listed in latest-mac.yml`);
}

console.log(`[finalize] signing/notarizing ${dmgs.length} DMG artifact(s) as ${identity}`);
for (const dmg of dmgs) {
  const filePath = artifactPath(dmg);
  if (!fs.existsSync(filePath)) {
    throw new Error(`[finalize] missing ${filePath}`);
  }
  run("codesign", ["--force", "--sign", identity, "--timestamp", filePath]);
  run("codesign", ["--verify", "--verbose=2", filePath]);
  run("xcrun", ["notarytool", "submit", filePath, "--keychain-profile", profile, "--wait"]);
  run("xcrun", ["stapler", "staple", filePath]);
  run("xcrun", ["stapler", "validate", filePath]);
  run("spctl", ["-a", "-vv", "--type", "open", "--context", "context:primary-signature", filePath]);
}

refreshFeedHashes();
console.log("[finalize] macOS artifacts are signed, notarized, stapled, and feed-synced");
