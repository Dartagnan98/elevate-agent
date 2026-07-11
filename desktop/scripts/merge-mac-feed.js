#!/usr/bin/env node
// Rebuild latest-mac.yml after separate x64/arm64 electron-builder runs.

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const yaml = require("js-yaml");
const { releaseArtifactNames, resolveReleaseProfile } = require("../src/release-profile");
const { verifySourceReceipt } = require("./candidate-receipt");

const ROOT = path.resolve(__dirname, "..");
const DIST = path.join(ROOT, "dist");
const RELEASE_CHANNEL = (process.env.ELEVATE_RELEASE_CHANNEL || "latest").trim().toLowerCase();
if (!["latest", "beta"].includes(RELEASE_CHANNEL)) {
  throw new Error(`[merge-feed] unsupported release channel: ${RELEASE_CHANNEL}`);
}
const FEED_NAME = `${RELEASE_CHANNEL}-mac.yml`;
const FEED = path.join(DIST, FEED_NAME);
const APP_BUNDLE_NAME = resolveReleaseProfile(RELEASE_CHANNEL).appBundleName;
const { version } = require(path.join(ROOT, "package.json"));

verifySourceReceipt({ channel: RELEASE_CHANNEL, version });

function appVersion(appPath) {
  const result = spawnSync(
    "plutil",
    ["-extract", "CFBundleShortVersionString", "raw", path.join(appPath, "Contents/Info.plist")],
    { encoding: "utf8" },
  );
  if (result.status !== 0) {
    throw new Error(`[merge-feed] could not read app version for ${appPath}`);
  }
  return (result.stdout || "").trim();
}

for (const appPath of [
  path.join(DIST, "mac", APP_BUNDLE_NAME),
  path.join(DIST, "mac-arm64", APP_BUNDLE_NAME),
]) {
  const actual = appVersion(appPath);
  if (actual !== version) {
    throw new Error(`[merge-feed] ${appPath} version ${actual} does not match package ${version}`);
  }
}

function artifact(name) {
  const filePath = path.join(DIST, name);
  if (!fs.existsSync(filePath)) {
    throw new Error(`[merge-feed] missing ${filePath}`);
  }
  const bytes = fs.readFileSync(filePath);
  return {
    url: name,
    sha512: crypto.createHash("sha512").update(bytes).digest("base64"),
    size: bytes.length,
  };
}

const files = releaseArtifactNames(resolveReleaseProfile(RELEASE_CHANNEL), version).map(artifact);

const primary = files[0];
const feed = {
  version,
  files,
  path: primary.url,
  sha512: primary.sha512,
  releaseDate: new Date().toISOString(),
};

fs.writeFileSync(FEED, yaml.dump(feed, { lineWidth: -1, noRefs: true }));
verifySourceReceipt({ channel: RELEASE_CHANNEL, version });
console.log(`[merge-feed] wrote ${path.relative(ROOT, FEED)} with ${files.length} artifact(s)`);
