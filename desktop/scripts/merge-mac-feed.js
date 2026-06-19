#!/usr/bin/env node
// Rebuild latest-mac.yml after separate x64/arm64 electron-builder runs.

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const yaml = require("js-yaml");

const ROOT = path.resolve(__dirname, "..");
const DIST = path.join(ROOT, "dist");
const FEED = path.join(DIST, "latest-mac.yml");
const { version } = require(path.join(ROOT, "package.json"));

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
  path.join(DIST, "mac", "Elevate.app"),
  path.join(DIST, "mac-arm64", "Elevate.app"),
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

const files = [
  artifact(`Elevate-${version}-mac-x64.zip`),
  artifact(`Elevate-${version}-mac-arm64.zip`),
  artifact(`Elevate-${version}-mac-x64.dmg`),
  artifact(`Elevate-${version}-mac-arm64.dmg`),
];

const primary = files[0];
const feed = {
  version,
  files,
  path: primary.url,
  sha512: primary.sha512,
  releaseDate: new Date().toISOString(),
};

fs.writeFileSync(FEED, yaml.dump(feed, { lineWidth: -1, noRefs: true }));
console.log(`[merge-feed] wrote ${path.relative(ROOT, FEED)} with ${files.length} artifact(s)`);
