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
//   - SSH key auth set up for root@5.78.46.234
//   - rsync installed locally (default on macOS)

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const yaml = require("js-yaml");

const DIST = path.resolve(__dirname, "..", "dist");
const FEED = path.join(DIST, "latest-mac.yml");
const HOST = "root@5.78.46.234";
const REMOTE = "/var/www/elevate-updates/";

if (!fs.existsSync(DIST)) {
  console.error(`[ship] no dist/ folder at ${DIST} — did the build run?`);
  process.exit(1);
}

if (!fs.existsSync(FEED)) {
  console.error(`[ship] no latest-mac.yml at ${FEED} — did the build run?`);
  process.exit(1);
}

// electron-builder emits latest-mac.yml (the feed file electron-updater polls).
// Ship exactly the files referenced by the feed, plus matching blockmaps when
// present, so stale artifacts in dist/ never leak into the update directory.
const feed = yaml.load(fs.readFileSync(FEED, "utf8"));
const selected = new Set(["latest-mac.yml"]);
for (const file of feed.files || []) {
  selected.add(file.url);
  // The updater uses zip blockmaps on macOS. DMG blockmaps are generated before
  // finalize:mac signs/staples the DMGs, so do not upload stale DMG blockmaps.
  if (file.url.endsWith(".zip")) {
    const blockMap = `${file.url}.blockmap`;
    if (fs.existsSync(path.join(DIST, blockMap))) selected.add(blockMap);
  }
}

const matches = Array.from(selected).filter((name) => fs.existsSync(path.join(DIST, name)));

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

console.log("\n[ship] live at https://api.elevationrealestatehq.com/updates/");
console.log("[ship] running apps poll every ~3min (and on window focus), so it lands within minutes.");

// Cleanup: electron-builder leaves unpacked .app bundles in dist/mac and
// dist/mac-arm64. macOS Spotlight indexes those as standalone "Elevate" apps,
// which then clutter the launcher as ghost duplicates of the real install.
// The shippable artifacts (zip/dmg/yml) are already on Hetzner, so drop the
// unpacked bundles after every successful ship. Keep the dmg/zip as a local
// release archive.
for (const sub of ["mac", "mac-arm64"]) {
  const dir = path.join(DIST, sub);
  if (fs.existsSync(dir)) {
    fs.rmSync(dir, { recursive: true, force: true });
    console.log(`[ship] cleaned unpacked bundle dist/${sub}/ (no Spotlight ghost)`);
  }
}
