#!/usr/bin/env node
// Push electron-builder artifacts to the Hetzner ctrl-flow box so
// electron-updater (generic provider) can pull them from
// https://api.elevationrealestatehq.com/updates/
//
// Flow:
//   1. `npm run release:mac` builds + invokes this script
//   2. We rsync the relevant files from ./dist into /var/www/elevate-updates/
//   3. Done. Running apps poll the feed every 2hr (or on next launch).
//
// Requirements:
//   - SSH key auth set up for root@5.78.46.234 (already is — Dartagnan uses it)
//   - rsync installed locally (default on macOS)

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const DIST = path.resolve(__dirname, "..", "dist");
const HOST = "root@5.78.46.234";
const REMOTE = "/var/www/elevate-updates/";

if (!fs.existsSync(DIST)) {
  console.error(`[ship] no dist/ folder at ${DIST} — did the build run?`);
  process.exit(1);
}

// electron-builder emits latest-mac.yml (the feed file electron-updater
// polls), one zip + blockmap per arch, plus the dmgs. Ship the lot.
const PATTERNS = [
  /^latest-mac\.yml$/,
  /^Elevate-.*-mac.*\.zip$/,
  /^Elevate-.*-mac.*\.zip\.blockmap$/,
  /^Elevate-.*\.dmg$/,
  /^Elevate-.*\.dmg\.blockmap$/,
];

const matches = fs
  .readdirSync(DIST)
  .filter((name) => PATTERNS.some((re) => re.test(name)));

if (matches.length === 0) {
  console.error(`[ship] no matching artifacts in ${DIST}`);
  process.exit(1);
}

console.log(`[ship] uploading ${matches.length} files to ${HOST}:${REMOTE}`);
for (const name of matches) {
  const size = (fs.statSync(path.join(DIST, name)).size / (1024 * 1024)).toFixed(1);
  console.log(`  - ${name} (${size} MB)`);
}

// rsync with progress, preserve mtime so cache headers are sensible.
const args = [
  "-avh",
  "--progress",
  ...matches.map((name) => path.join(DIST, name)),
  `${HOST}:${REMOTE}`,
];

const result = spawnSync("rsync", args, { stdio: "inherit" });

if (result.status !== 0) {
  console.error(`[ship] rsync failed with exit ${result.status}`);
  process.exit(result.status || 1);
}

// Fix ownership on the remote so nginx (www-data) can read.
const chown = spawnSync(
  "ssh",
  [HOST, `chown www-data:www-data ${REMOTE}* && ls -lh ${REMOTE}`],
  { stdio: "inherit" },
);

if (chown.status !== 0) {
  console.error("[ship] chown failed — may need to fix permissions manually");
}

console.log("\n[ship] live at https://app.ctrlstrategies.com/updates/");
console.log("[ship] running apps will pick up the update within ~2hr (or on next launch).");
